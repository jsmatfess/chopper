//! Reserve operation-key construction, then hand ownership to the decoded row.
use super::*;

/// A sorted partition's retained comparison key owns its capacity independently
/// of the decoder row, including old/new allocation overlap when it grows.
pub(super) struct BoundaryKey {
    bytes: Vec<u8>,
    memory: Reservation,
    initialized: bool,
}
impl BoundaryKey {
    pub(super) fn new(memory: Reservation) -> Self {
        Self {
            bytes: Vec::new(),
            memory,
            initialized: false,
        }
    }
    pub(super) fn matches(&self, key: &[u8]) -> bool {
        self.initialized && self.bytes == key
    }
    pub(super) fn replace(&mut self, key: &[u8]) -> Result<()> {
        self.memory.reserve_vec(&mut self.bytes, key.len())?;
        self.bytes.clear();
        self.bytes.extend_from_slice(key);
        self.initialized = true;
        Ok(())
    }
}

pub(super) struct OperationKey {
    pub bytes: Vec<u8>,
    reservation: Reservation,
}
impl OperationKey {
    fn allocate(capacity: usize, reservation: Reservation, sorter: &mut Sorter) -> Result<Self> {
        let mut reservation = reservation;
        let mut bytes = Vec::new();
        sorter.reserve_input(&mut reservation, capacity)?;
        bytes.try_reserve_exact(capacity)?;
        sorter.reserve_input(&mut reservation, bytes.capacity())?;
        Ok(Self { bytes, reservation })
    }

    pub fn tuple(
        fields: FieldViews<'_>,
        columns: &[usize],
        suffix: usize,
        reservation: Reservation,
        sorter: &mut Sorter,
    ) -> Result<Self> {
        let mut size = suffix;
        for &column in columns {
            let value = fields
                .clone()
                .nth(column)
                .context("invalid operation key column")?;
            size = size
                .checked_add(value.len())
                .and_then(|n| n.checked_add(value.bytes().filter(|b| *b == 0).count()))
                .and_then(|n| n.checked_add(2))
                .context("operation key capacity overflow")?;
        }
        let mut key = Self::allocate(size, reservation, sorter)?;
        for &column in columns {
            for byte in fields.clone().nth(column).expect("checked column").bytes() {
                key.bytes.push(byte);
                if byte == 0 {
                    key.bytes.push(255);
                }
            }
            key.bytes.extend_from_slice(&[0, 0]);
        }
        Ok(key)
    }

    pub fn allocation(
        index: u64,
        domain: &[u8; 32],
        id: u64,
        reservation: Reservation,
        sorter: &mut Sorter,
    ) -> Result<Self> {
        let mut key = Self::allocate(56, reservation, sorter)?;
        key.bytes.extend_from_slice(&index.to_be_bytes());
        key.bytes
            .extend_from_slice(&random::block(domain, id, 0)[..16]);
        key.bytes.extend_from_slice(domain);
        Ok(key)
    }

