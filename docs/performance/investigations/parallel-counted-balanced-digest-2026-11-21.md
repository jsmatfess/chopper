## Parallel counted Balanced digest (2026-11-21)

The synchronous parallel BLAKE3 prototype was slower in every measured pair.
It was removed. Three BLAKE3 compression routines accounted for 44.59% of
sampled user CPU in a separate one-worker 2 GiB run, approximately 2.04
seconds out of 4.57 seconds of user CPU. This identifies work inside Chopper’s
logical content digest. It does not estimate the elapsed cost of removing
the digest or explain the entire 8 GiB cross-tool gap.
[Current cross-tool comparison](current-balanced-cross-tool-at-8-gib-2026-11-21.md)

The candidate enlarged the admitted logical-digest buffer from 16 to 256 KiB
on the native counted singleton Balanced path with at least four configured
workers. Both passes synchronously submitted flushes of at least 128 KiB to
BLAKE3 1.8.7's parallel update in the existing job pool. Smaller tails and
oversized individual writes used serial updates.

| Measurement | Serial median [range] | Candidate median [range] |
| --- | ---: | ---: |
| Complete elapsed | 7.083 [6.982–7.483] s | 9.237 [9.036–10.440] s |
| Process CPU, user plus system | 6.28 [6.26–6.35] s | 13.81 [13.68–13.85] s |
| Accounted peak workspace | 207,445 bytes | 453,225 bytes |
| Peak process RSS | 5,860 KiB | 6,048 KiB |

The bundled changes increased median elapsed by 30.41% and median process CPU
by 119.90%. Median system CPU rose from 1.70 to 7.49 seconds. This experiment
does not separate pool scheduling, BLAKE3 task work and the buffer size change.
Managed temporary writes stayed at 1,496 bytes, and managed reads stayed at
zero. Both cgroups reached the 1 GiB cap including file cache.

The matched one-flag builds each used four workers, a 256 MiB engine setting,
and a 1 GiB WSL2/ext4 cgroup with swap disabled. Each measured job consumed the
same 2 GiB fixture and published eight exact parts with a 300 MiB serialized
cap. All output fields, quotas, order, digest parity and cleanup passed. The
small preflight and full-size warmup are excluded from the three alternating
pairs. The frozen rule required at least 5% lower median elapsed, all pairs
favorable, at most 15% more CPU and at most 1 MiB additional workspace. Only
the workspace rule passed. [Paired samples and exact build identities](../../benchmarks/parallel-counted-balanced-digest-summary-2026-11-21.json)
