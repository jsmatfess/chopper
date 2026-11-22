## Input prefetch native publication and digest overlap (2026-11-22)

This investigation isolates browser input wait, native parallel publication
with many output files, and second-pass hash overlap for counted Balanced.
Comparisons include complete Run through publication and cleanup. Independent
verification is outside each clock. The predeclared practical gate requires
at least 0.25 seconds and 5% lower median elapsed, all reversed pairs
favorable, and at most 15% more process CPU. The profiling gate for running
the digest candidate was hash CPU of at least 10% of complete elapsed.

### Browser input prefetch

[Initial browser attempts](../../benchmarks/overlap-followup-2026-11-22-browser-prefetch.jsonl) ·
[Corrected browser holdouts and rejection fallback](../../benchmarks/overlap-followup-2026-11-22-browser-controls.jsonl)

The browser already retains a synchronous 256 KiB source read-ahead window.
The prototype submits the next window as a Blob slice to the existing
storage worker while the engine consumes the current window. One shared
256 KiB slot carries the result. An offset or length mismatch uses the
existing synchronous path. A rejected speculative read also uses the
synchronous path. The extra shared slot and worker-side array buffer are
bounded prototype storage outside WASI working reservations.

| Disk-backed input and job | Synchronous Run | Prefetch Run | Median absolute saving |
| --- | ---: | ---: | ---: |
| 390.63 MiB plain streaming | 10.958 s | 9.614 s | 1.344 s |
| 390.63 MiB partition, eight keys | 10.712 s | 9.264 s | 1.448 s |
| 976.56 MiB plain streaming | 27.189 s | 23.790 s | 3.399 s |

Medians contain two reversed pairs in fresh Chromium persistent profiles.
All six pairs favor prefetch. Browser CPU was effectively flat on streaming
and comparable on partition. The larger streaming job waited roughly
5.6 cumulative seconds for synchronous source windows. The corresponding
engine-side refill metric fell to roughly 1.6 seconds with prefetch.
The OPFS destination writers and file limits are the same in both variants.

An initial partition control stopped at the verifier because the prior
driver incorrectly required globally increasing IDs across partitions.
The corrected driver checks per-key encounter order and exact membership.
The stopped attempt is excluded. The corrected panel also completes an
injected rejection of the first speculative read and verifies all output.
The tests check conservation, exact fields, strict caps, the marker and
workspace cleanup. Source files are Playwright disk-backed Files on one WSL
host. Keep one-window overlap as a benchmarked candidate. Production
integration still needs explicit browser buffer ownership and in-flight
cancellation coverage.

### Native plain publication

[Linux high file count](../../benchmarks/overlap-followup-2026-11-22-publication.jsonl) ·
[Linux larger chunks](../../benchmarks/overlap-followup-2026-11-22-publication-coarse.jsonl) ·
[Native Windows high file count](../../benchmarks/overlap-followup-2026-11-22-windows-publication.jsonl)

The existing native `experimental-plain-publication` feature runs on a
2.00 GiB snapshot Partition with 192 groups, four workers and a 256 MiB
working budget. Match builds, source and configuration except for the
publication feature. Both variants write to private output and finish
through normal atomic publication. Serial uses one measured writer slot.
The opt-in reaches four. The 2 MiB cap produces 1,152 outputs. The 16 MiB
control produces 192 from the same source.

| Host and cap | Serial median | Parallel median | Process CPU serial / parallel |
| --- | ---: | ---: | ---: |
| Linux/WSL ext4, 2 MiB | 17.783 s | 14.549 s | 10.31 / 10.93 s |
| Native Windows NTFS, 2 MiB | 17.622 s | 13.772 s | 11.71 / 12.89 s |
| Linux/WSL ext4, 16 MiB | 12.644 s | 11.117 s | 10.06 / 10.13 s |

Each cell uses two reversed rounds. Elapsed clears the practical gate in
both file-count regimes on Linux and at the measured high count on Windows.
Per-key stable order, field contents, record conservation, caps and
workspace cleanup passed. CPU and RSS are separate from managed temporary
traffic. Both OS runtimes share one physical host, and some independent
measurements overlap. The result supports continuing the existing opt-in.
Defaults and Auto thresholds have broader resource and workload contracts.

### Counted Balanced second-pass digest

