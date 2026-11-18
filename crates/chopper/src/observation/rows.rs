//! RowSink adapter: a successful row call accounts for itself in its owning span.
use super::physical::Span;
use crate::storage::{Group, PackedRow, Row, RowSink};
use anyhow::Result;

/// Forward without converting compact rows. Starting happens at the real row
/// boundary; failed writes never increment successfully delivered rows.
pub(crate) struct ObservedRows<'a, 'ctx, S> {
    inner: &'a mut S,
    span: &'a mut Option<Span<'ctx>>,
}
impl<'a, 'ctx, S: RowSink> ObservedRows<'a, 'ctx, S> {
    pub(crate) fn new(inner: &'a mut S, span: &'a mut Option<Span<'ctx>>) -> Self {
        Self { inner, span }
    }
    fn start(&mut self) {
        if let Some(span) = self.span.as_mut() {
            span.start();
        }
    }
    fn delivered(&mut self) {
        if let Some(span) = self.span.as_mut() {
            span.row_processed();
        }
    }
}
impl<S: RowSink> RowSink for ObservedRows<'_, '_, S> {
    fn physical_input(&mut self, source: Option<u32>) {
        self.inner.physical_input(source);
    }
    fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
        self.inner.begin(lineage, exact)
    }
    fn row(&mut self, group: &mut Group, row: &Row) -> Result<()> {
        self.start();
        self.inner.row(group, row)?;
        self.delivered();
        Ok(())
    }
    fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
        self.start();
        self.inner.packed_row_ref(group, row)?;
        self.delivered();
        Ok(())
    }
    fn end(&mut self, group: Group) -> Result<()> {
        self.inner.end(group)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        observation::{physical::Kind, Status},
        storage::Context,
    };
    use std::sync::{atomic::AtomicBool, Arc, Mutex};
    #[derive(Default)]
    struct Sink {
        owned: usize,
        packed: usize,
    }
    impl RowSink for Sink {
        fn begin(&self, lineage: Vec<serde_json::Value>, exact: bool) -> Group {
            Group {
                offset: 0,
                rows: 0,
                lineage,
                exact,
            }
        }
        fn row(&mut self, group: &mut Group, _: &Row) -> Result<()> {
            self.owned += 1;
            group.rows += 1;
            Ok(())
        }
        fn packed_row_ref(&mut self, group: &mut Group, row: &PackedRow) -> Result<()> {
            anyhow::ensure!(row.id != 2, "fixture row rejected");
            self.packed += 1;
            group.rows += 1;
            Ok(())
        }
        fn end(&mut self, _: Group) -> Result<()> {
            Ok(())
        }
    }
    #[test]
    fn owned_and_compact_row_calls_account_for_themselves_and_exclude_failures() -> Result<()> {
        let mut ctx = Context::new(
            &chopper_core::Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )?;
        let facts = Arc::new(Mutex::new(Vec::new()));
        let received = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            received.lock().unwrap().push(fact);
            true
        }));
        let row = |id| Row {
            id,
            ordinal: id,
            key: vec![],
            fields: vec!["valid".into()],
        };
        let packed = PackedRow::new(row(1))?;
        let rejected = PackedRow::new(row(2))?;
        let mut sink = Sink::default();
        let mut group = sink.begin(vec![], false);
        let mut work = ctx.physical_pending_span_for(Kind::Grouping, [1, 0]);
        let result = (|| -> Result<()> {
            let mut observed = ObservedRows::new(&mut sink, &mut work);
            observed.physical_input(None);
            assert!(facts.lock().unwrap().is_empty(), "wiring is not row work");
            observed.row(&mut group, &row(0))?;
            observed.packed_row_ref(&mut group, &packed)?;
            observed.packed_row_ref(&mut group, &rejected)?;
            Ok(())
        })();
        work.unwrap().finish_result(&result);
        assert!(result.is_err());
        assert_eq!((sink.owned, sink.packed, group.rows), (1, 1, 2));
        let facts = facts.lock().unwrap();
        let final_fact = facts.last().unwrap();
        assert_eq!((final_fact.rows, final_fact.status), (2, Status::Failed));
        Ok(())
    }
}
