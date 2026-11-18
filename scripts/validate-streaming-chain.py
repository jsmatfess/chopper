"""Check routing-chain parity, parent counters, rollback, encodings and clean failures."""
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
    csv.field_size_limit(4 * 1024 * 1024)
    with tempfile.TemporaryDirectory(prefix='chopper-chain-controls-') as directory:
        root = Path(directory)
        source, output, temp, config = (root / p for p in ['input.csv', 'output', 'temp', 'job.json'])
        temp.mkdir()
        cases = ['leading', 'parents', 'parents_interleaved', 'downstream', 'interleaved',
                 'last_probability', 'both_probability', 'duplicate_columns', 'deep_chain',
                 'high_fanout', 'late_fallback', 'wide_key', 'empty', 'named_empty', 'empty_only',
                 'utf16', 'no_header', 'strict_cap', 'max_files', 'insufficient', 'malformed',
                 'temp_budget', 'oversized_record']
        for case in cases:
            count = 0 if case in ('empty', 'empty_only') else 1200 if case == 'high_fanout' else 2400 if case == 'late_fallback' else 121
            records = [[str(i), str(i % 3), f'001 / NA / null / "界"\ntext{i % 5}'] for i in range(count)]
            if case in ('high_fanout', 'late_fallback'):
                for i, record in enumerate(records):
                    record[1] = 'common' if case == 'late_fallback' and i < count // 2 else str(i // 3)
            if case == 'wide_key':
                for record in records:
                    record[1] += '界' * 200000
            if case == 'oversized_record':
                records[-1][1] = 'x' * (2 * 1024 * 1024)
            with source.open('w', newline='') as stream:
                writer = csv.writer(stream, lineterminator='\n')
                if case != 'no_header':
                    writer.writerow(['id', 'key', 'payload'])
                writer.writerows(records)
            if case == 'malformed':
                with source.open('a') as stream:
                    stream.write('122,g,"unterminated')
            def probability():
                return {'type': 'assign_probabilistic', 'groups': [
                    {'name': 'treatment / 界', 'percent': '60'}, {'name': 'control', 'percent': '40'},
                    {'name': 'empty', 'percent': '0'}], 'strata': [2 if case == 'no_header' else 'payload']}
            key = 1 if case == 'no_header' else 'key'
            first, last = probability(), {'type': 'interleaved', 'files': 3}
            if case in ('interleaved', 'parents_interleaved', 'last_probability'):
                first = {'type': 'interleaved', 'files': 3}
            if case in ('last_probability', 'both_probability', 'deep_chain', 'high_fanout', 'late_fallback'):
                last = probability()
            if case in ('named_empty', 'empty_only'):
                first['groups'] = [{'name': 'keep', 'percent': '100'}, {'name': 'empty', 'percent': '0'}]
            if case == 'insufficient':
                last['files'] = 1000
            columns = [key, 1] if case == 'duplicate_columns' else [key]
            operations = [first, {'type': 'partition', 'columns': columns}, last]
            if case in ('parents', 'parents_interleaved', 'late_fallback'):
                operations.insert(0, {'type': 'balanced', 'files': 2})
            if case == 'downstream':
                operations += [{'type': 'shuffle', 'strategy': 'uniform'}, {'type': 'balanced', 'files': 2}]
            if case == 'deep_chain':
                operations += [probability(), {'type': 'partition', 'columns': ['payload']}, {'type': 'interleaved', 'files': 1}]
            job = {'input': str(source), 'output': str(output), 'seed': 'routing-chain-controls-v1',
                   'operations': operations, 'limits': {'bytes': 20 if case == 'strict_cap' else 134217728},
                   'input_csv': {'headers': case != 'no_header'},
                   'output_csv': {'headers': case != 'no_header', 'encoding': 'utf-16le' if case == 'utf16' else 'utf-8', 'bom': case == 'utf16'},
                   'resources': {'memory_mb': 32, 'workers': 4, 'max_record_bytes': 2097152,
                                 'max_files': 4 if case == 'max_files' else 100000, 'temp_dir': str(temp)}}
            if case == 'temp_budget':
                job['resources']['temp_bytes'] = 1
            config.write_text(json.dumps(job))
            reference = None
            for variant, binary in [('baseline', args.baseline), ('candidate', args.candidate)]:
                result = subprocess.run([str(binary.resolve()), 'run', '--config', str(config), '--yes'],
                                        text=True, capture_output=True, timeout=180)
                assert not list(temp.iterdir()), (case, 'temporary leak')
                if case in ['strict_cap', 'max_files', 'malformed', 'insufficient', 'temp_budget', 'oversized_record']:
                    assert result.returncode and not output.exists(), result.stderr
                    print(json.dumps({'case': case, 'variant': variant, 'verified': True, 'outcome': 'clean rejection', 'error': result.stderr.strip()}), flush=True)
                    continue
                assert result.returncode == 0, (case, result.stderr)
                analysis = json.loads(result.stdout)
                fingerprint = pipelines.fingerprint(output, analysis, 'none')
                if reference is not None:
                    assert fingerprint == reference, case
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
                if variant == 'candidate':
                    diagnostics = analysis['diagnostics']
                    if case in ('high_fanout', 'late_fallback', 'wide_key'):
                        assert diagnostics['streaming_chain_retries'] >= 1
                        assert diagnostics['streaming_chain_fusions'] == 0
                    else:
                        assert diagnostics['streaming_chain_fusions'] >= 1
                print(json.dumps({'case': case, 'variant': variant, 'verified': True, 'outcome': 'success', 'fingerprint': fingerprint, 'analysis': analysis}), flush=True)
                shutil.rmtree(output)


if __name__ == '__main__':
    main()
