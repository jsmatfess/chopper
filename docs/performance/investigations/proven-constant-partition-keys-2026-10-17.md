## Proven-constant partition keys (2026-10-17)

The opt-in `experimental-constant-partition` feature proves a column constant
inside a parent only when an earlier logical value partition selected it.
Balanced/interleaved splits, assignment and shuffling select or reorder records
without changing fields, so the proof survives those operations. Name/index
aliases resolve to the same column. Profiling samples, observed cardinalities
and correlations between columns never establish this proof. No value catalog
is collected: the proof walks at most the validated 64 logical operations and
recovers the current parent's constant values from original partition lineage.

When every requested column is constant, an intermediate partition writes only
its child catalog and shares the immutable data file. A terminal partition
copies checked compact rows directly into the encoded snapshot, reusing decode
capacity. A following uniform-v1 shuffle sorts the same original child random
keys directly, without reconstructing constant tuple keys. Empty named parents
still produce no partition children. Every logical partition remains in stage
statistics, lineage and filenames, and its `exact` flag retains original
partition behavior.

When only some keys are constant, the original partition/sort machinery receives
only varying keys in their original configured order. A fixed value cannot
change the lexicographic order within that parent. Full requested tuples still
construct lineage and child random domains; random keys, collision refinement,
source IDs and encounter order retain v1 semantics. Existing sorter/routing and
external fallbacks remain in place. This does not fuse arbitrary consecutive
partitions on different columns.

The reduced-key vector and temporary borrowed-value descriptors reserve actual
capacity before allocation. Typed admission denial drops optional storage and
selects the original full-key execution; partial shared catalogs are discarded
before retry. Existing JSON values/clones and runtime allocations retain the
previous incomplete accounting boundary, so no process/RSS cap is claimed.
Corrupt/missing proof lineage is terminal rather than silently selecting another
value. Cancellation and max-files/strict output limits retain normal cleanup and
publication behavior. Defaults are unchanged.

### Complete-job comparison

Keep the feature opt-in. The final native comparison completes **156 timed
complete jobs and 52 separate allocation censuses**, including three alternating
repetitions on 300,001 presorted rows, one/four workers and narrow/many-column/
rare-wide shapes. Every successful job independently checks unique IDs and every
field, then compares exact CSV bytes/order, filenames, full partition tuples,
lineage, stage statistics and logical digests across builds/workers.

Four-worker medians, seconds:

| Shape | Pipeline | Original | Reduced keys | Change |
| --- | --- | ---: | ---: | ---: |
| Narrow | Repeated partition | 0.3162 | 0.2058 | -34.9% |
| Narrow | Partition → balanced → repeat → shuffle → balanced | 0.5124 | 0.4490 | -12.4% |
| Narrow | Partition → probabilistic allocation → repeat → shuffle | 0.6091 | 0.5530 | -9.2% |
| 33 columns | Repeated partition | 1.1736 | 0.8709 | -25.8% |
| 33 columns | Partition → balanced → repeat → shuffle → balanced | 1.4520 | 1.3840 | -4.7% |
| 33 columns | Partition → probabilistic allocation → repeat → shuffle | 1.7697 | 1.6778 | -5.2% |
| Rare wide, 33 columns | Repeated partition | 1.2247 | 0.9170 | -25.1% |
| Rare wide, 33 columns | Partition → balanced → repeat → shuffle → balanced | 1.4886 | 1.4015 | -5.8% |
| Rare wide, 33 columns | Partition → probabilistic allocation → repeat → shuffle | 1.8012 | 1.7092 | -5.1% |
| 33 columns | 31-key partition → add payload key → shuffle | 4.2166 | 2.9248 | -30.6% |
| Rare wide, 33 columns | 31-key partition → add payload key → shuffle | 4.2219 | 2.9302 | -30.6% |

The 18 primary medians improve 1.8–36.5%; repeated partitions improve
20.7–36.5%. The four mixed-key medians improve 29.6–30.6%. Their first partition
selects all 31 generated keys; the next adds the payload field and shuffles.
Only the payload remains variable by proof, even though observed generated
columns are correlated. No such correlation is used to skip another key.

The separate 6,400-row small-group control has 64 parents for single-key
partitions and 320 tuples for 31-key partitions. Its 24 timings/eight censuses
are mixed: repeat-only costs 5.7%, the downstream split/shuffle case improves
7.2%, and named-empty/mixed cases change by less than 1%. Ranges are retained;
these metadata/publication-heavy controls prevent a universal speedup claim.

For the four-worker many-column repeated partition, the separate census lowers
whole-job requested allocation traffic from 401.4 to 16.0 MB and allocation calls
from 1,520,141 to 620,017. Logical engine reads fall from 317.0 to 211.2 MB, writes
from 342.5 to 236.7 MB, and peak temporary bytes from 141.4 to 130.9 MB. Peak
charged capacity remains about 8.6 MB because the initial partition still sets
the whole-job peak. The four-worker many-column mixed case lowers requested
traffic from 567.2 to 506.5 MB and sort runs from 30 to 20; both use ten merges.
Different run counts retain exact random-key collision/order semantics.
Median whole-job CPU falls from 1.01 to 0.75 seconds for the repeated case and
3.84 to 2.64 seconds for mixed keys (GNU time resolution 0.01 seconds). Median
per-process RSS is about 13–14 MiB for these cells, with much smaller changes
than requested allocation traffic; the raw distributions remain authoritative.

