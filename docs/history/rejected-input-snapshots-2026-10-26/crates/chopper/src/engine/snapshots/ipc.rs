//! Uncompressed, dictionary-free positional UTF-8 IPC files. Decode only after
//! validating bounded footer/message layouts; do not let FileReader eagerly
//! allocate an unchecked footer or dictionary.
use super::*;
use arrow_array::{builder::StringBuilder, Array, ArrayRef, RecordBatch, StringArray};
use arrow_buffer::MutableBuffer;
use arrow_ipc::{reader::FileDecoder, writer::FileWriter, Block};
use arrow_schema::{DataType, Field, Schema};
const MAX_FOOTER: usize = 256 * 1024;
const MAX_MESSAGE: usize = 256 * 1024;

pub(super) struct Writer {
    output: FileWriter<LimitedWriter>,
    schema: Arc<Schema>,
    columns: Vec<StringBuilder>,
    rows: usize,
    bytes: usize,
    batches: usize,
    _grant: Reservation,
}
impl Writer {
    pub(super) fn new(output: LimitedWriter, columns: usize, ctx: &Context) -> Result<Self> {
        let maximum = TARGET_BATCH_BYTES.max(ctx.max_record);
        ensure!(
            maximum <= i32::MAX as usize / 4,
            "IPC snapshot record bound is too large"
        );
        let bytes = maximum
            .checked_mul(if columns == 0 { 0 } else { 4 })
            .and_then(|n| n.checked_add(columns * 16384))
            .and_then(|n| n.checked_add(MAX_BATCHES * 128))
            .context("IPC writer reservation overflow")?;
        let mut grant = Reservation::new(ctx);
        grant.resize(bytes)?;
        let schema = Arc::new(Schema::new(
            (0..columns)
                .map(|i| Field::new(format!("c{i}"), DataType::Utf8, false))
                .collect::<Vec<_>>(),
        ));
        let output = FileWriter::try_new(output, &schema).map_err(|error| {
            // Destroy upstream diagnostic payloads while the IPC reservation is live.
            drop(error);
            anyhow::anyhow!("IPC writer schema construction failed")
        })?;
        let columns = (0..columns)
            .map(|_| StringBuilder::with_capacity(MAX_BATCH_ROWS, 0))
            .collect();
        Ok(Self {
            output,
            schema,
            columns,
            rows: 0,
            bytes: 0,
            batches: 0,
            _grant: grant,
        })
    }
    #[cfg(test)]
    pub(super) fn census_flush(&mut self) -> Result<()> {
        self.flush()
    }
    #[cfg(test)]
    pub(super) fn census_catalog_at_limit(&mut self) {
        self.batches = MAX_BATCHES;
    }
    fn flush(&mut self) -> Result<()> {
        #[cfg(test)]
        let _phase = super::tests::arrow_census::Phase::enter(3);
        if self.rows == 0 {
            return Ok(());
        }
        ensure!(
            self.batches < MAX_BATCHES,
            "IPC snapshot exceeds bounded block catalog"
        );
        let arrays = self
            .columns
            .iter_mut()
            .map(|column| Arc::new(column.finish()) as ArrayRef)
            .collect();
        let batch = RecordBatch::try_new(self.schema.clone(), arrays).map_err(|error| {
            // Destroy upstream diagnostic payloads while the IPC reservation is live.
            drop(error);
            anyhow::anyhow!("IPC writer batch construction failed")
        })?;
        self.output.write(&batch).map_err(|error| {
            // Destroy upstream diagnostic payloads while the IPC reservation is live.
            drop(error);
            anyhow::anyhow!("IPC writer batch encoding failed")
        })?;
        self.rows = 0;
        self.bytes = 0;
        self.batches += 1;
        Ok(())
    }
    pub(super) fn row(&mut self, row: &chopper_core::csv::CompactRecord) -> Result<()> {
        ensure!(
            row.len() == self.columns.len(),
            "IPC snapshot column count changed"
        );
        let bytes = row
            .payload_bytes()
            .checked_add(row.len() * 4)
            .context("IPC snapshot row size overflow")?;
        if self.rows == MAX_BATCH_ROWS
            || (self.rows > 0
                && self
                    .bytes
                    .checked_add(bytes)
                    .is_none_or(|n| n > TARGET_BATCH_BYTES))
        {
            self.flush()?;
        }
        for (column, value) in self.columns.iter_mut().zip(row.fields()) {
            column.append_value(value);
        }
        self.rows += 1;
        self.bytes = self
            .bytes
            .checked_add(bytes)
            .context("IPC batch size overflow")?;
        Ok(())
    }
    pub(super) fn finish(mut self) -> Result<u64> {
        self.flush()?;
        #[cfg(test)]
        let _phase = super::tests::arrow_census::Phase::enter(4);
        self.output.finish().map_err(|error| {
            // Destroy upstream diagnostic payloads while the IPC reservation is live.
            drop(error);
            anyhow::anyhow!("IPC writer footer encoding failed")
        })?;
        #[cfg(test)]
        super::tests::arrow_census::set_phase(5);
        Ok(self
            .output
            .into_inner()
            .map_err(|error| {
                // Destroy upstream diagnostic payloads while the IPC reservation is live.
                drop(error);
                anyhow::anyhow!("IPC writer output finalization failed")
            })?
            .bytes)
    }
}

