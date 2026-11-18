## Parser, serialization, digest and merge improvements (2026-10-12)

2026-10-12. Implemented contract-preserving changes against the working tree that
existed at the start of this performance pass, including its uncommitted adaptive
execution and profiling changes:

- The CSV parser scans ordinary byte spans with `memchr`, retaining the scalar
  state machine for quotes, escapes, delimiters and record endings. A reusable
  `next_record_into` API reuses field allocations for profiling, plain streaming
  and initial spool writes. Retained sort/buffer rows still own their fields.
  Reused field capacity is bounded even when a wide value moves between columns.
- Output writers reuse serialization scratch and resolve encoding once. UTF-8
  writes directly from the text buffer; UTF-16 reuses the encoded buffer. Legacy
  encodings still use the strict encoder and may allocate per record.
- Logical digests batch the exact v1 field-count/length/payload stream into a
  bounded 16 KiB buffer, flushing before direct hashing of large fields and at EOF.
  Random-key hashing and seeded RNG consumption are unchanged.
- External merge heaps retain only keys, IDs and ordinals. Intermediate merges
  copy field payloads through one reusable scratch allocation while retaining
  field-count, cumulative-length, truncation and UTF-8 checks. Final consumers
  decode only the winning row. The spill format is unchanged. Fan-in reserves
  one largest decoded row plus each input's key, reader buffer and metadata,
  instead of reserving the largest payload independently for every input.
- Profile preview budgeting retains the original parser's capacity accounting,
  so storage reuse cannot change preview membership after a wide record.

No job schema, algorithm version, equality rule, seeded permutation, exact quota,
strict CSV/byte-limit behavior, confirmation step or publication guarantee changed.
Physical diagnostics (reservations, merge counts, temporary traffic and timings)
can change. At the end of this pass, end-to-end compact retained records, inline/radix shuffle sorting and
compressed spill blocks remained future experiments. Inline keys and explicit product
options were implemented in the subsequent passes recorded above.

### Validation and measurement scope

Native workspace tests and Clippy pass. Added regression coverage includes reused
CSV buffers, exact working limits, UTF encodings/custom escapes, capacity growth,
logical digest boundaries, composite merge runs, corrupt spool payloads, wide-row
workspace use and profile preview parity. Existing tests cover forced random-key
collisions across merge levels, cross-budget ordering, exact allocations, strict
serialized byte caps, cancellation and atomic publication.

A temporary differential harness compared 1,176,480 small-input parser cases
against the original source, varying malformed input, UTF-8, escapes, blank-line
handling, read-buffer boundaries and working limits; all matched, including error
messages and record counters. In an isolated parse/serialize allocation counter,
10,000 rows of 32 short fields required 400,002 allocation/reallocation calls
before versus 45 with reusable buffers. This is an isolated hot-loop count, not a
whole-job allocation profile or an RSS prediction.

