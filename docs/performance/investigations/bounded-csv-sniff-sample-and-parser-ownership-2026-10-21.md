## Bounded CSV sniff sample and parser ownership (2026-10-21)

The [sniff ownership pass](../../evidence-originals.md#sha256-001e5a51a7523874bc2350b736bdb63d00ac634ced657a0d04ca6948351d0c65 "Original: docs/benchmarks/sniff-inspection-resource-validation-2026-10-21.json")
adds admission for the raw sample, decoded UTF-8 sample and each candidate CSV
parser's scratch/row capacities. These owners share inspection and input-adapter
admission. Vector growth charges old/new capacity overlap before allocation;
EOF and truncation retain the allocation's charge until its owner drops. Raw
storage is released after decoding, while the decoded sample stays charged
through delimiter scoring. Scalar counters replace the previous widths vector.

Sniffing still reads at most 65,536 decompressed bytes. BOM inference, full-sample
incomplete-tail trimming, strict decoding, line-ending detection, preserved
header/quote/escape options, delimiter order/ties, the 90% consistency threshold
and the 50-record scoring limit remain unchanged. Ordinary CSV syntax/record-limit
errors retain their previous optional-scoring behavior. Typed memory admission
errors propagate instead of silently producing a different dialect suggestion;
retry requires a fresh source and owner after the conflicting owner is released.

Shared native/WASI controls verify three local denials, four shared denials and
four fresh release/retries, including raw/decoded reallocation overlap and parser
denial propagation. Twelve BOM/boundary cases and five strict-decoding cleanup
cases pass. A source error after a charged first chunk unwinds to zero; interrupted
reads retry. One-byte fragmented reads preserve JSON and grow capacity only when
needed. A counting source verifies the sample cap. All final reservations are
zero. Base and candidate WASI sniff reports match: separate phase peaks are
24,576 bytes for raw growth, 57,341 for overlapping raw/decoded ownership and
155 for decoded sample/candidate parsing on their declared fixtures. These are
separate controls, not simultaneous peaks or universal capacity requirements.

Public native integration checks pass through plain, gzip, Zstandard and ZIP
adapters using signature detection with `.data` paths. UTF-16BE/BOM, quoted
semicolon/CRLF, explicit headers and the column picker agree. An invalid UTF-8
byte immediately beyond the decompressed sample cap is not decoded. Inspection
creates no job output or temporary workspace.

The frozen 106-file compilation inventory matches before/after validation.
Full default Windows and Linux workspaces pass, including 138 and 140 library
tests respectively and both new integration tests. The recorded 17-feature
library pass contains 218 tests. Formatting and default/17-feature all-target
workspace Clippy pass. Standard 25-browser contracts, bridge and both real
Chromium/OPFS resource reactors pass, including existing retry/publication/export
contracts. The final production WASM SHA-256 is
`bf8541618bbfc35b4cc7cf6709e66cc9546f09230e0c261b4e50e53ff198b682`;
cleaned hosted packaging passes the production export guard with no test assets.
Initial compile failures are preserved separately from successful acceptance.

This is working-allocation correctness evidence, not a throughput comparison or
RSS cap. Returned JSON/configuration clones, inline decoder/chunk/stack storage,
codec internals and decoded ZIP metadata remain outside the slice. It establishes
no quota/device/deployment or cross-worker/tab coordination claim and changes no
execution default.
