## Deterministic full-shuffle correctness, 2026-10-15

This WSL-compatible acceptance step closes the deterministic correctness item;
physical SSD/cache calibration and complete live-memory accounting remain open.
Private draw helpers expose the production rejection rule and Fisher–Yates swap
loop to deterministic tests. Public interfaces, algorithm domains, draws,
cancellation-check placement and seeded order are unchanged.

- Enumerate every Fisher–Yates choice sequence for lengths zero through eight.
  Every one of the `n!` permutations appears exactly once, including empty and
  singleton inputs with no draws. Assert descending draw bounds and exact ID
  conservation. Inject a draw failure to verify immediate loop termination.
- Force repeated rejections at zero and one below the threshold, then acceptance
  exactly at the threshold or at `u64::MAX`. Bounds include one, powers of two,
  non-powers of two, `2^63 + 1` and `u64::MAX`; a zero bound fails before drawing.
  An independent `u128` calculation checks the rejection threshold. Compare real
  v1 stream values and consumed counters, including rejected draws.
- Force all initial random keys equal for 513 distinct IDs with identical field
  payloads. Exercise owned/compact ingestion, global/group-specific domains,
  resident output and fan-in-two multi-level external merging. Compare exact
  collision-refined order, ordinals, fields and sorted unique IDs; verify release
  of temporary files and workspace reservations. Existing radix and distribution
  collision/refinement/fallback tests remain enabled.
- Capture a fixed Fisher–Yates v1 order from the pre-change release binary in
  `crates/chopper/tests/fixtures/fisher-yates-v1.json`. Check it at 32/64 MiB and
  one/four workers alongside the existing v1 fixtures.
- Exercise both full-shuffle algorithms through complete jobs with explicit
  empty allocations, singleton groups, duplicate payloads and group isolation.
  Empty input still publishes no CSVs. Balanced downstream output accepts exact
  row/byte limits, rejects one-row/one-byte short limits, and cancellation before
  execution leaves no published output. Strict malformed CSV now explicitly
  covers both algorithms; existing corrupt-spill, oversized-row/group,
  cancellation and publication tests remain passing.

Validation: 103 default workspace tests and 29 combined experimental-feature
library tests passed on WSL, along with formatting and workspace/all-targets/
all-features Clippy with warnings denied. The two local-server tests require
loopback access outside the execution sandbox. The release WASI build passed.
All 22 Chromium/WASI contracts passed with the staged browser libraries,
including existing native/browser seeded parity and resident/external selection.

The enumeration checks the swap loop's bijection under uniformly chosen bounded
draws. It does not prove the pseudorandom stream is uniform, replace the planned
fixed-seed statistical diagnostics, or establish a performance improvement.
