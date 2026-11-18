"""Check native independent-group singleton/empty/cap parity and cleanup."""
import argparse
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def emit(record):
    print(json.dumps(record), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        'pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    variants = {'baseline': args.baseline.resolve(), 'candidate': args.candidate.resolve()}
    emit({'type': 'environment', 'binary_sha256': {
        k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in variants.items()}})
    with tempfile.TemporaryDirectory(prefix='chopper-group-edges-') as directory:
        root = Path(directory)
        temp, source, output, config = (root / name for name in
                                        ['temp', 'input.csv', 'output', 'job.json'])
        temp.mkdir()
        payload = 'duplicate, "界"\nnext'
        with source.open('w', newline='') as stream:
            writer = csv.writer(stream, lineterminator='\n')
            writer.writerow(['id', 'payload'])
            writer.writerows([[str(i), payload] for i in range(8)])
        for case in ['singletons', 'empty-allocation', 'strict-cap']:
            operations = [{'type': 'balanced', 'files': 8},
                          {'type': 'shuffle', 'strategy': 'uniform'}]
            if case == 'empty-allocation':
                operations = [
                    {'type': 'assign', 'groups': [
                        {'name': 'all', 'percent': '100'},
                        {'name': 'empty', 'percent': '0'}]},
                    # Break assignment/uniform fusion with an explicit resident shuffle to exercise the empty
                    # group in the candidate's actual independent worker path.
                    {'type': 'shuffle', 'strategy': 'fisher_yates'},
                    {'type': 'shuffle', 'strategy': 'uniform'}]
            job = {'input': str(source), 'output': str(output), 'seed': 'group-edges-v1',
                   'operations': operations, 'limits': {'bytes': 20} if case == 'strict-cap' else {},
                   'resources': {'memory_mb': 32, 'workers': 4,
                                 'max_record_bytes': 2097152, 'temp_dir': str(temp)}}
            config.write_text(json.dumps(job))
            reference = None
            for variant, binary in variants.items():
                result = subprocess.run([str(binary), 'run', '--config', str(config), '--yes'],
                                        text=True, capture_output=True, timeout=60)
                assert not list(temp.iterdir()), 'temporary leak'
                if case == 'strict-cap':
                    assert result.returncode and not output.exists(), result.stderr
                    assert 'cap' in result.stderr or 'limit' in result.stderr, result.stderr
                    emit({'type': 'control', 'case': case, 'variant': variant,
                          'outcome': 'clean rejection', 'verified': True,
                          'error': result.stderr.strip()})
                    continue
                assert result.returncode == 0, result.stderr
                analysis = json.loads(result.stdout)
                fingerprint = pipelines.fingerprint(output, analysis, 'none')
                if reference is not None:
                    assert reference == fingerprint
                reference = fingerprint
                seen, sizes = set(), []
                for path in sorted(output.glob('*.csv')):
                    with path.open(newline='') as stream:
                        records = csv.reader(stream)
                        assert next(records) == ['id', 'payload']
                        count = 0
                        for row in records:
                            index = int(row[0])
                            assert index not in seen and row == [str(index), payload]
                            seen.add(index)
                            count += 1
                        sizes.append(count)
                assert seen == set(range(8))
                assert sorted(sizes) == ([1] * 8 if case == 'singletons' else [0, 8])
                diagnostics = analysis['diagnostics']
                if variant == 'candidate':
                    assert diagnostics['parallel_groups'] == (8 if case == 'singletons' else 2)
                assert diagnostics['workspace_reserved_bytes'] == (
                    diagnostics['temporary_path_reserved_bytes'] + diagnostics['input_header_reserved_bytes'])
                emit({'type': 'control', 'case': case, 'variant': variant,
                      'outcome': 'success', 'verified': True, 'fingerprint': fingerprint,
                      'sizes': sizes, 'diagnostics': diagnostics})
                shutil.rmtree(output)


if __name__ == '__main__':
    main()
