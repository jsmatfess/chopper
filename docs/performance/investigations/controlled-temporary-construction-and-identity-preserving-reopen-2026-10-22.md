## Controlled temporary construction and identity-preserving reopen (2026-10-22)

Temporary files and job/staging directories now use
[`storage/temp_path.rs`](../../../crates/chopper/src/storage/temp_path.rs) to pre-admit
one path buffer before name/path construction. Inline random scratch replaces
tempfile's separately allocated random name. Checked sizing, capacity
reconciliation and any boxing overlap precede filesystem creation; successful
boxed paths retain their grants through cleanup or native publication disarm.
Atomic creation, Unix file mode 0600 and Windows temporary attributes are
preserved. Up to 128 collisions reuse the path storage without attaching cleanup
to an existing name. Randomness/OS failure releases the constructed path.

Chopper also ports tempfile's reopen operation without its path-decorating error
wrapper: Windows reopens the original handle, while Unix/WASI compare the reopened
device/inode. Independent offsets are preserved. Native adversarial replacement
checks cover Windows handle identity and Linux inode rejection; WASI checks
independent offsets and raw missing-name failure, not adversarial replacement.
An identity mismatch returns bare NotFound rather than a filename-owning message.
Direct target dependencies use rustix/windows-sys versions already in the lockfile.
The [source audit](../../evidence-originals.md#sha256-b903cb030b315b07f7f0b9b036c06409754e457b84f0c1926ff9fc9b537c85a6 "Original: docs/benchmarks/temporary-construction-source-audit-2026-10-22.json")
pins constructor, platform and error-wrapper sources; the
[ownership document](../../resource-policy-research.md#controlled-temporary-construction-and-reopen-2026-10-22)
records the maintained boundary and exclusions.

The [initial Windows attempt](../../evidence-originals.md#sha256-3a1e45cbc8e8e5d8c17f48a235e104d3a326a2b2199bcec4dc2193a2d9c4ff24 "Original: docs/benchmarks/temporary-construction-final-validation-2026-10-22.json")
and [Linux attempt](../../evidence-originals.md#sha256-945f65438bd58418c0378f0afbf90a10642edd860c9858a292003f6bd2eb4c47 "Original: docs/benchmarks/temporary-construction-linux-validation-2026-10-22.json")
are preserved. A conservative error-path reservation around the library reopen
made five exact reader-capacity tests fail before their intended row/merge
boundary. The implementation now eliminates that copy instead; the original
reader budgets/assertions remain intact. This is not a weakened capacity contract.

The [final Windows record](../../evidence-originals.md#sha256-457615ed738b7e88e5078b42f5ba770b91ab7dd524350196747b6fd9c33f2ab6 "Original: docs/benchmarks/temporary-construction-reopen-final-validation-2026-10-22.json")
and [Linux/WSL record](../../evidence-originals.md#sha256-5a360ce0dd40b62cc4479ecc03c4ad3d24c84c34fe9fb8a75fc67baca98ab4f4 "Original: docs/benchmarks/temporary-construction-reopen-linux-validation-2026-10-22.json")
retain command output and source inventories. Shared native/WASI controls check
six local/shared admission edges, denial before filesystem entry, competing-owner
release/retry, preserved collision sentinels, retry exhaustion, random/OS failure,
invalid inputs and cleanup. Path construction matches `Path::join` for Unicode,
dot/parent components and trailing separators, plus native Windows drive, UNC and
verbatim cases. Existing directory, failed-unlink, catalog/reader, pipeline and
publication contracts exercise the new owners.

All 20 Windows and six Linux/WSL final-source commands pass with unchanged source
identities. The Windows pass includes 248 default workspace tests, 305
combined-feature Chopper tests, default/combined Clippy, printed resource/lineage
contracts, 28 UI tests/build, native/WASI releases, resource reactors in Chromium,
Chrome and Edge, the 25 production browser contracts and final hosted packaging.
The [binary/package record](../../evidence-originals.md#sha256-b315538c840e34712f305582c1c05fd3c96f4bc550fb67cbc0dda45b32107b3d "Original: docs/benchmarks/temporary-construction-package-identities-2026-10-22.json")
pins native test/release executables, harness source and seven production hosted
files, with the resource entry absent. Historical failed attempts retain their
own source inventories and are not counted as successful acceptance.

The [19-command production lifecycle pass](../../evidence-originals.md#sha256-23cf4b047931bfbf2f568c9c30ff723b821ca8a755f3b62ee39acb1e3799e7b1 "Original: docs/benchmarks/temporary-construction-browser-lifecycle-2026-10-22.json")
then passes storage-error bridging, real peer-tab/worker cleanup, temporary
interruption, persistent restart and forced browser-process termination/recovery
in Chromium, Chrome and Edge. Chrome/Edge also pass the 25 production correctness
contracts with this engine. Source identities and all seven production asset
hashes remain unchanged; final packaging removes test assets. Disposable profiles
and same-origin OPFS fixtures bound this acceptance. Native picker/external
destinations, real quota/device faults, arbitrary crash timing, power loss and
other OS/device coverage are not inferred.

Parent discovery/absolutization, OS conversions and syscall internals,
allocator/runtime/error-formatting storage, recursive deletion, codecs and native
stacks remain separate. This closes controlled name/path construction and removes
the reopen error-path copy; it is not complete runtime admission, an RSS cap,
macOS acceptance or a throughput comparison. The new local build is not published.
