## Automatic native execution bounds (2026-11-22)

This pass integrates measured native paths into normal Run on the Auto branch.
The complete-job comparison begins at CLI launch and ends after publication and
workspace cleanup. Independent record, output and workspace verification follows
the clock. The acceptance rule requires at least 0.25 seconds and 5% lower
median elapsed, improvement in both reversed rounds, and at most 15% more
process CPU. Lower-bound controls verify old-route selection. CPU, process peak
RSS or Windows working set, admitted working reservations, logical temporary
traffic and sync counts have separate scopes.

### Matched Run results

The matched executable identities, individual measurements and resources are in
the linked raw records. Linux uses WSL ext4 and Windows executes native MSVC
binaries with NTFS test data. Both runtimes share one physical host. Some
independent tests and builds overlapped, so elapsed spread is relevant.
The 8 GiB terminal comparisons include the measured change from ordinary
snapshot publication to grouped private output. Earlier same-path [wide
merge](wide-terminal-uniform-merge-2026-11-21.md) and [short-tail
merge](terminal-uniform-short-tail-2026-11-21.md) experiments isolate the merge
choice. The 40 GiB result has one earlier matched pair. The new automatic short-tail
rule uses the repeatedly tested 96 MiB tier.

| Runtime and workload | Baseline elapsed | Candidate elapsed | Baseline / candidate CPU |
| --- | ---: | ---: | ---: |
| [Linux Bounded Partition, 293 MiB](../../benchmarks/native-auto-bounds-2026-11-22-final-bounded-partition-control.jsonl) | 1.42 s | 0.64 s | 1.02 / 0.49 s |
| [Linux Bounded Partition, two 2 GiB jobs](../../benchmarks/native-auto-bounds-2026-11-22-linux-bounded.jsonl) | 10.49 s | 5.91 s | 7.86 / 3.94 s |
| [Windows Bounded Partition, two 2 GiB jobs](../../benchmarks/native-auto-bounds-2026-11-22-windows-qualified-bounded-partition.jsonl) | 13.60 s | 6.32 s | 9.40 / 4.36 s |
| [Linux Bounded Interleaved, 16 writers](../../benchmarks/native-auto-bounds-2026-11-22-final-bounded-interleaved.jsonl) | 8.43 s | 5.18 s | 6.44 / 3.14 s |
| [Windows Bounded Interleaved, 16 writers](../../benchmarks/native-auto-bounds-2026-11-22-windows-final-bounded-interleaved.jsonl) | 8.94 s | 5.41 s | 6.78 / 3.74 s |
| [Linux Bounded probabilistic assignment](../../benchmarks/native-auto-bounds-2026-11-22-final-bounded-probabilistic.jsonl) | 8.21 s | 5.48 s | 7.06 / 4.10 s |
| [Windows Bounded probabilistic assignment](../../benchmarks/native-auto-bounds-2026-11-22-windows-final-bounded-probabilistic.jsonl) | 9.99 s | 5.71 s | 7.46 / 4.38 s |
| [Linux Shared UTF-16LE serializer, wide rows](../../benchmarks/native-auto-bounds-2026-11-22-final-wide-utf16.jsonl) | 15.78 s | 10.29 s | 9.97 / 6.84 s |
| [Linux Counted Balanced](../../benchmarks/native-auto-bounds-2026-11-22-integrated-counted-balanced.jsonl) | 7.06 s | 4.98 s | 5.60 / 3.75 s |
| [Windows Counted Balanced](../../benchmarks/native-auto-bounds-2026-11-22-windows-qualified-counted-balanced.jsonl) | 7.20 s | 6.12 s | 5.49 / 4.70 s |
| [Linux Counted Partition → Balanced](../../benchmarks/native-auto-bounds-2026-11-22-integrated-counted-partition.jsonl) | 11.82 s | 6.81 s | 9.84 / 5.62 s |
| [Windows Counted Partition → Balanced](../../benchmarks/native-auto-bounds-2026-11-22-windows-qualified-counted-partition.jsonl) | 12.58 s | 7.72 s | 9.79 / 6.25 s |
| [Linux Counted Zstandard-input Balanced](../../benchmarks/native-auto-bounds-2026-11-22-final-counted-zstd.jsonl) | 7.31 s | 4.65 s | 5.42 / 3.74 s |
| [Windows Counted Zstandard-input Balanced](../../benchmarks/native-auto-bounds-2026-11-22-windows-qualified-counted-zstd.jsonl) | 6.78 s | 5.60 s | 5.01 / 4.19 s |
| [Linux Interleaved → probabilistic assignment](../../benchmarks/native-auto-bounds-2026-11-22-integrated-chain-forward.jsonl) | 12.92 s | 5.60 s | 11.94 / 4.36 s |
| [Windows Interleaved → probabilistic assignment](../../benchmarks/native-auto-bounds-2026-11-22-windows-qualified-chain-forward.jsonl) | 14.32 s | 6.63 s | 12.17 / 5.21 s |
| [Linux Probabilistic assignment → Interleaved](../../benchmarks/native-auto-bounds-2026-11-22-integrated-chain-reverse.jsonl) | 17.76 s | 6.11 s | 12.33 / 4.29 s |
| [Windows Probabilistic assignment → Interleaved](../../benchmarks/native-auto-bounds-2026-11-22-windows-qualified-chain-reverse.jsonl) | 14.75 s | 6.00 s | 12.23 / 4.64 s |
| [Linux Retained stratified exact writers](../../benchmarks/native-auto-bounds-2026-11-22-final-retained-exact.jsonl) | 21.24 s | 9.61 s | 17.67 / 8.01 s |
| [Windows Retained stratified exact writers](../../benchmarks/native-auto-bounds-2026-11-22-windows-qualified-retained-exact.jsonl) | 20.18 s | 10.36 s | 17.80 / 8.88 s |
| [Linux Batched sync, 8,192 files](../../benchmarks/native-auto-bounds-2026-11-22-linux-final-sync.jsonl) | 66.00 s | 28.36 s | 11.16 / 8.66 s |
| [Linux Batched sync, 16,384 files](../../benchmarks/native-auto-bounds-2026-11-22-pending-final-sync-ceiling.jsonl) | 194.77 s | 43.71 s | 18.80 / 14.02 s |
| [Linux Wide merge, 8 GiB at 256 MiB](../../benchmarks/native-auto-bounds-2026-11-22-final-terminal-wide.jsonl) | 52.75 s | 40.89 s | 45.09 / 36.55 s |
| [Linux Short-tail merge, 8 GiB at 96 MiB](../../benchmarks/native-auto-bounds-2026-11-22-final-terminal-short.jsonl) | 52.77 s | 43.58 s | 45.30 / 38.42 s |
| [Linux Indexed quota, 4.2 million rows and 1,000 groups](../../benchmarks/native-auto-bounds-2026-11-22-final-quota-index-heavy.jsonl) | 11.64 s | 10.36 s | 6.27 / 5.89 s |

