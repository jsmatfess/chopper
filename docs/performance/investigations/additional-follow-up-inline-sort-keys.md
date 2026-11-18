## Additional follow-up: inline sort keys

2026-10-13. Implemented the next contract-preserving experiment on top of the
parser/merge working tree described below. Retained 16-byte keys now live inside the packed
row descriptor. Uniform-shuffle ingestion constructs them without a separate
key allocation. Comparisons use big-endian 128-bit integers, preserving the
existing lexicographic byte order; equal keys still use the exact existing
collision refinement. Other key lengths use boxed byte slices. Reservations
include the actual descriptor size and retained heap storage on each target.

The public `Row` type, spool format, random-key generation, seeded permutation,
logical digests, quotas and output bytes are unchanged. Converting a retained
row back to the public type still allocates its 16-byte key. This is not an
end-to-end removal of key allocations. Physical diagnostics can change as more
rows fit in a native sort buffer. No requirement-relaxing alternative was added.

### Measured scope and tradeoffs

Five alternating A/B repetitions on warm local storage, one worker. The baseline
was rebuilt from the existing working tree before these edits. The larger cases
contain 300,000 rows; the two narrow cases contain only an ID column. The resident
case uses a 256 MiB budget; external cases use 32 MiB. Timings cover complete CLI
jobs. Every run verified output bytes/order, names, row/byte counts, lineage,
stage metadata and logical digests against the baseline.

| Workload | Before seconds | After seconds | Speedup |
| --- | ---: | ---: | ---: |
| Resident uniform shuffle, 300,000 narrow rows | 0.242 | 0.180 | 1.35× |
| External uniform shuffle, 300,000 narrow rows | 0.181 | 0.163 | 1.11× |
| External uniform shuffle, 33 columns and one rare wide row | 1.020 | 0.997 | 1.02× |

The resident case used about 26% less elapsed time, with median CPU time falling
from 0.22 to 0.16 seconds and median peak RSS from 43.7 to 34.5 MiB. Its elapsed
ranges were 0.231–0.267 seconds before and 0.156–0.197 after. External narrow
shuffle used about 10% less elapsed time, with ranges of 0.178–0.190 before and
0.162–0.165 after; initial runs fell from seven to six. Temporary bytes written
did not change in any of these three cases.

The broader 15-case suite mostly moved by small amounts: ratios ranged from
0.96× to 1.02×, including a roughly 4% slower skewed partition median. These short
jobs do not support a general speedup claim. Boxed variable keys can require
shrinking an allocation, and inline descriptors have different size tradeoffs
on 32-bit WASM. Browser correctness was checked, but browser A/B speedups were
not measured. No cold-storage, large-scale, CPU-sampling or whole-job allocation
profile was collected. The results measure inline storage and fixed-width
comparison together, not their individual contributions.

Raw measurements, binary hashes and per-run diagnostics:
[large shuffle results](../../evidence-originals.md#sha256-15e914e34ac6a84fcca1f220a670f73e20f67b124bff38b63848b04665ca1fea "Original: docs/benchmarks/inline-keys-stress-2026-10-12.jsonl") and
[general results](../../evidence-originals.md#sha256-8e689423e6431b3d2c169267c6dd901a9d70629eef41f25e57590e449d73ec3a "Original: docs/benchmarks/inline-keys-native-2026-10-12.jsonl").
Reproduce with:

```sh
python3 scripts/benchmark-hot-paths.py --before OLD --after NEW --repeats 5 \
  --rows 300000 --cases shuffle_resident shuffle_narrow merge_rare_wide
python3 scripts/benchmark-adaptive.py --before OLD --after NEW --repeats 5
```

### Validation and remaining opportunities

All 68 native tests, workspace Clippy with warnings denied, Rust formatting,
the hosted UI build and all 17 Chromium browser contracts pass. New regressions
check byte-identical spool serialization for key lengths around the inline
boundary, packed and wide fields, and forced collisions through resident and
multi-level external sorting. Existing contracts cover cross-budget seeded
order, fused pipelines, strict byte caps, cancellation and publication. Browser
test artifacts were removed from the hosted build after verification.

The next contract-preserving experiment is radix sorting for large uniform
shuffle buffers, with auxiliary storage explicitly reserved and the same
collision refinement retained. Compact records through final consumers could
remove the remaining unpack/repack costs but require broader interface changes.
Spill compression remains lower priority until measurements identify storage
traffic as the bottleneck. Any probabilistic allocation, weaker mixing guarantee
or reduced CSV validation would change the data contract and needs a separate
decision before implementation.
