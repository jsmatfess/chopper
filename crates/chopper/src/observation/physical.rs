//! Fixed-record prepared-Run facts. The caller owns the sink just like Notify.
use crate::{observation::Status, storage::Context};
use serde::Serialize;
use std::{sync::Arc, time::Instant};
pub type Sink = Arc<dyn Fn(Fact) -> bool + Send + Sync>;
pub const MAX_OPERATION: usize = 16;
pub const ID_BASE: u32 = 1000;
pub const CATEGORY_SLOTS: u32 = 32;
pub const ROLE_SLOTS: u8 = 2;
pub const MAX_MEMBERSHIPS: usize = 16;
pub const MAX_RECORDS: u64 = 65536;
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
#[repr(u8)]
pub enum Kind {
    Read,
    ResidentSort,
    FisherYates,
    Grouping,
    Serialize,
    Materialize,
    Elided,
    RoutedGrouping,
    Spill,
    Merge,
    HierarchicalMerge,
    MergeTraversal,
    Routing,
    Fallback,
    Reuse,
    ExactMembership,
    ProbabilisticMembership,
    Stratification,
    DatasetMaterialize,
    SharedRanges,
    InterleavedMembership,
    BalancedTraversal,
    FusedBalanced,
    GzipInput,
    ZstandardInput,
    ZipInput,
    GzipOutput,
    ZstandardOutput,
    ZipDeflate,
    ZipArchive,
    StageComplete,
    Omitted,
}
/// Every physical step must declare its reporting contract here. Batch work has
/// a measurable final size, but cannot claim incremental progress inside a sort.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum ProgressUnit {
    Rows,
    Bytes,
    Batch,
    Phase,
}
impl Kind {
    pub(crate) fn progress_unit(self) -> ProgressUnit {
        match self {
            Self::Read
            | Self::Grouping
            | Self::Serialize
            | Self::RoutedGrouping
            | Self::Merge
            | Self::HierarchicalMerge
            | Self::MergeTraversal
            | Self::Routing
            | Self::ExactMembership
            | Self::ProbabilisticMembership
            | Self::Stratification
            | Self::DatasetMaterialize
            | Self::SharedRanges
            | Self::InterleavedMembership
            | Self::BalancedTraversal
            | Self::FusedBalanced => ProgressUnit::Rows,
            Self::GzipInput
            | Self::ZstandardInput
            | Self::ZipInput
            | Self::GzipOutput
            | Self::ZstandardOutput
            | Self::ZipDeflate
            | Self::ZipArchive => ProgressUnit::Bytes,
            Self::ResidentSort | Self::FisherYates | Self::Spill | Self::Fallback | Self::Reuse => {
                ProgressUnit::Batch
            }
            Self::Materialize | Self::Elided | Self::StageComplete | Self::Omitted => {
                ProgressUnit::Phase
            }
        }
    }
}
pub(crate) fn identity(operation: usize, kind: Kind) -> Option<u32> {
    identity_for(operation, kind, 0)
}
pub(crate) fn identity_for(operation: usize, kind: Kind, role: u8) -> Option<u32> {
    if operation > MAX_OPERATION + 1 || role >= ROLE_SLOTS {
        return None;
    }
    Some(
        ID_BASE
            + (role as u32 * (MAX_OPERATION as u32 + 2) + operation as u32) * CATEGORY_SLOTS
            + kind as u32,
    )
}
const _: () = assert!((Kind::Omitted as u32) < CATEGORY_SLOTS);
fn empty_memberships(values: &[u64; MAX_MEMBERSHIPS]) -> bool {
    values.iter().all(|n| *n == 0)
}
#[derive(Clone, Copy, Debug, Serialize)]
pub struct Fact {
    pub id: u32,
    pub role: u8,
    pub groups: u64,
    pub empty_groups: u64,
    #[serde(skip_serializing_if = "empty_memberships")]
    pub memberships: [u64; MAX_MEMBERSHIPS],
    pub membership_len: u8,
    pub omitted_memberships: u64,
    pub kind: Kind,
    pub operations: [usize; 2],
    pub rows: u64,
    pub bytes: u64,
    pub seconds: f64,
    pub status: Status,
    pub source_omitted: bool,
    pub source: Option<u32>,
    pub sources: [Option<u32>; 4],
    pub attempt: u64,
    pub runs: u64,
    pub level: Option<u32>,
}
#[derive(Clone, Copy, Default)]
pub(crate) struct AllocationCounts {
    pub rows: u64,
    pub groups: u64,
    pub empty_groups: u64,
    pub memberships: [u64; MAX_MEMBERSHIPS],
    pub len: usize,
}
/// Owns observation lifetime and delivery cadence. Report cumulative work at
/// successful row/I/O boundaries; callers never decide whether to publish it.
#[must_use = "An observation must be retained for the lifetime of its work"]
pub(crate) struct Attempt {
    reporter: crate::storage::PhysicalReporter,
    fact: Fact,
    start: Instant,
    last: Instant,
    next_report: u64,
    state: SpanState,
}
pub(crate) struct Span<'a> {
    _ctx: &'a Context,
    attempt: Attempt,
}
#[derive(PartialEq)]
#[repr(u8)]
enum SpanState {
    Pending,
    Active,
    Finished,
}
/// Monotone operation frontier. Call only after output and stage stats commit.
pub(crate) struct StageCompletion<'a> {
    ctx: &'a Context,
    completed: usize,
}
impl StageCompletion<'_> {
    pub(crate) fn complete_through(&mut self, end: usize) {
        debug_assert!(end >= self.completed);
        for operation in self.completed + 1..=end.min(MAX_OPERATION) {
            self.ctx.physical_stage_complete(operation);
        }
        self.completed = end;
    }
}
impl Context {
    pub(crate) fn physical_stages(&self) -> StageCompletion<'_> {
        StageCompletion {
            ctx: self,
            completed: 0,
        }
    }
    pub(crate) fn physical_stage_complete(&self, operation: usize) {
        if operation > MAX_OPERATION + 1 {
            return;
        }
        if let Some(mut work) =
            self.physical_attempt_state(Kind::StageComplete, [operation, 0], [None; 4], true, false)
        {
            work.state = SpanState::Active;
            work.finish(Status::Completed, 0, 0, None);
        }
    }
    pub(crate) fn physical_identity(&self, kind: Kind) -> Option<u32> {
        identity_for(self.physical_operations[0], kind, self.physical_role)
    }
    pub(crate) fn physical_scope(&self, operations: [usize; 2]) -> Self {
        let mut scope = self.clone();
        scope.physical_operations = operations;
        scope
    }
    pub(crate) fn physical_attempt(&self, kind: Kind) -> Option<Attempt> {
        self.physical_attempt_from(
            kind,
            self.physical_operations,
            [self.physical_source, None, None, None],
        )
    }
    pub(crate) fn physical_attempt_from(
        &self,
        kind: Kind,
        operations: [usize; 2],
        sources: [Option<u32>; 4],
    ) -> Option<Attempt> {
        self.physical_attempt_details(kind, operations, sources, false)
    }
    pub(crate) fn physical_attempt_details(
        &self,
        kind: Kind,
        operations: [usize; 2],
        sources: [Option<u32>; 4],
        omitted: bool,
    ) -> Option<Attempt> {
        self.physical_attempt_state(kind, operations, sources, omitted, true)
    }
    fn physical_attempt_state(
        &self,
        kind: Kind,
        operations: [usize; 2],
        mut sources: [Option<u32>; 4],
        omitted: bool,
        emit: bool,
    ) -> Option<Attempt> {
        if !self.physical_enabled() {
            return None;
        }
        if matches!(kind, Kind::Serialize | Kind::Elided) {
            sources = [None; 4];
        }
        let fact = Fact {
            id: identity_for(operations[0], kind, self.physical_role).unwrap_or(u32::MAX),
            role: self.physical_role,
            groups: 0,
            empty_groups: 0,
            memberships: [0; MAX_MEMBERSHIPS],
            membership_len: 0,
            omitted_memberships: 0,
            kind,
            operations,
            rows: 0,
            bytes: 0,
            seconds: 0.,
            status: Status::Active,
            source_omitted: omitted
                || kind != Kind::Read
                    && kind != Kind::Elided
                    && sources.iter().all(Option::is_none),
            source: sources[0],
            sources,
            attempt: self.physical_attempt_id(),
            runs: 0,
            level: None,
        };
        let reporter = self.physical_reporter()?;
        if emit {
            reporter.emit(fact);
        }
        Some(Attempt {
            reporter,
            fact,
            start: Instant::now(),
            last: Instant::now(),
            next_report: match kind.progress_unit() {
                ProgressUnit::Rows => 4096,
                ProgressUnit::Bytes => 65536,
                ProgressUnit::Batch | ProgressUnit::Phase => u64::MAX,
            },
            state: if emit {
                SpanState::Active
            } else {
                SpanState::Pending
            },
        })
    }
    pub(crate) fn physical_span(&self, kind: Kind) -> Option<Span<'_>> {
        self.physical_span_for(kind, self.physical_operations)
    }
    pub(crate) fn physical_pending_span_for(
        &self,
        kind: Kind,
        operations: [usize; 2],
    ) -> Option<Span<'_>> {
        Some(Span {
            _ctx: self,
            attempt: self.physical_attempt_state(
                kind,
                operations,
                [self.physical_source, None, None, None],
                false,
                false,
            )?,
        })
    }
    pub(crate) fn physical_span_for(&self, kind: Kind, operations: [usize; 2]) -> Option<Span<'_>> {
        self.physical_span_from(kind, operations, [self.physical_source, None, None, None])
    }
    pub(crate) fn physical_span_from(
        &self,
        kind: Kind,
        operations: [usize; 2],
        sources: [Option<u32>; 4],
    ) -> Option<Span<'_>> {
        Some(Span {
            _ctx: self,
            attempt: self.physical_attempt_from(kind, operations, sources)?,
        })
    }
}
impl Attempt {
    pub(crate) fn allocation(mut self, status: Status, counts: AllocationCounts) {
        self.fact.groups = counts.groups;
        self.fact.empty_groups = counts.empty_groups;
        self.fact.memberships = counts.memberships;
        self.fact.membership_len =
            counts.len.min(counts.groups as usize).min(MAX_MEMBERSHIPS) as u8;
        self.fact.omitted_memberships = counts.groups.saturating_sub(MAX_MEMBERSHIPS as u64);
        self.finish(status, counts.rows, 0, None);
    }
    pub(crate) fn source(&mut self, source: Option<u32>) {
        let Some(source) = source else {
            self.fact.source_omitted = true;
            return;
        };
        if self.fact.sources.contains(&Some(source)) {
            return;
        }
        if let Some(index) = self.fact.sources.iter().position(Option::is_none) {
            if self.fact.sources.iter().all(Option::is_none) {
                self.fact.source_omitted = false;
            }
            self.fact.sources[index] = Some(source);
            self.fact.source = self.fact.sources[0];
        } else {
            self.fact.source_omitted = true;
        }
    }
    pub(crate) fn finish_groups(mut self, status: Status, rows: u64, groups: u64, empty: u64) {
        self.fact.groups = groups;
        self.fact.empty_groups = empty;
        self.finish(status, rows, 0, None);
    }
    fn start(&mut self) {
        if self.state == SpanState::Pending {
            self.state = SpanState::Active;
            self.start = Instant::now();
            self.last = self.start;
            self.reporter.emit(self.fact);
        }
    }
    pub(crate) fn bytes_processed(&mut self, bytes: u64) {
        debug_assert_eq!(self.fact.kind.progress_unit(), ProgressUnit::Bytes);
        debug_assert!(bytes >= self.fact.bytes);
        self.start();
        self.fact.bytes = bytes;
        self.publish(bytes, 65536);
    }
    pub(crate) fn finish_bytes(self, status: Status, bytes: u64) {
        self.finish_bytes_counts(status, bytes, 0);
    }
    pub(crate) fn finish_bytes_counts(mut self, status: Status, bytes: u64, entries: u64) {
        debug_assert!(
            status != Status::Completed || self.fact.bytes == bytes,
            "byte work must account for every successful I/O boundary"
        );
        self.fact.bytes = bytes;
        self.finish(status, 0, entries, None);
    }
    pub(crate) fn rows_processed(&mut self, rows: u64) {
        debug_assert_eq!(self.fact.kind.progress_unit(), ProgressUnit::Rows);
        debug_assert!(
            rows == self.fact.rows || rows == self.fact.rows.saturating_add(1),
            "streaming work must account at each successful row boundary"
        );
        self.start();
        self.fact.rows = rows;
        self.publish(rows, 4096);
    }
    fn publish(&mut self, total: u64, stride: u64) {
        if total < self.next_report {
            return;
        }
        self.next_report = total.saturating_add(stride);
        self.publish_if_due();
    }
    pub(crate) fn groups_processed(&mut self, groups: u64, empty: u64) {
        debug_assert!(groups >= self.fact.groups && empty <= groups);
        self.start();
        self.fact.groups = groups;
        self.fact.empty_groups = empty;
        if groups.is_multiple_of(4096) {
            self.publish_if_due();
        }
    }
    fn publish_if_due(&mut self) {
        if !self.reporter.enabled() || self.last.elapsed() < std::time::Duration::from_millis(100) {
            return;
        }
        self.last = Instant::now();
        self.fact.seconds = self.start.elapsed().as_secs_f64();
        self.reporter.emit(self.fact);
    }

