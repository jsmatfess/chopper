//! Decoded records entering the existing header/digest/operation consumer.
//! Readers retain their own I/O grants; this callback charges caller-owned
//! record/scratch capacity before growth and through consumer handoff.
use anyhow::Result;
use chopper_core::csv::{CompactRecord, Parser};
use std::io::BufRead;

pub(crate) trait Records {
    fn record_number(&self) -> u64;
    fn scratch_capacity(&self) -> usize;
    fn next_record_into_reserved(
        &mut self,
        fields: &mut Vec<String>,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool>;
    fn next_compact_record_into_reserved(
        &mut self,
        fields: &mut CompactRecord,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool>;
}

impl<R: BufRead> Records for Parser<R> {
    fn record_number(&self) -> u64 {
        self.record
    }
    fn scratch_capacity(&self) -> usize {
        Parser::scratch_capacity(self)
    }
    fn next_record_into_reserved(
        &mut self,
        fields: &mut Vec<String>,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        Parser::next_record_into_reserved(self, fields, reserve)
    }
    fn next_compact_record_into_reserved(
        &mut self,
        fields: &mut CompactRecord,
        reserve: &mut impl FnMut(usize) -> Result<()>,
    ) -> Result<bool> {
        Parser::next_compact_record_into_reserved(self, fields, reserve)
    }
}
