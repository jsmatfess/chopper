## Borrowed UTF-8 spill validation and copying, 2026-10-15

Intermediate balanced-split scans and encoded intermediate merges now validate
field text directly in borrowed reader chunks. A field spanning buffers retains
only its incomplete UTF-8 scalar in a **four-byte stack array** (at most three
pending bytes between reads). It does not allocate a field-sized scratch vector.
The short-field path is inlined and performs one UTF-8 validation and callback;
the boundary state machine is separate. Encoded merges write each chunk directly
to their already-buffered temporary destination instead of copying, zero-filling
and validating a reusable field vector. Final decoded consumers and CSV input
parsing retain their existing paths.

Field/key framing, field-count and cumulative payload limits, truncation checks,
UTF-8 validation and v1 shuffle/collision order remain unchanged. Pending scalar
bytes cannot cross a field boundary. A merge can write a prefix to its temporary
file before discovering later corruption or an I/O error; that failed merge
propagates the error and discards the file. It never publishes that prefix.
Existing malformed-spill, cancellation, disk-budget, exact-cap and cleanup tests
remain passing. The merge's conservative winning-row reservation remains in
place; this change does not select larger fan-in or claim complete allocation/RSS
accounting. Parser/decoded-input capacity and conversion overlap remain open.

The new differential tests cover all 256 one-byte and 65,536 two-byte inputs,
valid Unicode boundary code points and every prefix of a mixed UTF-8 corpus,
buffer sizes 1/2/3/4/7/64, overlong encodings, surrogates, values beyond Unicode,
invalid continuations, truncation and injected write failures. They compare
acceptance with `str::from_utf8`, exact copied bytes and the following field's
untouched sentinel. The existing scanner/owned/compact decoder differential test
still checks every truncation of a framed Unicode record, malformed lengths,
cumulative limits and tiny reader buffers. A new real WASI contract carries
roughly 84 KB multibyte fields (including quoted CRLF/text) through intermediate
balanced splitting and partitioning; it checks exact expected group/text order
and encoded byte caps/counts across a split Unicode scalar.

