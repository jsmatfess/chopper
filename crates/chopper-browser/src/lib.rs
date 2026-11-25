//! WASI reactor: the same engine used by the CLI, hosted in a browser worker.
#[cfg(any(test, target_os = "wasi"))]
mod report;
#[cfg(target_os = "wasi")]
mod reactor {
    use chopper::{core::Job, engine, DecodedJob};
    use std::{
        cell::RefCell,
        sync::{atomic::AtomicBool, Arc},
    };
    thread_local! { static PROFILE: RefCell<chopper::profile::ProfileCache> = RefCell::new(chopper::profile::ProfileCache::default()); }

    use chopper::output::{BlockEncoder, BLOCK_BYTES, COMPRESSED_BLOCK_BYTES};

    struct CodecScratch {
        input: Vec<u8>,
        output: Vec<u8>,
        encoder: BlockEncoder,
    }

    thread_local! {
        static CODEC: RefCell<CodecScratch> = RefCell::new(CodecScratch {
            input: vec![0; BLOCK_BYTES],
            output: vec![0; COMPRESSED_BLOCK_BYTES],
            encoder: BlockEncoder::default(),
        });
    }

    #[no_mangle]
    pub extern "C" fn chopper_compression_input_capacity() -> usize {
        BLOCK_BYTES
    }

    #[no_mangle]
    pub extern "C" fn chopper_compression_output_capacity() -> usize {
        COMPRESSED_BLOCK_BYTES
    }

    #[no_mangle]
    pub extern "C" fn chopper_compression_input() -> *mut u8 {
        CODEC.with(|codec| codec.borrow_mut().input.as_mut_ptr())
    }

    #[no_mangle]
    pub extern "C" fn chopper_compression_output() -> *const u8 {
        CODEC.with(|codec| codec.borrow().output.as_ptr())
    }

    #[no_mangle]
    pub extern "C" fn chopper_compression_encode(bytes: usize) -> usize {
        CODEC.with(|codec| {
            let mut codec = codec.borrow_mut();
            let CodecScratch {
                input,
                output,
                encoder,
            } = &mut *codec;
            input
                .get(..bytes)
                .and_then(|input| encoder.encode(input, output).ok())
                .unwrap_or(0)
        })
    }

    #[no_mangle]
    pub extern "C" fn chopper_clear_profile() -> i32 {
        PROFILE.with(|p| p.borrow_mut().clear());
        0
    }
    #[no_mangle]
    pub extern "C" fn chopper_analyze() -> i32 {
        report((|| {
            let decoded = DecodedJob::read_inspection()?;
            let job = decoded.job();
            validate_resources(job)?;
            PROFILE.with(|p| {
                p.borrow_mut().profile(
                    job,
                    Arc::new(AtomicBool::new(false)),
                    Arc::new(|p| println!("{}", serde_json::json!({"progress":p}))),
                )
            })
        })())
    }

