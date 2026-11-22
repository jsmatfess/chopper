# Browser engine

See the [documentation guide](README.md), [latest recorded validation](validation.md#latest-recorded-coverage) and [GitHub Issues](https://github.com/jsmatfess/chopper/issues). This page owns browser setup and runtime/export limits.

Release acceptance follows the [preparation, complete tiny journey
and frozen-batch prerequisites](validation-runner.md#actual-host-acceptance-preflight).
Keep existing browser receipts within their recorded host/channel/path scope;
neither preparation nor tiny qualification establishes scale acceptance.
The [complete hosted tiny guide](hosted-tiny-qualification.md) defines hosted
actual-picker, SMALL and scale-controller qualification modes. References there
to native UI/picker acceptance belong to historical 0.1 work; the current native
product is CLI-only.

The hosted build runs the engine as a WASI WebAssembly reactor in a dedicated
browser worker. Its web host serves static assets; it has no CSV upload or
processing endpoints. No local Chopper executable is needed by hosted users.
There is no native local server or embedded browser UI.

The public browser app is available at [chopper-1rx.pages.dev](https://chopper-1rx.pages.dev/).
The link is a user entry point; this documentation does not assert a current
deployment identity. Historical deployment evidence is scoped to its recorded
source, browser and fixtures.

The hosted form starts in **Auto**. Open **Advanced** to change working memory,
workers, grouping, or the shuffle algorithm. Switching to Auto asks the engine
to choose these settings. Switching back restores the advanced draft. Output
caps and safety limits apply in both modes. Importing a job with explicit
execution settings opens Advanced.

**Results → Auto plan** shows the resource settings, actual strategy,
writer slots and retries. Run validates its current input and can use the
calibrated shuffle fusion without Analyze. A completed Analyze remains optional.

## Local development

Use desktop Chrome or Edge. The application requires a secure context (HTTPS or localhost), File System Access, OPFS, Web Locks, and cross-origin isolation. The supplied server and Cloudflare `_headers` configure isolation. Opening `index.html` directly will not work.

Prerequisites are Node.js 22+ and Rust with the `wasm32-wasip1` target.
The supported release build workflow covers Windows and Linux. WSL is optional.
Native Windows Rust also needs the Microsoft C++ Build Tools and Windows SDK.

`node scripts/build-browser.mjs` uses the optional repository-local Rust toolchain
described in the root README when present. Otherwise Cargo must be on `PATH`.
The Bash entry point delegates to the same Node implementation.

The wrapper fixes package `chopper-browser`, target `wasm32-wasip1` and the release
profile so the copied engine is the requested artifact. Set `CARGO_TARGET_DIR`
to override the output directory. The wrapper resolves it (or its default `target`)
once and binds both Cargo target-directory environment forms to that absolute
path, so inherited Cargo configuration cannot redirect the build away from the
copy source. Supported arguments are feature selection
(`--features`/`-F`, `--all-features`, `--no-default-features`),
`--resource-contracts`, `--offline`, `--locked`, `--frozen` and verbosity flags.
Other Cargo arguments, including `--target-dir`, `--target`, `--profile`,
`--manifest-path` and `--config`, reject before Cargo or output modification.
Use direct Cargo invocation when a different build layout is required; such an
invocation does not package an engine through this wrapper. Historical replay
uses the build script and toolchain pinned by its original evidence.

Build the WASI engine, then the hosted UI and local static server. From the
repository root on Windows:

```powershell
rustup target add wasm32-wasip1
node scripts/build-browser.mjs
npm.cmd --prefix ui ci
npm.cmd --prefix ui run build:hosted
npm.cmd --prefix ui run serve:hosted
```

On Linux, run `rustup target add wasm32-wasip1`, then run `node scripts/build-browser.mjs`, `npm --prefix ui ci`, `npm --prefix ui run build:hosted`, and `npm --prefix ui run serve:hosted`. `npm --prefix ui run build` is an alias for `build:hosted`. Native CLI builds do not need Node or a generated UI bundle.

Open **http://127.0.0.1:8421/**. Browse for an input and an output parent folder, configure the pipeline and choose Run. Analyze is optional and returns input statistics and estimates; Run validates the current configuration independently. Results go into a new `chopper-results-<UUID>` subdirectory. A `CHOPPER-COMPLETE.json` marker is written only after every result file has closed successfully.

A hosted Run with a selected `.csv` file and plain output can prefetch
one 256 KiB source window for an empty pipeline or a single Partition. With
an empty pipeline, the storage worker also batches adjacent writes to the
current file in one 1 MiB block. The two shared slots and the worker buffers have a combined
live capacity of 2.5 MiB plus 24 control bytes, outside the WASI working-memory
reservations. A rejected source prefetch falls back to the current synchronous
read. Destination errors fail Run before completion. The storage worker waits
for outstanding operations before aborting open streams and cleaning incomplete
results. See the [publication contract](direct-execution.md).

For large local benchmark jobs, use a persistent browser profile. The external
comparison harness now does so explicitly. On the recorded Chromium build,
Playwright's temporary context returned an invalid OPFS write count after about
1 GiB of retained storage; the standalone `scripts/validate-browser-opfs.mjs`
probe completes 1.5 GiB with a persistent profile. Storage read/write counts are
validated before crossing WASI, and delayed notifications are checked against
the current request's completion flag. These checks fail the job cleanly rather
than passing invalid counts into Rust. This observation does not establish a
universal browser storage limit. See the [recorded diagnostic](benchmarks/browser-opfs-contexts-2026-10-17.jsonl).

## Processing and limits

The rejected independent-parent batching/replay adapter and its browser feature
forwarding are removed. `experimental-parallel-groups` fails in Cargo, including
through the engine build wrappers. WASI keeps its ordinary serial parent stages;
this removal makes no browser performance claim.

Partition-first and dormant Parquet wiring were removed on 2026-10-24.
`experimental-flexible-partition` and `experimental-parquet-input` are invalid
native/browser Cargo features, including through browser build wrappers. Neither
provided a dedicated public runtime selector or Parquet decoder. Flexible `auto`
still executes shuffle then partition in logical order; exact shuffle/partition,
allocation ranges and counter-v1 remain. Direct compact/Arrow IPC snapshot APIs
and `experimental-input-snapshots` were separately rejected and removed after E3
review on 2026-10-26. Use direct CSV input; the old Rust module no longer compiles
and native/browser builds naming the removed feature fail explicitly.
Historical Python Parquet/CSV adapter research does not describe Rust input support.

Independent random buckets and buffered XOF are removed from native/core/browser
features. `experimental-random-buckets` and `experimental-fast-rng` fail in Cargo,
including through the browser build wrapper. WASI Job decoding rejects
`independent_buckets_v1`, `blake3_xof_v1` and resource
`shuffle_rng_buffer_bytes` before profiling/preparation; no substitute is selected.
Explicit `adaptive_v1` and `blake3_counter_v1` remain supported.

The rejected `experimental-radix` and `experimental-distribution` feature
forwarding has been removed. Build requests naming them fail in Cargo. These
experiments had no public Job selector; unsupported strategy/algorithm values
remain strict schema errors. Comparison sorting and external merge remain.

The hosted engine rejects the removed `buffer` shuffle strategy and `buffer_rows`
field during strict Job decoding, including during profiling. Supported shuffle
strategies remain `uniform`, `auto` and `fisher_yates`; see the
[current contract](specification.md#shuffling-and-seeds).

The original operations and the explicit probabilistic allocation, interleaved split and Fisher–Yates options, plus all native CSV encodings/dialects, gzip and ZIP use the existing Rust implementation. Exact allocation and grouping semantics are preserved. There is no reproducibility checkbox or seeded-output policy; randomized output may change across execution plans and resource budgets. There is no seed field in the form or exported Job. Older jobs containing `seed` are rejected with a removal message. Results show the algorithm version. Resources contains one expandable resource-budget section. See the [seed contract](specification.md#shuffling-and-seeds). ZIP output remains one archive containing all CSV chunks.

Charged allocations in one WASI engine instance now share a 1 GiB aggregate admission ledger across profiling, cached/returned profiles, preparation and execution. Per-job Auto or explicit numeric budgets still apply. Automatic selection observes this instance’s free admission capacity without reserving it. See the [resource contract](specification.md#resources-publication-and-interfaces). Pressure can trigger spills or a bounded failure; this is not a JavaScript/WASM/process RSS cap, and separate workers/tabs do not share the ledger. [Hosted limit evidence](performance/investigations/hosted-memory-ceiling-2026-11-16.md).

Input uses bounded `File.slice()` reads. Temporary spools, external merge runs, and staged results are stored in OPFS, not an in-memory filesystem. A storage worker services synchronous WASI file operations through a 1 MiB shared transfer buffer. It caps open OPFS handles at 64 and evicts handles earlier when the browser reports a handle quota; closed WASI descriptors are reused. Only file/directory metadata is retained in the JavaScript directory tree.

The browser currently uses one processing worker and accepts a 32–2048 MiB working-memory budget or `"auto"`. Omission selects Auto. Auto usually targets at most 256 MiB. An eligible plain-output uniform shuffle can target 512, 1024, or 2048 MiB to avoid spilling. Before Analyze, Run uses the size of a plain UTF-8 CSV and the pipeline shape. For supported CSV settings, the existing eight-row preview can raise the target using sampled field widths and column count. For eligible plain CSVs starting at 1024 MiB, Run can refine the estimate using up to 256 KiB sampled farther into the file. The samples can reveal width changes beyond the preview. Run uses them to size memory and still parses the current source. If the larger tier lacks capacity, Run can use the original tier when it fits. For gzip, the same preview can use the final member's trailer as a size hint. This hint can miss expansion in earlier members. Preview observations apply only to the same selected file, parsing settings, and record ceiling. Run can start without a preview and validates the entire input. With applicable Analyze observations it estimates the retained sort footprint from decoded payload, row count and column count. The Analyze card shows its memory estimate. The Run plan reports the selected starting target, whether Analyze changed it, and any capacity fallback. Run resolves it against available engine capacity. Automatic selection can fail normal record/worker validation rather than increasing the budget or lowering record limits. This is an algorithm working budget, not a limit on total browser process memory. WebAssembly linear memory is capped at 2 GiB. OPFS space is subject to browser quota and free disk space; there is no default temporary-space cap or quota-estimate reserve. Actual OPFS quota/write failures fail the job. An explicit `resources.temp_bytes` limit still applies to engine temporary files; staged output also consumes real quota. The input section gives a rough 2–8× uncompressed source-size guide for sorting/grouping, not an upper bound. Compressed source expansion is unknown. Source size itself is not limited by WebAssembly address space. Billion-row browser operation has **not** been validated.

The 2 GiB ceiling avoids changing the current WASI shim: imported i32 pointer
arguments arrive in JavaScript as signed numbers, and its DataView/typed-array
accesses do not normalize addresses above 2 GiB. Reaching the wasm32 maximum of
4 GiB would require auditing/normalizing all affected imports and offsets,
checking allocator growth/overlap and large contiguous Rust allocations, and
qualifying supported browsers under pressure. Beyond 4 GiB requires a different
addressing architecture, such as memory64, or independently partitioned engine
instances; simply raising a form maximum or linker flag is insufficient. The
native engine already accepts much larger budgets, subject to its platform
admission policy, and avoids this browser ABI.
See [V8's wasm32 memory explanation](https://v8.dev/blog/4gb-wasm-memory) and
[Rust's contiguous allocation limits](https://doc.rust-lang.org/std/vec/index.html).

Large gzip and ZIP output can use up to four dedicated compression Web Workers
under Auto. They run the same DEFLATE codec in separate WASM instances. The
engine retains an admission grant for the shared block buffers and codec
scratch until the Run retires the workers. The selected file and output bytes
stay local. The engine has one processing worker, and an explicit worker setting
of 1 uses serial compression. The Auto details report parallel compression
slots when used. See [compression selection](direct-execution.md#compression-selection).

Analyze scans every record without producing output spools or retaining an
executable snapshot. Run processes limits-only jobs and a single uncompressed
Balanced step directly into publication output without an additional complete CSV
snapshot; other pipelines prepare internally.
Final plain CSV and gzip files and their manifest go directly to a fresh
folder under the selected destination. Intermediate data and retained engine
snapshots still use OPFS. ZIP uses the staged export path because archive
finalization reopens the manifest. The storage worker forwards one bounded write
at a time and closes each destination stream before acknowledging its close. Run starts from the current
configuration and validates its input independently of earlier Analyze results.

Browser APIs cannot atomically publish a directory. An active direct Run can
have files visible in its results folder before it finishes. A failed or
cancelled direct Run aborts open destination streams and attempts to remove its
own incomplete folder. Failed staged exports attempt the same removal.
If the browser process or tab is lost, manual destination cleanup may be needed. Completion requires a valid `CHOPPER-COMPLETE.json` record, not just a file with that name. The v1 JSON record contains `complete: true`, `engine: "chopper-browser"`, `version: 1`, and `files` counting every exported result file including the manifest, excluding the marker itself. An empty or unparseable entry is incomplete. Cancellation or tab close after the marker commits does not roll back that completed folder, even if the client has not received the success reply. The native CLI retains its native publication behavior.

Keep the tab open. Cancellation stops the engine and deletes its OPFS workspace. Closing/crashing the tab can leave temporary data behind. Opening the hosted app starts a background sweep of unlocked Chopper workspaces, skipping jobs active in other tabs or workers. Returning to the tab checks for abandoned data without deleting it. **Clear temporary data** appears only when an unlocked workspace remains, including when automatic deletion fails; successful cleanup hides the control. Checks and sweeps do not overlap within a tab. Storage-access failures alone do not expose the link. It never deletes exported results. Browser storage is origin-specific, so localhost and the hosted site have separate workspaces.

## Tiny encoding qualification (#153)

The shared CSV editor retains imported labels such as `cp1252` and `sjis`, including
when copying input settings to output. Unknown labels remain selected for correction
or explicit engine rejection. Alias resolution stays in the engine.
`npm --prefix ui run test:workspace` covers both entry points with mocked responses;
this checks import/edit/export, Analyze and fresh Run requests, not encoded
execution or publication.

For independently checked tiny encoded-byte fixtures (no engine/browser startup):

```sh
python3 scripts/test-browser-encoding.py self-test
python3 scripts/test-browser-encoding.py prepare /tmp/chopper-encoding-153
```

Use a fresh fixture directory. Each JSON job uses the matching non-ASCII CSV and
alias for both input and output, with one data row and a 32-byte strict cap.
The literal expected bytes are independently checked using Python codecs. During
hosted qualification, select the corresponding CSV and a destination parent with
the browser file controls. Earlier instructions to import jobs into the native
UI described the retired 0.1 interface.
Edit an unrelated setting, export and inspect the Job, then exercise Run and a
Analyze-then-Run cycle with fresh destinations. Verify each
result folder (for hosted, the exported child folder):

```sh
python3 scripts/test-browser-encoding.py verify cp1252 /path/to/result-folder
python3 scripts/test-browser-encoding.py verify sjis /path/to/result-folder
```

The verifier requires one CSV with exact expected bytes and decoded fields, and
rejects UTF-8 substitution. Check unsupported-label errors separately against the
real engine. Record source/bundle/engine identities, platform/browser and logs;
fixture self-tests and mocked DOM passes do not establish runtime acceptance.
Preserve frozen606 assets and prior evidence: they do not certify changed source
or replace final matching native/hosted release qualification.

## Session ownership

The [session module](../ui/src/browser/session.ts) owns hosted job lifecycle
and replaceable browser sessions. Defaults, column inspection and Analyze can reuse a session. Analyze caches
bounded input statistics; it never retains output bytes for later approval. The [client adapter](../ui/src/browser/client.ts) owns picker/UI
integration and history rendering, without coordinating worker generations.

Each session owns startup, the engine/storage workers, correlated requests and
its workspace lock. Retirement detaches its resources and rejects pending work
before awaiting storage cleanup. Cleanup or its 15-second forced-termination
bound releases only that session's lock. Cancellation can retire incomplete
startup; a later quota/lock/init continuation cannot start replacement work.
A queued Web Lock granted after retirement is released without creating workers.
Cleanup replies and permission waits cannot change a newer job's state.
Submitted settings and input/output handles are captured before startup or
permission waits. A delayed Run grant rechecks active-job eligibility. Run uses
the captured destination even if Browse selections change while permission waits.
Post-start worker errors and request-send failures notify the lifecycle owner
directly and reject outstanding requests. The captured failed session retires
even when idle or analyzed without a pending Run, or during inspection;
late errors cannot retire a replacement session.

Retained execution history remains independent of session lifetime. Retired
worker messages use a separate path for confirmed same-Run facts; they cannot
update job status or acknowledge another session's observation credit. Export
and completion-marker semantics are unchanged.

Focused [session tests](../ui/tests/browser-session.mjs) exercise the lifecycle
interface with controlled browser effects, including startup failure, pending
requests, cleanup timeout and replacement races. Real-worker acceptance below
continues to verify destination CSVs, manifests and markers independently.

## Live Run history

A new observed Run opens the Execution view, with the bounded execution graph
beside the output plan on desktop and stacked on smaller screens. Users can collapse it; subsequent
observations preserve that choice until the next Run. It shows input, CSV writing, saved-and-closed
export files and separate completion-marker confirmation, with an equivalent
keyboard list. Internal preparation additionally observes partitioning, resident
uniform/Fisher–Yates work, exact fusion, elision and snapshot/materialization.
History survives worker shutdown and form edits. External spill, hierarchical merge, grouping handoff and ordered-file reuse
now have bounded physical summaries. Exact/probabilistic allocation, exact strata,
shared balanced ranges, terminal/fused balanced traversal and interleaved
membership report actual counts without stratum values. Actual gzip and ZIP input adapters, output compressors and ZIP archive
assembly add byte-scoped facts; see the [observation contract and fixed
bounds](execution-observation.md). This does not change export/cleanup semantics.

The output plan's **Run in CLI** disclosure generates an ordered native
`run` command with explicit `--step` blocks for the current editor settings. It uses literal repeated
selectors to preserve column names versus indices and allocation names containing
commas or equals signs. A compact tab-styled native radio group offers Windows (PowerShell
7.3+), Linux (Bash), and macOS (zsh/Bash), initially suggested from the browser's
platform and always overridable. Native radio keyboard navigation changes the
selection without adding custom tab-panel semantics to the shared command preview. Commands use the appropriate local executable,
path syntax and literal shell quoting. Switching platform preserves the Job
values; it does not guess conversions between Windows and Unix file paths.
Browser handles expose names rather than full paths: replace input with the full
file path and output with a new directory path. The command updates after edits;
copy feedback clears when the draft or selected platform changes. Invalid intermediate sizes suppress
command copying. Jobs over 24,000 UTF-16 code units or containing NUL characters use the existing Job JSON
export and `run --config` command instead, leaving headroom under Windows' native
command-line limit. This is a conservative UI threshold, not an OS size guarantee.

Native package availability is listed on the
[releases page](https://github.com/jsmatfess/chopper/releases); macOS remains
source-only for 0.2. See the [0.2 notes](releases/0.2.0.md) and
[Run CLI reference](run-cli.md). Older v0.1.0 executables accept JSON Run with
`--config`, while current source also supports ordered Run flags.

Graph, List and Timeline share step selection and the inspector. Timeline uses
worker-observed elapsed time since processing began, captured before delivery
coalescing. Its bars span the first observed start to the latest activity of each
step; repeated groups can leave gaps inside that window. Measured work remains
the separate cumulative inclusive duration, not CPU time or a concurrency claim.
Missing starts/timing are labeled rather than inferred. The live axis freezes on
completion or interruption; hidden tabs pause visual refresh while retaining
observations. Interrupted steps without a terminal observation have dashed bars
to the frozen capture cutoff, labeled “end not observed.” The timing capture has
its own fixed per-step bounds and continues
after the separate 128-significant-event prefix saturates. New runs capture timing;
history produced by an older worker may have none.

## Tests

`node scripts/test-browser-step-starts.mjs` runs Auto shuffle followed by a country
partition at 128 MiB on a bounded external-sort fixture. It pauses the real worker
when grouping accepts its first input, verifies serialization is still absent
until grouping supplies output, and independently checks all fields, row
conservation, partition membership and the completion marker. It uses an owned
disposable browser/server on port 8432; this is a regression check, not a
25-million-row or installed-browser qualification.

The four graph harnesses share an owned
[hosted-browser scope](../scripts/browser-acceptance.mjs). It waits for the
server's listen-ready line, rejects early exit or stalled startup, creates a
disposable context, and attempts context/browser/server cleanup in order. Server
termination is bounded and exit is observed before success; primary test errors
are retained alongside cleanup failures. Routes, fault wrappers and independent
output assertions remain in each harness. Persistent/process-kill and peer-tab
cleanup fixtures retain their distinct lifetimes. Native-editor fixtures refer
to the retired 0.1 interface and are historical.

`node --test scripts/browser-acceptance.test.mjs` checks this lifetime with
controlled effects and real owned-server exit, port reuse and bind failure.
Playwright's package must be installed (`npm --prefix ui ci`); these focused
checks do not launch a real browser. Run the migrated graph, lifecycle (including
`--composed`), inspection and bounds harnesses with a production hosted build to
check the real browser path. The browser CI job runs both levels.

`node scripts/test-browser-graph.mjs` exercises the public Run action across
limits-only and pipeline grouping, shuffle, allocation and split fixtures with independent enabled/disabled
CSV, manifest and marker checks. Run it after the production hosted build; its
server and picker/telemetry fixtures are test-only, not deployable assets.
Codec fixtures independently decode exports using Node gzip and Python 3 ZIP.
The small-fixture helper is test-only.

`node scripts/test-browser-graph-lifecycle.mjs` checks the public hosted Run page
with production WASI and OPFS, specializing the worker to the staged copy path. Test-context routes inject worker,
result-writer and marker failures, cancellation at processing/marker boundaries,
queued old-generation facts, observation transport loss and a one-shot rendering
failure. It independently reads output CSVs/manifests and markers. A marker closed
without observed readback stays unconfirmed; an actual queued confirmation can
update the retained same-Run history after cancellation, without changing job
state or rescanning the destination. No injection route is packaged for users.

The production interruption harness also accepts `--direct`. Run
`node scripts/test-browser-termination.mjs --persistent --process-kill --direct`
to check direct Run through processing, CSV export and marker-close interruption,
same-client retry, tab close and forced-process recovery. Its `prepare` checkpoint
label denotes pre-export input processing in this mode; the report records
`direct_run: true`. Pipeline and limits-only acceptance remain separate invocations.

```powershell
node scripts/build-browser-tests.mjs
```

With the local server running, open http://127.0.0.1:8421/tests.html. Contracts use real workers, WebAssembly, browser file objects, and OPFS; only the user picker interactions are replaced with test fixture selections. Tests exercise all operations, compression roundtrips, strict validation, encoding/byte caps, bounded-disk shuffling, and cancellation cleanup. The native suite remains `cargo test --workspace --locked`.

For CI, install Chromium with `npm --prefix ui exec -- playwright install --with-deps chromium`, then run `node scripts/test-browser.mjs`. Production `build:hosted` removes the test harness from `ui/dist`.

The browser, bridge, peer-cleanup and termination harnesses accept
`CHOPPER_BROWSER_CHANNEL=chrome` or `CHOPPER_BROWSER_CHANNEL=msedge` to use an
installed desktop Chrome or Edge. The default is `bundled-chromium`. For example,
in PowerShell set `$env:CHOPPER_BROWSER_CHANNEL = 'msedge'`, then run the same
commands. These harnesses use disposable contexts/profiles, including persistent
restart tests; they do not open an existing user profile. Reports retain the
channel and actual browser version. Reset the environment variable after the
selected-browser run. A selected browser must be installed; a launch failure
does not count as browser validation.

`node scripts/test-browser-cleanup.mjs` separately tests the production abandoned
workspace cleaner with two same-origin tabs and a worker holding a real OPFS
synchronous handle. Cleanup skips held Web Locks, removes the worker's workspace
after termination and the tab's workspace after close, and preserves unrelated
files/directories and exported results. UUID-shaped files are not workspaces.
This covers deletion coordination, not shared memory admission across instances,
engine cancellation or export interruption. The harness serves its scripts from
test-only request routes; it adds no assets to the deployable build.

`node scripts/test-browser-direct-destination.mjs` exercises direct destination
publication with real WASI and OPFS, including late input failure, destination
write/close failure, confirmed invalid markers, unknown readback outcomes and
cancellation during writes and stalled prefetch. It also kills a disposable
browser process before and after the marker closes, then verifies the
destination and workspace cleanup on restart.

`node scripts/test-browser-termination.mjs` separately exercises the production
client, engine WASM and storage worker on the staged copy path with test-only pauses during preparation,
after a real destination write before close, and after one result file closes.
It also pauses after a marker write before close and after marker close before
the worker's success reply. It checks cancellation and forced tab close, peer
cleanup while the owner is active, abandoned-workspace removal, incomplete-export
preservation without a valid completion record, preservation of committed
completed folders, and successful same-client retries. An empty marker entry at
the write-before-close boundary is not a completed export. Pickers are replaced
with fixture selections and destinations are same-origin OPFS in a fresh temporary
Chromium context. Worker/FSA pause hooks are request-route fixtures and do not
modify production bundles. The default run covers a temporary context. External
directories, quota/device faults and cross-instance memory admission remain
outside these modes. Abrupt browser-process termination has a separate mode below.

`node scripts/test-browser-termination.mjs --persistent` repeats those checks in
a disposable saved Chromium profile, then closes and relaunches the browser with
three real jobs paused at preparation, marker write and committed-marker close.
It verifies different browser process IDs, retained OPFS workspaces with released
locks, peer cleanup after restart, and preserved closed results/marker semantics.
The profile is task-owned under the OS temporary directory and removed after
validation; no existing browser profile is used. This tests normal shutdown and
relaunch, not origin persistence permission, quota eviction, a process crash,
power-loss durability or physical SSD performance. A pending marker transaction
file observed on this Chromium build is recorded separately from committed
results and may disappear when the writer is aborted at shutdown.
The destination observer tolerates `NotFoundError` only when a recognized
Chromium writer-swap entry disappears between enumeration and reading. Observable
pending payloads still undergo the existing exact-byte checks; real result-file
errors, unrecognized names and other exception types remain failures. Negative
observer controls cover those boundaries. This follows
[Chromium's sibling swap-file naming](https://chromium.googlesource.com/chromium/src/+/b694dcb617f6ed6a9e738461017c48cb0de0ba4a/content/browser/file_system_access/file_system_access_file_handle_impl.cc),
not a Chopper output or completion-marker rule change.

`node scripts/test-browser-termination.mjs --persistent --process-kill` adds
abrupt browser-process termination. Five simultaneous production jobs pause at
preparation, CSV write before close, after one CSV closes, marker write before
close and committed marker close before reply. The harness obtains its own
browser PID through CDP, sends `SIGKILL` (`TerminateProcess` on Windows), and
requires observed process exit and browser disconnection before relaunching the
same disposable profile/origin. It checks released locks, retained workspaces,
cleanup of all five, exact committed exports, marker validity, and a fresh complete
job after recovery with exact CSV parity. Existing completed and interrupted
folders remain unchanged by that new job. Open transaction files can survive a
forced kill; only the exact paused CSV or marker `.crswap` name and known payload
are treated separately, with full before/after snapshots preserved. Empty targets
and pending transaction payloads do not count as completed exports. This mode
covers forced termination at those checkpoints, not power loss, device faults,
quota eviction, arbitrary crash timing or external destinations.

Resource admission uses a separate test reactor and worker, with the same
internal input-adapter assertions as native tests and real OPFS storage.

For the opt-in spill-block codec, build the resource reactor with
`--resource-contracts --features experimental-spill-blocks`, build the resource
test assets, then run `node scripts/test-browser.mjs --resource-contracts --spill-blocks`.
This invokes the same codec reconstruction, malformed/truncated stream, local
fallback, shared-pool denial/retry and live-reader cancellation assertions as the
native tests. The `--spill-blocks` flag requires their named results; generic
resource or lifecycle suites alone do not prove that blocks executed. If the
reactor also enables `experimental-shuffle-partition`, also pass
`--shuffle-partition` to the test runner.

The shared publication-metadata helper also checks pre-admitted batch/result
slots, bounded output-name owners, ordered collection, capacity denial/retry,
worker/consumer failure and cancellation. It checks final owner and fixture
cleanup; joined-path, job-manifest JSON and codec/runtime allocations remain
outside that slice. These are resource contracts, not speedup measurements.

The output-planning helper additionally checks separately admitted active-chunk
and materialized-group lineage clones, serialization/temporary-space failure,
denial/retry before emission, cancellation, row-cap rollover, named empty outputs
and materialized CSV/catalog parity. Original lineage construction and other
clones/growth remain outside that ownership slice.

The job-manifest helper checks preconstruction admission for the canonical
configuration/analysis JSON tree, exact bytes across the current schema,
partial-construction and write failure, capacity edges, independent owners and
real publication denial/retry/cancellation cleanup. Its private preflight supports
the current immutable schema; source metadata, custom serializer allocations and
runtime storage remain separate boundaries.

```sh
node scripts/build-browser.mjs --resource-contracts
node scripts/build-browser.mjs --resource-contracts --features experimental-shuffle-partition
node scripts/build-browser-tests.mjs --resource-contracts
node scripts/test-browser.mjs --resource-contracts
node scripts/test-browser.mjs --resource-contracts --shuffle-partition
npm --prefix ui run build:hosted
```

The nondefault `resource-contract-tests` feature adds one test-only export.
`--resource-contracts` writes `ui/dist/engine-resource-tests.wasm`; when Cargo
features enable `experimental-shuffle-partition`, it instead writes
`ui/dist/engine-resource-tests-shuffle-partition.wasm`. Repeated `--features`,
comma/space/list values, `--features=value`, `-F` and `--all-features` select the
same partition basename. Neither resource build changes production `engine.wasm`.
Build both before freezing inputs; the test page propagates the existing
`shuffle-partition` query to its worker, which fetches only the matching basename.
A missing selected reactor fails without falling back to its sibling. Both can
therefore remain immutable through one baseline/partition SMALL batch.
The test page checks typed shared-memory
denial for input adapters and decoded groups, retained owners, explicit retry,
pathname unlink failure that prevents engine publication, and final cleanup;
it adds no injection API to the production worker. Both base and candidate reports
also check column-inspection source/parser admission, retained EOF owners,
terminal errors and fresh retry after sibling release. The bounded-sniff report
also checks raw/decoded sample and candidate-parser ownership, growth overlap,
typed denial, scoring parity and the decompressed sample cap. Returned inspection
JSON has its own pre-admitted immutable owner, with ordinary/wide-Unicode header
and sniff contracts checking construction overlap, shared/local edges, concurrent
responses, serialization failure and final drop. The WASI reporter serializes it
directly while that owner is live. Caller-created clones, inline decoder storage
and codec internals remain outside those claims.
The ZIP metadata report exercises twelve archive forms and ninety terminal
callback-denial checkpoints. It checks preallocation envelopes, compatible
directory fallback, retained EOF owners, exact local/shared edges, competing-owner
release/retry, CRC/consumer error and public-profile cancellation cleanup. Its
conservative pinned-source allowance is distinct from actual heap/RSS usage; see
the [patch contract](../vendor/zip-2.4.2/CHOPPER.md).
Separate codec reports cover gzip input, ZIP member readers, and gzip and
raw DEFLATE output owners. The input reports exercise bounded codec buffers and
release after parse, checksum and cancellation errors.
The directory-path report verifies pre-admitted context/staging paths, exact
local/shared edges, retained final owners, denial/retry and publication disarm.
Live contexts keep an explicit directory reservation after other work is dropped;
file/directory/header/audit owner equations distinguish that baseline from leaks.
These are controlled contract
checks, not throughput or RSS measurements. The unlink case is a real WASI
filesystem-adapter pathname/type rejection, not an OPFS deletion or destination
export fault. The separate candidate build additionally checks retained-parent
shuffle/partition denial and replay, cancellation, persistent pressure, cleanup
failure at the retry boundary and terminal emission denial. The runner requires
that candidate report only with `--shuffle-partition`; use that mode for any
combined resource build enabling `experimental-shuffle-partition`, since it also
creates the isolated export destination. The ordinary resource pass verifies
that the candidate section is absent. The candidate also checks
real encoded-output planning, strict UTF-16/BOM CSV caps, cap rejection and writing
cancellation after retained-parent retry. It retains the verified WASI result for
the resource worker, which uses the same
[`exportResults`](../ui/src/browser/export.ts) copy/marker function as the
production worker. A separate same-origin OPFS destination verifies exact source
bytes and marker ordering; a test-only wrapper rejects the second write of a
large CSV after a real first write, checking abort and marker absence in the
partial folder. Additional controls reject result-writer close and marker
write/close, require abort of the failing writer and no committed marker content,
and reject an existing completed destination before modifying it. An empty marker
entry left by failed creation is not a completion marker. All test destinations
and retained source files are removed
before workspace cleanup, with parent-side cleanup covering worker failure.
This covers controlled browser export behavior, not a real quota-exhaustion
event, user-selected filesystem handles, worker-termination timing, cross-tab
coordination, deployed hosting or physical I/O. The export fixture enters at a
retained dataset boundary. A separate candidate contract enters the public
`prepare_with_memory_pool` API using immutable OPFS input and a caller-owned pool,
then exercises ingestion, dispatch, late-parent shared denial, exact encoded
replay/publication, cancellation and persistent pressure cleanup. It independently
checks IDs, fields, membership, metadata and strict UTF-16/BOM byte caps. This does
not inject through production worker request dispatch or test JavaScript
export/termination for that new preparation fixture.
After resource/experimental testing, restore the default production engine and
remove all test assets before packaging/upload:

```sh
node scripts/build-browser.mjs
npm --prefix ui run build:hosted
```

The production guard rejects an `engine.wasm` exposing the test entry point.
Both resource reactor names are test assets removed by `build:hosted`; the
release packager still permits exactly seven production members and rejects either
extra reactor. The final
default rebuild also prevents an experimental production engine from being reused.


## Protected SMALL installed contracts (#121)

This opt-in **test orchestration** keeps the owning fixtures, assertions and fault
routes. Ordinary invocations still use bundled Chromium, or the existing channel
selector, without these observations. They do not constitute protected acceptance.
Implementation and fake controls authorize no browser execution. The parent must
approve the concrete producer plan below and schedule each actual installed
Windows Chrome/Edge attempt. Missing configuration,
identity, guard, origin estimate or permission observation is a failure, never a
fallback to ordinary execution. No receipt here establishes an installed-browser pass.

Proposed SMALL limits, encoded exactly in `smallLimits` in
[`browser-small-observer.mjs`](../scripts/browser-small-observer.mjs):

| Limit | Proposed value |
| --- | ---: |
| Entire sequential channel batch, including restarts | 7,200 seconds |
| Cumulative owned storage, including retained earlier failures/logs/profiles | strictly below 20 GiB |
| Every involved physical volume before each launch / stop floor | 40 GiB / 8 GiB |
| Usable origin quota before contract work / stop floor | 4 GiB / 2 GiB |
| Sampling interval / maximum sample age | 1 second / 5 seconds |
| Individual guard/quota/receipt operation timeout | 4 seconds |
| No actual contract progress | less than 10 minutes |

Usable quota is `floor(max(0, quota - usage) * 0.8)`, retaining the engine's 20%
reserve. These SMALL thresholds require explicit parent approval. They are
separate from scale's 16 GiB startup / 2 GiB stop limits and the tiny driver's
128 MiB startup floor. No tiny fixture or export ceiling changes. Samples can miss
transient peaks; neither this observer nor its reservation is a browser RSS cap.
The parent guard must also enforce the ceilings during launch, shutdown, deliberate
kill/restart and any period without a live origin. Quota is sampled while the owned
origin is live, with a final sample before ordinary shutdown or deliberate kill.

### Packet and parent guard boundary

Use one immutable JSON packet per owning command/variant and channel. All paths
are absolute native Windows paths; JSON uses forward slashes or escaped backslashes.
Each packet has these required fields (substitute real values; placeholders deny):

```json
{
  "schema": "chopper-small-contract-observation-v1",
  "approved": true,
  "channel": "chrome",
  "argv": ["C:/test-checkout/scripts/test-browser.mjs"],
  "features": "default-product; separately declared test reactor",
  "source_commit": "639d1fe97d985b1544df0932321c6a93cca2567b",
  "source_tree": "b3bde79d552ee29760cb283d07938f9248cee0bb",
  "package_receipt_sha256": "1720f28a01cbbd7a30cbb8c8614b9efc2da01e57c765c625f51e8a5e3455c30d",
  "executable": "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "executable_sha256": "REPLACE_WITH_CURRENT_SHA256",
  "browser_version": "REPLACE_WITH_APPROVED_BROWSER_VERSION",
  "origin": "http://127.0.0.1:8422",
  "guard": "C:/owned-attempt/guard.json",
  "runner_lock": "C:/owned-attempt/batch/runner.lock",
  "receipt": "C:/owned-attempt/standard-observation.jsonl",
  "reservation": "REPLACE_WITH_HELD_PARENT_RESERVATION_ID",
  "batch_started_ms": 0,
  "volumes": ["C:/"],
  "limits": {
    "batch_seconds": 7200,
    "owned_bytes": 21474836480,
    "start_free_bytes": 42949672960,
    "stop_free_bytes": 8589934592,
    "start_quota_bytes": 4294967296,
    "stop_quota_bytes": 2147483648,
    "sample_ms": 1000,
    "stale_ms": 5000
  },
  "inputs": [{"path": "C:/test-checkout/ui/dist/engine.wasm", "sha256": "REPLACE_WITH_SHA256"}]
}
```

`executable` must match Node's canonical `realpath` spelling, including Windows
separators; obtain it programmatically rather than copying the displayed example.
`argv[0]` must likewise be the resolved owning script in the test checkout.
`batch_started_ms` is the actual channel batch start, shared across every command
and restart, never reset for each packet. `volumes` is the exact physical-capacity
inventory from the parent's freeze, covering source, artifacts, profile/temp,
output and receipt storage. Directories on the same volume need only one entry.

The abbreviated `inputs` above is **not sufficient**: enumerate and hash every
file in `ui/dist` and `ui/src`, the owning harness, `browser-small-contract.mjs`,
`browser-small-observer.mjs`, `browser-launch.mjs`, `browser-acceptance.mjs`,
`browser-artifacts.mjs`, `serve-hosted.mjs`, and all other relevant transitive
inputs/toolchains/dependency locks through the runner manifest. Symlinks in the
served/source trees are denied. Hashes are checked before launch, before observation
and at finalization; the packet itself is also pinned. The production WASM export
guard remains active. Test reactors and test-page assets require their own exact
hashes in each resource packet; they never replace the immutable default product
assets. The source commit/tree and package-receipt fields are custody references,
**not proof** from those labels: the parent must independently reconcile their
actual files against the frozen source and exact package receipts. Use a separate
test checkout/artifact overlay, never alter the frozen candidate or ZIP packages.

Graph (`test-browser-graph.mjs`) packets additionally require a canonical absolute
`python` executable path with one matching SHA-256 entry in `inputs`.
Include Python, `scripts/browser-graph-codec.mjs` and
`scripts/graph-codec-fixtures.py` in the frozen inputs. The Node helper is an
observer dependency for every selection. Both codec scripts require selected
harness Git-blob proof for Graph.

Before preflight and each ZIP codec spawn, the harness checks the declared hashes
of the canonical, nonempty Python executable and helper. It invokes the selected
Python with `[graph-codec-fixtures.py, mode]` and a 64 MiB capture bound. Ordinary
unprotected calls use `python3`.

The producer pins its reviewed harness snapshot in `HARNESS`, separately from
Product639. Use that exact revision for harness source mappings, including the
observer, Graph caller and both codec scripts. Freeze controller inputs separately
when their revision differs from the harness. Older ca48159 mappings lack the new
caller and cannot satisfy this proof. Create a new config/plan and fresh owned
root with config `python`, complete input hashes and directory inventories.
Re-run preparation, independently review the resulting plan hash, and obtain the
existing parent approval before execution. Product639, its packages and historical
receipts retain their original identities. Source/fake controls establish helper
correctness only, not installed-browser acceptance.

The opt-in [parent producer](#executable-parent-producer) integrates this heartbeat
with the existing [validation runner guard callback and owned Windows Job](validation-runner.md),
under the actual native host lock. The standalone runner CLI does **not** create
this guard or establish its reservation/Job. #122's scale controller is separate.
Protected execution remains parent-owned and blocked pending independently
reviewed exact configuration, native probe and selected acceptance.

The guard atomically replaces `guard.json` from its real census at least every
second and independently raises a guard denial when any limit fails. Its schema:

```json
{
  "schema": "chopper-small-contract-guard-v1",
  "allowed": true,
  "sampled_ms": 0,
  "last_progress_ms": 0,
  "runner_pid": 123,
  "child_pid": 456,
  "owned_pids": [123, 456, 789],
  "reservation": "HELD_PARENT_RESERVATION_ID",
  "reservation_held": true,
  "windows_job_kill_on_close": true,
  "batch_started_ms": 0,
  "cumulative_owned_bytes": 0,
  "volumes": [{"path": "C:/", "free_bytes": 0}]
}
```

Timestamps are Unix milliseconds. `runner_pid` must equal the Node harness's live
parent and the runner lock PID. `child_pid` is this Node harness, and `owned_pids`
must be the actual owned Job census, including the observed CDP browser PID once
launched. A configured boolean alone is not Job evidence: the parent must establish
`contain_session()` before spawning, retain its kill-on-close handle through
cleanup, and derive this census from its owned Job. It must discover the direct
runner child, not infer its PID from a label. Retain parent guard/census logs and
post-exit cleanup evidence separately. Denials can include an `error` string.
`last_progress_ms` reflects real harness checkpoints/runner command completion,
not a quota timer heartbeat. Cumulative storage is monotonic across this channel's
commands and retained attempts, not merely the latest live directory size; record
its accounting method and all owned roots. Set `TEMP`/`TMP` to a new owned root
before Node starts so Playwright temporary and persistent profiles are included.
Missing, malformed, stale, observations more than one second in the future, or
regressing observations deny acceptance.
The parent also checks the origin receipt independently and stops/reaps on monitor
loss; keep both controls through final process cleanup.

### Owning commands and observations

For each selected row below, create a packet whose `argv` is the absolute script
plus the listed flags, and whose `origin` has that port. A bridge packet chooses
an explicit free loopback port; ordinary bridge runs retain their ephemeral port.
Run sequentially; port reuse does not authorize connection to an existing listener.

| Owning script | Flags / distinct variants | Origin port |
| --- | --- | ---: |
| `test-browser.mjs` | none | 8422 |
| `test-browser-graph.mjs` | none | 8423 |
| `test-browser-graph-lifecycle.mjs` | none; `--composed` | 8425 |
| `test-browser-graph-inspection.mjs` | none | 8427 |
| `test-browser-graph-bounds.mjs` | none | 8431 |
| `test-browser-bridge.mjs` | none | packet-selected |
| `test-browser-cleanup.mjs` | none | 8423 |
| `test-browser-termination.mjs` | none; `--persistent`; `--persistent --process-kill`; `--persistent --process-kill --direct`; `--persistent --process-kill --composed` | 8424 |
| `test-browser.mjs` | `--resource-contracts`; `--resource-contracts --shuffle-partition` | 8422 |

Flags and their order are exact. Other protected commands/variants are denied.
For each row, the exact runner step command is:

```powershell
& 'C:/verified/node.exe' 'C:/test-checkout/scripts/browser-small-bootstrap.mjs' 'C:/owned-attempt/standard-packet.json'
```

Declare that same argument array as the step's `argv`, with the packet, wrapper,
all harness/product dependencies and verified executables in `inputs`, the JSONL
receipt in `artifacts`, dependencies on relevant exact final receipts, and explicit
step/batch deadlines within the shared 7,200-second channel ceiling. The bootstrap
waits at most five seconds for an atomic guard matching its own
PID and actual runner parent, then imports the wrapper in the same Node process.
Wrong PID/parent, denial, stale guard or wrong Job census fail immediately; the
pre-spawn null-child heartbeat only permits waiting. The wrapper
sets the channel, `CHOPPER_SMALL_CONTRACT_REQUIRED=1` and
`CHOPPER_SMALL_CONTRACT_PACKET`, then imports the owning command with the exact
approved arguments, without spawning another process. **Only execute that step
through the parent's guarded `validation-runner.run(plan, batch, guard=...)` after
Job containment and reservation acquisition.** This command is an entry point,
not permission to execute without the approved producer plan. Direct owning
commands can also use those three environment variables; an absent packet with
`REQUIRED=1` fails before launch. Unset them for ordinary CI.

Each launch binds explicit `executablePath`, configured hash, OS executable path,
OS parent PID/creation time/command line (Windows CIM), CDP browser PID and actual
`Browser.getBrowserCommandLine` arguments, owned profile and `browser.version()`.
Protected ordinary and persistent launches explicitly pass `--enable-automation`,
which permits that CDP command; Playwright defaults alone need not include it.
The flag is added only to protected launch options, without replacing default
switches or skipping the OS/CDP identity comparison. The metadata-only
`node scripts/test-browser-launch.mjs` component check covers both modes with
bundled Chromium; it does not establish installed-browser or product acceptance.
The browser must be a direct child of this harness and in the parent's owned Job
census. Configured channel/version labels alone cannot pass this binding. Temporary
profiles must be the fresh Playwright profile under the owned OS temp root;
persistent/restarted profiles remain the termination harness's local `mkdtemp`
owner. No process-name search, existing user profile or broad Playwright monkeypatch
is used. Unsupported identity APIs fail closed.

Quota runs on a separate inert page in the same owned context/origin, with one
exact unique test route. It records secure context, isolation, estimate, persisted
state and actual `persistent-storage` permission; it never starts a product worker.
That page's isolation is supplied by its test route; owning product assertions
retain responsibility for actual served product behavior. Sampling has one bounded
in-flight operation. An unexpected disconnect or sampler error remains a failure;
monitor failure closes only its acquired context to interrupt contract waits.
Only the existing termination harness can arm a deliberate browser kill, after a
fresh sample and exact PID recheck. It must observe actual process exit and browser
disconnection before relaunch. Worker termination fixtures remain local and never
exempt observer errors. Ordinary shutdown takes a final sample before close. Owning harnesses create explicit browser contexts so contract, quota-observer and app-smoke pages share the observed origin storage. Playwright's single-page `browser.newPage()` context cannot host an additional observer page; stop the observer before closing its context.

JSONL binding/sample/monitor-error/initialization-error/monitor-cleanup and deliberate
kill records are observation evidence, separate from the owning assertion JSON and
runner stdout/stderr/exit status. Cleanup failures retain earlier assertion and
monitor errors. Acquired servers are stopped and reaped with bounded escalation;
only owned listeners/routes/pages/timers are removed. Protected persistent failures
retain their profile for diagnosis; successful cleanup still removes it. Temporary
profiles retain Playwright's cleanup behavior, so preserve logs/receipts before
close. A passing assertion report with a later monitor/cleanup failure is a failed
attempt. No scale, RSS, real picker/external-device, eviction, power-loss or Windows
browser pass follows from fake controls or this tooling change.

Safe observer controls (no browser or engine):

```sh
node --test scripts/browser-small-observer.test.mjs
node --test --test-skip-pattern='real ' scripts/browser-acceptance.test.mjs
python3 scripts/test-ci-scope.py
```

The existing browser CI scope-test command imports the observer controls as well.
The unfiltered scope suite also has two real hosted-server lifecycle controls;
use the explicit skip pattern for fake-only implementation work.

### Executable parent producer

[`browser-small-runner.py`](../scripts/browser-small-runner.py) has distinct
`prepare` and `run` modes. Neither a packet nor this documentation grants execution.
The [inert example](../scripts/browser-small-runner.config.example.json) deliberately
denies until filled. It is a config shape, not a launchable acceptance packet.
No default CI entry point, product asset or owning fixture changes.

Parent-only commands, after separate configuration/approval and exact gates:

```powershell
& 'C:/verified/python.exe' scripts/browser-small-runner.py prepare C:/private/small-config.json C:/private/small-plan.json
# Independently review the entire plan, commands, exact hashes and source mapping.
& 'C:/verified/python.exe' scripts/browser-small-runner.py run C:/private/small-plan.json --approve-sha256 REVIEWED_PLAN_SHA256
```

Preparation hashes concrete inputs and verifies declared product/harness source
files against Git blobs at **639d1fe** and the selected **b68c2cf** harness
respectively. Historical ca48159 plans retain their original pins. The selected
product tree is `b3bde79d552ee29760cb283d07938f9248cee0bb`; the immutable package
receipt is `1720f28a01cbbd7a30cbb8c8614b9efc2da01e57c765c625f51e8a5e3455c30d`.
All seven default hosted assets and three ZIPs must match that receipt, and the
served default assets must equal those product bytes. Separate resource test
assets remain additional declared inputs; preparation performs no build or copy.

The caller must enumerate all relevant source/toolchain/transitive files,
including complete `scripts`, `ui/src`, `ui/dist`, `ui/node_modules` inventories
and package locks. `owned_root` must share the test checkout drive for the
maintained runner's relative input globs. Files on other inventoried volumes are
retained in its `external_input_manifest` and hash-pinned `source-manifest.json`;
the independent producer checks their identities. Node's executable also has the
runner's existing executable-hash check. No absolute-glob behavior is added to
the ordinary runner. Product source mappings cover tracked `crates`, `vendor`,
`.cargo`, Cargo manifests, UI source/native assets/package locks and the browser
build script at the product revision. The actual test checkout's `ui/src` must
contain exactly PRODUCT's UI files, mapped at their own Git paths in
`product_source`. In particular, candidate `app.ts` differs from main, and
candidate639 has no `hosted-workspace.ts`. Do not replace candidate UI with main
UI to satisfy a harness pin. No production UI overlay exception is needed:
resource test imports under `ui/src/browser` are identical at these revisions.

`harness_source` binds selected scripts and observer support to **b68c2cf**,
never production `ui/src`. Resource selections additionally require
`scripts/build-browser-tests.mjs` and both `ui/tests/resource-contract-*.ts`
entry points at that ancestor, mapped to their actual checkout paths. Other
product mappings may use immutable custody files. Every mapping retains its
per-file Git blob check, and every concrete input retains its hash/identity check.
The producer itself is a separate declared input, not a future self-referential
harness pin. Frozen606/CQual58 files, receipts and historical read-only replay
retain their original identities.

The selected source is the focused repository
`/opt/chopper/source/focused639` (sanitized locator alias) at
`639d1fe97d985b1544df0932321c6a93cca2567b`. Its
`scratch/focused-package-notices/source-reconciliation.json` explicitly records
reuse from build `feb9e099e5e0f22c4da8d0f5ba7269e221c91e9d` (tree
`57f6675f4e216d0b504c3063c17a2b37ab16ac20`): 1,116 inventoried source files are
unchanged; only `docs/release-packaging.md`, `docs/releases/native-usage.txt` and
`scripts/package-release.py` differ. Keep this reconciliation with package proof
and original build receipts; the new package receipt does not relabel the old
build or establish new runtime acceptance.
The published source locator is a sanitized alias; the original sealed locator
and source stay privately retained under the [public source boundary](history/public-source-boundary.md).

Matching candidate639 resource reactors are not yet built: resource acceptance
remains blocked on parent preparation and build provenance. Parent must qualify
the existing native probe against the final producer source; old native proof
does not qualify this change. The parent selected a separate candidate639 campaign
with fresh clocks only when preparation/execution starts. This source change
starts no campaign and approves no run. Each channel retains the exact 7,200-second
limit, under-20-GiB owned allowance, 40/8-GiB physical start/stop thresholds,
4/2-GiB usable quota thresholds and ten-minute no-progress stop; no retry or
automatic renewal is added. Preserve all previous charges, failures and history.

### Optional retained-origin accounting bridge

The producer config may set `retained_origin_manifest` to a canonical absolute
JSON file already declared exactly once in `inputs`, with its exact SHA-256.
Omit the field to retain the existing configuration path. The file must be
strictly smaller than 1 MiB and have this versioned shape:

```json
{
  "schema": "chopper-small-retained-origin-v1",
  "additional_retained_bytes": 0,
  "adopted_roots": ["C:/private/explicit-existing-custody"],
  "metadata": {"derivation": "Parent-reviewed original numeric terms and exact provenance"}
}
```

This is a shape example, not an approved zero debit or runnable manifest.
`additional_retained_bytes` must be an integer from zero through `2^64 - 1`
(booleans, fractions and nonfinite numbers deny). It is an **additional** debit
in the original recorded metrics: preserve known original numeric charges and
full allowances separately labeled in the parent-reviewed derivation. Optional
`metadata` is an object for that derivation/provenance, not an executable policy.
Unknown fields and duplicate JSON keys deny. The bridge computes no credits,
automatic subtraction, reconciliation or retrospective historical bound.

Every adopted root must be a unique existing canonical absolute directory on an
inventoried volume, without aliases or ancestor/duplicate overlap with another
adopted root, `owned_root` or any `history_roots` entry. Adoption can include
source/preparation custody without requiring a history ledger there; all source
blob, inventory and frozen-input proofs still apply. Existing history ledgers
retain their exact method checks and **whole** original cumulative charges.
The parent may exclude those original charges from the additional debit only
through a concrete reviewed derivation proving exactly which old history charges
are already added. Never mutate old roots or manufacture compatible ledgers.

Preparation includes the manifest in the required frozen inputs, packets and
runner input paths. Run rebuilds that plan; resource initialization rechecks
inputs, the bounded hash-pinned manifest and roots, adds the debit once, and
requires the live baseline to fit strictly below the unchanged cap before any
product command. The manifest is also runtime pinned. Adopted roots join the
same rounded, identity-high-water Storage census through cleanup: future growth
and new identities add charges; shrink/deletion give no refund; missing roots,
links, invalid census and ceiling exhaustion deny under the existing rules.

A new reviewed manifest may correct an earlier candidate's overly broad donor
scope: a checkout read only for provenance does not make unrelated CI files
SMALL-owned. Prove the actual SMALL write paths and keep those adopted; preserve
every prior debit and add the old whole root's fresh visible original-metric
charge without subtracting the subpaths that remain live. Keep all frozen input
and original history-ledger checks. A source path or proposed copy map alone
proves neither an executed write nor its absence.
Actual SMALL-owned roots and their recorded high-waters remain in the declared
live scope. Freeze the predecessor, exact scope correction, writer attribution
and transition census in the new manifest and approval. Manifest metadata remain
parent-reviewed evidence, not executable validation.

This establishes a fresh sampled current origin plus future identity highs,
additional to original-metric debts. It is not a retrospective/history bound,
physical-I/O measurement, fit certificate, runtime qualification or acceptance
proof. Unknown old intervals remain explicitly unmeasured, never zero. Before
using this interface, the parent must select the exact delivered producer commit,
migrate private constructor/source pins and input hashes, review the concrete
manifest and approved plan, and run the separate Linux/native Windows gates and
qualification. Existing product/build/harness pins, packets and receipts are not
reselected or relabeled by this bridge.

### Immutable resource routing handoff (#143)

The selected harness ancestor is
`b68c2cfba4bd9c49c94e007080f80522b5f9f293`. It retains the resource routing from
historical `ca481595399108e8208dc0586d88b8dca1ec9130` and contains the required harness support
sources, including `browser-artifacts.mjs`, and both resource
TypeScript entry points. The later producer pin is an ordinary declared input;
it is not a self-referential harness commit. Retained `1a6c4d6` source maps and
attempts keep their original identity and cannot prove this routing change.

Before freezing a separately approved candidate639 test namespace, the parent
must build matching resource reactors and map each variant as follows. Historical
reactors cannot substitute for candidate639 builds. No builds or copies occurred here.

| Retained original custody | Immutable served alias in new test namespace |
| --- | --- |
| Baseline resource reactor originally named `engine-resource-tests.wasm` | `ui/dist/engine-resource-tests.wasm` |
| Partition resource reactor originally named `engine-resource-tests.wasm` in its separate retained build | `ui/dist/engine-resource-tests-shuffle-partition.wasm` |

The parent must identify each candidate639 build by its receipt/path, byte length
and SHA-256, copy those exact bytes to the indicated aliases, and record equality
with the originals before input freeze. Basenames alone do not identify variants.
Keep both original custody directories and old support WASMs immutable; no rename,
overwrite, hardlink or rebuild of those originals. This change supplies no new
engine bytes or engine build certification. The seven selected 639d1fe production
assets and package receipt remain exact, including production `engine.wasm`.

Resource test HTML/JavaScript also needs separate preparation for this selection.
In the separate selected harness checkout, `node scripts/build-browser-tests.mjs
--resource-contracts` compiles `ui/tests/resource-contract-tests.ts` and
`ui/tests/resource-contract-worker.ts`. Do this before freeze, never in the
frozen candidate or an existing approved namespace. Retain the exact command,
checkout commit/tree and clean status, Node/npm/esbuild versions, package-lock and
installed dependency identities, stdout/stderr, and byte lengths/SHA-256 of the
three generated files. Capture esbuild's `metafile` input lists for the same two
entry points/options and hash every transitive input, including WASI shim and
browser fs/export/history dependencies. Verify mapped tracked inputs against Git
blobs at the selected harness ancestor; declare test sources/build script,
dependencies and outputs as concrete frozen inputs alongside the required
`harness_source` mapping. A Git label or output hash alone is not rebuild proof.
Do not run `build:hosted` in this test namespace: restoration removes test assets
and rebuilds product JavaScript, which must remain frozen 639d1fe bytes.

A changed test namespace invalidates earlier inventory hashes and prepared plans;
the parent must reconcile the complete `scripts`, `ui/src`, `ui/dist` and
`ui/node_modules` inventories and source maps before independent plan review.
The existing two allowed resource command variants then share the same immutable
files without widening packet variants, flags or workload scope. This handoff does
not authorize a new launch, retry, resume, #103 exception or clock renewal. The
historical frozen606 Chrome deadline remains **20:39:36.963** for that campaign;
its cumulative records and charges remain retained. Candidate639 has the separate
parent-selected campaign described above, with unchanged SMALL limits. Installed acceptance, independent review and exact
local platform gates remain parent-owned.


Required config keys follow the example: canonical absolute native paths for
`root`, fresh `owned_root`, `node`, `python`, `browser`, `package_receipt`, file lists
`product_assets`, `package_zips`, `history_roots`, `input_directories`, and `volumes`;
source maps `{path, git_path}`; concrete `inputs` entries `{path, sha256}`; explicit
`channel`, observed `browser_version`, fixed commit/tree references, exact `limits`,
and bounded `commands` entries `{script, flags, origin, timeout_seconds}`. Nulls,
missing inputs, changed identities, unsupported variants and repeated commands deny.
Each command is at most 900 seconds; no matrices, retries or resume. Preparation
freezes the channel start clock, so review time consumes the 7,200-second ceiling
rather than renewing it. A fresh selection requires independent approval.

The supervisor holds `local-ci.host_lock()` through cleanup and records the actual
lock file identity, reservation ID and owner. A separate worker establishes
`contain_session()`, publishes its native Job handle, then waits. The supervisor
duplicates and independently queries that handle's actual limit flags and bounded
PID census. After verification, the worker closes its original handle, transferring
ownership to the supervisor; supervisor death therefore closes the last handle
and kills the worker and descendants even during runner input hashing. The
supervisor retains its duplicate through termination, empty-census verification
and worker reap. No PID/name-wide kill or process-name enumeration is used.
Cleanup keeps the independent watchdog active through Job-handle release and
bounds each native/filesystem operation. Source, capacity, storage and deadline
checks continue through worker reap and final metadata writes. A conservative
1 MiB final-metadata charge is retained in the last storage ledger; a post-write
census must fit that charge before the controller can return success.

The worker calls **maintained**
`validation-runner.run(plan, batch, guard=..., observe=...)`. The optional
[immutable observation interface](validation-runner.md#optional-immutable-status-observation)
atomically publishes a bounded PID/reservation/exact-plan-bound status prefix.
The first checkpoint is durable before the worker announces its owned Job, so
the verified parent can begin reading immediately after handoff.
The parent validates that compact file inside its existing 800 ms sample; it
never loads the growing rich `batch/status.json` for live supervision. The worker
guard also uses the immutable callback snapshot. Full rich status, manifests,
input and artifact maps remain retained for audit. Missing, malformed, regressing,
substituted or incomplete terminal observations fail closed. Only completed
runner steps with matching observer cleanup receipts refresh useful progress.
This interface neither renews an expired channel deadline nor supplies a
continuation/retry or controller recovery mechanism.
Before each spawn it waits for a fresh null-child acknowledgement for that exact
attempt. The same direct Node child waits for its own PID heartbeat before
importing the contract wrapper; no intermediate Node parent or guessed PID.
`TEMP`/`TMP` are set to the fresh owned root before Node starts. Job membership,
parent/creation identities, source/packet/tool metadata, native host reservation
and physical free space are checked independently of any browser/origin.
A separate watchdog terminates the Job and reaps the worker on a late atomic
heartbeat, even if runner hashing or supervisor filesystem sampling blocks.
Sampling itself has an 800 ms bound; atomic heartbeats must complete within one
second. A false denial remains a failed attempt; it never relaxes a threshold.
Each immutable-input scan reads shared ancestors and file metadata once, then
reuses that scan's observations for the declared files and directory inventories.
No observations survive into the next scan. Readonly frozen inputs may have hardlink
aliases: preparation pins their bytes and live scans still bind device/file identity,
size and timestamps. Symlinks, reparse points, changed metadata and changed names
still deny; the deadlines are unchanged. Owned storage keeps its single-link rule.

The live storage census also uses a separate fresh metadata scan, deduplicating
shared ancestors within that census. This keeps profile growth during launch from
repeating canonical-path resolution for every cache entry on top of the full
immutable-input scan. Every census still visits the complete owned namespace,
checks root/ancestor reparse metadata, file type and single-link ownership, and
retains identity high-water charges. No metadata cache crosses census boundaries.
Storage may retain at most 200,000 validated lexical Path-to-parent decompositions;
new paths beyond that cache size are still validated and sampled without caching.
These immutable decompositions skip repeated parsing only: each yielded directory
and its postcheck, and both root checks, still start a fresh metadata census.

Successful `guard-history.jsonl` entries include `sample_trace`: start/completion
events for inputs, reservation/pinned files, Job census, process identities,
capacity and storage. Completions include monotonic elapsed seconds. On denial,
`control-failure.json` retains the available trace, including the last started
phase if it blocked. Trace writes do not renew or extend either watchdog. A
launch-preflight receipt without a browser binding cannot establish whether a
browser process started; retain temp/profile artifacts and independent process
inspection alongside the failure.

The producer consumes observer JSONL independently. Samples must match a guard
actually produced from its native Job census, with a live origin estimate,
permission observation and the correct child binding. Initial usable quota is
4 GiB; subsequent live samples require 2 GiB and age at most five seconds.
Quota disappearance, loss, truncation, monitor/cleanup errors and unexpected
browser absence deny. Only the explicit process-kill variant and its exact
armed/observed PID receipts suspend quota expectation; all physical/source/host
checks continue during that interval and restarts. Receipt and quota chatter do
not advance progress. Only a completed runner command advances `last_progress_ms`;
a command without a meaningful checkpoint therefore stops at ten minutes even
when its configured maximum is fifteen minutes.

Storage accounting sums per-file identity high-water allocation envelopes (4 KiB
rounding plus metadata allowance), never subtracting deleted/shrunk bytes. It
covers temp profiles, all command receipts, failed/partial logs and prior retained
roots. Windows birth time disambiguates reused file IDs. Known file/directory
deletion races retain prior charges; an unseen disappearing entry cannot be
bounded and fails closed. Symlinks, junctions, hardlinks, missing owned roots and
a census exceeding 200,000 identities deny. Every prior root requires a declared,
hash-pinned `storage-ledger.json`: its historical charge is added and its visible
files conservatively charged again. This intentionally overcounts rather than
crediting deletion. The current ledger is atomically retained at each heartbeat.
As with the observer, sampling cannot certify transient peaks between samples;
this is conservative sampled accounting, not a filesystem hard quota or RSS cap.

Retain the whole owned directory: `guard-history.jsonl`, `storage-ledger.json`,
`reservation.json`, `source-manifest.json`, packets, `runner-plan.json`, `batch/manifest.json`,
`batch/status.json`, numbered stdout/stderr, observer receipts, worker streams,
`control-failure.json`, `cleanup.json` and `result.json`. A hard kill can leave a
partial running attempt and runner lock; these remain evidence, never resumable
passes. Failure and cleanup errors remain separate from owning assertions.

Focused controls (no browser/product execution):

```sh
python3 scripts/test-browser-small-runner.py
python3 scripts/test-validation-runner.py
node --test scripts/browser-small-bootstrap.test.mjs scripts/browser-small-observer.test.mjs
```

The **unrun parent-owned native probe**, after the live exact gates finish, is:

```powershell
& 'C:/verified/python.exe' -B scripts/test-browser-small-runner.py --native-probe C:/private/fresh-small-native-probe
```

It runs a safe Node fake through the maintained runner, actual native Job census
and same-process bootstrap handshake, retains logs at that fresh path, and imports
no browser/product harness. The probe disables bytecode before loading its helpers
and passes `-B` to its transfer worker, preserving frozen source namespaces even
when the caller has no bytecode environment setting. Fake Linux controls do not establish this integration,
Windows Job API behavior or installed-browser acceptance. Both independent review
axes, exact platform gates, native probe and actual selected contracts remain
parent-owned. Actions remain disabled; no acceptance or delivery follows from
this implementation.


Storage ancestor metadata is refreshed whenever the walker yields a directory,
then shared only among that directory's entries, and checked again after those
entries and at the end of each root traversal. A root or ancestor replaced
with a symlink/junction before traversal therefore denies instead of reusing its
pre-walk observation. No observations carry into the next directory or sample.

The guard overlaps its full frozen-input scan with the independent dynamic
storage, process, reservation and capacity census. Both must complete successfully
before the same allowed heartbeat is published. The outer 800 ms sample bound,
one-second hard watchdog and all freshness/capacity limits are unchanged; a
blocked or failed input scan cannot be replaced by a completed storage scan.
Per-phase traces may therefore interleave and report the actual elapsed phase
cost rather than a sequential schedule.

### Read-only guard latency qualification

Before another parent-approved launch, the parent can run the following in the
native candidate checkout with its verified Python and a freshly reconciled
candidate plan. Replace the two private paths. Preserve stdout/stderr as native
diagnostics. The old approved plan remains evidence; source drift after a fix
must deny rather than silently rebinding its frozen entries.

```powershell
@'
import json, runpy, time
from pathlib import Path
m = runpy.run_path('scripts/browser-small-runner.py')
plan_path = Path('C:/private/reconciled-candidate-plan.json')
retained = Path('C:/private/retained-browser-runtime')
p = json.loads(plan_path.read_text())
s = m['Storage']([retained, *p['config']['history_roots']])
t0 = time.perf_counter()
m['check_inputs'](p)
t1 = time.perf_counter()
charge = s.sample()
t2 = time.perf_counter()
print(json.dumps(dict(plan_sha256=m['runner'].digest(plan_path),
    inputs_seconds=t1-t0, retained_storage_seconds=t2-t1,
    combined_seconds=t2-t0, visible_storage_envelope=charge)))
'@ | & 'C:/verified/python.exe' -
```

This reads the complete candidate input namespace and retained launch profile;
it starts no worker, Node, browser or engine and writes no attempt files. The
visible storage envelope excludes prior retired-byte ledgers. It omits the live
Job/process census, held reservation and pinned runtime checks, physical capacity,
runner hashing contention, observer and heartbeat writes. Passing this diagnostic
therefore does not qualify a full guard cycle or establish installed acceptance.
Parent-owned native fake/probe coverage and exact platform gates remain separate.


## Release tiny integration preparation

The external [scale acceptance harness](../scripts/scale_acceptance/README.md#tiny-final-product-integration-handoff-104)
connects the production app/client source and execution history outside `ui/dist`,
using unchanged frozen production workers/WASM and a fresh persistent profile.
Its tiny-only manifest pins source/assets/browser/toolchains, retains failures and
uses the existing guarded validation runner. Compilation/negative controls do not
establish a browser pass. Parent-scheduled installed Windows Chrome/Edge execution
and final frozen assets remain prerequisites for #104; injected File/OPFS handles
remain separate from #105's actual-dialog/external-filesystem coverage. Existing
small harness bounds and production WASM guards remain unchanged.

## Cloudflare Pages

Deploy only `ui/dist` after `build:hosted`. The directory includes the `.wasm` binary and `_headers` needed for worker isolation and WebAssembly execution. There are no Functions, databases, or file-storage services to configure.

The CI browser job builds and validates an artifact named `chopper-hosted`. Download/extract it and use Cloudflare Pages Direct Upload, or publish that built directory using Wrangler. For Git integration, arrange the Rust WASI build in CI rather than relying on Cloudflare's default frontend image. Do not publish the native `ui/index.html`/`ui/public` build as the hosted app.

No Cloudflare deployment is performed by the local build scripts.

Before an explicit upload, verify the Pages project and production branch with
`npx wrangler pages project list --json` and
`npx wrangler pages deployment list --project-name PROJECT --environment production --json`.
The local Git branch can differ from the Pages production branch. Publish the
prepared directory with
`npx wrangler pages deploy ui/dist --project-name PROJECT --branch PRODUCTION_BRANCH`;
mark an uncommitted build with `--commit-dirty=true` and retain its source/package
hashes. See the [Wrangler Pages reference](https://developers.cloudflare.com/workers/wrangler/commands/pages/).
The [recorded publication and live Chrome/Edge acceptance](performance.md#validated-current-build-published-to-pages-2026-10-22)
checks served hashes, input profiling, preparation, capped export and cleanup on
one small fixture. It does not establish native picker/external-filesystem,
large-job or other-device acceptance.

CSV settings can now be detected explicitly from a sample of at most 64 KiB of decompressed input. Review the suggestion: BOMs identify UTF-16/UTF-8; otherwise UTF-8 is assumed, and header/quote/escape choices are preserved. The picker includes CSV, TSV, text, and supported compressed extensions, with an all-files option.

Analysis includes expandable distinct-value lists for selected partition/stratification columns. Lists cover the whole validated input but are capped at 64 columns, 100 values per column, and 256 KiB total; incomplete lists are labeled. Progress shows phase-local rows, elapsed time, observed throughput, and temporary usage. No overall percentage is shown because multi-pass work does not provide a reliable completion total.

Analyze uses the same full-file input-statistics path as native `chopper analyze`. It reports exact input row counts and exact or explicitly approximate distinct counts; sorted input is not truncated to a prefix. The cached profile can be reused across configuration edits in the current worker. Picking another File object clears it, and Run, cancellation, or completion can terminate that worker and discard the cache. A new multi-column grouping or stratification combination triggers another full scan. A root Partition can reuse matching cached skew or derive it from complete single-column counts. If those facts are missing, Analyze refreshes them in its usual scan. Analyze retains no executable output. Run does not depend on an earlier analysis.

The graph inspection harness exercises the real hosted page with fused/repeated
work, default/advanced and graph/list selection, events, keyboard focus and frozen
configuration across later Analyze/Prepare activity. It independently checks
exports. Pass `--screenshots=<directory>` for targeted 1280px/390px visual review;
its worker pause is test-only and ships no production injection API.


Final graph acceptance adds `node scripts/test-browser-graph-bounds.mjs`,
`node scripts/test-browser-graph-lifecycle.mjs --composed` and
`node scripts/test-browser-termination.mjs --persistent --process-kill --composed`.
These cover focused saturation with real cancellation and gzip/operation lifetime
combinations. The [path inventory and measurement contract](execution-graph-acceptance.md)
separate correctness controls, resource bounds and the accepted scoped overhead
result, retaining earlier unmet reports and precision-selection limitations.
Run `python3 scripts/test-execution-graph-analysis.py` for the independent
measurement-gate regression controls and
`python3 scripts/test-execution-graph-extension.py` for exact bootstrap/provenance
checks on a single retained-data precision extension. CI does not launch the long benchmark.

## Result ownership and publication contracts

Async results carry a source/configuration origin: input selection identity,
input parsing/member settings, submitted configuration, draft revision and run
identity. `result-ownership.ts` owns these comparisons. Hosted lifecycle slots
pair result values with their origins; unrelated draft edits preserve an input
profile, while replacement input or parser settings reject a pending profile.
Run captures its submitted configuration and source/destination handles before
permission/dispatch. Edits made while permission is pending cannot change that
submission; a later Run captures the new draft. Analyze retains only advisory
input statistics, with source/configuration origins for invalidation. Internal
engine snapshots retain their exact encoded-byte contract.

State polls are ordered within a command epoch. A late response cannot overwrite
a newer response or cross a Run/Analyze/Cancel acknowledgement. Starting
a newer poll does not discard an older response while the newer one is pending.
Worker generation checks independently reject messages from retired sessions.
Completed Runs retain their submitted origin for historical results; they never
supply column values to an unrelated current input.

Browser processing and destination publication remain different boundaries.
Either destination path closes every output writer, closes the marker, then reads back
that exact marker (at most 256 bytes), with or without observation enabled. Only
an exact match returns a destination-bound publication receipt. The page validates
its folder, output path, version and file count before obtaining a typed verified
publication and entering Complete. Missing, malformed or stale receipts fail the
Run. Readback failure can leave valid files and a marker on disk, but cannot
claim verified success. Cleanup checks ownership and preserves results with a committed marker.
Cancellation and cleanup retain their existing policies, including a retained
same-Run confirmation without resurrecting cancelled job state.

## Hosted workspace (#127)

The rail’s top-right sun/moon button switches to the opposite of the rendered theme.
System is the default and follows OS changes live. A switch away from the system
preference persists in `chopper-color-scheme` and synchronizes across tabs; switching
back removes the override. Later OS changes do not erase an existing override.
Its accessible label names the next action, and its tooltip identifies the current
theme and automatic mode. Blocked storage still allows current-tab changes.
Themes retain the grid and use a softened code-green accent, brighter in dark
mode. Run uses a subdued forest-green fill in both modes; header controls and selected
CLI platform tabs follow the chosen theme. Color changes apply immediately to keep text/control contrast consistent;
contrast-heavy execution canvases and CLI code blocks remain dark islands.

The hosted build emits a color-scheme meta tag and a minimal early preference
bootstrap before the stylesheet. `scripts/hosted-theme.mjs` owns the exact script
bytes and its SHA-256 CSP allowance, shared by the local static server and Pages
headers; `unsafe-inline` is not enabled. The production artifact has seven files.
`node scripts/test-browser-theme.mjs` checks the saved override before app.js can
run under the real CSP, system changes and forced colors. Use `--screenshots=DIR`
for both themes at desktop and mobile widths. The graph refinements harness also
accepts `--theme=light` or `--theme=dark` for real Run inspection.

The hosted workbench uses neutral paper surfaces, graphite execution chrome and
green for actions/selection. A fixed viewport layer holds the visible 40px page grid and emerald/teal washes
while the interface scrolls above it. A fine
tonal card border add depth around solid card surfaces; focus highlights the active section without
changing geometry. Header dividers are softly inset inside cards so they do not
visually join the page grid; paired title/body rows retain their geometry.
Forced colors use solid native surfaces and borders. The workspace uses a themed grid and accent behind neutral editing cards with consistent icon and divider colors. Step numbers use operation colors, and hover connectors and outlines match those numbers. Icons use the neutral palette. Field values use regular weight, labels
and secondary controls use medium weight, and headings/main actions retain
semibold emphasis. Desktop inputs are 0.875rem (14px at the default root size);
coarse-pointer inputs stay at 1rem to avoid mobile focus zoom. Keyboard focus and
forced-color selection indicators remain visible; reduced-motion preferences
suppress control transitions. These rules are scoped to `.hosted-workspace`.

The **Clear temporary data** control appears in the utility dock only when
abandoned workspace data is detected. Its tooltip explains that source and
exported files and active workspaces are preserved.

The sticky top rail groups the theme button with quiet GitHub and Buy me a coffee
links on the right, opening links in a new tab with no third-party widgets. The
utilities wrap below the brand on narrow screens. Conditional cleanup and its
status share this group; there is no separate cleanup footer or “On-device
processing” badge.
The measured rail height offsets sticky section navigation, anchor targets and
the Execution plan pane. Only the bottom processing strip reserves footer space.

The hosted app follows Source → Output → optional ordered pipeline → Resources.
At widths of at least 1600px, a slim text navigation rail sits beside the capped
configuration workspace; smaller screens keep compact sticky top navigation.
Both layouts use the same links and current-section state. Configure and Execution
views preserve the existing form, output plan and graph DOM. A new observed Run
opens Execution once; subsequent progress updates respect a manual return to
Configure. Execution places the graph beside the output plan at widths of at least
1100px, with results beneath the plan in its scrollable sidebar. Smaller screens
stack the graph and plan. Configured plan links return to their editor controls;
graph-to-plan connectors remain available in Execution. The header view switch
also allows manual inspection before a Run. A short View Transition keeps the
plan as an anchor on desktop, with a simple crossfade on narrow layouts. Reduced
motion and missing API support switch immediately and focus the new view heading.
The fixed bottom action bar shows Run and the next setup requirement. During
profiling and Run it shows the current activity, elapsed time, and Cancel, with
View execution available from Configure. The page reserves the measured bar
height, including safe-area padding, so content remains reachable above it.
Execution also shows the active phase and available row and temporary-storage
counts above the graph. At the end of the job, the bar returns to Run.
In Configure, completion returns focus to results (failure to the error) unless
focus is inside the editor, preserving in-progress configuration edits. Execution
preserves graph focus and scroll on completion; disappearing processing controls
return focus to the view heading. Failures reveal their error. View execution opens the
graph, or the progress/results card before a graph exists.
Navigation follows the visible section with native scroll targets and an
IntersectionObserver/position fallback; `aria-current` mirrors the selected
section. Clicking inside a configuration card selects its navigation link and replaces
the URL fragment without scrolling; the next scroll resumes visible-section tracking.
In Configure, the page title aligns with the configuration shell.
Section jumps account for the top bar on smaller screens; the wide rail
does not reserve vertical header space.
Source shows selected-file size and preview column count together with a bounded,
collapsible sample. File size comes from the chosen browser File, not the job JSON;
unknown metadata is not inferred from the preview. Loading a different source or
changing parsing clears the old sample until the new preview is ready.
Full-file input analysis is associated with the selected source/member and input CSV
settings, including a new selection of a same-named browser file. Output, resource
and pipeline edits do not discard its valid input totals or column values; pipeline
estimates are labeled as belonging to the analyzed configuration after edits.
Late results for another source are replaced with an instruction to analyze again.
The analysis card emphasizes exact input rows, columns and scan duration; pipeline
estimates and coverage details start collapsed. Bounded column values from profiling
or exact preparation appear beside the input preview as expandable per-column rows,
with exact/estimated distinct labels, wrapped value chips and a column-name filter
for larger lists. These filters are inspection controls and never edit the Job or
invalidate exact confirmation. Preview rows remain a bounded sample, separate from
full-file counts. Source changes clear the old value inspector.
The value inspector uses soft sage in light mode and a slate surface with a restrained
green tint in dark mode, indexed column rows, exact/estimated count badges and readable
value chips. Column-value disclosures start collapsed and preserve manually opened
columns across same-source refreshes. Complete low-cardinality lists show exact input-row shares as a
ranked list with percentage labels and slim 0–100% bars, largest first. Counts
accumulate during the existing analysis/preparation scan. Crossing the 100-value
or 256 KiB display limit drops frequencies for that column and retains the bounded
value preview without percentages; no extra scan or unbounded table is added.
The empty field is a distinct value. Percentages use all input rows as denominator,
not the displayed subset or final pipeline groups. Legacy responses without counts
keep value chips. Summary padding keeps expanded chevrons and count badges inside the row. Main section
headers use warm stone for Source, blue for Output plan, and neutral slate for
Results, with muted teal, violet and amber for Output, Pipeline and Resources.
Navigation uses slate; the processing bar follows the page chrome, keeping green
for actions, state accents and the input inspector. Headers retain their labels and icons. These
accents aid scanning without changing field values, estimates or the Run action.
Output-plan section number badges share the exact header palette of their
configuration cards. Step hover and selection use faint neutral surfaces and
outlines in the editor, output plan and execution views; matched-plan connector
colors and explicit keyboard focus indicators remain available. Green accents lean slightly brighter and less blue while the
Run button uses a subdued emerald fill with contrasting text in both themes.
Forced colors restore system surfaces, text and focus indicators.
Pipeline steps have operation icons, short effect descriptions, dedicated drag
handles and the existing movement arrows. Dragging previews a before/after
insertion line; order changes only on drop. Handles also support Up/Down keys,
restore focus after moves and announce the resulting position. In-place drops and
cancelled drags preserve the draft and current input analysis. Selected-column
handles show insertion markers across wrapped chips and accept drops at either
end, preserving exact named versus numeric selectors. Column reordering remains
scoped to its own picker, including partition and stratification selectors; Left/Right
keyboard reordering remains available. External/cross-picker drops are ignored. Each output-plan step has a concise linked summary with its full existing
rules in a disclosure; draft refresh preserves open explanations. Unselected plan
links use neutral text; hover and selection use faint neutral surfaces and outlines,
while explicit processing status keeps its semantic accents.

The hosted execution graph uses a dedicated wide pane beside the plan in Execution.
The graph grows with its content at every zoom level, so the page scrolls through
all activity rows. Drag the Zoom slider or use its arrow keys to change the scale.
Moving the slider disables Auto-fit. Check Auto-fit to fit the width again.
When the graph is wider than its pane, drag the background sideways or use
horizontal scrolling. Timeline colors match output-plan operations, with fused
work using its first mapped operation color and readable context labels.
Each graph card has a small decorative diagram for its observed physical step.
Fisher–Yates swaps records; uniform shuffle ranks random-key rows; spills, merges,
allocation, grouping and codecs have their own gestures. Auto follows the observed
strategy rather than predicting one from configuration. These are illustrative
loops, not progress percentages or throughput measurements. Only actual active
attempts animate; diagrams pause in place between attempts and resume without
restarting for the next group. Status badges use title case and keep In Progress
across groups, marking Completed only after processing confirms no more groups
will invoke the step. Motion pauses for
offscreen cards, hidden tabs and the graph's Pause motion control. Reduced motion
uses static diagrams. List and Timeline retain their existing presentation.
`node scripts/test-browser-step-motion.mjs` checks real Fisher–Yates and uniform
shuffle facts, live input/exact-allocation/intermediate-materialization row/time
progress, both themes,
pause/resume, reduced motion and completion. The harness holds real observation
delivery briefly so short engine phases remain inspectable;
it does not measure processing speed. A test-only hold at materialization start
opens the existing progress throttle without fabricating engine counters. Use
`--screenshots=DIR` for active cards.
In Configure, the editor and output plan are centered together with a maximum
width of 86rem, or 106rem when the paired plan/results columns are visible on wide
screens; the editor remains at most 65rem wide. Counts and short CSV values have
compact widths, while paths and column selectors retain available form space.
Resource and allocation rows adapt to the editor container width.

The pipeline editor is always visible: users can add and edit steps without
opening a disclosure. Split/allocation modes use compact native radio choices;
long allocation and shuffle explanations are disclosed beside their settings.
Path/Browse and amount/unit controls share a joined outline. Parsing controls that
do not apply to that direction are hidden while their configuration values remain
intact. Resource budget groups Processing and Safety limits separately; the
browser-managed temporary directory is retained in configuration but hidden.
`CHOPPER_CONFIG_SCREENSHOTS=DIR npm --prefix ui run test:workspace` optionally
captures the expanded editor in both themes at desktop and mobile widths. The
Output plan starts with the proposed format, destination, and strict CSV caps,
then shows the linked pipeline. Details are available on demand. The Results
card leads with the saved location and file count, followed by warnings and
details. Configuration stays visible at narrow widths, and
counts and CSV bytes remain unknown until processing. Input and output parsing/serialization controls remain
independent. Source detection is explicit and bounded; Analyze input remains an
optional full-file profile. Run submits the current draft without requiring
Analyze and always validates its consumed input. No output snapshot is retained
for later user approval. Editing changes the next Run configuration. A late acknowledgement cannot validate
a newer draft. Previous processing results are labelled when the draft changes.

[`hosted-workspace.ts`](../ui/src/hosted-workspace.ts) moves the existing form
controls at hosted startup. It adds presentation and navigation; the existing
[`app.ts`](../ui/src/app.ts) still reads the Job and calls the same browser client.
The client, lifecycle, workers, WASI engine, OPFS owners and export completion
marker are unchanged. There are no CSV upload, processing service or telemetry
additions. The hosted build gate is a compile-time constant. Older notes about a
separate native serve layout, picker, publication wording or generated native
bundle describe the retired 0.1 interface and do not apply to current source.
This UI design change is independent of the frozen 6069cef release source and
packages.

The hosted design uses a compact top bar, theme-aware surfaces and restrained
green action accents. Configure keeps source, output and pipeline controls visible;
less-used encoding and resource settings use disclosures. A new observed Run opens
the separate Execution view, pairing the growing graph with the output plan and
retaining node inspection when switching views. Processing controls stay in the
bottom bar.
No prototype HTML or simulated data is imported by production source.

Run `npm --prefix ui run test:workspace` after installing UI dependencies and
Playwright's bundled Chromium (`node ui/node_modules/playwright/cli.js install chromium`
if absent). The suite serves HTML/CSS/compiled app code through intercepted requests
in a disposable browser context, replaces client responses and forbids workers.
It starts no server, product job, engine, OPFS or real picker. It exercises the
actual form handlers, import/export preservation, seed-free submissions, all operation
kinds, column picking, action routing, prepared revision invalidation, keyboard
focus, validation disclosure and responsive navigation. Native entry-point layout
has a separate DOM control. These simulated responses establish UI interaction
coverage only; existing real editor, lifecycle, export, cancellation and marker
acceptance, embedded native validation and platform gates remain required before
delivery. They do not establish installed Chrome/Edge, Windows, engine correctness,
performance or accessibility certification.

### Input samples and output-plan actions

Selecting a source or importing a job requests a bounded sample using the current
input encoding, dialect and ZIP member. The preview is incomplete and never
replaces full validation. Imported browser paths still require choosing the file
with Browse to grant access. Analyze input sits beside the Source preview and
describes the input facts it can show. Run stays in the bottom action bar and
submits the current settings independently of Analyze.

### Pipeline operation modes

The operation menu groups related methods under one action. **Split into equal
parts** offers **Consecutive rows** (`balanced`, the default) and **Alternating
rows** (`interleaved`). Both produce counts differing by at most one; only the
consecutive mode restores input order when parts are concatenated. **Assign
groups by percentage** offers **Exact counts** (`assign`, the default, rounded
to whole rows) and **Approximate counts** (`assign_probabilistic`, independent
random assignment). These labels describe output guarantees rather than promise
relative speed. Imported jobs retain their operation types, counts, named groups
and strata; changing a mode changes only its operation type. The stored Job
schema and engine behavior are unchanged.

### Live configuration checks

The output card lists incomplete or incompatible settings, with links that reveal
and focus the relevant editor controls. Guidance updates while editing; invalid
field styling and screen-reader error descriptions appear after interaction or a
submission attempt. Run and Prepare reject invalid configurations locally;
Analyze input permits a missing output destination. Checks cover paths being
filled, numeric/byte-size limits, exact percentage totals and group names, selected
columns, supported CSV encodings/dialect/header/BOM combinations, part/file limits,
and record/worker limits versus the requested memory budget. The browser form checks Auto record limits against its 256 MiB baseline. Choose
manual memory in Advanced to configure larger record limits. Run still checks
the actual resolved budget. Filesystem existence/permissions, full-input validity and
output-cap feasibility remain engine checks. Equal parts with hard limits remains
an advisory warning because the combination can be valid.

Inactive controls keep their values: manual memory is disabled under Automatic,
compressed targets under uncompressed output, and ZIP member selection for known
non-ZIP sources. Input line endings and BOM are detected while reading; their
configuration controls are disabled. Output skip-empty-lines is input-only and
disabled. The hosted temporary directory is disabled with an explanation that
browser-managed storage is used. Automatic memory does not override explicit
worker or record limits, so those controls remain editable.

### Auto and Advanced execution

Auto shows who controls processing settings in the Resources card and on
shuffle steps. Switch on Advanced to edit working memory, worker requests,
grouping, and shuffle strategy. Safety limits and requested pipeline and
output settings apply in both modes. The hosted engine uses one worker.
After a completed Auto run, Resources reports its working-memory budget and
peak writer slots used. The Output Plan reports the physical plan.

### Linked output-plan text

The current configuration summary and plan sentences are color-coded buttons.
Hovering or focusing a sentence outlines its matching configuration; a closed
disclosure is highlighted without opening it. Clicking or pressing Enter/Space
opens relevant disclosures, scrolls to the setting and focuses its control. Each
pipeline step has a separate sentence so links remain unambiguous after reordering.
Row/byte targets, compression, source, destination and resources link to
their own controls. Configure places Output directly after Source. The Output Plan
keeps Output after Pipeline and links each heading to its configuration card.
Ordered plan items use the corresponding pipeline step numbers. Hovering an editor step brings its plan entry into view. Underlines are
omitted, while hover backgrounds and keyboard focus outlines indicate interaction.
A noninteractive curved connector joins the active text to the highlighted
configuration on hover, focus or click, following scrolling and resizing. The
connector is anchored to the output card edge at the linked text’s height,
keeping its route outside the plan content. After a
click it stays connected while that configuration retains focus. Imported
column/group names are rendered as text.
Processing and execution behavior are unchanged.

Graph layout acceptance: `node scripts/test-browser-graph-refinements.mjs`.

The editor size fields pair an amount with a unit selector. Byte-based limits
accept decimal (KB/MB/GB/TB) and binary (KiB/MiB/GiB/TiB) units; working memory
uses MiB or GiB and still resolves to whole MiB. Changing a unit re-expresses the
same exact value, including fractional amounts, without rounding byte limits or
changing the next Run configuration. Editing the amount still changes
the draft normally.
Defaults are automatic working memory, an 8 MiB record working limit, and blank
optional size caps. Imports/exports and engine requests retain the existing
numeric byte and memory_mb fields; display units are not Job schema fields.
