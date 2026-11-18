## WASI group denial and cleanup publication contracts (2026-10-21)

The [new contract pass](../../evidence-originals.md#sha256-eb5f310d1e5d625c346ac3427f04999e71cbd99cc1f29feae5c437cf6312812c "Original: docs/benchmarks/wasi-group-cleanup-contracts-2026-10-21.json")
extends the separate test reactor below without changing production behavior.
The same decoded-group helper now runs in native unit tests and Chromium/WASI.
It retains the first real `Dataset::groups()` owner while a sibling reservation
leaves one byte less than the observed decoder transient demand. The second
record fails with typed shared admission; the ordinary iterator then stops.
Releasing the original held group permits an explicit fresh-reader retry of the
unchanged catalog. This is not the native parallel iterator's rewind mechanism.
The retried owner remains charged after its reader, dataset and context die,
and releases to zero only at final drop. Malformed typed JSON and cancellation
after a buffered record remain terminal.

On this wasm32 build, the 118-byte record retains 2,247 accounted bytes and its
decoder probe peaks at 5,181 accounted bytes. The separate pressure owner holds
4,121,141 bytes of ledger capacity; it does not allocate that amount of heap.
These target-specific observations calibrate a deterministic contract boundary,
not a production selector, allocator census or RSS limit. Native pointer sizes
and map allowances differ; no cross-target numeric threshold follows.

A second shared helper prepares a tiny job, renames a three-byte temporary file
and creates a directory at the old name. Dropping the file then receives an
actual WASI `path_unlink_file` rejection: `Is a directory (os error 31)`. The
filesystem adapter performs that pathname/type check while fixture data reside
in OPFS. This is not an injected string error, OPFS `removeEntry` failure or
physical-media fault. The test verifies the path-rich context error, retained
orphan bytes/path owner, failed `Prepared::execute`, absent published output and
removed staging. After the prepared job drops, three orphan bytes and 51 charged
path bytes remain; final context destruction removes the workspace and releases
capacity to zero. It does not exercise destination export or completion-marker
failure. The report retains the actual stderr diagnostic.

The initial reactor attempt stopped at the existing temporary-space headroom
check: its 16 MiB logical store was smaller than the default 64 MiB reserve.
Both tiny context fixtures now explicitly request an 8 MiB temporary budget;
production defaults and checks are unchanged. That failed attempt and cleanup
observations are preserved. The successful pass observes six OPFS files,
3,153 bytes peak logical workspace size, zero bytes before worker cleanup and
the workspace directory absent afterward. Contract duration and storage peaks
are not complete-job speedups or physical I/O measurements.

Windows default workspace tests pass (135 library tests); default and recorded
17-feature all-target Clippy and formatting pass. This pass does not rerun a
combined-feature library runtime suite. WSL Linux passes the two new helpers and
the combined adapter/group/cleanup entry test. Rebuilt default WASI passes 25
Chromium contracts and the bridge check, separately from the extended resource
contract. The test WASM hash is
`3a57740d1ffa1c5306389f473231c39f6acd470f5eb2a9e8e50eed950231b203`;
default WASM is
`e75a886a263584f6d7aa2f9e2e24d5c222583d5f509145c1c544c86663d208d9`.
The production guard rejects the actual test module, and final `build:hosted`
removes every test/benchmark asset while preserving the tested production module.

Controlled group-decode denial and pathname unlink/publication rejection are now
covered on the recorded WASI runtime. Late-parent fusion denial, rollback and
cleanup error at its retry boundary remain open, along with OPFS deletion/export
faults, cross-worker/tab coordination and the remaining allocation boundaries.
The cleanup fixture reports unsupported on unvalidated native targets; this pass
does not close macOS acceptance. No new benchmarks, defaults, broad platform,
scale, deployment or RSS-cap claims are introduced.
