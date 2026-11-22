#!/usr/bin/env python3
"""Build fixtures and compare complete native gzip/ZIP jobs. Run from repo root."""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import time
import zipfile

MIB = 1024 * 1024
HEADER = b"id,region,sku,note,payload\n"
REGIONS = 8
BASE = "87df5c047a05eafc0e886da8524a69494329925d"


def digest(path):
    with open(path, "rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def write_fixture(path, mib, seed):
    randomizer = random.Random(seed)
    whole = hashlib.sha256(HEADER)
    regions = [hashlib.sha256(HEADER) for _ in range(REGIONS)]
    notes = [b"delivery-window-priority-" * (1 + index % 5) for index in range(32)]
    rows = 0
    with open(path, "xb") as output:
        output.write(HEADER)
        while output.tell() < mib * MIB:
            region = rows % REGIONS
            fields = (
                str(rows).encode(),
                f"region-{region}".encode(),
                f"sku-{randomizer.randrange(65000)}".encode(),
                randomizer.choice(notes),
                base64.b64encode(randomizer.randbytes(randomizer.randrange(24, 104))),
            )
            row = b",".join(fields) + b"\n"
            output.write(row)
            whole.update(row)
            regions[region].update(row)
            rows += 1
    return {
        "kind": "fixture", "name": path.stem, "bytes": path.stat().st_size,
        "rows": rows, "sha256": whole.hexdigest(),
        "regions": [item.hexdigest() for item in regions],
    }


def operations(shape):
    if shape in ("single", "capped"):
        return []
    if shape == "many":
        return [{"type": "balanced", "files": 8}]
    if shape == "hundreds":
        return [{"type": "balanced", "files": 256}]
    if shape == "heavy":
        return [{"type": "partition", "columns": ["region"]}, {"type": "balanced", "files": 2}]
    raise ValueError(shape)


def output_records(destination):
    with open(destination / "manifest.jsonl", encoding="utf-8") as manifest:
        entries = [json.loads(line) for line in manifest]
    return entries[0], [entry for entry in entries if entry["type"] == "output"]


def verify_output(destination, fixture, shape, codec, cap=None):
    manifest, records = output_records(destination)
    if shape == "capped":
        assert len(records) > 1
        assert all(item["csv_bytes"] <= MIB for item in records)
    else:
        assert len(records) == {"single": 1, "many": 8, "hundreds": 256, "heavy": 16}[shape]
    assert sum(row["rows"] for row in records) == fixture["rows"]
    if cap is not None:
        assert all(row["csv_bytes"] <= cap for row in records)
    expected = fixture["regions"] if shape == "heavy" else [fixture["sha256"]]
    hashes = [hashlib.sha256(HEADER) for _ in expected]
    counts = [0] * len(expected)
    zip_path = destination / "outputs.zip"
    archive = zipfile.ZipFile(zip_path) if codec == "zip" else None
    try:
        if archive is not None:
            assert archive.namelist() == [record["path"] for record in records] + ["manifest.jsonl"]
            with archive.open("manifest.jsonl") as member:
                assert member.read() == (destination / "manifest.jsonl").read_bytes()
        for index, record in enumerate(records):
            path = Path(record["path"])
            # The pipeline-specific names may use directories, but remain relative.
            assert not path.is_absolute() and ".." not in path.parts
            group = index // 2 if shape == "heavy" else 0
            if archive is not None:
                assert archive.getinfo(record["path"]).compress_size == record["stored_bytes"]
                decoded = archive.open(record["path"])
            else:
                assert (destination / path).stat().st_size == record["stored_bytes"]
                decoded = gzip.open(destination / path)
            with decoded:
                assert decoded.readline() == HEADER
                length, lines = len(HEADER), 0
                for data in iter(lambda: decoded.read(256 * 1024), b""):
                    length += len(data)
                    lines += data.count(b"\n")
                    hashes[group].update(data)
                assert length == record["csv_bytes"]
                assert lines == record["rows"]
                counts[group] += lines
    finally:
        if archive is not None:
            archive.close()
    assert [item.hexdigest() for item in hashes] == expected
    assert sum(counts) == fixture["rows"]
    stored = zip_path.stat().st_size if archive is not None else sum(item["stored_bytes"] for item in records)
    return {"stored_bytes": stored, "verified_sha256": expected, "output_files": len(records),
            "csv_bytes": sum(item["csv_bytes"] for item in records), "manifest": manifest}


def append(path, record):
    with open(path, "a", encoding="utf-8") as output:
        print(json.dumps(record, separators=(",", ":")), file=output)
        output.flush()


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    prepare = commands.add_parser("fixtures")
    prepare.add_argument("root", type=Path)
    prepare.add_argument("--large-mib", type=int, default=256)
    prepare.add_argument("--large-seed", type=int, default=582)
    native = commands.add_parser("native")
    native.add_argument("root", type=Path)
    native.add_argument("fixtures", type=Path)
    native.add_argument("--build", action="append", nargs=2, required=True, metavar=("LABEL", "EXE"))
    native.add_argument("--repeats", type=int, default=3)
    native.add_argument("--case", action="append", nargs=2, required=True, metavar=("SIZE", "SHAPE"))
    native.add_argument("--workers", type=int, default=0)
    native.add_argument("--codec", action="append", choices=("gzip","zip"))
    native.add_argument("--build-workers", action="append", nargs=2, default=[], metavar=("LABEL", "N"))
    verify = commands.add_parser("verify")
    verify.add_argument("results", type=Path)
    verify.add_argument("count", type=int)
    observed = commands.add_parser("verify-output")
    observed.add_argument("destination", type=Path)
    observed.add_argument("fixtures", type=Path)
    observed.add_argument("size")
    observed.add_argument("shape")
    observed.add_argument("codec", choices=("gzip", "zip"))
    return parser.parse_args()


def run_native(args):
    root = args.root.resolve()
    root.mkdir()
    fixture_root = args.fixtures.resolve()
    fixtures = json.loads((fixture_root / "fixtures.json").read_text())
    binary = {label: Path(path).resolve() for label, path in args.build}
    requested_workers = {key:int(value) for key, value in args.build_workers}
    assert requested_workers.keys() <= binary.keys()
    results = root / "runs.jsonl"
    append(results, {
        "kind": "environment", "runtime": "wsl-native" if "microsoft" in platform.release().lower() else ("native-windows" if os.name == "nt" else "native"),
        "platform": platform.platform(), "cpu_count": os.cpu_count(),
        "base_commit": BASE, "executable_sha256": {key: digest(path) for key, path in binary.items()},
        "harness_sha256": digest(__file__), "cache": "warm/uncontrolled",
        "timer": "CLI spawn through successful atomic publication and process exit",
        "workers_requested": {label:requested_workers.get(label,args.workers) for label in binary}, "memory_requested": "auto",
    })
    for fixture in fixtures.values():
        append(results, fixture)
        assert digest(fixture_root / (fixture["name"] + ".csv")) == fixture["sha256"]
    for size, shape in args.case:
        fixture = fixtures[size]
        for codec in args.codec or ("gzip", "zip"):
            for rep in range(args.repeats):
                for label in (list(binary) if rep % 2 == 0 else list(reversed(binary))):
                    case = root / f"{size}-{shape}-{codec}-{rep}-{label}"
                    case.mkdir()
                    destination = case / "output"
                    cap = fixture["bytes"] + 256 if shape == "single" else MIB if shape == "capped" else None
                    job = {
                        "version": 1, "input": str(fixture_root / (size + ".csv")),
                        "output": str(destination), "compression": codec,
                        "operations": operations(shape),
                        "resources": {"memory_mb": "auto", "workers": requested_workers.get(label, args.workers), "temp_dir": str(case)},
                        "limits": {"bytes": cap},
                    }
                    job_path = case / "job.json"
                    job_path.write_text(json.dumps(job) + "\n")
                    usage = case / "usage.txt"
                    command = [str(binary[label]), "run", "--config", str(job_path), "--yes"]
                    timed = ["/usr/bin/time", "-o", str(usage), "-f", "%U %S %M", *command] if os.name != "nt" else command
                    record = {"kind": "run", "label": label, "codec": codec, "fixture": size,
                              "shape": shape, "repeat": rep, "job_sha256": digest(job_path)}
                    try:
                        with open(case / "stdout.json", "wb") as stdout, open(case / "stderr.log", "wb") as stderr:
                            start = time.perf_counter()
                            process = subprocess.run(timed, stdout=stdout, stderr=stderr)
                            record["seconds"] = time.perf_counter() - start
                        process.check_returncode()
                        if usage.is_file():
                            user, system, rss = usage.read_text().split()
                            record.update(cpu_user_seconds=float(user), cpu_system_seconds=float(system),
                                          rss_peak_kib=int(rss))
                        verified = verify_output(destination, fixture, shape, codec, cap)
                        analysis = json.loads((case / "stdout.json").read_text())
                        manifest = verified.pop("manifest")
                        with open(case / "manifest.jsonl", "wb") as file:
                            file.write((destination / "manifest.jsonl").read_bytes())
                        record.update(verified, status="verified", workers=analysis["workers"],
                                      memory_budget_bytes=analysis["memory_budget_bytes"],
                                      logical_digest=manifest["analysis"]["logical_digest"],
                                      diagnostics=analysis.get("diagnostics"), auto_plan=analysis.get("auto_plan"))
                        shutil.rmtree(destination)
                    except BaseException as error:
                        record.update(status="failed", error=repr(error))
                        raise
                    finally:
                        append(results, record)
                        print(size, shape, codec, rep, label, record.get("seconds"), record["status"], flush=True)


def main():
    args = parse_args()
    if args.mode == "fixtures":
        args.root.mkdir()
        fixtures = {name: write_fixture(args.root / (name + ".csv"), mib, seed)
                    for name, mib, seed in (("small", 1, 580), ("medium", 8, 581), ("large", args.large_mib, args.large_seed))}
        (args.root / "fixtures.json").write_text(json.dumps(fixtures, indent=2) + "\n")
    elif args.mode == "native":
        run_native(args)
    elif args.mode == "verify-output":
        fixtures = json.loads((args.fixtures / "fixtures.json").read_text())
        print(json.dumps(verify_output(args.destination, fixtures[args.size], args.shape, args.codec)))
    else:
        rows = [row for line in args.results.read_text().splitlines() if (row := json.loads(line))["kind"] == "run"]
        assert len(rows) == args.count
        assert all(row["status"] == "verified" and row["seconds"] > 0 for row in rows)


if __name__ == "__main__":
    main()
