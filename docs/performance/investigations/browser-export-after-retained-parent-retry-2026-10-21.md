## Browser export after retained-parent retry (2026-10-21)

The [browser-export contract pass](../../evidence-originals.md#sha256-79d7ffd615a9ec7e2729704ffed806f166d3a7ce26c70e7924258a22f0ff7454 "Original: docs/benchmarks/retained-parent-browser-export-2026-10-21.json")
extends verified retained-parent retry output through the production JavaScript
copy/marker path. That path now lives in `ui/src/browser/export.ts`, shared by the
production worker and the separate resource worker. No production fault-injection
hook or new WASM export is introduced. The test-only WASI helper transfers its
verified published result to `/results`; the resource worker owns those files
until export checks finish, then explicitly unlinks them.

In Chromium 156.0.8078.4, a separate same-origin OPFS directory receives the
manifest and five UTF-16 CSVs (5,120,904 CSV bytes, each below the 1,280,124-byte
cap). Every exported file matches the retained source in bounded chunks. The
source CSV/output-record BLAKE3 identities remain those in the preceding
encoded-publication pass. Per-file SHA-256 values identify this browser output;
the manifest hash contains path/diagnostic details and is not cross-runtime
parity. The completion marker reports six files and is opened only after all
six result writers close; the resulting folder contains seven entries.

The second export uses real OPFS handles wrapped only in the test worker. The
first chunk of a large CSV reaches the real writable; its second write throws
an injected `QuotaExceededError`. The error propagates, the writable aborts once,
two earlier result files have already closed, the partial directory remains, and
no completion marker is opened or present. This checks failure semantics, not
actual quota exhaustion. Test destinations and retained source files are removed
in `finally`; parent cleanup also removes its isolated destination container.
Storage cleanup sees zero remaining workspace bytes and verifies workspace and
export-container absence. Bridge metrics exclude the separate unprofiled
destination and do not measure a simultaneous combined storage peak.

The default 25-browser suite, base resource reactor, candidate resource/export
reactor and bridge check pass. Base mode has no candidate/export report. Windows
passes 215 recorded combined-feature library tests and its 135 default library
tests, but the default workspace run stops at `tests/flexible.rs`: Application
Control rejects its executable before execution (OS4551), both in the sandbox
and on the ordinary approved attempt. Both logs and the blocked binary hash are
retained; no executable/policy workaround was used. The full default Linux
workspace suite passes. Both Windows Clippy modes, formatting and 28 UI
tests/build pass. These results do not close the Windows integration-launch gap.

Named candidate/base/production WASM and worker hashes are recorded alongside
source identities and transcripts. After validation, hosted packaging removes
all test assets, rejects test reactors and accepts the default production engine
with unchanged WASM hash
`e75a886a263584f6d7aa2f9e2e24d5c222583d5f509145c1c544c86663d208d9`.
A prematurely run packaging check failed while test assets were still present;
the record retains that attempt separately from the successful final check.

This uses a temporary Playwright context and same-origin OPFS destination, not a
user-selected filesystem/device or deployed site. It adds no throughput, RSS,
physical-I/O, real quota/deletion fault, worker-termination, cross-tab, public
preparation-entry injection or macOS claim. Broader acceptance and cost selection
remain in [TODO](../../../TODO.md).
