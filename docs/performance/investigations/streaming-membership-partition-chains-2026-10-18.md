## Streaming membership partition chains (2026-10-18)

`experimental-streaming-chain` fuses adjacent count-independent membership,
value partition and count-independent membership into one input traversal and one
final grouping/materialization. Both endpoints support probabilistic allocation
and interleaved splitting. Exact-quota allocation, shuffles, positional balanced
splits and intervening operations are excluded. Native/WASI defaults remain unchanged.

### Exact execution and resource bounds

`streaming::Membership` now owns the original v1 categorical draws, selected
strata, weights, encounter counters, named allocations and charged metadata,
independently of materialization. Ordinary streaming execution uses this same
implementation. First-stage choices use the original logical parent's domain and
source IDs. Each observed `(first child, requested partition tuple)` retains its
own encounter counter and last-stage counts. A probabilistic last stage derives
its original domain from the complete first-child/partition lineage and original
operation index. Interleaving advances only the matching logical parent's counter.

A composite key orders the first requested child, original tuple, last requested
child and original encounter ordinal. Existing checked resident/routed/merge
consumers preserve exact field text, source IDs, relative order, canonical group
ordering, every logical stage summary and downstream random domains. Named empty
allocations contribute to the original stages; final empty allocations are
emitted in requested order. Partitioning drops earlier empty groups exactly as
before. Per-parent nonempty failures and strict final caps remain enforced.

Catalog keys, retained tuple strings, per-parent count vectors, selected-column
arrays and descriptor growth overlap reserve before allocation. The catalog is
bounded to 256 scopes and a conservative memory/32 allowance. Row keys reserve
the complete prefix/tuple/suffix capacity before construction and transfer through
the existing boxing/sort ownership path. A composite-key owned-row allowance
that exceeds the original per-row limit triggers replay rather than rejecting a
row that fits the original stage keys.

Counter fanout/capacity denial or typed memory denial drops the complete attempt,
including earlier parents' tentative outputs, then replays the original CSV or
immutable dataset pipeline. CSV restarts keep the existing source-stability
check. Semantic/CSV/disk/cap errors and cancellation are terminal. Only successful
complete attempts increment fusion/row counters; retries are recorded separately.
The retained prepared CSV snapshot remains the authority for confirmation/export.

### Measured revision

The initial candidate routed from its first row. Its 100,000-row native cases
improved 11–46%, but 4,000-row many-column cases regressed by up to 22% as eager
routing created small spool files before value fanout was known. The revised
candidate uses the existing resident first buffer and routing/merge preflight.
Small jobs can remain resident; larger buffers choose bounded routing or external
merging from observed keys. Initial source/build identities and complete initial
matrices are retained separately and superseded for final performance interpretation.

The final native comparisons contain **492 timed complete jobs and 148 separate
allocation censuses**, preserving exact output/order/metadata and independent
field/ID conservation. This includes 48 default-only controls around the shared
membership refactor; their medians vary −2.1% to +2.1%, with exact legacy output
and no claimed speedup. Those observations are reused after the candidate-only
revision because the default native, allocator and WASI hashes remain identical.

The primary 100,000-row matrix alternates three repetitions, one/four workers,
six chains and narrow/many-column/rare-wide rows. All primary medians improve
**12.3–43.4%**. The 100,000-row skew matrix improves **21.0–45.1%**. The revised
4,000-row controls remain mixed (**−13.0% to +2.0%**), replacing the initial
candidate's larger regression.

At 1,400,001 many-column rows/four workers, the probabilistic chain improves
**48.1%** (7.158 to 3.713 seconds), with ranges 7.137–7.181 and 3.658–3.753
seconds. The interleaved chain improves **33.7%** (6.838 to 4.534 seconds), with
ranges 6.790–6.843 and 4.529–4.587 seconds. The former uses bounded routing;
the latter exercises external merging after its larger composite-key fanout.

