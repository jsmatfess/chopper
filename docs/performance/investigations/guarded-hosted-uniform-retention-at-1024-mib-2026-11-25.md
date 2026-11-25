## Guarded hosted Uniform retention at 1024 MiB (2026-11-25)

A 320 MiB target for the initial sorter kept the 800,000-row hosted
standalone Uniform fixture resident at the same 1024 MiB Run budget.
It saved 7.643 seconds at the paired median through a verified export.
The [first fixed-budget screen](hosted-uniform-retention-at-a-fixed-1024-mib-2026-11-25.md)
used a broader 384 MiB target. [Issue #29](https://github.com/jsmatfess/chopper/issues/29) ·
[Samples and receipts](../../benchmarks/hosted-uniform-retention-guard-320-summary-2026-11-25.json)

### Scope and observed savings

The guard applies to the leading sorter for a WASI Run with one explicit
Uniform shuffle, a 1024 MiB request, Auto grouping, plain UTF-8 source
and output, and a record allowance of at most 8 MiB. A calculated
pipeline uses its normal intake path. Source signature classification
uses the engine's existing check. The sorter observes at least 448 MiB
of current working headroom before selecting 320 MiB. All real
allocations still require admission. The first actual spill returns
the sorter to the ordinary ceiling for subsequent runs.

| Pair | Ordinary, seconds | Guarded, seconds | Seconds saved |
| --- | ---: | ---: | ---: |
| 1 | 14.657 | 7.014 | 7.643 |
| 2 | 14.676 | 6.998 | 7.678 |
| 3 | 14.676 | 7.094 | 7.582 |

Both arms use the same verified 199,888,905-byte fixture, bundled
Chromium, OPFS, 4 MiB CSV caps and one worker. The clock covers Run
through usable output and workspace cleanup. Warmups and independent
export verification are recorded separately. The ordinary sorter made
two spill runs and merged once. The guarded sorter did neither.

### Controls and delivery boundary

The 1.1 million row holdout contains a late field with 1.5 MiB of quotes.
Both builds spill and merge, verify all fields and respect the cap.
The two reversed timing pairs show 0.010 seconds saved and 0.164 seconds
added. The median cost is 0.077 seconds, below the frozen 0.6-second gate.
A 400,000-row resident case also verified in both arms. The guarded
worker rejected its wide row below the required serialized cap, with
no completion marker or owned output left behind. A cancellation after
dispatch retired a live workspace and a same-page Run then completed.

With an admitted competing reservation, 469,762,047 bytes of available
capacity selected the existing 256 MiB target. At 469,762,048 bytes it
selected 320 MiB. A forced real spill restored 256 MiB in both cases
and the test verified every row and released all owners. The initial
test fixture omitted the explicit `/tmp` used by hosted Run; its default
path lookup failed before the guard was reached. The corrected fixture
and earlier failure have separate identities. These shared cases inject
a competitor into one WASI ledger. The observed UI starts a fresh
worker for each Run.

The result supports this narrow path. Automatic budgets, grouped
sorters, native jobs and explicit Fisher–Yates keep their ordinary
retention rules. The tracked workspace and logical OPFS metrics have
separate scopes from renderer memory and physical storage.

### Replay

Build feature-free WASI from `e0fe0320a2a2da03c67be890ed35988f111e81ef`.
Apply the [guard patch](../../benchmarks/hosted-uniform-retention-guard-320-2026-11-25.patch)
to the challenger. Use matching worker assets and the browser calibration
recipe for the same explicit 1024 MiB Job. For the external holdout,
generate 1,100,000 rows using that recipe and replace the payload at
zero-based ID 1,099,993 with 1,572,864 double quotes, escaped in one
quoted CSV field. Verify the original field contents by ID, the exact
manifest and all encoded caps outside the timer. Apply the
[resource control patch](../../benchmarks/hosted-uniform-retention-guard-contract-2026-11-25.patch)
to a separate checkout of the same base to replay the shared edges
with the standard resource-contract WASI build and browser driver.
