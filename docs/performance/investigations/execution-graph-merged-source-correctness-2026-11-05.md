## Execution graph merged-source correctness (2026-11-05)

**Result: the merged engine passes the recorded developer correctness checks.**
The [structured receipt](../../evidence-originals.md#sha256-c1bd573196f9b3cc545246f760b9609606dc4485ec39b9f3984fec29bc19f055)
pins 35 individual check/build/packaging records from five fresh runner batches,
with explicit status, exit code, command, input-set identity, original status
location and log hashes. Their engine/UI source matches merge commit
`db1ae5041fe3a675391037b366c0d1b4b6777e56`, with parents
`488525ef0c6465f994b39247c8237ff70c8eb3ca` and
`80894c6f0ba13ce1fa940e87002a97450b0dff06`. These are individual commands,
not a sum of test cases or performance observations.

The Linux/WSL native batch passes formatting, default and all-feature Clippy and
workspace tests, UI tests/build and the portable-core WASM compile. Hosted checks
execute in bundled Chromium 156.0.8078.4: graph strategy/codec/membership parity,
lifecycle, inspection, bounds, composed interruption, browser contracts, bridge,
cleanup and worker/process termination modes all pass. Base and experimental
shuffle-partition resource-contract variants pass. Their test reactors are
retained separately. The final default engine/hosted build passes the production
export guard and contains no test assets or resource-test entry point.
Compilation and packaging records remain distinct from executed browser checks.

Coverage metadata declares intent; the harness assertions and full logs determine
what was verified. The first hosted plan omitted `graph-codec-fixtures.py` from
its declared inputs. The committed source and a supplemental during-run snapshot
pin that helper; the supplemental files were rechecked unchanged after the runs.
This is not a retroactive launch-time runner identity. Later resource/restore
plans explicitly include the helper. This limitation remains in the receipt.

The full read-only evidence suite and execution-graph analysis/extension,
CI-routing, local-CI and validation-runner controls passed in a separate retained
19-command batch. Subsequent evidence registration is checked again against the
final files. These tooling checks supply no engine speed result. The initial
adapter red controls reported two failures and one error as expected; their
standalone disk log was not captured, and that missing log remains unknown.
The subsequent 22 adapter controls pass with durable runner logs.

This is developer validation on Linux/WSL and bundled Chromium. Native Windows,
macOS and installed Chrome/Edge checks were not run. It is not a local-CI delivery
receipt; no origin push or main delivery occurred. The changed production WASM
hash differs from the [earlier accepted build](../../evidence-originals.md#sha256-0accc096510b5e7767bffed9ec557fb6d4614b6ee0e4e171f1dab8ece0631830).
Its performance remains unmeasured: the earlier 126-job result and all earlier
unmet/failed attempts retain their [original scope](execution-graph-evidence-conformance-and-merge-scope-2026-11-05.md).
