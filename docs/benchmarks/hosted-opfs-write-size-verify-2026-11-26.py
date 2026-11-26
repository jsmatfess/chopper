"""Verify paired complete-Run receipts after the harness has checked every output."""
import json
import statistics
import sys
from pathlib import Path

config, path, summary = map(Path, sys.argv[1:])
options = json.loads(config.read_text())
records = [json.loads(line) for line in path.read_text().splitlines()]
assert {row["kind"] for row in records} == {"environment", "fixture", "measurement"}
env, = [row for row in records if row["kind"] == "environment"]
fixtures = {row["name"]: row for row in records if row["kind"] == "fixture"}
arms = list(options["engines"])
assert len(arms) == 2 and arms[0] == "baseline"
assert set(fixtures) == {case["name"] for case in options["cases"]}
assert env["assets"][arms[0]] == env["assets"][arms[1]]
assert env["assets"]["worker:" + arms[0]] != env["assets"]["worker:" + arms[1]]
fields = ("temporary_bytes_written", "temporary_bytes_read", "peak_workspace_reserved_bytes")
result = {}
for case in options["cases"]:
    name = case["name"]
    fixture = fixtures[name]
    rows = [row for row in records if row.get("cell") == name]
    pairs = range(-int(bool(case.get("warmup"))), case["pairs"])
    assert len(rows) == 2 * len(pairs)
    savings = []
    resource = []
    for pair in pairs:
        members = [row for row in rows if row["pair"] == pair]
        assert [row["variant"] for row in members] == (arms if pair % 2 == 0 else arms[::-1])
        base, candidate = sorted(members, key=lambda row: arms.index(row["variant"]))
        same_route = case["expect"][arms[1]] == "snapshot"
        for row in members:
            assert row["physical_plan"] == case["expect"][row["variant"]]
            assert row["checks"]["rows"] == fixture["rows"]
            assert row["checks"]["groups"] == fixture["keys"]
            assert row["storage"]["workspace_bytes_before_cleanup"] == 0
            assert row["storage"]["workspace_bytes_after_cleanup"] == 0
        for key in ("effective_memory_bytes", "sort", "memory_plan"):
            assert base[key] == candidate[key], (name, key, base[key], candidate[key])
        for key in ("files", "rows", "groups", "csv_bytes", "logical_digest", "marker"):
            assert base["checks"][key] == candidate["checks"][key], (name, key)
        if "min_runs" in case:
            assert base["sort"]["sort_runs"] >= case["min_runs"]
        base_write, candidate_write = (row["bridge"]["write"] for row in (base, candidate))
        assert base_write["bytes"] == candidate_write["bytes"]
        # A permutation can shift the row boundaries at which buffering flushes.
        assert abs(base_write["calls"] - candidate_write["calls"]) <= max(1, base_write["calls"] / 1000)
        base_export, candidate_export = (row["bridge"]["destination_write"] for row in (base, candidate))
        assert abs(base_export["calls"] - candidate_export["calls"]) <= max(1, base_export["calls"] / 1000)
        # Includes the manifest's run-specific timing numbers.
        assert abs(base_export["bytes"] - candidate_export["bytes"]) <= 128
        measurements = [row["measurements"] for row in (base, candidate)]
        b, c = measurements
        if same_route:
            # Each snapshot chunk seeks and buffers reads. Independent shuffled
            # rows can move its boundary and change buffer overread.
            read_field = "temporary_bytes_read"
            assert {k: v for k, v in b.items() if k != read_field} == {k: v for k, v in c.items() if k != read_field}
            assert abs(b[read_field] - c[read_field]) <= max(8192, fixture["bytes"] / 100)
            # Independently shuffled final merges can free a spill during
            # different snapshot writes. Require matching cumulative writes
            # above and bound variation in the instantaneous logical peak by
            # one 1 MiB transfer slot.
            assert abs(base["storage"]["workspace_peak_bytes"] - candidate["storage"]["workspace_peak_bytes"]) <= 1024 * 1024
            assert abs(base["storage"]["profiled_destination_bytes"] - candidate["storage"]["profiled_destination_bytes"]) <= 128
        else:
            for key in fields[:2]:
                # Direct publication retains a different catalog. Its metadata
                # bytes count in the same ledger as the removed CSV snapshot.
                assert b[key] - c[key] >= base["checks"]["csv_bytes"] * 0.99, (name, key)
            assert c[fields[2]] <= b[fields[2]] + 512 * 1024
        if pair >= 0:
            savings.append(base["seconds"] - candidate["seconds"])
            resource.append({key: b[key]-c[key] for key in fields})
    med = statistics.median(savings)
    timing_pass = (
        med >= case["min_median_savings"] and min(savings) > 0
        if "min_median_savings" in case
        else abs(med) <= case["median_tolerance"] and min(savings) >= -case["max_cost"]
    )
    timed = [row for row in rows if row["pair"] >= 0]
    result[name] = {
        "input_bytes": fixture["bytes"], "pairs": case["pairs"],
        "seconds": {arm: [row["seconds"] for row in timed if row["variant"] == arm] for arm in arms},
        "savings_seconds": savings, "median_saved_seconds": med,
        "timing_pass": timing_pass, "resource_deltas": resource,
    }
with summary.open("x") as out:
    json.dump(result, out, indent=2)
    out.write("\n")
print(json.dumps(result))
if not all(cell["timing_pass"] for cell in result.values()):
    raise SystemExit("Complete-job time gate failed")
