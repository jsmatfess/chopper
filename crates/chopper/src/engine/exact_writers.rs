//! Count immutable retained strata, then interleave their original quota streams.
use super::*;
use std::collections::BTreeMap;

struct Stratum {
    count: u64,
    remaining: u64,
    quota: Vec<u64>,
    random: Random,
}
const NODE_BYTES: usize = 16
    * (std::mem::size_of::<Vec<u8>>()
        + std::mem::size_of::<Stratum>()
        + std::mem::size_of::<usize>())
    + 4 * std::mem::size_of::<usize>();

struct Catalog {
    entries: BTreeMap<Vec<u8>, Stratum>,
    columns: Vec<usize>,
    key: keys::TupleBuffer,
    // Nodes, key/column/quota capacities drop before the aggregate grant.
    memory: Reservation,
}

pub(super) struct Prepared<'a> {
    catalog: Catalog,
    writers: direct::Writers<'a>,
    rows: u64,
    ctx: &'a Context,
}

fn eligible(job: &Job, ctx: &Context) -> bool {
    (ctx.auto_retained_exact
        || (cfg!(all(
            feature = "experimental-retained-exact-writers",
            not(target_os = "wasi")
        )) && matches!(job.operations.as_slice(), [Operation::Assign { groups, strata }]
        if !strata.is_empty() && configured_writer_capacity(job).is_some_and(|cap| groups.len() <= cap))))
        && ctx.direct_terminal_output
        && !ctx.physical_enabled()
        && job.output_csv.encoding.eq_ignore_ascii_case("utf-8")
}

pub(super) fn prepare<'a>(
    data: &Dataset,
    job: &'a Job,
    analysis: &Analysis,
    ctx: &'a Context,
) -> Result<Option<Prepared<'a>>> {
    if !eligible(job, ctx) || data.groups != 1 {
        return Ok(None);
    }
    ctx.event("Preparing retained exact writers", 0)?;
    let attempt = (|| {
        let parent = data
            .groups()?
            .next()
            .transpose()?
            .context("missing exact allocation parent")?;
        exact_plan::Proposal::new((), &parent).prepare(
            ctx,
            |(), parent| Prepared::new(data, parent, job, analysis, ctx),
            |error| {
                error
                    .downcast_ref::<crate::resources::MemoryAdmission>()
                    .is_some()
            },
        )
    })();
    let fallback = || {
        // Parent-reader setup can deny before the Proposal has a parent to borrow.
        // Both setup paths drop their owners before this cancellation/cleanup recheck.
        ctx.check()?;
        ctx.retained_exact_fallback();
        ctx.event(
            "Using original exact allocation after preparation denial",
            0,
        )?;
        Ok(None)
    };
    match attempt {
        Ok(exact_plan::Attempt::Prepared(prepared)) => Ok(Some(prepared)),
        Ok(exact_plan::Attempt::Retry(error)) => {
            drop(error);
            fallback()
        }
        Err(error)
            if error
                .downcast_ref::<crate::resources::MemoryAdmission>()
                .is_some() =>
        {
            drop(error);
            fallback()
        }
        Err(error) => Err(error),
    }
}

