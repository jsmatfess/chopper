## Job manifest tree construction admission (2026-10-21)

The next publication gap was the `json!` job record: it constructs a separate tree
containing configuration, analysis, headers/previews, diagnostics and nested
metadata before writing the manifest. The new
[`ManifestTree`](../../../crates/chopper/src/output/job_manifest.rs) admits that whole
tree before construction and retains its grant through serialization and final
drop. It still builds the same `serde_json::Value` representation, preserving
canonical sorted keys and exact job-record bytes. No pipeline, replay identity,
codec, resource ceiling or experimental default changes. This is resource
correctness work, not a throughput experiment.

An [allocation-free serializer preflight](../../../crates/chopper/src/output/job_manifest/estimate.rs)
walks the borrowed current `JobRecord` schema without collecting an intermediate
JSON value or text buffer. It counts owned string/key bytes, fixed char-string
capacity, sequence descriptors with old/new growth allowance, and the same
conservative map-node allowance used by decoded catalogs. Checked arithmetic
rejects overflow before admission. It supports the current borrowed-derived
job/analysis serialization forms. Display-based custom serialization, data-bearing
externally tagged enums and non-string map keys are rejected before construction;
these are not used by the current schema. Adding custom/allocating serialization
or changing the JSON map/number representation requires an envelope re-audit.
Source configuration/analysis ownership and serializer/runtime scratch remain
separate boundaries. The preflight assumes immutable, repeatable current schema
serialization; it is not an admission API for arbitrary stateful `Serialize` code.

After the preflight, local/shared admission precedes `serde_json::to_value`.
The constructed tree's independent capacity traversal must fit its allowance;
the retained grant is reconciled and stored after the value so destruction order
preserves ownership. Construction failure drops any partial tree before the grant.
The manifest writer's buffer remains independently charged. A conservative
envelope can reject a job that previously built this tree without accounting;
failure still removes staging and publishes no destination. No RSS cap follows.

The [shared contract](../../../crates/chopper/src/output/job_manifest/resource_contracts.rs)
checks exact old/new serialized job records for all operation variants, all four
compression modes and seeded/flexible policy fields, plus Unicode, character
settings, optional fields, nested diagnostics, sets/maps, previews and execution
metadata. It covers local/shared minus-one/exact/plus-one edges, competing-owner
release/retry, two independently returned trees surviving source drop and write
failure with grants still live. Additional controls verify that denial runs only
preflight, second-pass failure cleans a partial tree, and unsupported forms or
capacity overflow fail without retained reservations. A real prepared job checks
publication denial, staging cleanup, cancellation, retry and exact published
job-record bytes. Test fixture allocations are outside the working-owner claim.

The [validation transcript](../../evidence-originals.md#sha256-e3d78504813184da185a39770574bb417e8d817f7b57843e3f2094924e400766 "Original: docs/benchmarks/job-manifest-validation-2026-10-21.json")
retains dirty tracked/untracked source identities including vendor inputs,
harness/toolchain identities, individual WASI build hashes and per-command
outcomes. All 21 commands pass: formatting, the default Windows workspace (147
chopper library tests), candidate library (162), both all-target Clippy modes,
28 UI tests/build, native embedded rebuild, production WASI/hosted builds,
25 standard Chromium contracts, bridge/peer cleanup and both WASI resource
variants. Compilation-source inputs remain unchanged. Final hosted packaging
passes the production export guard and removes test assets. The existing ZIP
WASI unused-variable warning is preserved in the transcript.

The [cross-runtime comparison](../../evidence-originals.md#sha256-71c2a05e8d594a114d217b9401e261f2dec18e8662fc80fdef1a7bd0d13992fe "Original: docs/benchmarks/job-manifest-cross-runtime-2026-10-21.json")
matches all eight static fixture-manifest hashes, the richer execution-metadata
fixture hash and contract outcomes across Windows and both WASI builds. Source
artifact hashes and exact output pointers are retained. Per-run publication
controls verify canonical bytes against their own prepared analysis; they do not
claim that dynamic timing/path metadata matches across runs. Capacity envelopes
differ by representation. No Linux/macOS, persistent-browser, device-fault or
RSS claim is added. Command and contract durations are validation data, not speedups.
Remaining source metadata, response buffers, lineage/path/codecs/runtime ownership
and the other TODO acceptance/calibration/platform requirements remain open.
