## WASI Run Job handoff cost (2026-11-25)

The WASI Run decoder transfers the retained Job charge to PreparedJob.
The direct and retained paths charge the full local capacity and only the
new seed in the shared pool. Auto sizing credits its own existing charge.
The resource controls verify fifteen local and shared boundaries, including
transactional rollback and denial of a transfer to a different pool.
[Issue #79](https://github.com/jsmatfess/chopper/issues/79) ·
[Decoder and handoff](../../cli-job-decoding.md#wasi-run)

| Complete hosted Run | Baseline median, seconds | Handoff median, seconds | Paired median added, seconds |
| --- | ---: | ---: | ---: |
| Two rows, compact Job | 0.0768 | 0.0853 | +0.0085 |
| Two rows, near-1 MiB Job | 0.1415 | 0.1557 | +0.0142 |
| 800,000-row guarded Uniform Shuffle | 7.0572 | 6.9731 | -0.0874 |

Both two-row configurations pass the frozen 0.030 and 0.050 second gates.
The near-limit Job occupies 1,034,770 wire bytes and both decoders use 128
buffered source reads. A separate 1,051,185-byte virtual Job also runs and
produces the same capped fields. Malformed and strict-cap failure behavior
matches. The two retained shuffle builds stay resident with zero spills
and merges and both verify all 800,000 rows, the 4 MiB file caps, manifest,
completion marker and retirement. The shuffle comparison passes the
0.350-second paired median and 0.800-second individual limits.
[Matched samples and identities](../../benchmarks/wasi-run-job-handoff-timing-2026-11-25.json) ·
[Prior guarded shuffle](guarded-hosted-uniform-retention-at-1024-mib-2026-11-25.md)

The clocks cover each Run through usable publication and session retirement.
The cohorts use one warmup per build and three alternating pairs. Independent
field, inventory, cap, manifest and marker checks run outside the clock.
Both builds use the same production workers, disposable OPFS storage and
bundled Chromium 156.0.8078.4 on WSL Linux. Host cache state
is uncontrolled. The baseline and challenger source commits and asset hashes
are recorded in the summary.

The retained WASI contract resolves 2048 MiB with only its own Job charge,
256 MiB with a live one-byte competing grant, and 1024 MiB on explicit request.
The actual allocation ledger counts the competing owner throughout.
A feature-only test invokes the prior buffered decoder to check diagnostic
text, its exact position and the full read trace on a source failure. The early
virtual direct-Run fixture lacked the worker's /tmp setting and trapped.
The revised fixture supplies it and both virtual boundary cases pass.
