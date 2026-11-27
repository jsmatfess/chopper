"""Exercise Chopper from a fresh wheel install and a native CLI build."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

import chopper_csv as chopper


ROOT = Path(__file__).resolve().parents[3]


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as source:
        return list(csv.reader(source, strict=True))


class InstalledWheel(unittest.TestCase):
    def setUp(self):
        previous = Path.cwd()
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.addCleanup(os.chdir, previous)
        os.chdir(work.name)
        shutil.copyfile(ROOT / "examples/customers.csv", "customers.csv")
        self.settings = {"input": "customers.csv", "output": "output"}

    def verify_capped_result(self, manifest_path, report, cap):
        manifest = Path(manifest_path)
        job, *chunks = map(json.loads, manifest.read_text(encoding="utf-8").splitlines())
        header, *expected = read_csv("customers.csv")
        self.assertEqual(job["schema_version"], 1)
        self.assertEqual(job["application_version"], version("chopper-csv"))
        self.assertEqual(job["config"]["limits"]["bytes"], cap)
        self.assertGreater(len(chunks), 3)
        self.assertEqual(
            set(manifest.parent.iterdir()),
            {manifest, *(manifest.parent / chunk["path"] for chunk in chunks)},
        )
        actual = []
        countries = set()
        for chunk in chunks:
            path = manifest.parent / chunk["path"]
            actual_header, *rows = read_csv(path)
            self.assertEqual(actual_header, header)
            self.assertEqual(chunk["type"], "output")
            self.assertEqual(chunk["rows"], len(rows))
            self.assertLessEqual(path.stat().st_size, cap)
            self.assertEqual(chunk["csv_bytes"], path.stat().st_size)
            self.assertEqual(chunk["stored_bytes"], path.stat().st_size)
            country, = chunk["lineage"][0]["values"]
            self.assertEqual(chunk["lineage"][0]["operation"], 0)
            self.assertEqual({row[1] for row in rows}, {country})
            countries.add(country)
            actual.extend(rows)
        self.assertEqual(countries, {"DE", "GB", "US"})
        self.assertEqual(Counter(map(tuple, actual)), Counter(map(tuple, expected)))
        counts = {
            "rows": 12,
            "columns": 4,
            "groups": 3,
            "output_files": len(chunks),
            "output_csv_bytes": sum(chunk["csv_bytes"] for chunk in chunks),
        }
        for key, value in counts.items():
            self.assertEqual(report[key], value)
            self.assertEqual(job["analysis"][key], value)

    def test_composed_job_and_cli_replay(self):
        cap = 75
        pipeline = chopper.Pipeline().then(chopper.partition(["country"]))
        pipeline = pipeline.then(chopper.shuffle())
        job = chopper.Job({**self.settings, "limits": {"bytes": cap}}, pipeline=pipeline)
        report = job.run()
        self.assertEqual(Path(report["manifest_path"]), Path("output/manifest.jsonl"))
        self.verify_capped_result(report["manifest_path"], report, cap)

        saved = Path("recipes/job.json")
        saved.parent.mkdir()
        chopper.Job({**job.to_dict(), "output": "replayed"}).save(saved)
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["version"], 1)
        self.assert_job_error("config_write", lambda: job.save(saved))
        cli = subprocess.run(
            [BINARY, "run", "--config", saved, "--yes", "--summary"],
            check=False, capture_output=True, encoding="utf-8", timeout=60,
        )
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.verify_capped_result("replayed/manifest.jsonl", json.loads(cli.stdout), cap)

    def test_pipeline_reuse_keeps_operation_order_and_owns_its_selectors(self):
        columns = ["0", 0]
        groups = [{"name": "a", "percent": "70"}, {"name": "b", "percent": "30"}]
        prefix = chopper.Pipeline().then(chopper.partition(columns))
        tail = chopper.Pipeline().then(chopper.assign(groups, strata=(1,)))
        tail = tail.then(chopper.assign_probabilistic(groups)).then(chopper.shuffle("auto"))
        balanced = prefix.then(tail).then(chopper.balanced(2))
        interleaved = prefix.then(chopper.interleaved(2))

        columns[0] = "different"
        groups[0]["name"] = "changed"
        expected_part = {"type": "partition", "columns": ["0", 0]}
        self.assertEqual(chopper.Job(self.settings, pipeline=prefix).to_dict()["operations"],
                         [expected_part])
        self.assertEqual(
            chopper.Job(self.settings, pipeline=interleaved).to_dict()["operations"],
            [expected_part, {"type": "interleaved", "files": 2}],
        )
        composed = chopper.Job(self.settings, pipeline=balanced)
        operations = composed.to_dict()["operations"]
        self.assertEqual([operation["type"] for operation in operations], [
            "partition", "assign", "assign_probabilistic", "shuffle", "balanced",
        ])
        self.assertEqual(operations[1]["groups"][0]["name"], "a")
        self.assertEqual(operations[1]["strata"], [1])
        composed.validate()
        composed.save("six-helpers.json")
        self.assertEqual(chopper.Job.load("six-helpers.json").to_dict(), composed.to_dict())

    def test_numeric_name_differs_from_index_in_loaded_zip_job(self):
        with ZipFile("source.zip", "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("records.csv", "name,0\nall,GB\nall,DE\nall,GB\n")
        settings = {"input": "source.zip", "zip_member": "records.csv", "output": "named"}
        Path("configs").mkdir()
        pipeline = chopper.Pipeline().then(chopper.partition(["0"]))
        chopper.Job(settings, pipeline=pipeline).save("configs/zip-job.json")
        named = chopper.Job.load("configs/zip-job.json").run()
        indexed = chopper.run({**settings, "output": "indexed", "operations": [
            {"type": "partition", "columns": [0]},
        ]})
        self.assertEqual(named["rows"], indexed["rows"])
        self.assertEqual(named["groups"], 2)
        self.assertEqual(indexed["groups"], 1)

    def assert_job_error(self, code, action, *, path=None):
        with self.assertRaises(chopper.ChopperError) as failed:
            action()
        self.assertEqual(failed.exception.code, code)
        self.assertTrue(str(failed.exception))
        if path is not None:
            self.assertEqual(failed.exception.path, path)

    def test_validation_and_analysis_do_not_publish_and_run_reads_current_input(self):
        settings = {**self.settings, "input": "future.csv", "resources": {"temp_dir": "job-temp"},
                    "operations": [{"type": "partition", "columns": ["country"]}]}
        Path("job-temp").mkdir()
        self.assertIsNone(chopper.validate(settings))
        self.assertFalse(Path("future.csv").exists())
        self.assertFalse(Path("output").exists())
        self.assertEqual(list(Path("job-temp").iterdir()), [])

        shutil.copyfile("customers.csv", "future.csv")
        job = chopper.Job(settings)
        profile = job.analyze()
        self.assertEqual((profile["rows"], profile["columns"]), (12, 4))
        self.assertEqual(profile["header"], ["id", "country", "segment", "note"])
        country = next(column for column in profile["column_values"] if column["column"] == 1)
        self.assertEqual(country["distinct"], 3)
        self.assertFalse(Path("output").exists())
        with open("future.csv", "a", encoding="utf-8", newline="") as file:
            csv.writer(file).writerow([13, "CA", "new", "new input after Analyze"])
        result = job.run()
        self.assertEqual((result["rows"], result["groups"]), (13, 4))
        self.assertEqual(list(Path("job-temp").iterdir()), [])

    def test_invalid_forms_share_codes_and_failed_runs_preserve_destinations(self):
        invalid = {**self.settings, "operations": [{"type": "balanced", "files": 0}]}
        composed = chopper.Job(self.settings, pipeline=chopper.Pipeline().then(chopper.balanced(0)))
        Path("invalid.json").write_text(json.dumps(invalid), encoding="utf-8")
        for job in (chopper.Job(invalid), composed, chopper.Job.load("invalid.json")):
            for action in (job.validate, job.analyze, job.run):
                self.assert_job_error("invalid_config", action, path="/operations/0/files")

        wrong_type = {**self.settings, "operations": [{"type": "balanced", "files": "2"}]}
        Path("wrong-type.json").write_text(json.dumps(wrong_type), encoding="utf-8")
        for action in (lambda: chopper.Job(wrong_type), lambda: chopper.Job.load("wrong-type.json")):
            self.assert_job_error("json_schema", action)
        self.assert_job_error("json_syntax", lambda: chopper.Job.from_json("{"))
        self.assert_job_error("config_read", lambda: chopper.Job.load("missing-job.json"))

        unicode_job = {**self.settings, "input_dialect": {"comment_prefix": "é" * 180_000}}
        Path("unicode.json").write_text(json.dumps(unicode_job, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(chopper.Job(unicode_job).to_dict(), chopper.Job.load("unicode.json").to_dict())
        for invalid_job in ({**self.settings, "limits": {"bytes": float("nan")}},
                            {**self.settings, "output": "\ud800"}):
            Path("invalid.json").write_text(json.dumps(invalid_job), encoding="utf-8")
            for action in (lambda: chopper.Job(invalid_job), lambda: chopper.Job.load("invalid.json")):
                self.assert_job_error("json_syntax", action)

        formula = chopper.Job({**self.settings, "calculated_columns": [{"name": "bad", "expression": "1+"}]})
        for action in (formula.validate, formula.analyze, formula.run):
            self.assert_job_error("invalid_config", action, path="/calculated_columns/0/expression")

        destination = Path("output")
        destination.mkdir()
        keep = destination / "keep.txt"
        keep.write_text("previous result", encoding="utf-8")
        self.assert_job_error("destination", lambda: chopper.run(self.settings))
        self.assertEqual(set(destination.iterdir()), {keep})
        self.assertEqual(keep.read_text(encoding="utf-8"), "previous result")
        self.assert_job_error("record_limit", lambda: chopper.run({
            **self.settings, "output": "cap-too-small", "limits": {"bytes": 35},
        }))
        self.assertFalse(Path("cap-too-small").exists())

    def large_job(self, directory, blocks):
        root = Path(directory)
        root.mkdir()
        (root / "temp").mkdir()
        block = (b"1,US," + b"x" * 120 + b"\n") * 1024
        with (root / "input.csv").open("wb") as source:
            source.write(b"id,country,note\n")
            for _ in range(blocks):
                source.write(block)
        return chopper.Job({
            "input": str(root / "input.csv"), "output": str(root / "output"),
            "resources": {
                "memory_mb": 64, "workers": 1, "max_record_bytes": 1024 * 1024,
                "temp_dir": str(root / "temp"),
            },
            "operations": [{"type": "partition", "columns": ["country"]}],
        })

    def progress_until(self, control, future, predicate):
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            progress = control.progress()
            if predicate(progress):
                return progress
            if future.done():
                self.fail(f"Job finished before expected progress: {future.result()}")
            time.sleep(0.001)
        control.cancel()
        self.fail(f"expected progress before deadline: {control.progress()}")

    def test_analyze_releases_gil_for_progress_and_cancellation(self):
        job = self.large_job("analyzing", 256)
        control = chopper.ExecutionControl()
        with ThreadPoolExecutor() as pool:
            future = pool.submit(job.analyze, control)
            progress = self.progress_until(
                control, future, lambda state: state["phase"] == "Profiling all input records",
            )
            self.assertGreater(progress["rows"], 0)
            self.assertEqual(progress["temp_bytes"], 0)
            control.cancel()
            self.assert_job_error("cancelled", lambda: future.result(timeout=60))
        self.assertFalse(Path("analyzing/output").exists())
        self.assertEqual(list(Path("analyzing/temp").iterdir()), [])

    def test_cancellation_requested_before_execution(self):
        job = chopper.Job(self.settings)
        for action in (job.analyze, job.run):
            with self.subTest(action=action.__name__):
                control = chopper.ExecutionControl()
                control.cancel()
                self.assert_job_error("cancelled", lambda: action(control))
                self.assertEqual(
                    control.progress(), {"phase": "Cancelled", "rows": 0, "temp_bytes": 0},
                )
                self.assertFalse(Path("output").exists())

    def test_cancelling_run_cleans_its_job_while_another_publishes(self):
        cancelled = self.large_job("cancelled", 256)
        survivor = self.large_job("survivor", 512)
        cancel_control = chopper.ExecutionControl()
        survivor_control = chopper.ExecutionControl()
        with ThreadPoolExecutor(max_workers=2) as pool:
            survivor_future = pool.submit(survivor.run, survivor_control)
            cancel_future = pool.submit(cancelled.run, cancel_control)
            for control, future in [(survivor_control, survivor_future), (cancel_control, cancel_future)]:
                self.progress_until(
                    control, future,
                    lambda state: state["phase"] == "Reading and validating CSV"
                    and state["rows"] > 0 and state["temp_bytes"] > 0,
                )
            cancel_control.cancel()
            self.assert_job_error("cancelled", lambda: cancel_future.result(timeout=60))
            cancelled_root = Path("cancelled")
            self.assertEqual({path.name for path in cancelled_root.iterdir()}, {"input.csv", "temp"})
            self.assertEqual(list((cancelled_root / "temp").iterdir()), [])

            completed = self.progress_until(survivor_control, survivor_future,
                                            lambda state: state["phase"] == "Complete")
            self.assertEqual(completed["rows"], 512 * 1024)
            survivor_control.cancel()
            report = survivor_future.result(timeout=60)
        self.assertEqual(report["rows"], 512 * 1024)
        self.assertTrue(Path(report["manifest_path"]).is_file())
        self.assertEqual(list(Path("survivor/temp").iterdir()), [])
        self.assert_job_error("control_in_use", lambda: survivor.analyze(survivor_control))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path, help="Native chopper executable")
    args, unittest_args = parser.parse_known_args()
    BINARY = args.binary.resolve(strict=True)
    unittest.main(argv=[__file__, *unittest_args])