    fn report<T: serde::Serialize>(result: anyhow::Result<T>) -> i32 {
        super::report::write_report(&mut std::io::stdout().lock(), result)
    }
    #[cfg(feature = "resource-contract-tests")]
    #[no_mangle]
    pub extern "C" fn chopper_resource_contracts() -> i32 {
        report((|| {
            let mut result = engine::run_resource_contracts()?;
            result["inspection_job_decode"] = DecodedJob::resource_contracts()?;
            Ok(result)
        })())
    }
    #[cfg(feature = "resource-contract-tests")]
    #[no_mangle]
    pub extern "C" fn chopper_test_inspection_reserved_bytes() -> usize {
        DecodedJob::inspection_reserved_bytes().expect("test process ledger")
    }
    #[cfg(feature = "resource-contract-tests")]
    #[no_mangle]
    pub extern "C" fn chopper_test_buffered_job_decode() -> i32 {
        report((|| {
            let file = std::fs::File::open("/job.json")?;
            let reader = std::io::BufReader::with_capacity(8 * 1024, file);
            serde_json::from_reader::<_, Job>(reader)?;
            Ok(())
        })())
    }
    #[no_mangle]
    pub extern "C" fn chopper_defaults() -> i32 {
        report(
            serde_json::to_value(Job {
                resources: chopper::core::Resources::automatic(),
                ..Job::default()
            })
            .map_err(Into::into),
        )
    }
    #[no_mangle]
    pub extern "C" fn chopper_preview() -> i32 {
        report((|| {
            let decoded = DecodedJob::read_inspection()?;
            engine::input_preview(decoded.job())
        })())
    }
    #[no_mangle]
    pub extern "C" fn chopper_formula_scan() -> i32 {
        use std::io::{Read, Write};
        let result = (|| {
            let decoded = DecodedJob::read_inspection()?;
            engine::sample_formula_rows(
                decoded.job(),
                |batch| {
                    let mut stdout = std::io::stdout().lock();
                    serde_json::to_writer(&mut stdout, batch)?;
                    Ok(writeln!(stdout)?)
                },
                || {
                    let mut command = [0_u8; 1];
                    Ok(std::io::stdin().lock().read(&mut command)? == 1)
                },
            )
        })();
        match result {
            Ok(()) => 0,
            Err(error) => report::<()>(Err(error)),
        }
    }
    #[no_mangle]
    pub extern "C" fn chopper_formula_preview() -> i32 {
        report((|| {
            let file = std::fs::File::open("/formula-preview.json")?;
            let size = file.metadata()?.len();
            engine::formula_preview_json(file, size)
        })())
    }
    #[no_mangle]
    pub extern "C" fn chopper_sniff() -> i32 {
        report((|| {
            let decoded = DecodedJob::read_inspection()?;
            engine::sniff_csv(decoded.job())
        })())
    }
    #[no_mangle]
    pub extern "C" fn chopper_run() -> i32 {
        #[derive(serde::Serialize)]
        struct RunReport {
            analysis: engine::Analysis,
            complete: bool,
        }

        report((|| {
            let job = DecodedJob::read_hosted()?;
            validate_resources(job.job())?;
            fn emit(value: impl serde::Serialize, prefix: &str) -> bool {
                // Fixed stack serialization; no growing JSON/value allocation.
                struct Buffer {
                    bytes: [u8; 1024],
                    len: usize,
                }
                impl std::io::Write for Buffer {
                    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
                        if bytes.len() > self.bytes.len() - self.len {
                            return Err(std::io::ErrorKind::OutOfMemory.into());
                        }
                        self.bytes[self.len..self.len + bytes.len()].copy_from_slice(bytes);
                        self.len += bytes.len();
                        Ok(bytes.len())
                    }
                    fn flush(&mut self) -> std::io::Result<()> {
                        Ok(())
                    }
                }
                use std::io::Write;
                let mut buffer = Buffer {
                    bytes: [0; 1024],
                    len: 0,
                };
                if buffer.write_all(prefix.as_bytes()).is_err()
                    || serde_json::to_writer(&mut buffer, &value).is_err()
                    || buffer.write_all(b"}\n").is_err()
                {
                    return false;
                }
                std::io::stdout()
                    .lock()
                    .write_all(&buffer.bytes[..buffer.len])
                    .is_ok()
            }
            let mut observe = |snapshot| emit(snapshot, "{\"observation\":");
            let enabled = std::fs::File::open("/observe")
                .ok()
                .is_some_and(|mut file| {
                    let mut byte = [0];
                    std::io::Read::read(&mut file, &mut byte).ok() == Some(1) && byte[0] == 1
                });
            let cancel = Arc::new(AtomicBool::new(false));
            let notify: chopper::storage::Notify =
                Arc::new(|p| println!("{}", serde_json::json!({"progress":p})));
            let hint = std::fs::File::open("/auto-observations.json")
                .ok()
                .and_then(|file| {
                    use std::io::Read;
                    serde_json::from_reader(file.take(4096)).ok()
                });
            let preview = std::fs::File::open("/preview-observations.json")
                .ok()
                .and_then(|file| {
                    use std::io::Read;
                    serde_json::from_reader(file.take(256)).ok()
                });
            let observers = enabled.then(|| {
                let snapshot: chopper::observation::Sink<'_> = &mut observe;
                let physical: chopper::observation::physical::Sink =
                    Arc::new(|fact| emit(fact, "{\"physical\":"));
                (snapshot, physical)
            });
            let analysis = engine::run_decoded_hosted_with_preview(
                job, cancel, notify, hint, preview, observers,
            )?;
            Ok(RunReport {
                analysis,
                complete: true,
            })
        })())
    }
    fn validate_resources(job: &Job) -> anyhow::Result<()> {
        anyhow::ensure!(
            job.resources.memory_mb.as_mib().is_none_or(|mb| mb <= 2048),
            "browser working memory is limited to 2048 MiB"
        );
        Ok(())
    }
}