    pub(crate) fn finish(mut self, status: Status, rows: u64, runs: u64, level: Option<u32>) {
        self.start();
        debug_assert!(status != Status::Active && status != Status::Unknown);
        debug_assert!(
            status != Status::Completed
                || self.fact.kind.progress_unit() != ProgressUnit::Rows
                || self.fact.rows == rows,
            "streaming work must account for every row at its processing boundary"
        );
        self.state = SpanState::Finished;
        self.fact.status = status;
        self.fact.rows = rows;
        self.fact.runs = runs;
        self.fact.level = level;
        self.fact.seconds = self.start.elapsed().as_secs_f64();
        self.reporter.emit(self.fact);
    }
}
impl Drop for Attempt {
    fn drop(&mut self) {
        if self.state == SpanState::Active {
            self.fact.status = Status::Interrupted;
            self.fact.seconds = self.start.elapsed().as_secs_f64();
            self.reporter.emit(self.fact);
        }
    }
}
impl Span<'_> {
    pub(crate) fn start(&mut self) {
        self.attempt.start();
    }
    pub(crate) fn rows_processed(&mut self, rows: u64) {
        self.attempt.rows_processed(rows);
    }
    pub(crate) fn row_processed(&mut self) {
        self.attempt
            .rows_processed(self.attempt.fact.rows.saturating_add(1));
    }
    pub(crate) fn finish_result<T>(self, result: &anyhow::Result<T>) {
        let rows = self.attempt.fact.rows;
        match result {
            Ok(_) => self.finish(rows),
            Err(error) => self.finish_error(error, rows),
        }
    }
    pub(crate) fn source(&mut self, source: Option<u32>) {
        self.attempt.source(source);
    }
    pub(crate) fn finish_error(self, error: &anyhow::Error, rows: u64) {
        self.attempt.finish(error_status(error), rows, 0, None);
    }
    pub(crate) fn finish(self, rows: u64) {
        self.finish_counts(rows, 0, None);
    }
    pub(crate) fn finish_counts(self, rows: u64, runs: u64, level: Option<u32>) {
        self.attempt.finish(Status::Completed, rows, runs, level);
    }
}

