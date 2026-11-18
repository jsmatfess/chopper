## Nested balanced range fusion (2026-10-17)

The opt-in `experimental-nested-balanced` feature recognizes adjacent chains of
balanced splits after ingestion. It walks each parent's original nested ranges
with the original remainder rounding, rather than flattening the chain into one
product split. Logical operation indices, hierarchical lineage, canonical child
order, exact-group flags and every stage summary are retained.

Intermediate chains share the original immutable data file and write only the
final leaf catalog. One checked frame-length iterator per original parent finds
all final boundaries. Terminal chains instead decode rows once and emit leaves
directly into the retained encoded output snapshot. A downstream operation still
sees the original leaf lineage and source IDs, preserving its random domains.
Existing ingestion/shuffle fusion can consume the first balanced step; this
prototype handles the remaining adjacent chain, rather than changing that rule.

A fixed 64-entry stack array holds stage counters, matching the validated job
operation limit. Traversal reuses one parent lineage stack and clones lineage
only at leaf emission. The initial candidate retained one cloned lineage per
recursive level; its interrupted matrix is kept separately and superseded by the
revised candidate. Existing dataset/output buffers, readers, decoder capacity,
paths and publication limits retain their reservations. JSON lineage clones and
analysis metadata still share the existing incomplete accounting boundary; this
feature does not establish a complete RSS cap.

Each logical stage enforces the original nonempty-parent and max-files rules.
Cancellation is checked at traversal and row boundaries. Failure drops partial
catalogs/snapshots and publishes nothing. Empty input and named empty parents
retain balanced splitting's failure semantics; empty partition results introduce
no synthetic children.

### Complete-job comparison

Keep defaults unchanged; retain the candidate opt-in pending broader evidence.
The final native matrix contains **162 timed complete jobs and 54 separate allocation
censuses**, using paired release builds from the same sources. Three alternating
repetitions cover 300,001 presorted rows, three shapes, shallow/deep/downstream
chains, and one/four workers. All exact fingerprints match across builds and worker
counts; each output independently checks unique source IDs and every field.
Unshuffled jobs additionally check original nested-range membership.

Four-worker primary medians, seconds:

| Shape | Pipeline | Serial | Fused | Change |
| --- | --- | ---: | ---: | ---: |
| Narrow | balanced(3) → balanced(4) | 0.1539 | 0.1379 | -10.4% |
| Narrow | balanced(3) → balanced(4) → shuffle | 0.2940 | 0.2630 | -10.5% |
| Narrow | balanced(3) → balanced(4) → balanced(2) → balanced(2) | 0.2935 | 0.2489 | -15.2% |
| 33 columns | balanced(3) → balanced(4) | 0.7108 | 0.6502 | -8.5% |
| 33 columns | balanced(3) → balanced(4) → shuffle | 1.1572 | 1.0597 | -8.4% |
| 33 columns | balanced(3) → balanced(4) → balanced(2) → balanced(2) | 1.0490 | 0.7502 | -28.5% |
| Rare wide, 33 columns | balanced(3) → balanced(4) | 0.7324 | 0.6412 | -12.5% |
| Rare wide, 33 columns | balanced(3) → balanced(4) → shuffle | 1.1685 | 1.0984 | -6.0% |
| Rare wide, 33 columns | balanced(3) → balanced(4) → balanced(2) → balanced(2) | 1.0020 | 0.7570 | -24.5% |

All 18 principal medians improve 5.2–28.5%. Ten partitioned parents on
300,011-row many-column/rare-wide inputs add 24 timings and eight censuses;
their four medians improve 5.7–10.7%. The 1,400,001-row shuffled-input control
adds six timings and two censuses, with 77 sort runs and two merges in both
builds; its complete-job median falls from 6.055 to 5.661 seconds (6.5%).
Twenty-four tiny-job timings/eight censuses on 128 rows are mixed: medians
range from 4.0% faster to 4.7% slower. Setup/publication dominate those jobs.

For the four-worker many-column deep chain, median CPU falls from 0.80 to
0.54 seconds (GNU time resolution 0.01 seconds). Logical engine reads fall
from 420.5 to 104.9 MB; writes remain about 130.9 MB because the retained input
and encoded snapshot still dominate. Peak temporary bytes stay about 130.9 MB.
The separate census lowers whole-job requested allocation traffic from 10.87
to 7.51 MB and allocation calls from 5,785 to 4,935. Charged peaks remain about
208 KB for this cell; median per-process RSS is roughly 5.4 MiB and varies
separately from reservations. These figures do not measure filesystem page cache
or establish a process/RSS cap. Ordinary timings exclude instrumented censuses.

The repeated persistent-profile replay completes **132 native/WASI jobs** at
100,001 rows: three primary shapes/three pipelines and two partition-parent
shapes, with three alternating repetitions and four native workers/one browser
worker. All exact fingerprints match across variants and runtimes. Browser
primary medians improve 5.5–29.4%; parent cases improve 2.1–5.7%. Native parent
controls at this smaller size are mixed (−0.5%, +2.6%), limiting generalization.
A further four 1,400,001-row jobs all match, with native 77-run/two-merge and
browser 70-run/two-merge pipelines. The single browser acceptance observation
falls from 27.89 to 24.33 seconds (12.8%); it is not a repeated speed estimate.
Browser workers are built from current source, persistent disk profiles are
isolated per matrix, and generated development artifacts are restored. Default native and WASI builds
are restored afterward and their hashes verified.

