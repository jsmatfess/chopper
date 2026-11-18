## Resident allocation admission control (2026-11-02)

**Decision: retain the small fitting-case speed result, but block promotion of
the resident-allocation prototype until its transition headroom is designed and
verified. Stop further timing expansion.** Corpus [recipe decisions](../../history/prior-issues.md#issue-20)
identify the implemented region/probabilistic-allocation/shuffle case but leave
larger working-set parameters hypothesis-driven; they do not establish a fitting
parent-size envelope. Public/exact-allocation and ordered-export recipes are
separate paths. The [comparison criteria](../../history/prior-issues.md#issue-17)
require bounded fallback confidence before selectable execution. The retained
speed samples alone do not satisfy that requirement.

Source inspection identified a transition risk worth a single correctness control.
`reserve_row_capacity` can decline growth; `Sorter::push_packed` then calls
`flush`. Its eligible routing branch constructs and fills `Router` while holding
the retained row buffer, releasing those rows only after successful construction.
Immediate `Sorter::streaming` has no retained-row overlap. Eligibility checks
cardinality/order and nominal route limits, not a grant for this simultaneous
construction; reservation denial propagates. Reusing this path is not proof
that switching from immediate routing preserves its feasible admission domain.

The [probe patch](../../benchmarks/allocation-admission-probe-2026-11-02.patch) and
[derived control](../../benchmarks/allocation-admission-control-2026-11-02.json) record
one native Windows unit-test invocation, with two independent contexts and no
new measured Runs. A test-only nominal memory override of 4 MiB and 2 MiB local
workspace leaves 300,000 bytes after another held reservation, with directory
allowance accounted separately. Both paths receive the same 2,500 synthetic
rows, 128-byte payloads, two preassigned keys and increasing ordinals. This is
an occupied **local** workspace control, not a real concurrent-Job/OS-pressure
measurement, probabilistic membership test or supported 4-MiB CLI configuration.

Immediate routing succeeds and returns all 2,500 IDs in exact key/ordinal order.
Retained sorting instead returns an admission error. The retained-buffer/router
overlap explains a plausible denial site from source, but this probe does not
instrument the exact denied allocation. Both
return workspace usage to the same held baseline (1,797,200 bytes), leave zero
temporary bytes, and release the other grant back to the directory baseline.
Observed reservation maxima are 1,930,646 and 2,054,678 bytes respectively; both
stay within the admitted test envelope. These are reservations, not RSS. The
error case's raw `rows=0` is a missing-result placeholder; it does not mean zero
rows were visited. The test passed by recording outcomes and asserting successful
order/conservation and both cleanup paths; it did not require denial to occur.

The concrete self-reviewed runner manifest has a 600-second command/660-second
batch deadline, estimated 120 seconds/2 GiB additional build storage, within the
unchanged session deadline 2026-11-03 00:17 UTC. Existing compiled dependencies
are cache reuse only. Source, complete vendors and all embedded UI inputs are
retained separately under
`C:/Users/USER/git/jsmatfess/chopper-resident-20261102/scratch/allocation-admission-20261102/`;
`batch/status.json` records one pass and full logs. Original comparison sources,
binaries and raw records remain unchanged. Apply the zero-context probe to the
unchanged source using `git apply --unidiff-zero` in an isolated checkout, then
run the manifest's single `allocation_admission_overlap_probe` test.

This is a constructed admission counterexample for the sorter path, not evidence
that a production CLI job failed, that current default routing regressed, or that
the earlier fitting-case timings are invalid. Native publication, caller-specific
input/output grants, probabilistic draws, real shared-process pressure, browser
behavior and occurrence rates are outside this control. No product code, defaults,
contracts or holdouts changed. The next bounded design question is whether to
reserve construction headroom before retention or supply a safe transition when
that grant is unavailable. It needs its own concrete correctness-first plan;
no larger timing panel or default/selector work is justified before resolution.
