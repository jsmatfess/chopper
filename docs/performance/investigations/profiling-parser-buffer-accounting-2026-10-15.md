## Profiling parser buffer accounting (2026-10-15)

Full-file input profiling now uses the same reserved owned CSV parser as job
ingestion. A scan-local workspace follows the existing half-memory-budget policy;
profiling still needs no temporary directory or preparation Context. Fixed UTF-8
reader and decoder storage are reserved before constructing the decoder. Parser
scratch, string/descriptor capacity and old/new growth/shrink overlap are reserved
before allocation. The retained header keeps a separate charge until the scan
returns. Data-field storage is reused across records, preserving v1 previews,
full-file validation, distinct counts and cache behavior.

This closes the **live profiling parser** slice of the accounting backlog. It does
not account for retained/cache-returned profile metadata, profile clones, previews,
value sets/sketches, codec internals, simultaneous jobs or runtime allocations.
Header ownership transfers to the returned profile after the scan; its reservation
does not persist in the cache. Decoded intermediate buffers, remaining conversion
and sorting overhead also remain open. This is not a complete memory/RSS cap and
does not change shuffle algorithms or selection policy.

Validation: 129 workspace tests and 47 combined experimental-feature library tests
pass, as do formatting, Clippy with warnings denied, TypeScript, native/WASI release
builds and 24 real Chromium/WASI contracts. Three new tests check just-below/at/above
observed allocation peaks, competing reservations, retained header descriptors
through scan completion, late-wide/many-column/headerless/empty input, malformed
and oversized records, cancellation and release on every exit. Existing profile
contracts cover gzip/UTF-16, source replacement, cache invalidation and refusal to
cache partial scans. Loopback-server tests require the local binding permission;
Chromium uses the already staged `/tmp/chopper-browser-libs` libraries.

The new `scripts/benchmark-profiling-budget.mjs` alternates baseline/candidate and
native/Chromium-WASI profiles and independent complete jobs. It checks every
profile field except elapsed time/cache-hit identity, then verifies fresh/cache
content equality in the browser. Complete balanced → partition → uniform-shuffle
jobs compare output bytes/order, names, row counts, CSV bytes, lineage, stage
statistics and logical digests. Profiles do not authorize those jobs; preparation
still runs independently. Native profile CPU/RSS are measured with GNU time;
browser cache replay and scan/wall times are recorded separately. Instrumented
allocation censuses and browser CPU/RSS are not measured in this pass.

Fixtures use presorted IDs, four or 33 fields, and a late 1.8 MB UTF-8 field,
32 MiB configured memory, a 2 MiB record cap and one worker. Three repetitions on
100,000 rows give 36 fresh profiles, 18 cache replays and 36 complete jobs. A
128-row single-repetition control adds 12 fresh profiles, six cache replays and
12 complete jobs. All 120 checks pass. These are warm, uncontrolled WSL filesystem
and OPFS measurements; physical SSD traffic/cache calibration remains unmeasured.

Median seconds on the 100,000-row fixtures:

| Shape | Native profile before → after | Browser profile before → after | Native job before → after | Browser job before → after |
| --- | --- | --- | --- | --- |
| Four fields | 0.0274 → 0.0288 (+5.0%) | 0.0526 → 0.0630 (+19.8%) | 0.1755 → 0.1815 | 0.7704 → 0.7757 |
| 33 fields | 0.1191 → 0.1246 (+4.6%) | 0.2482 → 0.2893 (+16.5%) | 0.4063 → 0.4085 | 3.9775 → 3.9643 |
| Late wide | 0.0324 → 0.0354 (+9.3%) | 0.0732 → 0.0949 (+29.5%) | 0.1906 → 0.2077 | 1.1795 → 1.2805 |

Fresh profiling has an accounting cost; no speedup is claimed. Browser scan-only
medians cost 14.1–19.6%, with startup/polling contributing to wall time. Browser
cache replays remain around 11 ms. Independent complete-job timing shifts are
mixed, including slower wide controls, although this step changes no production
job-ingestion/operation path. Three uncontrolled repetitions cannot establish a
job throughput change or a precise memory reduction from process RSS. Raw ranges,
native CPU/RSS, build hashes and diagnostics are retained in the
[main run](../../evidence-originals.md#sha256-9d7bc3a2c400fb8716ff4dbfa2368328ee056ba86bbc2556a8fc618b30cff862 "Original: docs/benchmarks/profiling-budget-2026-10-15.jsonl"),
[tiny controls](../../evidence-originals.md#sha256-ceac1506711ab5dd1407c2432e2ed5fe54da6e808357d964a1388a5be4179ecc "Original: docs/benchmarks/profiling-budget-tiny-2026-10-15.jsonl") and
[summary](../../evidence-originals.md#sha256-c75d483172ec60cf6dbea4017047e39a97cb505f05e2e02a137610dca3d00ca0 "Original: docs/benchmarks/profiling-budget-summary-2026-10-15.json").

Reproduction (save baseline native/WASM builds before applying the change; build
the candidate release CLI and hosted engine before running):

```sh
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-profiling-budget.mjs \
  /tmp/chopper-before-profile-budget /tmp/chopper-before-profile-budget.wasm 100000 3
# Repeat with 128 1 for tiny controls.
```
