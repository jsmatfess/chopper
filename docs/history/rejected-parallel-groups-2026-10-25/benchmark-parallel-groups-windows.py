"""Bounded E2 native Windows evidence. Existing historical callers are unchanged.

Run gates first, then timings with the same work directory and immutable binaries.
All attempts/configs/logs/outputs survive failure. Successful owned trees are removed
only after verification. Process transfers include cache; physical I/O is unknown.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import threading
import time


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).resolve().parent
external = load('external_e2', HERE / 'benchmark-external-shuffle.py')
windows = load('windows_e2', HERE / 'benchmark-windows.py')
CELLS = {'A': (300000, 'columns', 4), 'B': (300000, 'skew', 3),
         'C': (6400, 'columns', 64)}
HEADER = ['id', 'payload'] + [f'c{i}' for i in range(31)]
SEED = 'external-comparison-v1'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def owners(analysis):
    d = analysis['diagnostics']
    keys = ['temporary_path_reserved_bytes', 'directory_path_reserved_bytes',
            'input_header_reserved_bytes', 'prepared_job_reserved_bytes',
            'analysis_preview_reserved_bytes', 'column_values_reserved_bytes',
            'stage_stats_reserved_bytes', 'analysis_text_reserved_bytes',
            'analysis_warnings_reserved_bytes', 'analysis_timings_reserved_bytes',
            'analysis_diagnostics_reserved_bytes']
    assert all(type(d[k]) is int and d[k] >= 0 for k in keys)
    assert d['workspace_reserved_bytes'] == sum(d[k] for k in keys) + external.audit_reserved_bytes(d)
    assert d['peak_workspace_reserved_bytes'] <= analysis['memory_budget_bytes'] // 2
    assert d['process_memory']['limit_bytes'] == 64 * 1024 * 1024


class Space:
    """Sequential file-size walk; each sample is non-atomic, a lower bound."""
    def __init__(self, root):
        self.root = root
        self.stop = threading.Event()
        self.records = []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def sample(self):
        record = {'start_ns': time.time_ns(), 'bytes': 0, 'errors': []}
        def onerror(error):
            record['errors'].append(repr(error))
        for directory, _, names in os.walk(self.root, onerror=onerror):
            for name in names:
                try:
                    record['bytes'] += (Path(directory) / name).stat().st_size
                except OSError as error:
                    record['errors'].append(repr(error))
        record['end_ns'] = time.time_ns()
        self.records.append(record)

    def run(self):
        while not self.stop.is_set():
            self.sample()
            self.stop.wait(.02)

    def finish(self):
        self.stop.set()
        self.thread.join()
        self.sample()
        return {'peak_logical_bytes': max(r['bytes'] for r in self.records),
                'interval_seconds': .02, 'samples': self.records,
                'scope': 'simultaneous owned temp/staging/output tree; excludes fixtures/config/logs; sequential non-atomic lower bound, sampler interference possible'}


def verify(output, analysis, shape, rows, groups, cap, empty=False):
    owners(analysis)
    assert analysis['seed'] == SEED
    seen = bytearray(rows)
    entries = [json.loads(s) for s in (output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    job = entries[0]
    assert job['type'] == 'job' and job['schema_version'] == 1
    assert job['algorithm_version'] == 'chopper-v1-blake3-1'
    assert job['config']['seed'] == SEED
    assert job['analysis']['logical_digest'] == analysis['logical_digest']
    outputs = [e for e in entries if e['type'] == 'output']
    assert len(outputs) == groups
    fingerprint = hashlib.sha256()
    fingerprint.update(json.dumps(analysis['stages'], sort_keys=True).encode())
    fingerprint.update(analysis['logical_digest'].encode())
    counts = []
    for index, entry in enumerate(outputs):
        path = output / entry['path']
        assert path.stat().st_size == entry['csv_bytes'] == entry['stored_bytes']
        assert path.stat().st_size <= cap
        fingerprint.update(json.dumps({k: entry[k] for k in ('path', 'rows', 'csv_bytes', 'lineage')}, sort_keys=True).encode())
        fingerprint.update(path.read_bytes())
        count = 0
        with path.open(encoding='utf-8', newline='') as stream:
            reader = csv.reader(stream)
            assert next(reader) == HEADER
            for record in reader:
                row = int(record[0])
                assert 0 <= row < rows and not seen[row]
                assert record == external.fields(row, shape)
                if shape == 'skew':
                    assert entry['lineage'][0]['values'] == [record[1]]
                    assert entry['lineage'][1]['part'] == 1
                elif not empty:
                    parent = entry['lineage'][0]['part'] - 1
                    assert parent == index
                    start = parent * (rows // groups) + min(parent, rows % groups)
                    assert start <= row < start + rows // groups + int(parent < rows % groups)
                seen[row] = 1
                count += 1
        assert count == entry['rows']
        counts.append(count)
    assert all(seen) and analysis['rows'] == rows
    if shape == 'skew':
        assert counts == [rows * 90 // 100, rows * 9 // 100, rows // 100]
    if empty:
        assert sorted(counts) == [0, rows]
    assert set(p.name for p in output.iterdir()) == {'manifest.jsonl', *(e['path'] for e in outputs)}
    return {'fingerprint': fingerprint.hexdigest(), 'counts': counts,
            'manifest_sha256': sha(output / 'manifest.jsonl'),
            'csv_sha256': {e['path']: sha(output / e['path']) for e in outputs}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--mode', choices=['gates', 'timings'], required=True)
    args = parser.parse_args()
    assert os.name == 'nt'
    root = args.work_dir.resolve()
    root.mkdir(exist_ok=True)
    csv.field_size_limit(2097152)
    binaries = {k: getattr(args, k).resolve() for k in ('baseline', 'candidate')}
    env = {k: v for k, v in os.environ.items() if not k.startswith('CHOPPER_')}
    env['CHOPPER_MEMORY_LIMIT_MB'] = '64'
    identity = {'binaries': {k: sha(p) for k, p in binaries.items()},
                'harnesses': {str(p): sha(p) for p in (Path(__file__), Path(external.__file__), Path(windows.__file__))},
                'environment': {k: v for k, v in env.items() if k.startswith('CHOPPER_')},
                'cache': 'warm/uncontrolled; no cache eviction', 'physical_io_bytes': None,
                'allocation_census': None,
                'scope': 'CLI startup through preparation, optional failed work/replay, encoded outputs, atomic publication and process exit; setup/verification/disposal excluded'}
    save(root / (args.mode + '-identity.json'), identity)
    if args.mode == 'timings':
        gate = json.loads((root / 'gates-passed.json').read_text(encoding='utf-8'))
        assert gate == identity, 'gate/build/harness drift'

    def fixture(label, rows, shape):
        path = root / ('fixture-' + label + '.csv')
        if not path.exists():
            with path.open('x', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                writer.writerow(HEADER)
                writer.writerows(external.fields(i, shape) for i in range(rows))
            save(root / ('fixture-' + label + '.json'), {'rows': rows, 'shape': shape,
                 'sha256': sha(path), 'bytes': path.stat().st_size})
        metadata = json.loads((root / ('fixture-' + label + '.json')).read_text(encoding='utf-8'))
        assert metadata == {'rows': rows, 'shape': shape, 'sha256': sha(path), 'bytes': path.stat().st_size}
        return path

    def run(label, variant, source, rows, shape, groups, workers=4, cap=100000000,
            empty=False, reject=False, reference=None):
        attempt = root / label / variant
        attempt.mkdir(parents=True, exist_ok=False)
        owned = attempt / 'owned'
        owned.mkdir()
        temp = owned / 'temp'
        temp.mkdir()
        output = owned / 'output'
        operations = ([{'type': 'partition', 'columns': ['payload']}, {'type': 'balanced', 'files': 1}]
                      if shape == 'skew' else [{'type': 'balanced', 'files': groups}])
        if empty:
            operations = [{'type': 'assign', 'groups': [{'name': 'all', 'percent': '100'}, {'name': 'empty', 'percent': '0'}]},
                          {'type': 'shuffle', 'strategy': 'fisher_yates'}]
        operations += [{'type': 'shuffle', 'strategy': 'uniform'}]
        dialect = {'encoding': 'utf-8', 'headers': True, 'delimiter': ',', 'quote': '"',
                   'escape': None, 'line_ending': 'lf', 'bom': False, 'skip_empty_lines': False}
        job = {'input': str(source), 'output': str(output), 'seed': SEED,
               'compression': 'none', 'full_shuffle_policy': 'seeded_v1',
               'input_csv': dialect, 'output_csv': dialect, 'operations': operations,
               'limits': {'bytes': cap}, 'resources': {'memory_mb': 32, 'workers': workers,
                   'max_record_bytes': 2097152, 'temp_dir': str(temp)}}
        config = attempt / 'config.json'
        save(config, job)
        command = [str(binaries[variant]), 'run', '--config', str(config), '--yes']
        sampler = Space(owned)
        sampler.thread.start()
        record = {'command': command, 'started_ns': time.time_ns(), 'verified': False}
        process = None
        try:
            with (attempt / 'stdout').open('xb') as stdout, (attempt / 'stderr').open('xb') as stderr:
                start = time.perf_counter()
                process = subprocess.Popen(command, stdout=stdout, stderr=stderr, env=env)
                process.wait(timeout=180)
                record.update(seconds=time.perf_counter() - start, returncode=process.returncode)
                try:
                    record.update(windows.counters(process))
                except OSError as error:
                    record.update(cpu_seconds=None, peak_working_set_bytes=None, process_io=None,
                                  counters_error=repr(error))
            record['storage'] = sampler.finish()
            save(attempt / 'raw-result.json', record)
            assert not list(temp.iterdir()), 'temporary leak'
            assert set(owned.iterdir()) == ({temp} if reject else {temp, output}), 'publication cleanup mismatch'
            if reject:
                assert process.returncode != 0 and not output.exists()
                error = (attempt / 'stderr').read_text(encoding='utf-8')
                assert 'cap' in error or 'limit' in error
            else:
                assert process.returncode == 0, (attempt / 'stderr').read_text(encoding='utf-8')
                analysis = json.loads((attempt / 'stdout').read_text(encoding='utf-8'))
                record['verification'] = verify(output, analysis, shape, rows, groups, cap, empty)
                if reference is not None:
                    assert {k: v for k, v in record['verification'].items() if k != 'manifest_sha256'} == {k: v for k, v in reference.items() if k != 'manifest_sha256'}, 'exact parity mismatch'
                d = analysis['diagnostics']
                expected_groups = groups if variant == 'candidate' and workers > 1 and groups > 1 else 0
                if expected_groups % 4 == 1:
                    expected_groups -= 1
                assert d['parallel_groups'] == expected_groups
                assert d['parallel_group_batches'] == (expected_groups + 3) // 4
                assert d['parallel_group_retries'] == 0
                record.update(diagnostics=d, timings=analysis['timings'], peak_temp_bytes=analysis['peak_temp_bytes'])
            record['verified'] = True
            save(attempt / 'verified.json', record)
            shutil.rmtree(owned)
            return record
        except BaseException as error:
            if process is not None and process.poll() is None:
                process.kill()
                process.wait()
            if sampler.thread.is_alive():
                record['storage'] = sampler.finish()
            record['failure'] = repr(error)
            save(attempt / 'failure.json', record)
            raise

    if args.mode == 'gates':
        controls = [('worker1', 40, 4, 1, False, False, 100000000),
                    ('single-parent', 40, 1, 4, False, False, 100000000),
                    ('remainder', 40, 5, 4, False, False, 100000000),
                    ('empty', 40, 2, 4, True, False, 100000000)]
        for label, rows, groups, workers, empty, reject, cap in controls:
            source = fixture(label, rows, 'columns')
            b = run(label, 'baseline', source, rows, 'columns', groups, workers, cap, empty, reject)
            c = run(label, 'candidate', source, rows, 'columns', groups, workers, cap, empty, reject, b['verification'])
            assert {k: v for k, v in b['verification'].items() if k != 'manifest_sha256'} == {k: v for k, v in c['verification'].items() if k != 'manifest_sha256'}
        # Bind the cap exactly to a complete singleton CSV (header included).
        source = fixture('cap', 8, 'columns')
        with source.open(encoding='utf-8', newline='') as stream:
            records = list(csv.reader(stream))
        import io
        stream = io.StringIO(newline='')
        csv.writer(stream, lineterminator='\n').writerows(records[:2])
        cap = len(stream.getvalue().encode('utf-8'))
        for reject in (False, True):
            for variant in binaries:
                run('cap-' + str(reject), variant, source, 8, 'columns', 8,
                    cap=cap - int(reject), reject=reject)
        for cell, (rows, shape, groups) in CELLS.items():
            source = fixture(cell, rows, shape)
            b = run('parity-' + cell, 'baseline', source, rows, shape, groups)
            c = run('parity-' + cell, 'candidate', source, rows, shape, groups, reference=b['verification'])
            # Manifest job output paths differ; compare only invariant fields/CSV.
            assert {k: v for k, v in b['verification'].items() if k != 'manifest_sha256'} == {k: v for k, v in c['verification'].items() if k != 'manifest_sha256'}
        save(root / 'gates-passed.json', identity)
    else:
        summaries = {}
        for cell, (rows, shape, groups) in CELLS.items():
            samples = {'baseline': [], 'candidate': []}
            reference = json.loads((root / ('parity-' + cell) / 'baseline/verified.json').read_text(encoding='utf-8'))['verification']
            for repeat in range(3):
                for variant in (['baseline', 'candidate'] if repeat % 2 == 0 else ['candidate', 'baseline']):
                    record = run(f'timed-{cell}-{repeat + 1}', variant, fixture(cell, rows, shape), rows, shape, groups, reference=reference)
                    assert {k: v for k, v in record['verification'].items() if k != 'manifest_sha256'} == {k: v for k, v in reference.items() if k != 'manifest_sha256'}
                    samples[variant].append(record)
            summaries[cell] = {variant: {'n': len(values), 'median_seconds': statistics.median(v['seconds'] for v in values),
                'range_seconds': [min(v['seconds'] for v in values), max(v['seconds'] for v in values)]} for variant, values in samples.items()}
        save(root / 'summary.json', summaries)


if __name__ == '__main__':
    main()
