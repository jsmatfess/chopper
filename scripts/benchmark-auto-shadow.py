#!/usr/bin/env python3
"""Evaluate Auto's shadow predictions through native CLI publication."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from decimal import Decimal
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import tempfile
from threading import Barrier
import time

MIB = 1024 * 1024
CASES = {
    "small-fusion": (1000, 40, False, False, False),
    "correlated": (280_000, 180, False, False, False),
    "gzip-correlated": (280_000, 180, True, False, False),
    "late-wide": (115_000, 150, False, True, False),
    "small-exact": (2500, 40, False, False, True),
    "high-fanout": (1_050_000, 40, False, False, True),
}
ARMS = ("baseline", "shadow", "with-analyze", "opt-in", "opt-in-with-analyze")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fields(index, width, late, rows):
    key = 0 if index % 20 < 17 else 1 + index % 7
    return [str(index), str(key), str(key * 3), "q" * (300_000 if late and index == rows - 1 else width)]


def fixture(case, work):
    rows, width, compressed, late, exact = CASES[case]
    source = work / (case + (".csv.gz" if compressed else ".csv"))
    with source.open("wb") as disk:
        stream = gzip.GzipFile(filename="", mode="wb", fileobj=disk, mtime=0) if compressed else disk
        stream.write(b"id,region,site,payload\n")
        for index in range(rows):
            stream.write((",".join(fields(index, width, late, rows)) + "\n").encode())
        if compressed:
            stream.close()
    if exact:
        operations = [{"type": "assign", "groups": [
            {"name": f"q{index:04}", "percent": "0.1"} for index in range(1000)
        ]}]
    else:
        operations = [
            {"type": "partition", "columns": ["region", "site"]},
            {"type": "assign_probabilistic", "strata": ["site"], "groups": [
                {"name": "major", "percent": "80"}, {"name": "minor", "percent": "20"},
                {"name": "empty", "percent": "0"},
            ]},
            {"type": "shuffle", "strategy": "uniform"},
        ]
    return source, operations


def verify(case, output):
    rows, width, _, late, exact = CASES[case]
    seen = bytearray(rows)
    groups = {}
    encounter = {}
    with (output / "manifest.jsonl").open() as manifest:
        header = json.loads(next(manifest))
        assert header["analysis"]["rows"] == rows
        for line in manifest:
            record = json.loads(line)
            if record["type"] != "output":
                continue
            name = record["path"]
            lineage = record["lineage"]
            assert record["csv_bytes"] == (output / name).stat().st_size <= MIB
            assert record["rows"] <= 50_000
            count = 0
            label = lineage[-1]["allocation"]
            with (output / name).open() as data:
                reader = csv.reader(data)
                assert next(reader) == ["id", "region", "site", "payload"]
                for row in reader:
                    index = int(row[0])
                    assert 0 <= index < rows and not seen[index]
                    seen[index] = 1
                    assert row == fields(index, width, late, rows)
                    if exact:
                        assert index > encounter.get(label, -1)
                        encounter[label] = index
                    else:
                        assert lineage[0]["values"] == row[1:3]
                        assert label in ("major", "minor")
                    count += 1
            assert count == record["rows"]
            if exact:
                groups[label] = count
            elif label == "empty":
                assert count == 0
    assert seen.count(1) == rows
    if exact:
        assert len(groups) == 1000
        assert all(groups[f"q{index:04}"] == rows // 1000 + (index < rows % 1000)
                   for index in range(1000))


def measured(binary, command, stdout, prefix):
    metrics = prefix.with_suffix(".time")
    stderr = prefix.with_suffix(".err")
    started = time.monotonic()
    with stdout.open("w") as out, stderr.open("w") as err:
        process = subprocess.run(["/usr/bin/time", "-f", "%U %S %M", "-o", metrics,
                                  binary, *command], stdout=out, stderr=err, check=False)
    elapsed = time.monotonic() - started
    user, system, rss = metrics.read_text().splitlines()[-1].split()
    result = {"elapsed_s": elapsed, "user_s": float(user), "system_s": float(system),
              "peak_rss_kib": int(rss), "exit": process.returncode}
    if process.returncode:
        result["stderr"] = stderr.read_text()
    return result


def execute(work, binaries, fixtures, case, arm, round_number, barrier=None):
    competing = barrier is not None
    directory = work / f"{case}-{arm}-{round_number}-{competing}"
    directory.mkdir()
    output = directory / "out"
    scratch = directory / "tmp"
    scratch.mkdir()
    source, operations = fixtures[case]
    config = directory / "job.json"
    config.write_text(json.dumps({
        "input": str(source), "output": str(output), "operations": operations,
        "limits": {"rows": 50_000, "bytes": MIB}, "resources": {
            "memory_mb": 32, "workers": 1, "max_record_bytes": MIB, "temp_dir": str(scratch),
        },
    }))
    record = {"case": case, "arm": arm, "round": round_number, "competing": competing}
    binary = binaries[{"with-analyze": "shadow", "opt-in-with-analyze": "opt-in"}.get(arm, arm)]
    report = directory / "profile.json"
    if barrier is not None:
        barrier.wait()
    started = time.monotonic()
    args = ["run", "--config", config, "--yes"]
    if arm.endswith("with-analyze"):
        record["analyze"] = measured(binary, ["analyze", "--config", config], report, directory / "profile")
        args += ["--analysis", report]
    result_path = directory / "result.json"
    record["run"] = measured(binary, args, result_path, directory / "run")
    ended = time.monotonic()
    record["total_elapsed_s"] = ended - started
    if barrier is not None:
        barrier.wait()
    record["scratch_empty"] = not any(scratch.iterdir())
    record["published"] = output.is_dir()
    record["verified"] = False
    if record["run"]["exit"] == 0:
        try:
            stats = json.loads(result_path.read_text())
            diagnostics = stats["diagnostics"]
            record["peak_process_reserved_bytes"] = diagnostics["process_memory"]["peak_reserved_bytes"]
            record["peak_workspace_reserved_bytes"] = diagnostics["peak_workspace_reserved_bytes"]
            record["prepublication_temporary_bytes_read"] = diagnostics["temporary_bytes_read"]
            record["prepublication_temporary_bytes_written"] = diagnostics["temporary_bytes_written"]
            if "auto_plan" in stats:
                record["auto_plan"] = stats["auto_plan"]
            verify(case, output)
            record["verified"] = True
        except (AssertionError, KeyError, ValueError, OSError) as error:
            record["verification_error"] = repr(error)
    shutil.rmtree(directory)
    return record, (started, ended)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arm in ("baseline", "shadow", "opt-in"):
        parser.add_argument("--" + arm, required=True, type=Path)
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    csv.field_size_limit(MIB)
    binaries = {arm: Path(getattr(args, arm.replace("-", "_"))).resolve() for arm in
                ("baseline", "shadow", "opt-in")}
    source = subprocess.check_output(["git", "diff", "HEAD", "--",
        "crates/chopper/src", "crates/chopper-core/src", "Cargo.toml", "Cargo.lock", "vendor",
    ])
    source += Path("crates/chopper/src/engine/auto.rs").read_bytes()
    cpu = Path("/proc/cpuinfo").read_text().split("model name", 1)[1].splitlines()[0].split(":", 1)[1].strip()
    result = {
        "engine_patch_sha256": hashlib.sha256(source).hexdigest(),
        "rustc_version": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "schema_version": 1,
        "host": {"platform": platform.platform(), "cpu_count": os.cpu_count(),
                 "cpu_model": cpu,
                 "temporary_filesystem": subprocess.check_output(["stat", "-f", "-c", "%T", tempfile.gettempdir()], text=True).strip(),
                 "soft_fd_limit": resource.getrlimit(resource.RLIMIT_NOFILE)[0]},
        "baseline_revision": "cf0c1e4f0d5beea05fdbd79e11fb3eb39d7ebd4e",
        "builds": {arm: {"sha256": sha256(binary), "features": [
            "experimental-probabilistic-shuffle-fusion", "experimental-exact-quota-index",
        ] if arm == "opt-in" else []} for arm, binary in binaries.items()},
        "harness_sha256": sha256(Path(__file__)),
        "timing_boundary": "CLI Analyze if requested, Run through publication and report serialization; fixture and verification excluded",
        "fixtures": {}, "jobs": [],
    }
    with tempfile.TemporaryDirectory(prefix="chopper-auto-panel-") as path:
        work = Path(path)
        fixtures = {case: fixture(case, work) for case in CASES}
        for case, (source, operations) in fixtures.items():
            result["fixtures"][case] = {"sha256": sha256(source), "bytes": source.stat().st_size,
                                        "rows": CASES[case][0], "operations": operations}
        for round_number in range(args.rounds):
            arms = ARMS if round_number % 2 == 0 else ARMS[::-1]
            for case in CASES:
                for arm in arms:
                    item, _ = execute(work, binaries, fixtures, case, arm, round_number)
                    result["jobs"].append(item)
                    args.record.write_text(json.dumps(result, indent=2) + "\n")
                    print(case, arm, round_number, round(item["total_elapsed_s"], 3), item["verified"], flush=True)
            for arm in arms:
                barrier = Barrier(2, timeout=120)
                with ThreadPoolExecutor(max_workers=2) as executor:
                    jobs = list(executor.map(
                        lambda case: execute(work, binaries, fixtures, case, arm, round_number, barrier),
                        ("correlated", "high-fanout"),
                    ))
                makespan = max(end for _, (_, end) in jobs) - min(start for _, (start, _) in jobs)
                for item, _ in jobs:
                    item["competing_pair_makespan_s"] = makespan
                    result["jobs"].append(item)
                args.record.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
