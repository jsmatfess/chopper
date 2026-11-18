## Restored Windows checks and column-inspection ownership (2026-10-21)

The [revalidation record](../../evidence-originals.md#sha256-b6ecd6bf654841ac8e1eb955abf17e4cd5988e70ebbaf3b0e8e4d5e9d634b280 "Original: docs/benchmarks/columns-and-windows-revalidation-2026-10-21.json")
records successful reruns after the user disabled Smart App Control. A read-only
check observed state `0`; the previously rejected unchanged baseline executable
now starts. The full default Windows workspace passes, including its 137 library
tests and the previously blocked flexible integration executable. The exact
candidate-only retained-owner command passes; the joint resource/candidate
library configuration passes 151 tests and the recorded 17-feature configuration
passes 217. These are separate passes, not additive counts.

Column inspection now retains admission for its 64 KiB source buffer and parser
scratch/row capacities through their actual owners. Shared native/WASI contracts
cover local/shared denial, held-owner release and fresh retry, terminal parser
errors, EOF ownership, malformed input/read-error cleanup and unchanged
first-record-only JSON behavior. Returned JSON/configuration clones, decoder
inline storage and codec heaps, sniff samples and decoded ZIP metadata remain
outside this coverage; reservations are not a complete RSS cap.

The first full Linux run exposed a stack overflow in the monolithic contract
fixture. Its failed log is preserved. Splitting controls into smaller functions
fixes the fixture without increasing stack limits; the ordinary-stack production
path and shared-capacity regressions pass on Windows and Linux. The final Linux
default workspace passes, including 139 library tests. Formatting, both all-target
Clippy configurations, 28 UI tests/build, 25 standard Chromium contracts, the
bridge and both base/candidate resource reactors pass. Resource passes also
retain the exact-output, denial, cleanup and real OPFS export/marker checks.
The final production WASM SHA-256 is
`5611db537d9b8cd54b657e551de2d43eb8394746f79c559cdf06502eeb0d0afc`;
the cleaned hosted package passes the export guard and excludes test assets.

One abandoned temporary held-writer/USN diagnostic had no retained source or
command and cannot be faithfully replayed. The maintained profile regression
now keeps its read/write handle open across a same-size rewrite, timestamp
restoration and the second profile; changed content is observed without a cache
hit. It passes on Windows, but does not establish USN suitability. The record
maps each earlier blocked check to its rerun or this explicit exception.