At 100,000 many-column rows and one worker, the probability/partition/interleaved
chain's median falls from 0.652 to 0.445 seconds. Logical temporary writes fall
from 184,956,152 to 45,397,740 bytes, reads from 177,089,410 to 36,788,890 bytes,
and whole-job requested allocation traffic from 145,296,158 to 28,848,803 bytes.
Peak live requested allocation rises from 8,344,954 to 11,200,889 bytes; peak
workspace reservation rises from 8,595,895 to 11,271,628 bytes. This exchanges
higher live memory for fewer passes and less allocation traffic. At 4,000 rows,
the same cell creates four rather than 68 engine temporary files. Allocator
censuses are separate from timed jobs; GNU time records native CPU/RSS/block
counters, and requested/ledger peaks do not establish an RSS cap.

The persistent-profile comparison completes **240 alternating native/WASI
jobs**: 216 at 100,000 rows across three shapes and all six chains, plus 24
repeated 1,400,001-row jobs for the routed and external candidates. Every result
matches exact CSV bytes/order, names, lineage, logical digests and stage summaries;
native verification independently checks fields, IDs, partition membership and
interleaved parent counters. **24 candidate Chromium/WASI contracts pass.**

Primary browser medians improve **13.3–45.6%**. The large probabilistic/routed
chain improves **55.9%**, from 23.527 to 10.380 seconds, with ranges
23.500–23.766 and 10.341–10.425 seconds. Both builds use routing without external
sort runs/merges in this cell.

The large interleaved case exposes a material browser regression: **24.176 to
27.584 seconds (+14.1%)**, with ranges 24.171–24.512 and 27.326–27.853 seconds.
The original uses routing without external merges; fusion performs 71 sort runs
and two merges (86 runs/two merges natively). Its accompanying native median
improves 35.0%. These observations demonstrate a runtime/scale tradeoff; they do
not isolate browser CPU or individual OPFS costs. Keep the feature opt-in.
Default native/allocator/WASI development builds are restored, with hashes
recorded in the summary.

### Validation, limits and reproduction

**199 default / 244 all-feature workspace tests, 158 all-feature library tests,
formatting and default/all-feature all-target Clippy with warnings denied pass.**
Local-server integration tests run with loopback access.

Eight new tests cover eligibility/barriers; all four membership combinations;
original counters/domains/stats/ordinals and downstream seeded shuffles; forced
resident/hierarchical execution; exact catalog capacity and growth overlap;
shared denial; rollback after an emitted parent; CSV/dataset admission retry;
named empty scopes and ingestion snapshots; cancellation after actual output;
and the composite-key owned-row allowance boundary. The existing four streaming
reservation/reuse tests continue to pass after sharing membership logic.

Forty-six CLI controls preserve exact bytes/order/names/lineage/stages/digests and
independently conserve all IDs/fields, or reject cleanly. They include an earlier
parent with a nonzero source ordinal, a second chain over empty/nonempty parents,
duplicated selected columns, all membership combinations, high fanout, rollback
after a successful parent, large keys, empty input/named allocations, UTF-16/BOM,
headerless input, strict caps, max-files limits, insufficient parents, malformed
CSV, temporary quotas and oversized records. Every failure leaves no output or
temporary files. Matrix verification independently reconstructs per-scope
interleaved encounter counters from conserved input IDs.

Configured shared-admission checks add eight unconstrained references,
32 constrained successes, eight clean failures and four invalid settings across
one/four workers, many-column/late-wide input, profiles and complete jobs. Six
successful real jobs retry the original graph at 4/8 MiB process-ledger ceilings.
All successes match exact references, and every failure leaves no output or
temporary files. These are configured ledger limits, not OS/cgroup/RSS pressure
experiments.

Storage is warm uncontrolled WSL and persistent-profile Chromium OPFS. Logical
I/O counters include read-ahead; physical SSD traffic/cache/device throughput,
browser CPU/allocations/RSS and complete process/RSS accounting are not measured.
The increased live-memory peak and remaining broader storage/platform/resource
policy evidence keep this candidate opt-in. Flexible randomization and exact
allocation/shuffle rewrites remain separate work.

