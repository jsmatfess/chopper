"""Frozen native E5 W1/W0 tooling. No builds, retries, tuning or promotion.

--freeze records a plan, without generating full fixtures or launching Chopper.
--run verifies artifact-bound native test controls and a separate release build.
CLI ceilings are not denial hooks; controls never become timing samples.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CASES = [('small', 1000), ('external', 1000000), ('skew', 200000), ('late_wide', 100000)]
SEED = 'e5-workers-held-fixed-v1'
ALGORITHM = 'chopper-v1-blake3-1'
DISK_BYTES = 2 * 1024**3
BLOCKERS = ['D1-D4: verified complete-Run denial control report not supplied']
CONTROL_PREFIX = 'E5_WORKER_CONTROL '
CONTROL_FILTER = 'resources::e5_worker_controls::'


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


memory = load('benchmark-e5-memory')
external = load('benchmark-external-shuffle')
sha = memory.sha
fields = memory.fields


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def inventory(root=ROOT):
    # git covers dirty/untracked nonignored inputs; explicit walks also include
    # ignored vendor/build inputs. No docs/history or target caches are inputs.
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others',
                                     '--exclude-standard', '-z', '--', 'crates',
                                     'ui', 'scripts', 'vendor', 'Cargo.toml', 'Cargo.lock',
                                     '.cargo', 'rust-toolchain', 'rust-toolchain.toml'], cwd=root).decode().split('\0')
    paths = {root / n for n in names if n and '__pycache__' not in Path(n).parts
             and (root / n).is_file()}
    for directory in ('vendor/zip-2.4.2', 'vendor/zstd-sys-2.1.1'):
        paths.update(p for p in (root / directory).rglob('*') if p.is_file())
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(paths)}


def identities(binary=None):
    result = {'source_sha256': inventory(), 'harness_sha256': {
        p: sha(ROOT / 'scripts' / p) for p in ('benchmark-e5-workers.py',
        'benchmark-e5-memory.py', 'benchmark-external-shuffle.py', 'benchmark-windows.py')}}
    if binary is not None:
        result['binary_sha256'] = sha(binary)
    return result


def assert_identity(expected, binary=None):
    require(identities(binary) == expected, 'source/build/harness identity drift; retain attempt and stop')


def schedule():
    return [(case, rows, rep + 1, variant) for case, rows in CASES
            for rep in range(3) for variant in ((1, 0) if rep % 2 == 0 else (0, 1))]


def job_for(case, source, output, temp, workers):
    operations = [] if case == 'small' else [{'type': 'shuffle', 'strategy': 'uniform'}]
    if case == 'skew':
        operations.append({'type': 'partition', 'columns': ['key']})
    return {'input': str(source.resolve()), 'output': str(output.resolve()), 'seed': SEED,
            'operations': operations, 'limits': {'bytes': 262144, 'rows': 2000},
            'resources': {'memory_mb': 256, 'workers': workers, 'max_record_bytes': 1048576,
                          'temp_dir': str(temp.resolve()), 'temp_bytes': 268435456}}


def disk_usage(root):
    size = 0
    for path in root.rglob('*'):
        try:
            if path.is_file():
                size += path.stat().st_size
        except FileNotFoundError:
            pass  # private staging can disappear during publication
    return size


def budget(root, deadline, limit=DISK_BYTES):
    require(time.monotonic() < deadline, 'batch deadline exceeded')
    require(disk_usage(root) < limit, 'retained fixture/output/temp/log disk ceiling reached')
    require(shutil.disk_usage(root).free >= 268435456, 'less than live temp allowance free')


def attempt(command, folder, env, deadline, guard=lambda: None, timeout=60,
            counter=lambda process: {}):
    """Retain every launch/outcome/log, kill and reap on timeout/guard failure.

    Guard samples are lower bounds, not a filesystem quota. The clock includes
    the monitoring overhead equally in both variants. No subprocess shell.
    """
    folder.mkdir()  # exclusive: never overwrite or silently retry
    write_json(folder / 'command.json', {'argv': command, 'cwd': str(ROOT),
               'env_overrides': {'CHOPPER_MEMORY_LIMIT_MB': env.get('CHOPPER_MEMORY_LIMIT_MB')}})
    result = {'command': command, 'status': 'launching', 'exit_code': None}
    process = None
    began = time.perf_counter()
    try:
        guard()
        with (folder / 'stdout.log').open('xb') as out, (folder / 'stderr.log').open('xb') as err:
            # Administrative preflight and log creation are outside the frozen
            # spawn-through-exit interval, but still consume the batch budget.
            began = time.perf_counter()
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=out, stderr=err)
            end = min(deadline, time.monotonic() + timeout)
            while process.poll() is None:
                guard()
                require(time.monotonic() < end, 'attempt timeout or batch deadline')
                time.sleep(.02)
            result['seconds'] = time.perf_counter() - began
            result['exit_code'] = process.returncode
            require(process.returncode == 0, 'nonzero subprocess exit')
            guard()
            result['status'] = 'completed'
    except BaseException as error:
        result.update(status='failed', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            result['exit_code'] = process.returncode
            try:
                result.update(counter(process))
            except Exception as error:
                result['counter_error'] = f'{type(error).__name__}: {error}'
                # Missing counters invalidate a successful measurement, but must
                # never replace the original subprocess/timeout/guard error.
                if result['status'] == 'completed':
                    result.update(status='failed', error=result['counter_error'])
        result.setdefault('seconds', time.perf_counter() - began)
        write_json(folder / 'outcome.json', result)
    require(result['status'] == 'completed', result.get('error', 'counter capture failed'))
    return result


def verify(output, temp, analysis, case, rows, workers, source=None):
    """Adapt the existing E5 verifier and external lineage/owner checks.

    Fingerprint contains complete output records, exact CSV hashes, logical
    digest and stages. Only job path/resources/timing records are excluded.
    """
    require(not sys.flags.optimize, 'run without Python -O: reused audit verifier uses assertions')
    require(analysis['rows'] == rows, 'analysis row count')
    require(analysis['seed'] == SEED and analysis['algorithm_version'] == ALGORITHM, 'seed/algorithm')
    require(analysis['workers'] == (4 if workers == 0 else 1), 'resolved worker count ineligible')
    require(analysis['memory_budget_bytes'] == 256 * 1024**2, 'resolved nominal memory')
    require(not any(temp.iterdir()), 'owned temporary directory not empty')
    require(analysis['diagnostics']['temporary_cleanup_failures'] == 0, 'cleanup failures')
    # The older external verifier's exact owner sum predates admitted Analysis
    # payloads. Keep its audit validation and cap check, but do not claim that a
    # CLI snapshot proves final-drop release (that belongs to Rust controls).
    d = analysis['diagnostics']
    audit = external.audit_reserved_bytes(d)
    owners = [d[k] for k in ('temporary_path_reserved_bytes', 'directory_path_reserved_bytes',
        'prepared_job_reserved_bytes', 'analysis_preview_reserved_bytes',
        'analysis_warnings_reserved_bytes', 'analysis_timings_reserved_bytes',
        'analysis_text_reserved_bytes', 'stage_stats_reserved_bytes',
        'column_values_reserved_bytes', 'input_header_reserved_bytes',
        'analysis_diagnostics_reserved_bytes')]
    require(all(type(v) is int and v >= 0 for v in owners), 'malformed owner charge')
    require(sum(owners) + audit <= d['workspace_reserved_bytes'] <= d['peak_workspace_reserved_bytes']
            <= analysis['memory_budget_bytes'] // 2, 'workspace ownership/cap')
    require(d['process_memory']['limit_bytes'] == 64 * 1024**2 and
            d['process_memory']['peak_reserved_bytes'] <= 64 * 1024**2, 'shared ledger cap')
    entries = [json.loads(line) for line in (output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    require(entries and entries[0]['type'] == 'job', 'missing job manifest record')
    record = entries[0]
    require(record['algorithm_version'] == ALGORITHM, 'manifest algorithm')
    config = record['config']
    expected = job_for(case, source or Path(config['input']), output, temp, workers)
    for key in ('input', 'output', 'seed', 'operations', 'limits'):
        # Serialized limits may include defaults; compare each requested field.
        if key == 'limits':
            require(all(config[key][k] == v for k, v in expected[key].items()), 'manifest limits')
        else:
            require(config[key] == expected[key], 'manifest config ' + key)
    require(all(config['resources'][k] == v for k, v in expected['resources'].items()), 'manifest resources')
    require(record['analysis']['logical_digest'] == analysis['logical_digest'], 'manifest digest')
    require(all(record['analysis'][k] == analysis[k] for k in
                ('rows', 'seed', 'workers', 'memory_budget_bytes', 'stages', 'output_files', 'output_csv_bytes')),
            'manifest analysis mismatch')
    seen, fingerprint, paths = bytearray(rows), [], set()
    total_bytes, encountered = 0, 0
    for entry in entries[1:]:
        require(entry['type'] == 'output', 'unexpected manifest record')
        raw_path = output / entry['path']
        require(not any(p.is_symlink() for p in (raw_path, *raw_path.parents)), 'output symlink')
        path = raw_path.resolve()
        require(path.is_relative_to(output.resolve()) and path not in paths, 'output path')
        paths.add(path)
        require(path.stat().st_size == entry['csv_bytes'] == entry['stored_bytes'] <= 262144, 'encoded cap/metadata')
        require(entry['compressed_target_exceeded'] is False, 'unexpected compression')
        total_bytes += entry['csv_bytes']
        count = 0
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.reader(stream)
            require(next(reader) == ['id', 'key', 'payload'], 'header')
            for row in reader:
                i = int(row[0])
                require(0 <= i < rows and not seen[i] and row == fields(case, i, rows), 'row conservation/fields')
                if case == 'small':
                    require(i == encountered, 'direct order')
                for step in entry['lineage']:
                    if 'values' in step:
                        require(case == 'skew' and step['operation'] == 1 and step['values'] == [row[1]], 'partition membership')
                require(case != 'skew' or any(s.get('operation') == 1 and s.get('values') == [row[1]] for s in entry['lineage']), 'missing partition lineage')
                seen[i] = 1
                encountered += 1
                count += 1
        require(count == entry['rows'] and 0 < count <= 2000, 'row cap/metadata')
        fingerprint.append([entry, sha(path)])
    require(all(seen), 'missing IDs')
    require(analysis['output_files'] == len(paths) and analysis['output_csv_bytes'] == total_bytes, 'analysis output totals')
    require({p.resolve() for p in output.rglob('*') if p.is_file()} == paths | {(output / 'manifest.jsonl').resolve()}, 'unlisted output/staging files')
    return [fingerprint, analysis['logical_digest'], analysis['stages']]


def coverage(analysis, case):
    if case == 'small':
        return
    d = analysis['diagnostics']
    require(d['sort_calls'] > 0 and d['sort_rows'] > 4095 * d['sort_calls'],
            'missing proof of >=4096-row sort dispatch; retain and stop, no resize')
    if case == 'external':
        require(d['sort_runs'] > 0 and d['merge_operations'] > 0, 'external run/merge coverage missing')


def checked_file(record, key):
    path = Path(record[key])
    require(path.is_absolute() and path.is_file(), 'missing retained artifact: ' + key)
    require(sha(path) == record[key + '_sha256'], 'stale retained artifact: ' + key)
    return path


def control_records(text):
    records = []
    for line in text.splitlines():
        if CONTROL_PREFIX in line:
            records.append(json.loads(line.split(CONTROL_PREFIX, 1)[1]))
    expected = [('D1', 'local', 1, 1), ('D2', 'local', 0, 4),
                ('D3', 'shared', 1, 1), ('D4', 'shared', 0, 4)]
    require(len(records) == 4, 'denial controls require exactly four records')
    for record, (identifier, kind, requested, resolved) in zip(records, expected):
        require(all(record.get(k) == v for k, v in {
            'id': identifier, 'kind': kind, 'requested_workers': requested,
            'resolved_workers': resolved, 'memory_mb': 256, 'passed': True}.items()),
            'failed or incompatible denial control ' + identifier)
        scenarios = record.get('scenarios', [])
        require(len(scenarios) == 4, 'missing exact denial scenarios')
        for scenario, (phase, cancelled) in zip(scenarios, [
                ('Reading and validating CSV', False), ('Finalizing output snapshot', False),
                ('Serializing output', False), ('Finalizing output snapshot', True)]):
            require(all(scenario.get(k) == v for k, v in {
                'phase': phase, 'cancelled': cancelled, 'local_limit_bytes': 128 * 1024**2,
                'pool_limit_bytes': (64 if kind == 'shared' else 256) * 1024**2,
                'remaining_bytes': 0, 'cleanup_verified': True,
                'error': 'cancelled' if cancelled else kind}.items()), 'incompatible denial injection')
            require(type(scenario.get('grant_bytes')) is int and 0 < scenario['grant_bytes']
                    <= scenario['pool_limit_bytes'], 'missing exact denial grant')
            require(scenario.get('rows') == (65536 if phase == 'Serializing output' else
                    5000 if phase == 'Finalizing output snapshot' else 0), 'denial emission boundary')
    require('test result: ok. 1 passed; 0 failed;' in text,
            'denial controls lack successful exact test result')
    return records


def validate_controls(report, identity, binary):
    require(report.get('schema') == 1 and report.get('exit_code') == 0, 'failed denial controls report')
    require(report.get('source_sha256') == identity['source_sha256'], 'stale denial controls source inventory')
    test_binary = checked_file(report, 'test_binary')
    build = report.get('test_build', {})
    require(build.get('source_sha256') == identity['source_sha256'] and build.get('features') == []
            and build.get('binary_sha256') == sha(test_binary), 'missing matching test build provenance')
    require(build.get('exit_code') == 0 and build.get('toolchains'), 'failed test build')
    command = build.get('command', [])
    require(all(v in command for v in ('test', '--locked', '--lib', '--no-run', '-p', 'chopper'))
            and not any(v.startswith(('--features', '--all-features')) for v in command), 'test build command')
    require(build.get('logs'), 'missing test build logs')
    for log in build['logs']:
        checked_file(log, 'path')
    require(test_binary.resolve() != binary.resolve() and sha(test_binary) != sha(binary),
            'test-hook and production binary must be separate artifacts')
    require(report.get('command') == [str(test_binary), CONTROL_FILTER + 'complete_run_worker_denials',
                                    '--exact', '--nocapture'], 'unexpected denial controls command')
    stdout = checked_file(report, 'stdout')
    checked_file(report, 'stderr')
    require(control_records(stdout.read_text(encoding='utf-8')) == report.get('records'),
            'denial controls report differs from retained test output')


def validate_build(proof, identity):
    require(proof.get('features') == [] and proof.get('binary_sha256') == identity.get('binary_sha256'),
            'build binary/features mismatch')
    require(proof.get('source_sha256') == identity['source_sha256'], 'build source inventory mismatch')
    require(proof.get('profile') == 'release' and proof.get('toolchains'), 'incomplete release build provenance')
    commands = proof.get('commands', [])
    require(commands and all(isinstance(c, list) for c in commands), 'build commands require argument arrays')
    require(any('build' in c and '--release' in c and '--locked' in c and '-p' in c
                and c[c.index('-p') + 1] == 'chopper' for c in commands), 'missing locked release build command')
    require(not any(any(v.startswith(('--features', '--all-features', '--tests', '--lib')) for v in c) for c in commands),
            'production proof includes test hooks/features')
    outcomes = proof.get('outcomes', [])
    require(outcomes and all(v == 0 or isinstance(v, dict) and v.get('exit_code') == 0
                            and v.get('status') == 'passed' for v in outcomes), 'failed build outcome')
    require(proof.get('build_logs'), 'missing retained build logs')
    for log in proof['build_logs']:
        checked_file(log, 'path')


def validate_attestations(value):
    require(all(value.get(k) for k in ('os_build', 'volume_device', 'background_cache')), 'missing launch attestations')
    require(type(value.get('cpu_available')) is int and value['cpu_available'] >= 4, 'CPU availability ineligible')
    require(value.get('filesystem') == 'NTFS' and value.get('storage') == 'NVMe', 'storage mapping ineligible')
    require(type(value.get('free_space_bytes')) is int and value['free_space_bytes'] >= DISK_BYTES,
            'insufficient attested free space')
    require(value.get('no_concurrent_work') is True, 'concurrent work launch blocker')


def freeze(binary=None, build_proof=None, controls=None, attestations=None):
    blockers = []
    identity = identities(binary)
    proof = None
    if build_proof:
        proof = json.loads(build_proof.read_text(encoding='utf-8'))
        validate_build(proof, identity)
    else:
        blockers.append('B1: stable default release binary and matching source/toolchain/build record not supplied')
    control = None
    if controls:
        require(binary is not None, 'denial controls require production binary')
        control = json.loads(controls.read_text(encoding='utf-8'))
        validate_controls(control, identity, binary)
    else:
        blockers.extend(BLOCKERS)
    attested = None
    if attestations:
        attested = json.loads(attestations.read_text(encoding='utf-8'))
        validate_attestations(attested)
    else:
        blockers.append('L1: host/storage/background launch attestations not supplied')
    return {'schema': 1, 'status': 'blocked' if blockers else 'ready', 'blockers': blockers,
            'identity': identity, 'binary': str(binary.resolve()) if binary else None,
            'build_proof': proof, 'build_proof_sha256': sha(build_proof) if build_proof else None,
            'build_proof_path': str(build_proof.resolve()) if build_proof else None,
            'controls': control, 'controls_path': str(controls.resolve()) if controls else None,
            'controls_sha256': sha(controls) if controls else None,
            'attestations': attested, 'attestations_path': str(attestations.resolve()) if attestations else None,
            'attestations_sha256': sha(attestations) if attestations else None,
            'cases': CASES, 'schedule': schedule(), 'jobs_max': 24, 'attempt_seconds': 60,
            'batch_seconds': 600, 'disk_bytes': DISK_BYTES, 'shared_limit_mb': 64,
            'platform': platform.platform(), 'python': platform.python_version(),
            'cache': 'warm/uncontrolled; generation and verification outside CLI clock',
            'counters': 'Win32 CPU/peak working set/process transfer; no physical IO claim',
            'environment_required_before_launch': ['OS build', 'CPU availability >=4', 'NTFS/NVMe volume/device mapping',
                'free space >=2GiB', 'background/cache conditions', 'no concurrent builds/tests/experiments'],
            'denial_controls': 'D1-D4 exact native test executable; rerun untimed before fixtures; never measurement executable'}


def run(plan, work):
    # Generation/prelaunch failures need the same durable stop marker as job
    # failures. Never write into an existing tree rejected by exclusive mkdir.
    existed = work.exists()
    try:
        return run_panel(plan, work)
    except BaseException as error:
        if not existed and work.is_dir() and not (work / 'STOP.json').exists():
            write_json(work / 'STOP.json', {'attempt': 'preparation-or-finalization',
                       'error': f'{type(error).__name__}: {error}', 'no_retry': True})
        raise


def run_panel(plan, work):
    require(plan.get('controls') is not None, 'denial controls report required regardless of claimed readiness')
    require(not plan['blockers'] and plan['status'] == 'ready', 'launch blocked: ' + '; '.join(plan['blockers']))
    require(platform.system() == 'Windows', 'native Windows panel only')
    binary = Path(plan['binary'])
    assert_identity(plan['identity'], binary)
    # Reconstruct every readiness condition; a hand-edited ready flag grants nothing.
    for key in ('build_proof', 'controls', 'attestations'):
        path = Path(plan[key + '_path'])
        require(sha(path) == plan[key + '_sha256'] and json.loads(path.read_text(encoding='utf-8')) == plan[key],
                'stale ' + key + ' report')
    validate_build(plan['build_proof'], plan['identity'])
    validate_controls(plan['controls'], plan['identity'], binary)
    validate_attestations(plan['attestations'])
    require(plan['cases'] == [list(c) for c in CASES] or plan['cases'] == CASES, 'frozen recipe drift')
    require(plan['schedule'] == [list(c) for c in schedule()] or plan['schedule'] == schedule(), 'frozen schedule drift')
    require(all(plan.get(k) == v for k, v in {'jobs_max':24, 'attempt_seconds':60,
                'batch_seconds':600, 'disk_bytes':DISK_BYTES, 'shared_limit_mb':64}.items()), 'frozen ceilings drift')
    require(shutil.disk_usage(work.parent).free >= DISK_BYTES, 'less than 2GiB free before launch')
    work.mkdir()  # retained attempt tree, never reused
    counters = load('benchmark-windows')
    deadline = time.monotonic() + 600
    try:
        folder = work / 'untimed-denial-controls'
        attempt(plan['controls']['command'], folder, dict(os.environ), deadline,
                guard=lambda: budget(work, deadline), counter=counters.counters)
        require(control_records((folder / 'stdout.log').read_text(encoding='utf-8')) == plan['controls']['records'],
                'rerun denial controls differ from frozen report')
        validate_controls(plan['controls'], plan['identity'], binary)
        assert_identity(plan['identity'], binary)
    except BaseException as error:
        write_json(work / 'STOP.json', {'attempt': 'untimed-denial-controls', 'error': str(error), 'no_retry': True})
        raise
    references = {}
    fixtures, samples = {}, {}
    # Freeze every generated input before the first CLI launch. Their cache
    # effects are deliberately uncontrolled and recorded in the frozen design.
    for case, rows in CASES:
        source = work / (case + '.csv')
        with source.open('x', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['id', 'key', 'payload'])
            for i in range(rows):
                writer.writerow(fields(case, i, rows))
                if i % 4096 == 0:
                    budget(work, deadline)
        fixtures[case] = sha(source)
        write_json(work / (case + '-fixture.json'), {'rows': rows, 'sha256': fixtures[case], 'bytes': source.stat().st_size})
    for index, (case, rows, rep, workers) in enumerate(schedule()):
        require(index < 24, 'job ceiling')
        assert_identity(plan['identity'], binary)
        budget(work, deadline)
        source = work / (case + '.csv')
        require(sha(source) == fixtures[case], 'fixture identity drift')
        name = f'{index + 1:02}-{case}-{rep}-W{workers}'
        output, temp = work / (name + '-output'), work / (name + '-temp')
        temp.mkdir()
        config = work / (name + '.json')
        write_json(config, job_for(case, source, output, temp, workers))
        config_hash = sha(config)
        command = [str(binary), 'run', '--config', str(config.resolve()), '--yes']
        folder = work / name
        try:
            outcome = attempt(command, folder, dict(os.environ, CHOPPER_MEMORY_LIMIT_MB='64'), deadline,
                    guard=lambda: budget(work, deadline), counter=counters.counters)
            assert_identity(plan['identity'], binary)
            require(sha(source) == fixtures[case] and sha(config) == config_hash, 'fixture/config drift')
            analysis = json.loads((folder / 'stdout.log').read_text(encoding='utf-8'))
            identity = verify(output, temp, analysis, case, rows, workers, source)
            if case in references:
                require(identity == references[case], 'exact bytes/order/lineage/stages/digest parity mismatch')
            references.setdefault(case, identity)
            coverage(analysis, case)
            samples.setdefault(case, {}).setdefault(str(workers), []).append(outcome['seconds'])
            write_json(folder / 'verification.json', {'verified': True, 'config_sha256': sha(config),
                'output_identity_sha256': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()})
            budget(work, deadline)
        except BaseException as error:
            write_json(work / 'STOP.json', {'attempt': name, 'error': str(error), 'no_retry': True})
            raise
    write_json(work / 'summary.json', {case: {'samples': values,
        'median': {k: statistics.median(v) for k, v in values.items()},
        'min_max': {k: [min(v), max(v)] for k, v in values.items()},
        'paired_W0_minus_W1_seconds': [a - b for a, b in zip(values['0'], values['1'])]}
        for case, values in samples.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--freeze', type=Path)
    action.add_argument('--run', type=Path)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--build-proof', type=Path)
    parser.add_argument('--controls', type=Path)
    parser.add_argument('--attestations', type=Path)
    parser.add_argument('--work', type=Path)
    args = parser.parse_args()
    if args.freeze:
        write_json(args.freeze, freeze(args.binary, args.build_proof, args.controls, args.attestations))
    else:
        require(args.work is not None, '--work required')
        run(json.loads(args.run.read_text(encoding='utf-8')), args.work.resolve())


if __name__ == '__main__':
    main()
