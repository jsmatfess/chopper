## Native Windows SSD shuffle/partition calibration (2026-10-20)

Decision: test whether exact shuffle/partition pass elimination benefits complete
native Windows jobs on the target SSD. Compare matching release builds with no
features versus only `experimental-shuffle-partition`, retaining `seeded_v1`.
Stop after three alternating pairs per cell or the first correctness/cleanup
failure. This bounded experiment does not reopen bucket/RNG variants or rerun
the historical full matrix, and does not authorize default promotion.

The [raw pass](../../evidence-originals.md#sha256-b484ffd6976ed1b34e49d82c62b3f9b4fc3a79a432682cb5169ebd62f7b96f62 "Original: docs/benchmarks/windows-shuffle-partition-native-2026-10-20.jsonl")
contains 30 complete CLI jobs, five fixture records and five derived summaries.
Each cell has three observations per build. Order is baseline/candidate,
candidate/baseline, baseline/candidate. Time includes startup, preparation,
execution and atomic publication; generation, independent verification and
cleanup are outside the clock. Ranges are observed min/max, not confidence
intervals. These are within-Windows comparisons, not comparisons to WSL timings.

| Cell / raw measurement lines | Rows / partition key | Baseline median [min–max], seconds | Fusion median [min–max], seconds | Median time reduction |
| --- | --- | --- | --- | --- |
| resident / 3–8 | 3,000 / `c0` | 0.0417 [0.0403–0.0438] | 0.0379 [0.0365–0.0392] | 9.1% |
| external / 11–16 | 300,000 / `c0` | 1.1920 [1.1793–1.1950] | 0.8294 [0.8154–0.8469] | 30.4% |
| hierarchical / 19–24 | 1,400,000 / `c0` | 6.4567 [6.4343–6.5704] | 4.5694 [4.5505–4.5833] | 29.2% |
| skew / 27–32 | 300,000 / payload, 90:9:1 | 1.2261 [1.2231–1.2328] | 0.8851 [0.8580–0.9027] | 27.8% |
| rare_wide / 35–40 | 300,000 / `c0`, one 1.8 MB payload | 1.2208 [1.2164–1.2313] | 0.8421 [0.8382–0.8469] | 31.0% |

Reduction is `100 * (1 - candidate median / baseline median)`. All fixtures have
33 columns and unique ordinal IDs; ordinary payloads are constant and `c0`
cycles over ten values. This brackets resident, single-merge and hierarchical
execution at one budget, without locating a precise resident/external threshold.
The tiny resident result is startup-sensitive; its 15.625 ms CPU counters are too
coarse to infer a CPU improvement.

Host: Windows 11 build 26200, AMD Ryzen AI 9 HX 370, 24 logical processors;
`MTFDKBA1T0QFM-1BD1AABGB` NVMe SSD, NTFS C: volume, about 642 GB free at setup.
Fixture, temp, staging and output share that volume under
`scratch/windows-calibration`. Cache is **warm/uncontrolled**: generation and
verification touch data, with no eviction. Other host activity, antivirus, power
policy and firmware are uncontrolled. Windows storage/CIM query results are
embedded in environment record 1. No browser/OPFS jobs were run in this pass.

Both builds use 32 MiB per job, four requested/effective workers, 2 MiB maximum
records and seed `external-comparison-v1`. The Windows shared-admission fallback
applies; no `CHOPPER_MEMORY_LIMIT_MB` override was set. Builds use Rust/Cargo
1.99.1, `x86_64-pc-windows-msvc`, locked offline release dependencies, thin LTO and
one codegen unit. Record 1 retains revision, dirty status, relevant source hashes,
binary hashes, features and both harness hashes. Unrelated checkout edits were
preserved. Fixture records retain actual SHA-256 and byte sizes. Raw pass SHA-256:
`b484ffd6976ed1b34e49d82c62b3f9b4fc3a79a432682cb5169ebd62f7b96f62`.

The following resource values are medians of those same three jobs per side;
MB means decimal MB. Independent peaks are not additive simultaneous usage.

| Metric | External baseline → fusion | Hierarchical baseline → fusion |
| --- | --- | --- |
| Process CPU seconds | 1.1875 → 0.8438 | 6.4844 → 4.6563 |
| Peak process working set, MB | 18.64 → 17.52 | 18.49 → 17.74 |
| Peak charged workspace, MB | 8.60 → 7.89 | 8.60 → 7.92 |
| Engine peak temporary bytes, MB | 214.49 → 146.12 | 1002.87 → 840.72 |
| Engine logical temporary read/write, MB | 320.37 / 346.36 → 120.19 / 146.18 | 1924.52 / 2046.61 → 982.11 / 1104.20 |
| Process read/write transfers, MB | 372.55 / 372.36 → 172.37 / 172.19 | 2169.15 / 2168.72 → 1226.73 / 1226.31 |
| Sampled temp + staging + output sizes, MB | 213.17 → 144.88 | 996.26 → 828.60 |
| Sort runs / merge operations | 17 / 1 → 19 / 1 | 77 / 2 → 86 / 2 |

Win32 `GetProcessTimes`, `GetProcessMemoryInfo` and `GetProcessIoCounters` read
the terminated process's retained counters before its handle closes. Working set
is Windows resident memory, not Linux RSS; raw data retains peak pagefile/commit
separately. Process transfers include cached I/O and are **not physical device
traffic**; engine logical I/O has another boundary. A 20 ms directory sampler
records logical file-size lower bounds, excluding source/config/logs and directory
metadata. It measures neither allocated clusters nor device I/O; its overhead is
included on both sides. No allocator census was run, so requested allocation
traffic remains unknown. Reservations do not cap total process memory. Skew's
median working set rises slightly (18.03 → 18.15 MB), and rare-wide charged
workspace rises (10.72 → 11.27 MB): speedups do not imply universal memory savings.

Every timed job independently verifies unique IDs and field text, partition
membership, row/byte metadata, exact CSV bytes/order and logical stage/digest
fingerprints across builds. A 100 MB serialized CSV cap is checked on each file;
timings do not exercise an actively splitting byte boundary. Temp and staging
cleanup is checked after every success. The
[CLI controls](../../evidence-originals.md#sha256-830e97eb503d92e5e21762e75ca6565ca6f3b234b75370ab5e137968d131a8bf "Original: docs/benchmarks/windows-shuffle-partition-controls-2026-10-20.jsonl")
pass 20 checks: leading/later parents, no header, UTF-16/BOM with active caps,
empty input, clean cap/file-count/malformed/ambiguous-header rejection, and source
replacement after preparation followed by retained-snapshot publication through
both local servers. Six focused Rust tests also pass: forced collisions/hierarchy,
downstream domains, reservation rollback, malformed input, cooperative cancellation
and injected disk-budget denial/cleanup. These are not physical disk-full,
power-loss or OS Ctrl+C acceptance tests.

The [two-job pilot](../../evidence-originals.md#sha256-d83cc7b6c2849c4f3a8912313a0ba2e8e42260e31b629be8c4c4c193d62df42f "Original: docs/benchmarks/windows-shuffle-partition-pilot-2026-10-20.jsonl")
is retained and excluded from all estimates. It validated instrumentation before
the final harness added explicit UTF-8 output, hardware and fusion-count assertions.
Initial resident startup took 1.686/0.808 seconds; this startup/cache behavior
limits interpretation. Its historical harness hash differs from the final pass.
PowerShell UTF-16 output was transcoded to UTF-8 without changing record values.

Decision: exact shuffle/partition fusion remains a promising **opt-in** Windows
candidate. External gains survive this OS/filesystem change and two merge
operations, with lower CPU and logical traffic in these cells. Defaults remain
unchanged: one warm device, three repeats, one budget/worker count, synthetic
shapes and no physical I/O/concurrent-admission measurements cannot justify a
universal selector. Other fusions, browser storage, precise transition thresholds
and broader device coverage remain in the existing SSD-calibration TODO.

Reproduction from the repository root (PowerShell; use installed absolute paths
if Rust/Python are absent from PATH):

```powershell
New-Item -ItemType Directory -Force scratch/windows-calibration
cargo build --release --locked --offline -p chopper --bin chopper
Copy-Item target/release/chopper.exe scratch/windows-calibration/baseline.exe
cargo build --release --locked --offline -p chopper --bin chopper --features experimental-shuffle-partition
Copy-Item target/release/chopper.exe scratch/windows-calibration/candidate.exe
$env:PYTHONUTF8 = '1'
python scripts/benchmark-windows.py --baseline scratch/windows-calibration/baseline.exe --candidate scratch/windows-calibration/candidate.exe --work-dir scratch/windows-calibration --output scratch/windows-calibration/new-pass.jsonl
python scripts/validate-shuffle-partition.py --baseline scratch/windows-calibration/baseline.exe --candidate scratch/windows-calibration/candidate.exe --snapshot
cargo test --locked --offline -p chopper --lib --features experimental-shuffle-partition engine::shuffle_partition::tests -- --test-threads=1
cargo build --release --locked --offline -p chopper --bin chopper
```

The [Windows harness](../../../scripts/benchmark-windows.py) reuses fixture/verification
logic from [the external-shuffle harness](../../../scripts/benchmark-external-shuffle.py),
whose GNU-time and `/proc` measurement path cannot run natively on Windows.
`--output` refuses overwrite: choose a fresh filename. Optional `--hardware`
accepts a JSON object with `disks`, `volumes`, `physical_disks` and `cpu` arrays
from `Get-CimInstance Win32_DiskDrive`, `Get-Volume -DriveLetter C`,
`Get-PhysicalDisk` and `Get-CimInstance Win32_Processor`. Owned fixture/results
directories are removed on completion; copied binaries remain in ignored scratch.
The default release build was restored after measurement.

Windows checkout maintenance: Git `core.autocrlf=true` had converted historical
evidence to CRLF, changing catalog hashes without changing Git's content diff.
Only files whose CRLF-to-LF bytes exactly matched their HEAD blobs were restored
to those original bytes; no historical observations changed. `.gitattributes`
now disables Git text conversion for raw evidence and pins hashed Markdown to
LF. Catalog navigation writes explicit UTF-8/LF and rejects CRLF drift in
`--check`; its focused regression and existing catalog tests pass.
