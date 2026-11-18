## Retained-parent retry and decoded output-catalog ownership (2026-10-20)

The first [stage/parent policy](../../adaptive-execution.md#evidence-based-stage-and-parent-policy-design-2026-10-20)
implementation slice applies to retained-dataset exact shuffle/partition behind
its existing feature gate. Each parent's admitted attempt owns resolved-column
capacity while constructing tentative sorted rows without touching the sink.
Typed memory admission denial before emission drops the attempt and replays that
parent through original shuffle and partition stages. Previously emitted parents
are not repeated. Errors after emission begins, cancellation and other failures
remain terminal. Leading raw ingestion has no new replay boundary. Diagnostics
now include `shuffle_partition_retries`; no cost threshold or default is promoted.

Separately, output chunk-catalog reads now reserve bounded JSON escape scratch,
array-growth overlap and a conservative decoded-tree allowance before owned
deserialization. Returned chunks retain actual string/vector capacity charges
and conservative BTreeMap-node allowances through reader destruction, peek,
batching and worker lifetimes. Borrowed output manifest records remove a lineage
tree clone while preserving prior serialized JSON bytes. These are working
allocation charges, not measured allocator layouts or an RSS cap. Dataset group
decoding, lineage construction/other clones, remaining publication/codecs/input
adapters and runtime overhead remain open. No throughput gain is claimed for
the extra JSON preflight traversal.

Eight focused experimental shuffle/partition tests pass on native Windows,
including later-parent late-wide denial with a retained charged owner, retry after
its release, cancellation at retry, persistent-owner clean failure, exact original
output parity, forced collisions/hierarchical merging and terminal sink denial
without replay. Injected charged-owner pressure is not an OS-pressure experiment;
cleanup-error injection and a calibrated selector remain open. Eight JSON-reader
and eight output-buffer tests cover predecode admission edges, shared-denial
rollback/retry, escaped/nested JSON, reader/peek/batch/thread ownership, malformed
input/cancellation, staged-publication denial cleanup/retry and byte-identical
manifest records. Test counts describe this build and overlap the workspace suite.

The default native workspace suite passes, including 121 library tests, with
normal parallel execution. Initial failures exposed unrelated fixture issues:
Linux absolute-path assumptions on Windows, plus independent tests competing
for the global process pool. Linux mount-resolution tests remain Linux-only;
hierarchy fixtures now use native PathBuf keys and non-Linux fallback has explicit
coverage. Focused host tests pass 4/4 on Windows and 4/4 on WSL Linux. Independent
algorithm/capacity fixtures now inject isolated pools with unchanged limits;
tests intentionally sharing capacity retain their shared owners. Formatting,
default and exact-shuffle/partition workspace Clippy with warnings denied, and
portable-core `wasm32-unknown-unknown` checks pass. An optional all-feature Clippy
attempt could not download uncached Parquet dependencies in the restricted
network environment; it is not reported as passing.

The Windows-built experimental WASI engine passes 25 real Chromium contracts and
the UTF-8 bridge error check; [raw contract evidence](../../evidence-originals.md#sha256-da95b0dce893bb8b9778da3ba1d25ff25698ad651d152f133e0660041cacbcab "Original: docs/benchmarks/stage-parent-browser-contracts-2026-10-20.json")
pins WASM/source/harness hashes, feature, revision/dirty context and command output.
The restored default WASI build independently passes the same 25 contracts and
bridge check; its [separate record](../../evidence-originals.md#sha256-7b5c67da395373b02791e8c4ab71ab5ba73809c4a1606e11032c885c25d6a97b "Original: docs/benchmarks/output-catalog-browser-contracts-2026-10-20.json")
also records Chromium 156.0.8078.4, executable hash and Node version. The final
hosted build uses default engine features and removes test assets.
The added retained-parent test compares four output CSVs after balanced(2),
uniform shuffle and country partition with the pinned feature-off native binary
from the Windows calibration. This checks a successful browser execution path;
it does not simulate browser admission denial, prove broad browser/device support
or establish an A/B speedup. Playwright uses a temporary context. UI tests (28)
and the hosted TypeScript/build check pass after sandbox parent-directory access
was granted; initial esbuild failures occurred before compilation.

The [TODO](../../../TODO.md) retains the broad policy/accounting/release items as open.
No complete capacity model, physical-I/O claim, cross-tab coordination or hosted
deployment acceptance follows from these tests.
