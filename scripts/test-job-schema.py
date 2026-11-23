#!/usr/bin/env python3
"""Check the release schema against saved Jobs read by the native CLI."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.request import urlopen

from jsonschema import Draft7Validator


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/job.json"
AUTHORING = ROOT / "docs/job-json.md"


def check(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chopper", type=Path, help="path to the native Chopper binary")
    parser.add_argument("--published", action="store_true", help="compare the tagged download after publishing")
    args = parser.parse_args()
    chopper = args.chopper.resolve()
    name, version = subprocess.check_output([chopper, "--version"], text=True).split()
    check(name == "chopper", f"unexpected binary name: {name}")
    relative_path = f"schemas/{version}/job.schema.json"
    url = f"https://raw.githubusercontent.com/jsmatfess/chopper/v{version}/{relative_path}"
    artifact = (ROOT / relative_path).read_bytes()
    schema = json.loads(artifact)
    Draft7Validator.check_schema(schema)
    check(schema["$id"] == url, f"expected release-pinned schema ID {url}")
    if args.published:
        with urlopen(url, timeout=30) as response:
            check(response.read() == artifact, f"tagged schema bytes differ from {relative_path}")

    # Read the association exactly as an editor user copies it from the guide.
    association = json.loads(AUTHORING.read_text(encoding="utf-8").split("```json\n")[1].split("```")[0])
    check(association["json.schemas"] == [{"fileMatch": ["/examples/job.json"], "url": url}],
          "the editor example must associate the tracked Job with its release schema")

    with tempfile.TemporaryDirectory(prefix="chopper-job-schema-") as temp:
        work = Path(temp)
        # A copied schema retains the same local references without fetching its ID.
        downloaded = work / "job.schema.json"
        downloaded.write_bytes(artifact)
        validator = Draft7Validator(json.loads(downloaded.read_bytes()))
        validator.validate(json.loads(EXAMPLE.read_bytes()))
        report = run_cli(chopper, "analyze", EXAMPLE)
        check(report.returncode == 0, report.stderr)

        check_decoder(chopper, validator, work)
        check_defaults(chopper, validator, work)

    print(f"Job schema {version} passed: release identity, editor example, decoder parity and defaults")


def check_decoder(chopper, validator, work):
    config = work / "job.json"
    source = work / "input.csv"
    source.write_text("id,0\n1,a\n2,a\n3,b\n", encoding="utf-8")
    group = {"name": "control", "percent": "100.000000"}
    valid_operations = [
        ({"type": "balanced", "files": 2}, None),
        ({"type": "interleaved", "files": 2}, None),
        ({"type": "partition", "columns": [0]}, 3),
        ({"type": "partition", "columns": ["0"]}, 2),
        ({"type": "assign", "groups": [group]}, None),
        ({"type": "assign_probabilistic", "groups": [group], "strata": ["0"]}, None),
        ({"type": "shuffle"}, None),
        *(({"type": "shuffle", "strategy": strategy}, None)
          for strategy in ("uniform", "auto", "fisher_yates")),
    ]
    for operation, expected_keys in valid_operations:
        job = {"input": str(source), "operations": [operation]}
        validator.validate(job)
        config.write_text(json.dumps(job), encoding="utf-8")
        result = run_cli(chopper, "analyze", config)
        check(result.returncode == 0, f"{operation}: {result.stderr}")
        if expected_keys is not None:
            check(json.loads(result.stdout)["stages"][0]["input_distinct_keys"] == expected_keys,
                  f"{operation}: partition selected the wrong column")

    # Each fragment goes alongside a usable input path; inspect the actual
    # decoder's error context separately from later configuration and input checks.
    cases = [
        ({"resources": {"memory_mb": "auto"}}, True, True, None),
        ({"resources": {"memory_mb": 256, "temp_dir": None, "temp_bytes": None}}, True, True, None),
        ({"resources": {"max_files": 2**64 - 1}}, True, True, None),
        ({"input_csv": {"escape": None, "quote": '"'}, "zip_member": None}, True, True, None),
        ({"limits": {"rows": None, "bytes": None, "compressed_bytes": None}}, True, True, None),
        ({"full_shuffle_rng": "blake3_counter_v1", "full_shuffle_algorithm": "adaptive_v1"}, True, True, None),
        ({"compression": "gzip"}, True, True, None),
        ({"compression": "zip"}, True, True, None),
        ({"$schema": validator.schema["$id"]}, False, False, None),
        ({"random_seed": None}, False, False, None),
        ({"compression": "zstd"}, False, False, None),
        ({"full_shuffle_rng": "other"}, False, False, None),
        ({"full_shuffle_algorithm": "other"}, False, False, None),
        ({"version": 2**32}, False, False, None),
        ({"resources": {"max_files": 2**64}}, False, False, None),
        ({"input_csv": {"extra": True}}, False, False, None),
        ({"output_csv": {"quote": "''"}}, False, False, None),
        ({"limits": {"rows": "1"}}, False, False, None),
        ({"limits": {"extra": 1}}, False, False, None),
        ({"resources": {"extra": 1}}, False, False, None),
        ({"operations": [{"type": "buffer"}]}, False, False, None),
        ({"operations": [{"type": "shuffle", "strategy": "buffer"}]}, False, False, None),
        ({"operations": [{"type": "shuffle", "buffer_rows": 1}]}, False, False, None),
        ({"operations": [{"type": "shuffle", "strategy": None}]}, False, False, None),
        ({"operations": [{"type": "balanced"}]}, False, False, None),
        ({"operations": [{"type": "interleaved", "files": 2, "columns": [0]}]}, False, False, None),
        ({"operations": [{"type": "partition"}]}, False, False, None),
        ({"operations": [{"type": "assign", "groups": [{"name": "a"}]}]}, False, False, None),
        ({"operations": [{"type": "assign_probabilistic", "groups": [dict(group, percent=100)]}]},
         False, False, None),
        ({"operations": [{"type": "assign", "groups": [dict(group, extra=1)]}]}, False, False, None),
        ({"operations": [{"type": "assign", "groups": [group], "strata": None}]}, False, False, None),
        # Parsed-value versus decoder-token differences.
        ({"resources": {"memory_mb": 256.0}}, True, False, None),
        ({"operations": [{"type": "partition", "columns": [0.0]}]}, True, False, None),
        ({"resources": []}, False, True, None),
        ({"operations": [["shuffle"]]}, False, True, None),
        # Configuration semantics and data-dependent checks come after decoding.
        ({"version": 2}, True, True, "unsupported configuration version"),
        ({"limits": {"compressed_bytes": 1}}, True, True, "requires output compression"),
        ({"resources": {"memory_mb": 0}}, True, True, "memory_mb must be between"),
        ({"operations": [{"type": "assign", "groups": [dict(group, percent="99")]}]},
         True, True, "percentages must sum exactly to 100"),
        ({"operations": [{"type": "partition", "columns": ["unknown"]}]},
         True, True, "missing or ambiguous"),
    ]
    cases.extend(({"resources": {"memory_mb": value}}, False, False, None)
                 for value in ("256", "AUTO", -1, 32.5, None, True, {}, []))
    cases.extend(({"operations": [{"type": "partition", "columns": [value]}]}, False, False, None)
                 for value in (-1, 0.5, None, True, {}, [], 2**64))
    for fragment, schema_valid, decoded, later_error in cases:
        job = {"input": str(source), **fragment}
        errors = list(validator.iter_errors(job))
        check((not errors) == schema_valid, f"{fragment}: schema expected {schema_valid}, got {errors}")
        config.write_text(json.dumps(job), encoding="utf-8")
        result = run_cli(chopper, "analyze", config)
        if not decoded:
            check(result.returncode != 0 and result.stderr.startswith("chopper: read job JSON:"),
                  f"{fragment}: expected a decode error, got {result.stderr}")
        elif later_error:
            check(result.returncode != 0 and later_error in result.stderr,
                  f"{fragment}: expected {later_error}, got {result.stderr}")
        else:
            check(result.returncode == 0, f"{fragment}: {result.stderr}")


def check_defaults(chopper, validator, work):
    config = work / "minimal.json"
    output = work / "minimal-output"
    config.write_text(json.dumps({"input": str(work / "input.csv"), "output": str(output)}),
                      encoding="utf-8")
    result = run_cli(chopper, "run", config, "--yes")
    check(result.returncode == 0, result.stderr)
    with (output / "manifest.jsonl").open(encoding="utf-8") as manifest:
        saved = json.loads(next(manifest))["config"]
    validator.validate(saved)
    properties = validator.schema["properties"]
    omitted_on_write = {"full_shuffle_rng", "full_shuffle_algorithm"}
    check(set(saved) | omitted_on_write == set(properties),
          "top-level schema fields and the manifest config differ")
    for field, value in saved.items():
        if field in {"input", "output"}:
            continue  # Processing required these paths.
        declaration = properties[field]
        if "$ref" in declaration:
            definition = declaration["$ref"].removeprefix("#/definitions/")
            fields = validator.schema["definitions"][definition]["properties"]
            expected = {key: spec["default"] for key, spec in fields.items()}
        else:
            expected = declaration["default"]
        check(value == expected, f"{field}: decoded default {value!r} differs from schema {expected!r}")


def run_cli(chopper, command, config, *options):
    return subprocess.run([chopper, command, "--config", config, *options],
                          cwd=ROOT, text=True, capture_output=True, timeout=30)


if __name__ == "__main__":
    main()
