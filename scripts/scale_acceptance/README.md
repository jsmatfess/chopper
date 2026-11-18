# Release acceptance tooling

Implementation for [#102](../../docs/history/prior-issues.md#issue-102), following
the reviewed [release plan](../../docs/history/prior-issues.md#issue-109).
These are correctness tools, not new performance evidence. Existing small workload
harnesses and their 16 MiB guards remain unchanged. No file here is a product asset.

For the distinct #126 native generation/checkpoint → explicit Run approval →
independent verification controller, see [NATIVE.md](NATIVE.md). It preserves the
existing tiny/native planner below; its fake controls authorize no real workload.

Run tiny controls from the repository root:

```sh
python3 scripts/scale-acceptance.py plan scratch/scale-tooling-check
python3 scripts/scale-acceptance.py run scratch/scale-tooling-check/plan.json scratch/scale-tooling-check/batch scratch/scale-tooling-check/policy.json
```

`plan` prints the concrete command and writes a validation-runner manifest plus
its declared guard policy. The self-check has a 600-second batch deadline,
64 MiB owned-tree limit, explicit source/artifact/dependency declarations and
subprocess deadlines. Python and Node controls use synthetic data only; neither
launches a product, a browser or a build. Fixture generation stays below 3 MiB
combined (127 narrow rows, 137 wide rows and eight wide rows). The fake browser
transfer fixture is about 1 MiB. Every width stays below 2,000 rows. Logs and the
runner's intentionally failed child attempts are retained inside the owned tree.
The workflow tooling job runs both focused control suites on Linux and Windows.
No existing runner, scheduler or host reservation is modified.
Direct focused entry points are `python3 scripts/test-scale-acceptance.py` and
`node scripts/test-scale-acceptance-browser.mjs`.

## Generator and recipes

`prepare DIRECTORY --shape D|G --runtime native|browser --rows N` creates a fresh
owned directory with `input.csv`, `fixture.json`, `job.json` and `temp/`. It refuses
existing directories and files. Omit `--rows` **only for separately authorized
scale execution**: this selects exactly 10,000,000,000 native or 1,000,000,000
browser bytes. Planning and the self-check never generate those files.

Format `release-acceptance-v1` is uncompressed ASCII/UTF-8, comma, header, LF,
no BOM or CSV metacharacters in fields. D uses width 100; G uses width 1000.
Header: `id,region,` + `p` repeated W−11 times + LF. Record i: twelve-digit ID,
comma, `r` + i modulo eight, comma, repeated lowercase SHA-256 hex of
`release-acceptance-v1:` + decimal i, truncated to W−17 bytes, LF. Header and each
record have exactly W bytes; total is (N+1)W. D counts are 99,999,999 native and
9,999,999 browser; G counts are 9,999,999 native and 999,999 browser. Generation
streams bytes and SHA-256 and retains parameters and actual counts.

`fixture-identity RECEIPT --shape D|G --runtime native|browser [--rows N]`
hashes that same stream without writing a CSV. Run it as bounded cold preparation
before choosing concrete input pins; its receipt records zero generated input
bytes and makes no stored-input or acceptance claim. Actual generation, pre-Run
input admission and the independent verifier still check the complete file.
The browser Large packet validator requires the exact selected D/G stream digest.
Large G also requires positive completed spill and merge outcomes in the retained
public graph; missing, truncated, unavailable or failed physical facts cannot
establish that criterion. Bounded event/upstream-detail omissions are recorded
separately and do not erase valid completed metrics. These checks do not replace Tiny.

D has no operations. G is partition(region), exact assign(treatment=80,
control=20, no strata), uniform shuffle. Both use strict 10,000,000-byte /
1,000,000-row caps, uncompressed output, 64 MiB working-allocation budget,
one worker, 4096 files/record bytes, grouping auto, explicit v1 seed, seeded_v1,
blake3_counter_v1 and adaptive_v1. Native intermediate cap is 100 GiB; browser
intermediate cap is 8 GiB with null temp directory. These are not filesystem/RSS
limits. `recipe.validate` validates only these exact Job schemas; initial tiny
controls additionally exercise smaller row/byte caps. Full product Job decoding
is an unrun integration prerequisite, not established by Python validation.

## Independent verification and parity

```sh
python3 scripts/scale-acceptance.py verify PATH/job.json PATH/fixture.json RECEIPT.json --bitmap-dir OWNED_DIRECTORY
```

Use `--output` for a separately extracted directory, and `--peer RECEIPT.json`
for same-input seeded peer parity. Receipts are exclusive writes. The verifier
imports neither the generator constructor nor the recipe module. It independently
reconstructs every source/output field, hashes streaming bytes and parses bounded
manifest lines. Supported dialect is deliberately only the fixed-width formula,
not arbitrary quoted/multiline CSV. Existing adversarial CSV contracts retain
that coverage. The verifier checks unique in-range IDs using a disk-backed bitmap,
then exact bit coverage and row totals. A second disk-backed bitmap binds each
ID to its allocation; canonical membership and encountered-order digests stream
per arm. Each bitmap is at most 12,500,000 bytes for the selected jobs; temporary
bitmap files close and disappear on success or failure. This is bounded working
allocation, not an RSS claim about mmap/page cache.

Checks cover manifest version, pinned algorithm, resolved default fields, full
Job settings, parent/output totals, deterministic safe unique names, exact lineage,
strict serialized caps, greedy boundaries and unexpected/truncated artifacts.
D verifies global ID order. G verifies region membership, per-region largest-
remainder quotas, configured arm order and both named arms even for zero quotas.
Peer receipts compare source identity, recipe caps, names, bytes, chunks,
membership and within-arm order. They do not reconstruct independent random draws
or prove uniformity. Different native/browser large inputs cannot be peers.
For browser CSV recipes the verifier requires the worker's exact WASI paths
(`/input.csv`, `/results`, `/tmp`); all other submitted configuration must match.

Mutation controls cover changed/duplicate/missing IDs, payload/region/header,
D order, caps, manifest/config/totals/paths/truncation, extra outputs, incorrect
lineage/quotas, zero-quota arms, peer digests and completion markers. Existing
versioned randomization regressions remain the random-source oracle.

## Browser seam: production integration prepared, execution unrun

`browser-page.mjs` installs a harness-only adapter supplied with the actual
production `browserApi` and execution-history getter. `browser-bundle.mjs`
connects those existing seams in an external bundle of the
production app/client source. `browser-driver.mjs` serves the frozen production
HTML with that bundle substituted for `/app.js` and a hidden File input added;
production worker/WASM bytes stay unchanged. The shared client instance supplies
both the app and adapter. Keep the bundle outside `ui/dist`. This exercises the
production source through a harness bundle, not the byte-identical shipped
`app.js` or actual picker UI. Select the declared local File with
the browser automation file input, then call `scaleAcceptance.start(job)`. It
injects an explicitly OPFS-backed output picker, calls public `run-direct` without
Prepare, and restores picker overrides. `sample()` reports real origin quota,
public state/progress and bounded graph observations (including spill/merge when
actually observed). Record unavailable/omitted facts; input size alone never
proves spill. `cancel()` uses the public cleanup path.

The host's `browser-export.mjs` `extract(page, freshDirectory, progressCallback)`
uses that adapter's completed output handle. It transfers 512 KiB decoded slices
as at most 699,052 base64 bytes (under 1 MiB including JSON framing). It never
returns whole output files, rejects malformed/short/oversize transfers, safely
writes partial host files and verifies the complete marker schema/count. Run the
independent Python verifier afterward for manifest/CSV checks. No marker or an
invalid marker is incomplete. Partial output is retained on extraction failure.
The caller owns cancellation, browser stop/reap and failed-attempt retention.

**Not established here:** connection to a frozen final production page/client and
workers, actual public Run/export/marker behavior, installed Chrome/Edge, a real
persistent profile's capacity, actual File input or external picker/filesystem
usability. Node fake-transport/Blob controls establish bounded extraction mechanics
only. Before #104 scale execution, its owner must perform a tiny frozen-product
integration and supply its identities/receipt. The tiny manifest below now
supplies the bridge/driver and actual public quota/
progress sampler. It still requires parent-selected frozen assets, build receipts,
executables, reservation and storage. Scale uses the separate
[browser scale contract](#separate-browser-scale-contract-122) below.

## Tiny final-product integration handoff (#104)

Preparation only (npm/esbuild; no product/browser launch):

```sh
npm --prefix ui ci
node scripts/scale_acceptance/browser-bundle.mjs scratch/browser-bridge
```

Create `scratch/` first if absent; the bundle destination itself must be fresh.
The esbuild input hook records hashes of the exact source bytes consumed, checks
for compilation-time drift and writes `bridge.js` plus `bundle-provenance.json`.
This does not build WASM or edit `ui/dist`. Freeze it **after** the parent has
selected the final clean source, restored default test-free production assets
with the owning build commands and reconciled matching #91 build/toolchain
receipts. Any later source/toolchain change requires a new bundle and freeze.
No version/package/release packet is changed by these commands.

The browser packet is a separate JSON input, not the native `FrozenIdentity`
packet or a release claim. Supply these fields; placeholders are not accepted
identities and this example is deliberately not a launchable packet:

```json
{
  "version": 1,
  "runtime": "browser",
  "mode": "tiny",
  "features": [],
  "parent_scheduled": true,
  "source": {"clean": true, "commit": "<actual clean 40-character source HEAD>"},
  "host": {"os": "Windows", "build": "<actual OS build and named host>"},
  "storage": {"volume": "<actual owned scratch/profile/output volume and capacity inventory>"},
  "toolchains": {"build": "<selected Rust/WASI/Node/Python/esbuild/Playwright versions and matching receipt locators>"},
  "build_receipts": ["scratch/final-build-receipt.json"],
  "channel": "chrome",
  "browser_version": "<actual Playwright browser.version() value for selected executable>",
  "origin": "http://127.0.0.1:8427",
  "browser": {"path": "<absolute installed executable>", "sha256": "<actual hash>"},
  "node": {"path": "<absolute real Node executable>", "sha256": "<actual hash>"},
  "python": {"path": "<absolute real Python executable>", "sha256": "<actual hash>"},
  "reservation": {"path": "<absolute immutable parent reservation token>", "sha256": "<actual hash>"},
  "bundle": "scratch/browser-bridge/bridge.js",
  "bundle_provenance": "scratch/browser-bridge/bundle-provenance.json",
  "inputs": [
    "Cargo.toml", "Cargo.lock", "crates", "vendor", "ui/src",
    "ui/package.json", "ui/package-lock.json", "ui/dist",
    "scripts/*.py", "scripts/*.mjs",
    "scripts/scale_acceptance/*.py", "scripts/scale_acceptance/*.mjs",
    "ui/node_modules/playwright", "ui/node_modules/playwright-core",
    "ui/node_modules/esbuild", "ui/node_modules/@esbuild",
    "scratch/browser-bridge/bridge.js", "scratch/browser-bridge/bundle-provenance.json",
    "scratch/final-build-receipt.json"
  ],
  "input_sha256": {"<every matched file, repository-relative POSIX name>": "<approved SHA-256>"}
}
```

Add actual build configuration/receipt inputs required by the selected build.
Use the existing validation runner's `identity(root, inputs)` (available through
`scale_acceptance.guard.load_runner()`) to inventory files, reject
`incomplete_identity`, and map each non-directory entry's `sha256` using POSIX
names. Record/approve that map before execution; do not replace it on a mismatch.
The bundle provenance source hashes must match it. Declare individual bundle and
receipt files, never all of `scratch/` or the mutable attempt directory. Pin the
selected browser executable, real Node/Python binaries and parent reservation by
hash, with no symlink ancestry. Hashing a receipt does not certify its assertions:
parent review must tie assets to the exact source, default features and build.
No native packet assertion is used to certify browser assets. Freeze the packet
under repository `scratch/`, outside the attempt root. Keep its bytes immutable.

Parent-only integration, after explicit scheduling and acceptance of the frozen
identities/capacity (run with that exact frozen Python):

```sh
python scripts/scale-acceptance.py browser-plan scratch/tiny-chrome --frozen scratch/browser-chrome-frozen.json --rows 127
python scripts/scale-acceptance.py run scratch/tiny-chrome/plan.json scratch/tiny-chrome/batch scratch/tiny-chrome/policy.json
```

For Edge prepare a distinct `msedge` packet, origin and fresh attempt root. The
existing browser channel selector is reused, with `executablePath` pinned to the
packet's actual binary. This driver launches only on actual Windows: its hard-stop ownership relies on
the existing runner kill-on-close Job. Playwright detaches POSIX browser processes
from the runner group, so POSIX launch is refused rather than claiming tree
cleanup there. Source compilation/controls can run on Linux. Windows
`bundled-chromium` is separately labelled and never fills either installed cell.
The running browser version must exactly match the packet. No existing profile
or public deployment is opened. The driver owns a loopback server at the exact
frozen origin and a fresh persistent `work/profile`, OPFS export parents, host
`work/D` and `work/G` extraction directories. Only enumerated assets are served;
path traversal URLs and off-origin browser requests are denied. The production
HTML's `/app.js` is substituted only in memory; all production assets remain
frozen, and resource-test assets/exports are rejected before launch. This is not
served-hash acceptance for the published application bundle.

`browser-plan` defaults to 127 rows per width and refuses more than 2,000, wrong
types or combined fixtures at/above 3 MiB. Its five sequential steps generate D,
generate G, run both tiny public jobs in one owned persistent profile, then
independently verify D and G. It cannot create a 1 GB plan. Both jobs retain the
selected browser recipe and public Run semantics (no Analyze/Prepare); local
Files come from automation's file input, picker handles are explicitly injected,
and destinations are same-origin OPFS. Real dialogs/external filesystems remain
#105. The existing whole-file/16 MiB limits in other harnesses are unchanged;
this tiny driver's extraction adds a 16 MiB aggregate ceiling per shape, while
keeping the scale helper's 512 KiB slices and <1 MiB encoded transfers.

The batch is at most 600 seconds/64 MiB for the entire owned tree, including
profile, fixtures, exports, logs and bitmaps. Generation/verifiers each get 30
seconds; the browser step gets 480 seconds. Physical space must start at 128 MiB
and stay at least 64 MiB free. Public usable origin quota (the production 80%
reserve calculation) must remain at least 128 MiB; samples must be current within
10 seconds. These are tiny tooling thresholds, never the scale capacity rules.
A fresh installed browser profile can itself exceed the tooling ceiling; retain
that denial and obtain a separately reviewed plan, never silently raise limits.

The Python guard inventories immutable names/metadata before every runner launch
and during waits, including packet, source, assets, dependency packages, selected
executables and reservation; initial approved byte hashes and actual source HEAD
must match. Capacity is sampled every second. Node samples real public
state/progress/quota every second, retaining a bounded latest graph plus final
per-shape snapshots. Only changed public status/phase/rows/temp counters or export
checkpoints count as progress; identical samples and timestamps do not. Stop
within 60 seconds without progress, on quota denial, drift, disconnect, error,
deadline, verifier mismatch or cleanup failure. Sampled bounds can miss transient
peaks; they are not RSS/physical-I/O measurement. Unavailable/omitted graph/spill
facts remain explicit; tiny inputs need not spill.

Normal failure/success attempts public cancellation (20-second cleanup deadline)
and closes the owned persistent context (20 seconds), then closes the owned
server. Cleanup errors fail the step. On guard denial or a hung driver the
existing runner stops/reaps its process tree/group; Windows wrapper containment
uses the existing kill-on-close Job. An abrupt guard stop cannot promise a public
cancel acknowledgement. Profiles, incomplete outputs, samples, runner stdout/
stderr/status and `guard-failure.json` remain; no retries, resumption, profile
reuse or failure deletion is automated. Node refuses accidental standalone launch
without the live parent runner lock. Browser receipts say `extracted` until the
separate Python verifiers pass; neither is a scale/full-contract receipt.

**Execution remains UNRUN in this preparation.** Parent still owes frozen
production tiny Run/export/valid-marker/independent-verifier evidence in the
selected installed channels, followed by the separately planned owning contract
sequence and any authorized scale work. Source-only negative controls exercise
real temporary file identities, plan/guard denial, synthetic transport,
quota/progress/deadline and cancellation/close error handling. They do not mock a
production integration pass. #104 and #87 remain open.

## Guarded manifests and execution handoff

Policy declarations compare native paths, accepting the browser planner's POSIX
separators and the native planner's platform separators on Windows. A policy
missing from any step's declared inputs is still denied before launch.

`plan DIRECTORY --shape D|G --frozen PACKET.json` creates **one native shape's**
concrete generate → public CLI Run → independent verify manifest, without running
it. D precedes G; a parent reviews D's result and storage retirement before creating
G's attempt. Never generate both large shapes implicitly. Each step declares exact
arguments, relevant input globs, required artifacts and dependencies through the
existing `validation-runner.py`. Executable, environment, input/artifact hashes,
input drift and full logs use that runner's provenance and process-tree cleanup.

The frozen packet must supply `runtime: "native"`, `features: []`,
`parent_scheduled: true`, `source: {clean: true, commit: <40 hex characters>, ...}`,
nonempty `package`, `host`, `storage` and `toolchains` objects; workspace-relative
`inputs` covering complete build/source/vendor/embedded assets and build receipts;
`input_sha256` mapping every matched file's repository-relative POSIX name to its
approved SHA-256 (omit directory entries, reject missing/extra files);
absolute `executable` and its `executable_sha256`; and `reservation: {path,
sha256}` for the parent's immutable reservation token. `storage.volumes` lists
existing paths on **every** involved volume. Source/package/host/toolchain details
are supplied by #91/#103; placeholders are not completed identities. Parent
review of that packet remains required. The plan validates selected source,
executable and reservation hashes and pins the packet's own hash in the policy.
Execution revalidates those approved byte hashes before any step. Immutable file
names and metadata are checked again before each launch and while waiting,
independently of capacity-sampling intervals; this catches replacement, additions,
deletion and writes without repeatedly hashing every source body. Changed source,
package or packet state is a denial, even when a touched file retains its bytes.
Frozen inputs must not contain symlinks. The packet's commit/build assertions
still require parent verification; the guard does not certify a build from hashes.
The packet declares provenance; it does not grant permission or certify its claims.
Keep the native executable and declared input paths under the repository root;
external selected tools are separately hashed by the runner.

`run` is a fresh-attempt wrapper around the existing runner's guard callback.
It binds the policy as an input, samples at most every five seconds, and rejects
symlinks/overlapping roots, owned-tree ceiling, low physical capacity, changed host
reservation, missing/stale browser-quota observations, no progress and deadlines.
The native policy sets 160 GiB owned, 200 GiB starting free on every volume,
20 GiB stopping free, eight-hour batch and one-hour generation/two-hour Run/
one-hour verifier ceilings. Progress uses generation/verifier row checkpoints,
CLI progress logs and the output manifest; guard samples do not count themselves
as progress. Samples can miss transient peaks; they are not physical I/O or RSS
measurements. Temporary children retired during a capacity census are skipped;
missing owned roots, unreadable entries and nonregular/symlink entries still deny
the attempt. Frozen-source removal remains a strict drift failure, independently
of this mutable temporary-file census. A denial stops/reaps the owned command through the existing runner,
retains attempts/logs and writes `guard-failure.json` for wrapper failures.
No automatic retry or resumption is exposed by the wrapper. Diagnose failures and
obtain a revised plan before another fresh attempt. Windows uses the existing
kill-on-close Job containment, but its platform behavior was not tested here.

Plan destinations are resolved below the real repository `scratch/` root before
creation. Parent traversal and existing symlink ancestry are rejected; a lexical
`scratch/../other` prefix is not an ownership boundary.

Browser guards can additionally consume a `browser_quota` policy object with
`path`, `start_bytes` and `stop_bytes`. The actual browser sampler must atomically
write `sampled_unix` and `usable_bytes` at least every five seconds (usable means
after the production engine's conservative reserve). Stale observations fail
closed. For selected browser scale, require 16 GiB starting/2 GiB stopping usable
quota, 40 GiB starting/8 GiB stopping physical free, 24 GiB owned and six hours.
This configuration is guidance for the integration owner, not a browser receipt.

Real local CI, native Windows validation, main delivery and #102 closure belong
to the parent. These focused self-checks establish tooling preparation only.

## Separate browser scale contract (#122)

`browser-scale-plan` and `browser-scale-run` are distinct from `browser-plan`,
`BrowserIdentity`, `browser-driver.mjs` and their tiny guards. Those retain their
2,000-row, 16 MiB export and 600-second/64 MiB limits. This tooling is preparation,
not approval: no browser/product Run or scale acceptance was performed here.
Only the parent can approve actual execution after reviewing a concrete plan,
capacity, final-product tiny integration and the owning installed-browser checks.

The selected product is source
`639d1fe97d985b1544df0932321c6a93cca2567b`, tree
`b3bde79d552ee29760cb283d07938f9248cee0bb`, as pinned in the
[candidate manifest](../../docs/releases/0.2.0-candidate.json). Its checkout,
assets, packages and receipts are read-only inputs, separate from this harness
checkout. The [review packet](../../docs/releases/0.2.0-review.md) and
[focused evidence](../../docs/releases/0.2.0-focused639-evidence.json) bind the
original feb9 runtime builds and three-path packaging/docs reconciliation; those
builds remain attributed to feb9. Frozen606 packets now fail the selected-source
check; their attempts, deadlines and charges remain immutable history. This pin
change starts no campaign, renews no clock and grants no execution approval.
Parent must supply reviewed selected639 build/package evidence, installed-channel
contracts and tiny integration before scale execution. Copying a custody path
does not establish a matching Windows identity.

A version-1 scale packet is a JSON object with the following required schema
(see `browser_scale_identity.py` for validation). No null identities, placeholders,
empty required identity objects or inferred acceptance are supported:

| Fields | Required content |
| --- | --- |
| `runtime`, `mode`, `features`, `parent_scheduled` | `"browser"`, `"scale"`, `[]`, `true` |
| `source` | `commit`, `tree` above and `clean: true`; actual product Git HEAD/tree and tracked cleanliness are checked |
| `harness_source` | Separate clean harness `commit`, `tree`, `clean: true`; actual harness HEAD/tree/cleanliness checked |
| `shape`, `channel`, `plan_id` | Exactly one `D` or `G`, installed `chrome` or `msedge`, unique simple plan ID |
| `host` | `os: "Windows"`, actual Python `platform.release()`, `platform.version()`, `platform.machine()`, `platform.node()` as `release`, `version`, `machine`, `node`; actual Node `os.release()`/`os.version()` as `node_os_release`, `node_os_version` |
| `browser_version`, `origin`, `profile` | Actual `browser.version()`, explicit `http://127.0.0.1:PORT`, exact fresh `ATTEMPT/work/profile` path |
| `product`, `harness`, `assets`, `evidence` | Each has absolute `root`, explicit relative `inputs` globs, and complete `sha256` map (every matched regular file, POSIX relative names, no extra/missing files) |
| `product.inputs` | At least Cargo manifests/lock, complete `crates`, `vendor`, `scripts`, `ui/src`, `ui/public`, `ui/index.html`, `ui/style.css`, UI package/lock; add all selected build inputs |
| `harness.inputs` | `scripts/scale-acceptance.py`, `scripts/validation-runner.py`, `scripts/browser-artifacts.mjs`, complete `scripts/scale_acceptance`, `ui/node_modules/playwright`, `playwright-core`, `esbuild`, `@esbuild`; add bridge/provenance and any additional dependencies |
| `assets.inputs` | `["*"]`, inventorying the entire directory; its map must contain exactly `engine.wasm`, `engine-worker.js`, `storage-worker.js`, `app.js`, `index.html`, `style.css`, `_headers` |
| `package`, `build_receipts` | Package `{path, sha256}` and nonempty array of receipt paths, all bound into `evidence.sha256`; parent checks assertions against product/default build and all seven assets |
| `toolchains`, `storage` | Actual `python_version` (`sys.version`), `node_version` (`process.version`), `playwright_version`, `esbuild_version`, matching receipt identities and named volume/capacity inventory for profile/data/extraction and parent claim records |
| `browser`, `node`, `python`, `reservation` | Each `{path, sha256}` uses a real absolute file, no symlink ancestry; actual binary bytes and subsequent metadata drift checked |
| `bundle`, `bundle_provenance` | Harness-relative external bridge files, explicitly in `harness.inputs`/map |
| `fixture` | `{width, rows, bytes, sha256}`: D = `100`, `9999999`, `1000000000`; G = `1000`, `999999`, `1000000000`; parent-approved expected actual input digest |
| optional `peer` | `{path, sha256}` of an immutable independent verifier receipt for the **same input bytes/count/shape**; absent means seeded peer coverage remains unmet |

Use `guard.load_runner().identity(root, inputs)` to construct each complete map,
reject `incomplete_identity`, and omit directory entries. Use real absolute binary
paths (no executable aliases). Hashes prove identity, not build correctness or
permission. Frozen groups, packet, tools, receipts, approval and reservation are
checked before launches and throughout runner waits. Fixture bytes/hash/count and
the exact Job are revalidated and pinned before the browser step; the driver
independently streams the actual local input before public Run. Never freeze a
mutable attempt directory as an input. Use Python `-B` throughout preparation and
execution so bytecode cache writes do not mutate the frozen harness directory.

If a bridge for these separate roots is needed, preparation only is:

```sh
node scripts/scale_acceptance/browser-scale-bundle.mjs /absolute/frozen/product/source scratch/scale-bridge
```

The parent supplies installed esbuild dependencies. This reads the selected
product app/client without changing them. Its provenance splits exact consumed
hashes into `inputs.product` and `inputs.harness`; both are reconciled against the
packet. It retains the existing `browserApi`/`executionHistory` and page adapter
seams. Only the in-memory page script is substituted. This is injected File/OPFS
integration, not real picker/external filesystem or published `app.js` served-hash
acceptance. It does not use or require unmerged #121 tooling.

The immutable parent reservation file has this structure. Values below describe
types, not a usable approval:

```text
version: 1
parent_scheduled: true
campaign: named campaign
claims_root: absolute existing parent-owned directory shared by all four slots
slots: array of 1..4 {plan_id, shape, channel, directory: absolute attempt path}
channels: {chrome and/or msedge: {start_unix, deadline_unix}}
```

Each shape/channel pair and plan ID is unique. Each channel window is at most
21,600 seconds and must already be active at execution. The claim root is outside
attempts. The parent must use the same campaign/claim root for this selected
four-Run campaign, with no omitted earlier attempts. One exclusive `active.lock`
prevents overlap; a permanent `PLAN_ID.consumed` records even a failed attempt.
**The active lock is retained after success, failure or crash.** Before scheduling
the next shape, the parent must confirm the controller has exited, its Windows
kill-on-close Job has terminated owned descendants, reconcile retained storage,
and explicitly retire the lock. Never remove consumed slots, retry, resume,
substitute another reservation or create another campaign to evade the ceiling.
Extant attempts for the selected channel are included together in its 24 GiB
capacity census; completed-data retirement is an explicit parent decision.

Prepare one plan with the selected frozen Python (no execution):

```sh
python -B scripts/scale-acceptance.py browser-scale-plan scratch/scale-D-chrome --frozen scratch/scale-D-chrome-frozen.json
```

The parent reviews `plan.json`, `policy.json`, their hashes, the frozen packet,
reservation and capacity. Only afterward it creates a separate immutable approval
JSON with these exact fields: `version: 1`, `decision: "approved"`,
`contract: "browser-scale-v1"`, selected `plan_id`, `shape`, `channel`,
`plan_sha256`, `policy_sha256`, `packet_sha256`, `reservation_sha256`, and concrete
`approved_by` plus `approval_reference`. There is no command to mint approval;
this record binds a parent decision and is not an authorization mechanism.
Execution, **only when the parent separately authorizes the actual costly run**:

```sh
python -B scripts/scale-acceptance.py browser-scale-run scratch/scale-D-chrome/plan.json scratch/scale-D-chrome/policy.json --approval scratch/scale-D-chrome-approved.json
```

The generic `run` refuses this contract. Full execution refuses non-Windows and
bundled Chromium; synthetic/unit controls on Linux do not establish acceptance.
The Windows runner enters its existing kill-on-close Job before child launch;
the driver requires the live runner lock and approval-bound authority. A fresh
batch/profile is mandatory. All files and failures remain after a denial.

The three sequential steps are generation ≤30 minutes, exactly one public Run
and extraction ≤90 minutes, independent verification ≤30 minutes. The per-channel
parent deadline is ≤6 hours, shared across its D and G attempts; no expansion,
retry, resume, fallback browser, implicit next shape or matrix is exposed. Jobs
keep default features, 64 MiB, one worker, 8 GiB intermediate, strict **10,000,000
serialized CSV bytes** per chunk and the existing versioned seeded D/G pipeline.
Capacity starts at ≥40 GiB physical free and ≥16 GiB usable origin quota after
the production 80% reserve, stops below 8 GiB/2 GiB, and caps channel-owned data
at 24 GiB. An independent watchdog samples physical/source/reservation state every second, including while the runner hashes inputs or artifacts, and fails/stops the contained controller tree if no sample completes within five seconds; the browser sampler runs every
second with one bounded watcher call and a four-second timeout. Run-progress
polling can overlap that watcher with one additional bounded sample. Quota older
than ten seconds (or future-dated beyond ten seconds) fails. The initial quota
gates Run; after the owned browser step closes, host verification continues
physical/identity/progress guards without requiring a live origin sample.
No changed useful checkpoint for 600 seconds, source/binary/recipe drift,
reservation conflict, quota denial, timeout or disconnect fails the attempt.
These sampled bounds do not measure RSS or physical I/O and can miss transients.

Extraction reuses `browser-export.mjs`: at most 512 KiB raw per slice and strictly
less than 1 MiB encoded response, streamed exclusive host writes and a bounded
inventory. It never accumulates output files. Malformed/short/extra slices and
invalid markers fail with partial files retained. Independent `verify.py` streams
source and outputs, uses disk-backed ID bitmaps, checks conservation, exact named
quotas, order, manifest, serialized caps and complete-marker schema/count. Optional
peer comparison includes source digest/count; a native 10 GB receipt cannot serve
as a browser 1 GB peer. Conservation alone does not prove G seeded membership or
shuffle draws. Actual public graph snapshots are retained; absent/omitted spill
facts are explicitly unmet coverage. The driver reports extraction, never a
verification/scale acceptance pass. Cancellation after committed completion keeps
the product’s existing semantics.

Cleanup independently attempts sampler stop, public cancellation, context close,
browser close and server close, with bounded deadlines and every failure retained
beside the primary error. The runner stops/reaps hung or denied owned commands;
controller exit closes the Windows Job for remaining descendants. A hard guard
kill can prevent final browser-side cleanup/receipt; runner logs, capacity samples,
status, partial files, `watchdog-failure.json` and `guard-failure.json` retain that failure. No cleanup
failure or unstarted/blocked command is acceptance.

Focused checks only (no browsers/builds, fixtures ≤2,000 rows):

```sh
python -B scripts/test-scale-acceptance-browser-scale.py
node scripts/test-scale-acceptance-browser-scale.mjs scratch/fresh-scale-fake-controls
python -B scripts/test-scale-acceptance.py --work-root scratch --receipt scratch/fresh-tiny-python.json
node scripts/test-scale-acceptance-browser.mjs scratch/fresh-tiny-node.json scratch
```

Keep raw stdout/stderr, including failed controls. The new Node controls always
retain their synthetic partial outputs and cleanup error list. Remaining parent
gaps: selected frozen-product tiny integration; real installed Chrome/Edge Windows
containment/quota/lifecycle validation; concrete final identities, capacity,
reservation and per-shape approval; all actual D/G scale Runs and seeded peer
results. This implementation supplies no Windows, spill, dialog or scale claim.

Native PR131 review controls and the parent-owned tooling workflow step are
recorded in [NATIVE.md](NATIVE.md#pr131-source-review-controls-and-parent-wiring-handoff).


The maintained hosted preparation path also generates `mode: "scale"`,
`shape: "D" | "G"` packets. These require a complete matching Tiny frozen batch
for that installed channel, the exact 1 GB fixture recipe, and a hash-pinned
`large_reservation` covering all four Chrome/Edge × D/G cells. Its external
claims root and canonical reservation must belong to the reconciled storage
union and remain disjoint from each cell's source and metadata. Each cell copies
only the immutable reservation bytes; all cells consume the same irreversible
claim files. Preparation and launch reuse the owning schedule predicate.

Cold materialization and common preflight precede actual guarded execution.
Large after-exit verification retains the ordinary independent process/Original
proof, checks the 1 GB input and exact independent oracle, matches installed
browser identity/public completion, and requires positive completed G spill and
merge facts. Bounded omitted event/upstream details are recorded; unavailable,
truncated, incomplete or contradictory completed facts deny acceptance. Cross-
channel parity remains pending until the same-shape peer oracle matches. These
source controls do not grant an actual Tiny or scale pass.

The initial qualified Tiny may create that campaign through optional declarative
`large_cells`; its existing materializer owns the reservation/claims directory.
Each Large packet pins the creator's `campaign_qualification` and exact original
`large_reservation`, separately from its own channel qualification. The complete
proof closure stays in continuous identity checks. After independent quiescence
and reconciled storage, after-exit retires the exact ended controller's active
campaign lock; permanent consumed claims remain on success and failure.
