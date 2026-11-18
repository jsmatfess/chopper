> Historical handoff, retained for context. Statements about defaults, open work,
> publication and the working tree below describe their dated snapshots. For
> current routing, use [current state](../current-state.md); GitHub Issues owns
> the active backlog.

# Chopper: current state and recommended next steps

The portable Progress source now uses allocation-free literal phases and admitted
shared dynamic text, retaining ownership through callbacks, cached state and the
last clone. The native cached output/status/error slices are also implemented,
including the approved bounded error fallback on admission denial. The
`scratch/progress-implementation-2026-10-28/final-report.json` checkpoint records
default/all-feature native and full bundled-Chromium/WASI acceptance, with the
default test-free hosted package restored. These checks do not add other-platform,
device, framing or complete-RSS coverage. Graphify's subsequent capture without
PowerShell stderr merging returned exit zero; logs are under
`scratch/repository-hygiene-2026-10-28/`.

The [shared exact-plan seam](../validation.md#shared-exact-plan-retained-parent-seam-2026-10-28)
now covers retained-parent preparation/retry for exact shuffle/partition and
streaming-chain execution, with Windows native and bundled-Chromium/WASI checks
and a restored default hosted package. The native server's cached output path
also retains its admission grant through state replacement; its separate native
validation is recorded in [validation.md](../validation.md). These are bounded
implementation changes, not a calibrated strategy selector or default promotion.
Other state sources and broader allocation coverage remain open in TODO.

The [bounded native E5 memory panel](../performance.md#e5-bounded-native-automatic-memory-panel-2026-10-28)
is complete. Automatic memory remains opt-in: the panel found no consistent
elapsed-time benefit and a low-headroom regression, with exact output/cap/cleanup
checks passing. Broader Auto strategy/worker/browser calibration remains pending.

Local implementation update: opt-in reproducibility controls and automatic memory
selection are delivered in the shared checkout. Omitted memory remains numeric
256 MiB; seeded execution remains the default. See the owning [seed](../specification.md#shuffling-and-seeds)
and [resource](../specification.md#resources-publication-and-interfaces) contracts.
The [frozen acceptance batch](../validation.md#reproducibility-and-opt-in-automatic-memory-2026-10-28)
passes Windows native/default/all-feature and bundled-Chromium hosted checks,
with the default test-free package restored locally. No deployment occurred.
The [bounded E4 study](../performance.md#e4-explicit-probabilistic-allocation-advice-2026-10-28)
is complete: retain explicit probabilistic allocation and withhold general speed
advice or automatic substitution. E5 and default promotions remain pending in
[TODO](../../TODO.md).

Update 2026-10-27: the [frozen accumulated-change checkpoint](../validation.md#accumulated-change-validation-checkpoint-2026-10-27)
is complete. The [direct-Run slice](../validation.md#limits-only-direct-run-2026-10-27)
now has Windows/native and bundled-Chromium acceptance, with a restored local
production package. Broader Auto policy/default promotion remains later TODO work.
No new build has been published. The dated details below describe
earlier snapshots, not the current implementation's full validation status.

Update 2026-10-24: the first implementation slice removes buffer shuffle from
the local native and hosted builds. See [removal validation](../validation.md#buffer-shuffle-removal-2026-10-24).
Auto defaults and mandatory preparation are unchanged; no new build has been
published. The older platform/package details below describe the prior snapshot.

Snapshot: 2026-10-23. This is a human-facing handoff, not another backlog.
[TODO.md](../../TODO.md) remains the only active checklist; detailed evidence lives
in [validation](../validation.md) and [performance](../performance.md).

## Where the project stands

Chopper has a native Rust CLI/local server and a separate hosted WASI engine.
Recent work has concentrated on making memory reservations follow the actual
owners of data, including prepared configurations, analysis results, request and
response buffers, codecs and picker output. Reservations account for admitted
working allocations. They do **not** establish a cap on total process memory
(RSS), operating-system allocations or every runtime allocation.

The current item completes parent-side native picker capture: stdout/stderr
buffers, decoded selection JSON and retained error bytes carry reservations.
Admission failure and server shutdown stop and reap the directly owned helper.
Cancellation remains effective after both pipes close. An incomplete HTTP request
cannot hold server shutdown waiting for a picker that never started. The
[evidence and remaining limits](../performance.md#native-picker-parent-pipe-admission-and-shutdown-2026-10-23)
include the development failures and final regression coverage.

The local build has Windows and Linux/WSL validation. Desktop browser evidence
covers bundled Chromium and installed Chrome and Edge on Windows. WSL uses the
same physical computer; it is not evidence from another storage device.
The preceding hosted engine
has production-browser, worker cleanup/interruption and desktop browser evidence;
the native picker change leaves those hosted assets unchanged. Tests use controlled
helper processes and supplied browser file/storage handles. They do not establish
that actual system dialogs, every external destination or real device faults work.
macOS validation remains deferred at your request.

For the picker snapshot, default/combined test totals are 296/350 on Windows
and 299/353 on Linux, each including nine doc tests. Formatting, linting,
focused picker regressions, Windows UI tests/build and native server behavior
comparisons pass. The final Linux server control also verifies shutdown while a
picker request body is incomplete. Exact commands and source hashes are linked
from the evidence above; repeated runs are not additive coverage.

## Local build versus public site

The public site is [chopper-1rx.pages.dev](https://chopper-1rx.pages.dev/).
The last recorded publication was the explicitly approved **2026-10-22** build;
its [deployment acceptance](../performance.md#validated-current-build-published-to-pages-2026-10-22)
records the served asset hashes and small-fixture checks. Later local changes have
not been published. This handoff does not claim a fresh check of the live site.

The latest local hosted package belongs to the
[Column deserialization pass](../performance.md#column-scalar-deserialization-without-successful-trial-errors-2026-10-23).
It differs from the recorded public deployment. The native picker item changes
only the native server. A successful local test is not evidence that the public
site contains that source snapshot. See the
[package identities](../evidence-originals.md#sha256-83788148ac6f8b2f8438a26ad64db0671f693f7d1bcbca552f13a8f355fd56b4 "Original: docs/benchmarks/picker-capture-final-package-identities-2026-10-23.json")
for exact native and unchanged local hosted asset hashes.

There is substantial accumulated uncommitted work, including source changes,
generated output, vendor sources and evidence. Preserve it. Review and package
that work before a release; do not clean the checkout by discarding unknown files.
Raw failed/interrupted validation records are intentional evidence.

## Recommended order of work

The owner has since agreed the [auto-mode and maintainability program](../auto-mode-and-maintainability.md).
Start with its evidence/strategy inventory and incremental repository cleanup;
[TODO.md](../../TODO.md) owns the current sequence. The release/ownership guidance
below remains context, not a competing instruction to finish every historical
engineering program before beginning the agreed work. No new engine behavior
or release is delivered by this planning update.

1. **Choose the next release's scope.** Decide which platforms, browsers, file
   destinations and workload sizes the release will actually claim. The five
   open TODO categories cover calibration, experimental policy implementation,
   remaining allocation ownership, candidate acceptance and release coverage.
   They are broad engineering programs, not five small remaining fixes.
2. **Finish ownership where it affects that scope.** Prioritize native server
   state/progress/error sources, command/path and helper-process/WSL construction,
   and thread/runtime overhead. Actual dialogs and descendant/broker cleanup
   remain distinct from the direct-helper controls just completed. Keep explicit
   runtime headroom; do not advertise a complete memory cap.
3. **Run targeted release acceptance.** Exercise real dialogs, external file
   destinations and interruption/recovery on the selected devices. Retain exact
   build and asset identities. Add larger or differently shaped jobs only when
   needed to substantiate the chosen claims; the historical billion-row result
   applies to one older copied build and one narrow fixture.
4. **Calibrate only a named performance decision.** Use matched complete jobs on
   the target storage device, record cache/storage context, and keep reservations,
   RSS, logical traffic and physical I/O separate. Existing warm WSL/OPFS evidence
   cannot select device-specific defaults. Experimental policies should stay
   opt-in until their own correctness and performance acceptance is met.
5. **Prepare one reviewable release snapshot.** Review the accumulated changes,
   rerun applicable checks, regenerate the benchmark catalog and prepare a
   test-free hosted package. If publication is desired, publish that validated
   package and compare served hashes and behavior against it.

## Human input and action

- **Release priorities:** specify the intended platform/device/workload claims and
  whether the next milestone is a native release, hosted release or further
  engineering. This determines which open gaps are release blockers.
- **Physical devices and dialogs:** provide access to the chosen additional
  devices/OS environments and perform or enable real picker/external-destination
  tests. The current Windows checkout and Linux/WSL cannot establish those claims.
  No macOS work is requested while its deferral stands.
- **Storage calibration:** provide an appropriate target SSD and a controlled
  testing window if device-specific performance choices are a goal.
- **Publication:** a new public-site update needs approval for the newly prepared
  package. The prior approval was used for the recorded October 22 publication;
  it is not treated as blanket permission to publish later local builds.
- **Change review:** decide how to divide and commit the accumulated work before
  release. No new commit, pull request or deployment is created by this handoff.

Routine code fixes and local validation can continue without those decisions.
They become necessary when selecting release claims, testing unavailable devices,
calibrating physical hardware or publishing a new build.
