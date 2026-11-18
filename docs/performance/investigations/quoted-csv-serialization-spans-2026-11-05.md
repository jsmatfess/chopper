## Quoted CSV serialization spans (2026-11-05)

**Decision: copy ordinary quoted-field text in spans while retaining exact
escaping; deliver the scoped native improvement with its negative control.**
The [eight-job record](../../evidence-originals.md#sha256-dc32b3a13179c799d2e4992d2eecf0aedd67ffb09c1664918ce3fcb4dc2e8e98),
[implementation patch](../../benchmarks/quoted-serialization-2026-11-05.patch),
[native harness](../../benchmarks/quoted-serialization-2026-11-05.py) and
[completed-process CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py)
compare against the [validated compact-field baseline](../../performance.md#validated-compact-field-traversal-2026-11-05).
The private native replay layout keeps the CPU helper's dated filename beside
`native-panel.py`. No worker machinery, execution graph/retry, feature, default,
Auto, encoding, output-cap or publication policy changes follow.

Previously, quoted CSV serialization appended every Unicode scalar separately,
checking target capacity on each append. The writer now uses UTF-8 character-boundary
matches for quote/escape characters, appends ordinary text spans and retains the
same escape-prefix/original-character bytes. Empty values, doubled quotes,
custom/identical/Unicode quote and escape characters, CRLF and output transcoding
retain their behavior. The reserved target still pre-admits full-record planned
capacity and old/new overlap on growth, retaining text/encoded buffers through
their owners. No buffer/thread/queue is added. Unreserved String capacity growth
is not claimed identical; strict serialized bytes remain identical.

Four fresh native Windows CLI ordered exports use one million rich records:
IDs, four region values, variable ASCII payloads, a comma, `界`, doubled quotes
and embedded CRLF. Python's CSV writer generates the fixture independently of
Chopper. The baseline/candidate/candidate/baseline schedule uses four workers,
32-MiB job/process budgets, 1-MiB record limit, 1-GiB temporary ceiling and
1,000,000-row/128-MiB strict output caps. Each emits one 120,776,853-byte CSV,
exactly equal to the input bytes. Elapsed time includes CLI startup through
complete Run/publication, Analysis JSON and process exit; fixture generation,
hashes, independent verification and the post-exit CPU query are excluded.

| Quoted ordered export | Observations | Median wall seconds | Wall range | Median process CPU seconds | CPU range |
| --- | ---: | ---: | ---: | ---: | ---: |
| Per-character appends | 2 | 0.77556 | 0.70856–0.84256 | 0.64844 | 0.64063–0.65625 |
| Ordinary spans | 2 | 0.61845 | 0.55728–0.67963 | 0.52344 | 0.51563–0.53125 |

Candidate-minus-baseline opposite-order wall differences are -0.16293 and
-0.15128 seconds; process CPU differences are -0.12500 in both pairs. Relative to
the baseline medians, wall time falls 20.26% and process CPU 19.28%. Two short
observations per variant with between-pair drift and uncontrolled warm cache/
background apps do not establish tails, thresholds, statistical significance or
broad shape/device performance. CPU is the sum of user/kernel time for all CLI
process threads, measured after the completed wait through
[GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes).
It is not function-level attribution, and raw CPU values show quantization.
A tiny Python-child self-control verifies this measurement path before any engine
build/job; it is not an additional Chopper performance observation.

Two separate unreplicated diagnostic pairs remain visible. Plain ASCII ordered
export bypasses the changed quoted branch: baseline/candidate wall observations
are 0.37392/0.38504 seconds and process CPU 0.34375/0.35938, slightly slower for
the candidate. A 200,000-row rich partition -> probabilistic 80/20/0 -> uniform
shuffle pair produces 12 CSVs/23,977,415 bytes, with wall 0.77796/0.72761 and CPU
0.59375/0.57813 seconds. Neither pair establishes a speedup or regression, and
neither is pooled with the quoted primary comparison or earlier cap/shape panels.

All eight jobs independently verify actual fields, unique IDs, group/lineage,
strict caps, inventory and cleanup. Per-cohort raw CSV hash maps, output records
and 17 logical Analysis fields match exactly. Both ordered fixtures also match
input bytes. The pipeline snapshots retain eight sort runs, four merges and equal
logical temporary reads/writes. Returned Analysis workspace peaks are
202,485/202,491 bytes for rich ordered export and 8,182,308/8,182,317 for the
pipeline; run-path/configuration charges differ with variant-name lengths.
These diagnostics precede final publication and do not measure complete-Run I/O,
physical device traffic or RSS.

Fresh Linux formatting, all-target Clippy, full workspace tests and portable-core
WASM check pass 4/4 gates. Nine independent literal-byte cases cover the escape
variants, empty/NUL/multiline/Unicode boundaries and admitted denial/retry.
Existing serialization contracts cover supported output encodings,
unrepresentable text, growth/shared-pressure edges, strict caps and cleanup.
The native batch passes 6/6 gates: exact baseline reuse, CPU self-control, fixture
construction, one fresh default candidate build, eight-job panel and verification.
The original baseline's 329 file hashes, 81 directory tokens, exact file-set and
artifact identity are rechecked; baseline/candidate Cargo executable and build
environment identities match. All maintained Rust/vendor/native-embedded bytes
match the validated candidate; native sources add only the identical unused probe
example. Exact patch replay passes. Full exact-head platform/combined-feature/
browser CI remains the merge gate.

Actual context is Windows 11 build 26200, Ryzen 7 5800X (8 cores/16 logical CPUs),
NTFS and Rust 1.99.1. Raw outputs, immutable source snapshots, full logs/status,
plans, hardware/toolchain and binary identities remain under private
`scratch/quoted-serialization-20261105T0830/` in both checkouts. One candidate
build/eight engine jobs are consumed without failures, retries, component scans
or matrix expansion; no own Linux build ran during native timing. Browser speed,
other quoted distributions/encodings and scale/RSS effects remain unmeasured.
