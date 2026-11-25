## Hosted Job JSON buffering (2026-11-25)

Buffer the WASI adapter's typed Job read with one 8 KiB reader. The existing
serde stream consumes bytes one at a time. Buffering batches the requests
that cross the WASI boundary. The adapter drops the reader when deserialization
returns and hands the typed Job to the existing entry point.
[Issue #74](https://github.com/jsmatfess/chopper/issues/74) ·
[Samples and receipt identities](../../benchmarks/hosted-job-json-buffering-summary-2026-11-25.json)

### Complete hosted Runs

Both builds used the same engine and storage worker assets, bundled Chromium,
256 MiB, one worker and disposable OPFS destinations. They ran the same
two-row CSV with one row per output. The larger synthetic Job had 63
calculated columns. Each formula is a 16 KiB string consisting of a literal
one followed by spaces. The serialized virtual Job measured 1,034,770 bytes.
The clock begins at the hosted client's Run request and ends at complete
state after marker publication and workspace retirement. A separate verifier
reads the exact CSVs, manifest and marker. Each cell used one warmup per arm
and three alternating measured pairs.

| Job configuration | Existing median [range], s | Buffered median [range], s | Median paired seconds saved |
| --- | ---: | ---: | ---: |
| Compact | 0.086 [0.074–0.086] | 0.086 [0.079–0.096] | −0.005 |
| 63 maximal formulas | 0.393 [0.379–0.407] | 0.142 [0.142–0.145] | 0.251 |

The large fixture saved 0.235–0.265 seconds per job. Compact paired costs
increased by 0.0003–0.0100 seconds. The measured cohort passes the declared
0.10-second large-config benefit and 0.03-second compact median cost gates.
These jobs isolate a large configuration on a tiny CSV. Their savings apply
to that configuration shape and recorded browser build.

### Read counts and compatibility

The untimed instrumentation counted only the descriptor for `/job.json`.
Both arms read exactly 1,034,770 bytes, with 1,034,771 calls in the existing
adapter and 128 through the buffered reader. Timed samples use the
unmodified worker assets. A 64-column fixture, with a 1,051,185-byte
virtual Job and 512 MiB request, also completed with exact accepted output.
It failed formula preparation at 256 MiB in a separate baseline control.
The 512 MiB control isolates the existing supported virtual file size.
An untimed production-page test imported a 1,034,412-byte Job in both
builds and verified its exact export. The upload control rejected a
1,048,577-byte file in both builds at the existing UI limit.

Adding an unknown field beyond the first buffer produced identical error
text and position. A 382-byte output cap failed in both builds without a
completion marker. The 383-byte success cap produced both exact expected
chunks. The first two harness preflights stopped on an outdated reservation
sum. The final census includes the 8,192-byte catalog and eight-byte
destination owner on the streaming route. The failed attempts remain in the
retained receipts. They contribute no elapsed comparisons.

### Replay

Use matching source snapshots from `428b83b0b464402358c396b8d6da536e3758b4e4`.
Build the baseline and a challenger with an 8,192-byte
`std::io::BufReader` in each typed `/job.json` decode through
`node scripts/build-browser.mjs`. Keep the existing entry-point validation
and execution callbacks. Serve both engine binaries behind the same
production worker assets. The [hosted swarm driver](../../../ui/tests/benchmark-swarm.ts)
invokes the complete Run and independently reopens its export. The
receipt records exact compiled assets, compiler, harness and workload
identities. The test-only descriptor wrapper runs in the untimed
diagnostics.
