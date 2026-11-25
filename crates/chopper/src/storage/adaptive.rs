//! Bounded physical representations shared by native and browser execution.
use super::*;
use std::collections::BTreeMap;

/// Tracks algorithm workspaces, retained temporary paths, intermediate dataset
/// I/O buffers, owned/compact dataset decode payloads/keys, ingestion/profiling parser
/// buffers, profiling sketches/metadata/cache rows, retained prepared headers,
/// row conversions, partition domain caches, exact-assignment scratch, streaming group
/// state, output-plan writer/serialization/prefix buffers, catalog input buffers,
/// logical-digest state and merge metadata.
/// The other half of the job budget covers
/// remaining catalog/publication/input/codec allocations and native runtime overhead.
/// Not an RSS cap.
#[derive(Debug)]
pub struct Workspace {
    used: AtomicU64,
    peak: AtomicU64,
    limit: u64,
    pool: Option<Arc<crate::resources::MemoryPool>>,
}
impl Workspace {
    #[cfg(any(
        test,
        all(
            feature = "resource-contract-tests",
            feature = "experimental-spill-blocks"
        )
    ))]
    pub(super) fn add_directory_allowance_for_test(&mut self, bytes: u64) {
        self.limit = self.limit.checked_add(bytes).unwrap();
    }
    pub fn new(limit: usize) -> Self {
        Self {
            used: AtomicU64::new(0),
            peak: AtomicU64::new(0),
            limit: limit as u64,
            pool: None,
        }
    }
    pub(crate) fn shared(limit: usize, pool: Arc<crate::resources::MemoryPool>) -> Self {
        Self {
            pool: Some(pool),
            ..Self::new(limit)
        }
    }
    #[cfg(any(test, feature = "resource-contract-tests"))]
    pub(crate) fn process_usage(&self) -> Option<crate::resources::MemoryUsage> {
        self.pool.as_ref().map(|pool| pool.usage())
    }
    pub(crate) fn with_process_usage<R>(
        &self,
        run: impl FnOnce(Option<crate::resources::MemoryUsageView<'_>>) -> R,
    ) -> R {
        match &self.pool {
            Some(pool) => pool.with_usage(|usage| run(Some(usage))),
            None => run(None),
        }
    }
    pub(crate) fn process_reservations(&self) -> Option<(u64, u64)> {
        self.pool.as_ref().map(|pool| pool.reservation_counts())
    }
    pub(crate) fn recheck_pressure(&self) {
        if let Some(pool) = &self.pool {
            pool.recheck_pressure();
        }
    }
    fn release(&self, bytes: u64) {
        self.used.fetch_sub(bytes, AtomicOrdering::Relaxed);
        if let Some(pool) = &self.pool {
            pool.release(bytes);
        }
    }
    pub fn used(&self) -> u64 {
        self.used.load(AtomicOrdering::Relaxed)
    }
    pub fn peak(&self) -> u64 {
        self.peak.load(AtomicOrdering::Relaxed)
    }
    pub(super) fn available_bytes(&self) -> u64 {
        let local = self.limit.saturating_sub(self.used());
        self.pool.as_ref().map_or(local, |pool| {
            local.min(
                pool.admission_limit()
                    .saturating_sub(pool.reservation_counts().0),
            )
        })
    }

    #[cfg(any(target_os = "linux", target_os = "wasi"))]
    pub(super) fn available_sort_buffer_limit(&self, nominal: usize) -> usize {
        nominal.min(usize::try_from(self.available_bytes() / 2).unwrap_or(usize::MAX))
    }
    pub(super) fn sort_buffer_limit(&self, nominal: usize) -> usize {
        self.pool.as_ref().map_or(nominal, |pool| {
            nominal.min((pool.admission_limit() / 2).min(usize::MAX as u64) as usize)
        })
    }
}
#[derive(Debug)]
pub struct Reservation {
    workspace: Arc<Workspace>,
    bytes: u64,
}
impl Reservation {
    pub(crate) fn effective_memory_bytes(&self) -> u64 {
        self.workspace.limit * 2
    }
    pub fn new(ctx: &Context) -> Self {
        Self::for_workspace(ctx.workspace.clone())
    }
    pub(crate) fn for_workspace(workspace: Arc<Workspace>) -> Self {
        Self {
            workspace,
            bytes: 0,
        }
    }
    // Move ownership of an already charged allocation without releasing it.
    pub(crate) fn absorb(&mut self, mut other: Self) {
        assert!(Arc::ptr_eq(&self.workspace, &other.workspace));
        self.bytes += other.bytes;
        other.bytes = 0;
    }
    /// Transfer live ownership without briefly releasing the shared charge.
    fn split(&mut self, bytes: usize) -> Self {
        assert!(bytes as u64 <= self.bytes);
        self.bytes -= bytes as u64;
        Self {
            workspace: self.workspace.clone(),
            bytes: bytes as u64,
        }
    }
    pub(crate) fn sibling(&self) -> Self {
        Self::for_workspace(self.workspace.clone())
    }
    pub(crate) fn bytes(&self) -> u64 {
        self.bytes
    }
    #[cfg(any(target_os = "wasi", test))]
    pub(crate) fn accept_shared(
        &mut self,
        bytes: usize,
        source_pool: &Arc<crate::resources::MemoryPool>,
        source_bytes: usize,
    ) -> Result<()> {
        ensure!(
            self.workspace
                .pool
                .as_ref()
                .is_some_and(|pool| Arc::ptr_eq(pool, source_pool)),
            "decoded Job and preparation use different memory pools"
        );
        ensure!(self.bytes == 0, "Job reservation already in use");
        let delta = bytes
            .checked_sub(source_bytes)
            .context("decoded Job exceeds preparation capacity")?;
        self.grow(bytes as u64, delta as u64)?;
        self.bytes = bytes as u64;
        Ok(())
    }
    /// Grow one allocation within an aggregate reservation, including both old
    /// and replacement capacities during reallocation. Payload charges already
    /// in this reservation are preserved.
    pub(crate) fn reserve_vec<T>(&mut self, values: &mut Vec<T>, capacity: usize) -> Result<()> {
        if capacity <= values.capacity() {
            return Ok(());
        }
        let element = std::mem::size_of::<T>();
        let old = self.bytes as usize;
        let base = old
            .checked_sub(values.capacity() * element)
            .context("vector capacity was not reserved")?;
        let requested = capacity
            .checked_mul(element)
            .context("vector capacity overflow")?;
        self.resize(
            old.checked_add(requested)
                .context("vector capacity overflow")?,
        )?;
        if let Err(error) = values.try_reserve_exact(capacity - values.len()) {
            self.resize(old)?;
            return Err(error.into());
        }
        self.resize(
            base.checked_add(values.capacity() * element)
                .context("vector capacity overflow")?,
        )
    }
    pub(crate) fn copy_string(&mut self, value: &str) -> Result<String> {
        let old = self.bytes as usize;
        self.resize(
            old.checked_add(value.len())
                .context("string capacity overflow")?,
        )?;
        let mut copy = String::new();
        copy.try_reserve_exact(value.len())?;
        self.resize(
            old.checked_add(copy.capacity())
                .context("string capacity overflow")?,
        )?;
        copy.push_str(value);
        Ok(copy)
    }
    #[inline]
    pub fn resize(&mut self, bytes: usize) -> Result<()> {
        let bytes = bytes as u64;
        if bytes == self.bytes {
            return Ok(());
        }
        self.resize_changed(bytes)
    }
    // Changing a charge performs admission or releases bytes. Isolate that
    // body so unchanged-size calls retain a small inline entry.
    #[inline(never)]
    fn resize_changed(&mut self, bytes: u64) -> Result<()> {
        if bytes > self.bytes {
            let extra = bytes - self.bytes;
            self.grow(extra, extra)?;
        } else {
            self.workspace.release(self.bytes - bytes);
        }
        self.bytes = bytes;
        Ok(())
    }

