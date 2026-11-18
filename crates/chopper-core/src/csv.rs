use crate::CsvSettings;
use anyhow::{bail, ensure, Context, Result};
use encoding_rs::{Decoder, DecoderResult, EncoderResult, Encoding, UTF_16BE, UTF_16LE, UTF_8};
use std::io::{self, BufRead, Read};

pub fn encoding(name: &str) -> Result<&'static Encoding> {
    let enc = Encoding::for_label(name.as_bytes())
        .ok_or_else(|| anyhow::anyhow!("unsupported encoding {name}"))?;
    ensure!(
        matches!(
            enc.name(),
            "UTF-8"
                | "UTF-16LE"
                | "UTF-16BE"
                | "windows-1250"
                | "windows-1251"
                | "windows-1252"
                | "windows-1253"
                | "windows-1254"
                | "windows-1255"
                | "windows-1256"
                | "windows-1257"
                | "windows-1258"
                | "Shift_JIS"
                | "GBK"
                | "Big5"
                | "EUC-KR"
                | "ISO-8859-2"
        ),
        "encoding {} is not supported in v1",
        enc.name()
    );
    Ok(enc)
}

/// Strict incremental transcoding. Never substitutes replacement characters.
pub struct DecodeReader<R> {
    source: R,
    decoder: Decoder,
    input: [u8; 8192],
    start: usize,
    end: usize,
    output: [u8; 32768],
    pos: usize,
    len: usize,
    eof: bool,
    done: bool,
}
impl<R: Read> DecodeReader<R> {
    pub fn new(source: R, name: &str) -> Result<Self> {
        Ok(Self {
            source,
            decoder: encoding(name)?.new_decoder_with_bom_removal(),
            input: [0; 8192],
            start: 0,
            end: 0,
            output: [0; 32768],
            pos: 0,
            len: 0,
            eof: false,
            done: false,
        })
    }
}
impl<R: Read> Read for DecodeReader<R> {
    fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
        if out.is_empty() {
            return Ok(0);
        }
        while self.pos == self.len && !self.done {
            if self.start == self.end && !self.eof {
                self.end = self.source.read(&mut self.input)?;
                self.start = 0;
                self.eof = self.end == 0;
            }
            let (result, used, written) = self.decoder.decode_to_utf8_without_replacement(
                &self.input[self.start..self.end],
                &mut self.output,
                self.eof,
            );
            self.start += used;
            self.pos = 0;
            self.len = written;
            match result {
                DecoderResult::Malformed(_, _) => {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "invalid byte sequence in selected input encoding",
                    ))
                }
                DecoderResult::InputEmpty if self.eof => self.done = true,
                _ => {}
            }
        }
        let n = out.len().min(self.len - self.pos);
        out[..n].copy_from_slice(&self.output[self.pos..self.pos + n]);
        self.pos += n;
        Ok(n)
    }
}

/// Validated UTF-8 fields in one allocation. The encoding is a little-endian
/// u64 field count followed by u64 byte lengths and exact field text. It also
/// matches the v1 logical-digest stream and internal spool field framing.
#[derive(Default)]
pub struct CompactRecord {
    bytes: Vec<u8>,
}
impl CompactRecord {
    pub fn clear(&mut self) {
        self.bytes.clear();
    }
    /// Pack already-decoded UTF-8 without CSV serialization or inference.
    /// The decoded working bound includes 32 bytes per field. Charge capacity
    /// and old/new overlap before allocation; retain that charge until drop or
    /// handoff. On error the record is empty and its capacity remains owned.
    pub fn set_text_fields_reserved<'a>(
        &mut self,
        fields: impl ExactSizeIterator<Item = &'a str> + Clone,
        maximum: usize,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<()> {
        self.bytes.clear();
        let result = (|| {
            reserve(self.bytes.capacity())?;
            let (count, payload) = text_record_size(fields.clone(), maximum)?;
            let needed = count
                .checked_mul(8)
                .and_then(|n| n.checked_add(payload))
                .and_then(|n| n.checked_add(8))
                .context("decoded record size overflow")?;
            grow_buffer(&mut self.bytes, needed, 0, reserve)?;
            self.bytes.extend_from_slice(&(count as u64).to_le_bytes());
            let mut seen = 0;
            for field in fields {
                ensure!(
                    seen < count
                        && self
                            .bytes
                            .len()
                            .checked_add(8 + field.len())
                            .is_some_and(|n| n <= needed),
                    "decoded fields changed during packing"
                );
                self.bytes
                    .extend_from_slice(&(field.len() as u64).to_le_bytes());
                self.bytes.extend_from_slice(field.as_bytes());
                seen += 1;
            }
            ensure!(
                seen == count && self.bytes.len() == needed,
                "decoded fields changed during packing"
            );
            Ok(())
        })();
        if result.is_err() {
            self.bytes.clear();
        }
        result
    }
    /// Recycle storage without trusting or exposing its previous contents.
    pub fn with_storage(mut bytes: Vec<u8>) -> Self {
        bytes.clear();
        Self { bytes }
    }
    pub fn len(&self) -> usize {
        self.fields().len()
    }
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
    pub fn payload_bytes(&self) -> usize {
        self.encoded_fields().len() - 8 - 8 * self.len()
    }
    pub fn encoded_fields(&self) -> &[u8] {
        if self.bytes.is_empty() {
            &[0; 8]
        } else {
            &self.bytes
        }
    }
    pub fn capacity(&self) -> usize {
        self.bytes.capacity()
    }
    pub fn into_encoded_fields(self) -> Vec<u8> {
        if self.bytes.is_empty() {
            vec![0; 8]
        } else {
            self.bytes
        }
    }
    pub fn fields(&self) -> CompactFields<'_> {
        let bytes = self.encoded_fields();
        CompactFields {
            remaining: u64::from_le_bytes(bytes[..8].try_into().unwrap()) as usize,
            bytes: &bytes[8..],
        }
    }
}

