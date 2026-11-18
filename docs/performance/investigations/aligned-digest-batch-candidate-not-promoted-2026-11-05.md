## Aligned digest batch candidate not promoted (2026-11-05)

Decision: reject the unchanged alignment candidate and restore production exactly.
Both elapsed and total process-CPU pairs favor it, but primary user CPU rises in
one pair and is flat in the other. The frozen conjunctive rule therefore fails.
No tuning, repetitions, alternate capacities or expanded shapes follow. This is a
mixed measured outcome, an unpromoted disposition and an unapplied patch; none
implies a general regression or a new default.

[Report and original raw identities](../../evidence-originals.md#sha256-ddb3ea01e3b04229ab8c2f60b493c55db668ec8ea3395452694bb4b5b318b94c),
[unapplied patch](../../benchmarks/aligned-digest-2026-11-05.patch),
[native harness](../../benchmarks/aligned-digest-2026-11-05-native.py),
[independent verifier](../../benchmarks/aligned-digest-2026-11-05-verify.py),
[preflight](../../evidence-originals.md#sha256-fc950f8a223f69f1f3f74349c7888a7364cda47168c56a2a8cb91c7f816322ca),
[matched-build attestation](../../evidence-originals.md#sha256-6f16c70c8818925c2b436720f141d380a98042c00840ed516657650c7aeee3ad)
and [frozen plan](../../evidence-originals.md#sha256-55c11b7821aee6b665ffa594df72e4386e5f7bff15a28823378f7731e23d8074) preserve the
reviewed commands and replay requirements. The
[CPU helper](../../benchmarks/quoted-serialization-2026-11-05-cpu.py) is byte-identical
to its retained native self-control and interpreter. The plan uses its recorded
private host filenames; these source copies are for review, not a standalone
portable benchmark command. Missing private originals remain a replay limitation.

The source question was whether full batches could reduce BLAKE3's serial
partial-chunk work. The pinned blake3 1.8.7 source favors aligned power-of-two
inputs. Current LogicalDigest already has an admitted 16 KiB buffer; the candidate
fills it before flushing, hashes complete 16 KiB multiples directly and retains
the tail. Concatenated field-count/length/payload bytes and their order remain
identical. A remaining input suffix means the old buffer was filled/flushed, so
the final tail fits existing capacity. No type, capacity, grant, lifetime, schema,
seed, algorithm, execution-graph or resource-policy change was proposed. The old
WSL profile does not isolate BLAKE3 callers or quantify this particular cost.

Initial source `773eafb8f5ba88beadf2b8dfa468d8fc20a155fb` passed Linux checks on
base `2ccbd7a75405ac03268e29a6c4b4feeedae5af74`. Native expected-head guards then
found the shared clean checkout in use by the separate execution-graph thread;
no dirty or active input was overwritten. After that thread landed current main
`fc235f82244a81b5dddd792fff439982e1eb1541`, safe integration produced measured
candidate `665508df69f28fa0497a76ba9795d8452d11771e`. Its fresh Linux and native
Windows workflows pass. The initial pass remains historical, not acceptance for
the changed head/base. The authored delta against main is only digest.rs.

The changed engine and embedded assets invalidate reuse of the older native
baseline. A separately reviewed premeasurement plan builds a fresh baseline and
candidate into disjoint retained targets. Each has 333 complete compilation,
vendored and embedded-asset inputs; exactly digest.rs differs. Build records,
source maps, binary hashes, Cargo/environment identities, resolved compiler hashes
before/after compilation and matching dependency features are retained. Immutable
completed build-step records are copied from the owned runner ledger; a changing
ledger is not treated as a frozen external input. All earlier source snapshots,
failed guards, baseline artifacts and plans remain untouched. No old timing or
binary is relabeled as current production.

The fixed plain probe-v1 fixture has one million rows, 94,776,853 bytes and SHA-256
`37bb8e696a4aa01df8452adcc1b4fb14c11bec1f8064b4575152a62be738e1ae`.
Both recipes retain seed `strict-csv-serial-v1`, four workers, 32 MiB job/shared
limits, 1 MiB record cap, 1 GiB temporary ceiling, 4096 files and strict
one-million-row/128 MiB output caps. Ordered export is the four-job ABBA primary;
region partition -> 80/20/0 probabilistic allocation -> uniform child shuffle is
a separate two-job transfer control. No new fixture, holdout, seed or shape is used.

Native Windows timing covers CLI launch through complete Run, publication,
Analysis JSON and process exit. Hashing, independent verification and post-exit
Win32 process CPU queries are excluded. CPU sums all process threads, with user,
kernel and total retained separately. Fresh hardware/NTFS context is recorded;
cache/background remain uncontrolled and no own builds overlap timing.

| Primary ABBA index | Variant | Elapsed seconds | Total CPU seconds | User CPU seconds |
| --- | --- | ---: | ---: | ---: |
| 0 | baseline | 0.474274 | 0.343750 | 0.218750 |
| 1 | candidate | 0.473377 | 0.296875 | 0.250000 |
| 2 | candidate | 0.336648 | 0.281250 | 0.203125 |
| 3 | baseline | 0.364543 | 0.312500 | 0.203125 |

There are two observations per primary variant. Baseline elapsed median is
0.419409 s (range 0.364543..0.474274); candidate is 0.405012 s
(0.336648..0.473377). `(baseline - candidate) / baseline` gives 3.43% elapsed
and 11.90% total-CPU median reductions, while median user CPU increases 7.41%.
Candidate-minus-baseline user differences are +0.031250 and 0 s; neither meets
the required favorable-pair condition. One elapsed pair differs by less than
1 ms and the elapsed ranges overlap widely. Lower total CPU is a kernel-time
difference; it cannot establish the intended user-code benefit. Small cells,
coarse accounting and uncontrolled background prevent general causal/tail claims.

The separate pipeline baseline/candidate pair is 2.533367/2.511429 s elapsed,
2.406250/2.203125 s total CPU and 1.828125/1.796875 s user CPU. It stays outside
the primary cell and cannot override its failed rule. Do not pool, subtract or
add these results to prior percentage gains.

All seven runner steps and six complete jobs pass. Independent checks preserve
exact fields, unique IDs, groups, CSV bytes/output records, seventeen logical
Analysis fields, strict caps, ordered-input equality and temporary/staging cleanup.
The source candidate expands the existing independent reference/CompactRecord
hash controls at empty, 64-byte, 1 KiB, 16 KiB and 32 KiB boundary neighbors.
Native/Linux/WASI correctness coverage belongs to the recorded measured-head
workflows; final evidence-only checks do not create a new platform pass. macOS is
deferred, hosted Actions are not dispatched and browser performance is unmeasured.

After rejection, production Rust, vendor and UI inputs are restored byte-for-byte
to current main. The unchanged candidate and expanded test remain in the patch,
commits and retained snapshots. One fresh baseline build, one experimental
candidate build and all six Runs are spent; there are no component scans or
measurement retries. The unused source-attempt slot cannot reopen this rejection.
The final evidence commit uses its applicable local gate and guarded landing;
the landing handoff records the actual SHA and validation rather than guessing it.

The reviewed normalized binding selects `/native/complete_jobs/0` and
`/native/complete_jobs/3` as baseline and `/native/complete_jobs/1` and
`/native/complete_jobs/2` as candidate, with `clock_pointer: /seconds`. Existing
tested native-complete-jobs extraction keeps elapsed, process/user/kernel CPU
separate. Extraction does not establish eligibility; summaries are copies of
these observations, not additional executions. The configured recipe, seed,
algorithm and source identities are pinned. No complete native physical-plan
observation was captured; returned diagnostics retain their pre-final-publication
snapshot scope. Reservations, RSS, allocations, logical/stored traffic and
physical I/O remain distinct and no new RSS or device-throughput claim follows.
