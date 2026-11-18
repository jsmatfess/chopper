//! Bounded physical observations, not a calibrated cost selector or replay log.
use super::*;

const CAPACITY: usize = 16;

#[derive(Default, Serialize)]
pub(crate) struct ShapeObservation {
    pub rows_decoded: u64,
    pub rows_keyed: u64,
    pub decoded_payload_bytes: u64,
    pub maximum_payload_bytes: u64,
    pub maximum_fields: u64,
    pub maximum_row_heap_capacity_bytes: u64,
    pub maximum_key_heap_capacity_bytes: u64,
    pub maximum_key_bytes: u64,
    pub totals_saturated: bool,
}
impl ShapeObservation {
    pub(crate) fn decoded(&mut self, row: &PackedRow) {
        let (fields, payload, _, _) = row.observation_sizes();
        self.rows_decoded = self.rows_decoded.saturating_add(1);
        self.maximum_fields = self.maximum_fields.max(fields as u64);
        self.maximum_payload_bytes = self.maximum_payload_bytes.max(payload as u64);
        if let Some(total) = self.decoded_payload_bytes.checked_add(payload as u64) {
            self.decoded_payload_bytes = total;
        } else {
            self.decoded_payload_bytes = u64::MAX;
            self.totals_saturated = true;
        }
    }
    pub(crate) fn keyed(&mut self, row: &PackedRow) {
        let (_, _, heap, key_heap) = row.observation_sizes();
        self.rows_keyed = self.rows_keyed.saturating_add(1);
        self.maximum_row_heap_capacity_bytes =
            self.maximum_row_heap_capacity_bytes.max(heap as u64);
        self.maximum_key_heap_capacity_bytes =
            self.maximum_key_heap_capacity_bytes.max(key_heap as u64);
        self.maximum_key_bytes = self.maximum_key_bytes.max(row.key.len() as u64);
    }
}

#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Phase {
    Admission,
    Preparation,
    OriginalRetry,
    Emission,
}
#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Outcome {
    Terminal,
    FusedCommitted,
    OriginalCommitted,
}
#[derive(Clone, Copy, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum Denial {
    Local,
    Shared,
}
impl Denial {
    pub(crate) fn from_error(error: &anyhow::Error) -> Option<Self> {
        error
            .downcast_ref::<crate::resources::MemoryAdmission>()
            .map(|denial| match denial {
                crate::resources::MemoryAdmission::Local => Self::Local,
                crate::resources::MemoryAdmission::Shared { .. } => Self::Shared,
            })
    }
}

#[derive(Clone, Copy, Default, Serialize)]
struct Counters {
    sort_runs: u64,
    resident_sorts: u64,
    merge_operations: u64,
    temporary_bytes_read: u64,
    temporary_bytes_written: u64,
}
impl Counters {
    fn read(ctx: &Context) -> Self {
        let budget = &ctx.budget;
        Self {
            sort_runs: budget.sort_runs.load(AtomicOrdering::Relaxed),
            resident_sorts: budget.resident_sorts.load(AtomicOrdering::Relaxed),
            merge_operations: budget.merge_operations.load(AtomicOrdering::Relaxed),
            temporary_bytes_read: budget.read.load(AtomicOrdering::Relaxed),
            temporary_bytes_written: budget.written.load(AtomicOrdering::Relaxed),
        }
    }
    fn since(self, earlier: Self) -> Self {
        Self {
            sort_runs: self.sort_runs.saturating_sub(earlier.sort_runs),
            resident_sorts: self.resident_sorts.saturating_sub(earlier.resident_sorts),
            merge_operations: self
                .merge_operations
                .saturating_sub(earlier.merge_operations),
            temporary_bytes_read: self
                .temporary_bytes_read
                .saturating_sub(earlier.temporary_bytes_read),
            temporary_bytes_written: self
                .temporary_bytes_written
                .saturating_sub(earlier.temporary_bytes_written),
        }
    }
}