fn text_record_size<'a>(
    fields: impl ExactSizeIterator<Item = &'a str>,
    maximum: usize,
) -> Result<(usize, usize)> {
    let count = fields.len();
    ensure!(count > 0, "decoded record has no fields");
    let descriptors = count
        .checked_mul(32)
        .context("decoded record size overflow")?;
    let mut payload = 0usize;
    let mut seen = 0usize;
    for field in fields {
        payload = payload
            .checked_add(field.len())
            .context("decoded record size overflow")?;
        ensure!(
            payload
                .checked_add(descriptors)
                .is_some_and(|n| n <= maximum),
            "decoded record exceeds max_record_bytes working limit"
        );
        seen += 1;
    }
    ensure!(seen == count, "invalid decoded field count");
    Ok((count, payload))
}

/// Copy decoded text into reusable owned fields, accounting for descriptors,
/// string capacity and allocation overlap. No type/null inference is performed.
/// On error contents are unspecified; the caller must drop rather than resume.
pub fn copy_text_fields_into_reserved<'a>(
    fields: impl ExactSizeIterator<Item = &'a str> + Clone,
    target: &mut Vec<String>,
    maximum: usize,
    reserve: &mut impl FnMut(usize) -> Result<()>,
) -> Result<()> {
    let (count, _) = text_record_size(fields.clone(), maximum)?;
    let mut payload = target.iter().map(String::capacity).sum::<usize>();
    reserve(target.capacity() * std::mem::size_of::<String>() + payload)?;
    grow_buffer(target, count.saturating_sub(target.len()), payload, reserve)?;
    target.resize_with(count, String::new);
    payload = target.iter().map(String::capacity).sum();
    let descriptors = target.capacity() * std::mem::size_of::<String>();
    reserve(descriptors + payload)?;
    let mut seen = 0;
    let mut actual = 0usize;
    for field in fields {
        actual = actual
            .checked_add(field.len())
            .context("decoded record size overflow")?;
        ensure!(
            seen < count && actual.checked_add(count * 32).is_some_and(|n| n <= maximum),
            "decoded fields changed during copying"
        );
        let slot = &mut target[seen];
        let old = slot.capacity();
        if old < field.len() || (old > 64 && field.len() < old / 4) {
            reserve(
                descriptors
                    .checked_add(payload)
                    .and_then(|n| n.checked_add(field.len()))
                    .context("decoded record size overflow")?,
            )?;
            let mut next = String::new();
            let result = (|| -> Result<()> {
                next.try_reserve_exact(field.len())?;
                reserve(
                    descriptors
                        .checked_add(payload)
                        .and_then(|n| n.checked_add(next.capacity()))
                        .context("decoded record size overflow")?,
                )?;
                Ok(())
            })();
            if let Err(error) = result {
                drop(next);
                reserve(descriptors + payload)?;
                return Err(error);
            }
            next.push_str(field);
            payload = payload - old + next.capacity();
            *slot = next;
            reserve(descriptors + payload)?;
        } else {
            slot.clear();
            slot.push_str(field);
        }
        seen += 1;
    }
    ensure!(seen == count, "decoded fields changed during copying");
    Ok(())
}
#[derive(Clone)]
pub struct CompactFields<'a> {
    remaining: usize,
    bytes: &'a [u8],
}
impl<'a> Iterator for CompactFields<'a> {
    type Item = &'a str;
    fn next(&mut self) -> Option<&'a str> {
        if self.remaining == 0 {
            return None;
        }
        let length = u64::from_le_bytes(self.bytes[..8].try_into().unwrap()) as usize;
        // SAFETY: only CompactRecord::fields constructs this iterator. Its private
        // buffer contains fields validated by ReservedRecord::field/field_slice,
        // or copied from &str by set_text_fields_reserved. Recycled storage is
        // cleared, and this shared borrow prevents mutation during traversal.
        let field = unsafe { std::str::from_utf8_unchecked(&self.bytes[8..8 + length]) };
        self.bytes = &self.bytes[8 + length..];
        self.remaining -= 1;
        Some(field)
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        (self.remaining, Some(self.remaining))
    }
}
impl ExactSizeIterator for CompactFields<'_> {}