    pub fn install(self, row: &mut PackedRow, sorter: &mut Sorter) -> Result<usize> {
        row.set_operation_key(self.bytes, self.reservation, sorter)
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

#[cfg(test)]
mod tests {
    use super::*;

    fn context() -> Result<Context> {
        Context::new(
            &Resources {
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                workers: 1,
                grouping: Grouping::Sort,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )
    }
    fn row() -> Result<PackedRow> {
        PackedRow::new(Row {
            id: 1,
            ordinal: 1,
            key: vec![9],
            fields: vec!["a".into()],
        })
    }

    #[test]
    fn tuple_capacity_edges_shared_pressure_and_v1_bytes() -> Result<()> {
        let ctx = context()?;
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        let fields = vec!["".into(), "界\0\n\"".into(), "tail\0\0".into()];
        let columns = [2, 0, 1, 2];
        let expected = random::tuple_key(&fields, &columns);
        for suffix in [0, 48] {
            let capacity = expected.len() + suffix;
            for limit in [capacity - 1, capacity, capacity + 1] {
                let workspace = Arc::new(Workspace::new(limit));
                let result = OperationKey::tuple(
                    FieldViews::owned(&fields),
                    &columns,
                    suffix,
                    Reservation::for_workspace(workspace.clone()),
                    &mut sorter,
                );
                assert_eq!(result.is_ok(), limit >= capacity);
                if let Ok(key) = result {
                    assert_eq!(key.bytes, expected);
                    assert_eq!(key.bytes.capacity(), capacity);
                    assert_eq!(workspace.used(), capacity as u64);
                    drop(key);
                }
                assert_eq!(workspace.used(), 0);
                let mut other = Reservation::for_workspace(workspace.clone());
                other.resize(limit)?;
                assert!(OperationKey::tuple(
                    FieldViews::owned(&fields),
                    &columns,
                    suffix,
                    Reservation::for_workspace(workspace.clone()),
                    &mut sorter
                )
                .is_err());
                assert_eq!(workspace.used(), limit as u64);
                drop(other);
                if limit >= capacity {
                    drop(OperationKey::tuple(
                        FieldViews::owned(&fields),
                        &columns,
                        suffix,
                        Reservation::for_workspace(workspace.clone()),
                        &mut sorter,
                    )?);
                }
                assert_eq!(workspace.used(), 0);
                assert!(OperationKey::tuple(
                    FieldViews::owned(&fields),
                    &[99],
                    suffix,
                    Reservation::for_workspace(workspace.clone()),
                    &mut sorter
                )
                .is_err());
                assert_eq!(workspace.used(), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn allocation_handoff_inline_index_and_framing_match_v1() -> Result<()> {
        let ctx = context()?;
        let workspace = Arc::new(Workspace::new(4096));
        let domain = [7; 32];
        for index in [0, 7, u64::MAX] {
            let mut sorter = Sorter::new(&ctx, SortOrder::Key);
            let mut row = row()?;
            let key = OperationKey::allocation(
                index,
                &domain,
                row.id,
                Reservation::for_workspace(workspace.clone()),
                &mut sorter,
            )?;
            let mut expected = index.to_be_bytes().to_vec();
            expected.extend_from_slice(&random::block(&domain, row.id, 0)[..16]);
            expected.extend_from_slice(&domain);
            assert_eq!(key.bytes, expected);
            assert_eq!(key.bytes.capacity(), 56);
            assert_eq!(key.install(&mut row, &mut sorter)?, 56);
            drop(sorter);
            assert_eq!(row.key.as_slice(), expected);
            assert_eq!(workspace.used(), 56 + 17); // key + packed one-field payload
            row.set_index_key(index)?;
            assert!(matches!(row.key, PackedKey::Index(_)));
            assert_eq!(workspace.used(), 17);
            let mut actual = Vec::new();
            row.write(&mut actual)?;
            let mut expected = Vec::new();
            write_row(
                &mut expected,
                &Row {
                    id: 1,
                    ordinal: 1,
                    key: index.to_be_bytes().to_vec(),
                    fields: vec!["a".into()],
                },
            )?;
            assert_eq!(actual, expected);
            drop(row);
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn boxing_overlap_checks_edges_and_preserves_row_on_denial() -> Result<()> {
        let ctx = context()?;
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        for limit in [66, 67, 68] {
            let workspace = Arc::new(Workspace::new(limit));
            let mut row = row()?;
            let mut key = OperationKey::allocate(
                64,
                Reservation::for_workspace(workspace.clone()),
                &mut sorter,
            )?;
            key.bytes.extend_from_slice(&[1, 2, 3]);
            let result = key.install(&mut row, &mut sorter);
            assert_eq!(result.is_ok(), limit >= 67);
            if result.is_ok() {
                assert_eq!(row.key.as_slice(), [1, 2, 3]);
                assert_eq!(workspace.used(), 3 + 17);
            } else {
                assert_eq!(row.key.as_slice(), [9]);
                assert_eq!(workspace.used(), 0);
            }
            assert_eq!(row.fields().collect::<Vec<_>>(), ["a"]);
            drop(row);
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn handoff_denial_releases_new_key_and_allows_retry() -> Result<()> {
        let ctx = context()?;
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        let workspace = Arc::new(Workspace::new(20));
        let mut other = Reservation::for_workspace(workspace.clone());
        other.resize(1)?;
        let mut row = row()?;
        let mut key = OperationKey::allocate(
            3,
            Reservation::for_workspace(workspace.clone()),
            &mut sorter,
        )?;
        key.bytes.extend_from_slice(&[1, 2, 3]);
        assert!(key.install(&mut row, &mut sorter).is_err());
        assert_eq!(row.key.as_slice(), [9]);
        assert_eq!(workspace.used(), 1);
        drop(other);
        let mut key = OperationKey::allocate(
            3,
            Reservation::for_workspace(workspace.clone()),
            &mut sorter,
        )?;
        key.bytes.extend_from_slice(&[1, 2, 3]);
        key.install(&mut row, &mut sorter)?;
        assert_eq!(workspace.used(), 20);
        drop(row);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    fn key_pressure_spills_retained_rows_before_retrying_allocation() -> Result<()> {
        let ctx = context()?;
        let mut sorter = Sorter::new(&ctx, SortOrder::Key);
        for id in 0..100 {
            sorter.push(Row {
                id,
                ordinal: id,
                key: vec![],
                fields: vec!["x".repeat(16384)],
            })?;
        }
        let used = ctx.diagnostics()["workspace_reserved_bytes"]
            .as_u64()
            .unwrap() as usize;
        let mut other = Reservation::new(&ctx);
        other.resize(ctx.memory / 2 - used - 256 * 1024)?;
        let key = OperationKey::allocate(1024 * 1024, Reservation::new(&ctx), &mut sorter)?;
        assert_eq!(ctx.diagnostics()["sort_runs"], 1);
        drop(key);
        drop(other);
        let rows = sorter.finish()?.collect::<Result<Vec<_>>>()?;
        assert_eq!(rows.len(), 100);
        for (id, row) in rows.iter().enumerate() {
            assert_eq!(row.id, id as u64);
            assert_eq!(row.fields[0].len(), 16384);
        }
        drop(rows);
        assert_eq!(ctx.used(), 0);
        assert_eq!(
            ctx.diagnostics()["workspace_reserved_bytes"],
            ctx.directory_reserved_bytes()
        );
        Ok(())
    }
}
