//! Reusable bounded catalog input, with optional ownership of decoded capacity.
use super::*;
use serde::de::{DeserializeOwned, DeserializeSeed, MapAccess, SeqAccess, Visitor};
use std::{fmt, ops::Deref};
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) mod resource_contracts;

/// Implement only for metadata whose allocations are strings, Value trees and
/// Vec<Value>. The preflight below does not bound arbitrary Deserialize code.
pub(crate) trait JsonCapacity {
    fn json_capacity(&self) -> Result<usize>;
}

// A conservative allowance per BTreeMap entry, including a full node's spare
// key/value slots and edges. This is working-allocation accounting, not allocator
// layout or RSS measurement. serde_json uses BTreeMap (no preserve_order feature).
pub(crate) fn map_entry_allowance() -> usize {
    16 * (std::mem::size_of::<String>()
        + std::mem::size_of::<serde_json::Value>()
        + std::mem::size_of::<usize>())
}

fn add_capacity(total: &mut usize, bytes: usize) -> Result<()> {
    *total = total
        .checked_add(bytes)
        .context("decoded catalog size overflow")?;
    Ok(())
}

impl JsonCapacity for Vec<serde_json::Value> {
    fn json_capacity(&self) -> Result<usize> {
        let mut bytes = self
            .capacity()
            .checked_mul(std::mem::size_of::<serde_json::Value>())
            .context("decoded catalog size overflow")?;
        for value in self {
            add_capacity(&mut bytes, value.json_capacity()?)?;
        }
        Ok(bytes)
    }
}

impl JsonCapacity for serde_json::Value {
    fn json_capacity(&self) -> Result<usize> {
        match self {
            Self::String(value) => Ok(value.capacity()),
            Self::Array(values) => values.json_capacity(),
            Self::Object(values) => {
                let mut bytes = values
                    .len()
                    .checked_mul(map_entry_allowance())
                    .context("decoded catalog size overflow")?;
                for (key, value) in values {
                    add_capacity(&mut bytes, key.capacity())?;
                    add_capacity(&mut bytes, value.json_capacity()?)?;
                }
                Ok(bytes)
            }
            _ => Ok(0),
        }
    }
}

/// Decoded JSON value retaining its working-capacity reservation.
///
/// Borrow its contents through `Deref` or serialize it directly. The reservation
/// follows the owner after its reader is exhausted or dropped; it is not an RSS
/// measurement. Field order releases the value before releasing its capacity.
pub struct ChargedJson<T> {
    value: T,
    _reservation: Reservation,
}
impl<T> Deref for ChargedJson<T> {
    type Target = T;
    fn deref(&self) -> &T {
        &self.value
    }
}
impl<T> ChargedJson<T> {
    #[cfg(feature = "experimental-nested-balanced")]
    // Nested balanced traversal admits its separate lineage-growth owner before
    // using this seam. The decoded grant continues to cover the original tree.
    pub(crate) fn value_mut(&mut self) -> &mut T {
        &mut self.value
    }
    /// Keep the returned reservation alive until every moved allocation dies.
    #[cfg(test)]
    fn into_parts(self) -> (T, Reservation) {
        (self.value, self._reservation)
    }
}
impl<T: Serialize> Serialize for ChargedJson<T> {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self.value.serialize(serializer)
    }
}

