## Execution graph landing candidate reconciliation (2026-11-05)

The owner lifted the push pause. Delivery remains subject to the exact-head,
current-base local-CI gate; this authorization changes delivery permission and
adds no performance experiment. The original 126-job acceptance remains scoped
to its earlier production assets. No benchmarks were rerun.

The first delivery attempt tested head
`24d879cd61a0b041879199b6753e0fa587dcf836` against main
`80894c6f0ba13ce1fa940e87002a97450b0dff06`. Native Windows local CI passed;
its receipt SHA-256 is `de098f1c85119d045af9e3e9a94a47eba54b937fc94e14b8935bb328dec52e9e`.
The receipt and referenced full plan/status/logs remain in the Windows checkout's
Git `local-ci/` directory under the exact head/base/platform filename. This pass
belongs to that pair, not to a later merge candidate.

The Linux workflow's native tests passed, but its release build exited 137 while
a concurrent act workflow replaced the same generated native-job Docker
container name. The log records Docker removal/RWLayer failures. Remaining work
in this attempt was deliberately interrupted to avoid further collisions. No
Linux pass was issued. Full logs, frozen inputs and all command output remain
under the shared Git directory's `local-ci/attempt-gj8ek7l9/`; the final runner
status SHA-256 is `6a8ada4313daa6bee272dbf21fca97714fa5a7e30dcbb3b7d92c3133862a08fb`. Its aggregate
status is interrupted/incomplete; that does not erase the earlier failed release
build inside the workflow. A retry is a separate attempt, and an older pass
cannot hide this outcome.

The concurrent delivery subsequently passed and advanced main to
`2ccbd7a75405ac03268e29a6c4b4feeedae5af74`. That revision adds the
[buffered spool field-copy implementation and finding](buffered-spool-field-copy-2026-11-05.md).
The execution-graph branch integrates it, retaining both sets of registered
narratives and explicit family assignments, preserving raw evidence bytes and
regenerating derived navigation. Source merging preserves field validation,
allocation ownership and the graph hooks; current correctness must be checked on
the resulting committed head. Its performance remains unmeasured.

Subsequent Linux workflows run sequentially because act generates shared Docker
job names. Fresh Linux/native Windows receipts must match the new committed
head and current main before `scripts/local-ci.py land` can push. This record
captures the reconciliation checkpoint and grants no receipt reuse or gate
exception. The eventual receipt and normal fast-forward push establish delivery;
this investigation does not claim those pending steps have already passed.
