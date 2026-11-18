"""Native exact-fusion CSV/encoding/cap/failure controls, separate from timings."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.request


def emit(record):
    print(json.dumps(record), flush=True)


def fields(index):
    key = ['g', 'g\0', 'g\0界'][index % 3]
    payload = '' if index % 5 == 0 else '001 / NA / null / 2026-10-16\t, "界"\nnext'
    return [str(index), key, payload]


def snapshot_control(binary, job, source, output, temp, fingerprint):
    process = subprocess.Popen([str(binary), 'serve', '--port', '0'], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        line = process.stdout.readline().strip()
        assert line.startswith('Chopper local UI: http://127.0.0.1:')
        origin, token = line.removeprefix('Chopper local UI: ').split('/#token=')
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(path, payload=None):
            data = None if payload is None else json.dumps(payload).encode()
            req = urllib.request.Request(origin + path, data=data, headers={
                'X-Chopper-Token': token, 'Content-Type': 'application/json'})
            with client.open(req, timeout=5) as response:
                return json.load(response)

        def wait_for(status):
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                state = request('/api/state')
                assert state['status'] not in ['failed', 'cancelled'], state.get('error')
                if state['status'] == status:
                    return state
                time.sleep(0.02)
            raise TimeoutError('local preparation/publication did not finish')

        request('/api/analyze', job)
        analysis = wait_for('ready')['analysis']
        source.write_text('corrupted source after preparation')
        request('/api/run', {})
        wait_for('complete')
        assert not list(temp.iterdir()), 'retained preparation leaked temporary data'
        return fingerprint(output, analysis, 'none'), analysis['diagnostics']
    finally:
        process.terminate()
        process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--snapshot', action='store_true', help='also test source changes through a local analysis/confirmation server')
    args = parser.parse_args()
    variants = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    emit({'type': 'environment', 'binary_sha256': {
        k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in variants.items()}})
    with tempfile.TemporaryDirectory(prefix='chopper-exact-fusion-controls-') as directory:
        root = Path(directory)
        source, output, temp, config = (root / p for p in ['input.csv', 'output', 'temp', 'job.json'])
        temp.mkdir()
        leading_fingerprint = None
        for case in ['leading', 'later', 'no_header', 'utf16', 'empty', 'strict_cap', 'max_files', 'malformed', 'ambiguous']:
            with source.open('w', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                if case != 'no_header':
                    writer.writerow(['id', 'key', 'key' if case == 'ambiguous' else 'payload'])
                if case != 'empty':
                    writer.writerows(fields(i) for i in range(120))
            if case == 'malformed':
                with source.open('a') as stream:
                    stream.write('120,g,"unterminated')
            shuffle = {'type': 'shuffle', 'strategy': 'uniform'}
            operations = ([{'type': 'balanced', 'files': 4}] if case == 'later' else [])
            operations += [shuffle, {'type': 'partition', 'columns': [1 if case == 'no_header' else 'key']}]
            if case == 'empty':
                operations.insert(0, shuffle)
            cap = 20 if case == 'strict_cap' else 160 if case == 'utf16' else 128
            job = {'input': str(source), 'output': str(output), 'seed': 'exact-fusion-controls-v1',
                   'operations': operations, 'limits': {'bytes': cap},
                   'input_csv': {'headers': case != 'no_header'},
                   'output_csv': {'headers': case != 'no_header', 'encoding': 'utf-16le' if case == 'utf16' else 'utf-8',
                                  'bom': case == 'utf16'},
                   'resources': {'memory_mb': 32, 'workers': 4, 'max_record_bytes': 2097152,
                                 'max_files': 2 if case == 'max_files' else 1000000, 'temp_dir': str(temp)}}
            config.write_text(json.dumps(job))
            reference = None
            for variant, binary in variants.items():
                result = subprocess.run([str(binary), 'run', '--config', str(config), '--yes'],
                                        text=True, capture_output=True, timeout=60)
                assert not list(temp.iterdir()), 'temporary leak'
                if case in ['strict_cap', 'max_files', 'malformed', 'ambiguous']:
                    assert result.returncode and not output.exists(), result.stderr
                    terms = {'strict_cap': ['cap', 'limit'], 'max_files': ['max_files'], 'malformed': ['quoted', 'unterminated'],
                             'ambiguous': ['ambiguous']}[case]
                    assert any(term in result.stderr for term in terms), result.stderr
                    emit({'type': 'control', 'case': case, 'variant': variant, 'outcome': 'clean rejection',
                          'verified': True, 'error': result.stderr.strip()})
                    continue
                assert result.returncode == 0, result.stderr
                analysis = json.loads(result.stdout)
                fingerprint = pipelines.fingerprint(output, analysis, 'none')
                if reference is not None:
                    assert fingerprint == reference
                reference = fingerprint
                if case == 'leading':
                    leading_fingerprint = fingerprint
                entries = [entry for entry in map(json.loads, (output / 'manifest.jsonl').read_text().splitlines())
                           if entry['type'] == 'output']
                seen = set()
                for entry in entries:
                    path = output / entry['path']
                    assert path.stat().st_size == entry['csv_bytes'] <= cap
                    with path.open(encoding='utf-16' if case == 'utf16' else 'utf-8', newline='') as stream:
                        records = csv.reader(stream)
                        if case != 'no_header':
                            assert next(records) == ['id', 'key', 'payload']
                        count = 0
                        for record in records:
                            index = int(record[0])
                            assert 0 <= index < 120 and index not in seen and record == fields(index)
                            assert next(step['values'] for step in entry['lineage'] if 'values' in step) == [record[1]]
                            if case == 'later':
                                part = entry['lineage'][0]['part'] - 1
                                assert part * 30 <= index < (part + 1) * 30
                            seen.add(index)
                            count += 1
                        assert count == entry['rows']
                assert seen == (set() if case == 'empty' else set(range(120)))
                diag = analysis['diagnostics']
                if variant == 'candidate':
                    assert diag['shuffle_partition_fusions'] == (4 if case == 'later' else 1)
                assert diag['workspace_reserved_bytes'] == diag['temporary_path_reserved_bytes'] + diag['input_header_reserved_bytes']
                emit({'type': 'control', 'case': case, 'variant': variant, 'outcome': 'success', 'verified': True,
                      'fingerprint': fingerprint, 'files': len(entries), 'diagnostics': diag})
                shutil.rmtree(output)
        if args.snapshot:
            # The last job has the same settings as the leading control. Restore
            # the valid original header/data before each independent preparation.
            for variant, binary in variants.items():
                with source.open('w', newline='') as stream:
                    writer = csv.writer(stream, lineterminator='\n')
                    writer.writerow(['id', 'key', 'payload'])
                    writer.writerows(fields(i) for i in range(120))
                actual, diagnostics = snapshot_control(binary, job, source, output, temp, pipelines.fingerprint)
                assert actual == leading_fingerprint, 'confirmation did not export the exact retained original snapshot'
                if variant == 'candidate':
                    assert diagnostics['shuffle_partition_fusions'] == 1
                emit({'type': 'control', 'case': 'retained_snapshot', 'variant': variant,
                      'outcome': 'success', 'verified': True, 'fingerprint': actual,
                      'source_changed_after_preparation': True, 'diagnostics': diagnostics})
                shutil.rmtree(output)


if __name__ == '__main__':
    main()
