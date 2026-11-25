## WASI inspection Job admission cost (2026-11-25)

The admitted decoder bounds requested heap layouts for the Job read and
retains the charge through the borrowing WASI inspection call. A matched
hosted Preview control found a 0.0123-second median cost on a near-1 MiB
Job. The compact Job's median cost was about 0.00003 seconds. Both pass
the frozen 0.050 and 0.008 second gates. [Issue #78](https://github.com/jsmatfess/chopper/issues/78) ·
[Samples and receipts](../../benchmarks/wasi-inspection-job-admission-preview-cost-2026-11-25.json)

The exact two-row CSV and production worker assets were matched. The
larger Job contains 63 maximal formula strings. Each of the three
alternating pairs starts from a new worker and measures from the Preview
request through the exact reply. Separate warmups are excluded.
Every preview returned the expected header, rows and positions.
This is Preview latency, with the consuming Run path outside the timing.

Resource controls reproduce the 41,209-byte required allowance, one-byte
short denial, 8,224 retained bytes and formula scan pause. The same engine
retries after the denial. Both buffered implementations return the same
error after a second-fill source failure and issue three equal read
requests. The first expectation counted only two; the corrected control
requires the full trace. The larger virtual Job and raw malformed
input errors also verify. [Decoder contract and replay](../../cli-job-decoding.md#wasi-inspection)
