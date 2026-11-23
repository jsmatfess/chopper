"""Check a supplied native Chopper binary against prior-release Jobs."""

import argparse
from collections import Counter
import csv
import gzip
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "scripts/fixtures/release-upgrade"


class ReleaseUpgrade(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.temp = self.root / "temp"
        self.temp.mkdir()

    def run_job(self, fixture, config):
        return subprocess.run(
            [BINARY, "run", "--config", config, "--yes"],
            cwd=fixture, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "TMPDIR": str(self.temp), "TMP": str(self.temp),
                 "TEMP": str(self.temp)},
            timeout=60,
        )

    def verify_manifest(self, directory):
        result = subprocess.run(
            [sys.executable, ROOT / "examples/verify_manifest.py", directory],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_unchanged_v040_job_preserves_rows_and_allocation(self):
        fixture = self.root / "v0.4.0"
        shutil.copytree(FIXTURES / "v0.4.0", fixture)
        result = self.run_job(fixture, "examples/job.json")
        self.assertEqual(result.returncode, 0, result.stderr)

        output = fixture / "chopped-customers"
        self.assertEqual(
            self.verify_manifest(output),
            {"rows": 12, "output_files": 6, "output_csv_bytes": 426},
        )
        job, *chunks = [
            json.loads(line)
            for line in (output / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(job["config"]["version"], 1)
        self.assertEqual(job["config"]["compression"], "zip")
        self.assertEqual(job["config"]["limits"]["rows"], 100000)
        header = ["id", "country", "segment", "note"]
        self.assertEqual(job["analysis"]["header"], header)
        with (fixture / "examples/customers.csv").open(encoding="utf-8", newline="") as stream:
            source = csv.reader(stream)
            self.assertEqual(next(source), header)
            expected_rows = Counter(map(tuple, source))

        actual_rows = Counter()
        allocations = Counter()
        with zipfile.ZipFile(output / "outputs.zip") as archive:
            for chunk in chunks:
                partition, assignment = chunk["lineage"]
                country, = partition["values"]
                group = assignment["allocation"]
                self.assertEqual(partition["operation"], 0)
                self.assertEqual(assignment["operation"], 1)
                self.assertFalse(chunk["compressed_target_exceeded"])
                records = csv.reader(io.StringIO(archive.read(chunk["path"]).decode("utf-8"),
                                                  newline=""), strict=True)
                self.assertEqual(next(records), header)
                for row in records:
                    self.assertEqual(row[1], country)
                    allocations[country, group] += 1
                    actual_rows[tuple(row)] += 1
        self.assertEqual(actual_rows, expected_rows)
        self.assertEqual(allocations, {
            ("DE", "treatment"): 2, ("DE", "control"): 1,
            ("GB", "treatment"): 3, ("GB", "control"): 1,
            ("US", "treatment"): 4, ("US", "control"): 1,
        })

    def test_v030_zstandard_output_rejection(self):
        fixture = self.root / "v0.3.0"
        shutil.copytree(FIXTURES / "v0.3.0", fixture)
        result = self.run_job(fixture, "job.json")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('Zstandard output compression "zstd" was removed', result.stderr)
        self.assertIn('set "compression" to "gzip", "zip", or "none"', result.stderr)
        self.assertCountEqual([p.name for p in fixture.iterdir()],
                              ["input.csv", "input.csv.zst", "job.json"])
        self.assertEqual(list(self.temp.iterdir()), [])

        config = json.loads((fixture / "job.json").read_bytes())
        config["compression"] = "gzip"
        (fixture / "job.json").write_text(json.dumps(config), encoding="utf-8")
        migrated = self.run_job(fixture, "job.json")
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        output = fixture / "result"
        self.assertEqual(self.verify_manifest(output),
                         {"rows": 1, "output_files": 1, "output_csv_bytes": 23})
        with gzip.open(next(output.glob("*.csv.gz")), "rb") as stream:
            self.assertEqual(stream.read(), (fixture / "input.csv").read_bytes())

    def test_v030_zstandard_input_rejection_and_csv_conversion(self):
        fixture = self.root / "v0.3.0"
        shutil.copytree(FIXTURES / "v0.3.0", fixture)
        config_path = fixture / "job.json"
        config = json.loads(config_path.read_bytes())
        config.update(compression="none", input="input.csv.zst")
        config_path.write_text(json.dumps(config), encoding="utf-8")
        result = self.run_job(fixture, "job.json")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Zstandard input is no longer supported", result.stderr)
        self.assertIn("decompress it before running Chopper", result.stderr)
        self.assertCountEqual([p.name for p in fixture.iterdir()],
                              ["input.csv", "input.csv.zst", "job.json"])
        self.assertEqual(list(self.temp.iterdir()), [])

        # input.csv is the known decoded counterpart of the 0.3.0 frame.
        config["input"] = "input.csv"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        converted = self.run_job(fixture, "job.json")
        self.assertEqual(converted.returncode, 0, converted.stderr)
        output = fixture / "result"
        self.assertEqual(self.verify_manifest(output),
                         {"rows": 1, "output_files": 1, "output_csv_bytes": 23})
        self.assertEqual(next(output.glob("*.csv")).read_bytes(),
                         (fixture / "input.csv").read_bytes())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chopper", type=Path, help="path to the extracted candidate executable")
    args = parser.parse_args()
    BINARY = args.chopper.resolve()
    if not BINARY.is_file():
        parser.error(f"executable does not exist: {BINARY}")
    unittest.main(argv=[sys.argv[0]], verbosity=2)
