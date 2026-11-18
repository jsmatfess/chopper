## Browser export finalization failure ownership (2026-10-21)

The [before/after contract record](../../evidence-originals.md#sha256-824e854a1aab1306ee460535d72ddfc4711737ea9706aee004b4f9f96e134e9b "Original: docs/benchmarks/browser-export-finalization-2026-10-21.json")
extends the retained-parent WASI output fixture through real same-origin OPFS
destination writers. It injects result-file close, marker write and marker close
failures, in addition to the existing mid-copy rejection, and rejects an existing
completed destination before export callbacks or writes. Successful output still
matches all six retained files, five UTF-16/BOM CSVs and their strict caps exactly.

Before the fix, marker-write rejection leaves its writable un-aborted and a
destination removal fails with `NoModificationAllowedError`. The marker now owns
a catch/abort boundary through write, accounting and close, retaining the original
error if abort itself rejects. The three new fault cases each observe one abort
and zero committed marker bytes; marker faults begin only after all six result
writers close. A created empty marker entry is not a successful completion marker.
The final contract removes all five test destination folders and retained sources.
The 28 UI tests, TypeScript/native UI build and candidate Chromium resource
contract pass. The artifact retains the failing pass rather than replacing it
with the successful one. This is cleanup/correctness acceptance, not timing evidence,
real quota/device failure coverage, cross-tab coordination, picker-backed external
destination acceptance or worker/tab termination acceptance. Those TODO gaps remain.
