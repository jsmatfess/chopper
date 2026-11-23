# Native release upgrade fixtures

## v0.4.0 saved Job

The `v0.4.0/examples/` files are byte-for-byte copies of `examples/job.json`
and `examples/customers.csv` from tag `v0.4.0`, commit
`450834242b840450d7376e9e2823442ee8401619`. The test preserves their relative
paths and runs from the fixture root. The Job was run with the published
Linux x86-64 binary. The [release receipt][v040] has SHA-256
`374ad8ca502fa95d2d026385c79a1a183e69e04afd2394e00a5d4c52180f195e`.
Its Linux executable has SHA-256
`7367b7c119707762cb1a4ebd1026c73cc734bb8036cd3e3c3ff9c3555b7`.

That run published 12 rows in six chunks totaling 426 serialized CSV
bytes. The test checks exact row contents as a multiset, country partition
membership, and exact treatment/control counts within each country.
Each country contributes one control row and the respective treatment
counts are two for DE, three for GB, and four for US. The sampled row
identities within these allocations can vary.

## v0.3.0 Zstandard

The synthetic `v0.3.0/job.json` and `input.csv` were run with the published
Linux x86-64 v0.3.0 binary, commit
`87df5c047a05eafc0e886da8524a69494329925d`. The [release receipt][v030]
has SHA-256
`6fab17a4cffa2b611e1d7f90a93b04463e9ca38c1b426cfe0af6c86b8abb9878`.
Its Linux executable has SHA-256
`29bf3a8f17c349ac2d77887374ce3cfed7f334f64f8e187a88bcf9972e49f7ad`.

From the fixture root, run `/path/to/chopper-0.3.0 run --config job.json --yes`
and copy `result/part-00000001.csv.zst` to `input.csv.zst` to reproduce the
compressed input fixture. Its SHA-256 is
`d9a51c4899ce31f9745eac5da097b5d9d541e2a900a3722414643a7de4176d20`.
It decompresses to the exact bytes of `input.csv`. Keeping both forms lets
the candidate check run without an external decoder.

[v040]: https://github.com/jsmatfess/chopper/releases/download/v0.4.0/chopper-0.4.0-artifact-receipt.json
[v030]: https://github.com/jsmatfess/chopper/releases/download/v0.3.0/chopper-0.3.0-artifact-receipt.json
