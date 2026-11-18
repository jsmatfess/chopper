## Encoded CSV caps and publication after retained-parent retry (2026-10-21)

The [encoded-publication contract pass](../../evidence-originals.md#sha256-4627b901a8ca799caf198fcd9ac18c29a1cf8acb1683a8cb5dc4504d84f906f3 "Original: docs/benchmarks/retained-parent-encoded-publication-2026-10-21.json")
extends the shared retained-parent fixture through the real `PlanWriter`, immutable
CSV snapshot and `Prepared::execute`. It supplies an existing retained-dataset
boundary directly, so it does not establish injection coverage through public
preparation dispatch. The feature stays opt-in; no selector/default changes or
performance runs are added.

Two eight-row parents contain narrow then 320,000-byte keys, with quoted commas,
quotes, embedded newlines and Unicode payloads. A synthetic ledger owner leaves
128 KiB after the first parent's commit, forcing one typed late-parent denial;
release permits replay through the original shuffle and partition stages. Output
uses UTF-16LE, BOM, headers and CRLF. Published files and output manifest records
are compared exactly with the explicit serial-stage baseline; physical/job
diagnostic records are excluded from byte parity.

| Control | Recorded result on Windows, Linux and WASI |
| --- | --- |
| Retry then publish with a 1,280,124-byte strict cap | Five CSVs total: eight narrow rows, then four two-row wide chunks; 5,120,904 serialized bytes |
| Cap of 640,075 bytes | One byte below the 28-byte prefix plus 640,048-byte largest row; retry ends with the same cap rejection as serial execution, no destination |
| Retry then cancel on the first `Writing output` event | One private writing event; cancellation removes staging and leaves no destination |

Every successful CSV is independently read, checked against the byte cap and
UTF-16/BOM framing, and compared with baseline bytes/names/metadata. Row totals
remain sixteen. Windows/Linux/WASI match CSV BLAKE3
`65be09d71f218621b54075b2da1c372aabd498e6740cd493d58575aa3f083aea`
and output-record BLAKE3
`357b9098aff2e4059e730da7187bd9225a574a408b7ff74e4a409ff335ba9b4d`.
The raw record pins fixture/source/native/WASM identities and explicit parity
fields. Each mode retains its audit charge until final context drop, then has
zero reservations, temporary files and workspace/staging directories. Successful
and writing-cancelled modes each peak at 25,929,352 temporary bytes; cap rejection
peaks at 13,125,941. Separate peaks are not added and fixture-verification
allocations are not a memory census or RSS cap.

Windows default workspace tests pass (135 library), as do the recorded 17-feature
library pass (215 tests), default/combined all-target Clippy, formatting and 28 UI
tests/build. The focused shared publication test passes on Linux and all three
controls run in the candidate Chromium/WASI resource reactor. Hosted packaging
rejects the test reactor and removes all test assets; production WASM remains
`e75a886a263584f6d7aa2f9e2e24d5c222583d5f509145c1c544c86663d208d9`.
Default/base browser suites were not rerun in this pass.

Native results exercise atomic directory publication; WASI results exercise
internal directory finalization on real OPFS-backed storage. They do not exercise
the JavaScript destination copy or `CHOPPER-COMPLETE.json`, user-selected output
handles, export/deletion faults, cross-tab coordination or deployed hosting.
Those acceptance gaps and cost calibration remain in [TODO](../../../TODO.md).
