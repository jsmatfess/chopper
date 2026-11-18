"""Text fidelity, quota, metadata, exclusion and clean-failure controls for ranges."""
import argparse
import collections
import csv
import gzip
import hashlib
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
    parser.add_argument('--candidate-algorithm', choices=['adaptive_v1'], default='adaptive_v1')
    parser.add_argument('--no-rewrite', action='store_true')
    args = parser.parse_args()
    cases = ['quoted', 'parents', 'downstream', 'utf16', 'headerless', 'gzip', 'zip', 'empty', 'named_empty', 'strict_cap', 'explicit_uniform', 'explicit_fisher', 'barrier', 'stratified', 'max_files', 'record_limit', 'disk_limit', 'malformed', 'insufficient']
    allocations = [{'name': 'small / 界', 'percent': '17'}, {'name': 'empty named', 'percent': '0'}, {'name': 'rest', 'percent': '83'}]
    with tempfile.TemporaryDirectory(prefix='chopper-allocation-controls-') as directory:
        root = Path(directory)
        source, output, temp, config = (root / n for n in ['input.csv', 'output', 'temp', 'job.json']); temp.mkdir()
        for case in cases:
            rows = [] if case == 'empty' else [[str(i), str(i % 3), f'001 / NA / null / 界 / "quoted"\nline{i % 5}\0'] for i in range(121)]
            stream = io.StringIO(newline=''); writer = csv.writer(stream, lineterminator='\n')
            if case != 'headerless': writer.writerow(['id', 'key', 'payload'])
            writer.writerows(rows); text = stream.getvalue()
            if case == 'malformed': text += '122,0,"unterminated'
            source.write_bytes(text.encode('utf-16' if case == 'utf16' else 'utf-8'))
            strategy = {'explicit_uniform': 'uniform', 'explicit_fisher': 'fisher_yates'}.get(case, 'auto')
            operations = [{'type': 'shuffle', 'strategy': strategy}, {'type': 'assign', 'groups': allocations, 'strata': [1 if case == 'headerless' else 'key'] if case == 'stratified' else []}]
            if case == 'parents': operations.insert(0, {'type': 'partition', 'columns': ['key']})
            if case == 'downstream': operations.append({'type': 'assign', 'groups': [{'name': 'left', 'percent': '50'}, {'name': 'right', 'percent': '50'}]})
            if case == 'insufficient': operations.append({'type': 'balanced', 'files': 1000})
            if case == 'barrier': operations.insert(1, {'type': 'interleaved', 'files': 2})
            if case == 'named_empty': operations.insert(0, {'type': 'assign', 'groups': [{'name': 'empty parent', 'percent': '0'}, {'name': 'all', 'percent': '100'}]})
            job = {'input': str(source), 'output': str(output), 'seed': 'allocation-controls-v1', 'full_shuffle_policy': 'flexible_v1', 'operations': operations, 'input_csv': {'encoding': 'utf-16le' if case == 'utf16' else 'utf-8', 'headers': case != 'headerless'}, 'output_csv': {'encoding': 'utf-16le' if case == 'utf16' else 'utf-8', 'bom': case == 'utf16', 'headers': case != 'headerless'}, 'compression': case if case in ['gzip', 'zip'] else 'none', 'resources': {'memory_mb': 32, 'workers': 1, 'max_record_bytes': 3 if case == 'record_limit' else 2097152, 'max_files': 1 if case == 'max_files' else 100000, 'temp_bytes': 1 if case == 'disk_limit' else None, 'temp_dir': str(temp)}, 'limits': {'rows': 11, 'bytes': 600 if case == 'strict_cap' else None}}
            reference = None
            for label, binary in [('baseline', args.baseline), ('candidate', args.candidate)]:
                if label == 'candidate' and args.candidate_algorithm != 'adaptive_v1': job['full_shuffle_algorithm'] = args.candidate_algorithm
                else: job.pop('full_shuffle_algorithm', None)
                config.write_text(json.dumps(job))
                result = subprocess.run([str(binary.resolve()), 'run', '--config', str(config), '--yes'], capture_output=True, text=True, timeout=120)
                failure = case in ['max_files', 'record_limit', 'disk_limit', 'malformed', 'insufficient']
                assert bool(result.returncode) == failure, (case, label, result.stderr)
                if failure:
                    assert not output.exists() and not list(temp.iterdir()), (case, label)
                    print(json.dumps({'case': case, 'build': label, 'clean_failure': True}), flush=True); continue
                analysis = json.loads(result.stdout)
                records = [json.loads(line) for line in (output / 'manifest.jsonl').read_text().splitlines()]
                entries = [r for r in records if r['type'] == 'output']
                rewrite = any(r['type'] == 'execution_rewrite' for r in records)
                assert rewrite == (label == 'candidate' and not args.no_rewrite and case not in ['barrier', 'stratified'])
                seen, counts, total, order, digest = set(), collections.Counter(), 0, [], hashlib.sha256()
                archive = zipfile.ZipFile(output / 'outputs.zip') if case == 'zip' else None
                allocation_step = next(i for i, o in enumerate(operations) if o['type'] == 'assign' and o['groups'] == allocations)
                for entry in entries:
                    data = archive.read(entry['path']) if archive else (output / entry['path']).read_bytes()
                    if case == 'gzip': data = gzip.decompress(data)
                    assert len(data) == entry['csv_bytes']; digest.update(data)
                    if case == 'strict_cap': assert len(data) <= 600
                    total += len(data)
                    lineage = entry['lineage']
                    parent = next((v['values'][0] for v in lineage if 'values' in v), 'all') if case == 'parents' else lineage[0]['allocation'] if case == 'named_empty' else str(lineage[0]['part']) if case == 'barrier' else 'all'
                    allocation = next(v for v in lineage if v.get('operation') == allocation_step and 'allocation' in v)
                    index = next(i for i, g in enumerate(allocations) if g['name'] == allocation['allocation'])
                    order.append((parent, index)); count = 0
                    reader = csv.reader(io.StringIO(data.decode('utf-16' if case == 'utf16' else 'utf-8'), newline=''))
                    if case != 'headerless': assert next(reader) == ['id', 'key', 'payload']
                    for row in reader:
                        i = int(row[0]); assert 0 <= i < len(rows) and i not in seen and row == rows[i]
                        if case == 'parents': assert row[1] == parent
                        if case == 'named_empty': assert parent == 'all'
                        seen.add(i); count += 1
                    assert count == entry['rows'] <= 11
                    counts[parent, index] += count
                if archive: archive.close()
                assert seen == set(range(len(rows))) and len(entries) == analysis['output_files'] and total == analysis['output_csv_bytes']
                # Requested allocation order, including a named zero quota in each parent.
                for parent in {p for p, _ in counts}:
                    indices = [i for p, i in order if p == parent]
                    assert indices == sorted(indices)
                    assert (parent, 1) in counts and counts[parent, 1] == 0
                    if case != 'stratified':
                        n = sum(counts[parent, i] for i in range(3)); q = n * 17 // 100
                        if n * 17 % 100 >= n * 83 % 100 and n % 100: q += 1
                        assert counts[parent, 0] == q and counts[parent, 2] == n - q
                # Preserve stage statistics; distribution-equivalent output is allowed to differ.
                actual = (analysis['stages'], analysis['logical_digest'])
                if case in (['explicit_uniform', 'explicit_fisher'] if args.candidate_algorithm != 'adaptive_v1' else ['barrier', 'stratified']): actual += (digest.hexdigest(), entries)
                assert reference is None or actual == reference, (case, label)
                reference = actual
                shutil.rmtree(output); assert not list(temp.iterdir())
                print(json.dumps({'case': case, 'build': label, 'conserved': True, 'rewrite': rewrite, 'files': len(entries)}), flush=True)


if __name__ == '__main__':
    main()
