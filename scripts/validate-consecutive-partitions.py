"""Complete-job consecutive-partition parity and clean rejection controls."""
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
    with tempfile.TemporaryDirectory(prefix='chopper-consecutive-controls-') as directory:
        root = Path(directory)
        source, output, temp, config = (root / p for p in ['input.csv', 'output', 'temp', 'job.json'])
        temp.mkdir()
        for case in ['leading', 'chain', 'deep', 'duplicate', 'parents', 'downstream', 'utf16', 'no_header', 'empty', 'named_empty', 'empty_only', 'strict_cap', 'max_files', 'malformed', 'ambiguous']:
            count = 0 if case in ('empty', 'empty_only') else 121
            records = [[str(i), str(i % 3), f'001 / NA / null / "界"\ntext{i % 5}'] for i in range(count)]
            with source.open('w', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                if case != 'no_header':
                    writer.writerow(['id', 'key', 'key' if case == 'ambiguous' else 'payload'])
                writer.writerows(records)
            if case == 'malformed':
                with source.open('a') as stream:
                    stream.write('122,g,"unterminated')
            selected = 1 if case == 'no_header' else 'key'
            partition = {'type': 'partition', 'columns': [selected]}
            second = {'type': 'partition', 'columns': [2 if case == 'no_header' else 'payload']}
            operations = [partition, second]
            if case == 'deep':
                operations = [partition, second] * 32
            if case == 'duplicate':
                operations = [{'type': 'partition', 'columns': [1, 'key']}, {'type': 'partition', 'columns': ['payload', 'key']}]
            if case == 'chain':
                operations += [partition]
            if case == 'parents':
                operations.insert(0, {'type': 'balanced', 'files': 2})
            if case == 'downstream':
                operations += [{'type': 'shuffle', 'strategy': 'uniform'}, {'type': 'balanced', 'files': 2}]
            if case in ('named_empty', 'empty_only'):
                allocation = {'type': 'assign_probabilistic', 'groups': [
                    {'name': 'keep', 'percent': '100'}, {'name': 'empty', 'percent': '0'}]}
                operations.insert(0, allocation)
            job = {'input': str(source), 'output': str(output), 'seed': 'consecutive-controls-v1',
                   'operations': operations, 'limits': {'bytes': 20 if case == 'strict_cap' else 65536},
                   'input_csv': {'headers': case != 'no_header'},
                   'output_csv': {'headers': case != 'no_header', 'encoding': 'utf-16le' if case == 'utf16' else 'utf-8', 'bom': case == 'utf16'},
                   'resources': {'memory_mb': 32, 'workers': 4, 'max_record_bytes': 2097152,
                                 'max_files': 4 if case == 'max_files' else 100000, 'temp_dir': str(temp)}}
            config.write_text(json.dumps(job))
            reference = None
            for variant, binary in [('baseline', args.baseline), ('candidate', args.candidate)]:
                result = subprocess.run([str(binary.resolve()), 'run', '--config', str(config), '--yes'],
                                        text=True, capture_output=True, timeout=60)
                assert not list(temp.iterdir()), 'temporary leak'
                if case in ['strict_cap', 'max_files', 'malformed', 'ambiguous']:
                    assert result.returncode and not output.exists(), result.stderr
                    terms = {'strict_cap': ['cap', 'limit'], 'max_files': ['max_files'],
                             'malformed': ['quoted', 'unterminated'], 'ambiguous': ['ambiguous']}[case]
                    assert any(term in result.stderr for term in terms), result.stderr
                    print(json.dumps({'case': case, 'variant': variant, 'verified': True, 'outcome': 'clean rejection', 'error': result.stderr.strip()}), flush=True)
                    continue
                assert result.returncode == 0, result.stderr
                analysis = json.loads(result.stdout)
                fingerprint = pipelines.fingerprint(output, analysis, 'none')
                if reference is not None:
                    assert fingerprint == reference
                reference = fingerprint
                seen = set()
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
                                    logical = operations[step['operation']]
                                    assert step['values'] == [record[c if isinstance(c, int) else ['id', 'key', 'payload'].index(c)] for c in logical['columns']]
                            seen.add(index)
                assert seen == set(range(count))
                print(json.dumps({'case': case, 'variant': variant, 'verified': True, 'outcome': 'success', 'fingerprint': fingerprint, 'analysis': analysis}), flush=True)
                shutil.rmtree(output)


if __name__ == '__main__':
    main()
