"""Prepare a tiny, native-only grouping controller control; never build or run engines."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location('baseline', Path(__file__).with_name('workload-baselines.py'))
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)
ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(Path(sys.base_prefix) / 'python.exe') if os.name == 'nt' else sys.executable


def verify_pair(first, second, record):
    jobs = [baseline.read_json(path) for path in (first, second)]
    for key in ('operations', 'input_csv', 'output_csv', 'compression', 'seed', 'full_shuffle_policy',
                'full_shuffle_rng', 'full_shuffle_algorithm', 'limits'):
        if jobs[0][key] != jobs[1][key]:
            raise ValueError('semantic parity mismatch: ' + key)
    results = [baseline.verify(path) for path in (first, second)]
    if results[0]['source_sha256'] != results[1]['source_sha256']:
        raise ValueError('fixture mismatch')
    def signature(job):
        folder = Path(job['output'])
        rows = [json.loads(line) for line in (folder / 'manifest.jsonl').read_text().splitlines()]
        return rows[0]['algorithm_version'], [(r['path'], r['rows'], r['csv_bytes'], r['lineage'],
                                              baseline.sha256(folder / r['path'])) for r in rows[1:]]
    if signature(jobs[0]) != signature(jobs[1]):
        raise ValueError('native seeded CSV parity failure')
    baseline.write_new(record, {'verified': True, 'seeded_csv_parity': True, 'independent_checks': results})


def plan(directory, executable, build_status, rows=2000, regions=8, provider='predeclared', codex=None):
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT / 'scratch'):
        raise ValueError('use a new scratch directory')
    if not 1 <= rows <= 20000 or regions not in (2, 8):
        raise ValueError('bounded development control: 1..20000 rows and 2 or 8 regions')
    baseline.build_reference(build_status, executable)
    directory.mkdir(parents=True, exist_ok=False)
    session = directory / 'session'
    session.mkdir()
    def relative(path):
        return str(path.relative_to(ROOT))
    batches = []
    for index, order in enumerate((('sort', 'auto'), ('auto', 'sort'))):
        name = f'pair{index+1}'
        steps, descriptors, output_roots, jobs = [], [], [], []
        for grouping in order:
            fixture = session / ('fixture-' + name + '-' + grouping)
            baseline.prepare(fixture, {'rows': rows, 'seed': 'entity-baseline-v1', 'regions': regions,
                'hot_percent': 30, 'notes_min': 24, 'notes_max': 128}, byte_cap=4096)
            destination = session / ('result-' + name + '-' + grouping)
            job_path = fixture / 'campaign.json'
            job = baseline.read_json(job_path)
            job['resources'].update(grouping=grouping, temp_dir=str(destination / 'temp'))
            job['output'] = str(destination / 'output')
            job_path.write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')
            record = destination / 'run.json'
            sources = ['scripts/workload-baselines.py', 'scripts/workload_entities.py',
                       'scripts/experiment-native-control.py', relative(job_path),
                       relative(fixture / 'entities.csv'), relative(fixture / 'dataset.json'),
                       relative(executable), relative(build_status), relative(build_status.with_name('manifest.json'))]
            prefix = name + '-' + grouping
            steps.append({'id': prefix + '-prepare', 'phase': 'prepare',
                'argv': [PYTHON, '-c', 'from pathlib import Path; import sys; Path(sys.argv[1]).mkdir(parents=True)',
                         str(destination / 'temp')], 'inputs': sources, 'artifacts': [relative(destination / 'temp')],
                'timeout_seconds': 5, 'depends': [steps[-1]['id']] if steps else []})
            steps.append({'id': prefix + '-run', 'phase': 'measure',
                'argv': [PYTHON, str(ROOT / 'scripts/workload-baselines.py'), 'run-native', str(executable),
                         str(job_path), '--record', str(record), '--build-status', str(build_status)],
                'inputs': sources, 'artifacts': [relative(destination / 'output'), relative(record),
                    relative(record.with_suffix('.stdout.log')), relative(record.with_suffix('.stderr.log'))],
                'timeout_seconds': 30, 'depends': [prefix + '-prepare']})
            descriptors.append({'path': relative(record), 'pointer': '/elapsed_seconds', 'unit': 'seconds',
                'scope': 'CLI process launch through successful Run/publication; preflight/verification excluded',
                'cell': grouping})
            output_roots.append(relative(destination))
            jobs.append(job_path)
        check_root = session / ('check-' + name)
        steps.append({'id': name + '-check-dir', 'phase': 'prepare', 'argv': [PYTHON, '-c',
            'from pathlib import Path; import sys; Path(sys.argv[1]).mkdir()', str(check_root)],
            'inputs': ['scripts/experiment-native-control.py'], 'artifacts': [], 'timeout_seconds': 5,
            'depends': [steps[-1]['id']]})
        steps.append({'id': name + '-verify', 'phase': 'verify', 'argv': [PYTHON,
            str(Path(__file__).resolve()), 'verify-pair', str(jobs[0]), str(jobs[1]), str(check_root / 'verified.json')],
            'inputs': ['scripts/experiment-native-control.py', 'scripts/workload-baselines.py',
                       *[relative(p) for p in jobs], *[p['path'] for p in descriptors]],
            'artifacts': [relative(check_root / 'verified.json')], 'timeout_seconds': 15,
            'depends': [steps[-1]['id']]})
        path = directory / (name + '.json')
        baseline.write_new(path, {'root': str(ROOT), 'batch_timeout_seconds': 100,
            'estimated_seconds': 20, 'estimated_disk_bytes': 64 * 1024**2,
            'toolchains': {'python': PYTHON, 'build_status': str(build_status)}, 'features': [],
            'fixtures': [f'entity-list-v1; {rows} rows; {regions} regions; independent notes 24..128; seed entity-baseline-v1'],
            'experiment': {'question': 'Does a bounded native grouping controller control preserve complete-job evidence?',
                'hypothesis': 'Both current auto/sort campaign jobs verify with identical seeded CSVs.',
                'decision_rule': 'Control only: report individual complete-job samples; no selector threshold or promotion.',
                'stop_rule': 'Stop on first failure, after two alternating pairs, or any session limit.',
                'cohort': 'development'}, 'steps': steps})
        batches.append({'id': name, 'kind': 'initial' if index == 0 else 'repeat',
            'parent': None if index == 0 else 'pair1', 'plan': str(path),
            'outputs': output_roots + [relative(check_root)], 'metrics': descriptors,
            'storage_reserve_bytes': 64 * 1024**2})
    config_path = directory / 'control.json'
    config = {'schema_version': 1, 'root': str(ROOT), 'provider': provider,
        'first': 'pair1', 'seconds': 300, 'storage_bytes': 512 * 1024**2, 'max_batches': 2,
        'max_runs': 4, 'max_decisions': 2, 'batches': batches, 'decisions': [
            {'action': 'repeat', 'target': 'pair2', 'assessment': 'useful',
             'reason': 'Predeclared alternating-order harness acceptance, not scientific endorsement.'},
            {'action': 'stop', 'target': None, 'assessment': 'inconclusive',
             'reason': 'Bounded controller acceptance complete; no performance conclusion.'}] if provider == 'predeclared' else []}
    if provider == 'codex':
        if codex is None:
            raise ValueError('Codex provider requires explicit executable, model and effort')
        config['codex'] = codex
    baseline.write_new(config_path, config)
    return {'config': str(config_path), 'session': str(session), 'estimated_seconds': 40,
            'storage_budget_bytes': 512 * 1024**2, 'note': 'Preparation only; builds and native Runs are separate.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare = sub.add_parser('plan')
    prepare.add_argument('directory', type=Path)
    prepare.add_argument('--executable', type=Path, default=ROOT / 'target/release/chopper.exe')
    prepare.add_argument('--build-status', type=Path, required=True)
    prepare.add_argument('--rows', type=int, default=2000)
    prepare.add_argument('--regions', type=int, choices=[2, 8], default=8)
    prepare.add_argument('--provider', choices=['predeclared', 'file', 'codex'], default='predeclared')
    prepare.add_argument('--codex-executable', type=Path)
    prepare.add_argument('--model')
    prepare.add_argument('--reasoning-effort', choices=['medium', 'high'])
    verify = sub.add_parser('verify-pair')
    for name in ('first', 'second', 'record'):
        verify.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.command == 'verify-pair':
        verify_pair(args.first, args.second, args.record)
    else:
        settings = None
        if args.provider == 'codex':
            if not args.codex_executable or not args.model or not args.reasoning_effort:
                parser.error('codex requires --codex-executable, --model and --reasoning-effort')
            settings = {'executable': str(args.codex_executable.resolve()), 'model': args.model,
                        'reasoning_effort': args.reasoning_effort, 'timeout_seconds': 90}
        print(json.dumps(plan(args.directory, args.executable.resolve(), args.build_status.resolve(),
                              args.rows, args.regions, args.provider, settings), indent=2))


if __name__ == '__main__':
    main()