    fn grow(&self, local: u64, shared: u64) -> Result<()> {
        let old = self
            .workspace
            .used
            .try_update(AtomicOrdering::Relaxed, AtomicOrdering::Relaxed, |used| {
                used.checked_add(local)
                    .filter(|n| *n <= self.workspace.limit)
            })
            .map_err(|_| crate::resources::MemoryAdmission::Local)?;
        if let Some(pool) = self.workspace.pool.as_ref().filter(|_| shared != 0) {
            if let Err(error) = pool.acquire(shared) {
                // Roll back the local charge before it escapes this call.
                self.workspace
                    .used
                    .fetch_sub(local, AtomicOrdering::Relaxed);
                return Err(error);
            }
        }
        self.workspace
            .peak
            .fetch_max(old + local, AtomicOrdering::Relaxed);
        Ok(())
    }
}
impl Drop for Reservation {
    fn drop(&mut self) {
        self.workspace.release(self.bytes);
    }
}

/// Short fields share one allocation; wide payloads retain their owned strings.
/// The disk representation is unchanged, so memory and external paths compare
/// exactly the same keys and preserve the same random collision refinement.
pub struct PackedRow {
    pub id: u64,
    pub ordinal: u64,
    pub key: PackedKey,
    fields: Fields,
    // Dataset decode ownership follows the row, including consumer handoff.
    decode_reservation: Option<Reservation>,
}
/// Keep random keys adjacent to the row descriptor. Boxing variable keys keeps
/// this enum the size of a Vec on native targets. Fixed group indices are inline
/// too; all variants use safe code.
pub enum PackedKey {
    Random([u8; 16]),
    Index([u8; 8]),
    Bytes(Box<[u8]>),
}
impl PackedKey {
    pub(crate) fn new(bytes: Vec<u8>) -> Self {
        match bytes.as_slice().try_into() {
            Ok(key) => Self::Random(key),
            Err(_) => Self::Bytes(bytes.into_boxed_slice()),
        }
    }
    pub fn as_slice(&self) -> &[u8] {
        match self {
            Self::Random(key) => key,
            Self::Index(key) => key,
            Self::Bytes(key) => key,
        }
    }
    fn heap_bytes(&self) -> usize {
        match self {
            Self::Random(_) | Self::Index(_) => 0,
            Self::Bytes(key) => key.len(),
        }
    }
    fn into_vec(self) -> Vec<u8> {
        match self {
            Self::Random(key) => key.to_vec(),
            Self::Index(key) => key.to_vec(),
            Self::Bytes(key) => key.into_vec(),
        }
    }
}
impl std::ops::Deref for PackedKey {
    type Target = [u8];
    fn deref(&self) -> &[u8] {
        self.as_slice()
    }
}
enum Fields {
    Packed(Vec<u8>),
    Owned(Vec<String>),
}
/// Views only framing created from strings or validated by the checked decoder.
#[derive(Clone)]
pub struct FieldViews<'a>(FieldViewStorage<'a>);
#[derive(Clone)]
enum FieldViewStorage<'a> {
    Packed { bytes: &'a [u8], remaining: usize },
    Owned(std::slice::Iter<'a, String>),
}
impl<'a> FieldViews<'a> {
    pub(crate) fn owned(fields: &'a [String]) -> Self {
        Self(FieldViewStorage::Owned(fields.iter()))
    }
    pub(crate) fn parsed(record: &'a chopper_core::csv::CompactRecord) -> Self {
        Self(FieldViewStorage::Packed {
            bytes: &record.encoded_fields()[8..],
            remaining: record.len(),
        })
    }
}
impl<'a> Iterator for FieldViews<'a> {
    type Item = &'a str;
    fn next(&mut self) -> Option<Self::Item> {
        match &mut self.0 {
            FieldViewStorage::Owned(fields) => fields.next().map(String::as_str),
            FieldViewStorage::Packed { bytes, remaining } => {
                if *remaining == 0 {
                    return None;
                }
                let length = u64::from_le_bytes(bytes[..8].try_into().unwrap()) as usize;
                // SAFETY: packed views borrow immutable CompactRecord storage,
                // strings packed by new_reusing_fields, or read_fields_reserved
                // output, which validates each field before returning a row.
                // No mutable byte view or unchecked packed constructor escapes.
                let value = unsafe { std::str::from_utf8_unchecked(&bytes[8..8 + length]) };
                *bytes = &bytes[8 + length..];
                *remaining -= 1;
                Some(value)
            }
        }
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        let n = match &self.0 {
            FieldViewStorage::Owned(fields) => fields.len(),
            FieldViewStorage::Packed { remaining, .. } => *remaining,
        };
        (n, Some(n))
    }
}
impl ExactSizeIterator for FieldViews<'_> {}
impl PackedRow {
    pub(crate) fn from_record(id: u64, record: chopper_core::csv::CompactRecord) -> Self {
        Self {
            id,
            ordinal: id,
            key: PackedKey::Bytes(Box::default()),
            fields: Fields::Packed(record.into_encoded_fields()),
            decode_reservation: None,
        }
    }
    pub(crate) fn into_parser_record(self) -> chopper_core::csv::CompactRecord {
        match self.fields {
            Fields::Packed(bytes) => chopper_core::csv::CompactRecord::with_storage(bytes),
            Fields::Owned(_) => Default::default(),
        }
    }
    #[cfg(test)]
    pub(super) fn read_fields(
        reader: &mut impl BufRead,
        maximum: usize,
        header: RowHeader,
    ) -> Result<Self> {
        Self::read_fields_reusing(reader, maximum, header, None)
    }
    /// The previous row is consumed before decoding, so only one payload buffer
    /// is live. Callers may recycle only rows they have finished consuming.
    pub(super) fn read_fields_reusing(
        reader: &mut impl BufRead,
        maximum: usize,
        header: RowHeader,
        previous: Option<Self>,
    ) -> Result<Self> {
        Self::read_fields_reserved(reader, maximum, header, previous, None)
    }
    pub(super) fn read_fields_reserved(
        reader: &mut impl BufRead,
        maximum: usize,
        mut header: RowHeader,
        previous: Option<Self>,
        charge: Option<Reservation>,
    ) -> Result<Self> {
        let count = get_u64(reader)?;
        ensure!(
            count <= (maximum / 24 + 1) as u64,
            "invalid spool field count"
        );
        // Use the owned decoder's descriptor allowance for short fields. Exact
        // growth keeps wide payloads within that allowance plus actual payload;
        // geometric growth could exceed the merge's single-row reservation.
        let (previous_fields, mut reservation) = match previous {
            Some(row) => (Some(row.fields), row.decode_reservation),
            None => (None, None),
        };
        if reservation.is_none() {
            reservation = charge;
        }
        if let Some(key_charge) = header.key_reservation.take() {
            match &mut reservation {
                Some(charge) => charge.absorb(key_charge),
                None => reservation = Some(key_charge),
            }
        }
        // Move key ownership after the aggregate grant, before any fallible
        // field construction, so errors drop bytes before releasing admission.
        let key = header.key;
        let mut key_capacity = key.capacity();
        let mut bytes = match previous_fields {
            Some(Fields::Packed(bytes)) => bytes,
            _ => Vec::new(),
        };
        if let Some(charge) = &mut reservation {
            charge.resize(bytes.capacity() + key_capacity)?;
        }
        bytes.clear();
        reserve_decode_bytes(
            &mut bytes,
            8 + count as usize * 24,
            key_capacity,
            &mut reservation,
        )?;
        put_u64(&mut bytes, count)?;
        let mut remaining = maximum;
        for index in 0..count {
            let length = get_u64(reader)?;
            ensure!(length <= remaining as u64, "invalid or oversized spool frame: length {length} bytes exceeds limit {remaining} bytes");
            let length = length as usize;
            if bytes.capacity() - bytes.len() < 8 + length {
                // Retain the remaining descriptor allowance after a wide field
                // so each following short field does not reallocate its payload.
                let target = bytes.len() + 8 + length + (count - index - 1) as usize * 24;
                reserve_decode_bytes(&mut bytes, target, key_capacity, &mut reservation)?;
            }
            put_u64(&mut bytes, length as u64)?;
            let start = bytes.len();
            let read = (|| -> io::Result<()> {
                // The complete destination capacity is already admitted. Copy
                // ordinary buffered fields directly instead of zeroing bytes
                // that read_exact immediately overwrites. Keep the original
                // large-field path and zero-length I/O behavior.
                if length != 0 && length < DISK_READ_BUFFER {
                    let buffered = reader.fill_buf()?;
                    if length <= buffered.len() {
                        debug_assert!(bytes.capacity() - start >= length);
                        bytes.extend_from_slice(&buffered[..length]);
                        reader.consume(length);
                        return Ok(());
                    }
                }
                bytes.resize(start + length, 0);
                reader.read_exact(&mut bytes[start..])
            })();
            read.with_context(|| format!("reading field {} for row {}", index + 1, header.id))?;
            std::str::from_utf8(&bytes[start..])?;
            remaining -= length;
        }
        // Boxing a variable key can shrink its allocation. Reserve any overlap;
        // 16-byte random keys move inline without allocating.
        if key.len() != 16 && key.len() < key_capacity {
            if let Some(charge) = &mut reservation {
                charge.resize(bytes.capacity() + key_capacity + key.len())?;
            }
        }
        let key = key.into_packed();
        key_capacity = key.heap_bytes();
        if let Some(charge) = &mut reservation {
            charge.resize(bytes.capacity() + key_capacity)?;
        }
        Ok(Self {
            id: header.id,
            ordinal: header.ordinal,
            key,
            fields: Fields::Packed(bytes),
            decode_reservation: reservation,
        })
    }
    /// Replace a decoded key without allocating an eight-byte group index.
    pub(crate) fn set_index_key(&mut self, index: u64) -> Result<()> {
        self.key = PackedKey::Index(index.to_be_bytes());
        let bytes = self.heap_bytes();
        if let Some(charge) = &mut self.decode_reservation {
            charge.resize(bytes)?;
        }
        Ok(())
    }
    /// The new vector is already charged. Include boxing overlap and retain
    /// ownership through routing/reuse or transfer into the sort buffer.
    pub(crate) fn set_operation_key(
        &mut self,
        key_bytes: Vec<u8>,
        reservation: Reservation,
        sorter: &mut Sorter,
    ) -> Result<usize> {
        // Local drop order keeps key storage alive only while it is charged.
        let mut charge = reservation;
        let bytes = key_bytes;
        let capacity = bytes.capacity();
        if bytes.len() != 16 && bytes.len() < capacity {
            sorter.reserve_input(
                &mut charge,
                capacity
                    .checked_add(bytes.len())
                    .context("operation key capacity overflow")?,
            )?;
        }
        let key = PackedKey::new(bytes);
        charge.resize(key.heap_bytes())?;
        let retained = self.heap_bytes() - self.key.heap_bytes() + key.heap_bytes();
        if self.decode_reservation.is_none() {
            // Parser-owned fields still overlap this handoff. Charge the row's
            // future ownership before the parser relinquishes its reservation.
            sorter.reserve_input(&mut charge, retained)?;
        }
        self.key = key;
        match &mut self.decode_reservation {
            Some(owner) => {
                owner.absorb(charge);
                owner.resize(retained)?;
            }
            None => self.decode_reservation = Some(charge),
        }
        Ok(capacity)
    }
    pub(super) fn release_decode_reservation(&mut self) {
        self.decode_reservation = None;
    }
    pub(crate) fn trim_fields(&mut self) -> Result<()> {
        // Parser-owned fields have no row grant for a replacement allocation.
        // Keep their actual capacity charged to the parser until handoff.
        if self.decode_reservation.is_none() {
            return Ok(());
        }
        if let Fields::Packed(fields) = &mut self.fields {
            // Decoder slack is useful while reading, but retained sort rows must
            // use the same compact capacity as rows packed from owned strings.
            if fields.len() < fields.capacity() {
                if let Some(reservation) = &mut self.decode_reservation {
                    reservation.resize(fields.capacity() + fields.len() + self.key.heap_bytes())?;
                }
                fields.shrink_to_fit();
                if let Some(reservation) = &mut self.decode_reservation {
                    reservation.resize(fields.capacity() + self.key.heap_bytes())?;
                }
            }
        }
        Ok(())
    }
    pub fn fields(&self) -> FieldViews<'_> {
        FieldViews(match &self.fields {
            Fields::Owned(fields) => return FieldViews::owned(fields),
            Fields::Packed(bytes) => FieldViewStorage::Packed {
                remaining: u64::from_le_bytes(bytes[..8].try_into().unwrap()) as usize,
                bytes: &bytes[8..],
            },
        })
    }
    pub(crate) fn append_calculated(
        &mut self,
        values: &[(String, char)],
        maximum: usize,
    ) -> Result<()> {
        let (count, payload) = self.field_sizes();
        let count = count
            .checked_add(values.len() + 1)
            .context("column count overflow")?;
        let kinds = values
            .iter()
            .map(|(_, kind)| kind.len_utf8())
            .sum::<usize>();
        let added = values.iter().try_fold(kinds, |size, (value, _)| {
            size.checked_add(value.len())
                .context("record size overflow")
        })?;
        ensure!(
            count <= maximum / 24 + 1 && added <= maximum.saturating_sub(payload),
            "calculated row exceeds maximum record size"
        );
        let Fields::Packed(bytes) = &mut self.fields else {
            anyhow::bail!("calculated row requires a packed input");
        };
        let target = bytes
            .len()
            .checked_add(8 * (values.len() + 1))
            .and_then(|size| size.checked_add(added))
            .context("record size overflow")?;
        reserve_decode_bytes(
            bytes,
            target,
            self.key.heap_bytes(),
            &mut self.decode_reservation,
        )?;
        for (value, _) in values {
            put_bytes(bytes, value.as_bytes())?;
        }
        bytes.extend_from_slice(&(kinds as u64).to_le_bytes());
        let mut buffer = [0; 4];
        for (_, kind) in values {
            bytes.extend_from_slice(kind.encode_utf8(&mut buffer).as_bytes());
        }
        bytes[..8].copy_from_slice(&(count as u64).to_le_bytes());
        Ok(())
    }
    pub fn disk_len(&self) -> u64 {
        let (count, payload) = self.field_sizes();
        (32 + self.key.len() + 8 * count + payload) as u64
    }
    pub(crate) fn field_sizes(&self) -> (usize, usize) {
        match &self.fields {
            Fields::Packed(bytes) => {
                let count = u64::from_le_bytes(bytes[..8].try_into().unwrap()) as usize;
                (count, bytes.len() - 8 - 8 * count)
            }
            Fields::Owned(fields) => (fields.len(), fields.iter().map(String::len).sum()),
        }
    }
    /// Lengths and actual row-owned capacities, excluding descriptor allowances.
    /// Packed fields expose these without another traversal or allocation.
    #[cfg(feature = "experimental-shuffle-partition")]
    pub(crate) fn observation_sizes(&self) -> (usize, usize, usize, usize) {
        let (fields, payload) = self.field_sizes();
        (fields, payload, self.heap_bytes(), self.key.heap_bytes())
    }
    pub(crate) fn decoded_size(&self, key_capacity: usize) -> usize {
        let (count, payload) = self.field_sizes();
        96 + key_capacity + count * 24 + payload
    }
    pub fn new(row: Row) -> Result<Self> {
        Self::new_reusing_fields(row).map(|(row, _)| row)
    }
    /// Return parser storage when packing narrow fields; transfer wide fields
    /// directly so a rare large payload is not copied just to retain it.
    pub(crate) fn new_reusing_fields(mut row: Row) -> Result<(Self, Vec<String>)> {
        let payload = row.fields.iter().map(String::len).sum::<usize>();
        let fields = if payload > row.fields.len().saturating_mul(256) {
            Fields::Owned(std::mem::take(&mut row.fields))
        } else {
            let mut packed = Vec::with_capacity(8 + row.fields.len() * 8 + payload);
            put_u64(&mut packed, row.fields.len() as u64)?;
            for field in &row.fields {
                put_bytes(&mut packed, field.as_bytes())?;
            }
            Fields::Packed(packed)
        };
        Ok((
            Self {
                id: row.id,
                ordinal: row.ordinal,
                key: PackedKey::new(row.key),
                fields,
                decode_reservation: None,
            },
            row.fields,
        ))
    }
    pub(super) fn new_reusing_fields_reserved(
        row: Row,
        owner: &Reservation,
    ) -> Result<(Self, Vec<String>)> {
        let payload = row.fields.iter().map(String::len).sum::<usize>();
        let fields = if payload > row.fields.len().saturating_mul(256) {
            row.fields.capacity() * std::mem::size_of::<String>()
                + row.fields.iter().map(String::capacity).sum::<usize>()
        } else {
            8 + row.fields.len() * 8 + payload
        };
        let overlap = if row.key.len() != 16 && row.key.len() < row.key.capacity() {
            row.key.len()
        } else {
            0
        };
        let mut charge = owner.sibling();
        charge.resize(fields + row.key.capacity() + overlap)?;
        let (mut packed, reusable) = Self::new_reusing_fields(row)?;
        charge.resize(packed.heap_bytes())?;
        packed.decode_reservation = Some(charge);
        Ok((packed, reusable))
    }
    pub fn memory(&self) -> usize {
        // Includes slack in the sort vector's geometric capacity growth.
        2 * std::mem::size_of::<Self>() + self.heap_bytes()
    }
    /// Allocations owned by this row, excluding its containing descriptor.
    pub(super) fn heap_bytes(&self) -> usize {
        self.key.heap_bytes()
            + match &self.fields {
                Fields::Packed(fields) => fields.capacity(),
                Fields::Owned(fields) => {
                    fields.capacity() * std::mem::size_of::<String>()
                        + fields.iter().map(String::capacity).sum::<usize>()
                }
            }
    }
    pub fn write(&self, w: &mut impl Write) -> Result<()> {
        put_u64(w, self.id)?;
        put_u64(w, self.ordinal)?;
        put_bytes(w, &self.key)?;
        match &self.fields {
            Fields::Packed(fields) => w.write_all(fields)?,
            Fields::Owned(fields) => {
                put_u64(w, fields.len() as u64)?;
                for field in fields {
                    put_bytes(w, field.as_bytes())?;
                }
            }
        }
        Ok(())
    }
    pub fn unpack(self) -> Result<Row> {
        let packed = match self.fields {
            Fields::Owned(fields) => {
                return Ok(Row {
                    id: self.id,
                    ordinal: self.ordinal,
                    key: self.key.into_vec(),
                    fields,
                })
            }
            Fields::Packed(fields) => fields,
        };
        let mut input = io::Cursor::new(packed);
        let count = get_u64(&mut input)?;
        let mut fields = Vec::with_capacity(count as usize);
        for _ in 0..count {
            let length = get_u64(&mut input)? as usize;
            let mut bytes = vec![0; length];
            input.read_exact(&mut bytes)?;
            fields.push(String::from_utf8(bytes)?);
        }
        Ok(Row {
            id: self.id,
            ordinal: self.ordinal,
            key: self.key.into_vec(),
            fields,
        })
    }
    pub(super) fn to_owned_reserved(&self, owner: &Reservation) -> Result<DecodedRow> {
        let mut reservation = owner.sibling();
        let mut key = Vec::new();
        reservation.reserve_vec(&mut key, self.key.len())?;
        key.extend_from_slice(&self.key);
        let mut fields = Vec::new();
        reservation.reserve_vec(&mut fields, self.fields().len())?;
        for field in self.fields() {
            fields.push(reservation.copy_string(field)?);
        }
        Ok(DecodedRow {
            row: Row {
                id: self.id,
                ordinal: self.ordinal,
                key,
                fields,
            },
            _reservation: reservation,
        })
    }
    pub(super) fn reserved_owned(&self) -> Result<Option<DecodedRow>> {
        self.decode_reservation
            .as_ref()
            .map(|charge| self.to_owned_reserved(charge))
            .transpose()
    }
}