#[derive(Serialize)]
pub(crate) struct DecisionRecord {
    pub shuffle_step: usize,
    pub partition_step: usize,
    pub parent_ordinal: u64,
    pub parent_offset: u64,
    pub parent_rows: u64,
    pub shape: ShapeObservation,
    pub observation_complete: bool,
    pub key_observation_complete: bool,
    pub phase: Phase,
    pub outcome: Outcome,
    pub admission_denial: Option<Denial>,
    pub admission_denial_phase: Option<Phase>,
    pub terminal_admission_denial: Option<Denial>,
    pub cancelled: bool,
    pub cleanup_failed: bool,
    context_counter_delta: Counters,
    #[serde(skip)]
    before: Counters,
}
impl DecisionRecord {
    pub(crate) fn new(
        ctx: &Context,
        shuffle_step: usize,
        partition_step: usize,
        parent_ordinal: u64,
        parent: &Group,
    ) -> Self {
        ctx.initialize_decision_audit();
        Self {
            shuffle_step,
            partition_step,
            parent_ordinal,
            parent_offset: parent.offset,
            parent_rows: parent.rows,
            shape: ShapeObservation::default(),
            observation_complete: false,
            key_observation_complete: false,
            phase: Phase::Admission,
            outcome: Outcome::Terminal,
            admission_denial: None,
            admission_denial_phase: None,
            terminal_admission_denial: None,
            cancelled: false,
            cleanup_failed: false,
            context_counter_delta: Counters::default(),
            before: Counters::read(ctx),
        }
    }
    pub(crate) fn finish(mut self, ctx: &Context, error: Option<&anyhow::Error>) {
        self.terminal_admission_denial = error.and_then(Denial::from_error);
        self.observation_complete = self.shape.rows_decoded == self.parent_rows;
        self.key_observation_complete = self.shape.rows_keyed == self.parent_rows;
        self.context_counter_delta = Counters::read(ctx).since(self.before);
        self.cancelled = ctx.budget.cancel.load(AtomicOrdering::Relaxed);
        self.cleanup_failed = ctx.budget.cleanup_failures.load(AtomicOrdering::Relaxed) > 0;
        let mut audit = ctx
            .budget
            .decision_audit
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        audit.completed_attempts = audit.completed_attempts.saturating_add(1);
        if audit.records.len() < CAPACITY && audit.reservation.is_some() {
            audit.records.push(self);
        } else {
            audit.omitted_attempts = audit.omitted_attempts.saturating_add(1);
        }
    }
}