All storage observations are warm, uncontrolled WSL filesystem/Chromium OPFS.
Logical temporary traffic is distinct from physical SSD bytes. Browser CPU,
allocation counts and RSS, controlled SSD cache conditions and other platforms
remain outside this experiment.


### Validation and reproduction

Two new library tests compare nonempty uneven counts across multiple parents,
shared-file offsets and terminal emission, every stage summary and downstream
seeded shuffle output. They also cover partial-catalog cleanup, insufficient
rows and cancellation. The revised sources pass **199 default / 221 all-feature
workspace tests (135 all-feature library tests), default/all-feature all-target Clippy
with warnings denied and 24 Chromium/WASI contracts**. The full suites run with
loopback access for their local-server tests. Formatting passes. Twenty-four native
controls cover terminal/downstream/partitioned jobs, quoted Unicode/newlines,
UTF-16/BOM, a 64-level chain, empty partitions, named empty allocations,
empty/insufficient input, strict caps, max-files and
malformed CSV; successes match exact bytes/order/metadata and independently check
every field/ID, while failures leave no output or temporary directory.

Artifacts: [native matrix](../../evidence-originals.md#sha256-7174b9009ac577c3b2e0453200cdca8da211dac8bc46c3ecbbda00bc2e700fd0 "Original: docs/benchmarks/nested-balanced-native-2026-10-17.jsonl"),
[partition parents](../../evidence-originals.md#sha256-2f4ddb71b7e106b5953b914f83bf6e4d57fd7df9ddb6faca05bea102cd20e885 "Original: docs/benchmarks/nested-balanced-parents-2026-10-17.jsonl"),
[hierarchical merge](../../evidence-originals.md#sha256-727496eb489e63887ad2b3be626d1c482f8509957960a028df3218f54d3d385c "Original: docs/benchmarks/nested-balanced-multilevel-2026-10-17.jsonl"),
[tiny controls](../../evidence-originals.md#sha256-dac91ed0fdef70483ec8b2a7b71b8f459b2f46978174d7c80e1960659de2c36a "Original: docs/benchmarks/nested-balanced-tiny-2026-10-17.jsonl"),
[native/WASI matrix](../../evidence-originals.md#sha256-8db365682a515e14a643028282aa634a4a21b2fc56566a3de9ecbcb81cd6c564 "Original: docs/benchmarks/nested-balanced-engines-2026-10-17.jsonl"),
[native/WASI parents](../../evidence-originals.md#sha256-0a6dc1a0075288a88380aa338033520598a7ad8d5d63a9906431117a41ed9714 "Original: docs/benchmarks/nested-balanced-parent-engines-2026-10-17.jsonl"),
[native/WASI hierarchy](../../evidence-originals.md#sha256-ce0419af2205ad3003cccbece6710db5466c82792556130362a42a62c6a7d37b "Original: docs/benchmarks/nested-balanced-multilevel-engines-2026-10-17.jsonl"),
[failure/encoding/deep-chain controls](../../evidence-originals.md#sha256-dc9572181997bf9a18d8154577cdbbf723b27aac871a5a1120174b7c557ed8d5 "Original: docs/benchmarks/nested-balanced-controls-2026-10-17.jsonl"),
[browser contracts](../../evidence-originals.md#sha256-65e6fd4689824ec3718ca852788faaf432148047efaaf01d3cd55bb6d3ba41a3 "Original: docs/benchmarks/nested-balanced-browser-2026-10-17.json"),
[summary and source/build hashes](../../evidence-originals.md#sha256-38ea7c75cfcb5e39ddfcabac30f346ef46428383a97406c0fb58180da1def81f "Original: docs/benchmarks/nested-balanced-summary-2026-10-17.json"),
[superseded initial candidate](../../evidence-originals.md#sha256-fd6b140fe35be5cf63d1285da632bc4f61c5c4a5148f5b87ca0f4d59b51683d3 "Original: docs/benchmarks/nested-balanced-initial-native-2026-10-17.jsonl").

```sh
# Build/copy SERIAL and SERIAL_ALLOC, then FUSED and FUSED_ALLOC from matching sources.
cargo build --release --locked -p chopper --bin chopper --example allocation-profile
cargo build --release --locked -p chopper --bin chopper --example allocation-profile \
  --features experimental-nested-balanced
python3 scripts/benchmark-external-shuffle.py --baseline SERIAL --candidate FUSED \
  --baseline-allocator SERIAL_ALLOC --candidate-allocator FUSED_ALLOC \
  --rows 300001 --memory-mb 32 --workers 1 4 --repeats 3 \
  --shapes narrow columns rare_wide --cases nested nested_downstream nested_deep
# Parent controls: --rows 300011 --shapes columns rare_wide --cases nested_parents
# Hierarchy: --rows 1400001 --workers 4 --shapes columns --cases shuffled_nested
# Tiny: --rows 128 --shapes narrow --cases nested nested_deep
python3 scripts/validate-nested-balanced.py --baseline SERIAL --candidate FUSED
# Build/copy matching default and candidate WASI files with scripts/build-browser.sh.
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs SERIAL FUSED SERIAL.wasm FUSED.wasm \
  100001 3 narrow,columns,rare_wide nested,nested_downstream,nested_deep serial,fused 4
```
