//! Decoded CSV intake owns parser/record storage before their admission grants.
//! Codec selection, source identity, execution and observation policy stay with
//! callers. The profiling slot adapter drops all borrowed-slot storage before
//! this owner; ordinary callers consume/recycle records through scoped callbacks.
//! A session fixes its data-record representation on its first read/prefetch;
//! header transfer is separate. Switching representation cannot leave a second
//! uncharged record buffer alive. Raw-parser construction is test-only.
use crate::storage::Reservation;
use anyhow::{ensure, Context, Result};
use chopper_core::{
    csv::{CompactRecord, DecodeReader, DialectParser, Parser},
    CsvSettings, InputDialect,
};
use std::io::{BufReader, Read};
mod parser;
pub(crate) use parser::Records;

pub(crate) const SOURCE_BUFFER: usize = 64 * 1024;
pub(crate) type DecodedInput<R> = Intake<Parser<BufReader<DecodeReader<R>>>>;

// Dispatch before entering a record loop so the plain parser stays statically
// dispatched and never tests for dialect extensions while reading rows.
macro_rules! with_dialect {
    ($input:expr, $dialect:expr, |$binding:ident| $run:expr) => {{
        let input = $input;
        let dialect = $dialect;
        if dialect.is_default() {
            let $binding = input;
            $run
        } else {
            let $binding = input.with_dialect(dialect);
            $run
        }
    }};
}
pub(crate) use with_dialect;

#[derive(Clone, Copy, PartialEq, Eq)]
enum Representation {
    Owned,
    Compact,
}

pub(crate) struct Intake<P> {
    parser: P,
    owned: Vec<String>,
    compact: CompactRecord,
    width: Option<usize>,
    headers: bool,
    prefetched: bool,
    terminal: bool,
    representation: Option<Representation>,
    // All parser, source and row allocations above drop before these grants.
    _source: Reservation,
    memory: Reservation,
}

/// Retained headers transfer their existing fields and grant without copying.
pub(crate) struct HeaderFields {
    fields: Vec<String>,
    memory: Reservation,
}
impl HeaderFields {
    pub(crate) fn into_parts(self) -> (Vec<String>, Reservation) {
        (self.fields, self.memory)
    }
}

impl<R: Read> DecodedInput<R> {
    pub(crate) fn with_dialect<'a>(
        self,
        dialect: &'a InputDialect,
    ) -> Intake<DialectParser<'a, BufReader<DecodeReader<R>>>> {
        let Self {
            parser,
            owned,
            compact,
            width,
            headers,
            prefetched,
            terminal,
            representation,
            _source,
            memory,
        } = self;
        Intake {
            parser: DialectParser::new(parser, dialect),
            owned,
            compact,
            width,
            headers,
            prefetched,
            terminal,
            representation,
            _source,
            memory,
        }
    }

    pub(crate) fn new(
        source: R,
        settings: &CsvSettings,
        maximum: usize,
        mut memory: Reservation,
    ) -> Result<Self> {
        memory.resize(SOURCE_BUFFER + std::mem::size_of::<DecodeReader<R>>())?;
        let decoder = DecodeReader::new(source, &settings.encoding)?;
        Ok(Self::from_parser(
            Parser::new(
                BufReader::with_capacity(SOURCE_BUFFER, decoder),
                settings.clone(),
                maximum,
            ),
            memory,
            settings.headers,
        ))
    }

    /// Inspection retains its existing source-buffer-only envelope; decoder
    /// inline arrays and configuration clones remain outside that accounting.
    pub(crate) fn inspection(
        source: R,
        settings: &CsvSettings,
        maximum: usize,
        mut memory: Reservation,
    ) -> Result<Self> {
        let decoder = DecodeReader::new(source, &settings.encoding)?;
        memory.resize(SOURCE_BUFFER)?;
        Ok(Self::from_parser(
            Parser::new(
                BufReader::with_capacity(SOURCE_BUFFER, decoder),
                settings.clone(),
                maximum,
            ),
            memory,
            settings.headers,
        ))
    }
}

impl<P: Records> Intake<P> {
    // Also the internal parser seam for pre-read denial controls.
    fn from_parser(parser: P, source: Reservation, headers: bool) -> Self {
        let memory = source.sibling();
        Self {
            parser,
            owned: Vec::new(),
            compact: CompactRecord::default(),
            width: None,
            headers,
            prefetched: false,
            terminal: false,
            representation: None,
            _source: source,
            memory,
        }
    }

    #[cfg(any(test, feature = "resource-contract-tests"))]
    pub(crate) fn preadmitted_parser(parser: P, source: Reservation, headers: bool) -> Self {
        Self::from_parser(parser, source, headers)
    }

    fn select_representation(&mut self, representation: Representation) -> Result<()> {
        if self
            .representation
            .is_some_and(|current| current != representation)
        {
            self.terminal = true;
            anyhow::bail!("CSV intake cannot change record representation");
        }
        self.representation = Some(representation);
        Ok(())
    }

    pub(crate) fn reservation(&self) -> Reservation {
        self.memory.sibling()
    }
    pub(crate) fn columns(&self) -> usize {
        self.width.unwrap_or(0)
    }
    pub(crate) fn owned(&self) -> &Vec<String> {
        &self.owned
    }
    pub(crate) fn compact(&self) -> &CompactRecord {
        &self.compact
    }

    fn end_on_error<T>(&mut self, result: Result<T>) -> Result<T> {
        if result.is_err() {
            self.terminal = true;
        }
        result
    }