[Profile gate](../../benchmarks/overlap-followup-2026-11-22-digest-profile.jsonl) ·
[Initial ordinary records](../../benchmarks/overlap-followup-2026-11-22-digest-overlap.jsonl) ·
[Isolated repeat](../../benchmarks/overlap-followup-2026-11-22-digest-isolated.jsonl) ·
[4 KiB rows](../../benchmarks/overlap-followup-2026-11-22-digest-wide.jsonl) ·
[512 KiB rows](../../benchmarks/overlap-followup-2026-11-22-digest-very-wide-retry.jsonl)

The instrumented current Linux counted Balanced build measured 1.115
seconds of thread CPU inside second-pass hash updates and finalization
out of 6.028 seconds of elapsed Run. That passed the profiling gate.
Instrumentation is kept out of timed candidate comparisons. The first
count pass already skips the singleton digest. The prior synchronous
parallel BLAKE3 rejection remains separate.

The candidate puts the existing ordered logical byte stream into two
admitted 256 KiB buffers. A single background thread owns the hasher and
returns the first buffer before the next handoff. It joins before result
publication and when an in-progress digest is dropped. A same-capacity
serial arm uses identical framing and copying, allowing the overlap
comparison to isolate the worker handoff. The ordinary production arm
uses its original 16 KiB buffering and direct update for an oversized
field. The prototype accounts for both byte buffers, estimates channel
storage, with the runtime thread stack outside those grants.

On 512-byte records, the isolated repeat reduced the median from roughly
4.00 to 3.52 seconds relative to the same-size serial buffer. Both
pairs favored overlap. Median CPU rose from 3.22 to 3.53 seconds.
The earlier overlapping-load screen also favored elapsed, with its CPU
increase at the gate to measurement precision. The 4 KiB row holdout
had one reversal against the same-buffer serial control. This disfavors
unconditional use across row shapes.

All eligible timed jobs verify exact field contents, eight consecutive
quotas, strict serialized caps and matching logical digests. A focused
prototype test verifies framing across buffer boundaries, releases the
admission owners on finish and early drop, and rejects an insufficient
buffer budget without retaining memory. Native direct-run tests also
passed with the experimental timing features enabled. The first 512 KiB
test stopped at the independent Python CSV field-size limit. The corrected
verifier raises its limit to the declared fixture width.

[Profile patch](../../benchmarks/overlap-followup-2026-11-22-digest-profile.patch) ·
[Digest overlap patch](../../benchmarks/overlap-followup-2026-11-22-digest-overlap.patch) ·
[Failed-attempt notes](../../benchmarks/overlap-followup-2026-11-22-attempt-notes.json)

The additional [256-byte-row holdout](../../benchmarks/overlap-followup-2026-11-22-digest-narrow.jsonl)
and the corrected 512 KiB holdout failed the complete-job threshold against
the same-size serial buffer. Very-wide rows also incurred extra CPU. Those
records cross the larger buffer size and lose the original arm's no-copy
large-update behavior. Preserve the experiment patch and the 512-byte
positive result. Reject enabling this implementation across counted Balanced
jobs. Future work would need an independently verified selector and a
candidate that preserves admission for all thread, channel and buffer owners.

### Coverage and replay

Browser tests use the normal Run adapter with substituted experimental
worker modules. Native matches use one source snapshot, pinned binaries and
explicit feature flags. The Windows data is native NTFS and the Linux data
is WSL ext4. Measurements cover synthetic fixtures on one host. Source
sizing, prefetch and buffer wait telemetry are logical operation timings.
Sampled browser RSS includes shared pages and moved independently of the
fixed slot size. Native process CPU and RSS, engine reservations and logical
temporary traffic remain separate metrics. These runs do not establish
physical device throughput.

```sh
mkdir -p scratch/read-screen scratch/read-controls
node scripts/benchmark-auto-multigib.mjs source-prefetch ui/dist scratch/read-screen
node scripts/benchmark-auto-multigib.mjs source-prefetch-controls ui/dist scratch/read-controls
python3 scripts/benchmark-auto-contention.py publication scratch/publication SERIAL --writers-binary PARALLEL
python3 scripts/benchmark-auto-contention.py digest scratch/digest SERIAL --writers-binary OVERLAP --overlap-digest
```

Use builds with `experimental-counted-balanced` for both native controls,
add `experimental-plain-publication` for the parallel publication arm, and
apply the preserved patch in a disposable build for the digest challenger.
Use the revision-checked Windows dispatcher for the same publication
command on NTFS.
