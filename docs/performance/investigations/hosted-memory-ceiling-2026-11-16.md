## Hosted memory ceiling (2026-11-16)

Raise the hosted manual working-budget maximum from 512 to 2048 MiB, the
instance's tracked-allocation ledger from 128 MiB to 1 GiB, and the WASM linear
memory maximum from 1 to 2 GiB. Keep numeric omission at 256 MiB and automatic
selection capped at 256 MiB. This is an available manual capacity increase, not
automatic host-RAM discovery or a browser RSS guarantee. Native limits do not
change. The user authorized a higher-limit experiment and supported increases;
no additional strategy, dependency, parallel worker or addressing architecture
is introduced.

The [retained comparison receipt](../../evidence-originals.md#sha256-5668ebd49113d1b0fc41d89a527cf2339e3a62d7b434c6e16194b608b5c7dc72)
contains source-forest and WASM identities, environment/toolchains, individual
observations, verification/cleanup receipt identities, warmup exclusions, capacity
controls and boundary diagnostics. Raw logs, frozen source archives, fixtures and
original harness versions remain in local ignored `scratch/hosted-memory-20261116`.
No remote evidence upload or main delivery occurred.

### Decision and experiment

The existing [shared admission policy](shared-process-admission-and-linux-startup-discovery-2026-10-16.md)
and [explicit-budget feasibility rule](../../resource-policy-research.md#explicit-settings-and-shared-reservations)
make a larger form maximum alone ineffective. Sorters target the smaller of one
quarter of the requested budget and half shared admission. The old WASI fallback
therefore limits retained sort rows to 64 MiB even with a 512 MiB request.
Coordinated higher ceilings let a 2048 MiB request target 512 MiB of sort rows.
Local and aggregate grants, growth-overlap accounting and fallback rules remain.

The bounded [harness](../../../scripts/benchmark-hosted-memory.mjs) uses the
existing browser prepare/confirm/export driver and independent CSV/manifest
verifier. Its primary input has 1,200,003 rows, three columns and a 192-byte
payload with periodic UTF-8, quoting and embedded-newline cases. The operation
is uniform shuffle, with one worker, a 1 MiB record limit, 100,000-row and strict
4 MiB serialized CSV caps. The small control has 120,003 rows and a 64-byte
payload, with both builds requesting the unchanged 256 MiB budget.

The initial pilot screens 256/512/1024/2048 MiB once, without treating these
single observations as repeated evidence. The primary and small control each
use three alternating measured pairs after one excluded warmup per variant.
The primary contrasts the old build at its default 256 MiB against the coordinated
candidate at 2048 MiB; it does not isolate a linker change from a budget change.
The clock includes preparation, confirmation, destination export, marker close
and worker retirement. Fixture fetch, collection and verification are outside it.
Stop the cohort at correctness, cleanup, timeout or unexpected allocation failure.

### Complete-job results

Elapsed reduction is `(baseline median - candidate median) / baseline median`.
Ranges are observed minimum/maximum, not confidence intervals or tail estimates.

| Cell | Baseline median [range], seconds | Candidate median [range], seconds | Interpretation |
| --- | --- | --- | --- |
| Primary, old 256 MiB versus new 2048 MiB | 7.75116 [7.72277, 7.83068] | 6.25154 [6.14771, 6.36172] | 19.3% less elapsed time; separated ranges in this cell. |
| Small unchanged-default control, both 256 MiB | 0.39961 [0.39702, 0.40706] | 0.40371 [0.39644, 0.41765] | Candidate median 1.0% higher; overlapping ranges, no improvement claimed. |

Every measured primary baseline writes six sorted runs and performs one merge;
every larger-budget candidate retains the sort and performs no external merge.
At preparation, logical temporary traffic falls from about 326 MB read / 569 MB
written to zero read / 243 MB written. Final encoded CSV staging remains. These
are engine logical counters, not physical SSD traffic or complete-export traffic.

The primary's prepared peak tracked reservations rise from about 64.3 to
447.6 MiB. WASM linear-memory high water rises from 67.3 to 457.4 MiB. The latter
is the nonshrinking linear buffer measured at worker replies, not browser RSS;
Analysis reservation diagnostics describe preparation rather than a final
whole-job allocation census. The 2 GiB working-budget request does not preallocate
2 GiB, nor does this fixture demonstrate consuming all available memory.

The unreplicated pilot shows six, three, two and zero spill runs respectively;
1024 MiB still merges and its elapsed observation is close to the old default.
Only the repeated primary supports the quoted elapsed improvement. Increasing
memory is useful when it changes fitting/spill behavior, not a general throughput
promise for streaming or already-fitting work.

### Capacity, correctness and failure

A separate resident Fisher–Yates control uses the primary fixture. The old build
at its former 512 MiB maximum rejects the parent as exceeding resident capacity.
The candidate at 2048 MiB completes and independently verifies all rows. The
expected denial is retained with failed state, zero workspace bytes, an empty
destination and successful owned-destination cleanup. It is a capacity result,
not an elapsed baseline or a comparison between shuffle algorithms.

Verification checks exact original fields, unique IDs/conservation, header,
lineage/logical-stage metadata, group counts, file/row/encoded-byte metadata,
strict row/byte caps, completion marker and empty retired workspace. No fixed
random order is required across independently randomized jobs. Prepared
confirmation still executes the retained snapshot. Resource tests preserve
transactional denial and final-owner release. The recorded engine validation
includes native workspace Clippy/tests, portable-core WASM, real hosted
acceptance including 2048 MiB acceptance/2049 MiB rejection and retry, and both
base and shuffle-partition resource-contract variants. Final production engine
bytes match the measured candidate after restoring ordinary feature flags.

The T3 restart interrupted one process-kill acceptance attempt. Its incomplete
log stays separate; completed checks were retained, and resumed attempts have
their own logs and exit codes. An interrupted attempt is not a pass or timing
observation.

### Why stop at 2 GiB

The current browser WASI shim passes imported i32 pointers directly to
JavaScript DataView/typed-array operations. Actual WASM imports expose these
as signed numbers: above 2 GiB they become negative. A retained Node/V8 ABI
diagnostic using the pinned shim verifies that a positive JavaScript offset
works while an actual WASM clock import at that address raises RangeError.
A separate artifact diagnostic grows the actual baseline/candidate memories
to their declared 1/2 GiB limits, writes the final bytes, and verifies another
page is rejected. Neither diagnostic is browser-RSS or full-capacity engine
acceptance.

The [wasm32 address-space maximum is 4 GiB](https://v8.dev/blog/4gb-wasm-memory).
Reaching it would require unsigned normalization and an audit of affected shim
imports, paths and pointer arithmetic; a review of allocator fragmentation and
growth overlap; handling the nominal 4 GiB-to-usize conversion; and additional
browser pressure/failure qualification. Rust also limits individual contiguous
allocations to [isize::MAX bytes](https://doc.rust-lang.org/std/vec/index.html).
Beyond 4 GiB requires a different addressing architecture, such as memory64,
or independently partitioned instances with an explicit ownership/coordination
design. That exceeds this small, dependency-preserving change. The native engine
avoids the browser ABI but remains subject to its platform admission policy.

Coverage is warm WSL2/ext4 with disposable persistent bundled Chromium
156.0.8078.4. No installed Windows browser, browser RSS, physical SSD throughput,
25-million-row performance or general low-memory-device safety claim is made.
WASI still cannot discover available host RAM; users opt into larger manual
budgets and actual resource exhaustion can fail. Current limits and ownership
remain in the [resource specification](../../specification.md#resources-publication-and-interfaces)
and [browser guide](../../browser.md#processing-and-limits).
