//! Opt-in spill adapter. Public consumers still see the exact v1 row stream.
//! Blocks share field-count metadata; lengths are bounded u32 values. Payloads
//! stream through fixed buffers, so a wide row is never retained per merge run.
use super::*;

const MAGIC: &[u8; 8] = b"CHOPSB01";
const MAX_ROWS: u32 = 256;
const TARGET_BYTES: u64 = 64 * 1024;
const READ_BUFFER: usize = DISK_READ_BUFFER - 4096 - std::mem::size_of::<Decoder>();

pub(super) enum SpillFile {
    Raw(DiskFile),
    Blocked(Box<Encoder>),
}
impl From<DiskFile> for SpillFile {
    fn from(file: DiskFile) -> Self {
        Self::Raw(file)
    }
}
impl std::ops::Deref for SpillFile {
    type Target = DiskFile;
    fn deref(&self) -> &DiskFile {
        match self {
            Self::Raw(f) => f,
            Self::Blocked(e) => e.writer.as_ref().unwrap().get_ref(),
        }
    }
}
impl SpillFile {
    pub(super) fn new(ctx: &Context) -> Result<Self> {
        let file = ctx.file()?;
        let mut reservation = Reservation::new(ctx);
        // Optional construction pressure falls back to the existing format.
        if reservation.resize(std::mem::size_of::<Encoder>()).is_err() {
            ctx.budget
                .compact_spill_fallbacks
                .fetch_add(1, AtomicOrdering::Relaxed);
            return Ok(Self::Raw(file));
        }
        ctx.budget
            .compact_spill_files
            .fetch_add(1, AtomicOrdering::Relaxed);
        Ok(Self::Blocked(Box::new(Encoder {
            writer: Some(BufWriter::with_capacity(0, file)),
            reservation,
            maximum: ctx.max_record,
            phase: Phase::Id,
            word: [0; 8],
            word_len: 0,
            remaining: 0,
            fields: 0,
            row_remaining: 0,
            width: None,
            rows: 0,
            start: 0,
            source_bytes: 0,
            failed: false,
        })))
    }
    /// The caller owns the existing fixed writer-buffer reservation. Blocked
    /// files place that buffer inside the adapter; raw files place it outside.
    /// Exactly one payload buffer is allocated in either representation.
    pub(super) fn buffered(mut self, capacity: usize) -> Result<BufWriter<Self>> {
        let outer = match &mut self {
            Self::Raw(_) => capacity,
            Self::Blocked(e) => {
                let file = e
                    .writer
                    .take()
                    .unwrap()
                    .into_inner()
                    .map_err(|e| e.into_error())?;
                e.writer = Some(BufWriter::with_capacity(capacity, file));
                0
            }
        };
        Ok(BufWriter::with_capacity(outer, self))
    }
    pub(super) fn reader(&self) -> Result<BufReader<SpillReader>> {
        let raw = DiskReader {
            file: self
                .file
                .as_ref()
                .expect("temporary file already closed")
                .reopen()?,
            budget: self.budget.clone(),
        };
        let reader = match self {
            Self::Raw(_) => SpillReader::Raw(raw),
            Self::Blocked(e) => {
                ensure!(
                    !e.failed
                        && e.phase == Phase::Id
                        && e.word_len == 0
                        && e.rows == 0
                        && e.writer.as_ref().unwrap().buffer().is_empty(),
                    "compact spill must be flushed before reading"
                );
                SpillReader::Blocked(Box::new(Decoder {
                    source: BufReader::with_capacity(READ_BUFFER, raw),
                    maximum: e.maximum,
                    phase: Phase::Block,
                    word: [0; 8],
                    word_pos: 0,
                    word_end: 0,
                    remaining: 0,
                    rows: 0,
                    fields: 0,
                    row_remaining: 0,
                    width: None,
                    failed: false,
                }))
            }
        };
        // Row cursors already reserve DISK_READ_BUFFER. Divide that fixed grant
        // between the physical buffer, decoder box and exposed v1 buffer.
        let capacity = if matches!(&reader, SpillReader::Blocked(_)) {
            DISK_READ_BUFFER - reader_bytes()
        } else {
            DISK_READ_BUFFER
        };
        Ok(BufReader::with_capacity(capacity, reader))
    }
}
impl Write for SpillFile {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        match self {
            Self::Raw(f) => f.write(bytes),
            Self::Blocked(e) => {
                if e.failed {
                    return Err(io::Error::other("compact spill writer already failed"));
                }
                if let Err(error) = e.feed(bytes) {
                    e.failed = true;
                    return Err(io::Error::other(error));
                }
                Ok(bytes.len())
            }
        }
    }
    fn flush(&mut self) -> io::Result<()> {
        match self {
            Self::Raw(f) => f.flush(),
            Self::Blocked(e) => {
                if e.failed {
                    return Err(io::Error::other("compact spill writer already failed"));
                }
                match e.finish() {
                    Ok(()) => Ok(()),
                    Err(error) => {
                        e.failed = true;
                        Err(io::Error::other(error))
                    }
                }
            }
        }
    }
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Phase {
    Block,
    Row,
    Id,
    Ordinal,
    KeyLength,
    Key,
    Count,
    Length,
    Field,
    End,
}

