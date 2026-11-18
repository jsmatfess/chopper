## Validated compact-field traversal (2026-11-05)

**Decision: remove repeated UTF-8 validation while traversing already-validated
immutable packed fields; retain a narrow favorable complete-job comparison.**
The [raw record](../../evidence-originals.md#sha256-4e3867b38e8f9ee4eeaf9bec46b3348c402a929c424ad3516f62fcbd3dec26ef),
[implementation patch](../../benchmarks/validated-compact-fields-2026-11-05.patch) and
[native harness](../../benchmarks/validated-compact-fields-2026-11-05.py) follow the
[rejected copied-batch parser](../../performance.md#bounded-parallel-csv-parsing-with-copied-handoff-2026-11-05).
Only `CompactFields::next` and packed `FieldViews::next` switch to documented
`from_utf8_unchecked` conversions. Every CSV/spool UTF-8 check, framing/bounds
check, error placement, storage representation and reservation remains in place.
There is no execution graph/retry, worker, feature, default or Auto policy change.

The [constructor invariant](../../resource-policy-research.md#validated-packed-field-traversal-2026-11-05)
is essential: private buffers come from valid Rust strings, the strict CSV parser
or the checked spool decoder. Recycled CompactRecord storage is cleared, failed
construction exposes no unchecked fields and immutable views prevent mutation.
The optimization is not permission to trust arbitrary input/spool bytes.

Four fresh native Windows CLI Runs compare the stronger serial baseline with the
candidate on one million probe-v1 ASCII records: partition -> probabilistic
80/20/0 allocation -> uniform shuffle. The schedule is baseline/candidate/
candidate/baseline, with matching four workers, 32-MiB job/process limits,
1-MiB record limit, 1-GiB temporary ceiling and 1,000,000-row/128-MiB strict output
caps. These larger output chunks were declared before execution to reduce small
file publication cost; this workload is not pooled with earlier 200,000-row,
1,024-row-cap panels. Each Run emits 12 CSVs totaling 94,777,051 bytes.

| Pipeline | Observations | Median seconds | Range seconds |
| --- | ---: | ---: | ---: |
| Revalidate packed views | 2 | 2.91073 | 2.74652–3.07494 |
| Traverse validated fields | 2 | 2.75433 | 2.71602–2.79264 |

Candidate-minus-baseline opposite-order differences are -0.28230 and -0.03051
seconds; the candidate median is 5.37% lower relative to baseline. The ranges
overlap and the pair differences vary substantially. Two observations per variant
with uncontrolled warm cache/background apps do not establish statistical
significance, tails, thresholds or broad shape/device performance. A separate
ordered-export pair uses the same million-record fixture and caps. This path uses
owned fields, so the changed packed iterator is not called. Its 0.37769/0.37225
seconds are an unreplicated negative-control diagnostic, not a packed-reader gain.
All six durations include CLI startup through complete Run/publication, Analysis
JSON and process exit; fixture/hash/independent verification are outside the clock.

All six jobs independently verify actual fields, unique IDs, group/lineage,
strict row/byte caps, inventory and cleanup. Per-recipe raw CSV hash maps, output
records and 17 logical Analysis fields match exactly; ordered CSV bytes also equal
the input. Both pipeline variants report 36 sort runs, eight merges and matching
logical temporary traffic. Returned Analysis workspace peaks are 7,461,131 versus
7,461,140 bytes; run-path/configuration reservations differ because `candidate`
is longer than `baseline`. The code adds no buffer or grant. These diagnostics
precede final publication and do not measure complete-Run I/O or process RSS.

Fresh Linux formatting, all-target Clippy, full workspace tests and portable-core
WASM check pass 4/4 gates. Existing contracts cover malformed UTF-8/spool framing,
all framed-row truncations, checked wide-buffer reuse, admission denial,
transcoding, strict parser refill limits and cancellation/cleanup. A new core
regression exercises cloned partial iterators, dirty recycled storage, Unicode
scalar boundaries, refill sizes 1/2/3/7/65,536 and a valid field followed by invalid
UTF-8. The native batch passes 4/4 gates: exact baseline reuse, one fresh default
candidate build, six-job panel and verification. All maintained Rust/vendor/native
embedded bytes match the validated candidate. Native sources add only the
identical unused prior probe example. Exact patch replay passes. Exact-head CI
still gates native platforms, combined features and hosted/browser acceptance.

The baseline binary is the retained stronger serial CLI, reused only after its
original 328 file hashes, 81 directory tokens, exact source file-set and artifact
identity are rechecked; no old timing is reused. Native Windows 11 build 26200,
Ryzen 7 5800X (8 cores/16 logical CPUs), NTFS, Rust 1.99.1 and full source/toolchain/
artifact identities are recorded. Raw jobs, output, logs and immutable source
snapshots remain under private `scratch/compact-utf8-20261105T0814/` in both
checkouts. The one-build/six-job caps are consumed, with no failures, repeats,
component scans or matrix expansion. No own Linux build ran during native timing.
Unicode/wide shape timings, scale generalization and RSS remain unmeasured.
