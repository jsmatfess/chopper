use super::*;
const MAGIC: &[u8; 16] = b"CHOPPER-ROWS-V1\n";

pub(super) struct Writer {
    output: LimitedWriter,
    bytes: Vec<u8>,
    rows: usize,
    total: u64,
    batches: usize,
    _grant: Reservation,
}
impl Writer {
    pub(super) fn new(mut output: LimitedWriter, ctx: &Context) -> Result<Self> {
        let maximum = TARGET_BATCH_BYTES.max(ctx.max_record);
        ensure!(
            maximum <= u32::MAX as usize,
            "snapshot block exceeds u32 format limit"
        );
        let mut grant = Reservation::new(ctx);
        grant.resize(maximum)?;
        let mut bytes = Vec::new();
        bytes.try_reserve_exact(maximum)?;
        grant.resize(bytes.capacity())?;
        output.write_all(MAGIC)?;
        Ok(Self {
            output,
            bytes,
            rows: 0,
            total: 0,
            batches: 0,
            _grant: grant,
        })
    }
    fn flush(&mut self) -> Result<()> {
        if self.rows == 0 {
            return Ok(());
        }
        ensure!(
            self.batches < MAX_BATCHES,
            "snapshot exceeds bounded block catalog"
        );
        self.output
            .write_all(&(self.bytes.len() as u32).to_le_bytes())?;
        self.output.write_all(&(self.rows as u32).to_le_bytes())?;
        self.output.write_all(&self.bytes)?;
        self.bytes.clear();
        self.rows = 0;
        self.batches += 1;
        Ok(())
    }
    pub(super) fn row(&mut self, row: &chopper_core::csv::CompactRecord) -> Result<()> {
        let size = row
            .len()
            .checked_mul(4)
            .and_then(|n| n.checked_add(row.payload_bytes()))
            .and_then(|n| n.checked_add(4))
            .context("snapshot row size overflow")?;
        ensure!(
            size <= u32::MAX as usize && size + 4 <= self.bytes.capacity(),
            "snapshot row exceeds bounded block size"
        );
        if self.rows == MAX_BATCH_ROWS
            || (!self.bytes.is_empty() && self.bytes.len() + size + 4 > TARGET_BATCH_BYTES)
        {
            self.flush()?;
        }
        ensure!(
            self.bytes.len() + size + 4 <= self.bytes.capacity(),
            "snapshot block exceeds reserved capacity"
        );
        self.bytes.extend_from_slice(&(size as u32).to_le_bytes());
        self.bytes
            .extend_from_slice(&(row.len() as u32).to_le_bytes());
        for field in row.fields() {
            self.bytes
                .extend_from_slice(&(field.len() as u32).to_le_bytes());
            self.bytes.extend_from_slice(field.as_bytes());
        }
        self.rows += 1;
        self.total = self
            .total
            .checked_add(1)
            .context("snapshot record count overflow")?;
        Ok(())
    }
    pub(super) fn finish(mut self) -> Result<u64> {
        self.flush()?;
        self.output.write_all(&[0; 8])?;
        self.output.write_all(&self.total.to_le_bytes())?;
        self.output.flush()?;
        Ok(self.output.bytes)
    }
}

