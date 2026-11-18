## Retained job and staging directory path ownership (2026-10-21)

The [directory ownership pass](../../evidence-originals.md#sha256-7c46a081f4b024b3db27916904d1964aec09b7b12ecc30908fc264002f04e63c "Original: docs/benchmarks/directory-path-ownership-validation-2026-10-21.json")
implements the bounded owner identified in the
[temporary construction source audit](../../resource-policy-research.md#temporary-construction-ownership-audit-2026-10-21).
The shared workspace now exists before context-directory construction. Both
context and publication staging acquire a grant for the successful boxed path
before invoking the fixed-length tempfile builder, then retain it through the
actual directory owner. Provided absolute parents are borrowed; default discovery
and relative normalization remain outside this charge. Public `JobDirectory::new`
continues to wrap externally constructed, untracked directories for compatibility;
the engine's production context/staging callsites use the admitted constructor.

Directory cleanup transfers the existing path with `TempDir::keep`, invokes the
same `std::fs::remove_dir_all` primitive and reports failures while that original
path and grant remain live. This avoids the wrapper's cleanup clone and tempfile's
additional error-path decoration. Successful publication frees the old staging
path and disarms cleanup after commit, preserving the published directory.
Native directory publication remains distinct from WASI internal finalization
and the separately tested JavaScript copy/completion-marker protocol.

`directory_path_reserved_bytes` reports aggregate context and active staging
boxed-path ownership. A live idle context consequently has a nonzero reservation.
Exact verifier equations now include file paths, directory paths, retained input
header and validated optional audit ownership; unexplained extra bytes still
fail. Algorithm-boundary tests retain their original algorithm allowance with an
explicit additional directory baseline. Their test-only workspace transfer rejects
live algorithm or shared directory owners. Shared-process ceilings are unchanged;
final zero checks remain after the last owning context/directory is dropped.

Shared native/WASI contracts cover local/shared required-byte −1/exact/+1 edges,
one typed local denial, three typed shared denials, held sibling release and fresh
directory/staging retry, missing-parent cleanup, cancellation before creation,
early context failure, final `Arc` ownership, relative Unicode and trailing-separator
parents, unpublished staging removal and successful publication disarm. Both WASI
variants report identical fixture path charges: 47 context bytes and 56 staging
bytes, held simultaneously while staging exists and released to zero after final
ownership. These are fixture observations, not universal path sizes or an RSS cap.
Existing orphan-file/retry, UTF-16 cap, cancellation and browser export contracts
continue to pass with their exact owner equations.

The final 107-file compilation inventory is unchanged across final validation.
Full Windows and Linux default workspaces pass, including 139 and 141 library
tests respectively. The recorded 17-feature library passes 219 tests; focused
fast-RNG/flexible/streaming integration suites pass 4/6/12 tests. These counts
describe separate passes. Formatting, default/17-feature all-target Clippy,
25 standard Chromium contracts, bridge and base/candidate resource reactors pass.
Eleven portable verifier tests reject missing accounting and malformed charges;
a complete 1,000-row CLI job passes both resident/external output verifiers,
exact owner equality and staging/temporary cleanup. This is acceptance evidence,
not a new timing comparison. Earlier compile and old-baseline assertion failures
are retained with the successful final results.

The production WASM SHA-256 is
`c18a5139ebb5c0b960ad84cd5f62794f055cca66fbb23922bfc2615dfaa18ea3`;
the final hosted package passes the production export guard and contains no test
assets. Parent discovery/normalization, opaque tempfile construction scratch and
library error paths, filesystem conversion, recursive-delete internals, logging
and runtime overhead remain separate gaps. No full-constructor/RSS, physical-I/O,
deployment, cross-worker/tab coordination or new default claim follows.
