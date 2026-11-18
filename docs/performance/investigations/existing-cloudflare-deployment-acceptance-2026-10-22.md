## Existing Cloudflare deployment acceptance (2026-10-22)

The [deployed-site pass](../../evidence-originals.md#sha256-04ff46b4757aa4d115812187e75887797619944325085dad11e80ff90825e54a "Original: docs/benchmarks/hosted-deployment-acceptance-2026-10-22.json")
checks the user-supplied [Cloudflare Pages site](https://chopper-1rx.pages.dev/)
in installed Chrome 155.0.8059.85 on Windows. HTTPS startup succeeds with real
cross-origin isolation, SharedArrayBuffer, OPFS, Web Locks and the required
file/folder picker APIs. HTML, app, engine/storage workers and WASM return 200
with the isolation/security headers; their hashes stay unchanged during the
pass. The WASM has no resource-contract entry point. Test-asset paths return the
same HTML app fallback as `/`, rather than test HTML or a WASM binary. Its WASM SHA-256 is
`f6a7673e6abbe5ab0d0a13087dc4ebd539439d1615a30000ad0de5a36989a014`;
it differs from the checkout's current production build and lacks APIs
such as profiling. This is acceptance of that deployed artifact, not current-build
deployment validation. No site was published or changed.

Only the picker results are replaced: a synthetic five-row File includes Unicode,
quoted multiline text and an empty field, and a unique same-origin OPFS parent
contains an unrelated sentinel. The real deployed UI prepares three CSVs under a
two-row cap and reports 96 serialized CSV bytes. Before confirmation the parent
contains only its sentinel. Confirmation exports exact canonical CSV bytes in
row counts 2/2/1 (46/27/23 bytes), a matching manifest and a valid v1 completion
marker counting four result files. Captured browser requests are GETs with no
request payload; the fixture is processed locally.

The first verifier expectation incorrectly left the empty field unquoted.
Inspection confirmed correct canonical serialization; the rejected attempt and
corrected expectation remain in the artifact. A preflight reload had abandoned
one earlier startup workspace in the disposable context. The deployed cleaner
removes it, leaves no workspace entries and preserves every committed result
hash and the unrelated sentinel. The test-created destination is then removed.
The standalone test browser closes; the separate collaborative-preview startup
is cancelled and its tab closes. Two collaborative snapshot timeouts are recorded;
the end-to-end acceptance uses the Playwright CLI fallback, not those snapshots.

This closes a small existing-deployment startup/preparation/export/cleanup smoke
check. It does not establish current-build deployment parity, picker permission
dialogs, external filesystem export, quota/device failure, other browser/OS
deployment combinations, large hosted jobs, power-loss durability or physical I/O.
The local browser-channel acceptance above remains a separate build/runtime pass.
