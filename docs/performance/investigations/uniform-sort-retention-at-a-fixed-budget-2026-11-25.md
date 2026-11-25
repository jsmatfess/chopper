## Uniform sort retention at a fixed budget (2026-11-25)

Keep the quarter-job target for the random-key sorter. With the same 512 MiB
working budget, the three-eighths challenger retained more memory and still
produced two spill runs. The screen did not cross the resident boundary.
[Issue #29](https://github.com/jsmatfess/chopper/issues/29) ·
[Samples and receipt identities](../../benchmarks/uniform-sort-retention-screen-2026-11-25.json)

### Complete verified jobs

Three measured pairs followed one warmup per arm. The Linux CLI processed
524,291 synthetic rows (129,606,241 input bytes) through explicit Uniform
Shuffle then Balanced into eight parts. Both builds used one worker, 512 MiB
working memory and a 1 GiB managed temporary cap. The wall clock includes CLI
launch, usable publication, job cleanup and exit. Independent verification was
outside the timer. The verifier checked every row and field, exact quotas,
lineage, manifest and directory inventory, and serialized row and byte caps.
Both arms retired the temporary workspace.

| Quantity | Quarter target | Three-eighths target |
| --- | ---: | ---: |
| Wall seconds, median [min–max] | 0.927 [0.926–0.964] | 0.952 [0.932–0.953] |
| Initial spill runs / merge operations | 2 / 1 | 2 / 1 |
| Logical temporary writes, bytes | 295,388,187 | 295,388,187 |
| Logical temporary reads, bytes | 295,752,814–295,753,371 | 295,752,783–295,753,099 |
| Peak workspace reservations, MiB | 128.26 | 190.47 |
| GNU time maximum RSS, median MiB | 133.17 | 201.74 |

Baseline minus challenger elapsed time was +0.032, −0.026 and −0.025 seconds.
The predeclared screen required resident completion by the challenger, three
favorable pairs and a median paired saving of at least 0.10 seconds. It missed
all three criteria. Managed reads and writes describe logical traffic. No
physical-device I/O was measured. The measured peak reservation and RSS
describe separate scopes.

### Replay and applicability

Build the baseline from `48215e7e21e85be8bf615487c64286672c487340` using
`cargo build --release --locked -p chopper --bin chopper`. In the
[sorter constructor](../../../crates/chopper/src/storage.rs), compute the
challenger target as `ctx.memory / 8 * 3` for `SortOrder::Random(_)` and
`ctx.memory / 4` otherwise. Pass it through the existing workspace clamp.
Build with the same command and no optional features. The Rust compiler,
compiled binaries, harness and verifier identities are in the sample record.

Use the [data-movement driver](../../../scripts/benchmark-data-movement.py)
from that revision with `--case uniform-balanced-control --repeats 3`. In a
scratch source snapshot, set that recipe to 512 MiB and set
`resources.temp_bytes` to 1,073,741,824. The release stdout Analysis includes
the Run planner report. In the [verifier](../../../scripts/verify-shuffle-swarm.py),
compare the manifest Analysis to stdout with only `auto_plan` removed.
All other verification remains in force. Use `python3 -B` so imports cannot
create bytecode inside declared runner inputs. The initial attempt exited
normally and was invalidated by this input-tree change. The replay reused
the binaries, ran the same frozen recipe and passed the runner's input
checks. It supplies the figures above. The initial and replay receipts are
retained separately.

The fixture's encoded CSV size did not predict the retained rows' footprint
and growth overlap closely enough to isolate a spill reduction. This WSL2
ext4 screen with uncontrolled warm cache covers the random-key sorter.
Fisher–Yates, browser and native Windows eligibility remain open. A new
candidate needs a justified boundary where its memory use actually avoids
spills, plus independent row shapes, competing-owner, denial and cancellation
controls. The earlier [browser calibration](browser-auto-resource-calibration-2026-11-21.md)
crossed that boundary by changing the total job budget.
