# First workload baseline slice

This implements the first two jobs from the [investigation handoff](workload-investigation.md)
using current engine contracts. It adds tooling, not a strategy selector or engine
behavior change. Future defaults, relaxed randomized ordering, field sorting and
intermediate batching remain separate implementation work.

## Generator and recipes

[workload_entities.py](../scripts/workload_entities.py) defines `entity-list-v1`.
SHA-256 draws are addressed by version, seed, original row index and field label;
increasing row count preserves earlier rows. It streams UTF-8 comma/LF CSV with
headers, unique ordinal IDs, region/locality/segment categories, synthetic names,
addresses and variable-width notes. Notes include quoted multiline values;
addresses include quotes, commas and empty fields; names exercise Unicode.
All records are simulated and contain no source voter/customer records.

The [baseline driver](../scripts/workload-baselines.py) prepares complete Job JSON:

- `ordered.json`: preserve order and enforce a strict serialized-byte cap.
- `campaign.json`: partition `region`, independently allocate treatment/control
  with 80/20 probabilities, then uniform shuffle inside each resulting group.

Both explicitly select current `seeded_v1`/counter/adaptive versions, one worker,
64 MiB job memory, 256 MiB temporary budget, 4,096 files and 512 KiB maximum record.
The future opt-in-only reproducibility default is not enabled by these recipes.
`prepare` defaults to a 10,000,000-byte cap; the small generated control plans use
4,096 bytes deliberately to exercise many encoded chunk boundaries.

For a standalone fixture and recipes:

```powershell
python scripts/workload-baselines.py prepare scratch/entities-001 --rows 2000 --byte-cap 4096
```

Parameters include seed, rows, regions, hot-region percentage and minimum/maximum
notes bytes. Notes width and region draws are independent. The generator's row
addressing and metadata/version pinning are stable; modulo-based shape sampling
is not an algorithmic uniform-shuffle claim. This initial slice deliberately
does not create reserved correlated-width/late-key performance holdouts.

The preparation/verifier slice is limited to conservative 16 MiB fixtures and
262,144-byte notes. It is not a full-scale generator/verifier acceptance claim.
`dataset.json` pins source bytes, generator source/version, parameters and dialect.
Refuse overwrite: use a fresh owned directory for new experiments or failed
attempt retries. Completed matching steps can resume through the coded runner.

## Concrete build and run plans

Prerequisites: native Rust/C++ build tools, Node/UI dependencies and WASI SDK 33,
as routed by the [browser guide](browser.md). Install UI dependencies with
`npm.cmd --prefix ui ci` on Windows. The compiled native artifact must be inside
the checkout so the runner can pin it. Choose an installed browser channel or
install the supported bundled Chromium before execution.

```powershell
python scripts/workload-baselines.py plan scratch/baseline-001
python scripts/validation-runner.py scratch/baseline-001/native-build-plan.json scratch/baseline-001/native-build
python scripts/validation-runner.py scratch/baseline-001/browser-build-plan.json scratch/baseline-001/browser-build
python scripts/experiment-cycle.py run scratch/baseline-001/native-plan.json scratch/baseline-001/native-batch
$env:CHOPPER_BROWSER_CHANNEL = 'chrome'
python scripts/experiment-cycle.py run scratch/baseline-001/browser-plan.json scratch/baseline-001/browser-batch
Remove-Item Env:CHOPPER_BROWSER_CHANNEL
```

These are sequential foreground commands. Stop after a nonzero command; do not
launch a dependent run against an incomplete build. Build records include source,
vendor, toolchain and artifact identities. Supplied `--native-build-status` and
`--browser-build-status` paths can reference existing completed validation batches
instead of generating build plans. Runtime drivers check engine/hosted asset
hashes against the completed build records and retain their provenance pointers.

Each run plan has its own byte-identical generated fixture and independent output
locations, then measures/verifies both jobs. Defaults: 2,000 rows, eight possible
regions, 30% hot-region branch probability, and notes from 24 to 128 bytes. Small
fixture upper estimate is 768,000 bytes. Native/browser estimates are respectively
60/120 seconds and 64/256 MiB experiment-owned storage, with a ten-minute batch
deadline, 150-second per-Run deadline and 30-second verification deadline. Build
plans separately estimate three minutes and 2 GiB with a ten-minute deadline.
Recheck practical capacity and prerequisites rather than treating estimates as
measured bounds; a cold build or browser profile can exceed an estimate.

Raw output, failure records, build manifests, compact decision packets and native
stdout/stderr remain in the declared scratch tree. Do not edit active inputs.
Store selected evidence under the [archive policy](evidence-storage.md) before
cleanup; no archive upload is performed by these commands. No private credentials
or raw run artifacts are committed by this slice.

## Timing and browser scope

Native timing spans CLI process launch through successful Run/publication,
including analysis JSON emission; preflight hashing/builds/verification are
outside this timer. Browser timing spans `run-direct` through completed export,
including the client worker lifecycle and completion acknowledgement. It never
explicitly calls Prepare. Fixture selection, initial setup, host extraction and
verification are excluded and identified separately.

[run-workload-browser.mjs](../scripts/run-workload-browser.mjs) serves an allowlist
from existing default production assets and bundles its test entry in memory;
it does not modify `ui/dist`. It uses a fresh task-owned persistent profile,
Playwright-selected local File and an OPFS-backed output picker. It retains
browser/asset/build identities and checks the exported completion marker through
the independent verifier. This is real WASI processing and OPFS export, not a
measurement of native File System Access destinations or broader storage scale.
Profiles and failed exports remain task-owned artifacts for later cleanup.

## Independent checks and parity

The Python CSV-aware verifier reads source records independently of the engine's
digest. It verifies exact IDs/field values, conservation, manifest counts and
sizes, partition lineage/region membership, both named allocation arms including
empty arms, and actual serialized caps. Ordered output additionally checks source
order and independently calculated greedy chunk boundaries, including Chopper's
empty-field quoting. It rejects unsupported recipes/dialects rather than silently
applying these checks to arbitrary pipelines.

This small verifier retains source rows in memory. It does not independently
reconstruct seeded allocation draws or prove a shuffle/assignment probability
law; population counts are reported without enforcing exact 80/20 quotas.
Cross-runtime parity is a separate same-version seeded regression check:

```powershell
python scripts/workload-baselines.py parity scratch/baseline-001/native-data/ordered.json scratch/baseline-001/browser-data/ordered.json scratch/baseline-001/browser-data/ordered-browser-output --record scratch/baseline-001/ordered-parity.json
python scripts/workload-baselines.py parity scratch/baseline-001/native-data/campaign.json scratch/baseline-001/browser-data/campaign.json scratch/baseline-001/browser-data/campaign-browser-output --record scratch/baseline-001/campaign-parity.json
python scripts/test-workload-baselines.py
```

Parity compares identical source/semantic recipes, algorithm version, ordered
output lineage and CSV bytes after independent verification. Runtime container
manifests are expected to differ. Neither parity nor a single timing observation
establishes comparative speed, general randomness quality or full-scale behavior.