pub(super) struct Reader {
    file: crate::storage::DiskReader,
    buffer: Vec<u8>,
    cursor: usize,
    end: usize,
    rows: usize,
    total: u64,
    expected: u64,
    columns: usize,
    maximum: usize,
    batches: usize,
    finished: bool,
    ctx: Context,
    _grant: Reservation,
}
impl Reader {
    pub(super) fn new(
        mut file: crate::storage::DiskReader,
        manifest: &Manifest,
        ctx: &Context,
    ) -> Result<Self> {
        let maximum = TARGET_BATCH_BYTES.max(ctx.max_record);
        ensure!(
            maximum <= u32::MAX as usize,
            "snapshot block exceeds u32 format limit"
        );
        let mut grant = Reservation::new(ctx);
        grant.resize(maximum)?;
        let mut buffer = Vec::new();
        buffer.try_reserve_exact(maximum)?;
        grant.resize(buffer.capacity())?;
        buffer.resize(maximum, 0);
        let mut magic = [0; 16];
        file.read_exact(&mut magic)?;
        ensure!(&magic == MAGIC, "invalid compact snapshot magic/version");
        Ok(Self {
            file,
            buffer,
            cursor: 0,
            end: 0,
            rows: 0,
            total: 0,
            expected: manifest.records,
            columns: manifest.columns,
            maximum: ctx.max_record,
            batches: 0,
            finished: false,
            ctx: ctx.clone(),
            _grant: grant,
        })
    }
    pub(super) fn next_fields(&mut self) -> Result<Option<Fields<'_>>> {
        self.ctx.check()?;
        if self.finished {
            return Ok(None);
        }
        if self.rows == 0 {
            ensure!(
                self.cursor == self.end,
                "trailing bytes in compact snapshot block"
            );
            let mut header = [0; 8];
            self.file
                .read_exact(&mut header)
                .context("truncated compact snapshot block header")?;
            let length = u32::from_le_bytes(header[..4].try_into().unwrap()) as usize;
            let count = u32::from_le_bytes(header[4..].try_into().unwrap()) as usize;
            if length == 0 {
                ensure!(count == 0, "invalid compact snapshot footer");
                self.file.read_exact(&mut header)?;
                ensure!(
                    u64::from_le_bytes(header) == self.total && self.total == self.expected,
                    "compact snapshot footer record count mismatch"
                );
                ensure!(
                    self.file.read(&mut [0])? == 0,
                    "trailing bytes after compact snapshot footer"
                );
                self.finished = true;
                return Ok(None);
            }
            ensure!(
                count > 0
                    && count <= MAX_BATCH_ROWS
                    && length <= self.buffer.len()
                    && self.batches < MAX_BATCHES,
                "compact snapshot block exceeds format bounds"
            );
            ensure!(
                self.total
                    .checked_add(count as u64)
                    .is_some_and(|n| n <= self.expected),
                "compact snapshot block exceeds declared record count"
            );
            self.file
                .read_exact(&mut self.buffer[..length])
                .context("truncated compact snapshot block")?;
            self.cursor = 0;
            self.end = length;
            self.rows = count;
            self.batches += 1;
        }
        let mut position = self.cursor;
        let length = take_u32(&self.buffer[..self.end], &mut position)? as usize;
        let end = position
            .checked_add(length)
            .filter(|n| *n <= self.end)
            .context("invalid compact snapshot row length")?;
        let count = take_u32(&self.buffer[..end], &mut position)? as usize;
        ensure!(
            count > 0 && count == self.columns,
            "compact snapshot field count mismatch"
        );
        let start = position;
        let mut payload = 0usize;
        for _ in 0..count {
            let length = take_u32(&self.buffer[..end], &mut position)? as usize;
            let next = position
                .checked_add(length)
                .filter(|n| *n <= end)
                .context("invalid compact snapshot field length")?;
            std::str::from_utf8(&self.buffer[position..next])
                .context("invalid UTF-8 in compact snapshot field")?;
            payload = payload
                .checked_add(length)
                .context("snapshot decoded row overflow")?;
            ensure!(
                payload
                    .checked_add(count * 32)
                    .is_some_and(|n| n <= self.maximum),
                "decoded snapshot row exceeds working limit"
            );
            position = next;
        }
        ensure!(position == end, "trailing bytes in compact snapshot row");
        self.cursor = end;
        self.rows -= 1;
        self.total += 1;
        Ok(Some(Fields {
            bytes: &self.buffer[start..end],
            remaining: count,
        }))
    }
}
fn take_u32(bytes: &[u8], position: &mut usize) -> Result<u32> {
    let end = position
        .checked_add(4)
        .filter(|n| *n <= bytes.len())
        .context("truncated compact snapshot length")?;
    let value = u32::from_le_bytes(bytes[*position..end].try_into().unwrap());
    *position = end;
    Ok(value)
}
#[derive(Clone)]
pub(super) struct Fields<'a> {
    bytes: &'a [u8],
    remaining: usize,
}
impl<'a> Iterator for Fields<'a> {
    type Item = &'a str;
    fn next(&mut self) -> Option<Self::Item> {
        if self.remaining == 0 {
            return None;
        }
        let length = u32::from_le_bytes(self.bytes[..4].try_into().unwrap()) as usize;
        let field = std::str::from_utf8(&self.bytes[4..4 + length]).unwrap();
        self.bytes = &self.bytes[4 + length..];
        self.remaining -= 1;
        Some(field)
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        (self.remaining, Some(self.remaining))
    }
}
impl ExactSizeIterator for Fields<'_> {}