pub(super) struct Encoder {
    writer: Option<BufWriter<DiskFile>>,
    reservation: Reservation,
    maximum: usize,
    phase: Phase,
    word: [u8; 8],
    word_len: usize,
    remaining: usize,
    fields: usize,
    row_remaining: usize,
    width: Option<usize>,
    rows: u32,
    start: u64,
    source_bytes: u64,
    failed: bool,
}
impl Encoder {
    fn position(&self) -> u64 {
        let w = self.writer.as_ref().unwrap();
        w.get_ref().len() + w.buffer().len() as u64
    }
    fn close_block(&mut self) -> Result<()> {
        if self.rows == 0 {
            return Ok(());
        }
        let w = self.writer.as_mut().unwrap();
        w.write_all(&[0])?;
        w.write_all(&self.rows.to_le_bytes())?;
        let position = self.position();
        let file = self.writer.as_ref().unwrap().get_ref();
        file.budget
            .compact_spill_blocks
            .fetch_add(1, AtomicOrdering::Relaxed);
        file.budget
            .compact_spill_rows
            .fetch_add(self.rows as u64, AtomicOrdering::Relaxed);
        file.budget
            .compact_spill_source_bytes
            .fetch_add(self.source_bytes, AtomicOrdering::Relaxed);
        file.budget
            .compact_spill_stored_bytes
            .fetch_add(position - self.start, AtomicOrdering::Relaxed);
        self.rows = 0;
        self.source_bytes = 0;
        self.width = None;
        Ok(())
    }
    fn feed(&mut self, mut input: &[u8]) -> Result<()> {
        ensure!(
            !self
                .writer
                .as_ref()
                .unwrap()
                .get_ref()
                .budget
                .cancel
                .load(AtomicOrdering::Relaxed),
            "job cancelled"
        );
        while !input.is_empty() || self.phase == Phase::End {
            if self.phase == Phase::End {
                self.rows += 1;
                if self.rows == MAX_ROWS || self.position() - self.start >= TARGET_BYTES {
                    self.close_block()?;
                }
                self.phase = Phase::Id;
                continue;
            }
            if matches!(self.phase, Phase::Key | Phase::Field) {
                let n = input.len().min(self.remaining);
                self.writer.as_mut().unwrap().write_all(&input[..n])?;
                self.source_bytes += n as u64;
                input = &input[n..];
                self.remaining -= n;
                if self.remaining == 0 {
                    self.phase = if self.phase == Phase::Key {
                        Phase::Count
                    } else if self.fields == 0 {
                        Phase::End
                    } else {
                        Phase::Length
                    };
                }
                continue;
            }
            let n = (8 - self.word_len).min(input.len());
            self.word[self.word_len..self.word_len + n].copy_from_slice(&input[..n]);
            self.word_len += n;
            input = &input[n..];
            if self.word_len != 8 {
                continue;
            }
            self.word_len = 0;
            let value = u64::from_le_bytes(self.word);
            if self.phase == Phase::Id && self.rows == 0 {
                self.start = self.position();
                let w = self.writer.as_mut().unwrap();
                w.write_all(MAGIC)?;
            }
            self.source_bytes += 8;
            let w = self.writer.as_mut().unwrap();
            match self.phase {
                Phase::Id => {
                    w.write_all(&[1])?;
                    w.write_all(&self.word)?;
                    self.phase = Phase::Ordinal;
                }
                Phase::Ordinal => {
                    w.write_all(&self.word)?;
                    self.phase = Phase::KeyLength;
                }
                Phase::KeyLength => {
                    ensure!(
                        value <= self.maximum.saturating_mul(2).saturating_add(64) as u64,
                        "invalid compact spill key length"
                    );
                    w.write_all(
                        &u32::try_from(value)
                            .context("compact spill key exceeds u32 format bound")?
                            .to_le_bytes(),
                    )?;
                    self.remaining = value as usize;
                    self.phase = if value == 0 { Phase::Count } else { Phase::Key };
                }
                Phase::Count => {
                    ensure!(
                        value <= (self.maximum / 24 + 1) as u64,
                        "invalid compact spill field count"
                    );
                    let count = usize::try_from(value)?;
                    if self.width == Some(count) {
                        w.write_all(&[0])?;
                    } else {
                        w.write_all(&[1])?;
                        w.write_all(&u32::try_from(value)?.to_le_bytes())?;
                        self.width = Some(count);
                    }
                    self.fields = count;
                    self.row_remaining = self.maximum;
                    self.phase = if count == 0 {
                        Phase::End
                    } else {
                        Phase::Length
                    };
                }
                Phase::Length => {
                    ensure!(
                        value <= self.row_remaining as u64,
                        "invalid compact spill field length"
                    );
                    w.write_all(
                        &u32::try_from(value)
                            .context("compact spill field exceeds u32 format bound")?
                            .to_le_bytes(),
                    )?;
                    self.remaining = value as usize;
                    self.row_remaining -= self.remaining;
                    self.fields -= 1;
                    self.phase = if value != 0 {
                        Phase::Field
                    } else if self.fields == 0 {
                        Phase::End
                    } else {
                        Phase::Length
                    };
                }
                _ => unreachable!(),
            }
        }
        Ok(())
    }
    fn finish(&mut self) -> Result<()> {
        ensure!(
            self.phase == Phase::Id && self.word_len == 0,
            "truncated v1 input to compact spill"
        );
        self.close_block()?;
        self.writer.as_mut().unwrap().flush()?;
        let writer = self.writer.take().unwrap();
        let file = writer.into_inner().map_err(|e| e.into_error())?;
        self.writer = Some(BufWriter::with_capacity(0, file));
        self.reservation.resize(std::mem::size_of::<Self>())?;
        Ok(())
    }
}

