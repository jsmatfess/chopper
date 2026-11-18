## Windows whole-device I/O diagnostic follow-up (2026-10-20)

Decision: determine whether the target volume exposes device-level byte counters
that can supplement the earlier cached process/logical traffic measurements.
Retain the same pinned feature-off and exact shuffle/partition binaries; run only
the 300,000-row external and 1,400,000-row hierarchical fixtures, three matched
pairs each. Stop on the first parity, cleanup, provider-status or counter-reset
failure. No Rust builds/tests ran during this measurement window; host activity
outside Chopper remains uncontrolled. No cache eviction, forced flush or system
policy change was performed.

The [raw pass](../../evidence-originals.md#sha256-7e49e44407c5613d6a7e3f638f486ccde8bd480337eb2425dc27e995777c525b "Original: docs/benchmarks/windows-shuffle-partition-device-io-2026-10-20.jsonl")
contains environment line 1, external fixture line 2/jobs 3-8/summary 9 and
hierarchical fixture line 10/jobs 11-16/summary 17. Each side has three complete
CLI observations, alternating baseline/candidate, candidate/baseline,
baseline/candidate. Time runs from CLI spawn through wait, including preparation,
execution and publication; generation, verification, device-control waits and
cleanup are outside that clock. The directory sampler remains active through
the post-job drain; its logical-size peak is a lower bound with a different
time window from CLI elapsed. Keep this pass separate from prior timing cells.

| Cell | Baseline median [min-max], seconds | Fusion median [min-max], seconds | Median time reduction |
| --- | --- | --- | --- |
| external | 1.2116 [1.1795-1.2295] | 0.8270 [0.8190-0.8292] | 31.7% |
| hierarchical | 6.2802 [6.2702-7.2344] | 4.5376 [4.4312-4.5844] | 27.7% |

Reduction is `100 * (1 - candidate median / baseline median)`. These elapsed
observations preserve the earlier candidate's complete-job benefit under this
harness; ranges are observed min/max, not confidence intervals. They do not
measure a new engine build: explicit build evidence pins both binary hashes,
feature/source identities and the original artifact hash/location. The current
resource-accounting changes are not included in those retained binaries.

The helper resolves the work directory's C: volume to physical disk 0 with
`IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS`, then reads raw PDH
`PhysicalDisk(0 C:)` read/write byte counters. It validates raw status, type
272696576, timestamps and monotonic byte counts. These are whole-device stack
counts including every process, paging, metadata and delayed writes; they are
neither process attribution nor NAND traffic. See Microsoft's
[raw counter structure](https://learn.microsoft.com/en-us/windows/win32/api/pdh/ns-pdh-pdh_raw_counter)
and [physical-disk counter definitions](https://learn.microsoft.com/en-us/previous-versions/aa394308(v=vs.85)).

The table retains each job's raw device-window deltas in bytes. B/C labels are
baseline/candidate, with repetition number; `clean` means only that the original
numeric noise gates passed, not that device attribution is established.

| Raw line / cell / job | Device read bytes | Device write bytes | Original flags |
| --- | ---: | ---: | --- |
| 3 / external / B1 | 0 | 61,390,848 | read zero; write drain |
| 4 / external / C1 | 34,816 | 26,945,536 | read pre-idle |
| 5 / external / C2 | 619,520 | 34,545,664 | read pre-idle/drain |
| 6 / external / B2 | 8,192 | 26,914,816 | read pre-idle/post-idle |
| 7 / external / B3 | 32,768 | 103,284,736 | read pre-idle/drain |
| 8 / external / C3 | 0 | 26,681,344 | read zero |
| 11 / hierarchical / B1 | 537,312,768 | 2,312,598,016 | clean |
| 12 / hierarchical / C1 | 1,600,000 | 823,497,216 | read drain/post-idle |
| 13 / hierarchical / C2 | 85,557,248 | 890,630,144 | clean |
| 14 / hierarchical / B2 | 266,557,440 | 1,688,019,456 | clean |
| 15 / hierarchical / B3 | 5,919,232 | 1,701,065,216 | clean |
| 16 / hierarchical / C3 | 2,019,840 | 1,625,977,344 | read/write pre-idle |

Pre/post idle and post-job drain controls each last two seconds. The declared
gate flags a zero job delta, idle rate above 10% of the job-window rate, or drain
bytes above 10% of job-window bytes, per direction; global eligibility requires
no flags in either direction. Do not subtract noise or select a cleaner direction
after the fact. External has zero gate-clean jobs; hierarchical has four, but
only repetition 2 supplies a fully gate-clean matched pair. Even passing these
gates cannot exclude activity that bursts only during the job, or delayed fixture
writeback after the pre-idle window.

A further method limitation excludes physical-effect inference for this whole
pass. Microsoft describes performance counters as diagnostic and cautions against
collection more often than once per second
([collection guidance](https://learn.microsoft.com/en-us/windows/win32/perfctrs/about-performance-counters)).
The measured harness collected adjacent window boundaries and some external CLI
windows lasted less than one second. Fine `perf_counter` timestamps do not prove
equally fine provider resolution. Preserve the original numeric flags and raw
eligibility fields, but do not treat their four gate-clean survivors as validated
physical-effect samples or report a physical-I/O reduction from them.

The exact measured [PDH helper](../../benchmarks/windows-device-io-measured-2026-10-20.py)
and [harness](../../benchmarks/benchmark-windows-device-io-measured-2026-10-20.py) are
retained byte-for-byte with hashes matching environment line 1. The maintained
`scripts/windows-device-io.py` and `scripts/benchmark-windows-device-io.py` now
enforce explicit one-second collection cadence, reuse control boundaries, and
record short-CLI/device-window padding separately from CLI elapsed. Padding or
short CLI windows are excluded from physical inference. Fourteen deterministic
counter/cadence tests and three reused-build provenance tests pass; no replacement
device experiment has been run. The script snapshots document the earlier method
and are not executable entry points for the maintained harness.

All 12 jobs preserve exact CSV bytes/order, independent ID/field/group
conservation, logical stage/digest metadata, 100 MB per-file cap checks and success
cleanup; the caps do not actively split these outputs. There are no failed jobs
or restarted attempts. Raw SHA-256:
`7e49e44407c5613d6a7e3f638f486ccde8bd480337eb2425dc27e995777c525b`.
Stop this calibration here: counter availability and mapping are established,
but controlled physical-device effects, cold-cache throughput and a universal
selector remain open. No defaults are promoted.

For a separately justified future pass, first validate the maintained cadence
and use a new output path; the historical raw pass is never overwritten:

```powershell
python scripts/test-windows-device-io.py
python scripts/benchmark-windows-device-io.py --baseline scratch/windows-calibration/baseline.exe --candidate scratch/windows-calibration/candidate.exe --build-evidence docs/benchmarks/windows-shuffle-partition-native-2026-10-20.jsonl --work-dir scratch/windows-calibration --cells external hierarchical --repeats 3 --output scratch/windows-calibration/new-device-pass.jsonl
```
