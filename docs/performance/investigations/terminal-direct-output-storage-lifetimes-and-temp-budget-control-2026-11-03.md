## Terminal direct output: storage lifetimes and temp-budget control (2026-11-03)

**Decision: the unchanged prototype expands completion under the defined temporary
budget in this case; it does not establish lower combined filesystem storage.**
The [storage-control record](../../evidence-originals.md#sha256-21309dccb9fcd2cba79bcb37ba2a9c871f945f96ddbb2f4b63dad1507e8f2a6d)
reuses the [200k native fixture and frozen binaries](../../performance.md#terminal-direct-output-chrome-and-working-set-transfer-2026-11-03).
These four diagnostic controls include filesystem sampling overhead and supply no
additional speed observations. Production code, dispatch and defaults stay unchanged.

Native Windows/MSVC uses the same 200,000 independent events, seeded
`partition(event_type) -> assign_probabilistic(80/20)` recipe, plain UTF-8 output,
64-MiB job memory, 32-MiB shared admission and one worker. Input, temporary files,
private staging and destination reside on the same Windows volume. Only the
configured temporary budget changes between the 256-MiB and 38-MiB controls.

| Diagnostic control | Native outcome | Charged temporary peak, bytes | Sampled simultaneous combined lower bound, bytes |
| --- | --- | ---: | ---: |
| Prepared baseline, 256 MiB | Success | 44,150,137 | 43,757,001 |
| Direct prototype, 256 MiB | Success | 34,141,695 | 44,128,431 |
| Prepared baseline, 38 MiB | Expected exit 1: temporary-space budget exhausted | Unavailable after failure | 39,586,953 |
| Direct prototype, 38 MiB | Success | 34,141,695 | 44,188,443 |

The successful 38-MiB direct sample contains **33,079,215 temporary bytes plus
11,109,228 private-output bytes at the same scan boundary**. Its combined logical
file lengths exceed the configured 39,845,888-byte temporary budget, consistently
with output publication being outside that intermediate-file budget. This is a
specific completion-domain benefit, not a total-storage quota or free-space guarantee.

Sampling uses two consecutive recursive scans keyed by Windows file identity.
It de-duplicates aliases across temp/private/final locations, then counts only
identities present in both scans with nondecreasing length. For this append-only
plain-file path, first-scan lengths give a simultaneous lower bound at the intervening
boundary. Files deleted or created between scans cannot be summed into that bound.
A hardlink control verifies de-duplication; disjoint-lifetime and shrink controls
verify exclusions. Raw non-atomic endpoint estimates are retained separately and
are never treated as simultaneous peaks. Requested sleep is 2 ms; actual median
sample cadence is 3.75–4.05 ms, maximum 6.36 ms. One disappearing-file race and two
alias visits are retained; no shrinking identity is observed. Short-lived files,
file buffers, directory metadata and allocated blocks are not measured.

Do not subtract these lower bounds to claim a true peak increase or decrease.
The evidence directly captures earlier private-output overlap and prevents using
the charged-peak reduction as an equal combined-space saving. It does not establish
physical I/O, separate-device pressure, disk-full behavior, RSS or browser quota
behavior. `DiskFile::write` charges bytes before writing; plain `open_sink` creates
normal publication files. Prepared execution drops its final Dataset before
publication but retains the immutable CSV snapshot through copying. These source
boundaries explain the two accounting domains; no admission rule is weakened.

All three successful controls match exact CSV bytes, names, row order, lineage and
seeded membership, plus the 17 compared logical Analysis fields. Each produces
200,000 rows in eight files and 11,673,614 CSV bytes. The expected denial retains
its native exit code and full error; destination, temporary and private staging
cleanup pass for all four controls. Original native build inputs are rehashed;
the existing completion/pressure/cancellation tests remain separate evidence.

Raw plans, sampler controls, records, file-identity samples, outputs and full logs
remain private in Windows `scratch/terminal-storage-20261103T1328/`; WSL retains
source/output audit and evidence checks under the same task name. An initial WSL
audit setup rejected absolute glob patterns before a subprocess launch; a second
setup was interrupted while redundantly enumerating NTFS source directories.
Both are preserved; a fresh file-only input plan retains the original hash checks. This continuation
retains the original objective start and prior 28 attempts/29 admissions; four
new diagnostic CLI controls bring totals to 32 attempts/33 conservative admissions.
No old controller/state is resumed, and no raw evidence is uploaded or deleted.

Broader shared-pressure feasibility and pipeline/codec eligibility remain separate
acceptance gaps. The captured overlap and earlier mixed/small elapsed differences
do not justify production promotion or another timing matrix. Any next experiment
needs a named completion or whole-job benefit question from TODO.md.
