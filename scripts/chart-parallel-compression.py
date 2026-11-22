#!/usr/bin/env python3
"""Update the live investigation report from verified whole-job JSONL samples."""
import argparse
from collections import defaultdict
from html import escape
import hashlib
import json
from pathlib import Path
from statistics import median

LABELS = {
    "baseline": "Baseline",
    "blocks": "Parallel blocks",
    "across": "Parallel files",
    "serial": "One worker",
    "stream-zip": "Streamed ZIP",
    "auto": "Final Auto",
    "ordered": "One large member at a time",
    "gzip-input": "Chopper gzip input",
    "zip-input": "Chopper ZIP input",
    "plain-input": "Chopper plain input",
    "decode-first": "Parallel decode first",
}
SHAPES = {"single":"One file", "many":"Eight files", "hundreds":"256 files", "heavy":"Partition → Balanced", "capped":"1 MiB output cap"}


def samples(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    fixtures = {row["name"]:row for row in rows if row["kind"] == "fixture"}
    by_cell = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["kind"] == "run" and row.get("status") == "verified":
            by_cell[(row["fixture"], row["shape"], row["codec"])][row["label"]].append(row)
    return fixtures, by_cell


def figure(title, paths):
    result = [f"<details><summary>{escape(title)}</summary>"]
    table = []
    for path in paths:
        fixtures, cells = samples(path)
        for (size, shape, codec), arms in cells.items():
            if not arms or min(map(len, arms.values())) < 2:
                continue
            seconds = {key:median(t["seconds"] for t in terms) for key, terms in arms.items()}
            if len(seconds) < 2:
                continue
            mib = fixtures[size]["bytes"] / 2**20
            label = (
                f"{mib:.0f} MiB · Decode and publish"
                if codec == "input"
                else f"{mib:.0f} MiB · {SHAPES.get(shape, shape)} · {codec.upper()}"
            )
            maximum = max(seconds.values()) * 1.04
            result.append(f'<figure class="chart"><figcaption>{escape(label)}</figcaption>')
            base = next(
                (key for key in ("serial", "baseline", "blocks", "gzip-input", "auto") if key in arms),
                next(iter(arms)),
            )
            base_times = {row["repeat"]:row["seconds"] for row in arms[base]}
            for key in [base, *(arm for arm in arms if arm != base)]:
                terms = arms[key]
                label_arm = LABELS.get(key, key)
                value = seconds[key]
                style = ' baseline' if key == base else ''
                samples_s = [row["seconds"] for row in terms]
                result.append(f'<div class="series{style}"><span>{escape(label_arm)}</span>'
                    f'<meter min="0" max="{maximum:.8f}" value="{value:.8f}" aria-label="{escape(label_arm)} median seconds"></meter>'
                    f'<span>{value:.3f} s</span></div>')
                if key != base:
                    paired = [(base_times[row["repeat"]]-row["seconds"]) for row in terms if row["repeat"] in base_times]
                    table.append([label,f"{label_arm} vs {LABELS.get(base,base)}",f"{len(paired)}",
                        f"{median(paired):+.3f} s", f"{min(samples_s):.3f}–{max(samples_s):.3f} s"])
            result.append("</figure>")
    if table:
        result.append('<div class="table"><table><thead><tr><th scope="col">Workload</th><th scope="col">Comparison</th>'
            '<th scope="col">Pairs</th><th scope="col">Median seconds saved</th><th scope="col">Candidate range</th></tr></thead><tbody>')
        result.extend('<tr>'+''.join(f'<td>{escape(cell)}</td>' for cell in row)+'</tr>' for row in table)
        result.append('</tbody></table></div><p class="muted">Positive savings mean faster. Each bar starts at zero and shows the median of independently verified complete jobs. Scales differ by workload.</p>')
    result.append("</details>")
    return "\n".join(result)


def project(title, path, diagnostic):
    data = path.read_bytes()
    result = {
        "panel": title,
        "diagnostic": diagnostic,
        "local_raw_path": f"{path.parent.name}/{path.name}",
        "raw_sha256": hashlib.sha256(data).hexdigest(),
        "fixtures": [],
        "runs": [],
    }
    for number, raw in enumerate(data.splitlines(), 1):
        row = json.loads(raw)
        kind = row["kind"]
        if kind == "environment":
            keys = ("runtime", "browser", "channel", "platform", "cpu", "cpu_count",
                    "cache", "context", "timer", "timing_scope", "base_commit", "kernel",
                    "executable_sha256", "assets_sha256", "harness_sha256",
                    "workers_requested", "worker_request", "memory_requested", "rapidgzip_version",
                    "chopper_sha256", "rapidgzip_sha256")
            result[kind] = {key:row[key] for key in keys if key in row}
        elif kind == "fixture":
            keys = ("name", "bytes", "rows", "sha256", "gzip_bytes", "gzip_sha256",
                    "zip_bytes", "zip_sha256")
            result["fixtures"].append({key:row[key] for key in keys if key in row})
        elif kind == "run":
            keys = ("label", "codec", "fixture", "shape", "repeat", "status", "seconds",
                    "stored_bytes", "csv_bytes", "output_files", "workers",
                    "memory_budget_bytes", "cpu_user_seconds", "cpu_system_seconds",
                    "rss_peak_kib", "decoder_seconds", "temp_input_bytes", "job_sha256")
            run = {key:row[key] for key in keys if key in row}
            run["source_line"] = number
            measures = row.get("measurements") or (row.get("auto_plan") or {}).get("measurements", {})
            keys = ("temporary_bytes_written", "temporary_bytes_read", "peak_workspace_reserved_bytes",
                    "peak_writer_slots", "peak_deflate_workers")
            run["measurements"] = {key:measures[key] for key in keys if key in measures}
            result["runs"].append(run)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--panel", action="append", nargs="+", metavar=("TITLE","JSONL"), required=True)
    parser.add_argument("--diagnostic", action="append", nargs=2, metavar=("TITLE","JSONL"), default=[])
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    start, end = "<!-- CHARTS START -->", "<!-- CHARTS END -->"
    current = args.report.read_text(encoding="utf-8")
    assert current.count(start) == current.count(end) == 1
    before, after = current.split(start)[0], current.split(end)[1]
    sections = "\n".join(figure(title, list(map(Path, paths))) for title,*paths in args.panel)
    temporary = args.report.with_suffix(".tmp")
    temporary.write_text(
        before + start + '\n<section id="comparisons"><h2>Detailed timings</h2>\n'
        + sections + "\n</section>\n" + end + after,
        encoding="utf-8",
    )
    temporary.replace(args.report)
    if args.summary:
        panels = [project(title, Path(path), False) for title, *paths in args.panel for path in paths]
        panels.extend(project(title, Path(path), True) for title, path in args.diagnostic)
        summary = {"schema_version": 1, "kind": "reviewed-projection",
                   "raw_root": "scratch/parallel-compression", "panels": panels}
        args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
