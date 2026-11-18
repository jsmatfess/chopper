//! Borrowed diagnostic schema. Admission occurs after the visitor releases locks.
use super::*;
use serde::ser::SerializeMap;
pub(crate) struct Snapshot<'a> {
    ctx: &'a Context,
    process_memory: Option<crate::resources::MemoryUsageView<'a>>,
    #[cfg(feature = "experimental-shuffle-partition")]
    audit: decision_audit::AuditView<'a>,
}
impl Serialize for Snapshot<'_> {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        let mut map = serializer.serialize_map(None)?;
        map.serialize_entry(
            "temporary_bytes_written",
            &(self.ctx.budget.written.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "sort_runs",
            &(self.ctx.budget.sort_runs.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "merge_operations",
            &(self
                .ctx
                .budget
                .merge_operations
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "merge_inputs",
            &(self.ctx.budget.merge_inputs.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "temporary_bytes_read",
            &(self.ctx.budget.read.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "temporary_files_created",
            &(self.ctx.budget.files_created.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "temporary_cleanup_failures",
            &(self
                .ctx
                .budget
                .cleanup_failures
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "temporary_path_reserved_bytes",
            &(self.ctx.budget.path_bytes.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "peak_temporary_files",
            &(self.ctx.budget.peak_files.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry("grouping_policy", &(self.ctx.grouping))?;
        map.serialize_entry(
            "resident_sorts",
            &(self.ctx.budget.resident_sorts.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "sort_calls",
            &(self.ctx.budget.sort_calls.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "sort_rows",
            &(self.ctx.budget.sort_rows.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "sort_seconds",
            &(self
                .ctx
                .budget
                .sort_nanoseconds
                .load(AtomicOrdering::Relaxed) as f64
                / 1e9),
        )?;
        map.serialize_entry(
            "fisher_yates_calls",
            &(self
                .ctx
                .budget
                .fisher_yates_calls
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "fisher_yates_rows",
            &(self
                .ctx
                .budget
                .fisher_yates_rows
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "fisher_yates_seconds",
            &(self
                .ctx
                .budget
                .fisher_yates_nanoseconds
                .load(AtomicOrdering::Relaxed) as f64
                / 1e9),
        )?;
        map.serialize_entry(
            "routed_groupings",
            &(self.ctx.budget.routed_groups.load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "routing_fallbacks",
            &(self
                .ctx
                .budget
                .routing_fallbacks
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "routing_reused_runs",
            &(self
                .ctx
                .budget
                .routing_reused_runs
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry("process_memory", &(self.process_memory))?;
        map.serialize_entry(
            "spill_format_candidate",
            &(cfg!(feature = "experimental-spill-blocks")),
        )?;
        map.serialize_entry(
            "compact_spill_files",
            &(self
                .ctx
                .budget
                .compact_spill_files
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "compact_spill_blocks",
            &(self
                .ctx
                .budget
                .compact_spill_blocks
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "compact_spill_rows",
            &(self
                .ctx
                .budget
                .compact_spill_rows
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "compact_spill_source_bytes",
            &(self
                .ctx
                .budget
                .compact_spill_source_bytes
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "compact_spill_stored_bytes",
            &(self
                .ctx
                .budget
                .compact_spill_stored_bytes
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "compact_spill_fallbacks",
            &(self
                .ctx
                .budget
                .compact_spill_fallbacks
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "shuffle_partition_fusions",
            &(self
                .ctx
                .budget
                .shuffle_partition_fusions
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "shuffle_partition_rows",
            &(self
                .ctx
                .budget
                .shuffle_partition_rows
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "shuffle_partition_retries",
            &(self
                .ctx
                .budget
                .shuffle_partition_retries
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry("workspace_reserved_bytes", &(self.ctx.workspace.used()))?;
        map.serialize_entry(
            "peak_workspace_reserved_bytes",
            &(self.ctx.workspace.peak()),
        )?;
        map.serialize_entry(
            "directory_path_reserved_bytes",
            &(self.ctx.directory_reserved_bytes()),
        )?;
        map.serialize_entry(
            "consecutive_partition_fusions",
            &(self
                .ctx
                .budget
                .consecutive_partition_fusions
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "consecutive_partition_rows",
            &(self
                .ctx
                .budget
                .consecutive_partition_rows
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "consecutive_partition_retries",
            &(self
                .ctx
                .budget
                .consecutive_partition_retries
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "partition_balanced_fusions",
            &(self
                .ctx
                .budget
                .partition_balanced_fusions
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "partition_balanced_rows",
            &(self
                .ctx
                .budget
                .partition_balanced_rows
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "partition_balanced_retries",
            &(self
                .ctx
                .budget
                .partition_balanced_retries
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "streaming_chain_fusions",
            &(self
                .ctx
                .budget
                .streaming_chain_fusions
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "streaming_chain_rows",
            &(self
                .ctx
                .budget
                .streaming_chain_rows
                .load(AtomicOrdering::Relaxed)),
        )?;
        map.serialize_entry(
            "streaming_chain_retries",
            &(self
                .ctx
                .budget
                .streaming_chain_retries
                .load(AtomicOrdering::Relaxed)),
        )?;
        #[cfg(feature = "experimental-shuffle-partition")]
        map.serialize_entry("shuffle_partition_decisions", &self.audit)?;
        map.end()
    }
}
impl Context {
    pub(crate) fn with_diagnostic_snapshot<R>(&self, run: impl FnOnce(&Snapshot<'_>) -> R) -> R {
        // Audit construction can acquire the process ledger. Use audit ->
        // pressure order consistently; never reserve while visiting either.
        #[cfg(feature = "experimental-shuffle-partition")]
        {
            self.with_decision_audit_snapshot(|audit| {
                self.workspace.with_process_usage(|process_memory| {
                    run(&Snapshot {
                        ctx: self,
                        process_memory,
                        audit,
                    })
                })
            })
        }
        #[cfg(not(feature = "experimental-shuffle-partition"))]
        {
            self.workspace.with_process_usage(|process_memory| {
                run(&Snapshot {
                    ctx: self,
                    process_memory,
                })
            })
        }
    }
    pub(crate) fn diagnostic_reservations(&self) -> (u64, u64, Option<(u64, u64)>) {
        (
            self.workspace.used(),
            self.workspace.peak(),
            self.workspace.process_reservations(),
        )
    }
}
#[cfg(any(test, feature = "resource-contract-tests"))]
pub(crate) fn legacy(ctx: &Context) -> serde_json::Value {
    let mut diagnostics = serde_json::json!({"temporary_bytes_written": ctx.budget.written.load(AtomicOrdering::Relaxed), "sort_runs": ctx.budget.sort_runs.load(AtomicOrdering::Relaxed), "merge_operations": ctx.budget.merge_operations.load(AtomicOrdering::Relaxed), "merge_inputs": ctx.budget.merge_inputs.load(AtomicOrdering::Relaxed),
            "temporary_bytes_read": ctx.budget.read.load(AtomicOrdering::Relaxed),
            "temporary_files_created": ctx.budget.files_created.load(AtomicOrdering::Relaxed),
            "temporary_cleanup_failures": ctx.budget.cleanup_failures.load(AtomicOrdering::Relaxed),
            "temporary_path_reserved_bytes": ctx.budget.path_bytes.load(AtomicOrdering::Relaxed),
            "peak_temporary_files": ctx.budget.peak_files.load(AtomicOrdering::Relaxed),
            "grouping_policy": ctx.grouping,
            "resident_sorts": ctx.budget.resident_sorts.load(AtomicOrdering::Relaxed),
            "sort_calls": ctx.budget.sort_calls.load(AtomicOrdering::Relaxed),
            "sort_rows": ctx.budget.sort_rows.load(AtomicOrdering::Relaxed),
            "sort_seconds": ctx.budget.sort_nanoseconds.load(AtomicOrdering::Relaxed) as f64 / 1e9,
            "fisher_yates_calls": ctx.budget.fisher_yates_calls.load(AtomicOrdering::Relaxed),
            "fisher_yates_rows": ctx.budget.fisher_yates_rows.load(AtomicOrdering::Relaxed),
            "fisher_yates_seconds": ctx.budget.fisher_yates_nanoseconds.load(AtomicOrdering::Relaxed) as f64 / 1e9,
            "routed_groupings": ctx.budget.routed_groups.load(AtomicOrdering::Relaxed),
            "routing_fallbacks": ctx.budget.routing_fallbacks.load(AtomicOrdering::Relaxed),
            "routing_reused_runs": ctx.budget.routing_reused_runs.load(AtomicOrdering::Relaxed),
            "process_memory": ctx.workspace.process_usage(),
            "spill_format_candidate": cfg!(feature = "experimental-spill-blocks"),
            "compact_spill_files": ctx.budget.compact_spill_files.load(AtomicOrdering::Relaxed),
            "compact_spill_blocks": ctx.budget.compact_spill_blocks.load(AtomicOrdering::Relaxed),
            "compact_spill_rows": ctx.budget.compact_spill_rows.load(AtomicOrdering::Relaxed),
            "compact_spill_source_bytes": ctx.budget.compact_spill_source_bytes.load(AtomicOrdering::Relaxed),
            "compact_spill_stored_bytes": ctx.budget.compact_spill_stored_bytes.load(AtomicOrdering::Relaxed),
            "compact_spill_fallbacks": ctx.budget.compact_spill_fallbacks.load(AtomicOrdering::Relaxed),
            "shuffle_partition_fusions": ctx.budget.shuffle_partition_fusions.load(AtomicOrdering::Relaxed),
            "shuffle_partition_rows": ctx.budget.shuffle_partition_rows.load(AtomicOrdering::Relaxed),
            "shuffle_partition_retries": ctx.budget.shuffle_partition_retries.load(AtomicOrdering::Relaxed),
            "workspace_reserved_bytes": ctx.workspace.used(),
            "peak_workspace_reserved_bytes": ctx.workspace.peak()});
    diagnostics["directory_path_reserved_bytes"] =
        serde_json::json!(ctx.directory_reserved_bytes());
    diagnostics["consecutive_partition_fusions"] = serde_json::json!(ctx
        .budget
        .consecutive_partition_fusions
        .load(AtomicOrdering::Relaxed));
    diagnostics["consecutive_partition_rows"] = serde_json::json!(ctx
        .budget
        .consecutive_partition_rows
        .load(AtomicOrdering::Relaxed));
    diagnostics["consecutive_partition_retries"] = serde_json::json!(ctx
        .budget
        .consecutive_partition_retries
        .load(AtomicOrdering::Relaxed));
    diagnostics["partition_balanced_fusions"] = serde_json::json!(ctx
        .budget
        .partition_balanced_fusions
        .load(AtomicOrdering::Relaxed));
    diagnostics["partition_balanced_rows"] = serde_json::json!(ctx
        .budget
        .partition_balanced_rows
        .load(AtomicOrdering::Relaxed));
    diagnostics["partition_balanced_retries"] = serde_json::json!(ctx
        .budget
        .partition_balanced_retries
        .load(AtomicOrdering::Relaxed));
    diagnostics["streaming_chain_fusions"] = serde_json::json!(ctx
        .budget
        .streaming_chain_fusions
        .load(AtomicOrdering::Relaxed));
    diagnostics["streaming_chain_rows"] = serde_json::json!(ctx
        .budget
        .streaming_chain_rows
        .load(AtomicOrdering::Relaxed));
    diagnostics["streaming_chain_retries"] = serde_json::json!(ctx
        .budget
        .streaming_chain_retries
        .load(AtomicOrdering::Relaxed));
    #[cfg(feature = "experimental-shuffle-partition")]
    {
        diagnostics["shuffle_partition_decisions"] = ctx.decision_audit_diagnostics();
    }
    diagnostics
}
