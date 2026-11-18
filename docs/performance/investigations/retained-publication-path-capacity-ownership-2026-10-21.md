## Retained publication path capacity ownership (2026-10-21)

The next allocation decision was whether the manifest, archive and CSV publication
paths could retain their own working-capacity grants without changing path or
output semantics. `output/publication_path.rs` now validates a single filename
component, admits a checked encoded-byte capacity before reserving the `PathBuf`,
and reconciles its reported capacity. The path buffer drops before its grant.
CSV creation and metadata lookup share one path owner; the manifest owner spans
its later ZIP read, while the archive owner ends after file creation. Existing
atomic native publication and WASI internal-directory completion stay distinct.

The shared `publication-path-capacity-contract-v1` helper checks five Unicode and
separator shapes against `Path::join`, six local/shared capacity edges, held
competitor release/retry, two independent owners and eight invalid components.
Native Windows also checks drive, UNC and verbatim prefixes. File creation,
metadata lookup, early path drop with a live handle and failed creation preserve
the expected grant lifetimes. Public preparation/execute controls cover plain,
gzip, zstd and ZIP output: a held competitor denies manifest-path admission with
a typed shared error, staging is removed, cancellation publishes nothing, and a
fresh retry decodes to exact fixture CSV bytes. Every fixture ends with zero
reservations and removed directories. WASI runs this same helper over real OPFS;
Windows-prefix checks apply only to the native Windows build.

The [initial native validation](../../evidence-originals.md#sha256-f39db1061ed03b0e00de50e685b68744ebba4e83289e685affae4409e4e565fe "Original: docs/benchmarks/publication-path-validation-2026-10-21.json")
retains successful formatting and the printed native contract. Its recorder saved
the Unicode report before failing to print it to the terminal's cp1252 stream;
the [cross-runtime follow-up](../../evidence-originals.md#sha256-9118e8cd1edd003d8e2a64274b7dc458f25557a1a2a511faec15b02b9e671351 "Original: docs/benchmarks/publication-path-cross-runtime-2026-10-21.json")
uses UTF-8 stdout and records subsequent commands separately. Both records pin
dirty tracked and nonignored untracked compilation sources, including the ZIP
vendor patch, plus harness identities. Command durations are validation evidence,
not matched performance observations.

All 21 follow-up commands pass: workspace tests (148 native library tests), 163
candidate library tests, default/candidate Clippy, 28 UI tests/build, native
embedded rebuild, production WASI/hosted builds, 25 standard Chromium contracts,
bridge and peer cleanup, temporary/persistent production interruption/restart,
and base/candidate WASI resource contracts. The path reports are at
`/commands/17/output` and `/commands/19/output` in the follow-up, under
`resourceContracts.report.publication_paths`. Source identities remain unchanged
through the checks; WASM hashes are recorded per build. Final hosted packaging
contains no test assets. The existing vendored ZIP WASI `target_str` warning is
retained in build output and is unrelated to path ownership.

This closes retained joined publication buffers only. Destination absolute-path
discovery, opaque standard-library normalization scratch (including Windows
verbatim-path push internals), OS conversion, other temporary construction,
codec internals and native runtime/thread storage remain open. Extra path grants
can reject tight jobs that previously left these buffers uncharged. No defaults,
seeded replay identity, throughput claim or complete RSS cap changes.
