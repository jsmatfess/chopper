## Counted Balanced first-pass fingerprint (2026-11-21)

Omit the first-pass content fingerprint in the opt-in native singleton
counted Balanced path. In three 8 GiB complete-job pairs this reduced
median elapsed by 14.70% and process CPU by 18.40%. Every pair improved
on both measures. [Paired samples, build identities and frozen criteria](../../benchmarks/counted-balanced-first-pass-fingerprint-summary-2026-11-21.json)

| Metric | First and second pass digest | Second pass digest |
| --- | ---: | ---: |
| Elapsed, median [range] | 44.680 [42.275–44.934] s | 38.113 [33.558–39.164] s |
| Process CPU, median [range] | 25.16 [24.91–25.40] s | 20.53 [20.44–20.62] s |
| User CPU, median | 18.79 s | 14.09 s |
| System CPU, median | 6.36 s | 6.35 s |

Skipping the first-pass fingerprint removed about 4.6 process CPU seconds
on this fixture, including digest buffering and hash work. Both strict
parser passes remain in the clock. Output bytes and logical digests were
identical in each intact-input pair. Each job wrote 1,512 managed temporary
bytes and read zero. Peak working reservations differed by 12 bytes,
median process RSS by 104 KiB, and the whole cgroups reached the same
1 GiB cap including file cache. The primary pair effects on elapsed
were 12.35%, 9.84% and 25.32% lower than their respective controls.

The builds used the same source and flags except the temporary ablation
flag. They ran in alternating order with one worker, a 256 MiB engine
setting, a hard 1 GiB WSL2/ext4 cgroup without swap and an actual
1200 MiB serialized CSV cap. The independent byte-level oracle checked
all output bytes, eight exact consecutive parts, manifest and cleanup
outside the stopwatch. Both small preflights and the full warmup pair
are excluded. The final code applies the behavior inside the existing
counted Balanced experiment and removes the temporary ablation flag.

Both passes validate strict CSV and UTF-8. The native path rejects any
second-pass row-count mismatch and still compares decoded headers, source
byte length and modification time. A same-count edit that preserves
the header and metadata can go undetected. Analysis and the manifest
hash the rows actually emitted by the second pass. Retained snapshot
execution and counted Partition followed by Balanced keep their original
proofs. Regression tests exercise both mismatch directions with restored
metadata, a permitted same-count payload edit, exact output bytes and
the published digest, and malformed quoting or invalid UTF-8 in either
pass. The applied scope inherits support for existing counted codecs.
The 8 GiB timing applies to plain input and output.
[Current execution contract](../../direct-execution.md)

[Validation receipts](../../benchmarks/counted-balanced-first-pass-fingerprint-validation-2026-11-21.json)
