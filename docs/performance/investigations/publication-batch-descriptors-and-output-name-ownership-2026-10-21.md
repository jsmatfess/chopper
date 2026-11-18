## Publication batch descriptors and output name ownership (2026-10-21)

This resource-correctness slice closes the publication batch/result descriptor
vectors and generated output-name strings identified in [TODO](../../../TODO.md#resource-correctness).
It changes no pipeline, replay version, codec choice, concurrency ceiling or
experimental default. No timed A/B experiment was warranted: the decision is
whether each live metadata allocation has admission and an owner, not whether
the accounting produces a throughput benefit.

Publication now uses one [admitted task vector](../../../crates/chopper/src/output/publication_metadata.rs)
whose slots hold the decoded chunk owner and optional completed result together.
Admission precedes allocation; reported vector capacity is reconciled. Native
workers fill those slots in place, avoiding the separate result `Vec` allocated
by the old parallel collector. WASI fills the same slots serially. Collection
drains the slots in original order while the vector and its grant remain live;
early worker/consumer failure drops the remaining decoded/result owners before
releasing descriptor capacity. An exhausted catalog allocates no empty batch.
Existing compression and ZIP temporary-space concurrency rules stay in force.

Each output name now has its own retained reservation inside `CompletedChunk`.
Construction admits 214 bytes for the bounded UTF-8 name and 32 bytes for a
reusable numeric-label string before allocation, reconciles actual capacities,
and releases label scratch before retaining the name. The 180-byte descriptive
prefix, sanitization, empty labels, header/index fallback, numeric suffix and
compression extension keep their existing formatting. Admission/retention also
cover worker errors before a result is returned. A conservative 246-byte
construction allowance can deny work that previously allocated without a charge.
Temporary joined paths, job-manifest JSON construction, other lineage clones,
codec/error/runtime payloads and native stacks/threads remain separate gaps;
these reservations do not bound RSS.

The [shared native/WASI contract](../../../crates/chopper/src/output/publication_metadata/resource_contracts.rs)
checks local/shared minus-one/exact/plus-one boundaries independently for names
and two-slot batches, competing-owner denial/release/retry, and simultaneous
batch owners. Naming controls cover four compression choices, Unicode, forbidden
characters, empty labels/lineage, index fallback, maximal u64 suffixes and wide
UTF-8 truncation. Actual task execution covers success, injected manifest-consumer
failure, one failed output-file creation, and cancellation. It checks ordered
collection, completed-name charges, retained drained-vector capacity, restoration
of the pre-batch ledger and final fixture/context cleanup. Test scaffolding and
error payload allocations are not part of that accounting claim. The separate
browser test reactor runs the same helper through OPFS; its report is required by
the browser resource page and remains excluded from production packaging.

The [validation transcript](../../evidence-originals.md#sha256-f1fb41cb2abc9ea92e316ff39d260206a327a9fa0ff291b77556a77b4e4561cf "Original: docs/benchmarks/publication-metadata-validation-2026-10-21.json")
pins the dirty tracked/untracked compilation inputs including vendor sources,
toolchain, per-command outcomes and development failures. All 21 recorded commands
pass: formatting, the default Windows workspace (145 chopper library tests),
candidate library (160), both all-target Clippy modes, 28 UI tests/build, native
embedded rebuild, production WASI/hosted builds, 25 standard Chromium contracts,
bridge/peer cleanup, and base/candidate WASI resource contracts. Compilation
inputs remain unchanged through the pass. Final hosted packaging passes its
production export guard and removes all test assets. The transcript retains a
nonfatal Windows incremental-cache finalization error 5 and the existing WASI
vendored ZIP unused-variable warning; no validation command failed in this pass.

The [derived cross-runtime comparison](../../evidence-originals.md#sha256-b265423682a007b86712ae1506c6678a288a275b053a8b0a18c578963be193ee "Original: docs/benchmarks/publication-metadata-cross-runtime-2026-10-21.json")
retains the validation artifact hash and exact output pointers. Windows and both
WASI variants match names and task outcomes, including all cleanup assertions.
One task descriptor occupies 216 bytes on native and 176 on WASI; these are
representation-specific capacity charges, not comparable RSS measurements.
No Linux/macOS or persistent/device-fault result is added here. Command/contract
durations are validation observations, not complete-job speedups. The remaining
TODO allocation, selector, platform and destination-fault work stays open.