pub(crate) fn error_status(error: &anyhow::Error) -> Status {
    if error.chain().any(|e| e.is::<crate::storage::Cancelled>()) {
        Status::Interrupted
    } else {
        Status::Failed
    }
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) fn resource_contracts() -> anyhow::Result<serde_json::Value> {
    use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
    let resources = chopper_core::Resources {
        #[cfg(target_os = "wasi")]
        temp_dir: Some("/tmp".into()),
        ..Default::default()
    };
    let pool = Arc::new(crate::resources::MemoryPool::new(1024 * 1024 * 1024));
    let mut ctx = Context::with_memory_pool(
        &resources,
        Arc::new(AtomicBool::new(false)),
        Arc::new(|_| {}),
        pool.clone(),
    )?;
    let calls = Arc::new(AtomicU64::new(0));
    let omitted = Arc::new(AtomicU64::new(0));
    let counts = calls.clone();
    let omissions = omitted.clone();
    ctx.physical = Some(Arc::new(move |fact| {
        counts.fetch_add(1, Ordering::Relaxed);
        if fact.kind == Kind::Omitted {
            omissions.fetch_add(1, Ordering::Relaxed);
        }
        true
    }));
    let before = pool.usage().reserved_bytes;
    for _ in 0..32770 {
        if let Some(span) = ctx.physical_span(Kind::ResidentSort) {
            span.finish(1);
        }
    }
    assert_eq!(calls.load(Ordering::Relaxed), 65537);
    assert_eq!(omitted.load(Ordering::Relaxed), 1);
    assert_eq!(pool.usage().reserved_bytes, before);
    ctx.check()?;
    drop(ctx);
    assert_eq!(pool.usage().reserved_bytes, 0);
    assert!(std::mem::size_of::<Fact>() <= 384);
    assert!(std::mem::size_of::<Span<'_>>() <= 512);
    assert!(std::mem::size_of::<crate::storage::SortedRows>() <= 640);
    let maximal = Fact {
        id: u32::MAX,
        role: 1,
        kind: Kind::ProbabilisticMembership,
        operations: [MAX_OPERATION; 2],
        rows: u64::MAX,
        bytes: u64::MAX,
        seconds: f64::MAX,
        status: Status::Interrupted,
        source_omitted: true,
        source: Some(u32::MAX),
        sources: [Some(u32::MAX); 4],
        attempt: u64::MAX,
        runs: u64::MAX,
        level: Some(u32::MAX),
        groups: u64::MAX,
        empty_groups: u64::MAX,
        memberships: [u64::MAX; MAX_MEMBERSHIPS],
        membership_len: MAX_MEMBERSHIPS as u8,
        omitted_memberships: u64::MAX,
    };
    assert!(
        serde_json::to_vec(&maximal)?.len() + 16 <= 1024,
        "fixed producer serialization envelope"
    );
    for deny in [true, false] {
        let mut ctx = Context::with_memory_pool(
            &resources,
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool.clone(),
        )?;
        let count = Arc::new(AtomicU64::new(0));
        let counted = count.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            counted.fetch_add(1, Ordering::Relaxed);
            if deny {
                assert_eq!(fact.kind, Kind::Omitted);
            }
            false
        }));
        let baseline = pool.usage().reserved_bytes;
        let mut held = crate::storage::Reservation::new(&ctx);
        if deny {
            held.resize(ctx.memory / 2 - baseline as usize - 8191)?;
        }
        if let Some(span) = ctx.physical_span(Kind::ResidentSort) {
            span.finish(1);
        }
        assert_eq!(count.load(Ordering::Relaxed), 1);
        assert!(!ctx.physical_enabled());
        ctx.check()?;
        drop(held);
        assert_eq!(pool.usage().reserved_bytes, baseline);
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, 0);
    }
    Ok(
        serde_json::json!({"ordinary_records":65536,"omission_records":1,"retained_callback_grants":0}),
    )
}
#[cfg(test)]
mod tests {
    type Facts = std::sync::Arc<std::sync::Mutex<Vec<super::Fact>>>;
    fn captured() -> (crate::storage::Context, Facts) {
        use std::sync::{atomic::AtomicBool, Arc, Mutex};
        let mut ctx = crate::storage::Context::new(
            &chopper_core::Resources::default(),
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
        )
        .unwrap();
        let facts = Arc::new(Mutex::new(Vec::new()));
        let received = facts.clone();
        ctx.physical = Some(Arc::new(move |fact| {
            received.lock().unwrap().push(fact);
            true
        }));
        (ctx, facts)
    }
    #[test]
    fn reporting_retains_partial_rows_even_when_delivery_is_throttled() {
        let (ctx, facts) = captured();
        let mut span = ctx.physical_span(super::Kind::Grouping).unwrap();
        for rows in 1..=17 {
            span.rows_processed(rows);
        }
        drop(span);
        let facts = facts.lock().unwrap();
        let last = facts.last().unwrap();
        assert_eq!(last.status, crate::observation::Status::Interrupted);
        assert_eq!(last.rows, 17);
    }
    #[test]
    fn reporting_cannot_leave_a_started_attempt_active_when_its_owner_returns() {
        let (ctx, facts) = captured();
        let attempt = ctx.physical_attempt(super::Kind::ExactMembership).unwrap();
        drop(attempt);
        assert_eq!(
            facts.lock().unwrap().last().unwrap().status,
            crate::observation::Status::Interrupted
        );
    }
    #[test]
    fn reporting_owns_checkpoints_and_keeps_unpublished_tail_counts() {
        let (ctx, facts) = captured();
        let mut work = ctx.physical_attempt(super::Kind::Read).unwrap();
        work.last = std::time::Instant::now() - std::time::Duration::from_millis(110);
        for rows in 1..=4095 {
            work.rows_processed(rows);
        }
        assert_eq!(facts.lock().unwrap().len(), 1);
        work.rows_processed(4096);
        assert_eq!(facts.lock().unwrap().last().unwrap().rows, 4096);
        work.rows_processed(4097);
        assert_eq!(facts.lock().unwrap().len(), 2);
        drop(work);
        let facts = facts.lock().unwrap();
        assert_eq!(facts.last().unwrap().rows, 4097);
        assert_eq!(
            facts.last().unwrap().status,
            crate::observation::Status::Interrupted
        );
    }
    #[test]
    fn reporting_keeps_byte_and_empty_group_work_separate_from_rows() {
        let (ctx, facts) = captured();
        let mut bytes = ctx.physical_attempt(super::Kind::GzipInput).unwrap();
        bytes.bytes_processed(17);
        drop(bytes);
        let mut groups = ctx
            .physical_attempt(super::Kind::DatasetMaterialize)
            .unwrap();
        groups.groups_processed(1, 1);
        drop(groups);
        let facts = facts.lock().unwrap();
        assert_eq!((facts[1].rows, facts[1].bytes), (0, 17));
        assert_eq!(
            (facts[3].rows, facts[3].groups, facts[3].empty_groups),
            (0, 1, 1)
        );
    }
    #[test]
    fn reporting_pending_scopes_are_quiet_and_completion_is_not_duplicated() {
        let (ctx, facts) = captured();
        drop(ctx.physical_pending_span_for(super::Kind::Grouping, [1, 0]));
        assert!(facts.lock().unwrap().is_empty());
        for _ in 0..2 {
            let mut span = ctx
                .physical_pending_span_for(super::Kind::Grouping, [1, 0])
                .unwrap();
            span.row_processed();
            span.finish_result(&Ok(()));
        }
        let facts = facts.lock().unwrap();
        assert_eq!(facts.len(), 4);
        assert_eq!(facts[1].status, crate::observation::Status::Completed);
        assert_eq!(facts[3].status, crate::observation::Status::Completed);
        assert_ne!(facts[1].attempt, facts[3].attempt);
    }
    #[cfg(debug_assertions)]
    #[test]
    #[should_panic(expected = "streaming work must account for every row")]
    fn reporting_rejects_success_without_row_accounting() {
        let (ctx, _) = captured();
        ctx.physical_span(super::Kind::Grouping).unwrap().finish(1);
    }
    #[cfg(debug_assertions)]
    #[test]
    #[should_panic(expected = "streaming work must account at each successful row boundary")]
    fn reporting_rejects_catching_up_only_at_completion() {
        let (ctx, _) = captured();
        ctx.physical_attempt(super::Kind::Read)
            .unwrap()
            .rows_processed(4096);
    }
    #[test]
    fn saturation_and_release() {
        super::resource_contracts().unwrap();
    }
}
