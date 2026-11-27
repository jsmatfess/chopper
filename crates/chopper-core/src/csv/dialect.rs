use super::*;
use crate::{CsvTrim, InputDialect};

/// Input dialects use the strict CSV state machine and transform admitted
/// records before they reach schema binding. Plain inputs use Parser directly.
pub struct DialectParser<'a, R> {
    parser: Parser<CommentReader<'a, R>>,
    dialect: &'a InputDialect,
    header_pending: bool,
    preamble: u64,
    compact_fields: Vec<String>,
}

impl<'a, R: BufRead> DialectParser<'a, R> {
    pub fn new(parser: Parser<R>, dialect: &'a InputDialect) -> Self {
        let Parser {
            reader,
            settings,
            maximum,
            record,
            scratch,
            compact_hint,
        } = parser;
        let header_pending = settings.headers;
        Self {
            parser: Parser {
                reader: CommentReader {
                    reader,
                    replay: &[],
                },
                settings,
                maximum,
                record,
                scratch,
                compact_hint,
            },
            dialect,
            header_pending,
            preamble: dialect.skip_rows,
            compact_fields: Vec::new(),
        }
    }

    pub fn record_number(&self) -> u64 {
        self.parser.record
    }

    pub fn scratch_capacity(&self) -> usize {
        self.parser.scratch_capacity() + owned_capacity(&self.compact_fields)
    }

    pub fn next_record_into_reserved(
        &mut self,
        fields: &mut Vec<String>,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        let parser = &mut self.parser;
        for _ in 0..std::mem::take(&mut self.preamble) {
            if parser.reader.skip_until(b'\n')? == 0 {
                break;
            }
            parser.record += 1;
        }

        let mut target = ReservedOwned {
            payload_capacity: fields.iter().map(String::capacity).sum(),
            fields,
            reserve,
            scratch_capacity: parser.scratch.capacity(),
        };
        target.update()?;
        let skip_blank = self.dialect.skip_blank_rows && !self.header_pending;
        loop {
            let number = parser.record + 1;
            if let Some(prefix) = &self.dialect.comment_prefix {
                if parser.reader.skip_comment(prefix.as_bytes())? {
                    parser.record = number;
                    continue;
                }
            }
            let Some(count) = parser
                .parse_record(&mut target)
                .with_context(|| format!("CSV record {number}"))?
            else {
                target.fields.clear();
                target.payload_capacity = 0;
                target.update()?;
                return Ok(false);
            };
            if count == 0 {
                ensure!(
                    parser.settings.skip_empty_lines || skip_blank,
                    "bare blank CSV record {number} (enable skip_empty_lines to ignore)"
                );
                parser.record = number;
                continue;
            }
            parser.record = number;
            target.fields.truncate(count);
            for field in target.fields.iter_mut() {
                trim(field, self.dialect.trim);
            }
            if skip_blank && target.fields.iter().all(String::is_empty) {
                target.payload_capacity = target.fields.iter().map(String::capacity).sum();
                target.update()?;
                continue;
            }
            let skip_columns = self.dialect.skip_columns;
            ensure!(
                count > skip_columns,
                "CSV record {number} has {count} fields, cannot skip {skip_columns} columns"
            );
            target.fields.drain(..skip_columns);
            target.payload_capacity = target.fields.iter().map(String::capacity).sum();
            target.update()?;
            if target.payload_capacity > parser.maximum.saturating_mul(2) {
                target.shrink_fields()?;
            }
            self.header_pending = false;
            return Ok(true);
        }
    }

    pub fn next_compact_record_into_reserved(
        &mut self,
        record: &mut CompactRecord,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        let mut fields = std::mem::take(&mut self.compact_fields);
        record.bytes.clear();
        let present = self.next_record_into_reserved(&mut fields, &mut |bytes| {
            reserve(bytes + record.capacity())
        });
        self.compact_fields = fields;
        if !present? {
            return Ok(false);
        }
        let retained = self.scratch_capacity();
        // The parser has already enforced the unprojected CSV working limit.
        record.set_text_fields_reserved(
            self.compact_fields.iter().map(String::as_str),
            usize::MAX,
            &mut |bytes| reserve(retained + bytes),
        )?;
        Ok(true)
    }
}

