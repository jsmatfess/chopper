# Historical reproduction only: partition-first was removed on 2026-10-24.
# Requires pinned pre-removal binaries; not a current candidate or acceptance harness.
"""Independent small controls for flexible partition-first text/scopes and clean failures."""
import argparse
import csv
import gzip
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--candidate-rng',choices=['blake3_counter_v1'],default='blake3_counter_v1')
    parser.add_argument('--no-rewrite',action='store_true')
    args = parser.parse_args()
    cases = ['quoted', 'parents', 'downstream', 'utf16', 'headerless', 'gzip', 'zip', 'empty', 'named_empty', 'strict_cap', 'explicit_uniform', 'explicit_fisher', 'barrier', 'max_files', 'record_limit', 'disk_limit', 'malformed', 'insufficient']
    with tempfile.TemporaryDirectory(prefix='chopper-partition-first-controls-') as directory:
        root = Path(directory)
        source, output, temp, config = (root / name for name in ['input.csv', 'output', 'temp', 'job.json'])
        temp.mkdir()
        for case in cases:
            rows = [] if case == 'empty' else [[str(i), str(i % 3), f'001 / NA / null / 界 / "quoted"\nline{i % 5}\0'] for i in range(121)]
            stream = io.StringIO(newline='')
            writer = csv.writer(stream, lineterminator='\n')
            if case != 'headerless': writer.writerow(['id', 'key', 'payload'])
            writer.writerows(rows)
            text = stream.getvalue()
            if case == 'malformed': text += '122,0,"unterminated'
            source.write_bytes(text.encode('utf-16' if case == 'utf16' else 'utf-8'))
            strategy = {'explicit_uniform': 'uniform', 'explicit_fisher': 'fisher_yates'}.get(case, 'auto')
            operations = [{'type': 'shuffle', 'strategy': strategy}, {'type': 'partition', 'columns': [1 if case == 'headerless' else 'key']}]
            if case == 'parents': operations.insert(0, {'type': 'balanced', 'files': 2})
            if case in ['downstream', 'insufficient']: operations.append({'type': 'balanced', 'files': 1000 if case == 'insufficient' else 4})
            if case == 'barrier': operations.insert(1, {'type': 'interleaved', 'files': 2})
            if case == 'named_empty': operations.insert(0, {'type': 'assign', 'groups': [{'name': 'empty / 界', 'percent': '0'}, {'name': 'all', 'percent': '100'}]})
            job = {'input': str(source), 'output': str(output), 'seed': 'partition-first-controls-v1', 'full_shuffle_policy': 'flexible_v1', 'operations': operations, 'input_csv': {'encoding': 'utf-16le' if case == 'utf16' else 'utf-8', 'headers': case != 'headerless'}, 'output_csv': {'encoding': 'utf-16le' if case == 'utf16' else 'utf-8', 'bom': case == 'utf16', 'headers': case != 'headerless'}, 'compression': case if case in ['gzip', 'zip'] else 'none', 'resources': {'memory_mb': 32, 'workers': 1, 'max_record_bytes': 3 if case == 'record_limit' else 2097152, 'max_files': 1 if case == 'max_files' else 100000, 'temp_bytes': 1 if case == 'disk_limit' else None, 'temp_dir': str(temp)}, 'limits': {'rows': 11, 'bytes': 600 if case == 'strict_cap' else None}}
            reference = None
            for label, binary in [('baseline', args.baseline), ('candidate', args.candidate)]:
                job['full_shuffle_rng']=args.candidate_rng
                config.write_text(json.dumps(job))
                result = subprocess.run([str(binary.resolve()), 'run', '--config', str(config), '--yes'], capture_output=True, text=True, timeout=120)
                failure = case in ['max_files', 'record_limit', 'disk_limit', 'malformed', 'insufficient']
                assert bool(result.returncode) == failure, (case, label, result.stderr)
                if failure:
                    assert not output.exists() and not list(temp.iterdir()), (case, label)
                    print(json.dumps({'case': case, 'build': label, 'clean_failure': True}), flush=True)
                    continue
                analysis = json.loads(result.stdout)
                records = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
                entries = [r for r in records if r['type'] == 'output']
                rewrite = any(r['type'] == 'execution_rewrite' for r in records)
                assert rewrite == (label == 'candidate' and not args.no_rewrite and case not in ['explicit_uniform', 'explicit_fisher', 'barrier'])
                seen, total = set(), 0
                archive = zipfile.ZipFile(output / 'outputs.zip') if case == 'zip' else None
                last = None
                for entry in entries:
                    data = archive.read(entry['path']) if archive else (output / entry['path']).read_bytes()
                    if case == 'gzip': data = gzip.decompress(data)
                    assert len(data) == entry['csv_bytes']
                    if case == 'strict_cap': assert len(data) <= 600
                    total += len(data)
                    key = next(v['values'][0] for v in entry['lineage'] if 'values' in v)
                    parent = entry['lineage'][0]['part'] - 1 if case == 'parents' else None
                    order = (parent or 0, key)
                    if case != 'barrier': assert last is None or order >= last
                    last = order
                    reader = csv.reader(io.StringIO(data.decode('utf-16' if case == 'utf16' else 'utf-8'), newline=''))
                    if case != 'headerless': assert next(reader) == ['id', 'key', 'payload']
                    count = 0
                    for row in reader:
                        i = int(row[0]); assert 0 <= i < len(rows) and i not in seen
                        assert row == rows[i] and row[1] == key
                        if parent is not None: assert (i < 61) == (parent == 0)
                        seen.add(i); count += 1
                    assert count == entry['rows'] <= 11
                if archive: archive.close()
                assert seen == set(range(len(rows)))
                assert len(entries) == analysis['output_files'] and total == analysis['output_csv_bytes']
                logical = (analysis['stages'], analysis['logical_digest'])
                assert reference is None or logical == reference
                reference = logical
                shutil.rmtree(output)
                assert not list(temp.iterdir()), (case, label)
                print(json.dumps({'case': case, 'build': label, 'conserved': True, 'rewrite': rewrite, 'files': len(entries)}), flush=True)


if __name__ == '__main__':
    main()
