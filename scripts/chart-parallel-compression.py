#!/usr/bin/env python3
"""Update the live investigation report from verified whole-job JSONL samples."""
import argparse
from collections import defaultdict
from html import escape
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
}
SHAPES = {"single":"One file", "many":"Eight files", "hundreds":"256 files", "heavy":"Partition → Balanced"}


def samples(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    fixtures = {row["name"]:row for row in rows if row["kind"] == "fixture"}
    by_cell = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row["kind"] == "run" and row.get("status") == "verified":
            by_cell[(row["fixture"], row["shape"], row["codec"])][row["label"]].append(row)
    return fixtures, by_cell


def figure(title, paths):
    result = [f"<section><h2>{escape(title)}</h2>"]
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
            label = f"{mib:.0f} MiB · {SHAPES.get(shape,shape)} · {codec.upper()}"
            maximum = max(seconds.values()) * 1.04
            result.append(f'<figure class="chart"><figcaption>{escape(label)}</figcaption>')
            base = "serial" if "serial" in arms else "baseline" if "baseline" in arms else "blocks"
            base_times = {row["repeat"]:row["seconds"] for row in arms[base]}
            for key, terms in arms.items():
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
    result.append("</section>")
    return "\n".join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--panel", action="append", nargs="+", metavar=("TITLE","JSONL"), required=True)
    args = parser.parse_args()
    start, end = "<!-- CHARTS START -->", "<!-- CHARTS END -->"
    current = args.report.read_text()
    assert current.count(start) == current.count(end) == 1
    before, after = current.split(start)[0], current.split(end)[1]
    sections = "\n".join(figure(title, list(map(Path, paths))) for title,*paths in args.panel)
    temporary = args.report.with_suffix(".tmp")
    temporary.write_text(before + start + "\n" + sections + "\n" + end + after)
    temporary.replace(args.report)


if __name__ == "__main__":
    main()
