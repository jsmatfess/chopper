## Current complete-Run CPU after buffered spool copying (2026-11-05)

Decision: investigate code-generation overhead on unchanged-size reservation
resizes next, while preserving every existing grant, call and drop. This is an
informational diagnostic outcome with unchanged delivery, not a measured speedup,
source optimization or reopening of rejected experiments.

[Report and original raw identities](../../evidence-originals.md#sha256-e8599d0d75b55a302154f048bd8e62d4f463484becb9c870721f8a4dd861878d),
[profile harness](../../evidence-originals.md#sha256-b19c24b4b5820a9b0146a8de4b387b51a34cfcf91c96fafb348869f1b7ab117e),
[independent verifier](../../benchmarks/post-spool-cpu-attribution-2026-11-05-verifier.py),
[preflight](../../evidence-originals.md#sha256-96c820be3fa23e22aef9a6e5ae01b4f9c889fc494bfe82dc38de71a65316db0c),
[frozen executed plan](../../evidence-originals.md#sha256-d0d1d5d61ebc51a1bb0d7ad50ae91526144800dd922c17dab04d1dd17a7f5bb8) and
[static code-generation excerpt](../../evidence-originals.md#sha256-1e97ce095bcec0cc034232089d8b620c0ca7a8de86667b7b449c5e20d5436c98) preserve the
exact commands and replay requirements. The source copies use private host paths
and retained tool/library/control/oracle files; they are not standalone portable
commands. All raw profiles, outputs, planning revisions and failed setup remain
in the report's private locations with hashes.

The earlier complete-Run profile predates adopted inline spool keys and buffered
field copies. Its percentages cannot rank today's source. This fresh build uses
production `91f493f55d21f0893c63fc52caff3d599d92c772`, with all 333 compilation,
patched vendor and embedded-asset inputs frozen independently of the other dirty
root checkout. Rust 1.99.1 release has debug metadata level 1, default features and
unchanged optimization flags; the ELF, actual compiler/C/linker identities,
commands and environment controls are recorded. This artifact is for attribution,
not a performance comparison against an earlier build or native Windows.

The exact retained perf 7.0.14/packages/shared libraries are rechecked along with
current WSL kernel 6.18.33.1 and perf_event_paranoid 2. Original sampler access
produced 206 samples with zero loss but its wrapper falsely failed on a report
header. The reviewed read-only repair and original failed status remain intact.
This study rechecks the same control bytes/parser and matching tool/kernel context;
it does not repeat the sampler or call an old pass fresh acceptance. The first
new coordinator attempt fails before any command because absolute input globs are
unsupported; its manifest/log remain. A reviewed separate plan expresses those
same inputs relatively and passes all eight steps.

Two fixed complete jobs sample `cpu-clock:u` at 499 Hz with 16,384-byte DWARF
stacks. Ordered export uses the already frozen plain four-million-row fixture,
385,777,325 bytes/SHA-256
`876a1e8eef46cfd53f4b5667841327fae3f6a6d0e3b2c19b505c9b593edd2b74`.
Partition(region) -> probabilistic 80/20/0 allocation -> uniform child shuffle uses
the existing plain million-row fixture, 94,776,853 bytes/SHA-256
`37bb8e696a4aa01df8452adcc1b4fb14c11bec1f8064b4575152a62be738e1ae`.
Both retain seed `strict-csv-serial-v1`, four workers, 32-MiB job/shared limits,
1-MiB record cap, 1-GiB temporary ceiling and 4096 files. Ordered strict caps are
four million rows/512 MiB; pipeline caps are one million rows/128 MiB. These are
separate development recipes and denominators, not before/after variants or
reserved holdouts. Cache/background remain uncontrolled; no own builds overlap
capture. Profiling overhead is included and durations are excluded from speed
comparisons.

| Self-period symbol | Ordered, 440 samples | Pipeline, 783 samples |
| --- | ---: | ---: |
| Direct consume | 16.14% | See raw record |
| BLAKE3 SSE compression | 15.45% | 13.03% |
| Three-byte search | 11.82% | See raw record |
| UTF-8 validation | 10.23% | 7.54% |
| Output PlanWriter row | 8.18% | See raw record |
| Packed-row reserved field decode | See raw record | 10.47% |
| Reservation resize | 1.82% | 4.47% |
| ReusingRows next | See raw record | 4.21% |
| Buffered exact read | See raw record | 3.45% |
| Header decode | See raw record | 2.04% |

Both captures report zero lost samples and exceed the predeclared 100-self-sample
quality floor. Reported self-period percentages are rounded by perf. Inclusive
stack percentages overlap and must not be summed; unresolved addresses and bounded
DWARF capture limit caller attribution. BLAKE3 callers remain insufficiently
separated, so its entire share cannot be assigned to logical digests or RNG.
These observations do not justify retuning the closed digest, marker-cache,
ASCII-escape, SIMD or empty-grant studies.

Every job independently verifies all fields and unique IDs, membership/order,
lineage, strict caps, output inventory/bytes and cleanup. Raw CSV hashes, output
records and seventeen logical Analysis fields exactly match source-equivalent
native baseline correctness oracles after those independent checks. The native
observations supply correctness only; no old timing is reused. Ordered CSV also
equals the complete input. Each capture has a separate dependent verifier.
Analysis diagnostics/timings precede final publication and are distinct from
whole-Run accounting. Reservations are not RSS; CPU samples do not establish
physical I/O, Windows performance or kernel costs.

Both record commands use `--no-buildid-cache`, preserving the binary after the
older same-inode build-ID-cache link/ctime invalidation. Neither old statuses nor
active inputs are edited. One fresh Linux profiling build and two complete WSL
Runs are spent, with no source variants, component scans, capture repeats or
automatic resampling. macOS and browser performance remain unmeasured.

Source inspection shows unchanged-size reservation calls already return before
ledger work. The pinned Linux ELF nevertheless emits six register pushes and a
40-byte stack adjustment before that comparison in its 810-byte out-of-line
resize routine. A tiny inline equality wrapper could avoid that entry/exit work,
with the original changed-size body isolated. Static assembly establishes this
artifact's code shape, not which calls produced the samples or a Windows gain.
Any candidate needs its own fresh exact-head/base gates and frozen complete-Run
comparison. It must keep all reservation objects, zero/nonzero calls, grants,
drops, pressure checks, atomic rollback/releases and errors unchanged. This is
distinct from the rejected empty-grant/object/drop removal; that patch stays closed.

The current normalized adapters do not turn these per-symbol diagnostic shares
into whole-job timing observations or comparisons. Raw records and source locations
remain queryable, while unsupported extraction stays visible. No clock/comparison
binding is invented. Actual final evidence-only gate and landed SHA are recorded
separately after authorized local delivery. The original TODO objective continues
under the same 20:33:04 UTC deadline and 20:13:04 UTC measurement cutoff.