/// Inspect the JSON without constructing its tree. Serde's reusable escape
/// scratch is covered separately; strings here are borrowed rather than owned.
struct Footprint;
impl<'de> DeserializeSeed<'de> for Footprint {
    type Value = usize;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> std::result::Result<usize, D::Error> {
        deserializer.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Footprint {
    type Value = usize;
    fn expecting(&self, f: &mut fmt::Formatter) -> fmt::Result {
        f.write_str("catalog JSON")
    }
    fn visit_bool<E>(self, _: bool) -> std::result::Result<usize, E> {
        Ok(0)
    }
    fn visit_i64<E>(self, _: i64) -> std::result::Result<usize, E> {
        Ok(0)
    }
    fn visit_u64<E>(self, _: u64) -> std::result::Result<usize, E> {
        Ok(0)
    }
    fn visit_f64<E>(self, _: f64) -> std::result::Result<usize, E> {
        Ok(0)
    }
    fn visit_unit<E>(self) -> std::result::Result<usize, E> {
        Ok(0)
    }
    fn visit_str<E>(self, value: &str) -> std::result::Result<usize, E> {
        Ok(value.len())
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> std::result::Result<usize, A::Error> {
        let mut bytes = 0usize;
        let mut count = 0usize;
        while let Some(value) = seq.next_element_seed(Footprint)? {
            add_capacity(&mut bytes, value).map_err(serde::de::Error::custom)?;
            count = count
                .checked_add(1)
                .ok_or_else(|| serde::de::Error::custom("catalog length overflow"))?;
        }
        // serde's Vec growth starts with four slots and doubles. Include both
        // old and replacement allocations at each growth boundary.
        let slots = if count == 0 {
            0
        } else {
            count
                .checked_mul(3)
                .ok_or_else(|| serde::de::Error::custom("catalog length overflow"))?
                .max(4)
        };
        let capacity = slots
            .checked_mul(std::mem::size_of::<serde_json::Value>())
            .ok_or_else(|| serde::de::Error::custom("catalog length overflow"))?;
        add_capacity(&mut bytes, capacity).map_err(serde::de::Error::custom)?;
        Ok(bytes)
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> std::result::Result<usize, A::Error> {
        let mut bytes = 0usize;
        while let Some(key) = map.next_key_seed(Footprint)? {
            add_capacity(&mut bytes, map_entry_allowance()).map_err(serde::de::Error::custom)?;
            add_capacity(&mut bytes, key).map_err(serde::de::Error::custom)?;
            add_capacity(&mut bytes, map.next_value_seed(Footprint)?)
                .map_err(serde::de::Error::custom)?;
        }
        Ok(bytes)
    }
}

/// Decode a supported metadata schema while admitting parser scratch and trees.
pub(crate) fn decode_reserved<T: DeserializeOwned + JsonCapacity>(
    line: &[u8],
    mut charge: Reservation,
) -> Result<ChargedJson<T>> {
    // The slice parser's escape buffer doubles from a small initial allocation.
    // Cover old/new growth overlap during both the preflight and owned decode.
    let scratch = line
        .len()
        .max(8)
        .checked_next_power_of_two()
        .and_then(|n| n.checked_mul(2))
        .context("catalog scratch size overflow")?;
    charge.resize(scratch)?;
    let mut decoder = serde_json::Deserializer::from_slice(line);
    let allowance = Footprint.deserialize(&mut decoder)?;
    decoder.end()?;
    drop(decoder);
    charge.resize(
        scratch
            .checked_add(allowance)
            .context("decoded catalog size overflow")?,
    )?;
    let value: T = serde_json::from_slice(line)?;
    let retained = value.json_capacity()?;
    ensure!(
        retained <= allowance,
        "decoded catalog capacity exceeds preflight allowance"
    );
    charge.resize(retained)?;
    Ok(ChargedJson {
        value,
        _reservation: charge,
    })
}

pub(crate) struct JsonLines<T> {
    reader: BufReader<DiskReader>,
    line: Vec<u8>,
    maximum: usize,
    reservation: Reservation,
    _reader: Reservation,
    done: bool,
    value: std::marker::PhantomData<T>,
}

impl<T> JsonLines<T> {
    pub(crate) fn reserved(self) -> ReservedJsonLines<T>
    where
        T: DeserializeOwned + JsonCapacity,
    {
        ReservedJsonLines { lines: self }
    }
    fn stop(&mut self) {
        self.done = true;
        self.line = Vec::new();
        self.reservation.resize(0).expect("releasing capacity");
    }
    pub(crate) fn new(file: &DiskFile, maximum: usize) -> Result<Self> {
        let mut reader = file._path_reservation.sibling();
        reader.resize(DISK_READ_BUFFER)?;
        Ok(Self {
            reader: file.reader()?,
            line: Vec::new(),
            maximum,
            reservation: reader.sibling(),
            _reader: reader,
            done: false,
            value: std::marker::PhantomData,
        })
    }

    fn read_line(&mut self) -> Result<bool> {
        self.line.clear();
        loop {
            ensure!(
                !self
                    .reader
                    .get_ref()
                    .budget
                    .cancel
                    .load(AtomicOrdering::Relaxed),
                "job cancelled"
            );
            let available = self.reader.fill_buf()?;
            if available.is_empty() {
                return Ok(!self.line.is_empty());
            }
            let newline = available.iter().position(|b| *b == b'\n');
            let count = newline.unwrap_or(available.len());
            let needed = self
                .line
                .len()
                .checked_add(count)
                .context("catalog length overflow")?;
            ensure!(
                needed <= self.maximum,
                "catalog record exceeds metadata record budget"
            );
            if needed > self.line.capacity() {
                let capacity = needed
                    .max(self.line.capacity().saturating_mul(2))
                    .min(self.maximum);
                self.reservation.reserve_vec(&mut self.line, capacity)?;
            }
            self.line.extend_from_slice(&available[..count]);
            let consumed = count + usize::from(newline.is_some());
            self.reader.consume(consumed);
            if newline.is_some() {
                return Ok(true);
            }
        }
    }
}

pub(crate) struct ReservedJsonLines<T> {
    lines: JsonLines<T>,
}
impl<T: DeserializeOwned + JsonCapacity> Iterator for ReservedJsonLines<T> {
    type Item = Result<ChargedJson<T>>;
    fn next(&mut self) -> Option<Self::Item> {
        let lines = &mut self.lines;
        if lines.done {
            return None;
        }
        let result = match lines.read_line() {
            Ok(false) => {
                lines.stop();
                return None;
            }
            Ok(true) => decode_reserved(&lines.line, lines.reservation.sibling()),
            Err(error) => Err(error),
        };
        if result.is_err() {
            lines.stop();
        }
        Some(result)
    }
}

impl<T: DeserializeOwned> Iterator for JsonLines<T> {
    type Item = Result<T>;
    fn next(&mut self) -> Option<Self::Item> {
        if self.done {
            return None;
        }
        match self.read_line() {
            Ok(false) => {
                self.stop();
                None
            }
            Ok(true) => {
                let result = serde_json::from_slice(&self.line).map_err(Into::into);
                if result.is_err() {
                    self.stop();
                }
                Some(result)
            }
            Err(error) => {
                self.stop();
                Some(Err(error))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn decoded_groups_keep_capacity_through_reader_drop_and_moved_lineage() -> Result<()> {
        let text = br#"{"offset":7,"rows":2,"lineage":[{"values":["escaped\u754c",["wide",null]]}],"exact":true}"#;
        let (ctx, file) = fixture(text)?;
        let mut lines = JsonLines::<Group>::new(&file, text.len())?.reserved();
        let held = lines.next().unwrap()?;
        let retained = held.json_capacity()? as u64;
        assert_eq!(serde_json::to_vec(&held)?, serde_json::to_vec(&*held)?);
        assert!(lines.next().is_none());
        drop(lines);
        drop(file);
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + retained
        );
        let (group, charge) = held.into_parts();
        let lineage = group.lineage;
        assert_eq!(lineage[0]["values"][0], "escaped界");
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + retained
        );
        drop(lineage);
        drop(charge);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }

    #[test]
    fn decoded_group_admission_edges_and_competing_owners_roll_back() -> Result<()> {
        let text = br#"{"offset":0,"rows":1,"lineage":["abcdef"],"exact":false}"#;
        let probe = Arc::new(Workspace::new(1024 * 1024));
        let held = decode_reserved::<Group>(text, Reservation::for_workspace(probe.clone()))?;
        let retained = probe.used();
        let peak = probe.peak();
        drop(held);
        for delta in [-1i64, 0, 1] {
            let pool = Arc::new(crate::resources::MemoryPool::new(
                (peak + retained).checked_add_signed(delta).unwrap(),
            ));
            let first = Arc::new(Workspace::shared(1024 * 1024, pool.clone()));
            let second = Arc::new(Workspace::shared(1024 * 1024, pool.clone()));
            let held = decode_reserved::<Group>(text, Reservation::for_workspace(first))?;
            let next = decode_reserved::<Group>(text, Reservation::for_workspace(second.clone()));
            assert_eq!(next.is_ok(), delta >= 0);
            if let Err(error) = &next {
                assert!(error
                    .downcast_ref::<crate::resources::MemoryAdmission>()
                    .is_some());
                assert_eq!(second.used(), 0);
            }
            drop(next);
            drop(held);
            let retry = decode_reserved::<Group>(text, Reservation::for_workspace(second))?;
            assert_eq!(pool.usage().reserved_bytes, retained);
            drop(retry);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }

    #[test]
    fn decoded_admission_edges_cover_scratch_and_array_growth_overlap() -> Result<()> {
        // Ten input bytes: 32 bytes of escape/growth scratch, four Value slots,
        // and the six-byte string. Admission must precede owned deserialization.
        let text = br#"["abcdef"]"#;
        let required = 32 + 4 * std::mem::size_of::<serde_json::Value>() + 6;
        for limit in [required - 1, required, required + 1] {
            let workspace = Arc::new(Workspace::new(limit));
            let decoded = decode_reserved::<serde_json::Value>(
                text,
                Reservation::for_workspace(workspace.clone()),
            );
            assert_eq!(decoded.is_ok(), limit >= required);
            if let Ok(decoded) = decoded {
                assert_eq!(decoded[0], "abcdef");
                assert_eq!(
                    workspace.used(),
                    (4 * std::mem::size_of::<serde_json::Value>() + 6) as u64
                );
                assert_eq!(workspace.peak(), required as u64);
                drop(decoded);
            }
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn decoded_shared_owners_deny_then_release_and_retry() -> Result<()> {
        // A decoded string retains six bytes; the next decoder also needs 22
        // bytes during conversion. Its failed local grant must roll back.
        for limit in [27, 28, 29] {
            let pool = Arc::new(crate::resources::MemoryPool::new(limit));
            let first = Arc::new(Workspace::shared(64, pool.clone()));
            let second = Arc::new(Workspace::shared(64, pool.clone()));
            let held = decode_reserved::<serde_json::Value>(
                br#""abcdef""#,
                Reservation::for_workspace(first.clone()),
            )?;
            let next = decode_reserved::<serde_json::Value>(
                br#""abcdef""#,
                Reservation::for_workspace(second.clone()),
            );
            assert_eq!(next.is_ok(), limit >= 28);
            if next.is_err() {
                assert_eq!(second.used(), 0);
                assert_eq!(pool.usage().reserved_bytes, 6);
            }
            drop(next);
            drop(held);
            let retry = decode_reserved::<serde_json::Value>(
                br#""abcdef""#,
                Reservation::for_workspace(second.clone()),
            )?;
            assert_eq!(pool.usage().reserved_bytes, 6);
            drop(retry);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }

    #[test]
    fn reserved_reader_keeps_decoded_trees_after_exhaustion_and_reader_drop() -> Result<()> {
        let text = br#"{"lineage":[{"key":"escaped\u754c","values":[null,true,1,2.5,"wide"]}]}"#;
        let (ctx, file) = fixture(text)?;
        let paths = ctx.workspace.used();
        let mut lines = JsonLines::<serde_json::Value>::new(&file, text.len())?.reserved();
        let held = lines.next().unwrap()?;
        let retained = held.json_capacity()? as u64;
        assert_eq!(held["lineage"][0]["key"], "escaped界");
        assert!(lines.next().is_none());
        assert_eq!(
            ctx.workspace.used(),
            paths + DISK_READ_BUFFER as u64 + retained
        );
        drop(lines);
        drop(file);
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + retained
        );
        drop(held);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }

    #[test]
    fn reserved_decode_failure_and_cancellation_release_owned_and_scratch_charges() -> Result<()> {
        for (text, cancel) in [(&b"{\"x\":[1,2,\n"[..], false), (&b"{}\n"[..], true)] {
            let (ctx, file) = fixture(text)?;
            let paths = ctx.workspace.used();
            let mut lines = JsonLines::<serde_json::Value>::new(&file, text.len())?.reserved();
            ctx.budget.cancel.store(cancel, AtomicOrdering::Relaxed);
            assert!(lines.next().unwrap().is_err());
            assert!(lines.next().is_none());
            assert_eq!(ctx.workspace.used(), paths + DISK_READ_BUFFER as u64);
            drop(lines);
            assert_eq!(ctx.workspace.used(), paths);
        }
        Ok(())
    }

    fn fixture(text: &[u8]) -> Result<(Context, DiskFile)> {
        let ctx = Context::with_memory_pool(
            &chopper_core::Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            Arc::new(crate::resources::MemoryPool::new(128 * 1024 * 1024)),
        )?;
        let mut file = ctx.file()?;
        file.write_all(text)?;
        Ok((ctx, file))
    }

    #[test]
    fn shared_capacity_edges_reuse_and_exhausted_reader_lifetime() -> Result<()> {
        let text = b"\"abcdef\"\n\"abcdef\"\n";
        for delta in [-1isize, 0, 1] {
            let (ctx, file) = fixture(text)?;
            let paths = ctx.workspace.used() as usize;
            // Use a shared pressure holder in the file's existing workspace.
            let line_bytes = 8;
            let mut pressure = Reservation::new(&ctx);
            let limit = ctx.memory / 2;
            pressure
                .resize(limit - paths - DISK_READ_BUFFER - line_bytes + usize::from(delta < 0))?;
            if delta > 0 {
                pressure.resize(pressure.bytes() as usize - 1)?;
            }
            let mut lines = JsonLines::<String>::new(&file, line_bytes)?;
            assert_eq!(lines.next().unwrap().is_ok(), delta >= 0);
            if delta >= 0 {
                let charged = ctx.workspace.used();
                assert_eq!(lines.next().unwrap()?, "abcdef");
                assert_eq!(
                    ctx.workspace.used(),
                    charged,
                    "same-size records reuse storage"
                );
            }
            assert!(lines.next().is_none());
            assert_eq!(
                ctx.workspace.used(),
                pressure.bytes() + paths as u64 + DISK_READ_BUFFER as u64
            );
            drop(pressure);
            drop(file);
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + DISK_READ_BUFFER as u64
            );
            drop(lines);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        }
        Ok(())
    }

    #[test]
    fn aggregate_reader_admission_rolls_back_and_retries() -> Result<()> {
        let pool = Arc::new(crate::resources::MemoryPool::new(1024 * 1024));
        let ctx = Context::with_memory_pool(
            &chopper_core::Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let mut file = ctx.file()?;
        file.write_all(b"42\n")?;
        let paths = ctx.workspace.used();
        let other = Arc::new(Workspace::shared(1024 * 1024, pool.clone()));
        let mut pressure = Reservation::for_workspace(other.clone());
        pressure.resize(1024 * 1024 - paths as usize - DISK_READ_BUFFER + 1)?;
        assert!(JsonLines::<u64>::new(&file, 2).is_err());
        assert_eq!(ctx.workspace.used(), paths, "local admission rolls back");
        assert_eq!(pool.usage().reserved_bytes, paths + other.used());
        drop(pressure);
        let mut lines = JsonLines::<u64>::new(&file, 2)?;
        assert_eq!(lines.next().unwrap()?, 42);
        drop(file);
        assert_eq!(
            pool.usage().reserved_bytes,
            ctx.directory_reserved_bytes() + (DISK_READ_BUFFER + 2) as u64
        );
        drop(lines);
        assert_eq!(pool.usage().reserved_bytes, ctx.directory_reserved_bytes());
        Ok(())
    }

    #[test]
    fn malformed_oversized_and_cancelled_catalogs_stop_and_release_scratch() -> Result<()> {
        for (text, maximum, cancel) in [
            (&b"\"ok\"\ninvalid\n\"ignored\"\n"[..], 128, false),
            (&b"\"ok\"\n\"oversized\"\n"[..], 4, false),
            (&b"\"ok\"\n\"truncated"[..], 128, false),
            (&b"\"ok\"\n\"\xff\"\n"[..], 128, false),
            (&b"\"ok\"\n\"buffered\"\n"[..], 128, true),
        ] {
            let (ctx, file) = fixture(text)?;
            let paths = ctx.workspace.used();
            let mut lines = JsonLines::<String>::new(&file, maximum)?;
            assert_eq!(lines.next().unwrap()?, "ok");
            ctx.budget.cancel.store(cancel, AtomicOrdering::Relaxed);
            assert!(lines.next().unwrap().is_err());
            assert!(lines.next().is_none());
            assert_eq!(ctx.workspace.used(), paths + DISK_READ_BUFFER as u64);
            drop(lines);
            assert_eq!(ctx.workspace.used(), paths);
        }
        Ok(())
    }

    #[test]
    fn multi_buffer_record_growth_overlap_denial_and_retry() -> Result<()> {
        let text = serde_json::to_vec(&"界".repeat(DISK_READ_BUFFER))?;
        let (ctx, file) = fixture(&text)?;
        let paths = ctx.workspace.used();
        let mut pressure = Reservation::new(&ctx);
        // Permit the first chunk but deny old/new overlap at the second.
        pressure.resize((ctx.memory / 2) - paths as usize - 3 * DISK_READ_BUFFER)?;
        let mut denied = JsonLines::<String>::new(&file, text.len())?;
        assert!(denied.next().unwrap().is_err());
        assert!(denied.next().is_none());
        drop(denied);
        drop(pressure);
        let mut retry = JsonLines::<String>::new(&file, text.len())?;
        assert_eq!(retry.next().unwrap()?, "界".repeat(DISK_READ_BUFFER));
        assert!(retry.next().is_none());
        drop(retry);
        assert_eq!(ctx.workspace.used(), paths);
        Ok(())
    }
}
