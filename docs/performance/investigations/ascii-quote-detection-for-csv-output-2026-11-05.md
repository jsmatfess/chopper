## ASCII quote detection for CSV output (2026-11-05)

**Decision: use existing byte searches for ASCII quote/delimiter settings and
retain character matching for Unicode settings; deliver scoped favorable evidence.**
The [eight-job record](../../evidence-originals.md#sha256-30cd20f30cdaefa49c84a33d932bc1fd91b20a33609d68effd2fe456b5cf99c4),
[implementation patch](../../benchmarks/ascii-quote-detection-2026-11-05.patch) and
[native harness](../../benchmarks/ascii-quote-detection-2026-11-05.py) compare against the
[quoted-span baseline](../../performance.md#quoted-csv-serialization-spans-2026-11-05).
The harness reuses the unchanged [completed-process CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py)
with that dated filename beside it. No new dependency, unsafe runtime code,
buffer, schema, worker, execution graph/retry, default or Auto change follows.

The serializer and its cold capacity planner formerly used the same four-character
`str::contains` predicate. A private helper now checks empty values, uses
`memchr3` for ASCII delimiter/quote/LF and a separate CR search, and otherwise
retains the original character predicate. ASCII structural bytes cannot occur
inside another UTF-8 scalar. Escape alone remains outside the quoting trigger;
quoted escaping, output encodings, strict byte caps, full-record capacity planning
and owner lifetimes are unchanged. The existing memchr dependency already serves
input parsing; this adds no worker or separately retained storage.

Before implementing the candidate, the installed Rust 1.99.1 source was inspected
and one separately bounded native MSVC compiler invocation emitted two optimized
standalone predicates: default constant characters and runtime-selected characters.
Both [probe source](../../benchmarks/ascii-quote-detection-2026-11-05-audit.rs) and
[raw assembly](../../benchmarks/ascii-quote-detection-2026-11-05-audit.s) are retained.
They show scalar UTF-8 decoding/byte-advance loops. This is a compiler diagnostic,
not production inlined-code identity, a function-level CPU profile or a speed
observation. It justified testing an explicit byte-search hypothesis, not assuming
that library source alone determines final throughput.

Four fresh native Windows ordered exports use one million ordinary probe-v1 ASCII
records, in baseline/candidate/candidate/baseline order. Both variants use four
workers, 32-MiB job/process budgets, 1-MiB record limit, 1-GiB temporary ceiling and
1,000,000-row/128-MiB strict output caps. Each produces one 94,776,853-byte CSV,
exactly equal to the input. All elapsed observations include CLI startup through
complete Run/publication, Analysis JSON and process exit, excluding fixture hashes,
independent verification and the post-exit process CPU query.

| Plain ordered export | Observations | Median wall seconds | Wall range | Median process CPU seconds | CPU range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Character predicate | 2 | 0.44664 | 0.38178–0.51149 | 0.35156 | 0.34375–0.35938 |
| ASCII byte predicate | 2 | 0.41063 | 0.35394–0.46732 | 0.32813 | 0.32813–0.32813 |

Candidate-minus-baseline opposite-order wall differences are -0.04417 and
-0.02784 seconds; process CPU differences are -0.015625 and -0.031250. Relative
to baseline medians, wall time falls 8.06% and process CPU 6.67%. The wall ranges
overlap with substantial between-pair drift; CPU values are coarse. Two short
observations per variant with uncontrolled warm cache/background apps establish
no tails, thresholds, statistical significance or broad shape/device performance.
CPU sums user/kernel time for all CLI process threads, not function attribution.

Two unreplicated shape/control pairs stay separate. Already-quoted rich Unicode
ordered export has baseline/candidate wall 0.55365/0.54557 seconds and process CPU
0.54688/0.50000. A 200,000-row plain partition -> probabilistic 80/20/0 -> uniform
shuffle pair has wall 0.68095/0.65621 and CPU 0.57813/0.50000, producing 12 CSVs.
Neither pair establishes a speedup. No older timing is pooled, and percentage
gains from earlier serial/packed/quoted studies are not added together.

All eight jobs independently verify actual fields, unique IDs, group/lineage,
strict row/byte caps, inventory and cleanup. Per-cohort raw CSV hash maps, output
records and 17 logical Analysis fields match exactly; both ordered shapes also
match input bytes. Pipeline snapshots retain eight sort runs, four merges and
matching logical temporary traffic. Returned Analysis workspace peaks are
202,348/202,354 bytes for plain ordered and 7,461,220/7,461,229 for the pipeline;
variant-name lengths change path/configuration charges. These snapshots precede
final publication and do not measure complete-Run I/O, physical traffic or RSS.

Fresh Linux formatting, all-target Clippy, full workspace tests and portable-core
WASM check pass 4/4 gates. The new private differential test checks 128 ASCII and
ten Unicode boundary characters at ten padding/alignment sizes across eight
ASCII/Unicode/duplicate/unusual dialects: 11,040 comparisons against normative
character matching, plus eight empty-value checks. Existing literal serialized
bytes, escape, encoding/unrepresentable-text, admitted growth/retry, cap and cleanup
contracts remain passing. The native batch passes 5/5 gates: baseline/CPU-control
identity proof, exact fixtures, one fresh candidate build, eight-job panel and
verification. The prior CPU helper self-control is reused only after matching its
source and native Python executable; it is not rerun or recounted as a fresh test.
The separate assembly batch passes 2/2 gates and consumes one diagnostic compile.

The baseline's original 330 file hashes, 81 directory tokens, exact source file-set
and binary identity are rechecked; Cargo executable/build-environment identities
match. Every maintained Rust/vendor/native-embedded byte matches the validated
candidate; native sources add only the identical unused probe example. Exact patch
replay passes. Full exact-head native/combined-feature/browser CI still gates merge.

Actual context is Windows 11 build 26200, Ryzen 7 5800X (8 cores/16 logical CPUs),
NTFS and Rust 1.99.1. Raw jobs, immutable sources, logs/status, assembly, plans and
hardware/toolchain/artifact identities remain under private
`scratch/quote-detection-20261105T0850/` in both checkouts. The one-candidate-build/
eight-job caps are consumed without failures, repeats, component scans or matrix
expansion; no own Linux build ran during native timing. Non-ASCII dialect, other
encoding/browser speed, wider distributions, scale and RSS effects are unmeasured.
