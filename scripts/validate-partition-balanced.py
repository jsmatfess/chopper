"""Complete-job partition/uniform/balanced parity, fallback and rejection controls."""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('pipelines', Path(__file__).with_name('benchmark-pipelines.py'))
    pipelines = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipelines)
    with tempfile.TemporaryDirectory(prefix='chopper-triple-controls-') as directory:
        root = Path(directory)
        source, output, temp, config = (root / p for p in ['input.csv', 'output', 'temp', 'job.json'])
        temp.mkdir()
        for case in ['leading', 'parents', 'downstream', 'repeat', 'skew', 'high_fanout', 'late_fallback', 'wide_key', 'empty', 'named_empty', 'utf16', 'no_header', 'strict_cap', 'max_files', 'insufficient', 'malformed']:
            count = 0 if case == 'empty' else 2400 if case in ('high_fanout', 'late_fallback') else 121
            records = [[str(i), str(i % 3), f'001 / NA / null / "界"\ntext{i % 5}'] for i in range(count)]
            if case == 'high_fanout':
                for i, record in enumerate(records):
                    record[1] = str(i // 3)
            if case == 'late_fallback':
                for i, record in enumerate(records):
                    record[1] = 'common' if i < count // 2 else str(i // 3)
            if case == 'wide_key':
                for record in records:
                    record[1] += '界' * 200000
            if case == 'skew':
                for i, record in enumerate(records):
                    record[1] = 'rare' if i < 9 else 'common'
            with source.open('w', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                if case != 'no_header':
                    writer.writerow(['id', 'key', 'payload'])
                writer.writerows(records)
            if case == 'malformed':
                with source.open('a') as stream:
                    stream.write('122,g,"unterminated')
            shuffle = {'type': 'shuffle', 'strategy': 'uniform'}
            operations = [{'type': 'partition', 'columns': [1 if case == 'no_header' else 'key']}, shuffle]
            if case == 'repeat':
                operations += [shuffle, shuffle]
            operations += [{'type': 'balanced', 'files': 100 if case == 'insufficient' else 3}]
            if case in ('parents', 'late_fallback'):
                operations.insert(0, {'type': 'balanced', 'files': 2})
            if case == 'downstream':
                operations += [shuffle, {'type': 'interleaved', 'files': 2}]
            if case == 'named_empty':
                operations.insert(0, {'type': 'assign_probabilistic', 'groups': [
                    {'name': 'keep', 'percent': '100'}, {'name': 'empty', 'percent': '0'}]})
            job = {'input': str(source), 'output': str(output), 'seed': 'triple-controls-v1',
                   'operations': operations, 'limits': {'bytes': 20 if case == 'strict_cap' else 134217728},
                   'input_csv': {'headers': case != 'no_header'},
                   'output_csv': {'headers': case != 'no_header', 'encoding': 'utf-16le' if case == 'utf16' else 'utf-8', 'bom': case == 'utf16'},
                   'resources': {'memory_mb': 32, 'workers': 4, 'max_record_bytes': 2097152,
                                 'max_files': 4 if case == 'max_files' else 100000, 'temp_dir': str(temp)}}
            config.write_text(json.dumps(job))
            reference = None
            for variant, binary in [('baseline', args.baseline), ('candidate', args.candidate)]:
                result = subprocess.run([str(binary.resolve()), 'run', '--config', str(config), '--yes'],
                                        text=True, capture_output=True, timeout=120)
                assert not list(temp.iterdir()), 'temporary leak'
                if case in ['strict_cap', 'max_files', 'malformed', 'insufficient']:
                    assert result.returncode and not output.exists(), result.stderr
                    print(json.dumps({'case': case, 'variant': variant, 'verified': True, 'outcome': 'clean rejection', 'error': result.stderr.strip()}), flush=True)
                    continue
                assert result.returncode == 0, result.stderr
                analysis = json.loads(result.stdout)
                fingerprint = pipelines.fingerprint(output, analysis, 'none')
                if reference is not None:
                    assert fingerprint == reference, case
                reference = fingerprint
                seen = set()
                csv.field_size_limit(2097152)
                for entry in map(json.loads, (output / 'manifest.jsonl').read_text().splitlines()):
                    if entry['type'] != 'output':
                        continue
                    with (output / entry['path']).open(encoding='utf-16' if case == 'utf16' else 'utf-8', newline='') as stream:
                        reader = csv.reader(stream)
                        if case != 'no_header':
                            assert next(reader) == ['id', 'key', 'payload']
                        for record in reader:
                            index = int(record[0])
                            assert index not in seen and record == records[index]
                            for step in entry['lineage']:
                                if 'values' in step:
                                    assert step['values'] == [record[1]]
                            seen.add(index)
                assert seen == set(range(count))
                print(json.dumps({'case': case, 'variant': variant, 'verified': True, 'outcome': 'success', 'fingerprint': fingerprint, 'analysis': analysis}), flush=True)
                shutil.rmtree(output)


if __name__ == '__main__':
    main()
