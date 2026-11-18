"""Final bounded precision analysis, retaining all three admitted cohorts."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import statistics
import tempfile

from execution_graph_statistics import paired_bootstrap_conservative_upper95

path = Path(__file__).with_name('extend-execution-graph-analysis.py')
spec = importlib.util.spec_from_file_location('retained_analysis', path)
retained = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retained)


def final_cell(prior, added, resamples):
    result = copy.deepcopy(prior)
    baseline = prior['disabled_seconds'] + added['disabled_seconds']
    enabled = prior['enabled_seconds'] + added['enabled_seconds']
    assert len(baseline) == len(enabled) == 18, 'Final precision cap is eighteen paired blocks'
    base_median, median = statistics.median(baseline), statistics.median(enabled)
    simulation = paired_bootstrap_conservative_upper95(
        baseline, enabled, resamples=resamples, seed=735780)
    upper = simulation['upper95_slowdown']
    slowdown = median / base_median - 1
    result.update(
        n=18, disabled_seconds=baseline, enabled_seconds=enabled,
        disabled_median_seconds=base_median, enabled_median_seconds=median,
        disabled_range_seconds=[min(baseline), max(baseline)],
        enabled_range_seconds=[min(enabled), max(enabled)],
        disabled_mad_seconds=statistics.median(abs(value - base_median) for value in baseline),
        enabled_mad_seconds=statistics.median(abs(value - median) for value in enabled),
        paired_slowdowns=[value / base - 1 for value, base in zip(enabled, baseline)],
        median_slowdown=slowdown, paired_bootstrap_upper95_slowdown=upper,
        bootstrap_simulation=simulation, gate_pass=slowdown <= .05 and upper <= .05,
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('original_plan', 'original_raw', 'extension_plan', 'extension_raw',
                 'final_plan', 'final_raw', 'output'):
        parser.add_argument(name)
    parser.add_argument('--resamples', type=int, default=1_000_000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory:
        cohorts = [retained.read_cohort(plan, raw, Path(directory) / f'{index}.json')
                   for index, (plan, raw) in enumerate((
                       (args.original_plan, args.original_raw),
                       (args.extension_plan, args.extension_raw),
                       (args.final_plan, args.final_raw)))]
    original, extension, final = cohorts
    retained.verify_extension(original, extension)
    retained.verify_extension(original, final)
    retained.verify_extension(extension, final)
    extension_cells = {(c['workload'], c['mode']): c for c in extension['report']['cells']}
    final_cells = {(c['workload'], c['mode']): c for c in final['report']['cells']}
    summary = copy.deepcopy(original['report'])
    prior_cells = []
    for cell in summary['cells']:
        key = cell['workload'], cell['mode']
        if key in extension_cells:
            cell = retained.extend_cell(cell, extension_cells[key])
        prior_cells.append(cell)
    remaining = {cell['workload'] for cell in prior_cells if not cell['gate_pass']}
    assert len(remaining) == 1 and {w['id'] for w in final['plan']['workloads']} == remaining, \
        'Only the single still-unmet workload may receive final blocks'
    cells = []
    for cell in prior_cells:
        key = cell['workload'], cell['mode']
        if key in final_cells:
            cell = final_cell(cell, final_cells[key], args.resamples)
        cells.append(cell)
    summary.update(
        cells=cells, verified_jobs=sum(c['report']['verified_jobs'] for c in cohorts),
        gate_pass=len(cells) == 8 and all(c['gate_pass'] for c in cells),
        uncertainty=(
            'Conditional paired-block bootstrap: exact at six/twelve blocks; final eighteen-block '
            'cells use fixed-seed Monte Carlo with conservative DKW quantile inflation. '
            'All original observations retained; precision extensions selected after unmet gates. '
            'No population/tail or optional-stopping-adjusted confidence claim.'),
        simulation_error_scope='At most 1e-6 per simulated cell under independent uniform resampling; '
                               'union bound 2e-6 across the two final cells; seeded PRNG implementation recorded.',
    )
    summary['cohorts'] = [{
        'plan': c['plan_path'], 'raw': c['raw_path'],
        'plan_sha256': c['report']['plan_sha256'], 'raw_sha256': c['report']['raw_sha256'],
        'context': c['context'], 'verified_jobs': c['report']['verified_jobs'],
    } for c in cohorts]
    summary['samples'] = [{
        'raw_sha256': c['report']['raw_sha256'], 'raw_line': line,
        **{key: row[key] for key in ('sample', 'block', 'workload', 'mode', 'elapsed_seconds')},
    } for c in cohorts for line, row in c['located'] if row['kind'] == 'measurement']
    summary['analysis_sources'] = {name: retained.sha(Path(__file__).with_name(name)) for name in (
        'analyze-execution-graph.py', 'extend-execution-graph-analysis.py',
        'final-execution-graph-analysis.py', 'execution_graph_statistics.py')}
    Path(args.output).write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'verified_jobs': summary['verified_jobs'], 'gate_pass': summary['gate_pass']}))


if __name__ == '__main__':
    main()