/// Reserve both old and replacement allocations before growing decode storage.
/// A failed reservation leaves the buffer unchanged; dropping the decode releases
/// its charge on allocation, framing or UTF-8 errors.
fn reserve_decode_bytes(
    bytes: &mut Vec<u8>,
    target: usize,
    key_capacity: usize,
    reservation: &mut Option<Reservation>,
) -> Result<()> {
    if target <= bytes.capacity() {
        return Ok(());
    }
    if let Some(charge) = reservation {
        charge.resize(
            bytes
                .capacity()
                .checked_add(target)
                .and_then(|n| n.checked_add(key_capacity))
                .context("decode capacity overflow")?,
        )?;
    }
    bytes.try_reserve_exact(target - bytes.len())?;
    if let Some(charge) = reservation {
        charge.resize(bytes.capacity() + key_capacity)?;
    }
    Ok(())
}

/// Reserve retained payloads and actual descriptor capacity before growing a
/// vector. Reallocation can keep both descriptor arrays live; charge that peak
/// too. A denied reservation leaves the vector and ledger unchanged so callers
/// can spill using the same algorithm. Transient incoming rows are covered by
/// the job's separate decoding allowance.
pub(super) fn reserve_row_capacity(
    rows: &mut Vec<PackedRow>,
    heap_bytes: usize,
    reservation: &mut Reservation,
    limit: usize,
    overhead: usize,
) -> Result<bool> {
    let old_capacity = rows.capacity();
    let len = rows.len() + 1;
    let descriptor = std::mem::size_of::<PackedRow>();
    let base = heap_bytes
        .checked_add(overhead)
        .context("row buffer size overflow")?;
    let capacity = if len > old_capacity {
        // Prefer geometric growth, capped by the available reservation. Fill
        // the remaining capacity in one growth rather than reallocating once
        // per row near the ceiling.
        let preferred = old_capacity.max(1).saturating_mul(2);
        let available = (limit.saturating_sub(base) / descriptor).saturating_sub(old_capacity);
        preferred.min(available).max(len)
    } else {
        old_capacity
    };
    let overlap = if capacity > old_capacity {
        old_capacity
    } else {
        0
    };
    let peak = base.saturating_add(capacity.saturating_add(overlap).saturating_mul(descriptor));
    if peak > limit || reservation.resize(peak).is_err() {
        return Ok(false);
    }
    if capacity > old_capacity {
        rows.try_reserve_exact(capacity - rows.len())?;
    }
    // Vec may return excess capacity. Check it before retaining the row.
    let actual = base.saturating_add(rows.capacity().saturating_mul(descriptor));
    ensure!(
        actual <= limit,
        "row descriptor capacity exceeds memory budget"
    );
    reservation.resize(actual)?;
    Ok(true)
}
pub struct ResidentRows {
    pub rows: std::vec::IntoIter<PackedRow>,
    pub _reservation: Reservation,
}