Lower-bound controls and corrected attempts.

- [1.05-million-row quota control](../../benchmarks/native-auto-bounds-2026-11-22-qualified-quota-index.jsonl)
- [1,024-group indexed test and elapsed reversal](../../benchmarks/native-auto-bounds-2026-11-22-final-index-cap1024.jsonl)
- [1,024-file sync control](../../benchmarks/native-auto-bounds-2026-11-22-pending-final-sync-control.jsonl)
- [Integrated bounded Partition smoke under competing jobs](../../benchmarks/native-auto-bounds-2026-11-22-integrated-bounded-partition.jsonl)
- [First Windows pressure selection failure](../../benchmarks/native-auto-bounds-2026-11-22-windows-retry-bounded-partition.jsonl)
- [Initial terminal reporting failure](../../benchmarks/native-auto-bounds-2026-11-22-linux-terminal-wide.jsonl)
- [Initial Zstandard route assertion failure](../../benchmarks/native-auto-bounds-2026-11-22-integrated-counted-zstd.jsonl)

[Feature-free CLI verification with automatic memory and Analyze advice](../../benchmarks/native-auto-bounds-2026-11-22-smoke.json)

### Current policy

The [direct execution contract](../../direct-execution.md#native-auto-paths)
records the exact predicates. Writer routes keep the user-declared file and
record limits binding. Bounded Partition can use an exact Analyze count to
suggest a smaller file ceiling for an uncapped output. The recommendation leaves job limits under user control. Allocation uses
the current admitted workspace. A normal CLI smoke runs
Analyze, applies its matching advice on Run, and verifies that the suggestion
is reported without changing the configured limit. A large Interleaved smoke
runs with automatic memory and checks the effective 1 GiB tier and all outputs.

An actual Context checks admission after the initial policy decision. A denied
starting bound can return to the ordinary plan before output starts. Windows
has a conservative 128 MiB process ledger when host availability is unknown.
A config owner can lower the nominal automatic tier to 255 MiB. The 96 MiB live
floor keeps the two quantities independent. Linux high fanout also checks
current descriptor use. Competing-job tests use separate processes. The focused
contract adds constrained shared memory in the engine and checks the direct
selection boundary. Retained exact setup uses its existing pre-emission
typed-memory fallback with the same immutable parent and destination witness.

The Zstandard default is for containers up to 8 MiB on disk and at least
2 GiB of declared or applicable observed decoded size. The heavily compressible
checksummed holdout is about 6.4 MiB on disk. The earlier varied-input result
had a CPU increase and remains useful opt-in evidence. Source frame metadata
guides the route without authorising capacity or replacing complete
validation. An indexed exact cursor uses the actual rounded quota vector.
The 1.05-million-row screen and the 1,024-group indexed holdout each had
an elapsed reversal. Both use the linear route under the current rule.
The 1,024-file sync control keeps ordinary publication.

### Verification and attempts

The oracles check exact serialized sizes, fields and record conservation in
each cell. They also check encounter order where required, exact Balanced
ranges, per-stratum exact quotas, and round-robin membership for composed
Interleaved. Probabilistic frequencies are finite diagnostics. The native
atomic publication and hosted browser completion checks remain separate.

The first orchestration manifest was rejected for a missing explicit verifier
input. A subsequent prototype runner batch lost its freshness receipt when
the development harness changed. The integrated panels use pinned harness
copies. A Windows build initially reused the baseline binary because an
mtime-preserving checkout copy did not invalidate the build. A separate run
then exposed the conservative startup budget issue and fell back correctly.
The rematched Windows build has a distinct executable hash. An earlier
8 GiB terminal run passed its row oracle but failed the strategy reporting
assertion. The corrected build reports the actual merge and its peak fan-in.
An earlier Zstandard pair likewise caught the wrong route and was repeated
with decoded-size selection. A rejected 4,096-group staging attempt exceeded
the existing allocation schema limit and did not produce output.

### Reproduction

Use pinned feature-free old and new executables. The sync control has
typed catalogs and small writer buffers enabled, with original per-file
sync scheduling. Run from the repository root so the harness captures the
checkout identity. Input creation and optional existing-source verification
remain outside the per-job timer.

```sh
python3 scripts/benchmark-auto-contention.py bounded-partition SCRATCH BASELINE --writers-binary CANDIDATE --integrated
python3 scripts/benchmark-auto-contention.py final-sync SCRATCH TYPED_CONTROL --writers-binary CANDIDATE --integrated
python3 scripts/benchmark-auto-contention.py terminal-wide SCRATCH BASELINE --writers-binary CANDIDATE --integrated
```
