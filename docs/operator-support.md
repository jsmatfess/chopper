# Operator support

Start with the [native quickstart and support matrix](../README.md#native-quickstart)
or the [hosted browser requirements](browser.md#local-development).

| Symptom | What to check |
| --- | --- |
| The CLI cannot start | Verify the archive checksum, platform and architecture and run the executable from the extracted directory. On Linux, give `chopper` execute permission and check glibc. On Windows, follow the runtime guidance in the support matrix. |
| The sample input cannot be opened | Run from the directory containing the executable and the `quickstart/` folder. The bundled Job uses relative paths. |
| Chopper refuses the destination | Check permissions on the destination's parent and choose a fresh output directory. Keep earlier results for verification. |
| Native Run runs out of disk space | Check both volumes. Working files use the system temporary directory by default (`resources.temp_dir` in a saved Job or `--temp-dir` with ordered flags selects another). Chopper stages results on the output filesystem for publication, so that volume needs room for the full output. If both paths share one disk, allow for both at once. The temporary byte limit applies to working files. |
| The process uses more memory than the Job setting | The working-memory budget governs tracked engine allocations. Peak process RSS also includes runtime overhead and other allocations. Allow headroom and read the effective settings and resource diagnostics in the Run report. |
| A hosted export stops or runs out of space | Check the browser's origin-private storage quota and the destination's free space. Use a fresh destination for a retry and verify the [completion marker](browser.md#processing-and-limits) before using the result. |

Scale depends on the pipeline, records, host and available storage. Use
[recorded validation](validation.md#latest-recorded-coverage) to check which
builds, workloads, hosts and browsers have been qualified.

Analyze and Run reports can contain input headers, sampled rows and selected-column
values. A manifest can contain configuration paths, part names, group or partition
values, and Analysis details such as the header and preview. Review and redact
these files and related logs before sharing them. Use a small synthetic input
when opening a [support issue](https://github.com/jsmatfess/chopper/issues).
