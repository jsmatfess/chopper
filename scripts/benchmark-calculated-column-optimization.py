#!/usr/bin/env python3
"""Compare pinned Linux CLIs on ordered, deterministic calculated-column jobs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import tempfile
import time


MAX_BYTES = 8 * 1024 * 1024
FORMULAS = {
    "text": [("key", "UPPER(TRIM(region))")],
    "numeric": [
        ("cost", "ROUND(NUMBER(amount) * 1.03, 2)"),
        ("band", 'IF(cost >= 10, "large", "small")'),
    ],
    "pattern": [("key", 'REGEX_REPLACE(code, "([A-Z]{2})-[0-9]+", "$1")')],
    "timestamp": [
        ("ts", "TIMESTAMP_PARSE(when)"),
        ("day", 'TIMESTAMP_EXTRACT(ts, "day", "local")'),
    ],
}
PANEL = [
    ("text-small", "text", 18_000, 1200, 256),
    ("numeric-small", "numeric", 18_000, 1200, 256),
    ("pattern-small", "pattern", 18_000, 1200, 256),
    ("timestamp-small", "timestamp", 18_000, 1200, 256),
    ("text-wide", "text", 180_000, 1200, 32),
    ("numeric-wide", "numeric", 180_000, 1200, 32),
    ("pattern-wide", "pattern", 180_000, 1200, 32),
    ("timestamp-wide", "timestamp", 180_000, 1200, 32),
    ("numeric-narrow", "numeric", 350_000, 32, 256),
    ("timestamp-narrow", "timestamp", 350_000, 32, 256),
    ("terminal-text-small", "text", 18_000, 1200, 256),
    ("terminal-text-below", "text", 95_000, 1200, 256),
    ("terminal-text-wide", "text", 180_000, 1200, 32),
    ("terminal-pattern-wide", "pattern", 140_000, 1600, 32),
    ("terminal-timestamp-wide", "timestamp", 180_000, 1200, 32),
    ("terminal-timestamp-narrow", "timestamp", 350_000, 32, 256),
    ("control-grouped", "grouped", 180_000, 1200, 32),
    ("control-direct", "direct", 350_000, 32, 256),
]


def digest(path):
    with path.open("rb") as contents:
        return hashlib.file_digest(contents, "sha256").hexdigest()


def fixture(path, rows, width):
    timestamps = ("2026-11-23T00:30:00.123456789+02:00", "2026-11-22T22:30:00.123456789Z")
    padding = "x" * width
    with path.open("x", encoding="utf-8", newline="\n") as output:
        print("id,region,amount,code,when,payload", file=output)
        for row in range(rows):
            parity = row % 2
            region, code = ((" north ", "AB"), (" south ", "CD"))[parity]
            print(f"{row},{region},{row % 20},{code}-{row},{timestamps[parity]},{padding}", file=output)


def output_identity(output, raw, rows):
    files = []
    with (output / "manifest.jsonl").open(encoding="utf-8") as manifest:
        for line in manifest:
            entry = json.loads(line)
            if entry["type"] != "output":
                continue
            path = output / entry["path"]
            size = path.stat().st_size
            assert size == entry["csv_bytes"] == entry["stored_bytes"] <= MAX_BYTES
            files.append({
                "path": entry["path"],
                "lineage": entry["lineage"],
                "rows": entry["rows"],
                "csv_bytes": size,
                "sha256": digest(path),
            })
    assert sum(file["rows"] for file in files) == raw["rows"] == rows
    assert sum(file["csv_bytes"] for file in files) == raw["output_csv_bytes"]
    assert len(files) == raw["output_files"]
    return dict(rows=rows, columns=raw["columns"], groups=raw["groups"], stages=raw["stages"], output=files)


def run(binary, configuration, directory):
    config = directory / "job.json"
    metrics = directory / "process.txt"
    config.write_text(json.dumps(configuration), encoding="utf-8")
    command = [
        "/usr/bin/time", "-f", "%U %S %M %I %O", "-o", str(metrics),
        str(binary), "run", "--config", str(config), "--yes",
    ]
    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True)
    wall = time.perf_counter() - started
    record = dict(wall_seconds=wall, exit_code=completed.returncode)
    try:
        completed.check_returncode()
        user, system, rss, reads, writes = metrics.read_text().split()
        raw = json.loads(completed.stdout)
        diag = raw["diagnostics"]
        profile = re.search(r"^chopper_profile_formula_and_render_ns=(\d+)$", completed.stderr, re.M)
        thread_cpu = re.search(r"^chopper_profile_thread_cpu=([0-9,]+)$", completed.stderr, re.M)
        record.update(
            cpu_user_seconds=float(user), cpu_system_seconds=float(system), max_rss_kib=int(rss),
            filesystem_input_operations=int(reads), filesystem_output_operations=int(writes),
            timings=raw["timings"], peak_temp_bytes=raw["peak_temp_bytes"],
            peak_workspace_reserved_bytes=diag["peak_workspace_reserved_bytes"],
            sort_runs=diag["sort_runs"], merge_operations=diag["merge_operations"],
            profile_formula_and_render_ns=int(profile[1]) if profile else None,
        )
        if thread_cpu:
            fields = ("stage_ns", "sample_ns", "sample_count", "clock_overhead_ns", "formula_calls")
            record["profile_thread_cpu"] = dict(zip(fields, map(int, thread_cpu[1].split(",")), strict=True))
        return record, raw
    except Exception as error:
        record.update(error=repr(error), stdout=completed.stdout, stderr=completed.stderr)
        return record, None


def measure(args):
    binaries = {name: getattr(args, name).resolve(strict=True) for name in ("baseline", "candidate")}
    selected = [spec for spec in PANEL if not args.case or spec[0] in args.case]
    with args.output.open("x", encoding="utf-8") as evidence, tempfile.TemporaryDirectory(
        prefix="calculation-pairs-", dir=args.work_dir
    ) as temporary:
        def write(item):
            print(json.dumps(item, sort_keys=True), file=evidence, flush=True)

        root = Path(temporary)
        write(dict(
            type="context", schema_version=1, platform=platform.platform(),
            cpu=next(line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines()
                     if line.startswith("model name")),
            affinity=sorted(os.sched_getaffinity(0)),
            filesystem=subprocess.check_output(["stat", "-f", "-c", "%T", str(root)], text=True).strip(),
            builds={key: dict(path=str(path), sha256=digest(path)) for key, path in binaries.items()},
            harness_sha256=digest(Path(__file__)), repeats=args.repeats,
            cases=[case[0] for case in selected],
            timing_scope="before process launch through native publication and stdout capture, via GNU time",
            cache="generated once per shape, no cache drop, opposite order in successive pairs",
        ))
        fixtures = {}
        for name, formula, rows, width, memory in selected:
            key = rows, width
            if key not in fixtures:
                input_path = root / f"rows-{rows}-payload-{width}.csv"
                fixture(input_path, rows, width)
                fixtures[key] = input_path, digest(input_path)
            input_path, input_hash = fixtures[key]
            definitions = [dict(name=column, expression=code) for column, code in FORMULAS.get(formula, ())]
            selector = definitions[-1]["name"] if definitions else "region"
            terminal = formula == "direct" or name.startswith("terminal-")
            operations = [] if terminal else [dict(type="partition", columns=[selector])]
            reference = None
            for repeat in range(1, args.repeats + 1):
                order = list(binaries) if repeat % 2 == 1 else list(reversed(binaries))
                for variant in order:
                    with tempfile.TemporaryDirectory(prefix="job-", dir=root) as job:
                        directory = Path(job)
                        workspace = directory / "temp"
                        workspace.mkdir()
                        output = directory / "result"
                        config = dict(
                            input=str(input_path), output=str(output), operations=operations,
                            limits=dict(bytes=MAX_BYTES),
                            resources=dict(workers=1, memory_mb=memory, grouping="sort",
                                           max_record_bytes=1024 * 1024, temp_dir=str(workspace)),
                        )
                        if definitions:
                            config["calculated_columns"] = definitions
                        record, raw = run(binaries[variant], config, directory)
                        record.update(type="calculation_pair_run", case=name, variant=variant, repeat=repeat,
                                      fixture_sha256=input_hash, fixture_bytes=input_path.stat().st_size,
                                      rows=rows, payload_width=width, memory_mib=memory, workers=1,
                                      operations=operations, calculated_columns=definitions)
                        try:
                            assert raw is not None, record.get("error")
                            identity = output_identity(output, raw, rows)
                            if reference is None:
                                reference = identity
                            assert identity == reference, "output identity mismatch"
                            if memory == 32 and not terminal:
                                assert record["sort_runs"] > 1 and record["merge_operations"] > 0
                            record.update(status="passed", identity=identity)
                        except Exception as error:
                            record.update(status="failed", verification_error=repr(error))
                            write(record)
                            raise
                        write(record)
            print(f"{name}: {args.repeats} pairs verified", flush=True)


def verify(path):
    with path.open(encoding="utf-8") as evidence:
        context = json.loads(next(evidence))
        cells = {}
        for line in evidence:
            row = json.loads(line)
            assert row["status"] == "passed" and row["exit_code"] == 0
            cell = cells.setdefault(row["case"], {})
            key = row["repeat"], row["variant"]
            assert key not in cell
            cell[key] = row
    assert cells
    if "cases" in context:
        assert cells.keys() == set(context["cases"])
    for name, cell in cells.items():
        pairs = [(cell[i, "baseline"], cell[i, "candidate"]) for i in range(1, context["repeats"] + 1)]
        assert len(cell) == 2 * len(pairs)
        assert all(base["identity"] == candidate["identity"] and base["fixture_sha256"] == candidate["fixture_sha256"]
                   for base, candidate in pairs)
        assert all(base["identity"] == pairs[0][0]["identity"] for base, _ in pairs)
        if name.startswith("control-"):
            for base, candidate in pairs:
                for metric in ("sort_runs", "merge_operations", "peak_temp_bytes"):
                    assert base[metric] == candidate[metric], (name, metric, base[metric], candidate[metric])
        seconds = [base["wall_seconds"] - candidate["wall_seconds"] for base, candidate in pairs]
        print(f"{name}: median paired saving {statistics.median(seconds):+.3f}s, "
              f"range [{min(seconds):+.3f}, {max(seconds):+.3f}]")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(required=True, dest="mode")
    run_parser = modes.add_parser("measure")
    for argument in ("baseline", "candidate", "output", "work-dir"):
        run_parser.add_argument(f"--{argument}", type=Path, required=True)
    run_parser.add_argument("--case", choices=[case[0] for case in PANEL], action="append")
    run_parser.add_argument("--repeats", type=int, default=5)
    verifier = modes.add_parser("verify")
    verifier.add_argument("evidence", type=Path)
    args = parser.parse_args()
    if args.mode == "verify":
        verify(args.evidence)
    else:
        if args.repeats < 1 or not sys.platform.startswith("linux"):
            parser.error("positive repeats and Linux are required")
        measure(args)


if __name__ == "__main__":
    main()
