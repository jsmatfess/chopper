## Mixed hosted Uniform merge with a retained final batch (2026-11-26)

[Issue #105](https://github.com/jsmatfess/chopper/issues/105) ·
[Projected Run samples](../../benchmarks/hosted-uniform-mixed-merge-2026-11-26.jsonl) ·
[Shared-pressure controls](../../benchmarks/hosted-uniform-mixed-merge-pressure-2026-11-26.json) ·
[Timing patch](../../benchmarks/hosted-uniform-mixed-merge-2026-11-26.patch) ·
[Pressure control patch](../../benchmarks/hosted-uniform-mixed-merge-pressure-2026-11-26.patch)

Keep the ordinary final spill. A mixed traversal removed one write and read
pass, but its cursor held more memory through output setup and turned a
supported shared-pressure case into a late decode failure.

### Complete hosted Runs

The candidate sorts the final batch in memory and compares its next row against
the existing disk merge head using the same comparator. A disk head wins a tie
with the final batch. It screens standalone plain Uniform with one to three
existing disk runs and a 4 MiB slack allowance plus four times the largest
record's observed allocation hint. This allowance is an admission observation.

Three alternating matched pairs per cell ran in persistent bundled Chromium
on WSL2 with 128 MiB, one worker, Auto grouping, 256 payload bytes, and a 4 MiB
CSV cap. The timer covers Run through marker verification and workspace
retirement. The larger fixture has one existing run. The candidate drops the
final spill from two runs to one and saves 22,741,963 bytes each from tracked
temporary reads and writes. Peak working reservations were 33,830,423 bytes
in both arms after including sorter intake.

| Fixture | Baseline median [min–max], s | Candidate median [min–max], s | Paired seconds saved [min–max] |
| --- | ---: | ---: | ---: |
| 150,003 rows with final spill | 1.325 [1.298–1.382] | 1.184 [1.172–1.198] | 0.127 [0.126–0.199] |
| 50,003 rows, both resident | 0.434 [0.423–0.447] | 0.415 [0.410–0.433] | 0.015 [0.013–0.019] |

The resident control never enters the mixed path and has identical temporary
traffic. Its timing difference is outside the causal mixed-merge claim.
Every export checks conservation, fields, manifest, sizes, caps, marker and
cleanup. Independent Runs use fresh entropy. The separately pinned-internal-
order control traverses the same numeric key order in both arms.

### Late pressure falsifier

The pinned control writes a wide first disk row and retains twelve more
half-MiB rows with a known key order. It uses the production packed decoder
and capped snapshot encoder and a shared 128 MiB ledger. Early pressure at
2 MiB of headroom selects and completes the ordinary spill. In the late
WASI case the same 127,522,534-byte peer grant is admitted after the merge
and output writer exist. Before that grant the mixed path holds 6,629,658
bytes through writer setup and the ordinary path holds 402,072. The grant
leaves 65,536 bytes for the candidate and 6,293,122 bytes for the ordinary
path. Only the ordinary path encodes all 13 rows. The mixed path returns a
typed shared-memory denial at row zero.

The Linux control reproduces the same failure with its native writer
buffers. All successful, denied, and cancelled cases release their owned
files and reservations. A valid future design would need to secure downstream
decode and encode capacity across the mixed cursor's lifetime, or demonstrate
an isolated admission regime and bounded recovery before emission. The
complete-job savings justify preserving the experiment but cannot support
shipping the headroom-only selector.

### Reproduction

Use the measured ordinary chain from the
[routed group key investigation](a-single-admitted-key-per-routed-group-2026-11-26.md).
Apply the timing patch for the WASM challenger. The pressure patch is an
alternative to the timing patch and adds the component control to the test
reactor. Use the exact resource-contract worker and storage-worker assets in
a separate browser context. The retained controls record the native and WASI
results independently. The initial browser control omitted the storage
worker asset and was excluded before starting the reactor.
