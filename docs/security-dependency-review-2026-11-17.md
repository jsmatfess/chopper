# Rust dependency review for Chopper 0.2

The 2026-11-17 lockfile audit reported three vulnerabilities and twelve
unsoundness warnings. Updating four registry packages cleared those findings.
The vendored Zstandard WASI allocator has a separately verified upstream
backport. The final hosted runtime gate is pending.
[Tracking issue #1](https://github.com/jsmatfess/chopper/issues/1)

## Lockfile and production call paths

| Dependency | Before → after | Chopper call path |
| --- | --- | --- |
| `zstd` | 0.13.3 → 0.13.4 | Each output encoder owns a fresh context. The input adapter creates its own C context per reader. Neither path uses the borrowed `with_context` constructors that now reset the session. [RUSTSEC-2026-0391](https://rustsec.org/advisories/RUSTSEC-2026-0391), [upstream fix](https://github.com/gyscos/zstd-rs/commit/74ace2dcdca62a2ce0f034895d6079458311e003) |
| `zstd-safe` | 7.3.0 → 7.4.0 | Production input drives the custom C context through the pull reader with initialized `&mut [u8]` output. Reader errors propagate before a byte count is returned. It bypasses `DCtx::decompress_stream` and the write-side decoder that could expose unwritten `Vec` bytes. Seekable support is disabled. [RUSTSEC-2026-0398](https://rustsec.org/advisories/RUSTSEC-2026-0398), [RUSTSEC-2026-0403](https://rustsec.org/advisories/RUSTSEC-2026-0403) |
| `rustix` | 1.1.5 → 1.1.6 | Unix and WASI reopen use `fstat` for identity checks. These paths use no extended-attribute calls. Windows uses `ReOpenFile`. [Temporary reopen](../crates/chopper/src/storage/temp_path.rs), [RUSTSEC-2026-0486](https://rustsec.org/advisories/RUSTSEC-2026-0486) |
| `tokio` | 1.53.2 → 1.53.3, then removed | The intermediate update cleared the advisory. Retiring the native browser server and its `rfd` picker then removed Tokio and the picker dependency graph from the final lockfile. [RUSTSEC-2026-0386](https://rustsec.org/advisories/RUSTSEC-2026-0386) |

The ten `zstd-safe` unsoundness warnings cover APIs or states absent from the
production codec path. Chopper disables seekable and codec workers, uses no
dictionary training, prepared dictionaries, context cloning or stable-input
parameter, and never mixes one-shot and streaming calls on a context.
`zio` starts its normal read and write buffers at position zero and derives
later positions from successful stream calls. The custom input reader checks
allocation denial and codec errors before returning a count to its consumer.
[zstd-safe advisories](https://rustsec.org/packages/zstd-safe.html)

## Zstandard ownership

The resolved `zstd-sys` remains the workspace's vendored
`2.1.1+zstd.1.5.7` path package. Linux, Windows and WASI resolve the same
`experimental`, `legacy`, `std`, `vendored` and `zdict_builder` features
as before. The C source, legacy callbacks, build selection and codec
parameters are unchanged by the wrapper update. The vendored build guard
continues to reject a system library. [Allocator bridge](../vendor/zstd-sys-2.1.1/CHOPPER.md)

Input keeps its own `ZSTD_createDCtx_advanced` context and uses the same
`zio::Reader` state machine. The wrapper update leaves the reader's frame
transitions and EOF logic intact. Chopper keeps its initialized output slice,
window-log limit, session-only reset between frames and terminal admission
denial. The stable callback controller outlives context destruction. The
modern context and legacy 0.4–0.7 children release their payload and layout
header grants after deallocation, including on version-switch failure. The
source buffer and reader/controller boxes retain their separate grants.
[Input adapter and controller](../crates/chopper/src/engine/input_zstandard.rs),
[Input ownership contract](resource-policy-research.md#zstandard-input-streaming-allocation-ownership-2026-10-23)

Output still uses level 3, window log 21, a checksum and unknown source size.
The owning write encoder creates one `CCtx`, uses the same pinned C
compress/flush/end/free calls, and allocates a fixed 32 KiB writer buffer.
The new Rust context state and writer panic flag are inline and introduce
no additional heap owner. The new stream guards report errors without
committing an invalid cursor or issuing another C stream call on a failed
context. The configured output path uses explicit finish. The C size
estimator and 32 KiB allowance are admitted before construction and held
through destruction on finish, error or abandonment. The allowance covers
requested codec storage and the writer buffer. Process RSS, stacks and
allocator overhead are outside that estimate.
[Output adapter](../crates/chopper/src/output/zstandard.rs),
[Output ownership contract](resource-policy-research.md#zstandard-output-context-admission-2026-10-23),
[Released wrapper source](https://github.com/gyscos/zstd-rs/blob/357eb72b038676f8609dcb9e3f727e7da050e055/src/stream/zio/writer.rs),
[Released binding source](https://github.com/gyscos/zstd-rs/blob/357eb72b038676f8609dcb9e3f727e7da050e055/zstd-safe/src/lib.rs)

## Vendored source review

Cargo Audit 0.23.0 scans default-registry packages for advisories. Its zero
result omits the path override for `zstd-sys`. Chopper's input callbacks check
failure and own the modern and legacy streaming decoder allocations. The hosted
output encoder uses the default C allocation path through the vendored shim.
Working-storage admission can succeed before the underlying allocator fails.
The pinned source applies the exact upstream RUSTSEC-2026-0410 change to this
shim. It rejects `calloc` multiplication and header-size overflow, enforces
Rust's aligned layout bound, returns null on allocator failure and accepts
`free(NULL)`. The pinned C allocator bridge and legacy callbacks are preserved.
[WASI shim](../vendor/zstd-sys-2.1.1/src/wasm_shim.rs),
[RUSTSEC-2026-0410](https://rustsec.org/advisories/RUSTSEC-2026-0410),
[upstream fix](https://github.com/gyscos/zstd-rs/commit/165d1625553c236b9700ca794b8a7c51f5d98314)

The scan also omits the vendored ZIP path package. Chopper selects a
central-directory ZIP member and streams Stored or Deflate CSV data. It uses no
archive extraction, local-header streaming reader, AES password flow or legacy
ZIP decoder. These checks cover the published advisory preconditions reviewed
here. The retired native HTTP server, its `tiny_http` vendor package and the
native picker dependency graph are absent from the final product source.
[ZIP input](../crates/chopper/src/engine/input_zip.rs),
[ZIP advisories](https://rustsec.org/packages/zip.html)

## Verification

- Cargo Audit 0.23.0 reported zero vulnerabilities and zero warnings with
  `cargo audit --json --deny warnings`. Before and after used RustSec
  database revision `233155b4025b854c68a4b199c0e32d7fd53291a2` and no
  advisory exclusions. The release audit's separate npm result was zero.
- Linux unit checks passed for Zstandard input and output admission,
  publication grant lifetime and temporary construction and reopen.
  Linux integration checks passed for
  checksums, skippable frames, and Zstandard input and output byte accounting.
  The input admission suite includes legacy version switches, allocation
  failures, window limits and cancellation.
- A Linux comparison encoded empty, Unicode and deterministic 3 MiB-plus
  input with both wrapper pairs against the same vendored C backend. All
  three compressed files matched byte for byte and round-tripped.
- The vendored shim diff matches upstream. Three Linux tests compile the
  same shim source, make the native test allocator return null through both
  `alloc` and `alloc_zeroed`, and check size rejection, null deallocation,
  zeroing, payload bytes and the recovered deallocation layout.
  [Native shim tests](../crates/chopper/tests/zstd_wasm_shim.rs)
- A release build of the `wasm32-wasip1` resource-contract reactor linked
  successfully using WASI SDK 33. The test-only output codec contract calls
  the linked shim and checks overflow, the layout bound and null deallocation.
  The production artifact guard accepted a separate default build and rejected
  the test build. The existing `chopper_resource_contracts` entry point was the
  only export difference. Hosted runtime validation and the exact final Linux
  and native Windows release gates are pending.
  [WASI codec contract](../crates/chopper/src/output/zstandard/resource_contracts.rs)
