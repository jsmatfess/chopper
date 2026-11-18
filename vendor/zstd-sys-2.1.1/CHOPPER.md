# Chopper's Zstandard streaming allocator bridge

Upstream: registry `zstd-sys` 2.1.1+zstd.1.5.7, package SHA-256
`aeec9eaf2dffbbd09201e23bd0ffcbaa33bb8e9266a10734fd7ed90a85eca078`.
The Rust package and bundled C sources retain their upstream license files and
copyright notices. `UPSTREAM-SHA256.json` records the copied package files before
local changes. This package is excluded from Chopper's workspace and selected by
the root Cargo patch. The direct `vendored` feature and build-script guard forbid
substitution of a system library that lacks this allocator bridge.

`src/wasm_shim.rs` carries the upstream RUSTSEC-2026-0410 backport. The shim
checks allocation arithmetic and layout, returns null when the Rust allocator
fails, and accepts `free(NULL)`. This changes only the Rust WASM shim and
preserves the pinned C code and its allocator bridge.
[Upstream fix](https://github.com/gyscos/zstd-rs/commit/165d1625553c236b9700ca794b8a7c51f5d98314),
[RustSec advisory](https://rustsec.org/advisories/RUSTSEC-2026-0410)

Modern Zstandard already accepts `ZSTD_customMem` for its decoder context and
buffers. Its legacy streaming dispatcher previously created legacy contexts with
default allocation instead. This patch forwards the parent callbacks into the
buffered 0.4-0.7 decoders without changing frame parsing, dictionaries, window
semantics or default allocator behavior for other callers.

- `legacy/chopper_alloc.h` defines a uniquely named callback bridge with default
  malloc/free fallback.
- Buffered versions 0.4-0.6 retain that bridge and use it for their outer context,
  fixed inner decoder context and input/output buffers. Their inner context
  initialization stays the same; partial construction frees the admitted outer
  context when inner allocation fails. Inner context tables are inline, so their
  destruction requires only releasing that allocation.
- Version 0.7 converts the bridge to its existing advanced allocator API, which
  already owns its inner context and buffers.
- `ZSTD_initLegacyStream` receives the parent allocator. When changing versions,
  it clears the freed previous-context pointer before fallible construction, so
  terminal admission failure cannot cause a second free during root destruction.
- Root `ZSTD_decompressStream` passes its allocator to that dispatcher. One-shot
  legacy APIs and unused entropy-table allocation helpers are unchanged; Chopper
  input uses the streaming path. Versions 0.1-0.3 keep existing streaming errors.

Chopper's Rust adapter reuses zstd-rs's reader state machine and implements its
raw operation with the same C calls, cursor transfer, reset and EOF rules. Its
synchronous callbacks admit requested payload plus an aligned layout header
before each allocation, retain overlap and release the grant after deallocation.
A stable `UnsafeCell` controller lives beyond the C context. Admission failure is
latched, terminal and restored to its typed Rust error after the reader drops.
Reader/controller boxes and the source buffer have separate preallocation grants.
Working storage accounting excludes allocator usable-size, stacks and error/OS
internals; it is not an RSS cap.

`chopper-tests/legacy.c` is the unmodified v1.5.7 upstream test source downloaded
from the URL in `chopper-tests/SOURCE.json`. Its extracted 917-byte corpus covers
legacy 0.4-0.7 and a modern 0.8 control; `expected.txt` contains its exact 1,195
decoded bytes. The original source notice and the package BSD-3-Clause license
apply. Extraction hashes preserve provenance; do not regenerate these fixtures
from a current encoder or silently edit expected output.

Re-audit the complete reachable allocation/free paths, C callback ABI, ownership
and allocator alignment when changing sources, features, dependencies or decoder
settings. Include this entire directory in build provenance. Run shared
native/WASI allocation-failure, version-switch, format/byte, window-limit and
cancellation controls, plus unpatched/patched compatibility checks. Resource
denial must never become a successful partial scan or bypass the ledger.
