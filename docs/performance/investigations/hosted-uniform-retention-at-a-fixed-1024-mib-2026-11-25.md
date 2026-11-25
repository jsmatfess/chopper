## Hosted Uniform retention at a fixed 1024 MiB (2026-11-25)

At a fixed 1024 MiB Job request, a 384 MiB retained-row target kept the
800,000-row standalone Uniform fixture resident. The ordinary 256 MiB
target made two spill runs and one merge. The measured saving was 7.708
seconds at the paired median through usable OPFS export. [Issue #29](https://github.com/jsmatfess/chopper/issues/29) ·
[Samples and receipts](../../benchmarks/hosted-uniform-fixed-1024-retention-summary-2026-11-25.json)

### Complete Runs

The two feature-free WASM builds used the same production engine and storage
worker scripts, bundled headless Chromium, one processing worker and an
unchanged 1,024 MiB request. The input is the 199,888,905-byte
`shuffle-large` fixture from the browser calibration. All attempts used a
new Chromium context and same-origin OPFS destination on the same WSL host.
One warmup per build preceded the three alternating measured pairs. The
clock starts at Run and stops after the completed export and workspace
cleanup. Input selection, independent verification and disposal of the
saved output are outside the clock. [Fixture and harness](browser-auto-resource-calibration-2026-11-21.md)

| Pair order | 256 MiB target, seconds | 384 MiB target, seconds | Seconds saved |
| --- | ---: | ---: | ---: |
| Ordinary then larger | 14.772 | 7.108 | 7.664 |
| Larger then ordinary | 15.046 | 7.105 | 7.941 |
| Ordinary then larger | 14.799 | 7.091 | 7.708 |

Each measured and warmup Run verified all 800,000 exact rows and fields,
a shuffled order, 48 CSVs under the strict 4 MiB cap, the manifest's file
inventory and empty lineage, the completion marker and workspace cleanup.
The challenger passes all three paired and residency checks and the frozen
1.5-second median savings gate.

Peak working reservations rose from 268,703,172 to 298,954,120 bytes.
Logical temporary reads fell from 255,088,890 bytes to zero. Logical
temporary writes fell from 454,984,352 to 199,895,462 bytes. The OPFS
workspace peaked at about 455 MB and 200 MB respectively. These counters
describe recorded engine ownership and workspace traffic. Host cache was
uncontrolled. The cohort covers one hosted engine build and input shape.

### Decision and replay

The fixed-budget crossing warrants testing a bounded leading-sorter path
against the current quarter-job target. The screen changes every
`SortOrder::Random` retained target in the experiment binary. Grouped inputs,
competing grants, wide fields and cancellation need separate checks before a
product selection. Explicit Fisher–Yates uses a separate resident owner.
The native fixed-budget case retained spills and remains a separate result.
[Native screen](uniform-sort-retention-at-a-fixed-budget-2026-11-25.md)

Build both feature-free WASI snapshots from
`e0fe0320a2a2da03c67be890ed35988f111e81ef`. Apply the [scratch patch](../../benchmarks/hosted-uniform-retention-three-eighths-2026-11-25.patch)
to the challenger and build through `node scripts/build-browser.mjs`. Use
the same production worker bundle in both arms and serve each WASM in a
fresh context. The [calibration harness](../../../scripts/benchmark-browser-auto-resources.mjs)
supplies the `shuffle-large` CSV recipe, Run clock and independent CSV
verification. Restrict its primary panel to this fixture and the two
fixed-budget build arms, use one worker and alternate WASM identity after
one warmup per build. Reopen the actual OPFS manifest, every capped CSV
and the marker, then check the workspace and dispose of the owned output.
The sample record pins the adapted driver and raw receipts.

### Separate Fisher–Yates capacity control

A feature-free Linux control uses 72 rows with a 131,000-byte payload
per row, an explicit 32 MiB Job, one worker and a strict 1 MiB CSV cap.
At the same 16 MiB shared ceiling, the 8 MiB resident target rejects the
Job and a 12 MiB target completes the requested Fisher–Yates algorithm.
The completed run verifies all IDs and fields across nine CSVs with
zero sort spills. Both variants return shared denial at an 8 MiB shared
ceiling. All four cases clean up their temporary and destination owners.
[Capacity and cleanup receipts](../../benchmarks/fisher-yates-fixed-budget-control-2026-11-25.json)

Use the same native source base. Apply the separate [Fisher–Yates patch](../../benchmarks/fisher-yates-three-eighths-2026-11-25.patch)
to the experimental arm. Generate `id,payload` followed by IDs 0 through
71 and 131,000 `x` bytes per row. Run an explicit `fisher_yates` Job with
`max_record_bytes` 524288, `max_files` 16 and the stated byte cap.
Repeat both variants at `CHOPPER_MEMORY_LIMIT_MB=16` and 8.
This establishes a capacity crossing for the resident-only algorithm.
It supplies no elapsed saving and leaves the explicit Fisher–Yates
contract at its current quarter-job target.
