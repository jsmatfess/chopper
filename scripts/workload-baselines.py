"""Prepare, run and independently verify the first two current-contract workloads."""
import argparse
import csv
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from workload_entities import HEADER, VERSION, generate, sha256


ROOT = Path(__file__).resolve().parent.parent


def write_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def prepare(directory, parameters, memory_mb=64, byte_cap=10_000_000):
    if not 32 <= memory_mb <= 512 or byte_cap <= 0:
        raise ValueError('baseline memory must be 32..512 MiB and byte cap positive')
    if parameters['rows'] * (parameters['notes_max'] + 256) > 16 * 1024 * 1024:
        raise ValueError('this initial baseline slice is limited to 16 MiB fixtures')
    directory.mkdir(parents=True, exist_ok=False)
    metadata = generate(directory / 'entities.csv', parameters)
    write_new(directory / 'dataset.json', metadata)
    temp = directory / 'temp'
    temp.mkdir()
    csv_settings = {'encoding': 'utf-8', 'headers': True, 'delimiter': ',',
                    'quote': '"', 'escape': None, 'line_ending': 'lf',
                    'bom': False, 'skip_empty_lines': False}
    for case in ('ordered', 'campaign'):
        job = {'version': 1, 'input': str(directory / 'entities.csv'),
               'output': str(directory / (case + '-output')),
               'input_csv': csv_settings, 'output_csv': csv_settings,
               'compression': 'none', 'seed': 'workload-baseline-v1',
               'full_shuffle_policy': 'seeded_v1',
               'full_shuffle_rng': 'blake3_counter_v1',
               'full_shuffle_algorithm': 'adaptive_v1',
               'operations': [] if case == 'ordered' else [
                   {'type': 'partition', 'columns': ['region']},
                   {'type': 'assign_probabilistic', 'groups': [
                       {'name': 'treatment', 'percent': '80'},
                       {'name': 'control', 'percent': '20'}], 'strata': []},
                   {'type': 'shuffle', 'strategy': 'uniform'}],
               'limits': {'bytes': byte_cap} if case == 'ordered' else {},
               'resources': {'memory_mb': memory_mb, 'workers': 1,
                             'temp_dir': str(temp), 'temp_bytes': 256 * 1024 * 1024,
                             'max_files': 4096, 'max_record_bytes': 524288,
                             'grouping': 'auto'}}
        write_new(directory / (case + '.json'), job)
    return metadata


def csv_bytes(row):
    # Independent UTF-8/comma/LF encoder for the explicit recipe dialect.
    # Chopper quotes empty fields as well as delimiters, quotes and newlines.
    fields = [('"' + field.replace('"', '""') + '"')
              if not field or any(char in field for char in ',"\r\n') else field
              for field in row]
    return (','.join(fields) + '\n').encode('utf-8')


