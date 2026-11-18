use super::*;
use std::cell::Cell;
const EVENTS: usize = 2_000_000;
#[repr(C)]
#[derive(Clone, Copy, Default)]
struct Event {
    old: usize,
    new: usize,
    old_size: usize,
    new_size: usize,
    align: usize,
    kind: usize,
    phase: usize,
}
thread_local! {
 static BASE: Cell<*mut Event> = const { Cell::new(std::ptr::null_mut()) };
 static LEN: Cell<usize> = const { Cell::new(0) };
 static TAG: Cell<usize> = const { Cell::new(0) };
 static OVERFLOW: Cell<bool> = const { Cell::new(false) };
}
pub(in crate::engine::snapshots) fn set_phase(tag: usize) {
    let _ = TAG.try_with(|x| x.set(tag));
}
pub(in crate::engine::snapshots) struct Phase(usize);
impl Phase {
    pub(in crate::engine::snapshots) fn enter(tag: usize) -> Self {
        Self(TAG.with(|x| x.replace(tag)))
    }
}
impl Drop for Phase {
    fn drop(&mut self) {
        set_phase(self.0);
    }
}
pub(super) fn event(
    old: usize,
    new: usize,
    old_size: usize,
    new_size: usize,
    align: usize,
    kind: usize,
) {
    let _ = BASE.try_with(|base| {
        let ptr = base.get();
        if !ptr.is_null() {
            let _ = LEN.try_with(|len| {
                let n = len.get();
                if n < EVENTS {
                    let phase = TAG.try_with(Cell::get).unwrap_or(0);
                    // SAFETY: this thread exclusively owns the preallocated EVENTS-element capture buffer.
                    unsafe {
                        ptr.add(n).write(Event {
                            old,
                            new,
                            old_size,
                            new_size,
                            align,
                            kind,
                            phase,
                        });
                    }
                    len.set(n + 1);
                } else {
                    let _ = OVERFLOW.try_with(|x| x.set(true));
                }
            });
        }
    });
}
struct Capture {
    events: Vec<Event>,
}
impl Capture {
    fn start() -> Self {
        let mut events = vec![Event::default(); EVENTS];
        LEN.with(|x| x.set(0));
        OVERFLOW.with(|x| x.set(false));
        BASE.with(|x| x.set(events.as_mut_ptr()));
        Self { events }
    }
    fn finish(mut self, path: &Path) -> Result<()> {
        BASE.with(|x| x.set(std::ptr::null_mut()));
        self.events.truncate(LEN.with(Cell::get));
        // SAFETY: Event has seven initialized usize fields and no padding on this native target.
        let bytes = unsafe {
            std::slice::from_raw_parts(
                self.events.as_ptr().cast::<u8>(),
                self.events.len() * std::mem::size_of::<Event>(),
            )
        };
        std::fs::write(path, bytes)?;
        ensure!(!OVERFLOW.with(Cell::get), "allocation event ring overflow");
        Ok(())
    }
}
impl Drop for Capture {
    fn drop(&mut self) {
        let _ = BASE.try_with(|x| x.set(std::ptr::null_mut()));
    }
}
#[test]
#[ignore = "fixed R11 isolated census; explicitly invoked once"]
fn fixed_arrow_allocation_census() -> Result<()> {
    let output = PathBuf::from(
        std::env::var_os("CHOPPER_E3_GATE_EVIDENCE")
            .context("census evidence directory required")?,
    );
    std::fs::create_dir_all(&output)?;
    for (name, c, n) in [
        ("A", 0, 0),
        ("B", 1, 2049),
        ("C", 4, 2049),
        ("D", 33, 2049),
        ("E", 1024, 2),
        ("F", 33, 21),
        ("G", 1, 8192),
    ] {
        let case = output.join(name);
        std::fs::create_dir(&case)?;
        let text = (0..n)
            .map(|r| {
                (0..c)
                    .map(|i| {
                        if name == "F" {
                            if i == 0 {
                                "x".repeat(if r == 20 { 2096096 } else { 1usize << r })
                            } else {
                                String::new()
                            }
                        } else {
                            "x".into()
                        }
                    })
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        let fixture_bytes = serde_json::to_vec(&text)?;
        std::fs::write(case.join("fixture.json"), &fixture_bytes)?;
        std::fs::write(
            case.join("fixture.blake3"),
            blake3::hash(&fixture_bytes).to_hex().as_bytes(),
        )?;
        let mut records = Vec::new();
        for fields in &text {
            let mut row = chopper_core::csv::CompactRecord::default();
            row.set_text_fields_reserved(fields.iter().map(String::as_str), 2097152, &mut |_| {
                Ok(())
            })?;
            records.push(row);
        }
        let (_root, mut job) = fixture(b"id\n")?;
        job.resources.memory_mb = 64;
        job.resources.max_record_bytes = 2097152;
        let pool = Arc::new(crate::resources::MemoryPool::new(128 * 1024 * 1024));
        let ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let baseline = pool.usage().reserved_bytes;
        let path = case.join("artifact.arrow");
        let limited = LimitedWriter {
            file: File::create(&path)?,
            bytes: 0,
            limit: 64 * 1024 * 1024,
        };
        let mut manifest = sample_manifest();
        manifest.columns = c;
        manifest.records = n as u64;
        let capture = Capture::start();
        let result = (|| -> Result<()> {
            set_phase(1);
            let mut writer = ipc::Writer::new(limited, c, &ctx)?;
            for row in &records {
                set_phase(2);
                writer.row(row)?;
                if name == "G" {
                    writer.census_flush()?;
                }
            }
            set_phase(4);
            writer.finish()?;
            set_phase(6);
            let mut reader =
                ipc::Reader::new(ctx.artifact_reader(File::open(&path)?), &manifest, &ctx)?;
            for expected in &text {
                let fields = reader.next_fields()?.context("early EOF")?;
                ensure!(
                    fields.eq(expected.iter().map(String::as_str)),
                    "IPC exact text changed"
                );
            }
            ensure!(reader.next_fields()?.is_none(), "missing EOF");
            set_phase(11);
            drop(reader);
            Ok(())
        })();
        capture.finish(&case.join("events.bin"))?;
        result?;
        ensure!(
            pool.usage().reserved_bytes == baseline,
            "census owner release mismatch"
        );
        if name == "G" {
            let sink = LimitedWriter {
                file: File::create(case.join("gate.arrow"))?,
                bytes: 0,
                limit: 64 * 1024 * 1024,
            };
            let capture = Capture::start();
            let result = (|| -> Result<()> {
                set_phase(1);
                let mut writer = ipc::Writer::new(sink, 1, &ctx)?;
                writer.census_catalog_at_limit();
                writer.row(&records[0])?;
                let error = writer.census_flush().expect_err("block8193 must reject");
                ensure!(
                    error.to_string().contains("bounded block catalog"),
                    "wrong gate rejection"
                );
                drop(error);
                set_phase(5);
                drop(writer);
                Ok(())
            })();
            capture.finish(&case.join("gate-events.bin"))?;
            result?;
            ensure!(
                pool.usage().reserved_bytes == baseline,
                "gate owner release mismatch"
            );
        }
        eprintln!("R11 case {name}: exact text/EOF/drop passed");
    }
    Ok(())
}