pub struct Parser<R> {
    reader: R,
    settings: CsvSettings,
    maximum: usize,
    pub record: u64,
    scratch: Vec<u8>,
    compact_hint: usize,
}
impl<R: BufRead> Parser<R> {
    pub fn new(reader: R, settings: CsvSettings, maximum: usize) -> Self {
        Self {
            reader,
            settings,
            maximum,
            record: 0,
            scratch: Vec::new(),
            compact_hint: 0,
        }
    }
    fn byte(&mut self) -> Result<Option<u8>> {
        let data = self.reader.fill_buf()?;
        if data.is_empty() {
            return Ok(None);
        }
        let byte = data[0];
        self.reader.consume(1);
        Ok(Some(byte))
    }
    pub fn next_record(&mut self) -> Result<Option<Vec<String>>> {
        let mut fields = Vec::new();
        Ok(self.next_record_into(&mut fields)?.then_some(fields))
    }
    /// Reuse field storage when the caller does not retain the previous record.
    /// On EOF the destination is empty; on error its contents are unspecified.
    pub fn next_record_into(&mut self, fields: &mut Vec<String>) -> Result<bool> {
        loop {
            let result = self
                .parse_record(fields)
                .with_context(|| format!("CSV record {}", self.record + 1))?;
            match result {
                Some(0) if self.settings.skip_empty_lines => {
                    self.record += 1;
                    continue;
                }
                Some(0) => bail!(
                    "bare blank CSV record {} (enable skip_empty_lines to ignore)",
                    self.record + 1
                ),
                Some(count) => {
                    fields.truncate(count);
                    // A wide field moving between columns must not accumulate
                    // a maximum-sized allocation in every reused column.
                    if fields.iter().map(String::capacity).sum::<usize>()
                        > self.maximum.saturating_mul(2)
                    {
                        for field in fields.iter_mut() {
                            field.shrink_to_fit();
                        }
                    }
                    self.record += 1;
                    return Ok(true);
                }
                None => {
                    fields.clear();
                    return Ok(false);
                }
            }
        }
    }
    /// Parse owned fields while charging descriptor, string and scratch capacity
    /// before allocation, including old/new growth overlap. Keep the charge live
    /// through consumer handoff. On failure parsing must not be resumed; fields
    /// and scratch remain owned by the caller/parser and must stay charged.
    pub fn next_record_into_reserved(
        &mut self,
        fields: &mut Vec<String>,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        let payload = fields.iter().map(String::capacity).sum::<usize>();
        reserve(
            self.scratch.capacity() + fields.capacity() * std::mem::size_of::<String>() + payload,
        )?;
        let mut target = ReservedOwned {
            fields,
            reserve,
            scratch_capacity: self.scratch.capacity(),
            payload_capacity: payload,
        };
        loop {
            let result = self
                .parse_record(&mut target)
                .with_context(|| format!("CSV record {}", self.record + 1))?;
            match result {
                Some(0) if self.settings.skip_empty_lines => self.record += 1,
                Some(0) => bail!(
                    "bare blank CSV record {} (enable skip_empty_lines to ignore)",
                    self.record + 1
                ),
                Some(count) => {
                    target.fields.truncate(count);
                    target.payload_capacity = target.fields.iter().map(String::capacity).sum();
                    target.update()?;
                    if target.payload_capacity > self.maximum.saturating_mul(2) {
                        target.shrink_fields()?;
                    }
                    self.record += 1;
                    return Ok(true);
                }
                None => {
                    target.fields.clear();
                    target.payload_capacity = 0;
                    target.update()?;
                    return Ok(false);
                }
            }
        }
    }
    /// Parse with the same strict state machine and working limit, avoiding
    /// owned per-field strings. On EOF/error the destination is empty.
    pub fn next_compact_record_into(&mut self, fields: &mut CompactRecord) -> Result<bool> {
        self.next_compact_record_into_reserved(fields, &mut |_| Ok(()))
    }
    /// Charge the combined scratch/record capacity before growth, including
    /// old/new allocation overlap. The caller retains the charge until these
    /// buffers are dropped or their ownership is transferred. On denial the
    /// destination is empty and parsing must not be resumed.
    pub fn next_compact_record_into_reserved(
        &mut self,
        fields: &mut CompactRecord,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        let result = self.compact_record_reserved(fields, reserve);
        if result.is_err() {
            fields.bytes.clear();
        }
        result
    }
    pub fn scratch_capacity(&self) -> usize {
        self.scratch.capacity()
    }
    fn compact_record_reserved(
        &mut self,
        record: &mut CompactRecord,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        reserve(self.scratch.capacity() + record.capacity())?;
        let mut target = ReservedRecord {
            record,
            reserve,
            scratch_capacity: self.scratch.capacity(),
        };
        let fields = &mut target;
        if fields.record.bytes.capacity() == 0 {
            // Retaining a row transfers its allocation. Seed the next buffer
            // from the previous size instead of growing once per short field;
            // cap the hint so a rare wide record cannot inflate following rows.
            grow_buffer(
                &mut fields.record.bytes,
                self.compact_hint.max(8),
                fields.scratch_capacity,
                fields.reserve,
            )?;
        }
        loop {
            fields.record.bytes.clear();
            grow_buffer(
                &mut fields.record.bytes,
                8,
                fields.scratch_capacity,
                fields.reserve,
            )?;
            fields.record.bytes.extend_from_slice(&[0; 8]);
            let result = self
                .parse_record(fields)
                .with_context(|| format!("CSV record {}", self.record + 1));
            let count = match result {
                Ok(Some(0)) if self.settings.skip_empty_lines => {
                    self.record += 1;
                    continue;
                }
                Ok(Some(0)) => {
                    fields.record.bytes.clear();
                    bail!(
                        "bare blank CSV record {} (enable skip_empty_lines to ignore)",
                        self.record + 1
                    );
                }
                Ok(Some(count)) => count,
                Ok(None) => {
                    fields.record.bytes.clear();
                    return Ok(false);
                }
                Err(error) => {
                    fields.record.bytes.clear();
                    return Err(error);
                }
            };
            fields.record.bytes[..8].copy_from_slice(&(count as u64).to_le_bytes());
            self.compact_hint = fields.record.bytes.len().min(64 * 1024);
            self.record += 1;
            return Ok(true);
        }
    }
    fn parse_record(&mut self, fields: &mut impl FieldTarget) -> Result<Option<usize>> {
        // States: 0 start, 1 unquoted, 2 quoted, 3 closed quote, 4 escaped.
        let mut state = 0;
        let mut count = 0;
        let mut field = std::mem::take(&mut self.scratch);
        field.clear();
        let mut bytes = 0usize;
        let mut touched = false;
        let result = (|| {
            loop {
                // Copy ordinary spans in one go. Keep all structural bytes on the
                // scalar state machine, including CRLF's historical byte accounting.
                if state <= 2 {
                    let data = self.reader.fill_buf()?;
                    let n = if state == 2 {
                        memchr::memchr2(
                            self.settings.quote as u8,
                            self.settings.escape.unwrap_or(self.settings.quote) as u8,
                            data,
                        )
                        .unwrap_or(data.len())
                    } else {
                        let end = memchr::memchr3(
                            self.settings.delimiter as u8,
                            self.settings.quote as u8,
                            b'\n',
                            data,
                        )
                        .unwrap_or(data.len());
                        memchr::memchr(b'\r', &data[..end]).unwrap_or(end)
                    };
                    if n > 0 {
                        bytes = bytes.saturating_add(n);
                        ensure!(
                            bytes.saturating_add(count * 32) <= self.maximum,
                            "record exceeds max_record_bytes working limit"
                        );
                        // A complete unquoted field can be copied straight into
                        // an admitted destination. Structural/quoted/split
                        // fields keep the strict scalar path and scratch owner.
                        let end = data.get(n).copied();
                        if state == 0
                            && field.is_empty()
                            && end.is_some_and(|b| b == self.settings.delimiter as u8 || b == b'\n')
                            && fields.field_slice(
                                count,
                                &data[..n],
                                bytes.saturating_add(1).saturating_add(count * 32),
                                self.maximum,
                            )?
                        {
                            self.reader.consume(n + 1);
                            bytes += 1;
                            count += 1;
                            touched = true;
                            if end == Some(b'\n') {
                                return Ok(Some(count));
                            }
                            continue;
                        }
                        fields.reserve_scratch(&mut field, n)?;
                        field.extend_from_slice(&data[..n]);
                        self.reader.consume(n);
                        touched = true;
                        if state == 0 {
                            state = 1;
                        }
                    }
                }
                let byte = self.byte()?;
                let Some(b) = byte else {
                    ensure!(state != 2 && state != 4, "unterminated quoted field");
                    if !touched {
                        return Ok(None);
                    }
                    finish_field(fields, &mut count, &mut field)?;
                    return Ok(Some(count));
                };
                bytes += 1;
                ensure!(
                    bytes.saturating_add(count * 32) <= self.maximum,
                    "record exceeds max_record_bytes working limit"
                );
                if state == 4 {
                    fields.reserve_scratch(&mut field, 1)?;
                    field.push(b);
                    state = 2;
                    touched = true;
                    continue;
                }
                if state == 2 {
                    if self.settings.escape.map(|e| e as u8) == Some(b) {
                        state = 4;
                    } else if b == self.settings.quote as u8 {
                        state = 3;
                    } else {
                        fields.reserve_scratch(&mut field, 1)?;
                        field.push(b);
                    }
                    touched = true;
                    continue;
                }
                if state == 3 && b == self.settings.quote as u8 && self.settings.escape.is_none() {
                    fields.reserve_scratch(&mut field, 1)?;
                    field.push(b);
                    state = 2;
                    continue;
                }
                if b == b'\n' || b == b'\r' {
                    if b == b'\r' {
                        ensure!(
                            self.byte()? == Some(b'\n'),
                            "bare CR outside quoted field; expected CRLF"
                        );
                    }
                    if !touched {
                        return Ok(Some(0));
                    }
                    finish_field(fields, &mut count, &mut field)?;
                    return Ok(Some(count));
                }
                if b == self.settings.delimiter as u8 {
                    finish_field(fields, &mut count, &mut field)?;
                    state = 0;
                    touched = true;
                    continue;
                }
                ensure!(state != 3, "unexpected text after closing quote");
                if b == self.settings.quote as u8 {
                    ensure!(state == 0, "quote inside unquoted field");
                    state = 2;
                } else {
                    fields.reserve_scratch(&mut field, 1)?;
                    field.push(b);
                    state = 1;
                }
                touched = true;
            }
        })();
        self.scratch = field;
        result
    }
}

