## Text snapshot and compact block prototype evaluation (2026-10-16)

A standalone, opt-in Python/PyArrow experiment compares decoded text snapshots
using bounded row-block framing, Arrow IPC/Feather V2 (uncompressed) and Parquet
(Snappy). **No production spill format, input format, cache or default changed.**
[Primary-source research and proposed cache contract](../../input-format-research.md)
records the source-identity/version/lifetime requirements and native/browser
integration constraints before any reuse could be enabled.

The u64 control stores each row's field count and each field's UTF-8 byte length
as u64. The compact prototype shares a field count per block and uses u32 field
lengths, with a version marker and block row/width/payload lengths. Both use
1,024-row blocks and a 16 MiB payload rejection limit. These are text snapshot
prototypes: they omit Chopper's per-row ID/ordinal/sort-key framing and do not
replace its actual internal spill reader/writer. Python construction checks the
payload limit after building a block; it is **not a strict allocation budget**.
IPC and Parquet use explicit text arrays without type inference. Feather V2 and
IPC file are the same format, so there is one IPC candidate.

The matrix contains **162 verified complete jobs**: 100,000 rows, three shapes
(four fields, 33 fields, and a late 900,000-byte Unicode value), shuffle followed
by four balanced files and partitioning into 17 groups, three alternating
repetitions. All output bytes/order, filenames, row counts, lineage, stages and
logical digests match direct CSV. Independent field-framed hashes also match
across each source/snapshot/decoded CSV, including empty strings, leading zeros,
`NULL`, date-looking text, escaped quotes, commas, Unicode and embedded newlines.

Snapshots currently reach the engine through an explicitly measured disk CSV
adapter. First jobs include CSV parsing, snapshot encoding, snapshot decoding,
CSV adaptation and the complete CLI job. Replays include a source SHA-256 check,
snapshot decoding, CSV adaptation and the complete CLI job. The initial source
identity hash is fixture setup outside first-job timing; a production writer
would need to compute it while reading or include another source pass. Replays
here model pre-existing **text-only Parquet** separately from CSV-to-Parquet first
jobs. They do not cover typed/null/nested existing Parquet schemas.

| Shuffle + balanced job | Narrow median (s) | 33-field median (s) | Rare-wide median (s) |
| --- | ---: | ---: | ---: |
| Direct CSV | 0.100 | 0.258 | 0.102 |
| u64 block first / replay | 0.321 / 0.240 | 1.401 / 1.015 | 0.326 / 0.247 |
| Compact block first / replay | 0.299 / 0.231 | 1.401 / 1.080 | 0.310 / 0.245 |
| IPC first / replay | 0.210 / 0.167 | 0.706 / 0.498 | 0.224 / 0.171 |
| Parquet first / replay | 0.238 / 0.191 | 0.977 / 0.609 | 0.243 / 0.192 |

| Snapshot bytes | Narrow | 33 fields | Rare-wide |
| --- | ---: | ---: | ---: |
| u64 blocks | 5,372,470 | 32,666,906 | 6,272,464 |
| Compact blocks | 2,972,446 | 18,666,766 | 3,872,440 |
| IPC (uncompressed) | 3,012,522 | 18,920,298 | 3,912,514 |
| Parquet (Snappy) | 644,870 | 1,621,693 | 687,107 |

Compact framing cuts control snapshot space by 43–45% on narrow/many-column
fixtures (38% with the wide outlier). IPC is close to the compact snapshot's
size. Parquet's dictionary/compression savings are large for these deliberately
repetitive values; they do not predict high-cardinality compression. Every
adapter replay and first job regresses versus direct CSV in this matrix.
**Do not enable a disk CSV bridge as a performance optimization.** These results
cannot determine whether an integrated bounded row-block or Arrow batch consumer
would win. They also do not justify compressing internal spills.

The normal pass records wall/CPU time, per-process peak RSS, Arrow pool peak,
snapshot/adapter sizes and existing engine workspace/temporary traffic. GNU time
filesystem counters include verification and child work; the warm WSL counters
were zero and cannot establish physical SSD I/O. GNU time RSS is a process/child
maximum, not the simultaneous sum of Python and CLI resident sets. Arrow pool
peaks exclude Python/native runtime allocations. A separate `--trace` pass
records Python traced peaks; its timings are perturbed and excluded above.
Source verification/output hashing is outside the internal job timer, except
for the replay source hash. Raw process CPU/RSS include correctness verification.

Artifacts: [ordinary timings and parity](../../evidence-originals.md#sha256-2a3413a0464e65073af941eb1771b7186805254b925e1398a8410863417000d6 "Original: docs/benchmarks/input-formats-2026-10-16.jsonl"),
[summary and ranges](../../evidence-originals.md#sha256-003d543af5b4625f878875e6cebb270264c0a2b9a0f68a15e5e0591a1138ed3f "Original: docs/benchmarks/input-formats-summary-2026-10-16.json"),
[54 separately instrumented allocation/parity jobs](../../evidence-originals.md#sha256-c1deba6365b3011e4795a62891d2b345f374b91b23443e0df3145a1a812ec285 "Original: docs/benchmarks/input-formats-allocations-2026-10-16.jsonl").
Python traced peaks range from 2.1–7.5 MB across snapshot adapters; Arrow pool
peaks reach 1.84 MB for IPC and 4.71 MB for Parquet on these fixtures. These
measure different allocation domains and must not be added to per-process RSS.
Direct CSV's Python wrapper peak is about 65 KB; the CLI is a separate child.
Reproduce with PyArrow installed in a separate environment:

```sh
python3 scripts/benchmark-input-formats.py --rows 100000 --repeats 3
python3 scripts/benchmark-input-formats.py --rows 100000 --repeats 1 --trace
```

The standalone block reader also passes [21 round-trip/adversarial checks](../../evidence-originals.md#sha256-461050cb251a5f0536e43b1d06395f03e8776f35dba6a3155a3d13bf4dcec5a1 "Original: docs/benchmarks/input-block-controls-2026-10-16.json"): version, truncated header/payload, invalid UTF-8, row/payload bounds, oversized fields, field-count mismatch and trailing bytes. Reproduce with `python3 scripts/validate-input-blocks.py`. These controls exercise only this Python prototype.

Remaining acceptance: actual internal-spill/full-row framing, integrated bounded
consumers, allocation counts including library internals, production strict budget and cap
failure/corruption/cancellation tests, native/WASI compilation/execution and
browser quota/transfer measurements. Existing typed Parquet input needs explicit
null/type formatting semantics. Cross-session caching and source-change races
need a complete publication/ownership policy. Controlled SSD cache/physical I/O
and other-platform checks remain outside this warm WSL prototype.