    pub(crate) fn header(&mut self) -> Result<Option<HeaderFields>> {
        if !std::mem::take(&mut self.headers) || self.terminal {
            return Ok(None);
        }
        let result = (|| {
            let present = self
                .parser
                .next_record_into_reserved(&mut self.owned, &mut |n| self.memory.resize(n))?;
            let mut memory = self.memory.sibling();
            memory.resize(owned_capacity(&self.owned)?)?;
            let fields = std::mem::take(&mut self.owned);
            // Retained payload admission overlaps the parser's existing charge.
            self.memory.resize(self.parser.scratch_capacity())?;
            if present {
                self.width = Some(fields.len());
                Ok(Some(HeaderFields { fields, memory }))
            } else {
                self.terminal = true;
                drop(fields);
                Ok(None)
            }
        })();
        self.end_on_error(result)
    }

    /// Profiling needs column discovery before selection/statistic setup, but
    /// validates that first data row at its original later consumption point.
    pub(crate) fn prefetch(&mut self) -> Result<bool> {
        if self.terminal {
            return Ok(false);
        }
        self.select_representation(Representation::Owned)?;
        if self.prefetched {
            return Ok(true);
        }
        let result = self
            .parser
            .next_record_into_reserved(&mut self.owned, &mut |n| self.memory.resize(n));
        let present = self.end_on_error(result)?;
        self.prefetched = present;
        if present {
            self.width.get_or_insert(self.owned.len());
        } else {
            self.terminal = true;
        }
        Ok(present)
    }

    pub(crate) fn next_owned(&mut self, check: impl FnOnce() -> Result<()>) -> Result<bool> {
        if self.terminal {
            return Ok(false);
        }
        self.select_representation(Representation::Owned)?;
        let result = (|| {
            let present = if self.prefetched {
                self.prefetched = false;
                true
            } else {
                self.parser
                    .next_record_into_reserved(&mut self.owned, &mut |n| self.memory.resize(n))?
            };
            if !present {
                self.terminal = true;
                return Ok(false);
            }
            check()?;
            self.validate(self.owned.len())?;
            Ok(true)
        })();
        self.end_on_error(result)
    }

    pub(crate) fn next_compact(
        &mut self,
        check: impl FnOnce() -> Result<()>,
        mut reserve: impl FnMut(&mut Reservation, usize) -> Result<()>,
    ) -> Result<bool> {
        if self.terminal {
            return Ok(false);
        }
        self.select_representation(Representation::Compact)?;
        let result = (|| {
            if !self
                .parser
                .next_compact_record_into_reserved(&mut self.compact, &mut |n| {
                    reserve(&mut self.memory, n)
                })?
            {
                self.terminal = true;
                return Ok(false);
            }
            check()?;
            self.validate(self.compact.len())?;
            Ok(true)
        })();
        self.end_on_error(result)
    }

    fn validate(&mut self, columns: usize) -> Result<()> {
        let expected = *self.width.get_or_insert(columns);
        ensure!(
            columns == expected,
            "CSV record {} has {columns} fields, expected {expected}",
            self.parser.record_number()
        );
        Ok(())
    }

    /// The callback either restores reusable storage or transfers it to an
    /// independently admitted consumer before returning. Keep our grant through
    /// that handoff, including callback failure and returned-buffer admission.
    pub(crate) fn consume_owned<T>(
        &mut self,
        consume: impl FnOnce(&mut Vec<String>) -> Result<T>,
    ) -> Result<T> {
        self.select_representation(Representation::Owned)?;
        let result = consume(&mut self.owned);
        self.end_on_error(result)
    }

    pub(crate) fn consume_compact<T>(
        &mut self,
        consume: impl FnOnce(&mut CompactRecord) -> Result<T>,
    ) -> Result<T> {
        self.select_representation(Representation::Compact)?;
        let result = (|| {
            let value = consume(&mut self.compact)?;
            self.memory
                .resize(self.parser.scratch_capacity() + self.compact.capacity())?;
            Ok(value)
        })();
        self.end_on_error(result)
    }

    /// Internal profiling adapter: its slots must be destroyed before Intake.
    /// The aggregate charge covers every retained slot, not just the active row.
    #[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
    pub(crate) fn take_prefetched(&mut self, fields: &mut Vec<String>) {
        std::mem::swap(fields, &mut self.owned);
        self.prefetched = false;
    }

    #[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
    pub(crate) fn validate_slot(&mut self, fields: &[String]) -> Result<()> {
        let result = self.validate(fields.len());
        self.end_on_error(result)
    }

    #[cfg(all(feature = "experimental-parallel-profile", not(target_os = "wasi")))]
    pub(crate) fn next_slot(&mut self, fields: &mut Vec<String>) -> Result<bool> {
        if self.terminal {
            return Ok(false);
        }
        let result = (|| {
            let other = (self.memory.bytes() as usize)
                .checked_sub(self.parser.scratch_capacity())
                .and_then(|n| n.checked_sub(owned_capacity(fields).ok()?))
                .context("profile slot capacity exceeds intake admission")?;
            if !self
                .parser
                .next_record_into_reserved(fields, &mut |n| self.memory.resize(other + n))?
            {
                self.terminal = true;
                return Ok(false);
            }
            self.validate(fields.len())?;
            Ok(true)
        })();
        self.end_on_error(result)
    }
}

fn owned_capacity(fields: &Vec<String>) -> Result<usize> {
    fields.iter().try_fold(
        fields
            .capacity()
            .checked_mul(std::mem::size_of::<String>())
            .context("header capacity overflow")?,
        |n, field| {
            n.checked_add(field.capacity())
                .context("header capacity overflow")
        },
    )
}

#[cfg(test)]
mod tests;