trait FieldTarget {
    fn field(&mut self, index: usize, bytes: &mut Vec<u8>) -> Result<()>;
    fn field_slice(
        &mut self,
        _index: usize,
        _bytes: &[u8],
        _working_bytes: usize,
        _maximum: usize,
    ) -> Result<bool> {
        Ok(false)
    }
    fn reserve_scratch(&mut self, _bytes: &mut Vec<u8>, _additional: usize) -> Result<()> {
        Ok(())
    }
}
impl FieldTarget for Vec<String> {
    fn field(&mut self, index: usize, bytes: &mut Vec<u8>) -> Result<()> {
        if let Some(field) = self.get_mut(index) {
            let value = std::str::from_utf8(bytes)?;
            field.clear();
            field.push_str(value);
            bytes.clear();
        } else {
            self.push(String::from_utf8(std::mem::take(bytes))?);
        }
        Ok(())
    }
}
struct ReservedOwned<'a, F> {
    fields: &'a mut Vec<String>,
    reserve: &'a mut F,
    scratch_capacity: usize,
    payload_capacity: usize,
}
impl<F: FnMut(usize) -> Result<()>> ReservedOwned<'_, F> {
    fn total(&self) -> usize {
        self.scratch_capacity
            + self.payload_capacity
            + self.fields.capacity() * std::mem::size_of::<String>()
    }
    fn update(&mut self) -> Result<()> {
        let total = self.total();
        (self.reserve)(total)
    }
    fn shrink_fields(&mut self) -> Result<()> {
        for index in 0..self.fields.len() {
            let field = &self.fields[index];
            if field.len() == field.capacity() {
                continue;
            }
            let old = field.capacity();
            let retained = self.total();
            (self.reserve)(retained + field.len())?;
            let mut next = String::new();
            let result = (|| -> Result<()> {
                next.try_reserve_exact(field.len())?;
                (self.reserve)(retained + next.capacity())?;
                Ok(())
            })();
            if let Err(error) = result {
                drop(next);
                self.update()?;
                return Err(error);
            }
            next.push_str(field);
            self.payload_capacity = self.payload_capacity - old + next.capacity();
            self.fields[index] = next;
            self.update()?;
        }
        Ok(())
    }
}
impl<F: FnMut(usize) -> Result<()>> FieldTarget for ReservedOwned<'_, F> {
    fn field_slice(
        &mut self,
        index: usize,
        bytes: &[u8],
        working_bytes: usize,
        maximum: usize,
    ) -> Result<bool> {
        let Some(field) = self.fields.get(index) else {
            return Ok(false);
        };
        ensure!(
            working_bytes <= maximum,
            "record exceeds max_record_bytes working limit"
        );
        let value = std::str::from_utf8(bytes)?;
        let old = field.capacity();
        if value.len() <= old {
            let field = &mut self.fields[index];
            field.clear();
            field.push_str(value);
            return Ok(true);
        }
        let other = self.total() - old;
        let mut buffer = std::mem::take(&mut self.fields[index]).into_bytes();
        buffer.clear();
        let result = grow_buffer(&mut buffer, value.len(), other, self.reserve);
        if result.is_ok() {
            buffer.extend_from_slice(value.as_bytes());
        }
        self.payload_capacity = self.payload_capacity - old + buffer.capacity();
        self.fields[index] = String::from_utf8(buffer)?;
        result?;
        self.update()?;
        Ok(true)
    }

    fn reserve_scratch(&mut self, bytes: &mut Vec<u8>, additional: usize) -> Result<()> {
        let other = self.total() - self.scratch_capacity;
        grow_buffer(bytes, additional, other, self.reserve)?;
        self.scratch_capacity = bytes.capacity();
        Ok(())
    }
    fn field(&mut self, index: usize, bytes: &mut Vec<u8>) -> Result<()> {
        let value = std::str::from_utf8(bytes)?;
        if index < self.fields.len() {
            let old = self.fields[index].capacity();
            if value.len() <= old {
                // Reusing an already charged allocation changes no capacity.
                let field = &mut self.fields[index];
                field.clear();
                field.push_str(value);
                bytes.clear();
                return Ok(());
            }
            let other = self.total() - old;
            let mut buffer = std::mem::take(&mut self.fields[index]).into_bytes();
            buffer.clear();
            let result = grow_buffer(&mut buffer, value.len(), other, self.reserve);
            if result.is_ok() {
                buffer.extend_from_slice(value.as_bytes());
            }
            self.payload_capacity = self.payload_capacity - old + buffer.capacity();
            self.fields[index] = String::from_utf8(buffer)?;
            result?;
            bytes.clear();
        } else {
            grow_buffer(
                self.fields,
                1,
                self.scratch_capacity + self.payload_capacity,
                self.reserve,
            )?;
            self.payload_capacity += bytes.capacity();
            self.scratch_capacity = 0;
            self.fields.push(String::from_utf8(std::mem::take(bytes))?);
        }
        self.update()
    }
}
struct ReservedRecord<'a, F> {
    record: &'a mut CompactRecord,
    reserve: &'a mut F,
    scratch_capacity: usize,
}
impl<F: FnMut(usize) -> Result<()>> FieldTarget for ReservedRecord<'_, F> {
    fn field_slice(
        &mut self,
        _index: usize,
        bytes: &[u8],
        working_bytes: usize,
        maximum: usize,
    ) -> Result<bool> {
        ensure!(
            working_bytes <= maximum,
            "record exceeds max_record_bytes working limit"
        );
        std::str::from_utf8(bytes)?;
        grow_buffer(
            &mut self.record.bytes,
            8 + bytes.len(),
            self.scratch_capacity,
            self.reserve,
        )?;
        self.record
            .bytes
            .extend_from_slice(&(bytes.len() as u64).to_le_bytes());
        self.record.bytes.extend_from_slice(bytes);
        Ok(true)
    }
    fn reserve_scratch(&mut self, bytes: &mut Vec<u8>, additional: usize) -> Result<()> {
        grow_buffer(bytes, additional, self.record.capacity(), self.reserve)?;
        self.scratch_capacity = bytes.capacity();
        Ok(())
    }
    fn field(&mut self, _index: usize, bytes: &mut Vec<u8>) -> Result<()> {
        std::str::from_utf8(bytes)?;
        grow_buffer(
            &mut self.record.bytes,
            8 + bytes.len(),
            self.scratch_capacity,
            self.reserve,
        )?;
        self.record
            .bytes
            .extend_from_slice(&(bytes.len() as u64).to_le_bytes());
        self.record.bytes.extend_from_slice(bytes);
        bytes.clear();
        Ok(())
    }
}
/// Explicit separate allocation makes growth overlap predictable on all targets.
fn grow_buffer<T>(
    bytes: &mut Vec<T>,
    additional: usize,
    other: usize,
    reserve: &mut impl FnMut(usize) -> Result<()>,
) -> Result<()> {
    let needed = bytes
        .len()
        .checked_add(additional)
        .context("CSV buffer size overflow")?;
    if needed <= bytes.capacity() {
        return Ok(());
    }
    let old = bytes.capacity();
    let capacity = needed.max(old.saturating_mul(2)).max(8);
    let element = std::mem::size_of::<T>();
    let retained = other
        .checked_add(old * element)
        .context("CSV buffer size overflow")?;
    reserve(
        retained
            .checked_add(capacity * element)
            .context("CSV buffer size overflow")?,
    )?;
    let mut next = Vec::new();
    let result = (|| -> Result<()> {
        next.try_reserve_exact(capacity)?;
        reserve(
            retained
                .checked_add(next.capacity() * element)
                .context("CSV buffer size overflow")?,
        )?;
        Ok(())
    })();
    if let Err(error) = result {
        drop(next);
        reserve(retained)?;
        return Err(error);
    }
    next.append(bytes);
    *bytes = next;
    reserve(other + bytes.capacity() * element)
}
fn finish_field(
    fields: &mut impl FieldTarget,
    count: &mut usize,
    bytes: &mut Vec<u8>,
) -> Result<()> {
    fields.field(*count, bytes)?;
    *count += 1;
    Ok(())
}

