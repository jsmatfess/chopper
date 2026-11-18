## Retained profile header and preview accounting (2026-10-16)

Profiling now keeps its existing header reservation after the scan, through the
cached `InputProfile` lifetime. Preview selection retains the existing eight-row
and 32 KiB content policy. An accepted preview reserves the outer descriptor
vector once and each copied field vector/string before materialization. The
ledger reconciles actual capacities before filling them. Copies reserve their
final descriptor/string capacities once, avoiding growth/shrink overlap; the
cached profile and all returned copies remain charged simultaneously.

`InputProfile::try_clone` replaces infallible `Clone` for profile copies. It
reserves header/preview capacity against the cached profile's workspace before
copying. Each returned profile owns independent reservations; clearing or
replacing the cache cannot release a caller's live copy. If copying fails,
partial allocations/charges are released and the cached entry remains available
for retry. Reservation fields are skipped during serialization, preserving the
profile JSON schema, headers, previews, observations and cache-hit behavior.

Three new tests cover just-below/at/above shared capacity, empty/multibyte fields,
several independently retained cached responses, cache clearing and destruction
order, partial-copy denial and successful retry. Existing parser capacity tests
now include preview capacity and assert release after the retained profile is
dropped. Existing malformed/oversized input and cancellation tests continue to
verify cleanup; preview-membership fixtures preserve the historical selection.
All 148 workspace tests, 66 combined experimental-feature library tests and 24
Chromium/WASI contracts pass. Formatting, Clippy with warnings denied and
native/WASI release builds pass. HTTP/Chromium checks use loopback access and
Chromium's staged libraries under
`/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu`.

This step accounts for header/preview rows, not all profile metadata. Selected
value trees/strings, cardinality sketches, combination indices/maps, cache-key
paths/options, stage/accuracy strings and serialization buffers remain outside
these reservations. Profiling uses its own half-budget workspace; independent
scan/preparation workspaces are not a shared process-wide cap. The broader
simultaneous-job, conversion, merge/routed payload, sorting/runtime and RSS
accounting work remains open. Physical SSD calibration and other-platform
validation remain outside this WSL pass.

Three alternating baseline/candidate repetitions on 100,000-row narrow,
33-field and late-wide fixtures verify 36 fresh profiles, 18 browser cache
replays and 36 complete jobs with identical profiles (excluding timing/hit
fields), output bytes/order, metadata and logical digests. One native worker
and 32 MiB configured memory are used; the late-wide record contains a 1.8 MB
UTF-8 field. Native CPU/process peak RSS and complete-job workspace/temporary
I/O diagnostics are recorded; browser CPU/allocations/RSS are unmeasured.

| Fixture | Native fresh-profile median seconds, before → after | Browser fresh-profile median seconds, before → after |
| --- | --- | --- |
| Narrow | 0.0270 → 0.0285 (+5.5%) | 0.0623 → 0.0625 (+0.3%) |
| Many columns | 0.1196 → 0.1193 (-0.3%) | 0.2765 → 0.2794 (+1.1%) |
| Late wide | 0.0336 → 0.0345 (+2.7%) | 0.0832 → 0.0841 (+1.1%) |

Browser cached-response medians remain around 10.7–11.1 ms, including adapter
round trips. Timing workloads ran sequentially after builds/tests. This is
accounting work with mixed small timing changes, not a throughput gain. Storage
is warm uncontrolled WSL/OPFS storage; physical I/O/cache conditions are not
measured. These controls do not close the device/scale acceptance matrix.

Artifacts: [fresh profiles, cache replays and complete-job controls](../../evidence-originals.md#sha256-cc963736ee49b5f517c06d3d2437aa6db1aa475db7f2fb3f76441c16afeb223c "Original: docs/benchmarks/profile-rows-engines-2026-10-16.jsonl"),
[Chromium contracts](../../evidence-originals.md#sha256-cd080e94d616b6348164145a50057b253a48e39f4a118d6bf648d33fa262e1a6 "Original: docs/benchmarks/profile-rows-browser-2026-10-16.json"),
[summary and build hashes](../../evidence-originals.md#sha256-a3489abcf7bdfec0322e2bfd9028261c2ed1be602a66f017163c5a7a3aec58b6 "Original: docs/benchmarks/profile-rows-summary-2026-10-16.json").

Reproduce after preserving baseline native/WASI binaries and building the
candidate native/WASI releases:

```sh
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-profiling-budget.mjs BEFORE BEFORE.wasm 100000 3
```
