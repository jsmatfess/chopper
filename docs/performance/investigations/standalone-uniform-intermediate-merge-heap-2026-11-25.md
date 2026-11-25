## Standalone Uniform intermediate merge heap (2026-11-25)

Keep the current intermediate merge queue. Replacing the winning head in
place saved 5.459 seconds in one matched 8 GiB Run pair. The reversed pair
lost 4.308 seconds. The cohort stopped at the predeclared two-pair rule.
[Issue #20](https://github.com/jsmatfess/chopper/issues/20) ·
[Samples and receipts](../../benchmarks/standalone-uniform-merge-heap-screen-2026-11-25.json)

The scratch change keeps the 64-run hierarchy and snapshot publication. In
each intermediate merge, it updates the winning heap slot when the same run
has another row, or removes that head at EOF. It keeps the previous key's
grant through the existing observation boundary. Final traversal, caps,
framing, field validation and comparator order use their existing paths.
[Exact scratch patch](../../benchmarks/standalone-uniform-merge-heap-replacement-2026-11-25.patch)

| Pair order | Existing, seconds | In-place replacement, seconds | Seconds saved |
| --- | ---: | ---: | ---: |
| Existing then challenger | 61.021 | 55.562 | 5.459 |
| Challenger then existing | 52.356 | 56.664 | −4.308 |

The paired median was 0.576 seconds saved. The screen required all three
pairs to save time and the median to reach one second. Median process CPU
was 49.13 seconds for the existing heap and 49.18 seconds for the
challenger. Managed read and write counts, initial runs, merges, peak
fan-in and peak temporary file count match within each pair.

Build both feature-free Linux executables from
`e0fe0320a2a2da03c67be890ed35988f111e81ef`. The challenge is the exact
linked patch. Use the same 16,777,216-row standalone Uniform fixture,
256 MiB, one worker, strict 1,200 MiB CSV caps and ordinary host
headroom from the [standalone Run recipe](standalone-uniform-direct-publication-2026-11-25.md).
The clock runs from native CLI launch through publication, cleanup and exit.
The independent verifier checks all exact fields, IDs, file inventory,
lineage, serialized caps, nonidentity order and cleanup outside the clock.
Native storage tests and the multiway collision integration control also
pass. Host cache was uncontrolled. The receipt covers WSL Linux.