pub fn serialize(fields: &[String], settings: &CsvSettings) -> Result<Vec<u8>> {
    let mut serializer = Serializer::new(settings)?;
    serializer.serialize(fields)?;
    Ok(if serializer.encoding == UTF_8 {
        serializer.text.into_bytes()
    } else {
        serializer.encoded
    })
}

struct SerializationSettings {
    delimiter: char,
    quote: char,
    escape: Option<char>,
    crlf: bool,
}
/// Reuses encoding scratch across records and resolves the output encoding once.
/// Returned bytes remain valid until the next record is serialized.
pub struct Serializer {
    settings: SerializationSettings,
    encoding: &'static Encoding,
    text: String,
    encoded: Vec<u8>,
}
impl Serializer {
    pub fn bytes(&self) -> &[u8] {
        if self.encoding == UTF_8 {
            self.text.as_bytes()
        } else {
            &self.encoded
        }
    }
    pub fn new(settings: &CsvSettings) -> Result<Self> {
        Ok(Self {
            settings: SerializationSettings {
                delimiter: settings.delimiter,
                quote: settings.quote,
                escape: settings.escape,
                crlf: settings.line_ending == "crlf",
            },
            encoding: encoding(&settings.encoding)?,
            text: String::new(),
            encoded: Vec::new(),
        })
    }
    pub fn serialize(&mut self, fields: &[String]) -> Result<&[u8]> {
        self.serialize_fields(fields.iter().map(String::as_str))
    }
    /// Serialize borrowed fields without materializing owned strings.
    pub fn serialize_fields<'a>(
        &mut self,
        fields: impl IntoIterator<Item = &'a str>,
    ) -> Result<&[u8]> {
        self.text.clear();
        write_csv_text(&self.settings, fields, &mut self.text)?;
        if self.encoding == UTF_8 {
            return Ok(self.text.as_bytes());
        }
        self.encoded.clear();
        if self.encoding == UTF_16LE {
            self.encoded
                .extend(self.text.encode_utf16().flat_map(u16::to_le_bytes));
        } else if self.encoding == UTF_16BE {
            self.encoded
                .extend(self.text.encode_utf16().flat_map(u16::to_be_bytes));
        } else {
            let (data, _, errors) = self.encoding.encode(&self.text);
            ensure!(
                !errors,
                "output contains text unrepresentable in {}",
                self.encoding.name()
            );
            self.encoded.extend_from_slice(&data);
        }
        Ok(&self.encoded)
    }
    /// Serialize while reserving actual scratch capacities and old/new growth
    /// overlap before allocation. Keep the final charge until this serializer
    /// is dropped. Failure retains any live buffers and their current charge;
    /// a caller may retry after releasing competing reservations.
    pub fn serialize_fields_reserved<'a>(
        &mut self,
        fields: impl IntoIterator<Item = &'a str> + Clone,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<&[u8]> {
        reserve(self.capacity())?;
        self.text.clear();
        let sizing_fields = fields.clone();
        let settings = &self.settings;
        let mut target = ReservedText {
            text: &mut self.text,
            other: self.encoded.capacity(),
            reserve,
            planned_size: || serialized_text_size(settings, sizing_fields.clone()),
        };
        write_csv_text(settings, fields, &mut target)?;
        if self.encoding == UTF_8 {
            return Ok(self.text.as_bytes());
        }
        self.encoded.clear();
        if self.encoding == UTF_16LE || self.encoding == UTF_16BE {
            let needed = self
                .text
                .encode_utf16()
                .count()
                .checked_mul(2)
                .context("CSV serialization size overflow")?;
            grow_buffer(&mut self.encoded, needed, self.text.capacity(), reserve)?;
            if self.encoding == UTF_16LE {
                self.encoded
                    .extend(self.text.encode_utf16().flat_map(u16::to_le_bytes));
            } else {
                self.encoded
                    .extend(self.text.encode_utf16().flat_map(u16::to_be_bytes));
            }
        } else {
            let mut encoder = self.encoding.new_encoder();
            let needed = encoder
                .max_buffer_length_from_utf8_without_replacement(self.text.len())
                .context("CSV serialization size overflow")?;
            grow_buffer(&mut self.encoded, needed, self.text.capacity(), reserve)?;
            self.encoded.resize(needed, 0);
            let (result, read, written) =
                encoder.encode_from_utf8_without_replacement(&self.text, &mut self.encoded, true);
            self.encoded.truncate(written);
            ensure!(
                matches!(result, EncoderResult::InputEmpty) && read == self.text.len(),
                "output contains text unrepresentable in {}",
                self.encoding.name()
            );
        }
        reserve(self.capacity())?;
        Ok(&self.encoded)
    }
    /// Heap scratch retained between records; settings and encoder state are inline.
    pub fn capacity(&self) -> usize {
        self.text.capacity() + self.encoded.capacity()
    }
}