impl<'a> Prepared<'a> {
    fn new(
        data: &Dataset,
        parent: &Group,
        job: &'a Job,
        analysis: &Analysis,
        ctx: &'a Context,
    ) -> Result<Self> {
        let Operation::Assign { groups, strata } = &job.operations[0] else {
            unreachable!()
        };
        let mut catalog = Catalog {
            entries: BTreeMap::new(),
            columns: Vec::new(),
            key: keys::TupleBuffer::new(Reservation::new(ctx)),
            memory: Reservation::new(ctx),
        };
        catalog
            .memory
            .reserve_vec(&mut catalog.columns, strata.len())?;
        for column in strata {
            catalog.columns.push(resolve_column(
                column,
                analysis.header.as_deref(),
                analysis.columns,
            )?);
        }
        let domain = random::json_domain(job.random_seed.as_deref().unwrap(), 0, &parent.lineage)?;
        let mut hex = [0u8; 64];
        for (index, byte) in domain.iter().enumerate() {
            hex[2 * index] = b"0123456789abcdef"[(byte >> 4) as usize];
            hex[2 * index + 1] = b"0123456789abcdef"[(byte & 15) as usize];
        }
        let hex = std::str::from_utf8(&hex)?;
        let mut rows = 0u64;
        for row in data.packed_rows(parent, ctx.max_record)? {
            ctx.check()?;
            let row = row?;
            let fields = row.fields();
            catalog.key.replace(fields.clone(), &catalog.columns)?;
            if let Some(state) = catalog.entries.get_mut(catalog.key.bytes()) {
                state.count = state
                    .count
                    .checked_add(1)
                    .context("stratum count overflow")?;
            } else {
                catalog.memory.resize(
                    (catalog.memory.bytes() as usize)
                        .checked_add(NODE_BYTES)
                        .context("exact catalog capacity overflow")?,
                )?;
                let mut key = Vec::new();
                catalog
                    .memory
                    .reserve_vec(&mut key, catalog.key.bytes().len())?;
                key.extend_from_slice(catalog.key.bytes());
                let stratum = group_metadata::ClonedGroup::child(
                    parent,
                    &child_metadata::Entry::values(0, fields, &catalog.columns),
                    ctx,
                    |lineage| Group {
                        offset: 0,
                        rows: 0,
                        lineage,
                        exact: false,
                    },
                )?;
                let seed = random::json_domain(hex, 0, &stratum.group.lineage)?;
                catalog.entries.insert(
                    key,
                    Stratum {
                        count: 1,
                        remaining: 0,
                        quota: Vec::new(),
                        random: Random::new(seed),
                    },
                );
            }
            rows = rows.checked_add(1).context("row count overflow")?;
        }
        ensure!(rows == parent.rows, "retained allocation count changed");
        let mut scratch = AssignmentScratch::new(groups, false, Reservation::new(ctx))?;
        for state in catalog.entries.values_mut() {
            scratch.reset_quota(state.count);
            catalog.memory.reserve_vec(&mut state.quota, groups.len())?;
            state.quota.extend_from_slice(&scratch.quota);
            state.remaining = state.count;
        }
        drop(scratch);
        let mut writers = direct::Writers::new(job, ctx, groups.len())?;
        for allocation in groups {
            let group = group_metadata::ClonedGroup::child(
                parent,
                &child_metadata::Entry::allocation(0, &allocation.name),
                ctx,
                |lineage| Group {
                    offset: 0,
                    rows: 0,
                    lineage,
                    exact: false,
                },
            )?;
            writers.push(analysis.header.as_ref(), group)?;
        }
        Ok(Self {
            catalog,
            writers,
            rows,
            ctx,
        })
    }

    pub(super) fn emit(
        mut self,
        data: &Dataset,
        seed: output::DirectPublication,
    ) -> Result<(output::DirectPublication, u64, u64, StageStats)> {
        let parent = data
            .groups()?
            .next()
            .transpose()?
            .context("missing exact allocation parent")?;
        let mut rows = 0u64;
        for row in data.packed_rows(&parent, self.ctx.max_record)? {
            self.ctx.check()?;
            let row = row?;
            let fields = row.fields();
            self.catalog
                .key
                .replace(fields.clone(), &self.catalog.columns)?;
            let state = self
                .catalog
                .entries
                .get_mut(self.catalog.key.bytes())
                .context("retained stratum changed")?;
            ensure!(state.remaining > 0, "retained stratum count changed");
            let mut draw = state.random.below(state.remaining);
            let index = state
                .quota
                .iter()
                .position(|quota| {
                    if draw < *quota {
                        true
                    } else {
                        draw -= *quota;
                        false
                    }
                })
                .context("invalid exact allocation quota")?;
            state.quota[index] -= 1;
            state.remaining -= 1;
            self.writers.row(index, rows, fields)?;
            rows += 1;
        }
        ensure!(
            rows == self.rows
                && self
                    .catalog
                    .entries
                    .values()
                    .all(|state| state.remaining == 0 && state.quota.iter().all(|n| *n == 0)),
            "retained allocation count changed"
        );
        let stats = self.writers.statistics();
        let count = self.writers.len();
        drop(self.catalog);
        let (publication, files, bytes) = self.writers.finish_in_order(Some(seed), 0..count)?;
        Ok((publication, files, bytes, stats))
    }
}

