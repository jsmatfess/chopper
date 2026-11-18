## Radix-sort experiment, 2026-10-13

**Keep comparison sorting as the default.** The optional `experimental-radix`
Cargo feature in `chopper` (forwarded by `chopper-browser`) implements stable
byte-wise LSD sorting of indices for `SortOrder::Random` buffers with inline
16-byte keys and at least 16,384 rows. Equal-key ranges retain the existing
domain-specific `compare_ties` refinement, then an in-place permutation moves
the row descriptors. Key/group sorting and smaller buffers keep comparison
sorting. No job option or seeded algorithm version changes.

The candidate reserves two `usize` index arrays plus the 256-entry histogram
before allocating. Reservation or fallible allocation failure leaves rows
untouched and uses comparison sorting. At 300,000 rows this reserves 4,802,048
bytes on native x86-64; WASI uses 32-bit indices. Scratch is released before
spill/output work. This is additional algorithm workspace, not a process RSS cap.

### Native comparison

AMD Ryzen AI 9 HX 370, WSL Linux, warm uncontrolled local storage; 300,000 rows,
three alternating complete jobs per build/case/worker count. The baseline was
built from the existing workspace before the experiment. Reported runs did not
overlap compilation or other benchmarks; an initial overlapping probe was
discarded. Full output fingerprints include bytes/order, names, lineage, stage
metadata and logical digests. All 48 ordinary/profiled jobs matched.

| Fixture / workers | Comparison job median | Radix job median | Comparison sort median | Radix sort median |
| --- | ---: | ---: | ---: | ---: |
| Resident, 256 MiB / 1 | 0.1773 s | 0.2271 s | 0.0163 s | 0.0763 s |
| Resident, 256 MiB / 4 | 0.1625 s | 0.2346 s | 0.0064 s | 0.0769 s |
| 33 columns, 32 MiB / 1 | 1.0822 s | 1.0645 s | 0.0191 s | 0.0165 s |
| 33 columns, 32 MiB / 4 | 1.0789 s | 1.0694 s | 0.0190 s | 0.0164 s |
| Rare 1.8 MB field, 32 MiB / 1 | 1.0884 s | 1.0832 s | 0.0195 s | 0.0164 s |
| Rare 1.8 MB field, 32 MiB / 4 | 1.0775 s | 1.0751 s | 0.0193 s | 0.0172 s |

Resident whole-job time regressed 28%/44% for one/four workers. Its measured
one-worker range was 0.1730–0.1795 s before and 0.2271–0.2504 s after. Median
RSS rose from 35,508 to 39,648 KiB, and peak workspace reservation from
49,688,890 to 54,490,938 bytes. The smaller spill buffers save only a few
milliseconds of sort time; most complete-job ranges overlap. Runs, merges and
temporary traffic remain unchanged. The extra index passes, payload indirection
and permutation do not pay off for the large resident fixture.

Candidate CPU samples attribute 38 of 101 one-worker resident samples to
`Sorter::sort_buffer` (37.6%); the columns fixture attributes 6 of 478 (1.3%).
These are self samples with offline symbolization, not runtime allocation stacks.
The candidate allocation census records 1,800,298 allocations and 132,142,164
requested bytes for resident execution, and 21,001,016 allocations plus
1,200,306 reallocations for the columns fixture. Sorting does not remove the
field-conversion work. Profiled timings are excluded from the ordinary medians.

A 1.3-million-row rare-wide follow-up exercised 71 initial runs and two merges
with 72 total merge inputs. All 16 ordinary/profiled jobs matched. One-worker
complete-job medians were 5.8056 → 5.7845 s; four-worker medians were
5.8028 → 5.8024 s, with overlapping ranges in both cases. Both builds wrote
965,381,720 temporary bytes. This provides multi-level parity evidence, not a
meaningful full-job speedup.

### Browser/WASI comparison

The browser harness accepts an optional seventh argument naming baseline WASM.
It alternates the two modules, reloads the page between builds, records module
hashes and restores the candidate module afterward. Chromium, 100,000 generated
rows with zero payload bytes, three repetitions, OPFS test destination:

| Budget | Comparison job median (range) | Radix job median (range) | Sort median before → after |
| --- | ---: | ---: | ---: |
| 32 MiB | 0.5992 s (0.5428–0.6096) | 0.5692 s (0.5686–0.5783) | 0.0170 → 0.0098 s |
| 256 MiB | 0.2767 s (0.2683–0.2832) | 0.2689 s (0.2561–0.3049) | 0.0191 → 0.0156 s |

All 18 native/browser jobs matched output hashes, row counts, output CSV bytes
and logical digests. Browser whole-job ranges overlap; this is not evidence for
a universal speedup or for arbitrary physical export destinations.

Raw evidence: [native CPU/allocation/timing](../../evidence-originals.md#sha256-24ef02ed83858d397e8b6108b7ab9a650753749f3d9c3e3cb31c97528ae080de "Original: docs/benchmarks/radix-native-2026-10-13.jsonl"),
[browser A/B](../../evidence-originals.md#sha256-69a7da8245b3e0734d72f82d6612065870d4f331627b363ed73d27317335106f "Original: docs/benchmarks/radix-browser-2026-10-13.jsonl"),
[multi-level spill follow-up](../../evidence-originals.md#sha256-e1191efcb6cf1cf4ebe276c7d74df918ffd740d1bf30134c0e8256a21c3918a5 "Original: docs/benchmarks/radix-multilevel-2026-10-13.jsonl").
Cold/slow storage and constrained physical devices remain unmeasured. The next
active experiment is allocation-free intermediate balanced-split boundary scanning.

Validation: 79 native tests in both default and experimental builds and 21 Chromium
contracts passed, including existing caps, cancellation and publication tests.
New differential tests cover random keys, forced collisions, all-equal keys,
common prefixes, collision order across resident/spill budgets, permutation payload preservation, rejected sort/key types and
scratch-reservation failure. Formatting and workspace all-feature Clippy with
warnings denied passed.

Reproduction (save baseline native/WASM builds before enabling the feature):

```sh
cargo build --release --locked -p chopper --features experimental-radix --bin chopper --example allocation-profile
python3 scripts/capture-job-profiles.py --before /tmp/chopper-before-radix \
  --binary .tools/linux/target/release/chopper \
  --allocator .tools/linux/target/release/examples/allocation-profile \
  --artifacts /tmp/radix-profiles --rows 300000 --repeats 3
# Multi-level follow-up: --rows 1300000 --cases rare_wide, with a fresh artifacts directory.
bash scripts/build-browser.sh --features experimental-radix
node scripts/build-hosted.mjs
node scripts/benchmark-engines.mjs .tools/linux/target/release/chopper \
  100000 3 uniform32,uniform256 0 /tmp/chopper-before-radix.wasm
```
