//! Ordered CSV records with an optional, bounded native hash workspace.
use super::*;
use crate::csv_intake::{Intake, Records as CsvRecords};

pub(super) struct Records<P> {
    // Slots (and every owned string in them) drop before their aggregate grant
    // in input. The input owner also destroys its parser before that grant.
    #[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
    batch: Option<Batch>,
    input: Intake<P>,
    pub execution: ProfileExecution,
}
pub(super) struct Record<'a> {
    pub fields: &'a [String],
    pub hashes: Option<&'a [blake3::Hash]>,
}
impl<P: CsvRecords> Records<P> {
    pub fn new(input: Intake<P>, present: bool, job: &Job, hashes: usize, parallel: bool) -> Self {
        let mut result = Self {
            input,
            #[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
            batch: None,
            execution: ProfileExecution::default(),
        };
        #[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
        if parallel && present {
            if let Some(mut batch) = Batch::new(
                job,
                hashes,
                result.input.owned(),
                result.input.reservation(),
            ) {
                result.input.take_prefetched(&mut batch.slots[0].fields);
                result.execution.hash_workers = batch.pool.current_num_threads();
                result.batch = Some(batch);
            }
        }
        #[cfg(not(all(feature = "experimental-parallel-profile", not(target_os = "wasi"))))]
        let _ = (job, hashes, parallel, present);
        // Mutable only in feature-enabled native builds.
        let _ = &mut result;
        result
    }
    pub fn next<'a>(
        &'a mut self,
        combinations: &[(Vec<usize>, Cardinality)],
        cancel: &AtomicBool,
    ) -> Result<Option<Record<'a>>> {
        ensure!(!cancel.load(Ordering::Relaxed), ProfileCancelled);
        #[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
        if let Some(batch) = &mut self.batch {
            return batch.next(&mut self.input, combinations, cancel, &mut self.execution);
        }
        let _ = combinations;
        if !self.input.next_owned(|| Ok(()))? {
            return Ok(None);
        }
        Ok(Some(Record {
            fields: self.input.owned(),
            hashes: None,
        }))
    }
}
#[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
use parallel::Batch;
#[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
mod parallel {
    use super::*;
    use rayon::prelude::*;
    const MAX_ROWS: usize = 4096;
    const TARGET_BYTES: usize = 2 * 1024 * 1024;
    pub(super) struct Slot {
        pub fields: Vec<String>,
        hashes: Vec<blake3::Hash>,
    }
    pub(super) struct Batch {
        pub slots: Vec<Slot>,
        pub pool: rayon::ThreadPool,
        _metadata: Reservation,
        next: usize,
        count: usize,
        first: bool,
        finished: bool,
    }
    impl Batch {
        pub fn new(
            job: &Job,
            hashes: usize,
            first: &Vec<String>,
            mut metadata: Reservation,
        ) -> Option<Self> {
            let workers = if job.resources.workers == 0 {
                std::thread::available_parallelism()
                    .map_or(1, usize::from)
                    .min(4)
                    .min((metadata.effective_memory_bytes() / (64 * 1024 * 1024)).max(1) as usize)
            } else {
                job.resources.workers
            };
            if workers <= 1 || hashes == 0 {
                return None;
            }
            // Include row descriptors/payload, hashes and slot metadata in the
            // initial size estimate. Later wide rows still require admission.
            let per_row = capacity(first)
                .checked_add(hashes.checked_mul(std::mem::size_of::<blake3::Hash>())?)?
                .checked_add(std::mem::size_of::<Slot>())?;
            let rows = (TARGET_BYTES / per_row.max(1)).clamp(1, MAX_ROWS);
            // A first wide record must not force thousands of tiny pool jobs
            // for an otherwise narrow file. Use serial storage when this
            // estimate cannot supply one minimum-sized task per worker.
            if rows < workers * 16 {
                return None;
            }
            let mut slots = Vec::new();
            metadata.reserve_vec(&mut slots, rows).ok()?;
            for _ in 0..rows {
                let mut values = Vec::new();
                metadata.reserve_vec(&mut values, hashes).ok()?;
                slots.push(Slot {
                    fields: Vec::new(),
                    hashes: values,
                });
            }
            // Thread stacks/runtime bookkeeping use the existing separate runtime
            // headroom. The charged ledger covers all batch payload/hash storage.
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(workers)
                .stack_size(1024 * 1024)
                .thread_name(|i| format!("profile-hash-{i}"))
                .build()
                .ok()?;
            Some(Self {
                slots,
                pool,
                _metadata: metadata,
                next: 0,
                count: 0,
                first: true,
                finished: false,
            })
        }
        #[allow(clippy::too_many_arguments)]
        pub fn next<'a>(
            &'a mut self,
            input: &mut Intake<impl CsvRecords>,
            combinations: &[(Vec<usize>, Cardinality)],
            cancel: &AtomicBool,
            execution: &mut ProfileExecution,
        ) -> Result<Option<Record<'a>>> {
            if self.next == self.count {
                if self.finished {
                    return Ok(None);
                }
                self.next = 0;
                self.count = 0;
                let mut bytes = 0;
                for slot in &mut self.slots {
                    ensure!(!cancel.load(Ordering::Relaxed), ProfileCancelled);
                    if self.first {
                        self.first = false;
                        input.validate_slot(&slot.fields)?;
                    } else if !input.next_slot(&mut slot.fields)? {
                        self.finished = true;
                        break;
                    }
                    // A former wide field may retain capacity when reused for
                    // tiny records. Bound processed batch bytes here; charging
                    // all retained capacities is the reservation's separate job.
                    bytes += slot.fields.len() * std::mem::size_of::<String>()
                        + slot.fields.iter().map(String::len).sum::<usize>();
                    self.count += 1;
                    if bytes >= TARGET_BYTES {
                        break;
                    }
                }
                if self.count == 0 {
                    return Ok(None);
                }
                self.pool.install(|| {
                    self.slots[..self.count]
                        .par_iter_mut()
                        .with_min_len(16)
                        .try_for_each(|slot| -> Result<()> {
                            ensure!(!cancel.load(Ordering::Relaxed), ProfileCancelled);
                            slot.hashes.clear();
                            for field in &slot.fields {
                                slot.hashes.push(blake3::hash(field.as_bytes()));
                            }
                            for (indices, _) in combinations {
                                slot.hashes.push(combination_hash(&slot.fields, indices));
                            }
                            Ok(())
                        })
                })?;
                execution.hash_batches += 1;
                execution.hashed_rows += self.count as u64;
            }
            let slot = &self.slots[self.next];
            self.next += 1;
            Ok(Some(Record {
                fields: &slot.fields,
                hashes: Some(&slot.hashes),
            }))
        }
    }
    fn capacity(fields: &Vec<String>) -> usize {
        fields.capacity() * std::mem::size_of::<String>()
            + fields.iter().map(String::capacity).sum::<usize>()
    }
}