Artifacts: [final native](../../evidence-originals.md#sha256-d19c36a6fc9f8cf8d18fa4b396c7bcdba6de66691738dd582e55c2f93de2a813 "Original: docs/benchmarks/streaming-chain-native-2026-10-18.jsonl"),
[tiny](../../evidence-originals.md#sha256-5ec956d77ffeef0dde263a9cd3652170a6822d3761647a13ecf72b124f6a6f5b "Original: docs/benchmarks/streaming-chain-tiny-2026-10-18.jsonl"),
[skew](../../evidence-originals.md#sha256-034d6123d018185fa9f8e347f1b73af66c174d96ec8e169cca1227b28ae2a476 "Original: docs/benchmarks/streaming-chain-skew-2026-10-18.jsonl"),
[large native](../../evidence-originals.md#sha256-8c0724c60637316f0f62a0a74662b9176144cca1b7a3b6697c1159859587d25d "Original: docs/benchmarks/streaming-chain-multilevel-2026-10-18.jsonl"),
[unchanged default controls](../../evidence-originals.md#sha256-8e83ecf73d0b81ceb4a271db71d7ee4b5ca9f307ad46c78d4a248ce21a3f13ed "Original: docs/benchmarks/streaming-chain-default-controls-2026-10-18.jsonl"),
[native/WASI](../../evidence-originals.md#sha256-d574bbba4a0dd219192efb2fdec428fc761b65997973fb44e1dda1bbbecae89e "Original: docs/benchmarks/streaming-chain-engines-2026-10-18.jsonl"),
[large native/WASI](../../evidence-originals.md#sha256-431b40b68b50e75197b803afcbdda1b806c2e26650b2da9d548579d30cecbae1 "Original: docs/benchmarks/streaming-chain-multilevel-engines-2026-10-18.jsonl"),
[CLI controls](../../evidence-originals.md#sha256-1fd30dc376afd6feaf47a1ca08cfa10d257569f495ab98ac06b44a326bc09e11 "Original: docs/benchmarks/streaming-chain-controls-2026-10-18.jsonl"),
[shared admission](../../evidence-originals.md#sha256-882b833c6eb653ee54b05803494e852da8d1f737ed2103fa6403f3df8a4f1a95 "Original: docs/benchmarks/streaming-chain-boundaries-2026-10-18.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-f6194f732717f1318127afd9bc2db02454c84f8ad04f1d7c2747b385e754e07e "Original: docs/benchmarks/streaming-chain-browser-2026-10-18.json"),
[initial source/build identities](../../evidence-originals.md#sha256-a1339e8d709589e00a49cb5414158304d9f40e2b3628075385ec6a2fecea0663 "Original: docs/benchmarks/streaming-chain-initial-sources-2026-10-18.json"),
[final summary/source/build identities](../../evidence-originals.md#sha256-036ccf866f67599c43a52782f6eb9b889bdd91608ce0a170b189cdfb02893f21 "Original: docs/benchmarks/streaming-chain-summary-2026-10-18.json").

```sh
# Build/copy ORIGINAL and ORIGINAL_ALLOC, then FUSED and FUSED_ALLOC.
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
cargo build --release --locked -p chopper --bin chopper --example allocation-profile \
  --features experimental-streaming-chain
python3 scripts/benchmark-external-shuffle.py --baseline ORIGINAL --candidate FUSED \
  --baseline-allocator ORIGINAL_ALLOC --candidate-allocator FUSED_ALLOC \
  --rows 100000 --workers 1 4 --repeats 3 --shapes narrow columns rare_wide \
  --cases chain_probability chain_parents chain_downstream chain_interleaved chain_last_probability chain_both_probability
# Tiny: --rows 4000 --shapes narrow columns; skew: --shapes skew.
# Large: --rows 1400001 --workers 4 --shapes columns --cases chain_probability chain_interleaved.
python3 scripts/validate-streaming-chain.py --baseline ORIGINAL --candidate FUSED
python3 scripts/benchmark-shared-memory.py --before ORIGINAL --after FUSED \
  --streaming-chain --rows 100000 --memory-mb 32
# Build/copy default/candidate WASI files with scripts/build-browser.sh.
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs ORIGINAL FUSED ORIGINAL.wasm FUSED.wasm \
  100000 3 narrow,columns,rare_wide \
  chain_probability,chain_parents,chain_downstream,chain_interleaved,chain_last_probability,chain_both_probability original,fused 4
```
