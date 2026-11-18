## Direct input snapshot rejection and removal (2026-10-26)

Astra separately rejected retention of **compact** and **IPC** live direct snapshot
integrations before the distinct R25 removal authorization. The exact reviewed
[disposition](../../evidence-originals.md#sha256-3878d6fb31d9794e643e13c43a3a223066ee63ecbdfa21d26c4839c6ea0815e0 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-astra-disposition.md"),
[R24 report](../../evidence-originals.md#sha256-91b1479d51098723713af8da518f7e591355361650579cd53f32e9a5f0e1b65d "Original: docs/benchmarks/e3-direct-r24-2026-10-26-round-report.md") and
[all repetition/resource rows](../../evidence-originals.md#sha256-4ec5f5a2781db3966ae17848f2697e15cb0da5f35c3656f3e52c1826c87bf015 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-repetitions-and-resources.md")
are preserved byte-for-byte. The [copy source map](../../evidence-originals.md#sha256-0c60979cd28dcefba3098182488b39fe62a1fc0a274b6f74dcfd27321822d6f6 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-source-map.json")
records original paths and SHA256; reports retain original relative-link meaning.
The original disposition remains `.tools/e3-measure-20261026-r24/astra-disposition.md`,
SHA256 `3878d6fb31d9794e643e13c43a3a223066ee63ecbdfa21d26c4839c6ea0815e0`.
This is evidence-supported removal, independent of historical CSV-bridge losses.
No requested interoperability capability, numeric selection threshold, Auto/default
change, typed expansion or Parquet decoder is introduced.

R24 contains 24 sequences, 60 completed jobs (four imported prior CSV jobs plus
56 new jobs), 12 conversions and three matched pairs per candidate/shape cell.
Native Windows warm-read runs use 100000 rows: many 33 columns/K4 and rare-wide 4
columns/K1; uniform-v1 then balanced 4, seeded_v1, seed `format-experiment-v1`,
sort, 32 MiB job memory, one worker, 64 MiB shared pool. Maximum record 2097152,
files 100000, temporary 536870912 and conversion 134217728 bytes; row cap 30000 and
strict serialized CSV cap 4194304 bytes. UTF8/header/LF/no BOM/no compression.
Many SHA256 `46b6372ef9c1184f7ca149c4ef0dfbde4ad46f8f341bfcab8bd53050997e3ca3`;
rare `a60032bb8c1934550e38f3974f74ef2891f29a038ceaa342dfb6aa8b9c37ff29`.
The report/pins retain actual driver/native/WASM, upstream, full-vendor and source
identities. No cold flush was performed; no physical-device inference follows.

Compact loses every measured whole pair. Many first medians CSV 0.404650600s versus
compact 0.550494800s; K4 whole 1.553610800s versus1.770157400s. The interrupted first
compact-many pair has a timestamp-based gap lower bound 13893.082523s; the exact
gap is unknown. Separate n2 sensitivity excludes both sides: whole medians
1.524744650s versus1.767699850s with nonoverlapping observed ranges. Rare-wide K1
whole medians 0.164615000s versus0.235114100s (n3). Many reservation peak about 8.60MB
CSV versus 10.59MB compact; replay logical reads 45,566,327 versus 84,499,139 bytes/job;
persistent artifact 19,466,406 bytes. Complete samples/ranges remain in raw summaries.

IPC separately loses every measured whole pair. Many first medians CSV 0.369740700s
versus IPC 0.636083500s; K4 whole 1.553316000s versus1.821397500s; rare-wide K1
0.160197100s versus0.228078500s (n3). Many reservations about 8.60MB CSV versus 10.10MB
IPC; replay logical reads 45,566,327 versus 84,751,419 bytes/job; artifact 19,593,282
bytes. Repeated isolated intervals are mixed/overlap; neither candidate earns a
useful amortized gain from them. Do not extrapolate break-even at untested reuse
counts or claim either format universally loses. Samples are small, one seed,
pipeline/resource setting and two fixtures, with separate interrupted sensitivity.

Clocks include evidence serialization/fsync: two Analysis/live Context writes per
job, plus Created once per candidate (K4 candidate 9 versus CSV 8, K1 candidate3 versus
CSV2). No cost is subtracted and these are not instrumentation-free application
clocks. Whole-child CPU is not sequence-only CPU; requested 20 ms sampling plus scan
overhead yields lower-bound RSS/space peaks, not exact peaks. Reservations are not
RSS, logical/process transfers are not physical I/O, and independent peaks cannot
be added. Resource gates, exact corresponding CSV bytes/fields/membership/caps,
source/cache bindings and owner release passed in their recorded build scope.
W11 optional validated-audit owner equations and shared last-clone semantics remain.

Historical limits remain: 94 inaccessible records unknown; R8 original failed ZIP
lost; R13 first two layout manifests noncontemporaneous; R19 initial smoke failure;
R21 full wrapper-log limitation; R22 external verifier failure followed by R23
reverification of the unchanged retained four jobs. R23 modified generator copy
is not original generation provenance. Original R19/R20 generators are authoritative.
No historical failures, source/binary snapshots, pinned inputs or commands are edited.

R25 removes only the direct snapshot module/compact and IPC construction/replay,
its dedicated seven source/test files, diagnostic feature gate, artifact-reader
helper, native/browser feature forwarding and exclusive Arrow dependencies.
There is no independent surviving Rust Arrow consumer. Generic compact intermediate
and spill-block storage, CSV ingestion/parser, comparison/merge fallback and generic
correctness/resource/publication/cancellation coverage remain. Active shared
benchmark harnesses have no direct snapshot API cases; R19/R20 dedicated drivers
remain historical, archived with replay prerequisites. Removed Cargo controls fail;
removed direct Rust APIs fail compilation. Migrate to ordinary direct CSV Job input.
The [archive](../../history/rejected-input-snapshots-2026-10-26/README.md) maps exact source
copies, full integration baseline and necessary replay inputs. Verification and
packaging status are recorded separately in [validation](../../validation.md#direct-input-snapshot-removal-2026-10-26).
E1 remains unresolved/opt-in; E4/E5 untouched. Astra accepted the R25 implementation
and raw verification and the R26 final documentation diff. E3 is complete. The historical
R24/R25/R26 reports retain their original status wording unchanged.

Raw R24 navigation (copies preserve exact original payloads and origin pointers):

- [Controller completeness](../../evidence-originals.md#sha256-5d02f6e72d92fec201999b494289e9c28fdb8469d6b1a876513c5fa510a876c4 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-controller-complete.json")
- [e3-direct-r24-2026-10-26-analysis-checks.json](../../evidence-originals.md#sha256-b0e9a9f7425c1aa62478a10adde72685d8f79dba3566f0ba4997b81916bb9b38 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-analysis-checks.json")
- [e3-direct-r24-2026-10-26-baseline.json](../../evidence-originals.md#sha256-1e41e831d588335a80bd6897d2414728379c9a9460c8ada6ecb97e7e346e6975 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-baseline.json")
- [e3-direct-r24-2026-10-26-final-scope.json](../../evidence-originals.md#sha256-864ecbe8bb7786389421b41dbcfaa62b97545ffdafb80377da546d51e0437214 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-final-scope.json")
- [e3-direct-r24-2026-10-26-history-before.json](../../evidence-originals.md#sha256-78baed894cd29155ee3129a6a280067493da2b0e2cfb125230680bc34154c2a4 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-history-before.json")
- [e3-direct-r24-2026-10-26-hosted-before.json](../../evidence-originals.md#sha256-acd6d71f778865b1adf5275bd09959a487872a5c6711c0edc57e1131c7047b0c "Original: docs/benchmarks/e3-direct-r24-2026-10-26-hosted-before.json")
- [e3-direct-r24-2026-10-26-observations.json](../../evidence-originals.md#sha256-9954f1cad8b8bffea8be471da01d6c31221df9a5f76ade895d2e0b01c5886941 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-observations.json")
- [e3-direct-r24-2026-10-26-pins-before.json](../../evidence-originals.md#sha256-418cd1d16375c1db4e6e5ecbacc99b6c56f859b76b6908073111f9c712ad05f6 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-pins-before.json")
- [e3-direct-r24-2026-10-26-preservation.json](../../evidence-originals.md#sha256-42ccc55f21836e68ad90ce86dbba3c9528c506225c30ba40e33755fc05e7073e "Original: docs/benchmarks/e3-direct-r24-2026-10-26-preservation.json")
- [e3-direct-r24-2026-10-26-python-identity.json](../../evidence-originals.md#sha256-735e03913a4106a7c09adb662b69817ce51966f7c5d05a9afd8c9f0ee27a378a "Original: docs/benchmarks/e3-direct-r24-2026-10-26-python-identity.json")
- [e3-direct-r24-2026-10-26-resources.json](../../evidence-originals.md#sha256-9b57f388b43e86425fab89b8c8d3d60c3ab4484dfa4623de2e07591181bddaab "Original: docs/benchmarks/e3-direct-r24-2026-10-26-resources.json")
- [e3-direct-r24-2026-10-26-sensitivity.json](../../evidence-originals.md#sha256-b04f5a6c07346ba767d9916da35b49cda2206d96973e15be53f255d19526426f "Original: docs/benchmarks/e3-direct-r24-2026-10-26-sensitivity.json")
- [e3-direct-r24-2026-10-26-source-map.json](../../evidence-originals.md#sha256-0c60979cd28dcefba3098182488b39fe62a1fc0a274b6f74dcfd27321822d6f6 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-source-map.json")
- [e3-direct-r24-2026-10-26-summaries.json](../../evidence-originals.md#sha256-720adaf6aeb42679c6e8ca459e270f80b1a1dd5451077b66aa0ca6e3dedb0028 "Original: docs/benchmarks/e3-direct-r24-2026-10-26-summaries.json")
