"""Compare two native builds using identical seeded jobs and verify logical output parity.

Build the fixture generator with cargo build --release -p chopper --example generate.
Run with --before OLD_CHOPPER --after NEW_CHOPPER --generator GENERATE.
All fixtures, outputs, and temporary data are isolated and removed on completion.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
import zipfile
import shutil


def fingerprint(output, analysis, compression):
    digest = hashlib.sha256()
    digest.update(json.dumps(analysis["stages"], sort_keys=True).encode())
    digest.update(analysis["logical_digest"].encode())
    archive = zipfile.ZipFile(output / "outputs.zip") if compression == "zip" else None
    try:
        with (output / "manifest.jsonl").open() as manifest:
            next(manifest)
            for line in manifest:
                entry = json.loads(line)
                digest.update(json.dumps({key: entry[key] for key in
                    ["path", "rows", "csv_bytes", "lineage"]}, sort_keys=True).encode())
                path = output / entry["path"]
                source = (archive.open(entry["path"]) if archive else
                          gzip.open(path, "rb") if compression == "gzip" else path.open("rb"))
                with source:
                    while block := source.read(1024 * 1024):
                        digest.update(block)
    finally:
        if archive:
            archive.close()
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--generator", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=300000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--work-dir", type=Path, help="Parent filesystem for fixture, spill, and output")
    args = parser.parse_args()
    if args.rows < 1000 or args.repeats < 1:
        parser.error("rows must be at least 1000 and repeats must be positive")
    shuffle = {"type": "shuffle", "strategy": "uniform"}
    balanced = {"type": "balanced", "files": 10}
    partition = {"type": "partition", "columns": ["country"]}
    assign = {"type": "assign", "groups": [
        {"name": "treatment", "percent": "80"}, {"name": "control", "percent": "20"}]}
    cases = [
        ("rows", [], 32, 1, "none"),
        ("balanced", [balanced], 32, 1, "none"),
        ("shuffle32", [shuffle, balanced], 32, 1, "none"),
        ("shuffle256", [shuffle, balanced], 256, 1, "none"),
        ("partition_shuffle", [partition, shuffle, balanced], 256, 4, "none"),
        ("partition_assign_shuffle", [partition, assign, shuffle, balanced], 256, 4, "none"),
        ("gzip", [shuffle, balanced], 256, 4, "gzip"),
        ("zip", [shuffle, balanced], 256, 4, "zip"),
    ]
    with tempfile.TemporaryDirectory(prefix="chopper-benchmark-", dir=args.work_dir) as directory:
        root = Path(directory)
        subprocess.run([str(args.generator.resolve()), str(root / "input.csv"), str(args.rows), "128"], check=True)
        for name, operations, memory, workers, compression in cases:
            reference = None
            measurements = {"before": [], "after": []}
            # Alternate builds to reduce systematic ordering bias.
            for repeat in range(args.repeats):
                builds = [("before", args.before), ("after", args.after)]
                if repeat % 2:
                    builds.reverse()
                for label, executable in builds:
                    output = root / "output"
                    config = {"version": 1, "input": str(root / "input.csv"), "output": str(output),
                              "seed": "benchmark-1", "compression": compression, "operations": operations,
                              "limits": {"rows": max(args.rows, 100000)},
                              "resources": {"memory_mb": memory, "workers": workers,
                                            "max_record_bytes": 1048576, "temp_dir": str(root)}}
                    if name == "rows":
                        config["limits"]["rows"] = 100000
                    path = root / "job.json"
                    path.write_text(json.dumps(config))
                    started = time.perf_counter()
                    result = subprocess.run([str(executable.resolve()), "run", "--config", str(path), "--yes"],
                                            capture_output=True, text=True)
                    elapsed = time.perf_counter() - started
                    if result.returncode:
                        raise RuntimeError(f"{name}/{label}: {result.stderr}")
                    analysis = json.loads(result.stdout)
                    actual = fingerprint(output, analysis, compression)
                    if reference is None:
                        reference = actual
                    if actual != reference:
                        raise AssertionError(f"Logical output mismatch: {name}/{label}")
                    measurements[label].append((elapsed, analysis["analysis_seconds"], analysis["peak_temp_bytes"]))
                    shutil.rmtree(output)
            for label, samples in measurements.items():
                print(json.dumps({"case": name, "build": label, "rows": args.rows, "repeats": args.repeats,
                                  "median_seconds": round(statistics.median(s[0] for s in samples), 4),
                                  "median_analysis_seconds": round(statistics.median(s[1] for s in samples), 4),
                                  "peak_temp_bytes": max(s[2] for s in samples), "logical_outputs_match": True}), flush=True)


if __name__ == "__main__":
    main()