The [initial native](../../evidence-originals.md#sha256-f6ea5f01835a00077e842c7bf92430fcfaf705b7fdf403a25bc1a0b91e1f85eb "Original: docs/benchmarks/field-stream-initial-native-2026-10-15.jsonl"),
[initial multi-level](../../evidence-originals.md#sha256-e2c124b24a5d79dd90f271296effa3f4e7794c7bdc5b44bf81e2b859b1c03e3c "Original: docs/benchmarks/field-stream-initial-multilevel-2026-10-15.jsonl")
and [initial boundary](../../evidence-originals.md#sha256-35bea9e681d43dc33180855d57fdeb76b5977025d6629e3c1ca0d688d0b261c5 "Original: docs/benchmarks/field-stream-initial-boundaries-2026-10-15.jsonl")
experiments contain 96 alternating timed jobs and 32 allocation censuses. Exact
output/metadata matches, and wide scans remove 1,800,000 requested bytes, but
one-worker intermediate-wide median seconds rise **0.920 → 0.968**. Even the
resident control, which does not use this helper, rises **0.560 → 0.592**; these
warm WSL timings include variability rather than isolating a causal effect.
The final candidate separates the inlined common path from the boundary state
machine; initial binaries remain saved in `/tmp/chopper-field-stream-initial`.

The final [native](../../evidence-originals.md#sha256-1c16ff44a2ca5e1c896a9119a250866ede001789c49ee6e29cc159293f141140 "Original: docs/benchmarks/field-stream-native-2026-10-15.jsonl"),
[multi-level](../../evidence-originals.md#sha256-602a742c2230c51cd0bcb6e528c326b23cdc258ede6b04ba8f7f57e42b18cf1e "Original: docs/benchmarks/field-stream-multilevel-2026-10-15.jsonl") and
[boundary](../../evidence-originals.md#sha256-fed96ad9bdb7e602dbc6068f2c3db87ca1d2959956c49c932c562fec019b5aef "Original: docs/benchmarks/field-stream-boundaries-2026-10-15.jsonl") comparisons repeat
another **96 alternating timed complete jobs and 32 allocation censuses** against
the preceding retained-path build: 300,000 rows for controls/streaming/boundaries,
1.3 million for multi-level merges, 33 fields, one/four workers and three
repetitions. Every CSV byte/order, output name/lineage, stage and logical digest
matches. Run/merge counts, logical temporary reads/writes, file counts and peak
workspace reservations are unchanged on the tested jobs.

| Complete job | Workers | Median seconds before → after |
| --- | ---: | ---: |
| plain control | 1 / 4 | 0.328 → 0.335 / 0.318 → 0.321 |
| resident random-key control | 1 / 4 | 0.563 → 0.595 / 0.533 → 0.538 |
| intermediate shuffle, rare wide | 1 / 4 | 0.911 → 0.916 / 0.912 → 0.918 |
| streaming, forced sorting | 1 / 4 | 1.471 → 1.483 / 1.489 → 1.493 |
| multi-level global shuffle | 1 / 4 | 3.645 → 3.636 / 3.690 → 3.580 |
| multi-level shuffle plus balanced | 1 / 4 | 3.618 → 3.521 / 3.623 → 3.563 |
| balanced plus partition, many columns | 1 / 4 | 0.995 → 0.970 / 0.964 → 0.973 |
| balanced plus partition, rare wide | 1 / 4 | 0.970 → 0.973 / 1.013 → 0.968 |

In the final run, wide-pipeline medians are within 1% of baseline; timings remain
mixed, including the slower one-worker resident control. These uncontrolled warm WSL runs do not establish a general speedup.
In the one-worker allocation censuses, wide boundary jobs and intermediate-wide
shuffle jobs each remove one allocation
and **1,800,000 requested bytes**. Ordinary boundary/forced-streaming jobs remove
one allocation, two reallocations and 15 requested bytes; multi-level jobs remove
one allocation, one reallocation and 13 requested bytes. Plain/resident control
allocation profiles are identical. Whole-process peak live requested bytes are
unchanged throughout: removing later scratch does not remove the earlier parser/
consumer peak. This is lower transient allocation/copying, with no full-memory-cap
or new automatic resource-selection claim. Full timing ranges, CPU, RSS and
profiles remain in the raw records.

```sh
python3 scripts/benchmark-compact.py \
  --before /tmp/chopper-field-stream-before/chopper \
  --after /tmp/chopper-field-stream-after/chopper \
  --before-allocator /tmp/chopper-field-stream-before/allocation-profile \
  --after-allocator /tmp/chopper-field-stream-after/allocation-profile \
  --rows 300000 --repeats 3 --workers 1 4 \
  --cases plain resident uniform_pipeline_wide streaming_pipeline_sort
# Same arguments with --rows 1300000 --cases spill fused_balanced_spill
# Use benchmark-boundaries.py with --rows 300000 --cases columns rare_wide
# Initial candidate: substitute /tmp/chopper-field-stream-initial for --after.
```

The [large native/WASI replay](../../evidence-originals.md#sha256-e7b14e2896570f575a621858cac39fcf8ffabf4b19bf9f1fffed7c505d911d39 "Original: docs/benchmarks/field-stream-multilevel-browser-2026-10-15.jsonl")
adds six verified complete jobs: 1.3 million rare-wide rows, 32 MiB, two shuffles
with downstream balanced splitting, before/after, one/four native workers and
single-worker WASI. Exact bytes/order, unique-ID conservation, group/output
metadata and logical digests match across all variants. Native seconds before →
after: **5.941 → 5.788** (one worker), **5.953 → 5.797** (four); WASI:
**77.630 → 78.929**. This single repetition tests the multi-level borrowed-copy
path in WASI; it is not an estimate of browser timing variability or a browser
speedup. OPFS operations are recorded separately from physical I/O.

Final validation: **117 workspace tests**, **40 combined-feature library tests**,
formatting, all-feature Clippy, TypeScript, native/WASI release builds and all
**24 Chromium/WASI contracts** pass. [Browser contract record](../../evidence-originals.md#sha256-16dc70decf1686c3b0eeb94078f63908b9af7d4a944ee7fd2c1618e4eecdbc3b "Original: docs/benchmarks/field-stream-browser-2026-10-15.json").
No seeded algorithm, spill format, default strategy or publication behavior changes.

```sh
LD_LIBRARY_PATH=/tmp/chopper-browser-libs/root/usr/lib/x86_64-linux-gnu \
  node scripts/benchmark-external-browser.mjs \
  /tmp/chopper-field-stream-before/chopper /tmp/chopper-field-stream-after/chopper \
  /tmp/chopper-field-stream-before/engine.wasm /tmp/chopper-field-stream-after/engine.wasm \
  1300000 1 rare_wide multistage before,after 1,4
```
