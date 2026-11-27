"""Verify every row and its lineage against the fixture and submitted Job."""
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

recipe_path, result_path, output = map(Path, sys.argv[1:])
recipe = json.loads(recipe_path.read_text())
result = json.loads(result_path.read_text())
job = result['submitted']
analysis = result['analysis']
rows = recipe['rows']
widths = recipe['widths']
operations = job['operations']
assert operations == recipe['operations']
partition = next((index for index, op in enumerate(operations) if op['type'] == 'partition'), None)
shuffled = any(op['type'] == 'shuffle' for op in operations)
cap = recipe['byteCap']
assert job['limits']['bytes'] == cap and job['resources']['workers'] == 1


def key_for(identity):
    every = recipe.get('skewEvery')
    index = (0 if identity % every else 1 + (identity // every) % (recipe['keys'] - 1)) if every else identity % recipe['keys']
    return f'g{index:04d}'


group_ranges = {(): (0, rows)}
sizes = [rows]
stages = []
for index, op in enumerate(operations):
    parents = len(sizes)
    if op['type'] == 'partition':
        sizes = list(Counter(map(key_for, range(rows))).values())
    elif op['type'] == 'balanced':
        new_ranges = {}
        for lineage, (start, length) in group_ranges.items():
            length, remainder = divmod(length, op['files'])
            for part in range(1, op['files'] + 1):
                count = length + int(part <= remainder)
                new_ranges[(*lineage, (index, part))] = (start, count)
                start += count
        group_ranges = new_ranges
        sizes = [length for _, length in group_ranges.values()]
    stages.append((index + 1, parents, len(sizes), min(sizes), max(sizes), 0))

fields = ('operation', 'input_groups', 'output_groups', 'smallest_group', 'largest_group', 'empty_groups')
assert [tuple(s[k] for k in fields) for s in analysis['stages']] == stages
header, *entries = [json.loads(line) for line in (output/'manifest.jsonl').read_text().splitlines()]
marker = json.loads((output/'CHOPPER-COMPLETE.json').read_text())
assert marker == {'complete': True, 'files': len(entries) + 1, 'engine': 'chopper-browser', 'version': 1}
assert header['type'] == 'job' and header['analysis']['stages'] == analysis['stages']
assert header['analysis']['header'] == ['id', 'key', 'payload']
assert header['config']['operations'] == operations and header['config']['limits']['bytes'] == cap
inventory = {p.name for p in output.iterdir()}
assert inventory == {f['name'] for f in result['files']}
seen = bytearray(rows)
ordered = hashlib.sha256()
counts = Counter()
total = 0
descents = 0
last_id = -1
last_group = None
previous_size = None
payloads = {width: [chr(97 + i)*width for i in range(26)] for width in set(widths)}
for index, entry in enumerate(entries, 1):
    lineage = entry['lineage']
    if partition is not None:
        key = lineage[0]['values'][0]
        assert lineage == [{'operation': partition, 'values': [key]}]
        group = (key,)
        prefix = f'key-{key}-'
    else:
        group = tuple((step['operation'], step['part']) for step in lineage)
        assert lineage == [{'operation': operation, 'part': part} for operation, part in group]
        assert group in group_ranges
        prefix = ''.join(f'split-{part}-' for _, part in group)
    name = f'{prefix}part-{index:08}.csv'
    assert entry['path'] == name and name in inventory and entry['type'] == 'output'
    inventory.remove(name)
    path = output/name
    size = path.stat().st_size
    assert size == entry['stored_bytes'] == entry['csv_bytes'] <= cap
    assert entry['compressed_target_exceeded'] is False
    if last_group != group:
        assert last_group is None or last_group < group
        last_id = -1
    file_rows = 0
    with path.open(newline='', encoding='utf-8') as stream:
        reader = csv.reader(stream, strict=True)
        assert next(reader) == ['id', 'key', 'payload']
        for row in reader:
            identity = int(row[0])
            assert 0 <= identity < rows and not seen[identity]
            seen[identity] = 1
            assert row == [str(identity), key_for(identity), payloads[widths[identity % len(widths)]][identity % 26]]
            if partition is not None:
                assert row[1] == key
            elif not shuffled:
                assert identity == group_ranges[group][0] + counts[group] + file_rows
            if file_rows == 0 and last_group == group:
                assert previous_size + sum(map(len, row)) + len(row) > cap
            descents += int(identity < last_id)
            last_id = identity
            file_rows += 1
    assert file_rows == entry['rows'] > 0
    counts[group] += file_rows
    total += size
    last_group, previous_size = group, size
    with path.open('rb') as stream:
        ordered.update(hashlib.file_digest(stream, 'sha256').digest())
assert inventory == {'manifest.jsonl', 'CHOPPER-COMPLETE.json'}
assert all(seen) and analysis['rows'] == rows
assert analysis['groups'] == len(counts) == len(sizes)
assert len(entries) == analysis['output_files'] and total == analysis['output_csv_bytes']
if partition is None:
    assert counts == {lineage: length for lineage, (_, length) in group_ranges.items()}
assert not shuffled or descents > 0
print(json.dumps({'rows': rows, 'groups': len(counts), 'files': len(entries), 'csv_bytes': total,
                  'ordered_csv_sha256': ordered.hexdigest(), 'shuffle_descents': descents, 'marker': marker}))
