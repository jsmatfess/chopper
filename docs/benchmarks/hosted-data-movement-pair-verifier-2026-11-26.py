"""Evaluate the frozen paired timing and resource criteria after output readback."""
import json
import statistics
import sys
from pathlib import Path

config, receipts, summary = map(Path, sys.argv[1:])
options = json.loads(config.read_text())
data = [json.loads(line) for line in receipts.read_text().splitlines()]
env, = [row for row in data if row["kind"] == "environment"]
fixtures = {row["name"]: row for row in data if row["kind"] == "fixture"}
arms = list(options["engines"])
assert set(fixtures) == {case["name"] for case in options["cases"]}
assert {r["kind"] for r in data} == {"environment", "fixture", "measurement"}
assert arms[0] == "baseline" and len(arms) == 2
assert (env["assets"][arms[0]] == env["assets"][arms[1]]) == bool(options.get("engineWorkers"))
if options.get("engineWorkers"):
    assert env["assets"]["worker:"+arms[0]] != env["assets"]["worker:"+arms[1]]
results = {}
for case in options["cases"]:
    name = case["name"]
    fixture = fixtures[name]
    samples = [row for row in data if row.get("cell") == name]
    pairs = range(-int(bool(case.get("warmup"))), case["pairs"])
    assert len(samples) == 2 * len(pairs)
    seconds = {arm: [] for arm in arms}
    savings = []
    resource = []
    for pair in pairs:
        rows = [row for row in samples if row["pair"] == pair]
        assert [row["variant"] for row in rows] == (arms if pair % 2 == 0 else arms[::-1])
        before, after = sorted(rows, key=lambda row: arms.index(row["variant"]))
        for row in rows:
            assert row["storage"]["workspace_bytes_after_cleanup"] == 0
            assert row["storage"]["workspace_bytes_before_cleanup"] == 0
            assert row["checks"]["rows"] == case["rows"]
            assert row["sort"]["sort_runs"] >= case.get("min_runs", 0)
        for field in ("effective_memory_bytes", "sort", "memory_plan", "stages"):
            assert before[field] == after[field], (name, field, before[field], after[field])
        for field in ("rows", "groups", "files", "csv_bytes", "logical_digest", "marker"):
            assert before["checks"][field] == after["checks"][field], (name, field)
        if case["shape"] == "nested":
            assert before["checks"]["ordered_csv_sha256"] == after["checks"]["ordered_csv_sha256"]
        a, b = (row["measurements"] for row in (before, after))
        reads = a["temporary_bytes_read"] - b["temporary_bytes_read"]
        writes = a["temporary_bytes_written"] - b["temporary_bytes_written"]
        peak = a["peak_workspace_reserved_bytes"] - b["peak_workspace_reserved_bytes"]
        if case.get("pass_removed"):
            assert after["physical_plan"] == "private_terminal"
            assert min(reads,writes) >= before["checks"]["csv_bytes"] * 0.99, (name, reads, writes)
            assert peak >= -512 * 1024, (name, peak)
        elif case.get("fewer_scans"):
            assert reads >= fixture["bytes"]/2, (name, reads)
            assert writes >= -1024*1024 and peak >= -512*1024, (name, writes, peak)
        else:
            assert abs(reads) <= 1024*1024 and writes == 0 and peak == 0, (name, reads, writes, peak)
        for index, row in enumerate((before,after)):
            requests = row["bridge"].get("source_prefetch_request",{}).get("calls",0)
            assert bool(requests) == (index == 1 and bool(case.get("prefetch"))), (name, row["variant"], requests)
        if pair >= 0:
            savings.append(before["seconds"] - after["seconds"])
            resource.append({"temporary_read_saved":reads, "temporary_write_saved":writes, "working_peak_saved":peak})
            for row in rows:
                seconds[row["variant"]].append(row["seconds"])
    median = statistics.median(savings)
    timing_pass = (
        median >= case["min_saved"] and min(savings)>0
        if "min_saved" in case
        else abs(median)<=0.12 and min(savings)>=-0.25
    )
    results[name] = {"shape":case["shape"],"input_bytes":fixture["bytes"],"pairs":case["pairs"],
        "seconds":seconds,"savings_seconds":savings,"median_saved_seconds":median,"timing_pass":timing_pass,"resources":resource}
with summary.open('x') as out:
    json.dump(results,out,indent=2)
    out.write('\n')
print(json.dumps(results))
if not all(r["timing_pass"] for r in results.values()):
    raise SystemExit('Complete-Run timing gate missed')