pub(super) struct Reader {
    file: crate::storage::DiskReader,
    decoder: FileDecoder,
    blocks: Vec<Block>,
    index: usize,
    batch: Option<RecordBatch>,
    row: usize,
    total: u64,
    expected: u64,
    columns: usize,
    ctx: Context,
    _grant: Reservation,
}
impl Reader {
    pub(super) fn new(
        mut file: crate::storage::DiskReader,
        manifest: &Manifest,
        ctx: &Context,
    ) -> Result<Self> {
        let length = file.seek(SeekFrom::End(0))?;
        file.seek(SeekFrom::Start(0))?;
        ensure!(length >= 18, "truncated IPC snapshot");
        let mut magic = [0; 8];
        file.read_exact(&mut magic)?;
        ensure!(&magic == b"ARROW1\0\0", "invalid IPC file magic");
        let mut tail = [0; 10];
        file.seek(SeekFrom::End(-10))?;
        file.read_exact(&mut tail)?;
        let mut grant = Reservation::new(ctx);
        grant.resize(65536)?;
        let footer_len = arrow_ipc::reader::read_footer_length(tail).map_err(|error| {
            // Destroy upstream diagnostic payloads while the IPC reservation is live.
            drop(error);
            anyhow::anyhow!("invalid IPC footer framing")
        })?;
        ensure!(
            footer_len <= MAX_FOOTER && (footer_len as u64) + 18 <= length,
            "IPC snapshot footer exceeds bound"
        );
        let footer_start = length - 10 - footer_len as u64;
        grant.resize(footer_len + 65536)?;
        let mut footer_bytes = vec![0; footer_len];
        file.seek(SeekFrom::Start(footer_start))?;
        file.read_exact(&mut footer_bytes)?;
        let footer = arrow_ipc::root_as_footer(&footer_bytes).map_err(|error| {
            drop(error);
            anyhow::anyhow!("invalid IPC footer verification")
        })?;
        ensure!(
            footer.version() == arrow_ipc::MetadataVersion::V5,
            "IPC snapshot requires metadata V5"
        );
        ensure!(
            footer.dictionaries().is_none_or(|v| v.is_empty())
                && footer.custom_metadata().is_none_or(|v| v.is_empty()),
            "IPC snapshot dictionaries/custom footer metadata are unsupported"
        );
        let schema = footer.schema().context("missing IPC schema")?;
        ensure!(
            schema.endianness().equals_to_target_endianness(),
            "unsupported IPC endianness"
        );
        ensure!(
            schema.custom_metadata().is_none_or(|v| v.is_empty())
                && schema.features().is_none_or(|v| v.is_empty()),
            "unsupported IPC schema metadata/features"
        );
        let fields = schema.fields().context("missing IPC schema fields")?;
        ensure!(
            fields.len() == manifest.columns && fields.len() <= MAX_COLUMNS,
            "IPC snapshot schema width mismatch"
        );
        for (index, field) in fields.iter().enumerate() {
            ensure!(
                field.name() == Some(format!("c{index}").as_str())
                    && field.type_type() == arrow_ipc::Type::Utf8
                    && !field.nullable()
                    && field.dictionary().is_none()
                    && field.children().is_none_or(|v| v.is_empty())
                    && field.custom_metadata().is_none_or(|v| v.is_empty()),
                "IPC snapshot requires positional non-null UTF-8 columns"
            );
        }
        let blocks = footer
            .recordBatches()
            .context("missing IPC record block catalog")?;
        ensure!(
            blocks.len() <= MAX_BATCHES,
            "IPC snapshot block catalog exceeds bound"
        );
        let maximum_body = TARGET_BATCH_BYTES
            .max(ctx.max_record)
            .checked_add(fields.len() * 128)
            .context("IPC body bound overflow")?;
        let mut previous = 8u64;
        let mut maximum_block = 0usize;
        for block in blocks {
            let offset = u64::try_from(block.offset()).context("negative IPC block offset")?;
            let metadata =
                usize::try_from(block.metaDataLength()).context("negative IPC metadata length")?;
            let body = usize::try_from(block.bodyLength()).context("negative IPC body length")?;
            ensure!(
                (8..=MAX_MESSAGE).contains(&metadata) && body <= maximum_body,
                "IPC snapshot message/body exceeds bound"
            );
            let total = metadata
                .checked_add(body)
                .context("IPC block length overflow")?;
            let end = offset
                .checked_add(total as u64)
                .context("IPC block offset overflow")?;
            ensure!(
                offset >= previous && end <= footer_start,
                "IPC blocks overlap or escape data region"
            );
            previous = end;
            maximum_block = maximum_block.max(total);
        }
        let charge = maximum_block
            .checked_add(63)
            .and_then(|n| n.checked_add(footer_len * 4))
            .and_then(|n| n.checked_add(blocks.len() * 128))
            .and_then(|n| n.checked_add(fields.len() * 16384))
            .and_then(|n| n.checked_add(65536))
            .context("IPC reader reservation overflow")?;
        grant.resize(charge)?;
        #[cfg(test)]
        super::tests::arrow_census::set_phase(7);
        let decoded_schema = Arc::new(arrow_ipc::convert::try_fb_to_schema(schema).map_err(
            |error| {
                // Destroy upstream diagnostic payloads while the IPC reservation is live.
                drop(error);
                anyhow::anyhow!("invalid IPC schema conversion")
            },
        )?);
        let decoder =
            FileDecoder::new(decoded_schema, footer.version()).with_require_alignment(true);
        let blocks = blocks.iter().copied().collect();
        Ok(Self {
            file,
            decoder,
            blocks,
            index: 0,
            batch: None,
            row: 0,
            total: 0,
            expected: manifest.records,
            columns: manifest.columns,
            ctx: ctx.clone(),
            _grant: grant,
        })
    }
    pub(super) fn next_fields(&mut self) -> Result<Option<Fields<'_>>> {
        self.ctx.check()?;
        if self
            .batch
            .as_ref()
            .is_none_or(|batch| self.row == batch.num_rows())
        {
            // Release the old body/arrays before allocating the next block.
            self.batch = None;
            self.row = 0;
            let Some(block) = self.blocks.get(self.index) else {
                #[cfg(test)]
                super::tests::arrow_census::set_phase(10);
                ensure!(
                    self.total == self.expected,
                    "IPC snapshot record count mismatch"
                );
                return Ok(None);
            };
            #[cfg(test)]
            super::tests::arrow_census::set_phase(if self.index == 0 { 8 } else { 9 });
            let metadata = usize::try_from(block.metaDataLength())?;
            let body = usize::try_from(block.bodyLength())?;
            let mut bytes =
                MutableBuffer::try_from_len_zeroed(metadata + body).map_err(|_error| {
                    // Pinned MutableBufferError is scalar-only; retain no upstream source.
                    anyhow::anyhow!("IPC record buffer allocation failed")
                })?;
            self.file
                .seek(SeekFrom::Start(u64::try_from(block.offset())?))?;
            self.file.read_exact(bytes.as_slice_mut())?;
            ensure!(
                bytes[..4] == [255; 4],
                "IPC snapshot requires continuation framing"
            );
            let message_len = u32::from_le_bytes(bytes[4..8].try_into().unwrap()) as usize;
            ensure!(
                message_len > 0 && message_len <= metadata - 8,
                "invalid IPC message length"
            );
            let message =
                arrow_ipc::root_as_message(&bytes[8..8 + message_len]).map_err(|error| {
                    drop(error);
                    anyhow::anyhow!("invalid IPC record message verification")
                })?;
            ensure!(
                message.bodyLength() == block.bodyLength()
                    && message.version() == arrow_ipc::MetadataVersion::V5,
                "IPC message/footer length or version mismatch"
            );
            let record = message
                .header_as_record_batch()
                .context("IPC snapshot contains a non-record message")?;
            ensure!(
                record.compression().is_none()
                    && record.variadicBufferCounts().is_none_or(|v| v.is_empty()),
                "compressed/variadic IPC snapshots are unsupported"
            );
            let rows = usize::try_from(record.length())?;
            ensure!(
                rows > 0
                    && rows <= MAX_BATCH_ROWS
                    && self
                        .total
                        .checked_add(rows as u64)
                        .is_some_and(|n| n <= self.expected),
                "IPC snapshot batch row count exceeds bound"
            );
            let nodes = record.nodes().context("missing IPC field nodes")?;
            let buffers = record.buffers().context("missing IPC field buffers")?;
            ensure!(
                nodes.len() == self.columns && buffers.len() == self.columns * 3,
                "IPC field node/buffer count mismatch"
            );
            for node in nodes {
                ensure!(
                    node.length() == rows as i64 && node.null_count() == 0,
                    "IPC snapshot contains nulls or mismatched field rows"
                );
            }
            for (index, buffer) in buffers.iter().enumerate() {
                let offset = usize::try_from(buffer.offset())?;
                let length = usize::try_from(buffer.length())?;
                ensure!(
                    offset.checked_add(length).is_some_and(|n| n <= body),
                    "IPC buffer escapes record body"
                );
                if index % 3 == 0 {
                    ensure!(
                        length == 0 || length == rows.div_ceil(8),
                        "IPC snapshot validity buffer length mismatch"
                    );
                    if length != 0 {
                        let validity = &bytes[metadata + offset..metadata + offset + length];
                        ensure!(
                            (0..rows).all(|row| validity[row / 8] & (1 << (row % 8)) != 0),
                            "IPC snapshot contains null validity bits"
                        );
                    }
                }
                if index % 3 == 1 {
                    ensure!(
                        length == (rows + 1) * 4,
                        "IPC UTF-8 offsets length mismatch"
                    );
                }
            }
            let batch = self
                .decoder
                .read_record_batch(block, &bytes.into())
                .map_err(|error| {
                    drop(error);
                    anyhow::anyhow!("invalid IPC record batch decoding")
                })?
                .context("missing IPC record batch")?;
            ensure!(
                batch.num_columns() == self.columns && batch.num_rows() == rows,
                "decoded IPC batch shape changed"
            );
            for column in batch.columns() {
                ensure!(
                    column.null_count() == 0,
                    "IPC snapshot contains null values"
                );
                column.to_data().validate_full().map_err(|error| {
                    // Destroy upstream diagnostic payloads while the IPC reservation is live.
                    drop(error);
                    anyhow::anyhow!("invalid IPC UTF-8 array validation")
                })?;
            }
            self.batch = Some(batch);
            self.index += 1;
        }
        let batch = self.batch.as_ref().unwrap();
        let row = self.row;
        self.row += 1;
        self.total += 1;
        Ok(Some(Fields {
            batch,
            row,
            column: 0,
        }))
    }
}
#[derive(Clone)]
pub(super) struct Fields<'a> {
    batch: &'a RecordBatch,
    row: usize,
    column: usize,
}
impl<'a> Iterator for Fields<'a> {
    type Item = &'a str;
    fn next(&mut self) -> Option<Self::Item> {
        let column = self.batch.columns().get(self.column)?;
        self.column += 1;
        Some(
            column
                .as_any()
                .downcast_ref::<StringArray>()
                .unwrap()
                .value(self.row),
        )
    }
    fn size_hint(&self) -> (usize, Option<usize>) {
        let n = self.len();
        (n, Some(n))
    }
}
impl ExactSizeIterator for Fields<'_> {
    fn len(&self) -> usize {
        self.batch.num_columns() - self.column
    }
}