pub(super) enum SpillReader {
    Raw(DiskReader),
    Blocked(Box<Decoder>),
}
impl Read for SpillReader {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        match self {
            Self::Raw(r) => r.read(bytes),
            Self::Blocked(r) => r.read(bytes),
        }
    }
}
pub(super) fn reader_bytes() -> usize {
    std::mem::size_of::<Decoder>() + READ_BUFFER
}
pub(super) struct Decoder {
    source: BufReader<DiskReader>,
    maximum: usize,
    phase: Phase,
    word: [u8; 8],
    word_pos: usize,
    word_end: usize,
    remaining: usize,
    rows: u32,
    fields: usize,
    row_remaining: usize,
    width: Option<usize>,
    failed: bool,
}
impl Decoder {
    fn queue(&mut self, value: u64) {
        self.word = value.to_le_bytes();
        self.word_pos = 0;
        self.word_end = 8;
    }
    fn number(&mut self) -> io::Result<u64> {
        let mut bytes = [0; 4];
        self.source.read_exact(&mut bytes)?;
        Ok(u32::from_le_bytes(bytes) as u64)
    }
    fn decode(&mut self, mut output: &mut [u8]) -> Result<usize> {
        ensure!(
            !self
                .source
                .get_ref()
                .budget
                .cancel
                .load(AtomicOrdering::Relaxed),
            "job cancelled"
        );
        let original = output.len();
        while !output.is_empty() {
            if self.word_pos < self.word_end {
                let n = output.len().min(self.word_end - self.word_pos);
                output[..n].copy_from_slice(&self.word[self.word_pos..self.word_pos + n]);
                output = &mut output[n..];
                self.word_pos += n;
                continue;
            }
            match self.phase {
                Phase::Block => {
                    if self.source.fill_buf()?.is_empty() {
                        break;
                    }
                    let mut magic = [0; 8];
                    self.source.read_exact(&mut magic)?;
                    ensure!(&magic == MAGIC, "invalid compact spill version/header");
                    self.rows = 0;
                    self.width = None;
                    self.phase = Phase::Row;
                }
                Phase::Row => {
                    let mut tag = [0];
                    self.source.read_exact(&mut tag)?;
                    match tag[0] {
                        0 => {
                            let count = self.number()?;
                            ensure!(
                                count > 0 && count == self.rows as u64,
                                "invalid compact spill block rows"
                            );
                            self.phase = Phase::Block;
                        }
                        1 => {
                            ensure!(self.rows < MAX_ROWS, "invalid compact spill block rows");
                            self.phase = Phase::Id;
                        }
                        _ => anyhow::bail!("invalid compact spill row tag"),
                    }
                }
                Phase::Id | Phase::Ordinal => {
                    self.source.read_exact(&mut self.word)?;
                    self.word_pos = 0;
                    self.word_end = 8;
                    self.phase = if self.phase == Phase::Id {
                        Phase::Ordinal
                    } else {
                        Phase::KeyLength
                    };
                }
                Phase::KeyLength => {
                    let n = self.number()?;
                    ensure!(
                        n <= self.maximum.saturating_mul(2).saturating_add(64) as u64,
                        "invalid compact spill key length"
                    );
                    self.remaining = n as usize;
                    self.queue(n);
                    self.phase = if n == 0 { Phase::Count } else { Phase::Key };
                }
                Phase::Key | Phase::Field => {
                    let count = output.len().min(self.remaining);
                    let n = self.source.read(&mut output[..count])?;
                    ensure!(n != 0, "truncated compact spill payload");
                    self.remaining -= n;
                    output = &mut output[n..];
                    if self.remaining == 0 {
                        self.phase = if self.phase == Phase::Key {
                            Phase::Count
                        } else if self.fields == 0 {
                            Phase::End
                        } else {
                            Phase::Length
                        };
                    }
                }
                Phase::Count => {
                    let mut tag = [0];
                    self.source.read_exact(&mut tag)?;
                    if tag[0] == 1 {
                        let n = self.number()?;
                        ensure!(
                            n <= (self.maximum / 24 + 1) as u64,
                            "invalid compact spill field count"
                        );
                        self.width = Some(n as usize);
                    } else {
                        ensure!(tag[0] == 0, "invalid compact spill width tag");
                    }
                    let count = self.width.context("compact spill missing field count")?;
                    self.fields = count;
                    self.row_remaining = self.maximum;
                    self.queue(count as u64);
                    self.phase = if count == 0 {
                        Phase::End
                    } else {
                        Phase::Length
                    };
                }
                Phase::Length => {
                    let n = self.number()?;
                    ensure!(
                        n <= self.row_remaining as u64,
                        "invalid compact spill field length"
                    );
                    self.remaining = n as usize;
                    self.row_remaining -= n as usize;
                    self.fields -= 1;
                    self.queue(n);
                    self.phase = if n != 0 {
                        Phase::Field
                    } else if self.fields == 0 {
                        Phase::End
                    } else {
                        Phase::Length
                    };
                }
                Phase::End => {
                    self.rows += 1;
                    self.phase = Phase::Row;
                }
            }
        }
        Ok(original - output.len())
    }
}
impl Read for Decoder {
    fn read(&mut self, bytes: &mut [u8]) -> io::Result<usize> {
        if self.failed {
            return Err(io::Error::other("compact spill reader already failed"));
        }
        match self.decode(bytes) {
            Ok(n) => Ok(n),
            Err(error) => {
                self.failed = true;
                Err(io::Error::other(error))
            }
        }
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) fn resource_contracts() -> Result<serde_json::Value> {
    tests::run()
}

#[cfg(any(test, feature = "resource-contract-tests"))]
mod tests {
    use super::*;