#[inline]
fn needs_quotes(settings: &SerializationSettings, value: &str) -> bool {
    if value.is_empty() {
        return true;
    }
    if settings.delimiter.is_ascii() && settings.quote.is_ascii() {
        // ASCII structural bytes cannot occur inside another UTF-8 scalar.
        // Keep character matching for the public serializer's Unicode dialects.
        let bytes = value.as_bytes();
        memchr::memchr3(settings.delimiter as u8, settings.quote as u8, b'\n', bytes).is_some()
            || memchr::memchr(b'\r', bytes).is_some()
    } else {
        value.contains([settings.delimiter, settings.quote, '\r', '\n'])
    }
}

fn serialized_text_size<'a>(
    settings: &SerializationSettings,
    fields: impl IntoIterator<Item = &'a str>,
) -> Result<usize> {
    let mut needed = if settings.crlf { 2usize } else { 1 };
    for (index, value) in fields.into_iter().enumerate() {
        let quoted = needs_quotes(settings, value);
        let escaped = if quoted {
            value
                .chars()
                .filter(|c| *c == settings.quote || settings.escape == Some(*c))
                .count()
                .checked_mul(settings.escape.unwrap_or(settings.quote).len_utf8())
                .context("CSV serialization size overflow")?
        } else {
            0
        };
        needed = needed
            .checked_add(value.len())
            .and_then(|n| n.checked_add(escaped))
            .and_then(|n| {
                n.checked_add(if quoted {
                    2 * settings.quote.len_utf8()
                } else {
                    0
                })
            })
            .and_then(|n| {
                n.checked_add(if index > 0 {
                    settings.delimiter.len_utf8()
                } else {
                    0
                })
            })
            .context("CSV serialization size overflow")?;
    }
    Ok(needed)
}