fn owned_capacity(fields: &Vec<String>) -> usize {
    fields.capacity() * std::mem::size_of::<String>()
        + fields.iter().map(String::capacity).sum::<usize>()
}

fn trim(field: &mut String, mode: CsvTrim) {
    if matches!(mode, CsvTrim::End | CsvTrim::Both) {
        field.truncate(field.trim_end().len());
    }
    if matches!(mode, CsvTrim::Start | CsvTrim::Both) {
        field.drain(..field.len() - field.trim_start().len());
    }
}

struct CommentReader<'a, R> {
    reader: R,
    replay: &'a [u8],
}

impl<'a, R: BufRead> CommentReader<'a, R> {
    fn skip_comment(&mut self, prefix: &'a [u8]) -> io::Result<bool> {
        // Partial matches can cross reads. Replay the consumed prefix bytes
        // directly from the configured string if the match subsequently fails.
        let mut matched = 0;
        while matched < prefix.len() {
            let data = self.reader.fill_buf()?;
            let length = data.len().min(prefix.len() - matched);
            if length == 0 || data[..length] != prefix[matched..matched + length] {
                self.replay = &prefix[..matched];
                return Ok(false);
            }
            self.reader.consume(length);
            matched += length;
        }
        self.reader.skip_until(b'\n')?;
        Ok(true)
    }
}

impl<R: BufRead> Read for CommentReader<'_, R> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        let count = self.fill_buf()?.read(output)?;
        self.consume(count);
        Ok(count)
    }
}

impl<R: BufRead> BufRead for CommentReader<'_, R> {
    fn fill_buf(&mut self) -> io::Result<&[u8]> {
        if self.replay.is_empty() {
            self.reader.fill_buf()
        } else {
            Ok(self.replay)
        }
    }

    fn consume(&mut self, count: usize) {
        if self.replay.is_empty() {
            self.reader.consume(count);
        } else {
            self.replay = &self.replay[count..];
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{BufReader, Cursor};

    #[test]
    fn extensions_preserve_csv_boundaries_and_apply_blank_skip_before_projection() -> Result<()> {
        let input = concat!(
            "non-CSV preamble with a lone \"\r\n",
            "☃ comment with another \"\r\n",
            "drop, name , note \r\n",
            " , , \r\n",
            "☃x, keep ,\" line one\r\n☃ included in the value  \"\r\n",
            "nonempty,,\r\n",
            "\r\n",
        );
        let dialect = InputDialect {
            trim: CsvTrim::Both,
            comment_prefix: Some("☃ ".into()),
            skip_rows: 1,
            skip_columns: 1,
            skip_blank_rows: true,
        };
        for capacity in [1, 65536] {
            let raw = Parser::new(
                BufReader::with_capacity(capacity, Cursor::new(input.as_bytes())),
                CsvSettings::default(),
                1024,
            );
            let mut parser = DialectParser::new(raw, &dialect);
            let mut header = Vec::new();
            let mut compact = CompactRecord::default();
            assert!(parser.next_record_into_reserved(&mut header, &mut |_| Ok(()))?);
            assert_eq!(header, ["name", "note"]);
            for expected in [["keep", "line one\r\n☃ included in the value"], ["", ""]] {
                let mut admitted = 0;
                assert!(
                    parser.next_compact_record_into_reserved(&mut compact, &mut |bytes| {
                        admitted = bytes;
                        Ok(())
                    })?
                );
                assert!(compact.fields().eq(expected));
                assert_eq!(admitted, parser.scratch_capacity() + compact.capacity());
            }
            assert!(!parser.next_compact_record_into_reserved(&mut compact, &mut |_| Ok(()))?);
            assert_eq!(parser.record_number(), 7);
        }
        Ok(())
    }

    #[test]
    fn working_limit_checks_final_empty_field_at_eof() {
        for max in [33, 34] {
            let mut parser = Parser::new(Cursor::new(b"1,"), CsvSettings::default(), max);
            let row = parser.next_record();
            if max == 33 {
                assert!(format!("{:#}", row.unwrap_err()).contains("max_record_bytes"));
            } else {
                assert_eq!(row.unwrap().unwrap(), ["1", ""]);
            }
        }
    }
}
