## Parallel gzip and ZIP output (2026-11-22)

The [human review report](../reports/parallel-compression.html) contains charts
of complete-job elapsed time. The [reviewed evidence projection](../../benchmarks/parallel-compression-summary-2026-11-22.json)
keeps the measured values, original line locations and SHA-256 identities.
Source changes and original runs remain local.

The baseline is `87df5c047a05eafc0e886da8524a69494329925d`. The final native
binaries come from `e1354d38eb965fccdb0ed172a3ac4caf94026198`. The primary
hosted comparison used the production engine and workers at
`48dd7a1b840e459482d6df939243250b9000a489`. The follow-up compared it
with the final hosted revision `efb13ed228dac513380982753df9e2707852d87a`.
The environment records pin executable and asset hashes. Timed runs used a
Ryzen 7 5800X, a Linux-filesystem WSL CLI, native Windows NTFS and bundled
Chromium with a disposable persistent profile and an OPFS destination.
One timed job ran at a time. CPU and elapsed time may still vary with
normal machine activity, and cache conditions were
warm and uncontrolled. CLI clocks cover process launch through successful
publication and exit. Hosted clocks cover Run through completed export and
the verified completion marker. Input selection and independent output
verification are outside the timed interval.

All compared fixtures are deterministic synthetic CSVs. Each verifies
ordered decoded bytes, row and output counts, manifest sizes, and the ZIP
member order and embedded manifest where applicable. The partitioned case
verifies each region separately through its two balanced children. These
are workload-specific comparisons. Workspace reservations, WSL process RSS, stored
bytes and logical temporary traffic have separate meanings in the raw
records.

### Screening

- First native screen
  recorded 72 verified jobs. The old streaming Auto context resolved one
  worker on both builds. Those cells do not measure parallel blocks. Its
  Python subprocess timeout also quantized elapsed time, so the corrected
  panel uses an enclosing runner deadline and a continuous clock.
- Native blocks
  exercised up to four slots within a file. On a 256 MiB CSV, median WSL
  elapsed time went from 10.73 to 2.90 s for gzip and from 10.83 to 2.90 s
  for ZIP. The heavier partition-to-balanced job saved about 0.5 s. The
  1 MiB controls used serial compression. Existing native file concurrency
  saved approximately 6 s on the 8-file and 256-file balances compared
  with an explicit single worker.
- Original hosted startup probe
  waited on nested workers created during synchronous WASI. The wait
  timed out, then serial fallback returned verified output. It incurred
  roughly 20 s of extra latency and remains diagnostic evidence. A revised
  smoke check
  initialized the codec workers before entering WASI and used four
  successfully.
- Hosted blocks
  cut median 256 MiB single-output time from 17.55 to 7.18 s for gzip
  and from 17.04 to 7.25 s for ZIP. Hosted file concurrency
  is useful for smaller members. On the 256-file panel, gzip went from
  19.72 to 11.68 s and ZIP from 20.33 to 11.83 s. The 8-file and heavy
  panels had comparable timings between the two parallel policies. Keep
  several slots available to a large member instead of splitting those
  files across slots and exposing a long, skewed member tail.

### Local decision and validation

On the final WSL build, a single 256 MiB gzip job fell from 10.84 to 2.89 s
and ZIP from 10.77 to 2.90 s. A strict 1 MiB cap generated 257 outputs and
reduced job time from 11.71 to 4.47 s for gzip and from 10.37 to 3.13 s
for ZIP. The existing three-writer native 256-file balance stayed near
the same elapsed time for both codecs. Prepared ZIP still cut about
104.6 MiB each of logical temporary writes and reads through admitted small
member buffering. Direct ZIP removed about 104.5 MiB of writes and reads
on the one-member job by backpatching the private archive.

