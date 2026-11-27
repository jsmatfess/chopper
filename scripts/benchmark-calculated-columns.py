#!/usr/bin/env python3
"""Measure complete deterministic calculated-column jobs at fitting and spilling budgets."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def calculation(name, expression):
    return {"name": name, "expression": expression}


def workload(name, *definitions):
    return name, definitions, [{"type": "partition", "columns": [definitions[-1]["name"]]}]


CASES = [
    workload("text", calculation("key", "UPPER(TRIM(region))")),
    workload("numeric", calculation("cost", "ROUND(NUMBER(amount) * 1.03, 2)"),
             calculation("band", 'IF(cost >= 10, "large", "small")')),
    workload("pattern", calculation("key", 'REGEX_REPLACE(code, "([A-Z]{2})-[0-9]+", "$1")')),
    workload("timestamp", calculation("ts", "TIMESTAMP_PARSE(when)"),
             calculation("day", 'TIMESTAMP_EXTRACT(ts, "day", "local")')),
]
ROWS = 18000
MAX_BYTES = 8 * 1024 * 1024


def fixture(path):
    even = "2026-11-23T00:30:00.123456789+02:00"
    odd = "2026-11-22T22:30:00.123456789Z"
    padding = "x" * 1200
    with path.open("w", newline="\n", encoding="utf-8") as file:
        file.write("id,region,amount,code,when,payload\n")
        for row in range(ROWS):
            region = [" north ", " south"][row % 2]
            code = ["AB", "CD"][row % 2]
            file.write(f"{row},{region},{row % 20},{code}-{row},{[even, odd][row % 2]},{padding}\n")


def verify(output, analysis):
    fingerprints = []
    rows = 0
    bytes_written = 0
    manifest = (output / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    for line in manifest[1:]:
        entry = json.loads(line)
        if entry["type"] != "output":
            continue
        path = output / entry["path"]
        size = path.stat().st_size
        assert size == entry["csv_bytes"] == entry["stored_bytes"] <= MAX_BYTES
        rows += entry["rows"]
        bytes_written += size
        fingerprints.append({
            "path": entry["path"], "lineage": entry["lineage"], "rows": entry["rows"],
            "csv_bytes": size, "sha256": digest(path),
        })
    assert rows == analysis["rows"] == ROWS
    assert bytes_written == analysis["output_csv_bytes"]
    assert len(fingerprints) == analysis["output_files"]
    return fingerprints


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if command("git", "status", "--porcelain"):
        parser.error("benchmark from a clean committed source checkout")
    build_command = ["cargo", "build", "--release", "--locked", "-p", "chopper-csv"]
    subprocess.run(build_command, check=True)
    metadata = json.loads(command("cargo", "metadata", "--no-deps", "--format-version", "1"))
    executable = Path(metadata["target_directory"]) / "release" / "chopper"
    build = {
        "commit": command("git", "rev-parse", "HEAD"),
        "tree": command("git", "rev-parse", "HEAD^{tree}"),
        "binary_sha256": digest(executable),
        "harness_sha256": digest(Path(__file__)),
        "rustc": command("rustc", "-Vv"),
        "package": command(str(executable), "--version"),
        "build_command": build_command,
        "features": "default",
    }
    with args.output.open("x", encoding="utf-8", newline="\n") as evidence, \
            tempfile.TemporaryDirectory(prefix="chopper-calculated-columns-", dir=args.work_dir) as temporary:
        def write(record):
            print(json.dumps(record, sort_keys=True), file=evidence, flush=True)

        root = Path(temporary)
        source = root / "input.csv"
        fixture(source)
        source_info = {"sha256": digest(source), "bytes": source.stat().st_size, "rows": ROWS}
        write({
            "type": "context", "schema_version": 1, "build": build, "fixture": source_info,
            "platform": platform.platform(), "machine": platform.machine(),
            "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
            "filesystem_type": command("stat", "-f", "-c", "%T", str(root)),
            "cache": "fixture written once, no cache drop, modes alternate order",
            "timing_scope": "CLI process launch through native publication and stdout completion",
        })
        for name, definitions, operations in CASES:
            reference = None
            for repeat in range(args.repeats):
                order = [256, 32] if repeat % 2 == 0 else [32, 256]
                for memory in order:
                    with tempfile.TemporaryDirectory(prefix="job-", dir=root) as job_dir:
                        directory = Path(job_dir)
                        output = directory / "result"
                        workspace = directory / "temp"
                        workspace.mkdir()
                        configuration = {
                            "input": str(source), "output": str(output), "calculated_columns": definitions, "operations": operations,
                            "limits": {"bytes": MAX_BYTES},
                            "resources": {"workers": 1, "memory_mb": memory, "grouping": "sort",
                                          "max_record_bytes": 1024 * 1024, "temp_dir": str(workspace)},
                        }
                        config = directory / "job.json"
                        config.write_text(json.dumps(configuration), encoding="utf-8")
                        start = time.perf_counter()
                        completed = subprocess.run([executable, "run", "--config", config, "--yes"],
                                                   capture_output=True, text=True, check=False)
                        seconds = time.perf_counter() - start
                        record = {
                            "type": "calculation_baseline_run", "case": name, "repeat": repeat + 1,
                            "memory_mib": memory, "workers": 1, "wall_seconds": seconds,
                            "exit_code": completed.returncode, "calculated_columns": definitions, "operations": operations,
                            "fixture_sha256": source_info["sha256"], "binary_sha256": build["binary_sha256"],
                        }
                        try:
                            completed.check_returncode()
                            analysis = json.loads(completed.stdout)
                            fingerprints = verify(output, analysis)
                            diagnostic = analysis["diagnostics"]
                            assert bool(diagnostic["sort_runs"]) == (memory == 32), diagnostic
                            if reference is None:
                                reference = fingerprints
                            assert fingerprints == reference
                            record.update(status="passed", output=fingerprints, timings=analysis["timings"],
                                          sort_runs=diagnostic["sort_runs"], merge_operations=diagnostic["merge_operations"],
                                          peak_temp_bytes=analysis["peak_temp_bytes"],
                                          peak_workspace_reserved_bytes=diagnostic["peak_workspace_reserved_bytes"])
                        except Exception as error:
                            record.update(status="failed", error=repr(error), stdout=completed.stdout, stderr=completed.stderr)
                            write(record)
                            raise
                        write(record)


if __name__ == "__main__":
    main()