#[cfg(all(
    test,
    feature = "experimental-retained-exact-writers",
    not(target_os = "wasi")
))]
mod tests {
    use super::*;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Mutex,
    };

    fn fixture(
        notify: Notify,
    ) -> Result<(
        tempfile::TempDir,
        Job,
        Context,
        Ingested,
        Arc<crate::resources::MemoryPool>,
    )> {
        let dir = tempfile::tempdir()?;
        std::fs::create_dir(dir.path().join("temp"))?;
        let job = Job {
            input: dir.path().join("input.csv").to_string_lossy().into(),
            output: dir.path().join("out").to_string_lossy().into(),
            random_seed: Some("retained-exact-test".into()),
            operations: vec![Operation::Assign {
                groups: vec![
                    Allocation {
                        name: "a".into(),
                        percent: "50".into(),
                    },
                    Allocation {
                        name: "b".into(),
                        percent: "50".into(),
                    },
                ],
                strata: vec![Column::Index(1)],
            }],
            resources: chopper_core::Resources {
                memory_mb: 32.into(),
                max_record_bytes: 64 * 1024,
                workers: 1,
                temp_dir: Some(dir.path().join("temp").to_string_lossy().into()),
                ..Default::default()
            },
            ..Default::default()
        };
        std::fs::write(&job.input, b"id,key\n0,k0\n1,k1\n2,k0\n3,k1\n")?;
        let pool = Arc::new(crate::resources::MemoryPool::new(2 * 1024 * 1024));
        let mut ctx = Context::with_memory_pool(
            &job.resources,
            Arc::new(AtomicBool::new(false)),
            notify,
            pool.clone(),
        )?;
        ctx.direct_terminal_output = true;
        let ingested = ingest_options(
            &mut File::open(&job.input)?,
            &job,
            &ctx,
            false,
            false,
            false,
        )?;
        Ok((dir, job, ctx, ingested, pool))
    }

    #[test]
    fn setup_reader_denial_releases_before_fallback_and_keeps_initial_writer() -> Result<()> {
        let owner = Arc::new(Mutex::new(None::<Reservation>));
        let released = owner.clone();
        let fallback = Arc::new(AtomicUsize::new(0));
        let watched = fallback.clone();
        let (_dir, job, ctx, ingested, pool) = fixture(Arc::new(move |p| {
            if p.phase == "Using original exact allocation after preparation denial" {
                drop(released.lock().unwrap().take());
                watched.fetch_add(1, Ordering::SeqCst);
            }
        }))?;
        let before = pool.usage().reserved_bytes;
        let writer =
            output::PlanWriter::direct_grouped(&job, ingested.analysis.header.as_ref(), &ctx)?;
        let mut held = Reservation::new(&ctx);
        held.resize((pool.usage().limit_bytes - pool.usage().reserved_bytes) as usize)?;
        *owner.lock().unwrap() = Some(held);
        assert!(prepare(&ingested.dataset, &job, &ingested.analysis, &ctx)?.is_none());
        assert_eq!(fallback.load(Ordering::SeqCst), 1);
        assert_eq!(ctx.completed_measurements().retained_exact_fallbacks, 1);
        assert!(owner.lock().unwrap().is_none());
        assert_eq!(writer.files(), 0);
        let (seed, files, bytes) = writer.finish_direct()?;
        assert_eq!((files, bytes), (0, 0));
        drop(seed);
        assert_eq!(pool.usage().reserved_bytes, before);
        drop(ingested);
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn prepared_emission_denial_drops_every_tentative_owner_without_retry() -> Result<()> {
        let fallback = Arc::new(AtomicUsize::new(0));
        let watched = fallback.clone();
        let (_dir, job, ctx, ingested, pool) = fixture(Arc::new(move |p| {
            if p.phase == "Using original exact allocation after preparation denial" {
                watched.fetch_add(1, Ordering::SeqCst);
            }
        }))?;
        let before = pool.usage().reserved_bytes;
        let writer =
            output::PlanWriter::direct_grouped(&job, ingested.analysis.header.as_ref(), &ctx)?;
        let prepared = prepare(&ingested.dataset, &job, &ingested.analysis, &ctx)?
            .context("expected prepared writers")?;
        let (seed, _, _) = writer.finish_direct()?;
        let mut held = Reservation::new(&ctx);
        held.resize((pool.usage().limit_bytes - pool.usage().reserved_bytes) as usize)?;
        let result = prepared.emit(&ingested.dataset, seed);
        assert!(result.is_err());
        drop(result);
        assert_eq!(fallback.load(Ordering::SeqCst), 0);
        assert_eq!(ctx.completed_measurements().retained_exact_fallbacks, 0);
        assert!(!std::path::Path::new(&job.output).exists());
        assert_eq!(pool.usage().reserved_bytes, before + held.bytes());
        drop(held);
        drop(ingested);
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }
}