def verify(job_path, output=None, browser=False):
    """Exact record/field checks for small baselines, independent of engine digests.

    This intentionally holds source rows in memory. It is not the future large-
    scale verifier and does not prove probability laws or seeded draw membership.
    """
    job = read_json(job_path)
    for settings in (job['input_csv'], job['output_csv']):
        if (settings['encoding'] != 'utf-8' or settings['headers'] is not True
                or settings['delimiter'] != ',' or settings['quote'] != '"'
                or settings['escape'] is not None or settings['bom']
                or settings['line_ending'] != 'lf'):
            raise ValueError('verifier only supports the explicit UTF-8/comma/header/LF recipe')
    if job['compression'] != 'none' or job['full_shuffle_policy'] != 'seeded_v1':
        raise ValueError('unsupported baseline compression or policy')
    if job['operations'] and job['operations'] != [
            {'type': 'partition', 'columns': ['region']},
            {'type': 'assign_probabilistic', 'groups': [
                {'name': 'treatment', 'percent': '80'}, {'name': 'control', 'percent': '20'}], 'strata': []},
            {'type': 'shuffle', 'strategy': 'uniform'}]:
        raise ValueError('verifier only supports the ordered or campaign baseline recipe')
    if job['limits'].get('rows') is not None or job['limits'].get('compressed_bytes') is not None:
        raise ValueError('unsupported baseline limits')
    if job['operations'] and job['limits'].get('bytes') is not None:
        raise ValueError('campaign baseline must be uncapped')
    if not job['operations'] and not job['limits'].get('bytes', 0) > 0:
        raise ValueError('ordered baseline needs a positive byte cap')
    source = Path(job['input'])
    metadata = read_json(source.with_name('dataset.json'))
    if source.stat().st_size > 16 * 1024 * 1024:
        raise ValueError('independent baseline verifier is limited to 16 MiB inputs')
    if metadata['generator'] != VERSION or sha256(source) != metadata['sha256']:
        raise ValueError('source identity mismatch')
    csv.field_size_limit(1024 * 1024)
    with source.open(encoding='utf-8', newline='') as stream:
        reader = csv.reader(stream, strict=True)
        if next(reader) != HEADER:
            raise ValueError('source header mismatch')
        rows = list(reader)
    if len(rows) != metadata['parameters']['rows']:
        raise ValueError('source row count mismatch')
    if [row[0] for row in rows] != list(map(str, range(len(rows)))):
        raise ValueError('source IDs are not unique consecutive ordinals')
    folder = output or Path(job['output'])
    manifest = [json.loads(line) for line in (folder / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    if not manifest or manifest[0]['type'] != 'job':
        raise ValueError('missing job manifest')
    config = manifest[0]['config']
    for key in ('operations', 'input_csv', 'output_csv', 'compression', 'seed', 'full_shuffle_policy'):
        if config.get(key, 'seeded_v1' if key == 'full_shuffle_policy' else None) != job[key]:
            raise ValueError('manifest job mismatch: ' + key)
    for key in ('rows', 'bytes', 'compressed_bytes'):
        if config['limits'].get(key) != job['limits'].get(key):
            raise ValueError('manifest limits mismatch')
    outputs = manifest[1:]
    if any(entry['type'] != 'output' for entry in outputs):
        raise ValueError('unexpected manifest entry')
    names = [entry['path'] for entry in outputs]
    if len(names) != len(set(names)):
        raise ValueError('duplicate manifest output path')
    allowed = set(names) | {'manifest.jsonl'} | ({'CHOPPER-COMPLETE.json'} if browser else set())
    if {p.name for p in folder.iterdir()} != allowed:
        raise ValueError('unlisted or missing output files')
    if browser:
        marker = read_json(folder / 'CHOPPER-COMPLETE.json')
        if (marker.get('complete') is not True or marker.get('version') != 1
                or marker.get('engine') != 'chopper-browser' or marker.get('files') != len(names) + 1):
            raise ValueError('invalid browser completion marker')
    campaign = bool(job['operations'])
    seen = set()
    encountered = []
    populations = {}
    chunk_lengths = []
    for entry in outputs:
        name = entry['path']
        if Path(name).name != name or '/' in name or '\\' in name or not name.endswith('.csv'):
            raise ValueError('unsafe or unsupported output path')
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('output must be a regular file')
        size = path.stat().st_size
        if size != entry['csv_bytes'] or size != entry['stored_bytes']:
            raise ValueError('manifest output byte count mismatch')
        if job['limits'].get('bytes') is not None and size > job['limits']['bytes']:
            raise ValueError('strict serialized byte cap exceeded')
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.reader(stream, strict=True)
            if next(reader) != HEADER:
                raise ValueError('output header mismatch')
            actual = list(reader)
        if len(actual) != entry['rows']:
            raise ValueError('manifest output row count mismatch')
        if campaign:
            lineage = entry['lineage']
            parts = [e['values'] for e in lineage if e.get('operation') == 0 and 'values' in e]
            arms = [e['allocation'] for e in lineage if e.get('operation') == 1 and 'allocation' in e]
            if len(parts) != 1 or len(parts[0]) != 1 or arms not in (['treatment'], ['control']):
                raise ValueError('incorrect partition/allocation lineage')
            group = (parts[0][0], arms[0])
            if group in populations:
                raise ValueError('unexpected chunked or duplicate uncapped group')
            populations[group] = len(actual)
        elif entry['lineage']:
            raise ValueError('ordered export unexpectedly grouped')
        for row in actual:
            if len(row) != len(HEADER):
                raise ValueError('field count changed')
            try:
                index = int(row[0])
            except ValueError as error:
                raise ValueError('invalid record ID') from error
            if not 0 <= index < len(rows) or row != rows[index] or index in seen:
                raise ValueError('record lost, duplicated or field values changed')
            if campaign and row[1] != group[0]:
                raise ValueError('record placed in wrong region')
            seen.add(index)
            encountered.append(index)
        chunk_lengths.append(len(actual))
    if len(seen) != len(rows) or manifest[0]['analysis']['rows'] != len(rows):
        raise ValueError('record conservation failed')
    if campaign:
        expected = {(row[1], arm) for row in rows for arm in ('treatment', 'control')}
        if set(populations) != expected:
            raise ValueError('missing named group, including empty allocation')
    else:
        if encountered != list(range(len(rows))):
            raise ValueError('ordered export changed row order')
        # Independent greedy boundary oracle, counting serialized UTF-8 CSV.
        expected_lengths, count, size = [], 0, len(csv_bytes(HEADER))
        for row in rows:
            length = len(csv_bytes(row))
            if size + length > job['limits']['bytes'] and count:
                expected_lengths.append(count)
                count, size = 0, len(csv_bytes(HEADER))
            if size + length > job['limits']['bytes']:
                raise ValueError('fixture has an individually unfit record')
            count += 1
            size += length
        if count:
            expected_lengths.append(count)
        if chunk_lengths != expected_lengths:
            raise ValueError('encoded greedy chunk boundaries differ')
    return {'verified': True, 'rows': len(rows), 'files': len(outputs),
            'source_sha256': metadata['sha256'], 'case': 'campaign' if campaign else 'ordered',
            'checks': 'exact fields/IDs, conservation, lineage, sizes, caps and ordered boundaries',
            'limits': 'small-input verifier; no uniformity proof or independent seeded membership oracle',
            'populations': [{'region': region, 'arm': arm, 'rows': count}
                            for (region, arm), count in sorted(populations.items())]}


def build_reference(status_path, artifact):
    status = read_json(status_path)
    manifest = status_path.with_name('manifest.json')
    plan = read_json(manifest)
    if status['summary']['incomplete'] != 0:
        raise ValueError('build record is incomplete')
    latest = {attempt['id']: attempt for attempt in status['attempts']}
    expected = [identity['sha256'] for attempt in latest.values() if attempt['status'] == 'passed'
                for name, identity in attempt['artifacts'].items()
                if (Path(plan['root']) / name).resolve() == artifact.resolve() and 'sha256' in identity]
    if not expected or any(value != sha256(artifact) for value in expected):
        raise ValueError('artifact does not match completed build provenance')
    return {'status': str(status_path), 'status_sha256': sha256(status_path),
            'manifest_sha256': sha256(manifest)}


def run_native(executable, job_path, record, build_status=None):
    job = read_json(job_path)
    if Path(job['output']).exists():
        raise ValueError('output already exists; use a fresh attempt directory')
    data = {'runtime': 'native', 'status': 'running', 'job_sha256': sha256(job_path),
            'input_sha256': sha256(job['input']), 'binary_sha256': sha256(executable),
            'platform': platform.platform(), 'python': sys.version,
            'script_sha256': sha256(Path(__file__)), 'seed': job['seed'],
            'policy': job['full_shuffle_policy'], 'cache': 'uncontrolled',
            'timing_scope': 'CLI process launch through successful Run/publication; verification separate'}
    data['build_provenance'] = build_reference(build_status, executable) if build_status else None
    write_new(record, data)
    started = time.perf_counter()
    with record.with_suffix('.stdout.log').open('xb') as stdout, record.with_suffix('.stderr.log').open('xb') as stderr:
        result = subprocess.run([str(executable), 'run', '--config', str(job_path), '--yes'],
                                stdout=stdout, stderr=stderr)
    data.update(elapsed_seconds=time.perf_counter() - started, exit_code=result.returncode,
                status='complete' if result.returncode == 0 else 'failed')
    temporary = record.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, record)
    if result.returncode:
        raise RuntimeError('native Run failed; see retained stdout/stderr and record')
    return data


def parity(first_job, second_job, second_output):
    first, second = read_json(first_job), read_json(second_job)
    for key in ('operations', 'input_csv', 'output_csv', 'compression', 'seed',
                'full_shuffle_policy', 'full_shuffle_rng', 'full_shuffle_algorithm', 'limits'):
        if first[key] != second[key]:
            raise ValueError('parity requires identical semantic/seeded recipes: ' + key)
    if sha256(first['input']) != sha256(second['input']):
        raise ValueError('parity source bytes differ')
    verify(first_job)
    verify(second_job, second_output, browser=True)

    def signature(folder):
        records = [json.loads(line) for line in (folder / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
        return records[0]['algorithm_version'], [
            (entry['path'], entry['rows'], entry['csv_bytes'], entry['lineage'], sha256(folder / entry['path']))
            for entry in records[1:]]

    if signature(Path(first['output'])) != signature(second_output):
        raise ValueError('native/browser seeded logical output parity failed')
    return {'parity_verified': True, 'source_sha256': sha256(first['input']),
            'scope': 'same current seeded recipe, algorithm version, ordered lineage and CSV bytes; container manifests differ'}


def make_plans(directory, executable, node, parameters, byte_cap=4096, build_statuses=None):
    """Concrete small control plans, without building or launching engines."""
    directory = directory.resolve()
    if not directory.is_relative_to(ROOT / 'scratch'):
        raise ValueError('baseline plan directories must be inside repository scratch/')
    directory.mkdir(parents=True, exist_ok=False)
    if build_statuses is None:
        build_statuses = {runtime: directory / (runtime + '-build') / 'status.json'
                          for runtime in ('native', 'browser')}
        cargo = shutil.which('cargo') or 'cargo'
        def version(command):
            try:
                return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT).strip()
            except (OSError, subprocess.CalledProcessError):
                return 'unavailable; execution prerequisite'
        toolchains = {'cargo': version([cargo, '--version']), 'rustc': version(['rustc', '-vV']),
                      'node': version([node, '--version']), 'wasm_target': 'wasm32-wasip1'}
        source = ['Cargo.toml', 'Cargo.lock', 'crates', 'vendor']
        for runtime in ('native', 'browser'):
            steps = [{'id': 'engine-build', 'argv': ([cargo, 'build', '--release', '--locked', '-p', 'chopper-csv']
                       if runtime == 'native' else [node, 'scripts/build-browser.mjs']),
                      'timeout_seconds': 540, 'inputs': source + ([] if runtime == 'native' else ['scripts/build-browser.mjs']),
                      'artifacts': [str(executable.relative_to(ROOT))] if runtime == 'native' else ['ui/dist/engine.wasm'],
                      'depends': []}]
            if runtime == 'browser':
                steps.append({'id': 'hosted-workers', 'argv': [node, 'scripts/build-hosted.mjs'],
                              'timeout_seconds': 60, 'inputs': ['ui/src', 'ui/index.html', 'ui/style.css',
                                  'ui/package.json', 'ui/package-lock.json', 'ui/dist/engine.wasm',
                                  'scripts/build-hosted.mjs', 'scripts/browser-artifacts.mjs', 'scripts/hosted-theme.mjs',
                                  'docs/releases/native-usage.txt', 'docs/formula-functions.md',
                                  'examples/customers.csv', 'examples/quickstart-job.json'],
                              'artifacts': ['ui/dist'], 'depends': ['engine-build']})
            write_new(directory / (runtime + '-build-plan.json'), {
                'root': str(ROOT), 'batch_timeout_seconds': 600, 'estimated_seconds': 180,
                'estimated_disk_bytes': 2 * 1024**3, 'toolchains': toolchains,
                'features': [], 'fixtures': [], 'steps': steps})
    scripts = ['scripts/workload-baselines.py', 'scripts/workload_entities.py']
    relative = lambda path: str(path.relative_to(ROOT))
    python = str(Path(sys.base_prefix) / 'python.exe') if os.name == 'nt' else sys.executable
    base = [python, str(ROOT / scripts[0])]
    for runtime in ('native', 'browser'):
        data = directory / (runtime + '-data')
        prepare_args = [*base, 'prepare', str(data), '--byte-cap', str(byte_cap)]
        for key, value in parameters.items():
            prepare_args.extend(['--' + key.replace('_', '-'), str(value)])
        prepare_step = {'id': 'fixture', 'phase': 'prepare', 'argv': prepare_args,
                        'timeout_seconds': 30, 'inputs': scripts, 'artifacts': [
                            relative(data / name) for name in ('entities.csv', 'dataset.json', 'ordered.json', 'campaign.json')],
                        'depends': []}
        steps = [prepare_step]
        for case in ('ordered', 'campaign'):
            job = data / (case + '.json')
            record = directory / (case + '-' + runtime + '.json')
            output = data / (case + ('-output' if runtime == 'native' else '-browser-output'))
            extra_inputs = [relative(executable)] if runtime == 'native' else [
                'scripts/run-workload-browser.mjs', 'scripts/browser-launch.mjs', 'ui/tests/workload-baseline.ts',
                'ui/dist/engine.wasm', 'ui/dist/engine-worker.js', 'ui/dist/storage-worker.js',
                'ui/src/browser', 'ui/package-lock.json']
            # Native path must be a workspace artifact so the runner can pin it.
            command = ([*base, 'run-native', str(executable), str(job), '--record', str(record)]
                       if runtime == 'native' else [node, str(ROOT / 'scripts/run-workload-browser.mjs'),
                           str(job), str(output), str(record), str(directory / (case + '-profile'))])
            if build_statuses:
                status = build_statuses[runtime]
                extra_inputs += [relative(status), relative(status.with_name('manifest.json'))]
                command += (['--build-status', str(status)] if runtime == 'native' else [str(status)])
            measured = case + '-' + runtime
            artifacts = [relative(output), relative(record)]
            if runtime == 'native':
                artifacts += [relative(record.with_suffix(suffix)) for suffix in ('.stdout.log', '.stderr.log')]
            steps.append({'id': measured, 'phase': 'measure', 'argv': command,
                          'timeout_seconds': 150, 'inputs': scripts + [relative(job),
                              relative(data / 'entities.csv'), relative(data / 'dataset.json')] + extra_inputs,
                          'artifacts': artifacts, 'depends': ['fixture']})
            verification = [*base, 'verify', str(job), '--record', str(record.with_suffix('.verified.json'))]
            if runtime == 'browser':
                verification += ['--output', str(output), '--browser']
            steps.append({'id': measured + '-verify', 'phase': 'verify', 'argv': verification,
                          'timeout_seconds': 30, 'inputs': scripts + [relative(job), relative(output),
                              relative(data / 'entities.csv'), relative(data / 'dataset.json')],
                          'artifacts': [relative(record.with_suffix('.verified.json'))], 'depends': [measured]})
        plan = {'root': str(ROOT), 'batch_timeout_seconds': 600,
                'estimated_seconds': 60 if runtime == 'native' else 120,
                'estimated_disk_bytes': (64 if runtime == 'native' else 256) * 1024 * 1024,
                'toolchains': {'python': python + '; ' + sys.version, 'node': node,
                               'engine': 'prerequisite: record actual source/build provenance before execution'},
                'features': [], 'fixtures': [VERSION, parameters],
                'experiment': {'question': 'Do both current-contract baseline jobs complete correctly in ' + runtime + '?',
                               'hypothesis': 'Direct Run conserves records, respects grouping and serialized byte caps.',
                               'decision_rule': 'Require independent verification; single control timings imply no speedup.',
                               'stop_rule': 'Stop on invalid input, failure, timeout or verification failure.',
                               'cohort': 'development'}, 'steps': steps}
        write_new(directory / (runtime + '-plan.json'), plan)
    return {'plans': [str(directory / (runtime + '-plan.json')) for runtime in ('native', 'browser')],
            'build_statuses': {runtime: str(path) for runtime, path in build_statuses.items()},
            'prerequisites': 'fresh native build; npm ci; default production WASM/hosted assets; browser channel',
            'fixture_estimate_upper_bytes': parameters['rows'] * (parameters['notes_max'] + 256)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('prepare')
    create.add_argument('directory', type=Path)
    create.add_argument('--rows', type=int, default=2000)
    create.add_argument('--seed', default='entity-baseline-v1')
    create.add_argument('--regions', type=int, default=8)
    create.add_argument('--hot-percent', type=int, default=30)
    create.add_argument('--notes-min', type=int, default=24)
    create.add_argument('--notes-max', type=int, default=128)
    create.add_argument('--memory-mb', type=int, default=64)
    create.add_argument('--byte-cap', type=int, default=10_000_000)
    check = sub.add_parser('verify')
    check.add_argument('job', type=Path)
    check.add_argument('--output', type=Path)
    check.add_argument('--browser', action='store_true')
    check.add_argument('--record', type=Path, required=True)
    native = sub.add_parser('run-native')
    native.add_argument('executable', type=Path)
    native.add_argument('job', type=Path)
    native.add_argument('--record', type=Path, required=True)
    native.add_argument('--build-status', type=Path)
    plans = sub.add_parser('plan')
    plans.add_argument('directory', type=Path)
    plans.add_argument('--executable', type=Path, default=ROOT / 'target/release/chopper.exe' if os.name == 'nt' else ROOT / 'target/release/chopper')
    plans.add_argument('--node', default=shutil.which('node') or 'node')
    plans.add_argument('--native-build-status', type=Path)
    plans.add_argument('--browser-build-status', type=Path)
    compare = sub.add_parser('parity')
    compare.add_argument('first_job', type=Path)
    compare.add_argument('second_job', type=Path)
    compare.add_argument('second_output', type=Path)
    compare.add_argument('--record', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            fields = ('rows', 'seed', 'regions', 'hot_percent', 'notes_min', 'notes_max')
            result = prepare(args.directory.resolve(), {key: getattr(args, key) for key in fields},
                             args.memory_mb, args.byte_cap)
        elif args.command == 'verify':
            result = verify(args.job.resolve(), args.output.resolve() if args.output else None, args.browser)
            write_new(args.record.resolve(), result)
        elif args.command == 'run-native':
            result = run_native(args.executable.resolve(), args.job.resolve(), args.record.resolve(),
                                args.build_status.resolve() if args.build_status else None)
        elif args.command == 'parity':
            result = parity(args.first_job.resolve(), args.second_job.resolve(), args.second_output.resolve())
            write_new(args.record.resolve(), result)
        else:
            if bool(args.native_build_status) != bool(args.browser_build_status):
                raise ValueError('supply both build status paths, or neither to generate build plans')
            statuses = ({'native': args.native_build_status.resolve(),
                         'browser': args.browser_build_status.resolve()} if args.native_build_status else None)
            result = make_plans(args.directory, args.executable.resolve(), args.node,
                                {'rows': 2000, 'seed': 'entity-baseline-v1', 'regions': 8,
                                 'hot_percent': 30, 'notes_min': 24, 'notes_max': 128},
                                build_statuses=statuses)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, StopIteration) as error:
        print(f'workload-baselines: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
