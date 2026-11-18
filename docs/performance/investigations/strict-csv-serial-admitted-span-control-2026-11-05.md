## Strict CSV serial admitted-span control (2026-11-05)

**Decision: deliver a behavior-preserving ordinary-field copy optimization;
retain the modest scoped timing effect without general speed advice.** The
[raw comparison](../../evidence-originals.md#sha256-9f3785671bd655b62de2162b72c143ace069aa8322695fe1b32c1c85bae2690d),
[implementation patch](../../benchmarks/strict-csv-serial-spans-2026-11-05.patch),
[native harness](../../benchmarks/strict-csv-serial-spans-2026-11-05.py) and
[component probe](../../benchmarks/strict-csv-serial-spans-2026-11-05-probe.rs)
provide a stronger strict serial control for ingestion work before any
parallel parser. The existing parser already bulk-scans ordinary spans with
`memchr`; this change removes an intermediate scratch copy when a complete
nonempty unquoted field ends at a delimiter or LF in the current input buffer.
Admitted owned destinations reuse existing field slots, while compact destinations
append the existing length/payload framing directly. New owned slots, quoted,
escaped, split, CRLF and unterminated-last-field paths keep their prior handling.
No dependency, schema, Run dispatch, execution graph/retry, worker, algorithm/version,
default or Auto policy changes are made.

Exactly four native Windows CLI ordered-export Runs use one million unquoted
ASCII probe-v1 records, the fixed seed, 32-MiB job memory, one worker and
1,000,000-row/128-MiB strict caps, producing one CSV each. The schedule is
baseline/candidate/candidate/baseline, two observations per variant. Seconds
include process startup, configuration, complete Run/publication and Analysis JSON
through process exit; fixture generation, hashing and independent verification
are outside the clock.

| Ordered export | Median seconds | Minimum | Maximum |
| --- | ---: | ---: | ---: |
| Existing strict parser | 0.43791 | 0.37171 | 0.50411 |
| Admitted ordinary spans | 0.42328 | 0.35963 | 0.48693 |

Candidate-minus-baseline opposite-order differences are -0.01718 and -0.01208
seconds. The median reduction relative to baseline is 3.34%. These short ranges
overlap with substantial between-pair drift, warm/uncontrolled cache and retained
background apps; this is no tail, threshold, device-throughput or broad shape
claim. A separate 200,000-record partition -> probabilistic 80/20/0 -> uniform
shuffle pair retains the earlier 1,024-row/65,536-byte caps and emits 296 files.
Its 1.38283/1.36663 seconds are unreplicated diagnostic observations only.

All six jobs independently verify actual CSV fields, unique IDs, group/lineage,
row/byte caps, output inventory and cleanup. Raw per-file SHA-256 maps, ordered
output records and 17 logical Analysis fields match per recipe; ordered CSVs also
match the generated input bytes exactly. No row membership oracle beyond the
same-version baseline is claimed for seeded allocation/shuffling.

Eight supporting parser scans repeat the same ABBA schedule separately for
admitted owned and compact APIs. They time file-open/decode/parse and simple
field counters through EOF, excluding process startup. Owned medians are
0.12686/0.11361 seconds (10.44% lower), compact 0.14851/0.14741 (0.74% lower,
near-flat overlapping ranges). These are component controls, not Run speedups or
precise CPU attribution. Their always-accept capacity callback records modeled
peak requests: owned 828/837 and compact 660/669 bytes, baseline/candidate. The
nine-byte increases make clear that avoiding copies does not establish lower
memory. These are not actual engine grants, RSS or physical I/O measurements.

Fresh Linux formatting, all-target Clippy, complete workspace tests and portable
core WASM check pass 4/4 gates. New normative comparisons exercise every small
refill size, working-limit edges and strict errors against the unchanged
unreserved owned target; denied owned/compact callbacks cover retained capacities.
Native MSVC default builds, independent fixtures, six jobs, eight probes and
verification pass 8/8 gates. Every maintained Rust/vendor/native-embedded byte
matches the validated candidate; native builds add only the identical private
probe example. Exact patch replay passes. Exact-head CI still gates platform,
combined-feature and browser acceptance before merge.

Actual context is Windows 11 build 26200, Ryzen 7 5800X, eight cores/16 logical
CPUs, native NTFS and Rust 1.99.1; full hardware/toolchain/source hashes, plans,
binaries, raw output and failed preparation notes remain under private
`scratch/strict-csv-serial-20261105T0624/` in both checkouts. No native job was
repeated or matrix expanded, and no own Linux build ran during native timing.
Quoted/Unicode/wide/fallback shape timings, parallel boundary discovery,
queued-owner costs and complete-job parallel benefit remain unmeasured.
