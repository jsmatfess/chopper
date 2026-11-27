"""Exercise Chopper from a fresh wheel install and a native CLI build."""

import argparse
from collections import Counter, UserDict
from concurrent.futures import ThreadPoolExecutor
import csv
from importlib.metadata import version
from importlib.resources import files
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

    def test_typed_report_properties_and_json_snapshots(self):
        self.assertTrue(files(chopper).joinpath("py.typed").is_file())
        job = chopper.Job(self.settings)
        inspection = job.inspect()
        self.assertEqual(inspection.columns, 4)
        self.assertEqual(inspection.header, ["id", "country", "segment", "note"])
        self.assertFalse(inspection.input_is_zip)
        self.assertEqual(inspection.preview, [])
        self.assertEqual(inspection.preview_row_numbers, [])
        self.assertNotIn("preview", inspection.to_dict())
        preview = job.preview()
        self.assertEqual(preview.preview_row_numbers, list(range(1, 9)))
        self.assertEqual(len(preview.preview), 8)
        detected = job.detect_dialect()
        self.assertEqual(detected.settings["delimiter"], ",")
        self.assertGreater(detected.sample_bytes, 0)

        analysis = job.analyze()
        self.assertEqual((analysis.rows, analysis.columns), (12, 4))
        with self.assertRaises(AttributeError):
            analysis.rows = 0
        snapshot = analysis.to_dict()
        self.assertEqual(snapshot, dict(analysis))
        snapshot["header"][0] = "changed"
        self.assertEqual(analysis.header[0], "id")
        self.assertEqual(analysis["rows"], analysis.rows)

        control = chopper.ExecutionControl()
        progress = control.progress()
        self.assertEqual((progress.rows, progress.temp_bytes), (0, 0))
        self.assertEqual(progress.phase, progress["phase"])
        result = job.run(control)
        self.assertEqual(result.manifest_path, Path("output/manifest.jsonl"))
        self.assertTrue(result.manifest_path.is_file())
        self.assertIsInstance(result["manifest_path"], str)
        self.assertEqual(Path(result["manifest_path"]), result.manifest_path)
        self.assertEqual(json.loads(json.dumps(result.to_dict())), dict(result))
        with result.outputs() as manifest:
            header = manifest.header
            self.assertEqual(header.output_files, result.output_files)
            entry, = manifest
            self.assertEqual(entry.rows, result.rows)
            self.assertEqual(entry.path, entry["path"])
            self.assertEqual(header.to_dict(), dict(header))
            self.assertEqual(entry.to_dict(), dict(entry))

    def test_jobs_accept_path_objects_in_mapping_settings(self):
        source = Path("customers.csv")
        destination = Path("output")
        temp_dir = Path("temporary")
        temp_dir.mkdir()
        settings = UserDict({
            "input": source,
            "output": destination,
            "resources": UserDict({"temp_dir": temp_dir}),
        })
        job = chopper.Job(settings)
        job.save(Path("job.json"))
        saved = chopper.Job.load(Path("job.json"))
        self.assertEqual(saved.to_dict()["input"], str(source))
        self.assertEqual(saved.to_dict()["output"], str(destination))
        self.assertEqual(saved.to_dict()["resources"]["temp_dir"], str(temp_dir))
        self.assertIs(settings["input"], source)
        self.assertIs(settings["resources"]["temp_dir"], temp_dir)
        self.assertEqual(chopper.inspect(settings).columns, 4)
        settings["resources"]["temp_dir"] = str(temp_dir)
        self.assertEqual(chopper.Job(settings).to_dict(), saved.to_dict())
        self.assertEqual(saved.run().manifest_path, destination / "manifest.jsonl")

    def test_inspect_and_detect_a_source_only_job(self):
        content = "0\tsegment\tsegment\r\n" + "1\tnew\treturning\r\n" * 10
        sample = b"\xff\xfe" + content.encode("utf-16le")
        with ZipFile("records.zip", "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("nested/records.csv", sample)
            archive.writestr("notes.txt", "Choose the CSV member with zip_member.")
        settings = {"input": "records.zip", "zip_member": "nested/records.csv"}
        suggested = chopper.detect_dialect(settings)
        self.assertEqual(suggested["delimiter_status"], "detected")
        self.assertEqual(suggested["sample_bytes"], len(sample))
        self.assertEqual(suggested["settings"]["encoding"], "utf-16le")
        self.assertEqual(suggested["settings"]["delimiter"], "\t")
        self.assertEqual(suggested["settings"]["line_ending"], "crlf")
        self.assertTrue(suggested["settings"]["bom"])

        job = chopper.Job({**settings, "input_csv": suggested["settings"]})
        columns = job.inspect()
        self.assertTrue(columns["input_is_zip"])
        self.assertEqual(list(columns.iter_columns()),
                         [(0, "0"), (1, "segment"), (2, "segment")])
        self.assertEqual(list(chopper.iter_columns(columns)),
                         [(0, "0"), (1, "segment"), (2, "segment")])
        preview = chopper.preview(job.to_dict())
        self.assertEqual(preview["preview"], [["1", "new", "returning"]] * 8)
        self.assertEqual(preview["preview_row_numbers"], list(range(1, 9)))
        headerless = {
            **settings, "input_csv": {**suggested["settings"], "headers": False},
        }
        self.assertEqual(list(chopper.inspect(headerless).iter_columns()),
                         [(0, None), (1, None), (2, None)])
        self.assertIn("UPPER", dict(chopper.formula_functions()))
        self.assertEqual({path.name for path in Path().iterdir()}, {"customers.csv", "records.zip"})

    def test_calculated_columns_are_saved_and_can_partition_output(self):
        job = chopper.Job({
            **self.settings,
            "calculated_columns": [
                {"name": "label", "expression": "LOWER([country])"},
                {"name": "double_id", "expression": "NUMBER([id]) * 2"},
            ],
        }, pipeline=chopper.Pipeline().then(chopper.partition(["label"])))
        job.validate()
        job.save("formulas.json")
        saved = chopper.Job.load("formulas.json")
        self.assertEqual(saved.to_dict(), job.to_dict())
        result = saved.run()
        self.assertEqual((result["rows"], result["groups"]), (12, 3))
        with chopper.open_manifest(result["manifest_path"]) as manifest:
            for entry in manifest:
                label, = entry["lineage"][0]["values"]
                header, *rows = read_csv(Path("output", entry["path"]))
                self.assertEqual(header[-2:], ["label", "double_id"])
                self.assertTrue(rows)
                for row in rows:
                    self.assertEqual(row[4:], [row[1].lower(), str(int(row[0]) * 2)])
                    self.assertEqual(row[4], label)

    def test_composed_formulas_run_on_headerless_records(self):
        f = chopper.functions
        Path("records.csv").write_text("3,us\n7,gb\n1,\n", encoding="utf-8")
        settings = {
            **self.settings,
            "input": "records.csv",
            "input_csv": {"headers": False},
            "output_csv": {"headers": False},
        }
        number = f.number(chopper.col(0))
        column = chopper.col(1)
        with self.assertRaisesRegex(TypeError, "truth value"):
            bool(f.is_blank(column))
        condition = ~(chopper.lit(False) | True) & True
        self.assertEqual(str(condition), "NOT (FALSE OR TRUE) AND TRUE")
        self.assertEqual(chopper.lit(False).or_(True).not_().and_(True), condition)
        definitions = {
            "score": (10 - number) * chopper.parse("1 + 2") + 8 / (number + 1),
            "label": f.if_else(
                ~(f.is_blank(column) | f.is_null(column)) & f.is_text(column),
                f.concat(f.upper(column), ' "quoted"'),
                "missing",
            ),
            "tail": f.coalesce(None, f.substring(chopper.col("label"), 1), "fallback"),
            "raw": "lOwEr($1)",
        }
        job = chopper.Job(settings, calculated_columns=definitions)
        self.assertNotIn("calculated_columns", settings)
        job.validate()
        job.save("composed.json")
        saved = chopper.Job.load("composed.json")
        self.assertEqual(saved.to_dict(), job.to_dict())
        self.assertEqual(saved.to_dict()["calculated_columns"], [
            {"name": name, "expression": str(expression)}
            for name, expression in definitions.items()
        ])

        result = saved.run()
        with chopper.open_manifest(result["manifest_path"]) as manifest:
            entry, = manifest
        self.assertEqual(read_csv(Path("output", entry["path"])), [
            ["3", "us", "23", 'US "quoted"', 'S "quoted"', "us"],
            ["7", "gb", "10", 'GB "quoted"', 'B "quoted"', "gb"],
            ["1", "", "31", "missing", "issing", ""],
        ])

    def test_long_arithmetic_chains_run_and_nested_arithmetic_keeps_grouping(self):
        f = chopper.functions
        values = [str(value) for value in range(1, 65)]
        Path("numbers.csv").write_text(",".join(values) + "\n", encoding="utf-8")
        total = f.number(chopper.col(0))
        for index in range(1, len(values)):
            total += f.number(chopper.col(index))
        settings = {
            **self.settings,
            "input": "numbers.csv",
            "input_csv": {"headers": False},
            "output_csv": {"headers": False},
        }
        job = chopper.Job(settings, calculated_columns={
            "total": total,
            "difference": chopper.lit(15) - (chopper.lit(6) - 2),
            "ratio": chopper.lit(32) / (chopper.lit(8) / 2),
            "rounded": chopper.lit(1e16) + (chopper.lit(-1e16) + 1),
        })

        result = job.run()
        with chopper.open_manifest(result["manifest_path"]) as manifest:
            entry, = manifest
        self.assertEqual(read_csv(Path("output", entry["path"])), [
            [*values, "2080", "11", "8", "0"],
        ])
        self.assertEqual(chopper.parse(str(total)), total)

    def test_formula_column_names_and_positions_remain_distinct(self):
        f = chopper.functions
        Path("records.csv").write_text("id,0,side]\n3,7,western\n", encoding="utf-8")
        pipeline = chopper.Pipeline().then(chopper.partition(["choice"]))
        job = chopper.Job(
            {**self.settings, "input": "records.csv"},
            pipeline=pipeline,
            calculated_columns={
                "named": f.number(chopper.col("0")),
                "positional": f.number(chopper.col(0)),
                "joined": f.concat_ws(":", chopper.col("side]"), None, "", "tip", True, True),
                "choice": f.ifs((False, "wrong"), (True, "middle"), fallback="last"),
            },
        )
        result = job.run()
        with chopper.open_manifest(result["manifest_path"]) as manifest:
            entry, = manifest
        self.assertEqual(read_csv(Path("output", entry["path"])), [
            ["id", "0", "side]", "named", "positional", "joined", "choice"],
            ["3", "7", "western", "7", "3", "western:tip", "middle"],
        ])

    def test_formula_expression_builders_validate_inputs(self):
        f = chopper.functions
        expected = {
            "if_else" if name == "IF" else name.lower()
            for name, _ in chopper.formula_functions()
        }
        self.assertEqual(set(f.__all__), expected)
        self.assertEqual(chopper.col("a]b").as_str(), "[a]]b]")
        self.assertEqual(str(chopper.lit('a"b')), '"a""b"')
        self.assertEqual(str(f.round(2.5)), "ROUND(2.5)")
        self.assertEqual(str(f.round(2.5, None)), "ROUND(2.5, NULL)")
        with self.assertRaises(ValueError):
            chopper.parse("1 +")
        with self.assertRaises(TypeError):
            chopper.col(True)
        for index in (-1, 2 ** 128):
            with self.subTest(index=index), self.assertRaises(ValueError):
                chopper.col(index)
        for value in (float("nan"), float("inf"), 2 ** 1024):
            with self.subTest(value=value), self.assertRaises(ValueError):
                chopper.lit(value)
        with self.assertRaisesRegex(TypeError, "supply calculated_columns"):
            chopper.Job({**self.settings, "calculated_columns": []}, calculated_columns={})

    def test_stream_a_published_manifest(self):
        for mode in ("none", "gzip", "zip"):
            with self.subTest(compression=mode):
                destination = Path(f"manifest-{mode}")
                report = chopper.run({
                    **self.settings, "output": str(destination), "compression": mode,
                    "operations": [{"type": "partition", "columns": ["country"]}],
                })
                path = Path(report["manifest_path"])
                with chopper.open_manifest(path) as reader:
                    self.assertIsInstance(reader, chopper.ManifestReader)
                    self.assertEqual(reader.header["input_header"], ["id", "country", "segment", "note"])
                    self.assertEqual(reader.header["compression"], mode)
                    entries = list(reader)
                self.assertEqual(len(entries), report["output_files"])
                self.assertEqual(sum(entry["rows"] for entry in entries), report["rows"])
                self.assertEqual(sum(entry["csv_bytes"] for entry in entries), report["output_csv_bytes"])
                names = {entry["path"] for entry in entries}
                if mode == "zip":
                    with ZipFile(destination / "outputs.zip") as archive:
                        self.assertEqual(names | {"manifest.jsonl"}, set(archive.namelist()))
                        self.assertEqual(archive.read("manifest.jsonl"), path.read_bytes())
                else:
                    self.assertEqual(names, {file.name for file in destination.iterdir()} - {path.name})

                with chopper.open_manifest(path) as reader:
                    self.assertEqual(next(reader), entries[0])
                self.assertIsNone(next(reader, None))
                self.assert_job_error("manifest_limit", lambda: chopper.open_manifest(path, max_record_bytes=1))

        damaged = Path("damaged.jsonl")
        with path.open("rb") as source:
            damaged.write_bytes(source.readline() + b"{\n")
        with chopper.open_manifest(damaged) as reader:
            with self.assertRaises(chopper.ChopperError) as failed:
                next(reader)
            self.assertEqual(failed.exception.code, "manifest_format")
            self.assertEqual(failed.exception.line, 2)
            self.assertIsNone(next(reader, None))

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
