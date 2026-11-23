# Validate a saved Job

```sh
chopper validate --config job.json
chopper validate --config job.json --json
```

Validate uses the same admitted JSON decoder as scripted Run and Analyze. It
checks the [Job schema](job-json.md), version, operation invariants, configuration
relationships and the presence of both input and output paths. It reads the config file and
leaves the CSV or archive, output destination and temporary directory untouched.
A valid Job can refer to an input that does not exist yet.

[Analyze](specification.md#analyze-and-run) scans the configured input for
statistics such as row counts and column cardinality. It provides advisory
estimates for the pipeline. [Run](run-cli.md) independently validates the
submitted configuration and actual input, including CSV records and column
selections. Run also checks the destination, resolves automatic resource
settings, and enforces the resource limits and availability of the current run.

## Output and exit status

| Outcome | Exit status | Default streams | With `--json` |
| --- | --- | --- | --- |
| Valid Job | 0 | Confirmation on stdout | Result on stdout |
| Config read, decode or validation failure | 1 | Diagnostic on stderr | Result on stdout |
| Invalid command-line usage | 2 | Usage error on stderr | Usage error on stderr |

Exit status 1 also covers failure to write the result. Stream failures can leave
partial output and are reported on stderr. Normal validation results use only the
stream shown in the table.

JSON mode emits one object with `valid` and `error`. A successful result has
`"valid": true` and `"error": null`. A failed result has `"valid": false` and
one diagnostic.

```json
{
  "valid": false,
  "error": {
    "code": "invalid_config",
    "path": "/limits/compressed_bytes",
    "message": "compressed_bytes requires output compression",
    "line": null,
    "column": null
  }
}
```

Use these stable codes in scripts. The message is for people and can change.

| Code | Meaning | Field path |
| --- | --- | --- |
| `config_read` | The config could not be opened, read or admitted, including a size rejection | `null` |
| `json_syntax` | Malformed or incomplete JSON, including trailing content | `null` |
| `json_schema` | Typed decoding rejected a field, value or structure | Field or nearest enclosing value |
| `invalid_config` | A decoded Job failed a semantic rule, including an unsupported version | Canonical Job field |

Paths are JSON Pointers with zero-based array indices, such as
`/operations/0/groups/1/percent`. The empty string refers to the document root.
Schema errors inside an operation can point to the containing operation when the
decoder only locates the operation as a whole. Semantic paths use the Job's
named fields, including for omitted fields. `line` and `column` report the
JSON decoder position when available. Lines and byte columns are one-based,
with column zero possible at a line boundary. A syntax error reports its
position without a field path. Semantic and file errors have null position
fields.
