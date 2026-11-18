## Terminal direct output: dynamic owner and cancellation control (2026-11-03)

**Decision: reject the unchanged prototype's cancellation precedence; retain a
one-line publication-entry remedy after eight unchanged controls pass.** The
[control record](../../benchmarks/terminal-direct-dynamic-owner-2026-11-03.json) and
[revision patch](../../benchmarks/terminal-direct-dynamic-owner-2026-11-03.patch) extend
only the isolated prototype, leaving production dispatch and defaults unchanged.
No new elapsed-time panel or promotion accompanies these controls. The revised
source passes native formatting, workspace/all-target Clippy with warnings denied
and locked workspace tests; the latter reuses rather than reruns the separate
eight-scenario focused pass. These are Linux checks, not Windows or WASI
validation of the revised prototype.

Native Linux/WSL uses a frozen 65,537-row plain ASCII fixture: unique IDs, one
partition, probabilistic 100/0 named allocations, a final 16-KiB payload and strict
2,000-row/65,536-byte caps. Both paths share one test binary: explicit Prepare plus
Execute is the baseline; experimental terminal Run is the challenger. At the common
65,536-serialized-row callback, an independent workspace acquires exactly 16 MiB
from the 32-MiB shared pool while the output writer is already live. This competitor
stays through publication or releases at the end-of-serialization boundary.

All four successful revised jobs preserve exact CSV names, bytes and order, output
records and 17 logical Analysis fields. An independent plain-field verifier checks
every unique ID and payload, named empty output and encoded caps. It is deliberately
limited to this no-quoting fixture. All eight revised scenarios check temporary and
private staging cleanup, only the competitor's grant surviving job destruction,
zero final grants after its release and one input-start visit without raw replay.

Two further modes fill each path's remaining pool at its finalization callback,
then either leave denial active or also cancel. Those final grants differ between
paths and are **not** a matched admission-domain comparison. Both paths must report
typed shared denial in the first mode and cancellation in the second. The original
prototype passes seven scenarios but fails the eighth: its publication method
reserves the manifest path before checking cancellation, returning shared denial
where the baseline returns cancellation. Cleanup assertions after that failing
assertion were not reached and are not claimed as passes. `Context::event` checks
before notification; cancellation set by that callback needs a subsequent check.
The revised `DirectPublication::publish` calls `ctx.check()` before pressure refresh
or any publication allocation. All eight original expectations then pass.

An initial launch resolved the Cargo proxy symlink to rustup and failed before
compilation. The first actual compile then rejected a verifier's nonexistent CSV
crate API. Both failures and original source remain intact; the corrected verifier
uses independent plain ASCII parsing. The original cancellation failure, fresh
revision, manifests, full logs and focused test binary remain under ignored
`scratch/terminal-dynamic-20261103T1418/`. These are 16 new synthetic control-job
attempts, not additional CLI performance observations; the prior 34 CLI attempts
remain recorded separately. Continuation renews the objective time window under
the updated skill while preserving all earlier terminal session records.

This closes a specific late-cancellation defect and supplies bounded dynamic-owner
controls. Callback-synchronized competing grants do not establish arbitrary thread
interleavings or live host-pressure adaptation. Broader parent shapes, browser and
codec eligibility, admission-domain inclusion and whole-job benefit remain open;
there is no RSS, physical-I/O, universal completion or speed claim. Existing mixed
small timings still do not justify a production selector or more timing repeats.
