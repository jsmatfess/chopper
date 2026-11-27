# Guided CLI slice A validation handoff

## Delivered slice A

PR [#128](../history/prior-issues.md#issue-128) delivered slice A at
`9a2db1a0438dd82ad549fe7235e893215a67e7b2`. Exact Linux `a9iibucl` and native
Windows `g_7mduax` local gates passed against `41dc4ae`. A default native Windows
build passed ten focused controls and 24 actual Win32-console journeys, including
repeat counts, Unicode pairs/deletion, byte bounds, cancellation, invalid-reload
retention, capped Run verification and the printed PowerShell command. Binary
SHA-256: `d3a8c03bccdb3d961ae66aa28f4a99aefc336980a7c64619a7a3fa2ef538e0bb`.
The retained native evidence is in `C:\cqual-131-128-20261106`; the earlier
`75395cd` fault-build profile/Run barrier evidence remains separately scoped.
This is slice A acceptance, not #88 completion or selected606 release acceptance.
The commands below describe reproduction and future changed-source validation.


[#106](../history/prior-issues.md#issue-106) originally authorized slice A outside
the historical focused release. The current [0.2 scope](../releases/0.2.0.md)
includes the delivered Guide. The [guided specification](guided-cli-specification.md)
owns behavior; fresh release-source gates remain separate from the historical
acceptance above. This document is a test entry point, not another active
checklist or a coverage waiver.

## Linux controls

Run from the repository root under the existing
[host validation lock](../ci.md#local-development-and-transitional-delivery-gate), with bounded Cargo jobs.
Build the ordinary binary and retain a copy before building the fault binary:

```sh
cargo build --locked -p chopper-csv --bin chopper -j 2
# Copy target/debug/chopper to a fresh owned artifact directory as chopper-default.
cargo build --locked -p chopper-csv --bin chopper -j 2 --features resource-contract-tests
python3 scripts/test-guide.py --binary scratch/OWNED/chopper-default \
  --fault-binary target/debug/chopper --artifacts scratch/OWNED/new-pty-attempt
```

The harness opens actual Linux PTYs for stdin/stderr and redirects stdout to
separate files. It uses tiny quoted/multiline CSVs, independently parses CSV and
manifest records, and retains raw terminal/stdout/stderr logs. A failed attempt
stays intact. It verifies the save/reload/default-No/Run journey, literal Unicode
and apostrophe paths, copied shell quoting, skip-inspection/save-only, EOF and idle
SIGINT, late malformed records, strict header/record caps, invalid resources,
nonempty and late-created destinations, save replacement failure, line/Job bounds,
escaped/truncated source text, and committed output after stdout failure.

Only `resource-contract-tests` builds include the two one-shot row checkpoints.
`CHOPPER_GUIDE_TEST_PHASE=profile-row` or `direct-row` and
`CHOPPER_GUIDE_TEST_RELEASE=PATH` select a parent-owned barrier. The Linux harness
uses a FIFO, waits for the actual checkpoint, sends SIGINT, waits for the handler's
acknowledgement, then releases it and waits for process exit. No timing sleeps,
large fixtures or production fault API are involved. The direct-row checkpoint
is after header/output-owner construction and before the first output row;
profile-row is inside the full scan. The late-destination case introduces an
unrelated file at that same direct checkpoint and verifies its preservation.
Ordinary builds ignore these variables. Existing engine/resource tests cover
publication and cleanup-failure contracts separately; a PTY pass does not replace
them. Restore an ordinary build before handing off a runnable production binary.

Focused injected-I/O transcripts live in `guide.rs`; run them with
`cargo test --locked -p chopper-csv --bin chopper guide::tests`. These establish prompt
and persistence controls, not actual-terminal coverage. Normal contributor
fmt/Clippy/workspace tests remain applicable.

## Native Windows parent entry

No Windows build, dispatcher, actual PTY journey or local CI gate was executed by
the implementation worker. Windows acceptance is pending, including console
input/cancellation, atomic replacement and PowerShell command quoting. WSL PTYs
are Linux coverage only. Follow the [two-checkout workflow](../windows-wsl-workflow.md)
and use the exact PR head in a clean native checkout; parent owns dispatch/gates.

The portable part of the binary harness can run on Windows:

```powershell
python scripts/test-guide.py --binary target\debug\chopper.exe --artifacts scratch\guide-native-gate
```

On Windows this deliberately records only the actual non-TTY rejection and marks
all PTY journeys pending. It does not simulate `is_terminal`. To gather actual
terminal evidence, use an installed native terminal/ConPTY, keep stdin/stderr
attached, and redirect only stdout:

```powershell
& .\target\debug\chopper.exe guide 1> scratch\guide-analysis.json
```

Use a tiny UTF-8 source with the records `id,text`, `1,"a,b"`, a quoted multiline
second record, and `3,"say ""yes"""`. Configure row cap 2 and byte cap 64. In the
numbered journey accept input, inspect the full scan, Back/Edit the caps, choose an
output path with spaces and Unicode, save to a config path containing an
apostrophe, reload, decline Run with Enter, then confirm explicitly. Capture the
terminal transcript and exact source/binary/Job hashes. Repeat with inspection
skipped and with save-and-exit. Saved seeds must match Analysis and manifest.

Run the printed PowerShell command against a copy of the saved Job with a new
output path. Its single-quoted config argument doubles embedded apostrophes.
Independently verify each completed output with the portable verifier:

```powershell
python scripts/test-guide.py --verify-source scratch\source.csv --verify-output 'scratch\guided output 雪'
```

The verifier asserts exact decoded records/order, two data rows per CSV, at most
64 actual bytes per CSV, and matching manifest counts/bytes. Native console controls must also send coalesced `KEY_EVENT_RECORD` events with
`wRepeatCount > 1`: printable characters, Backspace, matching UTF-16 surrogate
pairs and repeated input crossing the encoded 64 KiB response bound. Native
console EOF,
idle/profile/Run Ctrl+C, default-No overwrite/discard, bounds and error/cleanup
journeys require actual native evidence for changed sources. Parent may adapt the deterministic
resource-contract barrier to a native named pipe; the Linux FIFO harness alone
makes no Windows barrier claim. Do not replace these missing journeys with a
fake terminal flag or mark #106/#88 complete from Linux evidence alone.
