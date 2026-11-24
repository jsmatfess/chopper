//! Retained caller configuration capacity and admission for a generated seed.
use super::*;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

/// Immutable configuration retained by a prepared snapshot. Borrow it through
/// Deref/Serialize. An explicit Job clone is caller-owned and has no shared grant.
///
/// ```compile_fail
/// fn grow(mut job: chopper::engine::PreparedJob) {
///     job.input.push_str("unadmitted growth");
/// }
/// ```
pub struct PreparedJob {
    value: Job,
    _memory: Reservation,
}
impl PreparedJob {
    /// Retained configuration capacity charged to the preparation context.
    pub fn reserved_bytes(&self) -> u64 {
        self._memory.bytes()
    }

    pub(super) fn admit(job: Job, mut memory: Reservation) -> Result<Self> {
        let bytes = capacity(&job)?;
        let generated = usize::from(job.random_seed.is_none()) * 64;
        memory.resize(
            bytes
                .checked_add(generated)
                .context("job capacity overflow")?,
        )?;
        let mut owner = Self {
            value: job,
            _memory: memory,
        };
        if owner.value.random_seed.is_none() {
            owner.value.random_seed = Some(generated_seed()?);
            owner._memory.resize(capacity(&owner.value)?)?;
        }
        Ok(owner)
    }
}
impl std::ops::Deref for PreparedJob {
    type Target = Job;
    fn deref(&self) -> &Job {
        &self.value
    }
}
impl std::fmt::Debug for PreparedJob {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.value.fmt(formatter)
    }
}
impl serde::Serialize for PreparedJob {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self.value.serialize(serializer)
    }
}

fn add(total: &mut usize, bytes: usize) -> Result<()> {
    *total = total.checked_add(bytes).context("job capacity overflow")?;
    Ok(())
}
fn vector<T>(total: &mut usize, values: &Vec<T>) -> Result<()> {
    add(
        total,
        values
            .capacity()
            .checked_mul(std::mem::size_of::<T>())
            .context("job capacity overflow")?,
    )
}
fn optional(total: &mut usize, text: &Option<String>) -> Result<()> {
    if let Some(text) = text {
        add(total, text.capacity())?;
    }
    Ok(())
}
fn settings(total: &mut usize, settings: &CsvSettings) -> Result<()> {
    let CsvSettings {
        encoding,
        line_ending,
        headers: _,
        delimiter: _,
        quote: _,
        escape: _,
        bom: _,
        skip_empty_lines: _,
    } = settings;
    add(total, encoding.capacity())?;
    add(total, line_ending.capacity())
}
fn columns(total: &mut usize, values: &Vec<Column>) -> Result<()> {
    vector(total, values)?;
    for value in values {
        if let Column::Name(name) = value {
            add(total, name.capacity())?;
        }
    }
    Ok(())
}

// Exhaustive field/variant matches make schema changes require an ownership audit.
pub(crate) fn capacity(job: &Job) -> Result<usize> {
    let Job {
        input,
        output,
        zip_member,
        input_csv,
        output_csv,
        operations,
        resources,
        random_seed,
        version: _,
        compression: _,
        limits,

        full_shuffle_rng: _,
        full_shuffle_algorithm: _,
    } = job;
    let Limits {
        rows: _,
        bytes: _,
        compressed_bytes: _,
    } = limits;
    let mut bytes = 0;
    add(&mut bytes, input.capacity())?;
    add(&mut bytes, output.capacity())?;
    optional(&mut bytes, zip_member)?;
    optional(&mut bytes, random_seed)?;
    settings(&mut bytes, input_csv)?;
    settings(&mut bytes, output_csv)?;
    let Resources {
        temp_dir,
        memory_mb: _,
        workers: _,
        temp_bytes: _,
        max_files: _,
        max_record_bytes: _,
        grouping: _,
    } = resources;
    optional(&mut bytes, temp_dir)?;
    vector(&mut bytes, operations)?;
    for operation in operations {
        match operation {
            Operation::Calculate { name, expression } => {
                add(&mut bytes, name.capacity())?;
                add(&mut bytes, expression.capacity())?;
            }
            Operation::Partition { columns: values } => columns(&mut bytes, values)?,
            Operation::Assign { groups, strata }
            | Operation::AssignProbabilistic { groups, strata } => {
                vector(&mut bytes, groups)?;
                columns(&mut bytes, strata)?;
                for Allocation { name, percent } in groups {
                    add(&mut bytes, name.capacity())?;
                    add(&mut bytes, percent.capacity())?;
                }
            }
            Operation::Balanced { files: _ }
            | Operation::Interleaved { files: _ }
            | Operation::Shuffle { strategy: _ } => {}
        }
    }
    Ok(bytes)
}