trait TextTarget {
    fn push_char(&mut self, value: char) -> Result<()>;
    fn push_text(&mut self, value: &str) -> Result<()>;
}
impl TextTarget for String {
    fn push_char(&mut self, value: char) -> Result<()> {
        self.push(value);
        Ok(())
    }
    fn push_text(&mut self, value: &str) -> Result<()> {
        self.push_str(value);
        Ok(())
    }
}
struct ReservedText<'a, F, P> {
    text: &'a mut String,
    other: usize,
    reserve: &'a mut F,
    planned_size: P,
}
impl<F: FnMut(usize) -> Result<()>, P: FnMut() -> Result<usize>> ReservedText<'_, F, P> {
    #[inline]
    fn grow(&mut self, additional: usize) -> Result<()> {
        let needed = self
            .text
            .len()
            .checked_add(additional)
            .context("CSV serialization size overflow")?;
        if needed <= self.text.capacity() {
            return Ok(());
        }
        self.grow_to(needed)
    }
    #[cold]
    fn grow_to(&mut self, needed: usize) -> Result<()> {
        let old = self.text.capacity();
        let capacity = (self.planned_size)()?
            .max(needed)
            .max(old.saturating_mul(2))
            .max(8);
        let retained = old
            .checked_add(self.other)
            .context("CSV serialization size overflow")?;
        (self.reserve)(
            retained
                .checked_add(capacity)
                .context("CSV serialization size overflow")?,
        )?;
        let mut next = String::new();
        let result = (|| -> Result<()> {
            next.try_reserve_exact(capacity)?;
            (self.reserve)(
                retained
                    .checked_add(next.capacity())
                    .context("CSV serialization size overflow")?,
            )
        })();
        if let Err(error) = result {
            drop(next);
            (self.reserve)(retained)?;
            return Err(error);
        }
        next.push_str(self.text);
        *self.text = next;
        (self.reserve)(self.other + self.text.capacity())?;
        Ok(())
    }
}
impl<F: FnMut(usize) -> Result<()>, P: FnMut() -> Result<usize>> TextTarget
    for ReservedText<'_, F, P>
{
    #[inline]
    fn push_char(&mut self, value: char) -> Result<()> {
        self.grow(value.len_utf8())?;
        self.text.push(value);
        Ok(())
    }
    #[inline]
    fn push_text(&mut self, value: &str) -> Result<()> {
        self.grow(value.len())?;
        self.text.push_str(value);
        Ok(())
    }
}
fn write_csv_text<'a>(
    settings: &SerializationSettings,
    fields: impl IntoIterator<Item = &'a str>,
    text: &mut impl TextTarget,
) -> Result<()> {
    for (i, value) in fields.into_iter().enumerate() {
        if i != 0 {
            text.push_char(settings.delimiter)?;
        }
        let quoted = needs_quotes(settings, value);
        if quoted {
            text.push_char(settings.quote)?;
            let escape = settings.escape.unwrap_or(settings.quote);
            let mut start = 0;
            for (index, special) in value.match_indices([settings.quote, escape]) {
                text.push_text(&value[start..index])?;
                text.push_char(escape)?;
                text.push_text(special)?;
                start = index + special.len();
            }
            text.push_text(&value[start..])?;
            text.push_char(settings.quote)?;
        } else {
            text.push_text(value)?;
        }
    }
    text.push_text(if settings.crlf { "\r\n" } else { "\n" })?;
    Ok(())
}

