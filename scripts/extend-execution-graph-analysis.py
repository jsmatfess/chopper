"""One explicit precision extension, retaining every original matched sample."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile

from execution_graph_statistics import paired_bootstrap_upper95


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_cohort(plan_path, raw_path, report_path):
    analyzer = Path(__file__).with_name('analyze-execution-graph.py')
    subprocess.run([sys.executable, str(analyzer), plan_path, raw_path, str(report_path)],
                   check=True, stdout=subprocess.DEVNULL)
    located = [(index, json.loads(line))
               for index, line in enumerate(Path(raw_path).read_text().splitlines(), 1) if line.strip()]
    rows = [row for _, row in located]
    assert not any(row['kind'] == 'diagnostic' for row in rows), 'Diagnostic samples are ineligible'
    return {
        'plan': json.loads(Path(plan_path).read_text()),
        'rows': rows, 'located': located,
        'context': next(row for row in rows if row['kind'] == 'context'),
        'report': json.loads(report_path.read_text()),
        'plan_path': plan_path, 'raw_path': raw_path,
    }


def configuration(cohort, workload):
    jobs = [{k: v for k, v in row['job'].items() if k != 'output'}
            for row in cohort['rows'] if row['kind'] == 'attempt' and row['workload'] == workload]
    assert jobs
    return jobs[0]


def verify_extension(original, extension):
    assert original['report']['raw_sha256'] != extension['report']['raw_sha256'], 'Duplicate raw observations'
    # Fresh persistent blocks have fresh destination identities. Re-encoding an
    # old JSONL file cannot turn its admitted jobs into new observations.
    def jobs(cohort):
        return {row['job_sha256'] for row in cohort['rows'] if row['kind'] == 'attempt'}
    assert jobs(original).isdisjoint(jobs(extension)), 'Duplicate admitted jobs across cohorts'
    old, new = original['context'], extension['context']
    assert old['assets'] == new['assets'], 'Production build assets differ'
    assert old['harness_sha256'] == new['harness_sha256'], 'Measurement harness differs'
    assert old['environment'] == new['environment'], 'Browser/runtime/storage environment differs'
    def browsers(cohort):
        return {(row['executable'], row['sha256'], row['version'])
                for row in cohort['rows'] if row['kind'] == 'browser_identity'}
    assert browsers(original) == browsers(extension), 'Actual browser process identity differs'
    original_workloads = {w['id']: w for w in original['plan']['workloads']}
    for workload in extension['plan']['workloads']:
        key = workload['id']
        assert original_workloads.get(key) == workload, 'Declared workload differs'
        assert old['fixtures'][key] == new['fixtures'][key], 'Fixture identity differs'
        assert configuration(original, key) == configuration(extension, key), 'Unmatched configuration'
        digests = {row['ordered_artifact_sha256'] for cohort in (original, extension)
                   for row in cohort['rows'] if row['kind'] == 'verification' and row['workload'] == key}
        assert len(digests) == 1, 'Cross-cohort ordered artifact parity differs'


def extend_cell(original, extension):
    result = copy.deepcopy(original)
    baseline = original['disabled_seconds'] + extension['disabled_seconds']
    enabled = original['enabled_seconds'] + extension['enabled_seconds']
    assert len(baseline) == len(enabled) == 12, 'Exactly one six-block extension is supported'
    base_median, median = statistics.median(baseline), statistics.median(enabled)
    slowdown = median / base_median - 1
    upper = paired_bootstrap_upper95(baseline, enabled)
    result.update(
        n=12, disabled_seconds=baseline, enabled_seconds=enabled,
        disabled_median_seconds=base_median, enabled_median_seconds=median,
        disabled_range_seconds=[min(baseline), max(baseline)],
        enabled_range_seconds=[min(enabled), max(enabled)],
        disabled_mad_seconds=statistics.median(abs(value - base_median) for value in baseline),
        enabled_mad_seconds=statistics.median(abs(value - median) for value in enabled),
        paired_slowdowns=[value / base - 1 for value, base in zip(enabled, baseline)],
        median_slowdown=slowdown, paired_bootstrap_upper95_slowdown=upper,
        gate_pass=slowdown <= .05 and upper <= .05,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original_plan', 'original_raw', 'extension_plan', 'extension_raw', 'output'):
        parser.add_argument(name)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        original = read_cohort(args.original_plan, args.original_raw, Path(directory) / 'original.json')
        extension = read_cohort(args.extension_plan, args.extension_raw, Path(directory) / 'extension.json')
    verify_extension(original, extension)
    added = {(cell['workload'], cell['mode']): cell for cell in extension['report']['cells']}
    summary = copy.deepcopy(original['report'])
    summary['cells'] = [extend_cell(cell, added[(cell['workload'], cell['mode'])])
                        if (cell['workload'], cell['mode']) in added else cell
                        for cell in original['report']['cells']]
    summary['verified_jobs'] += extension['report']['verified_jobs']
    summary['gate_pass'] = len(summary['cells']) == 8 and all(c['gate_pass'] for c in summary['cells'])
    summary['uncertainty'] = (
        'Exact paired-block bootstrap, conditional on six original blocks or twelve blocks after '
        'one predeclared precision extension. Every original valid observation is retained. '
        'Extension selected after the initial unmet gate; no population/tail or optional-stopping-adjusted claim.'
    )
    summary['cohorts'] = [{
        'plan': cohort['plan_path'], 'raw': cohort['raw_path'],
        'plan_sha256': cohort['report']['plan_sha256'], 'raw_sha256': cohort['report']['raw_sha256'],
        'context': cohort['context'], 'verified_jobs': cohort['report']['verified_jobs'],
    } for cohort in (original, extension)]
    summary['samples'] = [{
        'raw_sha256': cohort['report']['raw_sha256'], 'raw_line': line,
        **{key: row[key] for key in ('sample', 'block', 'workload', 'mode', 'elapsed_seconds')},
    } for cohort in (original, extension)
        for line, row in cohort['located'] if row['kind'] == 'measurement']
    summary['analysis_sources'] = {name: sha(Path(__file__).with_name(name)) for name in (
        'analyze-execution-graph.py', 'extend-execution-graph-analysis.py', 'execution_graph_statistics.py')}
    Path(args.output).write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'verified_jobs': summary['verified_jobs'], 'gate_pass': summary['gate_pass']}))


if __name__ == '__main__':
    main()
