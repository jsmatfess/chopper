"""Reconcile a native Chopper result directory using its v1 manifest."""

import argparse
from contextlib import ExitStack
import csv
import gzip
import json
from pathlib import Path
import sys
import zipfile
import zlib


MANIFEST = "manifest.jsonl"
ARCHIVE = "outputs.zip"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def count(record, field):
    value = record[field]
    require(type(value) is int and 0 <= value < 2**64, f"invalid {field}")
    return value


def result_file(directory, name):
    path = directory / name
    require(not path.is_symlink() and path.is_file(), f"missing regular file: {name}")
    return path


def invalid_json_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def records(manifest, embedded):
    for number, line in enumerate(manifest, 1):
        if embedded is not None:
            require(embedded.read(len(line)) == line, "ZIP manifest differs from sidecar")
        record = json.loads(line.decode("utf-8"), parse_constant=invalid_json_constant)
        require(isinstance(record, dict), f"manifest line {number} must be an object")
        yield record
    require(embedded is None or not embedded.read(1), "ZIP manifest differs from sidecar")


def csv_counts(stream, dialect, have_header):
    byte_count = 0
    if dialect["bom"]:
        require(stream.read(3) == b"\xef\xbb\xbf", "missing UTF-8 BOM")
        byte_count = 3

    def lines():
        nonlocal byte_count
        for line in stream:
            byte_count += len(line)
            yield line.decode("utf-8")

    rows = csv.reader(lines(), delimiter=dialect["delimiter"], quotechar=dialect["quote"],
                      strict=True)
    if have_header:
        require(next(rows, None) is not None, "missing CSV header")
    row_count = sum(1 for _ in rows)
    return row_count, byte_count


def verify(directory):
    """Return reconciled row, output and CSV byte totals or raise an exception."""
    directory = Path(directory)
    with ExitStack() as stack:
        manifest = stack.enter_context(result_file(directory, MANIFEST).open("rb"))
        job = next(records(manifest, None), {})
        require(job.get("type") == "job", "manifest must start with a job record")
        require(count(job, "schema_version") == 1, "unsupported manifest schema_version")
        require(isinstance(job["application_version"], str) and job["application_version"],
                "invalid application_version")
        config, analysis = job["config"], job["analysis"]
        compression = config["compression"]
        require(compression in ("none", "gzip", "zip"), "unsupported output compression")
        dialect = config["output_csv"]
        encoding = dialect["encoding"]
        require(isinstance(encoding, str) and encoding.lower() == "utf-8"
                and dialect["escape"] is None,
                "this example requires UTF-8 and doubled-quote escaping")
        header = analysis["header"]
        require(header is None or isinstance(header, list)
                and all(isinstance(field, str) for field in header), "invalid header")
        for flag in ("headers", "bom"):
            require(type(dialect[flag]) is bool, f"invalid {flag}")
        have_header = dialect["headers"] and header is not None

        archive = None
        embedded = None
        if compression == "zip":
            archive = stack.enter_context(zipfile.ZipFile(result_file(directory, ARCHIVE)))
            members = archive.namelist()
            require(len(set(members)) == len(members), "duplicate ZIP member name")
            embedded = stack.enter_context(archive.open(MANIFEST))
            manifest.seek(0)
            output_records = records(manifest, embedded)
            next(output_records)  # Compare the job record too.
        else:
            output_records = records(manifest, None)

        seen = set()
        rows = csv_bytes = 0
        suffix = ".csv.gz" if compression == "gzip" else ".csv"
        for record in output_records:
            require(record.get("type") == "output", "expected an output record")
            name = record["path"]
            require(isinstance(name, str) and name.endswith(suffix)
                    and not any(c in name for c in '/\\:<>"|?*\x00'),
                    f"invalid output path: {name!r}")
            require(name not in seen, f"duplicate output path: {name}")
            seen.add(name)

            if archive is not None:
                info = archive.getinfo(name)
                stored = info.compress_size
                stream = archive.open(info)
            else:
                path = result_file(directory, name)
                stored = path.stat().st_size
                stream = gzip.open(path, "rb") if compression == "gzip" else path.open("rb")
            with stream:
                require(stored == count(record, "stored_bytes"), f"stored byte mismatch: {name}")
                output_rows, output_bytes = csv_counts(stream, dialect, have_header)
            require(output_bytes == count(record, "csv_bytes"), f"CSV byte mismatch: {name}")
            require(output_rows == count(record, "rows"), f"row count mismatch: {name}")
            rows += output_rows
            csv_bytes += output_bytes

        expected_names = {MANIFEST, ARCHIVE} if archive is not None else seen | {MANIFEST}
        require({path.name for path in directory.iterdir()} == expected_names,
                "result directory inventory differs from manifest")
        if archive is not None:
            require(set(members) == seen | {MANIFEST}, "ZIP inventory differs from manifest")
        totals = {"rows": rows, "output_files": len(seen), "output_csv_bytes": csv_bytes}
        for field, value in totals.items():
            require(value == count(analysis, field), f"job total mismatch: {field}")
        return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_directory", type=Path)
    args = parser.parse_args()
    csv.field_size_limit(2**31 - 1)
    try:
        print(json.dumps(verify(args.result_directory)))
    except (ValueError, TypeError, KeyError, OSError, EOFError, RuntimeError,
            csv.Error, zipfile.BadZipFile, zlib.error) as error:
        print(f"verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
