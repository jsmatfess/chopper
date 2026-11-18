//! Fixed-schema child entries borrow source values until construction admission.
use super::*;
use serde::ser::SerializeSeq;

// Field order must match serde_json::Value's canonical BTreeMap order: the
// borrowed form also feeds seeded-v1 domains without constructing a JSON tree.
#[derive(Serialize)]
#[serde(untagged)]
pub(super) enum Entry<'a> {
    Part {
        operation: usize,
        part: u64,
    },
    Allocation {
        allocation: &'a str,
        operation: usize,
    },
    Values {
        operation: usize,
        values: SelectedValues<'a>,
    },
    #[cfg(feature = "experimental-constant-partition")]
    References {
        operation: usize,
        values: &'a [&'a str],
    },
}
pub(super) struct SelectedValues<'a> {
    fields: FieldViews<'a>,
    columns: Option<&'a [usize]>,
}
impl SelectedValues<'_> {
    fn len(&self) -> usize {
        self.columns
            .map_or_else(|| self.fields.len(), <[usize]>::len)
    }
    fn iter(&self) -> impl Iterator<Item = Result<&str>> {
        (0..self.len()).scan(self.fields.clone(), |fields, index| {
            Some(
                match self.columns {
                    Some(columns) => fields.clone().nth(columns[index]),
                    None => fields.next(),
                }
                .context("invalid child lineage column"),
            )
        })
    }
}
impl Serialize for SelectedValues<'_> {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        let mut seq = serializer.serialize_seq(Some(self.len()))?;
        for value in self.iter() {
            let value = value.map_err(serde::ser::Error::custom)?;
            seq.serialize_element(value)?;
        }
        seq.end()
    }
}
impl<'a> Entry<'a> {
    pub(super) fn part(operation: usize, part: u64) -> Self {
        Self::Part { operation, part }
    }
    pub(super) fn allocation(operation: usize, allocation: &'a str) -> Self {
        Self::Allocation {
            allocation,
            operation,
        }
    }
    pub(super) fn values(operation: usize, fields: FieldViews<'a>, columns: &'a [usize]) -> Self {
        Self::Values {
            operation,
            values: SelectedValues {
                fields,
                columns: Some(columns),
            },
        }
    }
    #[cfg(feature = "experimental-streaming-chain")]
    pub(super) fn all_values(operation: usize, fields: FieldViews<'a>) -> Self {
        Self::Values {
            operation,
            values: SelectedValues {
                fields,
                columns: None,
            },
        }
    }
    fn allowance(&self) -> Result<usize> {
        let (keys, payload) = match self {
            Self::Part { .. } => ("operation".len() + "part".len(), 0),
            Self::Allocation { allocation, .. } => {
                ("allocation".len() + "operation".len(), allocation.len())
            }
            Self::Values { values, .. } => {
                let mut bytes = values
                    .len()
                    .checked_mul(std::mem::size_of::<serde_json::Value>())
                    .context("child values capacity overflow")?;
                for value in values.iter() {
                    bytes = bytes
                        .checked_add(value?.len())
                        .context("child values capacity overflow")?;
                }
                ("operation".len() + "values".len(), bytes)
            }
            #[cfg(feature = "experimental-constant-partition")]
            Self::References { values, .. } => {
                let bytes = values
                    .len()
                    .checked_mul(std::mem::size_of::<serde_json::Value>())
                    .context("child values capacity overflow")?;
                let bytes = values.iter().try_fold(bytes, |bytes, value| {
                    bytes
                        .checked_add(value.len())
                        .context("child values capacity overflow")
                })?;
                ("operation".len() + "values".len(), bytes)
            }
        };
        (2 * json_map_entry_allowance())
            .checked_add(keys)
            .and_then(|n| n.checked_add(payload))
            .context("child entry capacity overflow")
    }
}

#[cfg(feature = "experimental-consecutive-partitions")]
pub(super) fn append(
    parent: &mut Group,
    entry: &Entry<'_>,
    ctx: &Context,
    memory: &mut Reservation,
) -> Result<()> {
    ctx.check()?;
    validate_lineage(&Child { parent, entry }, ctx)?;
    let retained = parent.json_capacity()?;
    memory.resize(
        retained
            .checked_add(entry.allowance()?)
            .context("child growth capacity overflow")?,
    )?;
    let length = parent
        .lineage
        .len()
        .checked_add(1)
        .context("child lineage length overflow")?;
    memory.reserve_vec(&mut parent.lineage, length)?;
    parent.lineage.push(serde_json::to_value(entry)?);
    let actual = parent.json_capacity()?;
    ensure!(
        actual <= memory.bytes() as usize,
        "child growth exceeds construction allowance"
    );
    memory.resize(actual)?;
    Ok(())
}

struct Child<'a, 'b> {
    parent: &'a Group,
    entry: &'a Entry<'b>,
}
impl Serialize for Child<'_, '_> {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        let mut seq = serializer.serialize_seq(Some(self.parent.lineage.len() + 1))?;
        for value in &self.parent.lineage {
            seq.serialize_element(value)?;
        }
        seq.serialize_element(self.entry)?;
        seq.end()
    }
}

pub(super) fn domain(
    parent: &Group,
    entry: &Entry<'_>,
    seed: &str,
    step: usize,
    ctx: &Context,
) -> Result<[u8; 32]> {
    ctx.check()?;
    let child = Child { parent, entry };
    validate_lineage(&child, ctx)?;
    Ok(random::json_domain(seed, step as u64, &child)?)
}

pub(super) fn build(
    parent: &Group,
    entry: &Entry<'_>,
    ctx: &Context,
    mut memory: Reservation,
) -> Result<(Vec<serde_json::Value>, Reservation)> {
    ctx.check()?;
    validate_lineage(&Child { parent, entry }, ctx)?;
    let width = std::mem::size_of::<serde_json::Value>();
    let length = parent
        .lineage
        .len()
        .checked_add(1)
        .context("child lineage length overflow")?;
    let descriptors = length
        .checked_mul(width)
        .context("child lineage capacity overflow")?;
    let parent_descriptors = parent
        .lineage
        .capacity()
        .checked_mul(width)
        .context("child lineage capacity overflow")?;
    let payload = parent
        .json_capacity()?
        .checked_sub(parent_descriptors)
        .context("invalid parent lineage capacity")?;
    let non_vector = payload
        .checked_add(entry.allowance()?)
        .context("child lineage capacity overflow")?;
    let allowance = non_vector
        .checked_add(descriptors)
        .context("child lineage capacity overflow")?;
    memory.resize(allowance)?;
    let mut values = Vec::new();
    values.try_reserve_exact(length)?;
    let allowance = non_vector
        .checked_add(
            values
                .capacity()
                .checked_mul(width)
                .context("child lineage capacity overflow")?,
        )
        .context("child lineage capacity overflow")?;
    memory.resize(allowance)?;
    values.extend(parent.lineage.iter().cloned());
    values.push(serde_json::to_value(entry)?);
    validate_lineage(&values, ctx)?;
    let retained = values.json_capacity()?;
    ensure!(
        retained <= allowance,
        "child lineage exceeds construction allowance"
    );
    memory.resize(retained)?;
    Ok((values, memory))
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;
