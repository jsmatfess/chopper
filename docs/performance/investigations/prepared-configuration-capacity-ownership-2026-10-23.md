## Prepared configuration capacity ownership (2026-10-23)

The [`PreparedJob` owner](../../../crates/chopper/src/engine/job_owner.rs) now admits
retained configuration String/Vec capacity before input processing. It includes
spare operation, column and allocation capacity and nested text. The grant stays
with the immutable payload through preparation/publication and releases after
its destruction. Missing seeds reserve 64 bytes before generating the same
lowercase hexadecimal representation of 32 random bytes. Canonical Job
serialization and read-only borrowing remain available; direct mutation through
`Prepared.job` is now rejected at compile time. Explicit Job clones remain
caller-owned. This public Rust field now has an owner type rather than `Job`.

The [ownership contract](../../resource-policy-research.md#prepared-configuration-capacity-ownership-2026-10-23)
distinguishes retained admission from caller construction, deserialization,
validation scratch and Context setup that precede this boundary. Source Analysis
trees/clones, response/error allocations, filesystem/runtime storage and stacks
remain open. The new `prepared_job_reserved_bytes` diagnostic identifies this
owner in analysis snapshots; exact workspace equations now include its charge
and still require only the directory baseline after prepared owners are dropped.

The [initial Windows](../../evidence-originals.md#sha256-d3872d4a6e5fa1237fb4107595313613170cf2a330e783067af0e2b7395330d4 "Original: docs/benchmarks/prepared-job-owner-validation-2026-10-23.json")
and [Linux](../../evidence-originals.md#sha256-9e853b74522fc7fed802c919e7dfe4fc019e4303b0f3d4a3c30ad21c0a390891 "Original: docs/benchmarks/prepared-job-owner-linux-validation-2026-10-23.json")
passes are retained: each fails the same three pipeline equations because they
omitted the newly charged configuration. The follow-up changes add that owner
to exact expectations and diagnostics rather than weakening resource assertions.

The [follow-up Windows record](../../evidence-originals.md#sha256-f14d7494b44a4c6514dc4d773efdb337e68e0648b7c7573137d096780371c704 "Original: docs/benchmarks/prepared-job-owner-final-validation-2026-10-23.json")
and [six-command Linux record](../../evidence-originals.md#sha256-07fb2cc58d6e608fab31961d18aa416c161b8d0f8b0cf39a2854c4e1172b3d05 "Original: docs/benchmarks/prepared-job-owner-linux-final-validation-2026-10-23.json")
pass default and combined-feature Clippy and native suites. Windows covers 254
default workspace and 311 combined-feature Chopper tests; Linux covers 257 and
314 respectively, each with the additional read-only compile-fail doctest. The
focused owner controls independently sum spare nested capacities, check six
local/shared edges, competing-owner release/retry, canonical serialization and
caller-clone independence. Public preparation denies a configuration retaining
1 MiB of spare capacity before the input-read event, retains its admitted grant
through serialization failure, and completes an exact CSV publication/release.

The same resource controls pass in bundled Chromium, installed Chrome and Edge
with the combined WASI candidate build. The nested fixture retains 2,336 bytes
on Windows and 1,700 in WASI; these are actual platform container capacities,
not RSS measurements. The public preparation fixture retains 1,048,750 bytes
on Windows and 1,048,666 in WASI, including its intentionally spare output path.

The Windows pass then stops in the standard production browser suite at an
older exact workspace equation; its CSV/stage checks had already passed. Three
browser equations receive the same explicit configuration-owner term. The
[browser follow-up](../../evidence-originals.md#sha256-040200bb1dc466ebcf1622245ee194cb830101d164b6568874f0e1b57bbd38df "Original: docs/benchmarks/prepared-job-owner-browser-followup-2026-10-23.json")
records `ui/tests/browser.ts` as the sole changed compilation input. Rust engine,
native binary and WASI modules are unchanged from the native/resource pass.

All five follow-up commands pass: UI's 28 tests, native UI build/type checking,
production's 25 Chromium contracts and final hosted packaging. The
[package identities](../../evidence-originals.md#sha256-5d856846f418203288773e09252d3cd1e05b5788f13daf83ca840d0ff4c6e91a "Original: docs/benchmarks/prepared-job-owner-package-identities-2026-10-23.json")
pin 25 native test executables, the release binary and seven final hosted assets;
the production resource-contract export is absent. Both native/resource and
browser-receiver passes retain their own unchanged source inventories.

The [retained native CLI comparison](../../evidence-originals.md#sha256-83112260ff2a546f1ee90b75af47d60a2f211d2885366c525d5596aa668b8335 "Original: docs/benchmarks/prepared-job-owner-native-compatibility-2026-10-23.json")
pins the prior binary to the preceding Zstandard input package. Seven fixtures
cover no operations, three shuffle strategies, partition/balanced, stratified
exact assignment and interleaving. All fourteen commands succeed with exact CSV
hashes, output records, canonical configuration (destination normalized) and
stage-statistic parity under row/byte caps. The
[initial verifier attempt](../../evidence-originals.md#sha256-b90983d045584f60cbe5b53981f137662dc106ca37af86d67b6aae4ab3960efc "Original: docs/benchmarks/prepared-job-owner-native-parity-2026-10-23.json")
is preserved: the prior binary rejected a balanced fixture whose seven-row cap
conflicted with its exact file count. The corrected comparison uses compatible
30-row/1,024-byte limits and removes its test directory.

These deterministic controls do not establish throughput, RSS, physical I/O,
large-job or additional-device acceptance. This local package is not published;
macOS remains deferred. Broader ownership and release work stays in [TODO](../../../TODO.md).