/// Explicit resident Fisher–Yates v1. Failure never switches algorithms.
pub(crate) struct ResidentShuffle {
    rows: Vec<PackedRow>,
    bytes: usize,
    reservation: Reservation,
    ctx: Context,
    rng: chopper_core::random::Random,
}

// A private draw seam lets tests enumerate every choice sequence through the
// production permutation loop, without substituting a seeded RNG or algorithm.
fn fisher_yates<T>(rows: &mut [T], mut draw: impl FnMut(u64) -> Result<u64>) -> Result<()> {
    for i in (1..rows.len()).rev() {
        let j = draw(i as u64 + 1)? as usize;
        rows.swap(i, j);
    }
    Ok(())
}
impl ResidentShuffle {
    pub fn new(ctx: &Context, domain: [u8; 32]) -> Self {
        Self {
            rows: Vec::new(),
            bytes: 0,
            reservation: Reservation::new(ctx),
            ctx: ctx.clone(),
            rng: chopper_core::random::Random::new(chopper_core::random::algorithm_domain(
                &domain,
                "fisher-yates-v1",
            )),
        }
    }
    #[cfg(test)]
    pub fn push(&mut self, mut row: Row) -> Result<Vec<String>> {
        self.ctx.check()?;
        row.key.clear();
        let (row, reusable) = PackedRow::new_reusing_fields_reserved(row, &self.reservation)?;
        self.push_compact(row)?;
        Ok(reusable)
    }
    pub(crate) fn push_compact(&mut self, row: PackedRow) -> Result<()> {
        ensure!(self.try_push_compact(row)?,
            "Fisher–Yates group exceeds resident shuffle memory budget; increase memory_mb or select uniform (external-capable) shuffle");
        Ok(())
    }
    /// Admission denial consumes the incoming row without retaining it. The
    /// caller may discard this complete attempt and replay an immutable source.
    pub(crate) fn try_push_compact(&mut self, mut row: PackedRow) -> Result<bool> {
        self.ctx.check()?;
        row.key = PackedKey::Bytes(Box::default());
        let bytes = self
            .bytes
            .checked_add(row.heap_bytes())
            .context("shuffle size overflow")?;
        if !reserve_row_capacity(
            &mut self.rows,
            bytes,
            &mut self.reservation,
            self.ctx.memory / 4,
            std::mem::size_of::<Self>(),
        )? {
            return Ok(false);
        }
        row.release_decode_reservation();
        self.rows.push(row);
        self.bytes = bytes;
        Ok(true)
    }
    pub fn finish(mut self) -> Result<ResidentRows> {
        let mut rng = std::mem::replace(&mut self.rng, chopper_core::random::Random::new([0; 32]));
        self.finish_with_draws(|bound| rng.below(bound))
    }
    pub(crate) fn finish_with_draws(
        mut self,
        mut draw: impl FnMut(u64) -> u64,
    ) -> Result<ResidentRows> {
        let observation_ctx = self.ctx.clone();
        let observation =
            observation_ctx.physical_span(crate::observation::physical::Kind::FisherYates);
        let started = std::time::Instant::now();
        fisher_yates(&mut self.rows, |bound| {
            self.ctx.check()?;
            Ok(draw(bound))
        })?;
        // Like sort_seconds, this is loop wall time, excluding ingestion and
        // output. RNG draws and cancellation checks are part of the loop.
        self.ctx.budget.fisher_yates_nanoseconds.fetch_add(
            started.elapsed().as_nanos().min(u64::MAX as u128) as u64,
            AtomicOrdering::Relaxed,
        );
        self.ctx
            .budget
            .fisher_yates_calls
            .fetch_add(1, AtomicOrdering::Relaxed);
        self.ctx
            .budget
            .fisher_yates_rows
            .fetch_add(self.rows.len() as u64, AtomicOrdering::Relaxed);
        if let Some(span) = observation {
            span.finish(self.rows.len() as u64);
        }
        Ok(ResidentRows {
            rows: self.rows.into_iter(),
            _reservation: self.reservation,
        })
    }
}
impl ResidentRows {
    pub(super) fn take_packed(&mut self) -> Option<PackedRow> {
        self.rows.next().map(|mut row| {
            let charge = self._reservation.split(row.heap_bytes());
            row.decode_reservation = Some(charge);
            row
        })
    }
    pub(crate) fn compact(mut self) -> impl Iterator<Item = Result<PackedRow>> {
        // Capture self to retain the reservation until the iterator is dropped.
        std::iter::from_fn(move || {
            let _reservation = &self._reservation;
            self.take_packed().map(Ok)
        })
    }
}
impl Iterator for ResidentRows {
    type Item = Result<DecodedRow>;
    fn next(&mut self) -> Option<Self::Item> {
        self.take_packed()
            .map(|row| row.to_owned_reserved(&self._reservation))
    }
}

