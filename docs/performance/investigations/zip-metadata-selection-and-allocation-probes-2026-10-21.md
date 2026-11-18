## ZIP metadata selection and allocation probes (2026-10-21)

This diagnostic tests the three metadata-selection assumptions identified by the
[source audit](../../resource-policy-research.md#zip-input-metadata-ownership-audit-2026-10-21)
before implementing a decoded ZIP owner. The decision is whether Chopper's
current final-EOCD eligibility expression can bound the metadata actually decoded
by the pinned `zip` 2.4.2 reader. It cannot on these executed fixtures. No parser,
admission default, ZIP compatibility policy or metadata grant is changed here.

[probe-zip-metadata.py](../../../scripts/probe-zip-metadata.py) generates five fixtures
below 10 MiB, each selecting the same one-row/two-column CSV. It invokes the
unchanged no-feature allocation-profile binary pinned in the
[original build record](../../evidence-originals.md#sha256-b808813ddd67adb5d5af2484ec15efb4bb96b399b37ac679dee6b5a7fad655f9 "Original: docs/benchmarks/profile-current-calibration-builds-2026-10-21.json"),
with a 32 MiB job budget, one worker, and separately configured 1/128 MiB shared
ceilings. There is one fresh-process census per fixture/ceiling, not timing
repetitions. The [initial pass](../../evidence-originals.md#sha256-79cc64be6c751e513f256f436bb02f8b1ce5246a6861d5da72ee53aac4dff0c3 "Original: docs/benchmarks/zip-metadata-selection-probe-2026-10-21.jsonl")
and its [exact harness snapshot](../../benchmarks/zip-metadata-probe-initial-harness-2026-10-21.py)
are preserved. A subsequent [deterministic-fixture pass](../../evidence-originals.md#sha256-ca77e7129d5fbc38ff655d79cebcf9df1a73a3f0e701b139a2ba0ec9b4d17eb6 "Original: docs/benchmarks/zip-metadata-deterministic-probe-2026-10-21.jsonl")
pins ZIP timestamps so the browser can consume the exact same archive bytes.
The two passes are separate observations, not additional statistical samples.

The ordinary 8,193-entry archive is rejected at both ceilings by the existing
4 MiB `directory_length + 512 * entry_count` eligibility check. Appending a
malformed final EOCD declaring one entry and zero directory bytes instead
succeeds at both ceilings: the dependency discards that candidate and reads the
earlier directory. Its process peak live requested bytes are 4,458,260, while the
successful-scan reservation peak is 119,274 bytes. This executes the selection
mismatch; it is not a new claim that the incomplete ledger bounds process memory.

A single long UTF-8 member with its EOCD directory length changed to zero also
profiles successfully. This confirms that the chosen entry count, rather than
that length field, drives actual central-record decoding. A ZIP64 fixture with
an independent 8,388,608-byte extensible sector succeeds at both configured
ceilings, with process peak live requested bytes 8,476,485 and successful-scan
reservations 119,263 bytes. The plain CSV control has process requested peak
70,599 and scan reservations 111,069 bytes. These are complete-process allocator
censuses versus scan-ledger observations, with different scopes; they are not RSS,
simultaneous component sums or exact attribution of every byte to ZIP metadata.
Allocation instrumentation perturbs execution and establishes no speed effect.

[probe-browser-zip-metadata.mjs](../../../scripts/probe-browser-zip-metadata.mjs) then
profiles the exact deterministic fixture bytes through the public browser client,
real engine worker and OPFS in a fresh temporary Chromium context. The
[final browser report](../../evidence-originals.md#sha256-24955975e1390ef40eca0fe1a69bb573f3a0c255f71b9fe2ea3afe7bbba53425 "Original: docs/benchmarks/zip-metadata-browser-probe-2026-10-21.json")
reproduces the same outcomes: ordinary-many-entry rejection, and successful
fallback, underreported-length and ZIP64-extension inputs. Successful profiles
retain the expected CSV header/shape; every workspace is removed and no output
directory is requested. It supplies no browser allocation/RSS or persistent-profile
device evidence. Its [initial successful report](../../evidence-originals.md#sha256-73bf5eb5047951283615b18e4130dca20dc07b6504f544bd4a0827deed880508 "Original: docs/benchmarks/zip-metadata-browser-initial-2026-10-21.json")
is retained separately from the final harness, which also guarantees fixture
cleanup after setup failure. Same-origin test routes preserve isolation/CSP and
add no test assets to the hosted package. The
[derived summary](../../evidence-originals.md#sha256-1f78c97ed9e0776b11a3c2eb6d84486e22761bc58d373a55243f1d06af53ca5d "Original: docs/benchmarks/zip-metadata-probe-summary-2026-10-21.json")
binds native physical lines, browser JSON pointers, source hashes and identical
fixture SHA-256 values; the cases are not pooled into a performance estimate.

Decision: the ZIP metadata ownership gap remains open, now with executable
native/WASI compatibility cases. A grant derived only from Chopper's selected
EOCD would miss accepted fallback directories, actual central records and ZIP64
extension allocations. The ownership boundary must follow the parser's actual
selection/allocation points, or establish an equivalent conservative bound
including fallback, before construction and through archive/member destruction.
The public archive API hides construction capacities; a reader heuristic based
only on requested read sizes is not yet a proven replacement for that seam.
Do not silently remove the accepted forms to make an accounting test pass.
Long CP437/comment/extra-field growth, shared denial/release/EOF/error lifetimes
and full allocation-envelope proof still need implementation/acceptance in
[TODO](../../../TODO.md). The diagnostic only asserts profile shape and cleanup;
recorded acceptance/rejection outcomes are observations, not a permanent gate
requiring the current missing accounting.

Reproduce with `python scripts/probe-zip-metadata.py --allocator ALLOCATOR
--build-record BUILD.json --work-dir DIRECTORY --output NEW.jsonl`, using the
original matching baseline build record. After hosted build and Chromium setup,
`node scripts/probe-browser-zip-metadata.mjs` runs the same generator and public
browser cases. Both commands run from the repository root; the native output
refuses overwrite. All raw rejections and successful censuses are retained.