Native A/B measurements alternate builds on warm local storage, with one worker.
The general suite uses five repetitions; the 300,000-row, 33-column stress suite
uses three and records GNU time CPU/peak RSS. Fingerprints include output bytes
and order, names, row/byte counts, lineage, stage metadata and logical digests.
Profile comparisons exclude only timing/cache-hit fields. Binary hashes and
individual measurements are recorded in
[general results](../../evidence-originals.md#sha256-e1adb237ab9371dde20a465faa6bbac45e1eed5852929109944310e60039ce81 "Original: docs/benchmarks/hot-paths-native-2026-10-12.jsonl") and
[stress results](../../evidence-originals.md#sha256-cfe68d0d7b2d4e60ad4aab7a35109b554b707dfc4172f2d5489fdf601daf9980 "Original: docs/benchmarks/hot-paths-stress-2026-10-12.jsonl").

Reproduce with `scripts/benchmark-adaptive.py --before OLD --after NEW --repeats 5`
and `scripts/benchmark-hot-paths.py --before OLD --after NEW --repeats 3`.
These experiments do not establish cold-storage performance, billion-row scaling,
or a universal speedup. No whole-process allocation/CPU sampling profile or
physical disk-read counter was collected.

### Native results

Elapsed-time medians in seconds; speedup is baseline/candidate. Fixtures include
quoted/multiline text and Unicode in the general suite. General cases range from
10,000 to 120,000 rows; stress cases use 300,000 rows and 33 columns.

| Workload | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| Plain streaming, narrow rows | 0.032 | 0.020 | 1.58× |
| Resident uniform shuffle | 0.016 | 0.014 | 1.09× |
| Uniform shuffle, many columns | 0.249 | 0.213 | 1.17× |
| Uniform shuffle, wide rows | 0.284 | 0.154 | 1.85× |
| Partition, few keys | 0.144 | 0.094 | 1.54× |
| Partition, skewed keys | 0.141 | 0.091 | 1.55× |
| Partition, many keys | 0.503 | 0.455 | 1.11× |
| Partition, late new keys | 0.469 | 0.421 | 1.11× |
| Exact allocation | 0.176 | 0.119 | 1.47× |
| Partition then allocation | 0.230 | 0.178 | 1.30× |
| Stratified allocation | 0.251 | 0.196 | 1.29× |
| Buffer shuffle, narrow rows | 0.044 | 0.036 | 1.25× |
| Buffer shuffle, many columns | 0.169 | 0.133 | 1.27× |
| Buffer shuffle, wide rows | 0.270 | 0.116 | 2.32× |
| Buffer shuffle then allocation | 0.193 | 0.140 | 1.38× |
| Streaming, 33 columns (stress) | 0.641 | 0.312 | 2.06× |
| Full-file profiling, 33 columns (stress) | 0.452 | 0.293 | 1.54× |
| Uniform shuffle, rare wide row (stress) | 1.957 | 1.031 | 1.90× |

The rare-wide-row fixture has one 1,800,000-byte field among otherwise short
records. At a 32 MiB job budget, both builds produced 18 sort runs, but merge
operations fell from 9 to 1. Temporary bytes written fell from 343,055,788 to
129,678,010 (62% less). Median CPU time fell from 1.93 to 1.00 seconds. Median peak
RSS was approximately 15.8 versus 16.1 MiB: this experiment demonstrates less work
and temporary traffic, not lower whole-process peak RSS. Streaming and profiling
CPU medians fell from 0.61 to 0.29 seconds and 0.43 to 0.28 seconds, respectively.

Stress elapsed ranges (before / after, seconds):

- Streaming, 33 columns (stress): 0.632–0.650 / 0.305–0.316.
- Full-file profiling, 33 columns (stress): 0.445–0.471 / 0.292–0.304.
- Uniform shuffle, rare wide row (stress): 1.944–1.972 / 1.016–1.039.

Short general-suite jobs are particularly sensitive to startup and filesystem noise.

### Browser verification

The final WASM engine passes all 17 Chromium browser contracts. A separate
100,000-row fixture with 64-byte payloads ran plain streaming, external uniform
shuffle, buffer shuffle and gzip output three times each in both native and
browser engines. Every output fingerprint matched across engines. Measurements
are in [browser results](../../evidence-originals.md#sha256-7fbfc21eaa75b137c4050d1aae0f98576e07b20796aec64061263a83fc48244f "Original: docs/benchmarks/hot-paths-browser-2026-10-12.jsonl").

| Browser workload | Median complete-job seconds |
| --- | ---: |
| rows | 0.356 |
| uniform32 | 0.966 |
| buffer | 0.408 |
| gzip | 1.075 |

These are final-build browser timings and parity checks, not browser A/B speedups.
The harness includes worker startup and export cleanup but excludes fixture
preparation and output hashing. Native measurements do not predict browser gains.
The test host needed Chromium runtime libraries extracted under `/tmp`; no system
packages were changed. Test harnesses were removed from the hosted build afterward.

WASM SHA-256: `0ebc69625dc67eedd98c18be486505493a935817f15bb7fc3102bad741505868`.
