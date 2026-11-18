## Buffered random draws and seed removal (2026-11-16)

Decision: retain fixed-block word reuse in bounded random draws, and remove public
seed configuration independently of the performance result. This is a modest,
workload-specific improvement, not a substantial general shuffle speedup. Exact
membership/quotas, full-shuffle distribution, CSV caps, admitted ownership and
native/browser publication contracts remain binding. Explicit preparation still
fixes the exact encoded snapshot consumed by confirmation.

The [compact comparison record](../../evidence-originals.md#sha256-6a959c77feb7ee1d7612ebb10980c89ebf5e9a720c3673f6a1236a74d06ef1fb)
contains all included repetitions, their ranges, native CPU/RSS/OS I/O counters,
Analysis diagnostics, source/binary/WASM identities and raw attempt paths. Raw
originals and frozen complete source forests, including all three vendor trees,
remain in ignored `scratch/random-source-20261116`. No external archive upload,
public evidence publication, main delivery or native Windows acceptance is claimed.
Successful CSV payloads are removed only after independent verification; file
hashes and complete verification receipts remain. Failed attempts are retained.

### Candidate, scope and measurement

The baseline constructs a keyed BLAKE3 block for each bounded draw, then uses
only the first eight of its 32 output bytes. The candidate consumes all four
disjoint little-endian u64 words before generating the next block. Rejected words
still consume their position, with the same unbiased rejection threshold. It adds
one fixed stack buffer/offset, no heap allocation, dependency, user switch or
shared mutable stream. Random-key generation and collision refinement are
unchanged. This is intentionally narrower than the removed historical XOF source
and does not restore its alternate runner or cache selectors.

Under the existing keyed-block pseudorandomness model, disjoint output words
supply the same bounded-draw distribution; rejection sampling and Fisher–Yates
choice semantics are unchanged. Exact assignment still samples remaining quotas.
Tests compare buffered word boundaries/rejections against an independent block
word iterator, and retain exhaustive small-permutation multiplicity and quota,
conservation and failure/admission checks. Finite diagnostics do not prove PRNG
independence. The implementation records `chopper-v2-blake3-words-1`; v1 block/domain
construction remains unchanged. Historical source vectors and narratives are not
rewritten to claim byte compatibility with the new draw consumption.

Native clocks cover GNU-time wrapper launch through CLI exit, including
publication and product cleanup. One excluded warmup per variant precedes five
alternating measured pairs per cell. Fixtures and verification are outside the
clock. The separate direct-control confirmation uses seven pairs. Native jobs
request one worker; Fisher–Yates uses 256 MiB, the other cells 32 MiB. Inputs use
three fields with quoted commas, quotes, UTF-8 and embedded newlines, plus 10,000-row
and 4 MiB encoded CSV caps. The independent existing verifier checks exact fields,
unique IDs, largest-remainder quotas, group order/lineage, metadata, caps, all
listed files and no leftover job temporary files.

Browser clocks cover prepare, confirmation, exported file closure/completion
marker and worker retirement, using one excluded warmup then three alternating
pairs in a persistent disposable bundled Chromium context. Input fetch/pickers,
verification/collection and successful destination removal are outside the clock.
Both variants use the same helper/worker bundles and receive identical internal
control seeds in these frozen pre-product-removal benchmark engines. This is an
experiment control, not a retained product option. The browser adapter's exact
path translation and added export warning are checked explicitly before comparing
manifest Analysis/configuration. Retained-owner sums, bounded handles, actual
export bytes and zero post-retirement workspace are checked by the shared driver.

### Complete-job results

Elapsed reduction means `(baseline median - candidate median) / baseline median`.
Ranges are the observed minimum and maximum, not confidence intervals or tails.
Native and browser clocks are different and are never pooled.

| Runtime / cell | Rows / payload bytes | Baseline median [range], s | Candidate median [range], s | Elapsed reduction |
| --- | --- | --- | --- | --- |
| WSL native / resident Fisher–Yates | 120,003 / 64 | 0.16715 [0.16357, 0.16949] | 0.15784 [0.15577, 0.16498] | 5.6% |
| WSL native / exact assignment | 150,003 / 192 | 0.28512 [0.27394, 0.29609] | 0.27036 [0.26322, 0.29857] | 5.2% |
| WSL native / external uniform control | 250,003 / 192 | 0.43752 [0.42112, 0.45616] | 0.43877 [0.42683, 0.44273] | -0.3% |
| WSL native / direct control | 250,003 / 192 | 0.26426 [0.24282, 0.29275] | 0.29507 [0.25215, 0.40836] | -11.7% |
| Persistent Chromium / resident Fisher–Yates | 120,003 / 64 | 0.55518 [0.51897, 0.56278] | 0.50348 [0.50185, 0.50376] | 9.3% |
| Persistent Chromium / exact assignment | 150,003 / 192 | 1.47621 [1.43949, 1.49237] | 1.47343 [1.44926, 1.49060] | 0.2% |
| Persistent Chromium / external uniform control | 250,003 / 192 | 2.00863 [1.98642, 2.04914] | 2.05024 [1.98851, 2.05028] | -2.1% |
| WSL native / larger direct confirmation | 1,000,000 / 192 | 0.99800 [0.98133, 1.18796] | 0.98388 [0.96649, 1.02629] | 1.4% |

The initial direct control's regression remains in the table. A separately
identified larger repeat did not reproduce it; it does not erase the first result
or establish a direct-split benefit. The retained implementation targets bounded
draws, with the clearest repeated benefit in resident Fisher–Yates. Exact-allocation
browser time is dominated by other complete-job work. External uniform shuffle
has no demonstrated improvement and is not promoted as a faster path. No new
resident selector, bucket algorithm, storage rewrite or additional matrix is added.
These warm WSL/OPFS cells do not establish physical SSD traffic, browser RSS,
native Windows/macOS, installed-browser, 25-million-row or scale performance.

### Product removal, failures and validation

Public `seed` Job JSON, the CLI `--seed` flag, guided seed editing, UI seed fields
and client-generated/retained submission seeds are removed. Older saved jobs with
`seed`, including null, fail strict decoding; the UI import message explains its
removal. `random_seed` is skipped internal execution/test state and also rejected
as a JSON input. Internal entropy is generated under existing retained-configuration
admission and diagnostic Analysis ownership. Exported Job JSON contains neither
field. Diagnostic entropy identifiers are not a replay interface. Resources has
one expandable resource-budget section, with no surrounding seed disclosure.

The first native warmup failed because the harness had not created its declared
temporary directory. A second attempt used a timed subprocess wait that rounded
short measurements; all its timings are excluded. The eligible native rerun uses
a blocking wait and separate deadline watchdog. Two browser warmups exposed the
browser warning and WASI path translation differences in the reused native
verifier; both attempts are excluded. The adapter now checks those exact
transformations before applying the unchanged independent data/metadata checks.
No failed attempt was rescued into the measurement population.

Validation results and final product transfer checks are recorded in the compact
comparison record. Historical fixed-seed goldens remain immutable. Current public
browser checks use independent conservation/fields, quotas, membership, lineage,
caps and snapshot guarantees instead of equality between separate random Runs;
unchanged internal algorithms retain their pinned exact-order controls.
