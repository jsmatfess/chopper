## A single admitted key per routed group (2026-11-26)

[Issue #101](https://github.com/jsmatfess/chopper/issues/101) ·
[Projected Run samples](../../benchmarks/routed-group-key-owner-2026-11-26.jsonl) ·
[Measured patch](../../benchmarks/routed-group-key-owner-2026-11-26.patch)

Ordinary routed frames keep the source ID, ordinal, and packed fields. A key is
stored once with its existing bucket allocation. Closing a bucket transfers the
key and part of the admitted tree allowance to a shared immutable owner. The
routed reader and a merge head or returned packed row can retain the key after
the originating file closes. Explicit owned row conversion admits a key copy.
When a merge materializes a different run it writes the ordinary full frames.

### Complete hosted Runs

Persistent bundled Chromium on WSL2, one worker, explicit 256 MiB, Auto grouping,
plain CSV with a 4 MiB cap. All variants used the same renderer and worker assets,
and timed Run through verified export and workspace retirement. Three alternating
pairs followed one excluded warmup per arm and cell. Verify every field and ID,
canonical group and encounter order, original lineage, exact encoded files and
sizes, strict caps, the marker and cleanup.

| Fixture | Baseline median [min–max], s | Candidate median [min–max], s | Paired seconds saved [min–max] | Temporary writes, bytes |
| --- | ---: | ---: | ---: | ---: |
| 640,003 rows, eight 96-byte keys | 3.331 [3.319–3.409] | 2.926 [2.889–2.934] | 0.430 [0.405–0.475] | 292,265,365 → 224,425,047 |
| 640,003 rows, eight one-byte keys | 1.851 [1.777–1.872] | 1.704 [1.700–1.722] | 0.129 [0.077–0.168] | 130,340,998 → 123,300,965 |
| 580,003 rows, late new keys | 3.299 [3.187–3.408] | 3.361 [3.057–3.383] | 0.047 [−0.196–0.241] | 199,904,208 → 166,266,760 |

The repeated 96-byte keys save 67,840,318 bytes each from tracked reads,
writes, and peak temporary storage. The handoff retains 64 already ordered
bucket files as one merge input and saves 33,637,448 bytes of tracked writes
with mixed elapsed results. Peak working reservations are identical at the
observed resolution. These counters measure managed temporary files and the
working ledger.

### Contracts and reproduction

The resource tests exercise owned key copy admission, shared key lifetime after
a merge file closes, truncation and cancellation. The experimental compact
spill codec still uses its complete key-bearing frame. It was outside the timing
screen. The adoption covers ordinary routes, including a late transfer from
routing into the existing sorter and merge.

The feature-free Wasm baseline is the measured #104 candidate in
[the calculated Partition investigation](observed-hosted-calculated-columns-followed-by-partition-2026-11-26.md).
Apply the linked routed-frame patch and rebuild with the same Rust 1.99.1
toolchain. The per-Run projection pins the builder artifacts and exact fixtures.
The full browser capture and verification inputs are retained locally.
