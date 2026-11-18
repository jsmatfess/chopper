## E5 bounded native automatic-memory panel (2026-10-28)

The delivered headroom rule does not justify omitted-memory promotion on this
panel. Keep automatic memory opt-in and omitted memory at 256 MiB. This resolves
only the native memory-rule comparison, not broader Auto strategy selection,
workers, browser performance or default-policy acceptance.

The [harness](../../../scripts/benchmark-e5-memory.py) freezes six shapes, three
repetitions per variant, one worker, seeded uniform shuffle where applicable,
strict 256 KiB/2,000-row caps, 60 seconds per job and a 600-second batch ceiling.
The scheduling estimate was 120 seconds and 512 MiB retained disk. No optional
profile or new strategy selector runs. Timing includes CLI startup through
publication and exit; fixture generation and verification are excluded. Native
Win32 counters cover CPU, peak working set and process transfers, not physical
SSD I/O. Windows filesystem cache is warm/uncontrolled. The retained default
release binary is SHA256
`5d317c632c2e2d398cfa831a30696808ef6eb81c04af62064e9d6dae92d410b2`;
[source identities](../../evidence-originals.md#sha256-87e03cf86d8788b01818913f2c9d3a02b7e98e4d6a1474f2cc3d5e4b54fa7904 "Original: docs/benchmarks/e5-memory-source-identities-2026-10-28.json")
include the dirty build inputs and vendor provenance from its frozen build.

The [complete r2 panel](../../evidence-originals.md#sha256-f765b0e1acfc5f857315e7daaa5266a9e67c4f8b25bf3bd30052b6247984d7c2 "Original: docs/benchmarks/e5-memory-native-2026-10-28-r2.jsonl")
alternates numeric 256 MiB and automatic memory, with identical shared ceilings.
Each successful job checks every field/unique ID, exact CSV bytes and output
records across budgets/repeats, logical digest, encoded caps and temporary cleanup.
The fixed held-out skew and late-wide fixtures were not used to tune the rule.

Median seconds, with three samples per variant (ranges in the raw summaries):

| Shape | Numeric 256 MiB | Automatic | Shared ceiling |
| --- | ---: | ---: | ---: |
| Small limits-only | 0.0315 | 0.0309 | 64 MiB |
| Uniform shuffle | 0.1843 | 0.1898 | 64 MiB |
| Shuffle then skewed partition | 0.0963 | 0.1012 | 64 MiB |
| Late-wide shuffle | 0.0523 | 0.0516 | 64 MiB |
| Low-headroom shuffle | 0.1120 | 0.1367 | 16 MiB |

Automatic memory resolves to 128 MiB with the 64 MiB ceiling and 32 MiB with
16 MiB. Low-headroom median elapsed time is 22.0% higher, calculated as
`(auto / numeric - 1) * 100`; its ranges do not overlap in this small panel.
Other differences are small in absolute time and do not establish general speed
benefit. These short, single-runtime jobs do not calibrate larger-than-memory
thresholds, device effects or tails. Do not expand the matrix to rescue promotion.

At a 4 MiB ceiling, the tiny numeric job succeeds, while Auto resolves to 8 MiB
and rejects the minimum working-memory/record allowance before output. All three
controls preserve cleanup. This is conservative validation, not automatic retry
or a claim that numeric 256 MiB was physically consumed. The
[first attempt](../../evidence-originals.md#sha256-009219973d600a735d14061d6a2f0704562c965e57d09d0a85e89a2e26c9ce6f "Original: docs/benchmarks/e5-memory-native-2026-10-28.jsonl") retained all 30
successful ordinary jobs, then stopped because the harness incorrectly expected
the numeric denial control to fail. R2 corrects that expectation; the first
attempt is excluded from the comparison above, not pooled as extra repetitions.
Full command logs/configurations and outputs remain under
`.tools/e5-memory-20261028/` and `.tools/e5-memory-20261028-r2/`.
No engine source, defaults, hosted artifact or deployment changed.


### E5 worker control preparation (2026-10-28)

At control preparation the worker follow-up was unmeasured. E5 remains incomplete. The
[test-only complete-Run controls](../../../crates/chopper/src/resources/e5_worker_controls.rs)
exercise numeric 256 MiB with workers 1 and workers 0 resolving to 4. Local
controls fill the actual 128 MiB workspace using a 256 MiB aggregate pool so
shared admission cannot mask the local edge. Shared controls fill a separate
competing workspace in the frozen 64 MiB pool. Each records its exact grant,
phase and emitted row boundary. The controls check typed denial before reading,
at prepared publication, and after 65,536 direct-output rows; cancellation at
publication takes precedence. Private output/temp cleanup, surviving competitor
usage, final grant release and absence of direct replay are asserted.

The [worker harness](../../../scripts/benchmark-e5-workers.py) requires matching source
inventories, separate test/release artifacts, retained successful control logs,
test build provenance and feature-free release build proof. It reruns the exact
controls inside the existing 600-second batch before generating fixtures. A
ready flag alone cannot bypass those checks. Hashes provide local provenance,
not signatures authenticating reports from an untrusted author. Tiny synthetic
loop tests exercise scheduling and verification; they are not engine timing or
replay evidence. A real tiny subprocess checks the Win32 counter adapter.

The panel is unchanged: four recipes, three alternating W1/W0 pairs each,
24 attempted timed jobs maximum, 60 seconds per child, 600 seconds per batch and
2 GiB for all owned fixtures/output/temp/logs. No timed Chopper job or full-size
fixture was launched in this preparation. Host/storage/background attestations
and a separately authorized timed launch remain prerequisites. Retained local
plans, full validation logs, artifact hashes and controls are under
`scratch/e5-worker-controls-2026-10-28/`; the earlier tooling freeze remains
historical. These controls do not promote a worker rule, defaults or E1.


### E5 bounded native worker panel (2026-10-28)

The authorized [complete panel](../../evidence-originals.md#sha256-19689c21e7836126ea96e2477a9c282f3a69a9a6acc4b81a0514a1f83e86ba78 "Original: docs/benchmarks/e5-workers-native-2026-10-28.json")
completed all 24 attempted CLI jobs: four frozen shapes, three alternating
W1/W0 pairs per shape, no retries or resizing. Keep current worker behavior and
defaults; these overlapping ranges and mixed paired differences do not establish
generic speed advice or a new selector. Broader E5 strategy/browser calibration
and default promotion remain open.

The exact pinned D1-D4 controls reran successfully (16 scenarios) before all four
fixtures were generated. Every timed job passed unique-ID/field conservation,
partition membership, exact CSV/output-record/stage/digest parity, serialized
caps, resolved W1=1/W0=4, ownership bounds and empty private temp checks.
All non-small jobs met the sufficient 4,096-row sort-dispatch coverage gate;
external jobs each performed four sort runs and one merge. This proves eligible
parallel dispatch, not simultaneous worker utilization. The small direct-output
case remains a negative control. No failure or STOP marker occurred.

Spawn-through-exit seconds below give W1 median [min,max], then W0, with three
samples each. Paired differences are W0 minus W1 seconds in repetition order:

- Small: 0.02873 [0.02686,0.22470]; 0.02882 [0.02715,0.02924].
  Differences: -0.19755, +0.00196, +0.00050. The slow first W1 sample is retained.
- External: 1.94116 [1.92323,1.97509]; 1.90205 [1.87242,1.93280].
  Differences: +0.00957, -0.03910, -0.10267.
- Skew: 0.73249 [0.71971,0.78998]; 0.72245 [0.65441,0.72738].
  Differences: +0.00767, -0.06753, -0.07808.
- Late-wide: 0.21221 [0.20676,0.21237]; 0.20503 [0.20470,0.22047].
  Differences: -0.00206, -0.00718, +0.00810.

Median CPU seconds W1/W0 were small 0.015625/0.015625, external
1.40625/1.484375, skew 0.500000/0.546875 and late-wide 0.125000/0.109375.
Peak workspace reservations matched across variants within each shape:
201,975; 51,386,243; 49,580,472; 24,439,310 bytes respectively. External peak
working-set ranges were 66,027,520-66,412,544 bytes W1 and
66,154,496-66,428,928 W0. Reservations are working-allocation accounting,
not RSS; native thread/runtime capacity is not completely charged. All raw CPU,
working-set/pagefile, process-transfer and logical-temp counters remain separate
in the artifact. Process transfers do not measure physical device I/O.

Fresh attestations identify Windows 11 Pro 10.0.26200, Ryzen AI 9 HX 370,
24 available logical CPUs, C: NTFS on disk 0 NVMe MTFDKBA1T0QFM-1BD1AABGB,
and 475 GB free. Chrome, Node and T3 processes remained present; cache was
uncontrolled and the machine is not claimed idle. Parent suspended concurrent
builds/tests/experiments. One host and three repetitions do not establish tails,
device throughput or browser performance. Generation and verification consume
the 600-second batch budget outside the CLI clock; each child retained its
60-second ceiling. The retained owned tree was 708,863,970 bytes at capture,
below 2 GiB; sampled guards are not a filesystem quota.

Release SHA256 is
`50073aa9484f86c842e51df0918a27d401a0f969fde4f3e2cd9d7a64e0c4510f`;
worker harness SHA256 is
`c13a2a33eb397695e263aef2333946c716adcc5a8af4052c0aae3581d4b6dba8`.
The artifact embeds the complete matching source/vendor map, feature-free build
proof, separate control artifact identity, fresh attestations, frozen schedule,
fixture/config hashes, every Analysis/outcome/verification and raw-file hashes.
Full fixtures, outputs, configs, commands and stdout/stderr remain under
`scratch/e5-worker-panel-2026-10-28-launch1/`; launch logs are
`panel-stdout.log` and `panel-stderr.log`, with per-attempt logs in `run/`.
No historical observations are pooled, discarded or relabeled. No Rust/hosted
rebuild, default promotion, E1 change, commit, PR or deployment accompanies this
interpretation. Next resolve the strategy rule's predecision observables and
cost hypothesis from the policy reconciliation before any new calibration;
browser calibration remains separately scoped.

### Public E5 worker derivative location (2026-10-28)

The existing E5 worker panel now has a separately reviewed
[public derivative v1](../../history/retired-evidence-site.md#preserved-evidence)
(449,406 bytes; SHA-256 `579eb79f0841daec1bb90d7a229292f5ed6576691aa0e2bb9da24d62a4783179`).
This is another location for the same panel, not a new study or additional samples.
Only 179 string fields and four tool-path dictionary labels change to reviewed
CHECKOUT/CARGO_HOME/MSVC_TOOLCHAIN root aliases. All 2,809 nonstring scalars,
24 measured jobs, 16 untimed controls, mixed timings and startup outlier remain.
The raw original stays byte-identical locally and private in R2 (455,210 bytes;
SHA-256 `19689c21e7836126ea96e2477a9c282f3a69a9a6acc4b81a0514a1f83e86ba78`).
The [reader manifest and build instructions](../../history/retired-evidence-site.md)
retain the raw relationship, private locator, transformation recipe and public
hydration identity. Hardware/software context remains intentionally public;
historical source mismatches and missing replay inputs remain unresolved.
No numerical synthesis or corpus provenance changes, no general worker speedup
claim and no new benchmarks accompany publication. Public readback verified all
four downloads; logs/receipt and clean public-only build proof remain in
`scratch/pages-e5-derivative-20261028`.