The persistent-profile comparison completes **132 repeated native/WASI jobs**
at 100,001 rows with exact output/metadata parity, four native workers and one
browser worker. Native references independently check every field/ID and full
partition tuples. Browser narrow primary medians improve 10.3–29.7%, while
many-column/rare-wide primary controls are near flat (−1.6% to +2.0%). Mixed-key
browser medians improve 21.5–22.9%; corresponding native medians improve about
32%. These smaller fixtures do not establish gains for all browser pipelines.

A further four 1,400,001-row mixed-key jobs preserve exact parity. All runtimes
perform ten external merges, reducing sort runs from 100 to 90. The single native
observation falls from 19.76 to 13.41 seconds (32.1%), and browser from 43.02 to
32.42 seconds (24.7%). These are acceptance points, not repeated estimates.
Persistent disk profiles isolate each matrix; current-source browser workers and
other generated development artifacts are restored afterward. Default native
and WASI artifacts are rebuilt and their hashes verified.

These are warm, uncontrolled WSL filesystem/Chromium OPFS observations.
Counters measure logical engine I/O, not physical SSD traffic or filesystem
allocation. Allocation censuses are separate from ordinary timings. Requested
bytes, charged capacity and per-process RSS are different metrics; filesystem
page cache and uncharged JSON/runtime allocations remain outside the ledger.
No complete RSS cap, controlled device/cache result or other-platform gain is
established.


### Validation and reproduction

Three new tests compare full/mixed/duplicate/name-index keys and fused child
shuffles against original full-key sorting. They check shared-file identity,
source IDs/ordinals/keys/fields and lineage, proof survival through selection,
exact admission failure/retry cleanup, named empty allocations and cancellation.
Recorded validation: **199 default / 224 all-feature workspace tests (138
all-feature library tests), default/all-feature all-target Clippy with warnings denied,
formatting and 24 Chromium/WASI contracts pass**. Local-server tests use loopback
access. Twenty-four native controls cover repeated/mixed keys, intervening splits
and shuffle, UTF-16/BOM and headerless text, empty partitions and named empty
allocations, strict caps, a max-files failure after grouping starts, malformed
CSV and ambiguous headers. Successful jobs independently conserve every field/ID
and match exact CSV bytes/order, lineage, stage statistics and digests. Failures
leave no published output or temporary directory.

Artifacts: [native matrix](../../evidence-originals.md#sha256-c97a88d59e508508963dfa5bd8650b90fd591f10d2322b6df0d20a6c30468921 "Original: docs/benchmarks/constant-partition-native-2026-10-17.jsonl"),
[mixed keys](../../evidence-originals.md#sha256-252c1f48ff3f64db85290265666669e59218a77ec82e7bb2b77012dc24b8fd74 "Original: docs/benchmarks/constant-partition-partial-2026-10-17.jsonl"),
[small parents](../../evidence-originals.md#sha256-05f2b7fad869831154c1c16a853f69adadf2ee1d11c7947f67e71e6b32da7c97 "Original: docs/benchmarks/constant-partition-small-groups-2026-10-17.jsonl"),
[native/WASI matrix](../../evidence-originals.md#sha256-1a91533482d218d72ead5acaee2934dda7d0ea9ca4db80ef8dbd7264411939ec "Original: docs/benchmarks/constant-partition-engines-2026-10-17.jsonl"),
[native/WASI mixed keys](../../evidence-originals.md#sha256-6dd4bae3f57b1e6299b3ada653fb80bbb5caedf63faca67ce0a293e7606bba87 "Original: docs/benchmarks/constant-partition-partial-engines-2026-10-17.jsonl"),
[large external groups](../../evidence-originals.md#sha256-635c18983f12999c3f869d84763a00e559b896b4dbaf5614d08a1b10b2b0be18 "Original: docs/benchmarks/constant-partition-large-engines-2026-10-17.jsonl"),
[failure/encoding controls](../../evidence-originals.md#sha256-eb962f457f1071ef3391cfc6524df77aeca133371e5f66897ad4f320757f423a "Original: docs/benchmarks/constant-partition-controls-2026-10-17.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-58fe3b8517b422afcbd2790e6d701aa53e5f8ff1e9c0d037676a596c0020ff80 "Original: docs/benchmarks/constant-partition-browser-2026-10-17.json"),
[summary and source/build identities](../../evidence-originals.md#sha256-29dc671ac65b0fa9f90e7c575246ac063032a20964c01fa6e684a31c1120b792 "Original: docs/benchmarks/constant-partition-summary-2026-10-17.json").

```sh
# Build/copy ORIGINAL and ORIGINAL_ALLOC, then REDUCED and REDUCED_ALLOC.
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
cargo build --release --locked -p chopper --bin chopper --example allocation-profile \
  --features experimental-constant-partition
python3 scripts/benchmark-external-shuffle.py --baseline ORIGINAL --candidate REDUCED \
  --baseline-allocator ORIGINAL_ALLOC --candidate-allocator REDUCED_ALLOC \
  --rows 300001 --memory-mb 32 --workers 1 4 --repeats 3 \
  --shapes narrow columns rare_wide \
  --cases constant_repeat constant_downstream constant_empty
# Mixed keys: --shapes columns rare_wide --cases constant_partial
# Small-parent control: same binary flags with scripts/benchmark-constant-groups.py,
# --rows 6400 --workers 4 --shapes columns --cases constant_repeat constant_downstream constant_empty constant_partial
python3 scripts/validate-constant-partition.py --baseline ORIGINAL --candidate REDUCED
# Build/copy matching default/candidate WASI files with scripts/build-browser.sh.
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs ORIGINAL REDUCED ORIGINAL.wasm REDUCED.wasm \
  100001 3 narrow,columns,rare_wide \
  constant_repeat,constant_downstream,constant_empty original,reduced 4
```
