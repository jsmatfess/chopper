"""Test the verification example against a built native Chopper binary."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class NativeManifest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name)
        self.input = self.root / "input.csv"
        self.input.write_bytes('id,country,note\n1,GB,"a\nb"\n2,GB,café\n3,US,c\n'.encode())

    def run_job(self, compression):
        output = self.root / compression
        target = [] if compression == "none" else ["--compressed-bytes", "1"]
        result = subprocess.run(
            [
                BINARY, "run", "--input", self.input, "--output", output, "--yes",
                "--compression", compression, "--rows", "1", "--output-bom", "true",
                "--output-line-ending", "crlf", "--step", "partition", "--by", "country",
                *target,
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return output

    def verify(self, output):
        return subprocess.run(
            [sys.executable, ROOT / "examples/verify_manifest.py", output],
            capture_output=True, text=True,
        )

    def test_verifies_all_formats_without_stdout_report(self):
        for compression in ("none", "gzip", "zip"):
            with self.subTest(compression=compression):
                output = self.run_job(compression)
                result = self.verify(output)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    json.loads(result.stdout),
                    {"rows": 3, "output_files": 3, "output_csv_bytes": 92},
                )
                with (output / "manifest.jsonl").open(encoding="utf-8") as manifest:
                    job, *chunks = map(json.loads, manifest)
                self.assertEqual(job["schema_version"], 1)
                self.assertTrue(job["application_version"])
                self.assertTrue(job["algorithm_version"])
                self.assertCountEqual(
                    [chunk["lineage"] for chunk in chunks],
                    [[{"operation": 0, "values": [value]}] for value in ("GB", "GB", "US")],
                )
                self.assertTrue(all(chunk["rows"] == 1 for chunk in chunks))
                self.assertTrue(all(
                    chunk["compressed_target_exceeded"] == (compression != "none")
                    for chunk in chunks
                ))

    def test_verifies_job_with_no_output_records(self):
        self.input.write_bytes(b"id,country,note\n")
        output = self.run_job("zip")
        result = self.verify(output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"rows": 0, "output_files": 0, "output_csv_bytes": 0},
        )

    def test_rejects_present_manifest_with_invalid_json_constant(self):
        output = self.run_job("none")
        manifest = output / "manifest.jsonl"
        contents = manifest.read_bytes()
        job, outputs = contents.split(b"\n", 1)
        manifest.write_bytes(job[:-1] + b',"invalid":NaN}\n' + outputs)
        result = self.verify(output)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("invalid JSON", result.stderr)

    def test_rejects_missing_manifest(self):
        output = self.run_job("none")
        (output / "manifest.jsonl").unlink()
        result = self.verify(output)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("manifest.jsonl", result.stderr)

    def test_rejects_present_csv_with_correct_bytes_and_wrong_row_count(self):
        output = self.run_job("none")
        manifest = (output / "manifest.jsonl").read_text(encoding="utf-8")
        record = json.loads(manifest.splitlines()[1])
        csv_file = output / record["path"]
        contents = csv_file.read_bytes()
        header, row = contents.split(b"\r\n", 1)
        # Replace one data record with two records occupying the same bytes.
        two_rows = b"1,,\r\n2,,"
        csv_file.write_bytes(header + b"\r\n" + two_rows + b"x" * (len(row) - 10) + b"\r\n")
        result = self.verify(output)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("row count mismatch", result.stderr)

    def test_rejects_missing_output_record(self):
        output = self.run_job("none")
        manifest = output / "manifest.jsonl"
        records = manifest.read_bytes().splitlines(keepends=True)
        manifest.write_bytes(b"".join(records[:-1]))
        (output / json.loads(records[-1])["path"]).unlink()
        result = self.verify(output)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("job total mismatch", result.stderr)

    def test_rejects_divergent_zip_manifest(self):
        output = self.run_job("zip")
        manifest = output / "manifest.jsonl"
        contents = manifest.read_bytes()
        manifest.write_bytes(b" " + contents)
        with zipfile.ZipFile(output / "outputs.zip") as archive:
            self.assertEqual(archive.read("manifest.jsonl"), contents)
        result = self.verify(output)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("ZIP manifest differs", result.stderr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chopper", type=Path)
    BINARY = parser.parse_args().chopper.resolve()
    unittest.main(argv=[sys.argv[0]])
