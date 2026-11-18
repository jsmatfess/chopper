//! Publication descriptor and name owners; payload/codec/runtime charges are separate.
use super::*;
use std::fmt::Write as _;

pub(super) struct PublicationName {
    value: String,
    _memory: Reservation,
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;
impl PublicationName {
    pub(super) fn as_str(&self) -> &str {
        &self.value
    }
}

pub(super) struct PublicationTask {
    pub(super) chunk: ChargedJson<Chunk>,
    pub(super) completed: Option<Result<CompletedChunk>>,
}
pub(super) struct PublicationBatch {
    pub(super) tasks: Vec<PublicationTask>,
    _memory: Reservation,
}
impl PublicationBatch {
    pub(super) fn new(capacity: usize, mut memory: Reservation) -> Result<Self> {
        let mut tasks = Vec::new();
        memory.reserve_vec(&mut tasks, capacity)?;
        Ok(Self {
            tasks,
            _memory: memory,
        })
    }
    pub(super) fn push(&mut self, chunk: ChargedJson<Chunk>) -> Result<()> {
        ensure!(
            self.tasks.len() < self.tasks.capacity(),
            "publication batch capacity exceeded"
        );
        self.tasks.push(PublicationTask {
            chunk,
            completed: None,
        });
        Ok(())
    }
}

// 180 prefix bytes, separator, part-, maximal u64 index, .csv and .zst.
const NAME_CAPACITY: usize = 180 + 1 + 5 + 20 + 4 + 4;
// column-<usize> and split-<u64> fit on supported 32/64-bit targets.
const LABEL_CAPACITY: usize = 32;

// Bound the descriptive prefix by UTF-8 bytes (also bounding Windows UTF-16
// code units), leaving room for the unique suffix and compression extension.
pub(super) fn output_name(
    index: u64,
    group: &Group,
    job: &Job,
    header: Option<&[String]>,
    mut memory: Reservation,
) -> Result<PublicationName> {
    memory.resize(NAME_CAPACITY + LABEL_CAPACITY)?;
    let mut prefix = String::new();
    prefix.try_reserve_exact(NAME_CAPACITY)?;
    memory.resize(
        prefix
            .capacity()
            .checked_add(LABEL_CAPACITY)
            .context("output name allowance overflow")?,
    )?;
    let mut label = String::new();
    label.try_reserve_exact(LABEL_CAPACITY)?;
    memory.resize(
        prefix
            .capacity()
            .checked_add(label.capacity())
            .context("output name allowance overflow")?,
    )?;
    let mut append = |label: &str| {
        if prefix.len() >= 180 {
            return;
        }
        if !prefix.is_empty() {
            prefix.push('-');
        }
        let start = prefix.len();
        for c in label
            .trim_matches(|c: char| c.is_whitespace() || c == '.')
            .chars()
        {
            let c = if c.is_control() || c.is_whitespace() || "<>:\"/\\|?*".contains(c) {
                '_'
            } else {
                c
            };
            if prefix.len() + c.len_utf8() > 180 {
                break;
            }
            prefix.push(c);
        }
        if prefix.len() == start && prefix.len() + 5 <= 180 {
            prefix.push_str("empty");
        }
    };
    for step in &group.lineage {
        if let Some(values) = step.get("values").and_then(|v| v.as_array()) {
            let operation = step.get("operation").and_then(|v| v.as_u64());
            if let Some(Operation::Partition { columns }) =
                operation.and_then(|i| job.operations.get(i as usize))
            {
                for (column, value) in columns.iter().zip(values) {
                    match column {
                        Column::Name(name) => append(name),
                        Column::Index(i) => {
                            if let Some(name) = header.and_then(|h| h.get(*i)) {
                                append(name);
                            } else {
                                label.clear();
                                write!(&mut label, "column-{}", *i as u128 + 1)?;
                                append(&label);
                            }
                        }
                    }
                    append(value.as_str().unwrap_or_default());
                }
            }
        } else if let Some(name) = step.get("allocation").and_then(|v| v.as_str()) {
            append("allocation");
            append(name);
        } else if let Some(part) = step.get("part").and_then(|v| v.as_u64()) {
            label.clear();
            write!(&mut label, "split-{part}")?;
            append(&label);
        }
    }
    if !prefix.is_empty() {
        prefix.push('-');
    }
    write!(
        &mut prefix,
        "part-{index:08}.csv{}",
        match job.compression {
            Compression::Gzip => ".gz",
            Compression::Zstd => ".zst",
            _ => "",
        }
    )?;
    ensure!(
        prefix.len() <= NAME_CAPACITY && label.len() <= LABEL_CAPACITY,
        "output name exceeds admitted capacity"
    );
    drop(label);
    memory.resize(prefix.capacity())?;
    Ok(PublicationName {
        value: prefix,
        _memory: memory,
    })
}