    pub(super) fn run() -> Result<serde_json::Value> {
        type Case = (&'static str, fn() -> Result<()>);
        let cases: [Case; 7] = [
            (
                "roundtrip_chunks_widths",
                block_roundtrip_shared_widths_zero_fields_and_arbitrary_source_chunks,
            ),
            ("footer_quota", footer_storage_quota_edges_and_cleanup),
            (
                "wide_reader_lifetime",
                wide_payload_streaming_and_reader_lifetime_fit_the_existing_fixed_grant,
            ),
            (
                "local_encoder_fallback_retry",
                constructor_capacity_fallback_flush_release_and_append,
            ),
            (
                "malformed_truncated_utf8_terminal",
                bad_headers_lengths_tags_truncation_utf8_and_terminal_failure_cleanup,
            ),
            (
                "shared_encoder_fallback_retry",
                shared_encoder_denial_preserves_competing_owner_and_retries,
            ),
            (
                "reader_live_cancellation",
                live_decoder_cancellation_releases_only_its_owners,
            ),
        ];
        let mut passed = Vec::new();
        for (name, run) in cases {
            run().with_context(|| format!("spill-block contract {name}"))?;
            passed.push(name);
        }
        Ok(serde_json::json!({"contract":"spill-block-resource-contracts-v1", "cases":passed}))
    }

    #[cfg_attr(test, test)]
    fn shared_encoder_denial_preserves_competing_owner_and_retries() -> Result<()> {
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let ctx = context_with_pool(None, pool.clone())?;
        let directory = ctx.directory_reserved_bytes();
        let path = ctx.file_path_bytes()?;
        let before = pool.usage().reserved_bytes;
        let mut competitor =
            Reservation::for_workspace(Arc::new(Workspace::shared(64 * 1024 * 1024, pool.clone())));
        let pressure =
            64 * 1024 * 1024 - before as usize - path - std::mem::size_of::<Encoder>() + 1;
        competitor.resize(pressure)?;
        let mut fallback = ctx.spill_file()?;
        assert!(matches!(fallback, SpillFile::Raw(_)));
        assert_eq!(ctx.workspace.used(), directory + path as u64);
        assert_eq!(
            pool.usage().reserved_bytes,
            before + pressure as u64 + path as u64
        );
        let row = Row {
            id: 1,
            ordinal: 2,
            key: vec![],
            fields: vec!["shared".into()],
        };
        let expected = encoded(&[row])?;
        fallback.write_all(&expected)?;
        fallback.flush()?;
        drop(fallback);
        assert_eq!(ctx.workspace.used(), directory);
        assert_eq!(pool.usage().reserved_bytes, before + pressure as u64);
        drop(competitor);
        assert_eq!(pool.usage().reserved_bytes, before);
        let mut retry = ctx.spill_file()?;
        assert!(matches!(retry, SpillFile::Blocked(_)));
        retry.write_all(&expected)?;
        retry.flush()?;
        assert_eq!(read_all(&retry, &ctx)?, expected);
        assert_eq!(
            ctx.budget.compact_spill_rows.load(AtomicOrdering::Relaxed),
            1
        );
        assert_eq!(
            ctx.budget
                .compact_spill_fallbacks
                .load(AtomicOrdering::Relaxed),
            1
        );
        drop(retry);
        assert_eq!(ctx.workspace.used(), directory);
        assert_eq!(pool.usage().reserved_bytes, before);
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[cfg_attr(test, test)]
    fn live_decoder_cancellation_releases_only_its_owners() -> Result<()> {
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let ctx = context_with_pool(None, pool.clone())?;
        let mut file = ctx.spill_file()?;
        write_row(
            &mut file,
            &Row {
                id: 1,
                ordinal: 2,
                key: vec![],
                fields: vec!["live".into()],
            },
        )?;
        file.flush()?;
        assert_eq!(
            ctx.budget.compact_spill_rows.load(AtomicOrdering::Relaxed),
            1
        );
        let mut fixed = Reservation::new(&ctx);
        fixed.resize(DISK_READ_BUFFER)?;
        let mut reader = file.reader()?;
        reader.read_exact(&mut [0; 1])?;
        ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
        // Bypass the exposed read buffer to reach the actual decoder checkpoint.
        assert!(reader.get_mut().read(&mut [0; 1]).is_err());
        assert!(reader.get_mut().read(&mut [0; 1]).is_err());
        drop(file);
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + DISK_READ_BUFFER as u64
        );
        assert_eq!(pool.usage().reserved_bytes, ctx.workspace.used());
        drop(reader);
        drop(fixed);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    fn context() -> Result<Context> {
        context_with_quota(None)
    }
    fn context_with_quota(temp_bytes: Option<u64>) -> Result<Context> {
        context_with_pool(
            temp_bytes,
            Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024)),
        )
    }
    fn context_with_pool(
        temp_bytes: Option<u64>,
        pool: Arc<crate::resources::MemoryPool>,
    ) -> Result<Context> {
        Context::with_memory_pool(
            &chopper_core::Resources {
                workers: 1,
                memory_mb: 32.into(),
                max_record_bytes: 2 * 1024 * 1024,
                temp_bytes,
                // WASI has no default temporary-directory discovery. Keep the
                // same absolute fixture parent as the other resource contracts.
                #[cfg(target_os = "wasi")]
                temp_dir: Some("/tmp".into()),
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool,
        )
    }
    fn encoded(rows: &[Row]) -> Result<Vec<u8>> {
        let mut bytes = Vec::new();
        for row in rows {
            write_row(&mut bytes, row)?;
        }
        Ok(bytes)
    }
    fn read_all(file: &SpillFile, ctx: &Context) -> Result<Vec<u8>> {
        let mut fixed = Reservation::new(ctx);
        fixed.resize(DISK_READ_BUFFER)?;
        let mut reader = file.reader()?;
        if let SpillReader::Blocked(decoder) = reader.get_ref() {
            assert_eq!(
                reader.capacity() + decoder.source.capacity() + std::mem::size_of::<Decoder>(),
                DISK_READ_BUFFER
            );
        }
        let mut actual = Vec::new();
        reader.read_to_end(&mut actual)?;
        Ok(actual)
    }

    #[cfg_attr(test, test)]
    fn block_roundtrip_shared_widths_zero_fields_and_arbitrary_source_chunks() -> Result<()> {
        let rows: Vec<_> = (0u64..600)
            .map(|id| Row {
                id,
                ordinal: u64::MAX - id,
                key: vec![0, 255, id as u8],
                fields: if id.is_multiple_of(13) {
                    vec![]
                } else {
                    (0..(id % 5 + 1))
                        .map(|i| format!("{id}-{i},界\n\0\"NULL"))
                        .collect()
                },
            })
            .collect();
        let expected = encoded(&rows)?;
        for chunk in [1, 3, 7, 65536] {
            let ctx = context()?;
            let mut file = ctx.spill_file()?;
            for bytes in expected.chunks(chunk) {
                file.write_all(bytes)?;
            }
            file.flush()?;
            assert_eq!(read_all(&file, &ctx)?, expected);
            assert_eq!(
                ctx.budget.compact_spill_rows.load(AtomicOrdering::Relaxed),
                600
            );
            assert_eq!(
                ctx.budget
                    .compact_spill_source_bytes
                    .load(AtomicOrdering::Relaxed),
                expected.len() as u64
            );
            assert_eq!(
                ctx.budget
                    .compact_spill_stored_bytes
                    .load(AtomicOrdering::Relaxed),
                file.len()
            );
            assert!(
                ctx.budget
                    .compact_spill_blocks
                    .load(AtomicOrdering::Relaxed)
                    >= 3
            );
            let physical = std::fs::read(file.file.as_ref().unwrap().path())?;
            assert_eq!(&physical[..8], MAGIC);
            assert_eq!(ctx.budget.written.load(AtomicOrdering::Relaxed), file.len());
            drop(file);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        Ok(())
    }

    #[cfg_attr(test, test)]
    fn footer_storage_quota_edges_and_cleanup() -> Result<()> {
        for quota in [78, 79, 80] {
            let ctx = context_with_quota(Some(quota))?;
            let mut file = ctx.spill_file()?;
            let row = Row {
                id: 1,
                ordinal: 2,
                key: vec![],
                fields: vec!["x".into(), "".into()],
            };
            write_row(&mut file, &row)?;
            write_row(&mut file, &row)?;
            let result = file.flush();
            assert_eq!(result.is_ok(), quota >= 79);
            if result.is_ok() {
                assert_eq!(ctx.used(), 79);
                assert_eq!(ctx.peak(), 79);
                assert_eq!(ctx.budget.written.load(AtomicOrdering::Relaxed), 79);
            } else {
                assert!(file.reader().is_err());
            }
            drop(file);
            assert_eq!(ctx.used(), 0);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.budget.live_files.load(AtomicOrdering::Relaxed), 0);
        }
        Ok(())
    }

    #[cfg_attr(test, test)]
    fn wide_payload_streaming_and_reader_lifetime_fit_the_existing_fixed_grant() -> Result<()> {
        let ctx = context()?;
        let rows = vec![Row {
            id: 0,
            ordinal: 1,
            key: vec![7; 4000],
            fields: vec!["界".repeat(600000), "".into()],
        }];
        let expected = encoded(&rows)?;
        let mut file = ctx.spill_file()?;
        for bytes in expected.chunks(4093) {
            file.write_all(bytes)?;
        }
        file.flush()?;
        assert_eq!(read_all(&file, &ctx)?, expected);
        let retained = ctx.workspace.used();
        let mut fixed = Reservation::new(&ctx);
        fixed.resize(2 * DISK_READ_BUFFER)?;
        let mut a = file.reader()?;
        let mut b = file.reader()?;
        assert_eq!(ctx.workspace.used(), retained + 2 * DISK_READ_BUFFER as u64);
        let mut small = [0; 3];
        a.read_exact(&mut small)?;
        b.read_exact(&mut small)?;
        drop(file);
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + 2 * DISK_READ_BUFFER as u64
        );
        let mut remainder = Vec::new();
        a.read_to_end(&mut remainder)?;
        assert_eq!(&remainder, &expected[3..]);
        drop(a);
        drop(b);
        drop(fixed);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }

    #[cfg_attr(test, test)]
    fn constructor_capacity_fallback_flush_release_and_append() -> Result<()> {
        let path_bytes = context()?.file_path_bytes()?;
        let exact = path_bytes + std::mem::size_of::<Encoder>();
        for limit in [exact - 1, exact, exact + 1] {
            let mut ctx = context()?;
            ctx.replace_workspace_for_test(Workspace::new(limit))?;
            let mut file = ctx.spill_file()?;
            assert_eq!(matches!(file, SpillFile::Blocked(_)), limit >= exact);
            let row = Row {
                id: 1,
                ordinal: 2,
                key: vec![],
                fields: vec!["x".into()],
            };
            write_row(&mut file, &row)?;
            file.flush()?;
            assert_eq!(
                ctx.workspace.used(),
                ctx.directory_reserved_bytes()
                    + (path_bytes
                        + if limit >= exact {
                            std::mem::size_of::<Encoder>()
                        } else {
                            0
                        }) as u64
            );
            write_row(&mut file, &row)?;
            file.flush()?;
            assert_eq!(
                ctx.budget.compact_spill_rows.load(AtomicOrdering::Relaxed),
                if limit >= exact { 2 } else { 0 }
            );
            drop(file);
            assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
            assert_eq!(ctx.used(), 0);
        }
        let ctx = context()?;
        let mut pressure = Reservation::new(&ctx);
        pressure.resize(ctx.memory / 2 - ctx.directory_reserved_bytes() as usize - exact + 1)?;
        let fallback = ctx.spill_file()?;
        assert!(matches!(fallback, SpillFile::Raw(_)));
        drop(fallback);
        drop(pressure);
        let mut retry = ctx.spill_file()?;
        assert!(matches!(retry, SpillFile::Blocked(_)));
        retry.flush()?;
        drop(retry);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        // The production writer seam spends the caller's one existing I/O
        // grant inside the codec, with no second payload buffer or grant.
        let mut io = Reservation::new(&ctx);
        io.resize(DISK_READ_BUFFER)?;
        let mut writer = ctx.spill_writer(DISK_READ_BUFFER)?;
        assert_eq!(writer.capacity(), 0);
        if let SpillFile::Blocked(e) = writer.get_ref() {
            assert_eq!(e.writer.as_ref().unwrap().capacity(), DISK_READ_BUFFER);
        } else {
            panic!("expected compact spill");
        }
        write_row(
            &mut writer,
            &Row {
                id: 1,
                ordinal: 0,
                key: vec![],
                fields: vec!["x".into()],
            },
        )?;
        assert!(writer.get_ref().reader().is_err());
        writer.flush()?;
        let file = writer.into_inner().map_err(|e| e.into_error())?;
        if let SpillFile::Blocked(e) = &file {
            assert_eq!(e.writer.as_ref().unwrap().capacity(), 0);
        }
        drop(io);
        assert_eq!(
            ctx.workspace.used(),
            ctx.directory_reserved_bytes() + (path_bytes + std::mem::size_of::<Encoder>()) as u64
        );
        drop(file);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }

    #[cfg_attr(test, test)]
    fn bad_headers_lengths_tags_truncation_utf8_and_terminal_failure_cleanup() -> Result<()> {
        let ctx = context()?;
        let mut file = ctx.spill_file()?;
        let row = Row {
            id: 1,
            ordinal: 2,
            key: vec![],
            fields: vec!["x".into(), "".into()],
        };
        write_row(&mut file, &row)?;
        write_row(&mut file, &row)?;
        file.flush()?;
        let valid = std::fs::read(file.file.as_ref().unwrap().path())?;
        assert_eq!(valid.len(), 79);
        assert_eq!(valid[29], 1);
        assert_eq!(valid[64], 0);
        let mut corruptions = Vec::new();
        for (offset, replacement) in [
            (0, b"BADVERSN".to_vec()),
            (75, 0u32.to_le_bytes().to_vec()),
            (75, 257u32.to_le_bytes().to_vec()),
            (29, vec![0]),
            (29, vec![2]),
            (25, u32::MAX.to_le_bytes().to_vec()),
            (30, u32::MAX.to_le_bytes().to_vec()),
            (34, u32::MAX.to_le_bytes().to_vec()),
            (38, vec![255]),
        ] {
            let mut data = valid.clone();
            data[offset..offset + replacement.len()].copy_from_slice(&replacement);
            corruptions.push(data);
        }
        let mut too_many = valid[..43].to_vec();
        for _ in 0..256 {
            too_many.extend_from_slice(&valid[43..74]);
        }
        too_many.push(0);
        too_many.extend_from_slice(&257u32.to_le_bytes());
        corruptions.push(too_many);
        corruptions.extend([
            valid[..11].to_vec(),
            valid[..16].to_vec(),
            valid[..valid.len() - 1].to_vec(),
            [valid.clone(), vec![0]].concat(),
        ]);
        let mut fixed = Reservation::new(&ctx);
        fixed.resize(DISK_READ_BUFFER)?;
        for (case, data) in corruptions.into_iter().enumerate() {
            std::fs::write(file.file.as_ref().unwrap().path(), data)?;
            let mut reader = file.reader()?;
            let result = (|| -> Result<()> {
                while read_row(&mut reader, ctx.max_record)?.is_some() {}
                Ok(())
            })();
            assert!(result.is_err(), "corruption {case} was accepted");
            if case != 8 {
                assert!(reader.get_mut().read(&mut [0; 1]).is_err());
            }
        }
        drop(fixed);
        drop(file);
        let source = encoded(&[row])?;
        for input in [source[..5].to_vec(), {
            let mut bytes = source.clone();
            bytes[16..24].copy_from_slice(&u64::MAX.to_le_bytes());
            bytes
        }] {
            let mut broken = ctx.spill_file()?;
            let wrote = broken.write_all(&input);
            assert!(wrote.is_err() || broken.flush().is_err());
            assert!(broken.write_all(&source).is_err());
            assert!(broken.reader().is_err());
            drop(broken);
        }
        let mut cancelled = ctx.spill_file()?;
        ctx.budget.cancel.store(true, AtomicOrdering::Relaxed);
        assert!(cancelled.write_all(&source).is_err());
        assert!(cancelled.reader().is_err());
        drop(cancelled);
        assert_eq!(ctx.used(), 0);
        assert_eq!(ctx.workspace.used(), ctx.directory_reserved_bytes());
        Ok(())
    }
}
