# Shuffle and tooling integration

The owner authorized main delivery of both reviewed branches on 2026-11-16.
This revision combines the optimization head
`5146193aa09c770fc0e1c2ad266cff23ffae37db` and tooling head
`c0301ed737925701de8c5db5abbd65e6d522dd2f`, based on main
`de93a7a728fd8652f01627b1d1483409ed499455`.

Ordinary builds retain adjacent unstratified exact-assignment range fusion and
narrow Auto/Uniform → Fisher–Yates elision together. The adaptive-ingestion pilot
remains rejected, and direct shuffled balanced parts remains deferred. Their
[dated investigation](performance/investigations/shuffle-swarm-decisions-2026-11-15.md),
proofs, measurements, exclusions and private originals remain unchanged. The
current decision registry records default delivery in this revision; the dated
investigation preserves its earlier awaiting-delivery context. No new performance
observations or broader eligibility are added by integration.

The [tooling follow-up](tooling-follow-up-2026-11-16.md) supplies artifact selection,
focused CI routing, Linux runner completion/cleanup, frozen campaign separation
and byte-preserving historical harness organization. Engine and tooling source
retain their reviewed branch versions. Shared workflow entries and documentation
retain both changes; evidence navigation is regenerated from the combined inputs.

Delivery uses `python3 scripts/local-ci.py land`. It validates the committed
combined head against fetched main and requires its matching native Windows
receipt before the guarded fast-forward push. Earlier branch receipts remain
historical; they cannot qualify the combined head. The local-CI receipt and its
full logs identify the actual tested/landed head and base.

Final packaging uses the default production WASM and test-free hosted bundle.
Native Windows correctness does not establish Windows performance or ordinary
runner whole-tree completion. No macOS, additional browser/device, new scale or
release qualification is added. The inherited parser shrink-overlap accounting
gap remains in [TODO](../TODO.md). Frozen acceptance sources/services and private
raw evidence remain unchanged; public deployment is separate from main delivery.