pub fn encode(text: &str, name: &str) -> Result<Vec<u8>> {
    let enc = encoding(name)?;
    if enc == UTF_16LE {
        return Ok(text.encode_utf16().flat_map(u16::to_le_bytes).collect());
    }
    if enc == UTF_16BE {
        return Ok(text.encode_utf16().flat_map(u16::to_be_bytes).collect());
    }
    let (data, _, errors) = enc.encode(text);
    ensure!(
        !errors,
        "output contains text unrepresentable in {}",
        enc.name()
    );
    Ok(data.into_owned())
}
pub fn bom(settings: &CsvSettings) -> Result<Vec<u8>> {
    if !settings.bom {
        return Ok(vec![]);
    }
    let enc = encoding(&settings.encoding)?;
    if enc == UTF_8 {
        Ok(vec![0xef, 0xbb, 0xbf])
    } else if enc == UTF_16LE {
        Ok(vec![0xff, 0xfe])
    } else if enc == UTF_16BE {
        Ok(vec![0xfe, 0xff])
    } else {
        bail!("BOM is only supported for UTF encodings")
    }
}

#[cfg(test)]
mod quote_predicate_contracts {
    use super::*;

    #[test]
    fn byte_search_matches_character_quote_rules_at_alignment_edges() {
        for (delimiter, quote) in [
            (',', '"'),
            (';', '\''),
            ('\r', '\n'),
            ('\0', '\0'),
            ('\u{7f}', ':'),
            ('界', '"'),
            (',', '界'),
            ('界', '§'),
        ] {
            let settings = SerializationSettings {
                delimiter,
                quote,
                escape: None,
                crlf: false,
            };
            for padding in [0, 1, 2, 7, 15, 16, 31, 32, 63, 64] {
                for character in (0..=127).map(|n| char::from_u32(n).unwrap()).chain([
                    '\u{80}',
                    '\u{7ff}',
                    '\u{800}',
                    '界',
                    '§',
                    '\u{d7ff}',
                    '\u{e000}',
                    '\u{ffff}',
                    '\u{10000}',
                    '\u{10ffff}',
                ]) {
                    let value = format!(
                        "{}{}{}",
                        "x".repeat(padding),
                        character,
                        "界".repeat(padding)
                    );
                    let expected = value.contains([delimiter, quote, '\r', '\n']);
                    assert_eq!(
                        needs_quotes(&settings, &value),
                        expected,
                        "dialect {delimiter:?}/{quote:?}, padding {padding}, char {character:?}"
                    );
                }
            }
            assert!(needs_quotes(&settings, ""));
        }
    }
}