const ROUTE_BUFFER: usize = 65536;
const MAX_ROUTES: usize = 64;
fn route_cost(key: &[u8]) -> usize {
    ROUTE_BUFFER + key.len() + 1024
}
struct Bucket {
    writer: BufWriter<SpillFile>,
    last_ordinal: u64,
}
pub struct Router {
    observation: Option<crate::observation::physical::Attempt>,
    observed_rows: u64,
    buckets: BTreeMap<Vec<u8>, Bucket>,
    ctx: Context,
    reservation: Reservation,
    bytes: usize,
}
impl Router {
    /// Check the entire first buffer before creating any files. High cardinality
    /// and reordered strata go straight to sorting without paying for routing.
    pub fn eligible(rows: &[PackedRow], ctx: &Context) -> bool {
        // Routing is capped at 64 keys. A sorted stack array avoids an
        // unreserved temporary tree during sort/fallback selection.
        let mut keys = [(&[][..], 0u64); MAX_ROUTES];
        let mut len = 0;
        let mut bytes = 0;
        for row in rows {
            match keys[..len].binary_search_by(|(key, _)| key.cmp(&row.key.as_slice())) {
                Ok(index) => {
                    if row.ordinal < keys[index].1 {
                        return false;
                    }
                    keys[index].1 = row.ordinal;
                }
                Err(index) => {
                    bytes += route_cost(&row.key);
                    if len == MAX_ROUTES || bytes > ctx.memory / 8 {
                        return false;
                    }
                    keys.copy_within(index..len, index + 1);
                    keys[index] = (row.key.as_slice(), row.ordinal);
                    len += 1;
                }
            }
        }
        true
    }
    pub fn new(ctx: &Context) -> Self {
        Self {
            buckets: BTreeMap::new(),
            ctx: ctx.clone(),
            reservation: Reservation::new(ctx),
            bytes: 0,
            observation: None,
            observed_rows: 0,
        }
    }
    /// False requests a one-way fallback. No row is written on that path.
    pub fn push(&mut self, row: &PackedRow) -> Result<bool> {
        self.push_parts(&row.key, row.ordinal, |writer| row.write(writer))
    }
    pub fn push_row(&mut self, row: &Row) -> Result<bool> {
        self.push_parts(&row.key, row.ordinal, |writer| write_row(writer, row))
    }
    fn push_parts(
        &mut self,
        key: &[u8],
        ordinal: u64,
        write: impl FnOnce(&mut BufWriter<SpillFile>) -> Result<()>,
    ) -> Result<bool> {
        self.ctx.check()?;
        if self.observed_rows == 0 {
            self.observation = self
                .ctx
                .physical_attempt(crate::observation::physical::Kind::Routing);
        }
        if let Some(bucket) = self.buckets.get_mut(key) {
            if ordinal < bucket.last_ordinal {
                return Ok(false);
            }
            write(&mut bucket.writer)?;
            bucket.last_ordinal = ordinal;
        } else {
            let bytes = self.bytes + route_cost(key);
            if self.buckets.len() == MAX_ROUTES || bytes > self.ctx.memory / 8 {
                return Ok(false);
            }
            self.reservation.resize(bytes)?;
            self.bytes = bytes;
            let mut writer = self.ctx.spill_writer(ROUTE_BUFFER)?;
            write(&mut writer)?;
            self.buckets.insert(
                key.to_vec(),
                Bucket {
                    writer,
                    last_ordinal: ordinal,
                },
            );
        }
        self.observed_rows += 1;
        if let Some(attempt) = &mut self.observation {
            attempt.rows_processed(self.observed_rows);
        }
        Ok(true)
    }
    fn flush(&mut self) -> Result<Catalog<SpillFile>> {
        let mut files = Catalog::new(&self.ctx);
        for (_, mut bucket) in std::mem::take(&mut self.buckets) {
            self.ctx.check()?;
            bucket.writer.flush()?;
            files.push(bucket.writer.into_inner().map_err(|e| e.into_error())?)?;
        }
        Ok(files)
    }
    /// Every bucket has a single key and nondecreasing ordinals. These are
    /// already valid Key-sort runs; fallback must not decode/re-sort them.
    pub fn into_runs(mut self) -> Result<Catalog<SpillFile>> {
        let files = self.flush()?;
        if let Some(attempt) = self.observation.take() {
            attempt.finish(
                crate::observation::Status::HandedOff,
                self.observed_rows,
                files.len() as u64,
                None,
            );
        }
        Ok(files)
    }
    pub fn finish(mut self) -> Result<RoutedRows> {
        let files = self.flush()?;
        // Bucket writers and tree metadata have been destroyed. Retain only
        // the single live read buffer; payload ownership is charged per row.
        self.reservation.resize(DISK_READ_BUFFER)?;
        if let Some(attempt) = self.observation.take() {
            attempt.finish(
                crate::observation::Status::Completed,
                self.observed_rows,
                files.len() as u64,
                None,
            );
        }
        Ok(RoutedRows {
            reader: None,
            current: None,
            files: files.into_iter(),
            ctx: self.ctx.clone(),
            _reservation: std::mem::replace(&mut self.reservation, Reservation::new(&self.ctx)),
            failed: false,
        })
    }
}

