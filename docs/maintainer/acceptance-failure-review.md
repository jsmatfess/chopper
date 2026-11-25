# Review repeated acceptance failures

When a release acceptance attempt fails unexpectedly, record the fault area, the
failed attempt ID and receipt path or SHA-256, and the assumption being tested in
the owning issue or the batch handoff. Preserve the original receipts and logs.
Group attempts by the underlying assumption and the component or guard it concerns.
A changed error, attempt ID or harness revision can still belong to the same fault
area. Count each failed attempt once. Expected failures in passing negative
controls do not count.

After the second failure in the same fault area, pause acceptance attempts in that
area. Before authorizing another attempt, add a concise review to the same record
with these fields.

- **Hypothesis** — State what could explain the failures and which assumption it
  challenges. Mark unknown causes as unknown.
- **Distinguishing check** — Describe the smallest bounded check that separates
  the plausible explanations. Specify the inputs, existing limits and observations
  that would support or refute the hypothesis.
- **Stop condition** — State when to end the diagnostic and which result, if any,
  would justify requesting another acceptance attempt. Stop on an unexpected
  failure, inconclusive result or exhausted limit and record the outcome for review.

Label the check and its result as diagnostic evidence. A passing diagnostic can
inform a later decision to authorize a fresh acceptance attempt. That attempt
still requires the applicable profile's reviewed plan, preflight, approval,
remaining budget and available slot. Preserve all prior charges and claims. The
earlier attempt stays failed even if cleanup or a later check passes. Apply any
stricter first-failure stop or no-retry rule immediately. This manual review grants
no launch, retry, deadline renewal or new model call.

## Worked review of Windows SMALL sampler startup

The [retained Frozen606 ledger](../releases/0.2.0-frozen606-evidence.json) records
these attempts under `later_protected_browser_attempts`.

| Attempt | Receipt reference in the ledger | Failure |
| --- | --- | --- |
| `20261106T153939Z` | `/later_protected_browser_attempts/0/runtime_records/control-failure.json` | Command-line identity query was denied because `--enable-automation` was absent. Cleanup also reported heartbeat watchdog failures. |
| `20261106T180530Z` | `/later_protected_browser_attempts/1/report` | Identity bound, but Playwright refused the additional page needed by the observer. No quota sample or contract pass was recorded. |

Both failures belong to **protected Windows SMALL sampler initialization**. The
assumption was that the ordinary launch could both prove browser identity and
provide a context capable of hosting the quota observer. The second failure
triggers review even though it got past the first failure point.

- **Hypothesis** — Observer startup needs two independent launch prerequisites.
  The CDP identity query needs the explicit automation flag. The ordinary launch
  needs an explicit multi-page context to host the observer beside the contract
  page. The second attempt exercised a different prerequisite in the same launch
  boundary.
- **Distinguishing check** — Run `node scripts/test-browser-launch.mjs --negative-control`
  once in a fresh runner step with a 120-second deadline, or the remaining
  approved limit if shorter. Use bundled Chromium and disposable contexts to
  check that the unflagged query and implicit context deny their respective
  operations, then verify the identity query and shared pages with the corrected
  launch options. Keep the existing component timeouts and cleanup. The check
  uses no CSV, WASI engine or product Run. [Component check](../../scripts/test-browser-launch.mjs)
- **Stop condition** — End after that one invocation. An unexpected query or page
  result, timeout or cleanup failure stops the diagnostic with both original
  failures retained. A clean result supports reviewing a fresh guarded installed
  SMALL plan under its existing approval and limits. It earns no acceptance credit.

This retrospective review uses the ledger and existing component check design.
The ledger records the later `20261106T183759Z` pass separately and scopes it to
the standard installed Chrome SMALL contract. Keep that scope and both original
failure records.
