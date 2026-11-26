import collections
import json
import sys
from pathlib import Path
from statistics import median

config = json.loads(Path(sys.argv[1]).read_text())
data = [json.loads(line) for line in Path(sys.argv[2]).read_text().splitlines()]
assert not any(row["kind"] == "failure" for row in data)
assert len([row for row in data if row["kind"] == "fixture"]) == len(config["cases"])
samples = {case["name"]: [] for case in config["cases"]}
for row in data:
    if row["kind"] == "measurement":
        samples[row["cell"]].append(row)
for case in config["cases"]:
    cell = case["name"]
    arms = case.get("variants", list(config["engines"]))
    pairs = range(-int(case.get("warmup", False)), case["pairs"])
    actual = collections.Counter((row["pair"], row["variant"]) for row in samples[cell])
    assert actual == collections.Counter((pair, arm) for pair in pairs for arm in arms)
    times = {arm: [] for arm in arms[1:]}
    for pair in pairs:
        runs = {row["variant"]: row for row in samples[cell] if row["pair"] == pair}
        baseline = runs["baseline"]
        for arm, row in runs.items():
            assert row["checks"]["rows"] == case["rows"]
            assert row["checks"]["groups"] == case["keys"]
            assert row["checks"]["logical_digest"] == baseline["checks"]["logical_digest"]
            assert row["checks"]["csv_bytes"] == baseline["checks"]["csv_bytes"]
            assert row["marker"]["status"] == "completed"
            assert row["storage"]["workspace_bytes_after_cleanup"] == 0
            expected = case.get("expect", {}).get(arm, "snapshot" if arm == "baseline" else "private_terminal")
            assert row["physical_plan"] == expected
            if not case.get("allowTopologyChange"):
                assert row["effective_memory_bytes"] == baseline["effective_memory_bytes"]
                assert row["sort"] == baseline["sort"]
            if arm != "baseline" and pair >= 0:
                times[arm].append(baseline["seconds"] - row["seconds"])
    for arm, values in times.items():
        print(f"{cell} {arm}: {len(values)} verified pairs, {median(values):+.3f} s saved ({min(values):+.3f} to {max(values):+.3f})")