impl Drop for Router {
    fn drop(&mut self) {
        if let Some(attempt) = self.observation.take() {
            attempt.finish(
                crate::observation::Status::Interrupted,
                self.observed_rows,
                0,
                None,
            );
        }
    }
}

pub struct RoutedRows {
    reader: Option<BufReader<SpillReader>>,
    current: Option<SpillFile>,
    files: catalog::CatalogIter<SpillFile>,
    ctx: Context,
    _reservation: Reservation,
    failed: bool,
}
impl RoutedRows {
    pub(super) fn next_decoded<T>(
        &mut self,
        decode: impl FnOnce(&mut BufReader<SpillReader>, usize, RowHeader) -> Result<T>,
    ) -> Option<Result<T>> {
        if self.failed {
            return None;
        }
        let result = (|| -> Result<Option<T>> {
            loop {
                self.ctx.check()?;
                if let Some(reader) = &mut self.reader {
                    if let Some(header) = read_header_reserved(
                        reader,
                        self.ctx.max_record,
                        Some(self._reservation.sibling()),
                    )? {
                        return decode(reader, self.ctx.max_record, header).map(Some);
                    }
                }
                // Close the descriptor before dropping the file (Windows).
                self.reader = None;
                self.current = None;
                let Some(file) = self.files.next() else {
                    return Ok(None);
                };
                self.reader = Some(file.reader()?);
                self.current = Some(file);
            }
        })();
        match result {
            Ok(row) => row.map(Ok),
            Err(error) => {
                self.failed = true;
                Some(Err(error))
            }
        }
    }
}
impl Iterator for RoutedRows {
    type Item = Result<DecodedRow>;
    fn next(&mut self) -> Option<Self::Item> {
        self.next_decoded(owned_fields_reserved)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aggregate_vector_growth_reserves_overlap_and_preserves_payload_charges() -> Result<()> {
        for delta in [-1isize, 0, 1] {
            let workspace = Arc::new(Workspace::new(4096));
            let mut charge = Reservation::for_workspace(workspace.clone());
            let payload = charge.copy_string("retained")?;
            let mut values = Vec::<u64>::new();
            charge.reserve_vec(&mut values, 4)?;
            values.extend([1, 2, 3, 4]);
            let before = charge.bytes();
            let mut other = Reservation::for_workspace(workspace.clone());
            other.resize(4096 - before as usize - 64usize.checked_add_signed(delta).unwrap())?;
            let result = charge.reserve_vec(&mut values, 8);
            assert_eq!(result.is_ok(), delta >= 0);
            assert_eq!(values, [1, 2, 3, 4]);
            assert_eq!(charge.bytes(), if delta < 0 { before } else { 8 + 64 });
            drop(values);
            drop(payload);
            drop(charge);
            assert_eq!(workspace.used(), other.bytes());
        }
        Ok(())
    }

    #[test]
    fn owned_adapter_checks_source_destination_overlap_and_retains_copy_charge() -> Result<()> {
        let workspace = Arc::new(Workspace::new(8192));
        let mut charge = Reservation::for_workspace(workspace.clone());
        let (source, _) = PackedRow::new_reusing_fields_reserved(
            Row {
                id: 3,
                ordinal: 8,
                key: vec![7; 17],
                fields: vec!["界\0".into(), String::new()],
            },
            &charge,
        )?;
        let base = workspace.used();
        let needed = 17 + 2 * std::mem::size_of::<String>() + 4;
        for delta in [-1isize, 0, 1] {
            charge.resize(8192 - base as usize - needed.checked_add_signed(delta).unwrap())?;
            let held = workspace.used();
            let copy = source.to_owned_reserved(&charge);
            assert_eq!(copy.is_ok(), delta >= 0);
            if let Ok(copy) = &copy {
                assert_eq!(copy.fields, ["界\0", ""]);
                assert_eq!(workspace.used(), held + needed as u64);
            }
            drop(copy);
            assert_eq!(workspace.used(), held);
        }
        charge.resize(0)?;
        let copy = source.to_owned_reserved(&charge)?;
        drop(source);
        assert_eq!(workspace.used(), needed as u64);
        drop(copy);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    fn buffered_spool_fields_preserve_owned_bytes_positions_and_failure_release() -> Result<()> {
        for capacity in [1, 3, 8, 64, 4096] {
            for invalid in [0, 1, 2] {
                let workspace = Arc::new(Workspace::new(4096));
                let row = Row {
                    id: 7,
                    ordinal: 13,
                    key: vec![7; 17],
                    fields: vec![String::new(), "界".into(), "x".repeat(100)],
                };
                let mut frame = Vec::new();
                write_row(&mut frame, &row)?;
                if invalid == 1 {
                    *frame.last_mut().unwrap() = 0xff;
                }
                if invalid == 2 {
                    frame.pop();
                }
                let expected_position = frame.len() as u64;
                let mut reader = BufReader::with_capacity(capacity, io::Cursor::new(frame));
                let header = read_header_reserved(
                    &mut reader,
                    1024,
                    Some(Reservation::for_workspace(workspace.clone())),
                )?
                .unwrap();
                let decoded =
                    PackedRow::read_fields_reserved(&mut reader, 1024, header, None, None);
                assert_eq!(reader.stream_position()?, expected_position);
                if invalid == 0 {
                    let decoded = decoded?;
                    assert_eq!(decoded.fields().collect::<Vec<_>>(), row.fields);
                    assert_eq!(decoded.key.as_slice(), row.key);
                    let held = workspace.used();
                    assert!(held > 0);
                    drop(reader);
                    assert_eq!(workspace.used(), held);
                    assert_eq!(decoded.fields().collect::<Vec<_>>(), row.fields);
                    drop(decoded);
                } else {
                    assert!(decoded.is_err());
                    drop(decoded);
                }
                assert_eq!(workspace.used(), 0);
            }
        }
        Ok(())
    }

    #[test]
    fn parser_owned_fields_retain_capacity_without_an_overlap_grant() -> Result<()> {
        let mut record = chopper_core::csv::CompactRecord::with_storage(Vec::with_capacity(128));
        let capacity = record.capacity();
        let workspace = Arc::new(Workspace::new(capacity));
        let mut parser = Reservation::for_workspace(workspace.clone());
        parser.resize(capacity)?;
        record.set_text_fields_reserved(["csv"].into_iter(), 128, &mut |bytes| {
            parser.resize(bytes)
        })?;
        let mut row = PackedRow::from_record(0, record);
        row.trim_fields()?;
        assert_eq!(row.heap_bytes(), capacity);
        assert_eq!(row.fields().collect::<Vec<_>>(), ["csv"]);
        assert_eq!(workspace.used(), capacity as u64);
        drop(row);
        drop(parser);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    fn dataset_decode_shrink_denial_and_truncation_release_capacity() -> Result<()> {
        let workspace = Arc::new(Workspace::new(32));
        let mut bytes = Vec::new();
        put_u64(&mut bytes, 1)?;
        put_bytes(&mut bytes, b"")?;
        let mut row = PackedRow::read_fields_reserved(
            &mut io::Cursor::new(bytes),
            1024,
            RowHeader {
                key_reservation: None,
                id: 0,
                ordinal: 0,
                key: vec![].into(),
            },
            None,
            Some(Reservation::for_workspace(workspace.clone())),
        )?;
        assert!(row.trim_fields().is_err());
        assert_eq!(workspace.used(), 32);
        assert_eq!(row.fields().collect::<Vec<_>>(), vec![""]);
        drop(row);
        assert_eq!(workspace.used(), 0);
        let mut bytes = Vec::new();
        put_u64(&mut bytes, 1)?;
        put_u64(&mut bytes, 8)?;
        bytes.push(b'x');
        assert!(PackedRow::read_fields_reserved(
            &mut io::Cursor::new(bytes),
            1024,
            RowHeader {
                key_reservation: None,
                id: 0,
                ordinal: 0,
                key: vec![].into()
            },
            None,
            Some(Reservation::for_workspace(workspace.clone())),
        )
        .is_err());
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    fn dataset_decode_reserves_growth_overlap_at_shared_capacity_edges() -> Result<()> {
        // One field: initial descriptor allowance 32, grown payload 116.
        // The reallocating step must reserve both allocations (148 bytes).
        for delta in [-1isize, 0, 1] {
            let workspace = Arc::new(Workspace::new(200));
            let mut competitor = Reservation::for_workspace(workspace.clone());
            competitor.resize(52usize.checked_add_signed(-delta).unwrap())?;
            let mut bytes = Vec::new();
            put_u64(&mut bytes, 1)?;
            put_bytes(&mut bytes, &[b'x'; 100])?;
            let result = PackedRow::read_fields_reserved(
                &mut io::Cursor::new(bytes),
                1024,
                RowHeader {
                    key_reservation: None,
                    id: 4,
                    ordinal: 9,
                    key: vec![].into(),
                },
                None,
                Some(Reservation::for_workspace(workspace.clone())),
            );
            assert_eq!(result.is_ok(), delta >= 0);
            if let Ok(row) = result {
                assert_eq!(row.fields().collect::<Vec<_>>(), vec!["x".repeat(100)]);
                assert_eq!(workspace.used(), competitor.bytes() + 116);
                assert_eq!(workspace.peak(), competitor.bytes() + 148);
                drop(row);
            }
            assert_eq!(workspace.used(), competitor.bytes());
            drop(competitor);
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn dataset_decode_reuses_wide_capacity_and_releases_on_corruption() -> Result<()> {
        for invalid in [false, true] {
            let workspace = Arc::new(Workspace::new(4096));
            let mut previous = None;
            for payload in [
                vec![b'x'; 1000],
                if invalid { vec![0xff] } else { vec![b'y'] },
            ] {
                let mut bytes = Vec::new();
                put_u64(&mut bytes, 1)?;
                put_bytes(&mut bytes, &payload)?;
                let result = PackedRow::read_fields_reserved(
                    &mut io::Cursor::new(bytes),
                    2048,
                    RowHeader {
                        key_reservation: None,
                        id: 0,
                        ordinal: 0,
                        key: vec![].into(),
                    },
                    previous.take(),
                    Some(Reservation::for_workspace(workspace.clone())),
                );
                if invalid && payload == [0xff] {
                    assert!(result.is_err());
                    assert_eq!(workspace.used(), 0);
                } else {
                    previous = Some(result?);
                    assert_eq!(workspace.used(), 1016);
                }
            }
            drop(previous);
            assert_eq!(workspace.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn fisher_yates_choice_sequences_have_equal_permutation_multiplicity() -> Result<()> {
        for len in 0..=8usize {
            let factorial = (1..=len).product::<usize>();
            let mut permutations = BTreeMap::new();
            for sequence in 0..factorial {
                let mut choices = sequence;
                let mut rows = (0..len).collect::<Vec<_>>();
                let mut bounds = Vec::new();
                fisher_yates(&mut rows, |bound| {
                    bounds.push(bound);
                    let choice = choices % bound as usize;
                    choices /= bound as usize;
                    Ok(choice as u64)
                })?;
                assert_eq!(choices, 0);
                assert_eq!(bounds, (2..=len as u64).rev().collect::<Vec<_>>());
                let mut conserved = rows.clone();
                conserved.sort_unstable();
                assert_eq!(conserved, (0..len).collect::<Vec<_>>());
                *permutations.entry(rows).or_insert(0usize) += 1;
            }
            assert_eq!(permutations.len(), factorial);
            assert!(permutations.values().all(|&count| count == 1));
        }
        Ok(())
    }

    #[test]
    fn fisher_yates_stops_immediately_when_draw_fails() {
        let mut rows = (0..6).collect::<Vec<_>>();
        let mut bounds = Vec::new();
        let result = fisher_yates(&mut rows, |bound| {
            bounds.push(bound);
            ensure!(bound != 4, "cancelled draw");
            Ok(0)
        });
        assert!(result.unwrap_err().to_string().contains("cancelled draw"));
        assert_eq!(bounds, [6, 5, 4]);
        assert_eq!(rows, [4, 1, 2, 3, 5, 0]);
    }

    #[test]
    fn retained_capacity_checks_exact_budget_and_reallocation_peak() -> Result<()> {
        let ctx = Context::new(
            &chopper_core::Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let make_row = || {
            PackedRow::new(Row {
                id: 0,
                ordinal: 0,
                key: vec![1; 17],
                fields: vec!["duplicate".into()],
            })
        };
        let row = make_row()?;
        let descriptor = std::mem::size_of::<PackedRow>();
        let overhead = 123;
        for delta in [-1isize, 0, 1] {
            let mut rows = Vec::with_capacity(3);
            let mut reservation = Reservation::new(&ctx);
            let exact = row.heap_bytes() + rows.capacity() * descriptor + overhead;
            let limit = exact.checked_add_signed(delta).unwrap();
            assert_eq!(
                reserve_row_capacity(
                    &mut rows,
                    row.heap_bytes(),
                    &mut reservation,
                    limit,
                    overhead,
                )?,
                delta >= 0
            );
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes() + if delta < 0 { 0 } else { exact as u64 }
            );
            drop(reservation);
        }
        let mut rows = Vec::with_capacity(1);
        rows.push(make_row()?);
        let mut reservation = Reservation::new(&ctx);
        let heaps = rows[0].heap_bytes() + row.heap_bytes();
        let peak = heaps + 3 * descriptor + overhead;
        assert!(!reserve_row_capacity(
            &mut rows,
            heaps,
            &mut reservation,
            peak - 1,
            overhead
        )?);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        assert!(reserve_row_capacity(
            &mut rows,
            heaps,
            &mut reservation,
            peak,
            overhead
        )?);
        assert_eq!(
            ctx.workspace.peak(),
            ctx.directory_reserved_bytes() + peak as u64
        );
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + (heaps + 2 * descriptor + overhead) as u64
        );
        drop(reservation);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }

    #[test]
    fn retained_payload_charges_owned_capacity_and_fisher_rng() -> Result<()> {
        let mut field = String::with_capacity(8192);
        field.push_str(&"x".repeat(1024));
        let mut fields = Vec::with_capacity(8);
        fields.push(field);
        let capacity = fields.capacity() * std::mem::size_of::<String>() + fields[0].capacity();
        let row = PackedRow::new(Row {
            id: 0,
            ordinal: 0,
            key: vec![],
            fields,
        })?;
        assert_eq!(row.heap_bytes(), capacity);
        let ctx = Context::new(
            &chopper_core::Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let mut shuffle = ResidentShuffle::new(&ctx, [0; 32]);
        shuffle.push_compact(row)?;
        assert_eq!(
            ctx.workspace.used() as usize,
            ctx.directory_reserved_bytes() as usize
                + capacity
                + shuffle.rows.capacity() * std::mem::size_of::<PackedRow>()
                + std::mem::size_of::<ResidentShuffle>()
        );
        drop(shuffle);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }

    #[test]
    fn checked_decoder_reuses_one_buffer_across_wide_and_small_rows() -> Result<()> {
        let mut previous = None;
        let mut last_pointer: *const u8 = std::ptr::null();
        let mut capacity = 0;
        for length in [100_000, 1, 8000, 0, 100_000] {
            let row = Row {
                id: length as u64,
                ordinal: 7,
                key: vec![9; 16],
                fields: vec!["界\0\n".into(), "x".repeat(length), String::new()],
            };
            let mut encoded = Vec::new();
            write_row(&mut encoded, &row)?;
            let mut reader = BufReader::with_capacity(7, encoded.as_slice());
            let header = read_header(&mut reader, 200_000)?.unwrap();
            let decoded = PackedRow::read_fields_reusing(&mut reader, 200_000, header, previous)?;
            assert_eq!(decoded.fields().collect::<Vec<_>>(), row.fields);
            assert_eq!(decoded.id, row.id);
            let Fields::Packed(bytes) = &decoded.fields else {
                unreachable!()
            };
            if !last_pointer.is_null() {
                assert_eq!(bytes.as_ptr(), last_pointer);
                assert_eq!(bytes.capacity(), capacity);
            }
            assert!(bytes.capacity() <= 8 + 3 * 24 + 100_006);
            last_pointer = bytes.as_ptr();
            capacity = bytes.capacity();
            previous = Some(decoded);
        }
        Ok(())
    }

    #[test]
    fn resident_shuffle_releases_workspace_on_failure_and_cancellation() -> Result<()> {
        for cancel in [false, true] {
            let flag = Arc::new(AtomicBool::new(false));
            let mut ctx = Context::new(
                &chopper_core::Resources::default(),
                flag.clone(),
                Arc::new(|_| {}),
            )?;
            ctx.memory = 64 * 1024;
            let mut shuffle = ResidentShuffle::new(&ctx, [0; 32]);
            for id in 0..4 {
                shuffle.push(Row {
                    id,
                    ordinal: id,
                    key: vec![],
                    fields: vec!["small".into()],
                })?;
            }
            assert!(ctx.workspace.used() > 0);
            if cancel {
                flag.store(true, AtomicOrdering::Relaxed);
                assert!(shuffle.finish().is_err());
            } else {
                assert!(shuffle
                    .push(Row {
                        id: 5,
                        ordinal: 5,
                        key: vec![],
                        fields: vec!["x".repeat(32768)]
                    })
                    .is_err());
                drop(shuffle);
            }
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[test]
    fn compact_resident_iterator_holds_workspace_until_drop() -> Result<()> {
        let ctx = Context::new(
            &chopper_core::Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let mut shuffle = ResidentShuffle::new(&ctx, [0; 32]);
        shuffle.push(Row {
            id: 0,
            ordinal: 0,
            key: vec![],
            fields: vec!["field".into()],
        })?;
        let mut rows = shuffle.finish()?.compact();
        assert!(ctx.workspace.used() > 0);
        assert!(rows.next().is_some());
        assert!(ctx.workspace.used() > 0);
        drop(rows);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }

    #[test]
    fn packed_keys_preserve_spool_bytes_and_owned_rows() -> Result<()> {
        for length in [0, 1, 15, 16, 17, 48, 4096] {
            for field in ["a,b\n界".to_string(), "x".repeat(1024)] {
                let row = Row {
                    id: 17,
                    ordinal: 9,
                    key: (0..length).map(|i| (i % 256) as u8).collect(),
                    fields: vec![String::new(), field],
                };
                let mut expected = Vec::new();
                write_row(&mut expected, &row)?;
                let mut input = expected.as_slice();
                let header = read_header(&mut input, 8192)?.unwrap();
                let decoded = PackedRow::read_fields(&mut input, 8192, header)?;
                assert!(input.is_empty());
                let mut reencoded = Vec::new();
                decoded.write(&mut reencoded)?;
                assert_eq!(reencoded, expected);
                assert_eq!(decoded.fields().collect::<Vec<_>>(), row.fields);
                if let Fields::Packed(bytes) = &decoded.fields {
                    assert!(
                        bytes.capacity()
                            <= 8 + row.fields.len() * 24
                                + row.fields.iter().map(String::len).sum::<usize>()
                    );
                }
                let packed = PackedRow::new(row.clone())?;
                assert_eq!(packed.key.as_slice(), row.key);
                if length == 16 {
                    assert_eq!(packed.key.heap_bytes(), 0);
                }
                let mut actual = Vec::new();
                packed.write(&mut actual)?;
                assert_eq!(actual, expected);
                assert_eq!(packed.disk_len(), actual.len() as u64);
                assert_eq!(packed.fields().len(), row.fields.len());
                assert_eq!(packed.fields().collect::<Vec<_>>(), row.fields);
                for encoding in ["utf-8", "utf-16le", "utf-16be"] {
                    let settings = chopper_core::CsvSettings {
                        encoding: encoding.into(),
                        ..Default::default()
                    };
                    let expected = chopper_core::csv::serialize(&row.fields, &settings)?;
                    let mut serializer = chopper_core::csv::Serializer::new(&settings)?;
                    assert_eq!(serializer.serialize_fields(packed.fields())?, expected);
                }
                let unpacked = packed.unpack()?;
                assert_eq!(unpacked.key, row.key);
                assert_eq!(unpacked.fields, row.fields);
                assert_eq!((unpacked.id, unpacked.ordinal), (row.id, row.ordinal));
            }
        }
        Ok(())
    }

    #[test]
    fn concurrent_reservations_share_a_ceiling_and_release_on_drop() -> Result<()> {
        let ctx = Context::new(
            &chopper_core::Resources {
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let mut first = Reservation::new(&ctx);
        let mut second = Reservation::new(&ctx);
        first.resize(12 * 1024 * 1024)?;
        assert!(second.resize(8 * 1024 * 1024).is_err());
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + 12 * 1024 * 1024
        );
        first.resize(8 * 1024 * 1024)?;
        second.resize(8 * 1024 * 1024 - ctx.directory_reserved_bytes() as usize)?;
        assert_eq!(ctx.workspace.peak(), 16 * 1024 * 1024);
        drop(first);
        drop(second);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }
}
