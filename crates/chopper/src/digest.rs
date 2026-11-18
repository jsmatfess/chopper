//! Batch the v1 logical record byte stream without changing its framing.
use crate::storage::Reservation;
use anyhow::Result;
const CAPACITY: usize = 16 * 1024;

pub(crate) struct LogicalDigest {
    hasher: blake3::Hasher,
    buffer: Vec<u8>,
    _reservation: Option<Reservation>,
}
impl LogicalDigest {
    #[cfg(test)]
    pub fn new() -> Self {
        Self {
            hasher: blake3::Hasher::new(),
            buffer: Vec::with_capacity(CAPACITY),
            _reservation: None,
        }
    }
    pub fn reserved(mut reservation: Reservation) -> Result<Self> {
        reservation.resize(std::mem::size_of::<Self>())?;
        let mut buffer = Vec::new();
        reservation.reserve_vec(&mut buffer, CAPACITY)?;
        Ok(Self {
            hasher: blake3::Hasher::new(),
            buffer,
            _reservation: Some(reservation),
        })
    }
    fn flush(&mut self) {
        self.hasher.update(&self.buffer);
        self.buffer.clear();
    }
    fn update(&mut self, bytes: &[u8]) {
        if bytes.len() > CAPACITY - self.buffer.len() {
            self.flush();
        }
        if bytes.len() >= CAPACITY {
            self.hasher.update(bytes);
        } else {
            self.buffer.extend_from_slice(bytes);
        }
    }
    pub fn record(&mut self, fields: &[String]) {
        self.update(&(fields.len() as u64).to_le_bytes());
        for field in fields {
            self.update(&(field.len() as u64).to_le_bytes());
            self.update(field.as_bytes());
        }
    }
    pub fn compact_record(&mut self, record: &chopper_core::csv::CompactRecord) {
        self.update(record.encoded_fields());
    }
    pub fn finalize(mut self) -> blake3::Hash {
        self.flush();
        self.hasher.finalize()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_v1_stream_at_buffer_and_large_field_boundaries() {
        for rows in [0, 1, 3, 1000] {
            let mut digest = LogicalDigest::new();
            let mut compact_digest = LogicalDigest::new();
            let mut reference = blake3::Hasher::new();
            for row in 0..rows {
                let fields = vec![
                    String::new(),
                    "界\0\n".into(),
                    "x".repeat([1, CAPACITY - 1, CAPACITY, CAPACITY + 1][row % 4]),
                ];
                reference.update(&(fields.len() as u64).to_le_bytes());
                for field in &fields {
                    reference.update(&(field.len() as u64).to_le_bytes());
                    reference.update(field.as_bytes());
                }
                digest.record(&fields);
                let encoded = chopper_core::csv::serialize(&fields, &Default::default()).unwrap();
                let mut parser = chopper_core::csv::Parser::new(
                    std::io::Cursor::new(encoded),
                    Default::default(),
                    1024 * 1024,
                );
                let mut record = chopper_core::csv::CompactRecord::default();
                assert!(parser.next_compact_record_into(&mut record).unwrap());
                compact_digest.compact_record(&record);
                assert!(digest.buffer.len() <= CAPACITY);
            }
            assert_eq!(digest.finalize(), reference.finalize());
            assert_eq!(compact_digest.finalize(), reference.finalize());
        }
    }
}

#[cfg(test)]
mod reservation_tests {
    use super::*;
    use crate::storage::Workspace;
    use std::sync::Arc;

    #[test]
    fn digest_capacity_shared_pressure_and_finalization_release() -> Result<()> {
        let bytes = std::mem::size_of::<LogicalDigest>() + CAPACITY;
        for limit in [bytes - 1, bytes, bytes + 1] {
            let workspace = Arc::new(Workspace::new(limit));
            let result = LogicalDigest::reserved(Reservation::for_workspace(workspace.clone()));
            assert_eq!(result.is_ok(), limit >= bytes);
            if let Ok(mut digest) = result {
                assert_eq!(workspace.used(), bytes as u64);
                digest.record(&["界".into(), "".into(), "x".repeat(2 * CAPACITY)]);
                let actual = digest.finalize();
                let mut reference = LogicalDigest::new();
                reference.record(&["界".into(), "".into(), "x".repeat(2 * CAPACITY)]);
                assert_eq!(actual, reference.finalize());
            }
            assert_eq!(workspace.used(), 0);
            let mut other = Reservation::for_workspace(workspace.clone());
            other.resize(limit)?;
            assert!(
                LogicalDigest::reserved(Reservation::for_workspace(workspace.clone())).is_err()
            );
            assert_eq!(workspace.used(), limit as u64);
            drop(other);
            if limit >= bytes {
                drop(LogicalDigest::reserved(Reservation::for_workspace(
                    workspace.clone(),
                ))?);
                assert_eq!(workspace.used(), 0);
            }
        }
        Ok(())
    }
}