On NTFS, the native 256 MiB gzip and ZIP jobs fell from 10.56 to 3.49 s
and from 10.64 to 3.52 s. At the 1 MiB cap, they fell from 11.44 to 6.44 s
and from 11.80 to 5.02 s. Prepared 256-member ZIP went from 5.92 to 4.57 s
and avoided 104.6 MiB each of temporary writes and reads. Native prepared
gzip used three writers on both builds. Windows medians went from
4.87 to 5.06 s in that cell, with no difference in stored bytes or logical
temporary traffic.

The 768 MiB WSL holdout used a distinct data seed and predeclared at least
ten seconds of savings. Median paired savings were 23.79 s for gzip and
24.21 s for ZIP. The held-out capture was on the same host and fixture family.

Chromium auto uses the codec workers within big outputs and across batches
of small outputs. One 256 MiB gzip and ZIP job fell from 17.57 to 7.14 s
and 16.98 to 6.71 s. A 1 MiB cap fell from 17.74 to 8.50 s and 18.16 to
7.43 s. The 256-member balance fell from 19.79 to 11.65 s and 20.38 to
10.41 s. For Partition → Balanced, the corresponding figures were
21.65 to 13.28 s and 21.84 to 13.24 s. A separate comparison tested two
Chromium builds with block compression, one keeping temporary compressed
ZIP members and one emitting directly into the archive. Staged ZIP took
7.19 s and streamed ZIP took 6.61 s. The streamed archive avoided about
104.7 MiB each of scratch writes and reads. Treat the smaller elapsed
change as directional because the two builds also vary in worker and
observation plumbing.

The final hosted batch scheduling finishes each large ZIP member before
opening another. On the 16-member composed job, the largest member held
6.54 MiB of compressed data. The largest corresponding four-member group
from the earlier layout held 26.12 MiB. That bounds the compressed member
spools held during publication. The observed whole-job peak scratch
came from planning, earlier in Run. In three new paired jobs, the
change moved the heavy gzip median from 13.32 to 13.35 s and ZIP from
13.30 to 13.28 s. The follow-up covered 36 jobs and included one large
output and 256 smaller outputs for each codec. Across its six cells, each
median paired change was within 0.02 s. Retain the shorter lifetime and
use the same block sizes and worker admission for the other paths.

For one 256 MiB ZIP the peak working reservation rose from 0.53 to 3.66
MiB and WSL peak RSS from 5.84 to 7.76 MiB. The resulting ZIP archive
grew 0.17%. Chromium admission rose from 0.53 to 9.26 MiB for the same
one-member job. Independent DEFLATE blocks use a fresh dictionary, so the
stored-byte cost depends on the source. Logical traffic counts temporary
file bytes separately from final output and physical I/O.

Zstandard input, output and the pinned C codec were removed as a product
decision. Jobs with retired output settings are rejected and former input
signatures receive a migration error. The hosted WASM asset shrank from
2,709,549 to 2,008,544 bytes, a 25.9% reduction before HTTP compression.
This supersedes the earlier decision to retain Zstandard for a counted
native Balanced route. The prior measurements remain evidence for the
earlier revision.

### Input decoding

From 256 MiB of decoded CSV through plain publication on WSL, medians
were 0.86 s for plain input, 1.26 s for gzip, and 1.21 s for a selected ZIP
member. Four-thread Rapidgzip 0.16.2 with CRC verification followed by
Chopper took 1.20 s end to end. Its median paired gain was 0.06 s and one
pair was slower. All twelve jobs verified exactly ordered output. Keep the
streaming input readers because the tested shortcut writes and rereads a
256 MiB decoded temporary file. An integrated bounded decoder was outside
the experiment. [Rapidgzip](https://github.com/mxmlnkn/rapidgzip)

Reproduce fixture creation and paired execution with
[`benchmark-parallel-compression.py`](../../../scripts/benchmark-parallel-compression.py)
and [the hosted harness](../../../scripts/benchmark-parallel-compression-browser.mjs).
[`chart-parallel-compression.py`](../../../scripts/chart-parallel-compression.py)
regenerates the chart sections from verified JSONL records. The
[dispatch rules](../../direct-execution.md#compression-selection) and
[format contracts](../../specification.md#compression-and-archives) describe
the code paths under evaluation.