#[derive(Default)]
pub(super) struct DecisionAudit {
    // Drop allocations before their charge. Reservation owns Workspace, not Budget.
    records: Vec<DecisionRecord>,
    reservation: Option<Reservation>,
    initialized: bool,
    collection_denied: bool,
    completed_attempts: u64,
    omitted_attempts: u64,
}
#[derive(Serialize)]
pub(super) struct AuditView<'a> {
    version: u32,
    policy: &'static str,
    selector: Option<()>,
    calibration: Option<()>,
    scope: &'static str,
    counter_scope: &'static str,
    capacity: usize,
    initialized: bool,
    reserved_bytes: u64,
    collection_denied: bool,
    completed_attempts: u64,
    omitted_attempts: u64,
    records: &'a [DecisionRecord],
}
impl Context {
    fn initialize_decision_audit(&self) {
        let mut audit = self
            .budget
            .decision_audit
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        if audit.initialized {
            return;
        }
        audit.initialized = true;
        let mut reservation = Reservation::new(self);
        let mut records = Vec::new();
        if reservation.reserve_vec(&mut records, CAPACITY).is_err() {
            // Optional telemetry cannot turn grant/allocation denial into a job
            // error. Drop any partially allocated vector before its reservation.
            drop(records);
            audit.collection_denied = true;
            return;
        }
        audit.records = records;
        audit.reservation = Some(reservation);
    }
    pub(super) fn with_decision_audit_snapshot<R>(
        &self,
        run: impl FnOnce(AuditView<'_>) -> R,
    ) -> R {
        let audit = self
            .budget
            .decision_audit
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        run(AuditView {
            version: 1,
            policy: "experiment_gate_v1",
            selector: None,
            calibration: None,
            scope: "completed retained-parent attempts; first records, not a representative sample",
            counter_scope:
                "context deltas, including failed tentative work and original-stage retry",
            capacity: CAPACITY,
            initialized: audit.initialized,
            reserved_bytes: audit.reservation.as_ref().map_or(0, Reservation::bytes),
            collection_denied: audit.collection_denied,
            completed_attempts: audit.completed_attempts,
            omitted_attempts: audit.omitted_attempts,
            records: &audit.records,
        })
    }
    #[cfg(any(test, feature = "resource-contract-tests"))]
    pub(super) fn decision_audit_diagnostics(&self) -> serde_json::Value {
        let audit = self
            .budget
            .decision_audit
            .lock()
            .unwrap_or_else(|error| error.into_inner());
        serde_json::json!({
            "version": 1, "policy": "experiment_gate_v1", "selector": null, "calibration": null,
            "scope": "completed retained-parent attempts; first records, not a representative sample",
            "counter_scope": "context deltas, including failed tentative work and original-stage retry",
            "capacity": CAPACITY, "initialized": audit.initialized,
            "reserved_bytes": audit.reservation.as_ref().map_or(0, Reservation::bytes),
            "collection_denied": audit.collection_denied,
            "completed_attempts": audit.completed_attempts, "omitted_attempts": audit.omitted_attempts,
            "records": audit.records,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn context(pool: Arc<crate::resources::MemoryPool>) -> Result<Context> {
        Context::with_memory_pool(
            &chopper_core::Resources {
                workers: 1,
                memory_mb: 32.into(),
                max_record_bytes: 1024 * 1024,
                ..Default::default()
            },
            Arc::new(AtomicBool::new(false)),
            Arc::new(|_| {}),
            pool,
        )
    }
    fn parent() -> Group {
        Group {
            offset: 99,
            rows: 2,
            lineage: vec![],
            exact: false,
        }
    }

    #[test]
    fn audit_is_lazy_bounded_and_charged_through_last_context_clone() -> Result<()> {
        let pool = Arc::new(crate::resources::MemoryPool::new(64 * 1024 * 1024));
        let ctx = context(pool.clone())?;
        let directory_bytes = ctx.directory_reserved_bytes();
        assert_eq!(pool.usage().reserved_bytes, directory_bytes);
        assert_eq!(
            ctx.diagnostics()["shuffle_partition_decisions"]["initialized"],
            false
        );
        for ordinal in 0..20 {
            DecisionRecord::new(&ctx, 2, 3, ordinal, &parent()).finish(&ctx, None);
        }
        let diagnostics = ctx.diagnostics();
        let audit = &diagnostics["shuffle_partition_decisions"];
        assert_eq!(audit["records"].as_array().unwrap().len(), CAPACITY);
        assert_eq!(audit["completed_attempts"], 20);
        assert_eq!(audit["omitted_attempts"], 4);
        assert_eq!(audit["records"][15]["parent_ordinal"], 15);
        assert_eq!(audit["records"][0]["observation_complete"], false);
        let required = audit["reserved_bytes"].as_u64().unwrap();
        assert!(required >= (CAPACITY * std::mem::size_of::<DecisionRecord>()) as u64);
        assert_eq!(pool.usage().reserved_bytes, required + directory_bytes);
        println!("decision audit retained capacity: {required} bytes");
        let last = ctx.clone();
        drop(ctx);
        assert_eq!(pool.usage().reserved_bytes, required + directory_bytes);
        drop(last);
        assert_eq!(pool.usage().reserved_bytes, 0);
        Ok(())
    }

    #[test]
    fn audit_shared_capacity_boundary_omits_records_without_an_execution_error() -> Result<()> {
        let required = (CAPACITY * std::mem::size_of::<DecisionRecord>()) as u64;
        let directory_bytes = context(Arc::new(crate::resources::MemoryPool::new(
            64 * 1024 * 1024,
        )))?
        .directory_reserved_bytes();
        for available in [required - 1, required, required + 1] {
            let pool = Arc::new(crate::resources::MemoryPool::new(
                available + directory_bytes,
            ));
            let ctx = context(pool.clone())?;
            assert_eq!(ctx.directory_reserved_bytes(), directory_bytes);
            DecisionRecord::new(&ctx, 0, 1, 0, &parent()).finish(&ctx, None);
            let diagnostics = ctx.diagnostics();
            let audit = &diagnostics["shuffle_partition_decisions"];
            assert_eq!(audit["collection_denied"], available < required);
            assert_eq!(audit["omitted_attempts"], u64::from(available < required));
            assert_eq!(
                pool.usage().reserved_bytes,
                directory_bytes + if available < required { 0 } else { required }
            );
            drop(ctx);
            assert_eq!(pool.usage().reserved_bytes, 0);
        }
        Ok(())
    }

    #[test]
    fn observations_separate_payload_lengths_and_actual_heap_capacity() -> Result<()> {
        let mut shape = ShapeObservation::default();
        for payload in ["short".to_owned(), "x".repeat(100_000)] {
            let row = PackedRow::new(Row {
                id: 0,
                ordinal: 0,
                key: vec![7; 33],
                fields: vec!["a".into(), payload],
            })?;
            let (fields, payload, heap, key_heap) = row.observation_sizes();
            shape.decoded(&row);
            shape.keyed(&row);
            assert_eq!(fields, 2);
            assert!(heap >= payload);
            assert_eq!(key_heap, 33);
        }
        assert_eq!(shape.rows_decoded, 2);
        assert_eq!(shape.rows_keyed, 2);
        assert_eq!(shape.maximum_payload_bytes, 100_001);
        assert_eq!(shape.decoded_payload_bytes, 100_007);
        assert_eq!(shape.maximum_fields, 2);
        assert_eq!(shape.maximum_key_bytes, 33);
        assert_eq!(shape.maximum_key_heap_capacity_bytes, 33);
        assert!(!shape.totals_saturated);
        shape.decoded_payload_bytes = u64::MAX;
        let row = PackedRow::new(Row {
            id: 1,
            ordinal: 1,
            key: vec![],
            fields: vec!["a".into()],
        })?;
        shape.decoded(&row);
        assert!(shape.totals_saturated);
        assert_eq!(shape.decoded_payload_bytes, u64::MAX);
        Ok(())
    }
}
