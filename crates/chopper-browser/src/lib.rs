//! WASI reactor: the same engine used by the CLI, hosted in a browser worker.
#[cfg(target_os = "wasi")]
mod reactor {
    use chopper::{core::Job, engine};
    use std::{
        cell::RefCell,
        sync::{atomic::AtomicBool, Arc},
    };
    thread_local! { static PROFILE: RefCell<chopper::profile::ProfileCache> = RefCell::new(chopper::profile::ProfileCache::default()); }

    #[no_mangle]
    pub extern "C" fn chopper_clear_profile() -> i32 {
        PROFILE.with(|p| p.borrow_mut().clear());
        0
    }
    #[no_mangle]
    pub extern "C" fn chopper_analyze() -> i32 {
        report((|| {
            let job: Job = serde_json::from_reader(std::fs::File::open("/job.json")?)?;
            validate_resources(&job)?;
            PROFILE.with(|p| {
                Ok(serde_json::to_value(p.borrow_mut().profile(
                    &job,
                    Arc::new(AtomicBool::new(false)),
                    Arc::new(|p| println!("{}", serde_json::json!({"progress":p}))),
                )?)?)
            })
        })())
    }

    fn report<T: serde::Serialize>(result: anyhow::Result<T>) -> i32 {
        match result {
            Ok(value) => {
                use std::io::Write;
                let mut stdout = std::io::stdout().lock();
                if serde_json::to_writer(&mut stdout, &value).is_err() || writeln!(stdout).is_err()
                {
                    return 1;
                }
                0
            }
            Err(error) => {
                println!("{}", serde_json::json!({"error":format!("{error:#}")}));
                1
            }
        }
    }
    #[cfg(feature = "resource-contract-tests")]
    #[no_mangle]
    pub extern "C" fn chopper_resource_contracts() -> i32 {
        report(engine::run_resource_contracts())
    }
    #[no_mangle]
    pub extern "C" fn chopper_defaults() -> i32 {
        report(serde_json::to_value(Job::default()).map_err(Into::into))
    }
    #[no_mangle]
    pub extern "C" fn chopper_columns() -> i32 {
        report((|| {
            let job: Job = serde_json::from_reader(std::fs::File::open("/job.json")?)?;
            engine::input_columns(&job)
        })())
    }
    #[no_mangle]
    pub extern "C" fn chopper_preview() -> i32 {
        report((|| {
            let job: Job = serde_json::from_reader(std::fs::File::open("/job.json")?)?;
            engine::input_preview(&job)
        })())
    }
    #[no_mangle]
    pub extern "C" fn chopper_sniff() -> i32 {
        report((|| {
            let job: Job = serde_json::from_reader(std::fs::File::open("/job.json")?)?;
            engine::sniff_csv(&job)
        })())
    }
    #[no_mangle]
    pub extern "C" fn chopper_run() -> i32 {
        report((|| {
            let job: Job = serde_json::from_reader(std::fs::File::open("/job.json")?)?;
            validate_resources(&job)?;
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
            let analysis = if enabled && !job.operations.is_empty() {
                engine::run_with_observations(
                    job,
                    cancel,
                    notify,
                    Arc::new(|fact| emit(fact, "{\"physical\":")),
                )?
            } else if enabled {
                engine::run_observed_with_physical(
                    job,
                    cancel,
                    notify,
                    &mut observe,
                    Arc::new(|fact| emit(fact, "{\"physical\":")),
                )?
            } else {
                engine::run(job, cancel, notify)?
            };
            Ok(serde_json::json!({"analysis":analysis,"complete":true}))
        })())
    }
    fn validate_resources(job: &Job) -> anyhow::Result<()> {
        anyhow::ensure!(
            job.resources.memory_mb.as_mib().is_none_or(|mb| mb <= 2048),
            "browser working memory is limited to 2048 MiB"
        );
        anyhow::ensure!(
            job.resources.workers <= 1,
            "browser engine currently uses one processing worker; select 0 or 1"
        );
        Ok(())
    }
}
