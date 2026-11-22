#!/usr/bin/env python3
"""Screen compressed-input costs and an external verified parallel gzip decoder."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import time
import zipfile


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case_root", type=Path)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("chopper", type=Path)
    parser.add_argument("rapidgzip", type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    root, fixture, engine, rapid = (path.resolve() for path in
                                     (args.case_root,args.fixture,args.chopper,args.rapidgzip))
    root.mkdir()
    records = root / "runs.jsonl"

    def record(value):
        with records.open("a", encoding="utf-8") as output:
            print(json.dumps(value, separators=(",",":")), file=output)

    gz, zipped = root / "input.csv.gz", root / "input.zip"
    with gz.open("xb") as gzip_file, fixture.open("rb") as original:
        with gzip.GzipFile(filename="", mode="wb", compresslevel=6, mtime=0, fileobj=gzip_file) as output:
            shutil.copyfileobj(original,output,1024*1024)
    with zipfile.ZipFile(zipped, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        output.write(fixture,"selected.csv")
    expected = digest(fixture)
    record({"kind":"environment","runtime":platform.platform(),
            "chopper_sha256":digest(engine),"rapidgzip_sha256":digest(rapid),
            "rapidgzip_version":subprocess.check_output([rapid,"--version"],text=True).strip(),
            "harness_sha256":digest(Path(__file__)),"cache":"warm/uncontrolled",
            "timing_scope":"Start at decoder or Chopper process launch through finished native publication. Input fixture preparation and verification excluded."})
    record({"kind":"fixture","name":"large","sha256":expected,"bytes":fixture.stat().st_size,
            "gzip_sha256":digest(gz),"gzip_bytes":gz.stat().st_size,
            "zip_sha256":digest(zipped),"zip_bytes":zipped.stat().st_size})
    arms = ["plain-input","gzip-input","zip-input","decode-first"]
    for repeat in range(args.repeats):
        order = arms if repeat % 2 == 0 else arms[::-1]
        for arm in order:
            case = root / f"{repeat}-{arm}"
            case.mkdir()
            source = {"plain-input":fixture,"gzip-input":gz,"zip-input":zipped}.get(arm,case/"decoded.csv")
            destination = case / "output"
            path = case / "job.json"
            path.write_text(json.dumps({"input":str(source),"output":str(destination),
                "compression":"none","resources":{"memory_mb":"auto","workers":0,"temp_dir":str(case)}})+"\n")
            row = {"kind":"run","fixture":"large","shape":"single","codec":"input",
                   "label":arm,"repeat":repeat,"job_sha256":digest(path)}
            try:
                with (case/"stderr.log").open("wb") as errors, (case/"analysis.json").open("wb") as output:
                    start=time.perf_counter()
                    if arm == "decode-first":
                        with source.open("xb") as temporary:
                            subprocess.run([rapid,"--verify","-P","4","-d","-c",gz],
                                           stdout=temporary,stderr=errors,check=True)
                        row["decoder_seconds"]=time.perf_counter()-start
                    subprocess.run([engine,"run","--config",path,"--yes"],stdout=output,stderr=errors,check=True)
                    row["seconds"]=time.perf_counter()-start
                assert digest(destination/"part-00000001.csv")==expected
                analysis=json.loads((case/"analysis.json").read_text())
                row.update(status="verified",output_sha256=expected,workers=analysis["workers"],
                           temp_input_bytes=source.stat().st_size if arm=="decode-first" else 0,
                           measurements=analysis["auto_plan"]["measurements"])
                shutil.rmtree(destination)
                if arm=="decode-first":
                    source.unlink()
            except BaseException as error:
                row.update(status="failed",error=repr(error))
                raise
            finally:
                record(row)
                print(arm,repeat,row.get("seconds"),row["status"],flush=True)


if __name__=="__main__":
    main()
