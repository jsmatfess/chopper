## Complete buffered packed-row copy (2026-11-05)

Decision: The frozen primary or bypass condition fails; restore production exactly and retain the unchanged candidate without tuning. Measured outcome is unfavorable, disposition
is reject, and delivery is unapplied.
Final committed head/current main validation and actual landing remain separate
from this scientific result. The study is closed without retuning or repeats.

[Report and raw identities](../../evidence-originals.md#sha256-e0e7dd22ae8bdd5ca532d6b6887e386648e408c7ed433c6af502fa250eb5b58a),
[exact source and controls](../../benchmarks/packed-row-buffered-copy-2026-11-05.patch),
[frozen plan](../../evidence-originals.md#sha256-3d6c03305d9a101c97cf1f09eb3a2cbf5fe5d0959528cc9bd8c909b3ca160b84),
[native panel](../../benchmarks/packed-row-buffered-copy-2026-11-05-native.py),
[independent verifier](../../benchmarks/packed-row-buffered-copy-2026-11-05-verify.py),
[reuse preflight](../../benchmarks/packed-row-buffered-copy-2026-11-05-preflight.py),
[build attestation](../../evidence-originals.md#sha256-ac7c2ce689bc0314820d2ea2298893c4c85065cf836716ed30b3632eae7d9620),
[native host lock](../../benchmarks/packed-row-buffered-copy-2026-11-05-native-lock.py) and
[Linux host lock](../../evidence-originals.md#sha256-b098c1f8d4688cedc10cdbf1ddc89eefb6d1ab9e0f24779406b484de66948bbd) preserve commands,
identities and limitations. These review copies use the recorded private host
layout. The original [CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py)
and its positive control/interpreter identity are rechecked, not remeasured.

The retained current-production WSL profile named packed decode self work
(10.47%) and separately read_exact self work (3.45%). They are not added or
converted to predicted gains. Its decoder body is still token-identical at the
selection checkpoint. Reuse-capable lending cursors exist, but mixed callers and
unresolved sampled stacks do not establish their proportions or fast-path hit
rate. No new profile, component scan, shape or matrix follows from this selection.

Candidate `65e26e964f7b59e8c3bfac5b2400d80b6bab45a5` on base `7b1b82d112b027464caa995b7f37884b20357792` keeps the original count read, key/grant
handoff, buffer/descriptor admission and count append. It inspects only one
borrowed window, bounded by actual unused admitted destination capacity. Checked
lengths, cumulative payload limits and per-field UTF-8 must all pass before one
copy of complete encoded length/data bytes and one consume. Otherwise the reader
and destination remain untouched by the attempted fast path and the original
sequential decoder runs. That fallback's token sequence is unchanged. Zero fields
skip new reader I/O. No cached extent survives consume.

The owner re-audit preserves [validated packed-field construction](../../resource-policy-research.md#validated-packed-field-traversal-2026-11-05)
and [spool-key admission](../../resource-policy-research.md#fixed-size-spool-header-keys-2026-11-05):
source bytes stay immutably borrowed through validation/copy, and every copied
field remains valid before immutable packed views are exposed. Fixed little-endian
length bytes round-trip identically. Every successful prefix fits existing
capacity, so the original loop would require no per-field growth or admission
either. Initial/final reservations, variable-key boxing and all drops stay in
place. No new heap allocation, schema, serialized layout, unsafe operation,
seed/replay, graph, Run routing, cancellation or publication rule is introduced.

Controls compare full, one-byte and changing windows, including every truncated
prefix, malformed count/length/UTF-8, empty/Unicode fields, following rows, cold
and reused capacity, live competing grants and local/shared denial. They compare
fields, packed bytes, complete error chains, consumed bytes, retained capacity,
local/shared peaks and cleanup. The baseline is the retained serial fallback,
not a duplicate implementation. Exact-head/current-base Linux and native Windows
workflow checks pass before any experimental build or measurement. Superseded
precheck attempts remain explicit: advanced-main refusal, wrong native expected
revision and an actual later host-lock refusal all stopped before act/science.
The initially mistaken host-lock interpretation was corrected after raw inspection.

The panel reuses exact plain1M pipeline and plain4M ordered-export fixtures.
Their sizes/hashes, every job/config and complete source/vendor/embedded maps are
in the report. Pipeline is region partition -> probabilistic80/20/0 allocation ->
uniform child shuffle, ABBA4 primary; ordered export is a separate pair bypassing
packed spool decode. Both use seed `strict-csv-serial-v1`, four workers, 32-MiB
job/shared limits, 1-MiB record cap, 1-GiB temporary ceiling and 4096 files.
Row/CSV caps are1M/128MiB pipeline and4M/512MiB ordered. No new generator or
holdout identity is inferred from names; pinned fixture bytes are reused.

The production baseline reuses the preceding reservation candidate artifact only
after its full source identity is proved equal to current production. Its original
build status/source/compiler/environment/features/binary are retained and
rechecked; it is not relabeled with a new build commit. One fresh default native
candidate is built in an independent target root. Unrecorded backend details stay
unknown. Native and Linux OS locks exclude overlapping check/land builds during
the supported experiment cycle, and the persistent delivery flock protects the
native transaction. No lock is deleted or check bypassed.

Timing covers native CLI startup through complete Run/publication/Analysis JSON
and process exit. Fixture/hash/independent verification and post-exit Win32 CPU
queries are outside wall time. CPU sums child threads, with total/user/kernel kept
separate. Warm cache/background are uncontrolled. Diagnostics returned before
publication are not whole-Run RSS, physical I/O or capacity peaks.

| Index | Variant | Wall seconds | Total CPU seconds | User CPU seconds |
| --- | --- | ---: | ---: | ---: |
| 0 | baseline | 2.534224 | 2.125000 | 1.437500 |
| 1 | candidate | 2.560048 | 2.265625 | 1.671875 |
| 2 | candidate | 2.405181 | 2.187500 | 1.750000 |
| 3 | baseline | 2.381994 | 2.234375 | 1.609375 |
| 4 | baseline | 1.269929 | 1.156250 | 0.843750 |
| 5 | candidate | 1.296476 | 1.187500 | 0.843750 |

Rows0..3 are the primary cell, n=2 per variant; rows4/5 are the separate bypass
pair, n=1. Primary baseline/candidate wall samples are
`[2.5342244999483228, 2.381993900053203]` / `[2.560047599952668, 2.4051809000084177]`.
Median `(baseline - candidate) / baseline` reductions are
-1.00% wall,
-2.15% total CPU and
-12.31% user CPU.
The frozen rule requires both opposite-order wall/total/user pairs favorable and
at least2% median wall reduction. Primary result: fail.
Bypass candidate-minus-baseline changes are +2.09% wall,
+2.70% total CPU and +0.00% user CPU;
none may regress by more than2%. Bypass result: fail.
Kernel remains separate in the raw report. No cells are pooled or subtracted.

All six complete native jobs and six runner steps pass exact every-field/unique-ID/
group/order/strict-cap/inventory/byte/17-logical-Analysis and cleanup verification.
The source/build/Run counts and all failed/superseded setup attempts remain in
the report. Candidate builds1/1, measured Runs6/6 and component scans0 are fixed;
unused source capacity cannot reopen this decision. The preceding studies and
all frozen raw bytes remain intact. Small samples do not establish general/tail
performance, and no untested macOS or browser performance coverage is implied.

Reviewed normalized bindings select primary baseline0/3 vs candidate1/2 and
separate bypass4/5, using exact `/native/complete_jobs/*` locations and
`clock_pointer: /seconds`. Tested adapters retain CPU components and metadata
references separately. Extraction is not broader eligibility; summaries, profiles,
contract durations and runner commands are not additional speed observations.
Actual final-head/base receipts and landed SHA are recorded after authorized
delivery. This work authorizes no wizard runtime, Auto/default-policy, release,
deployment or manual hosted dispatch.
