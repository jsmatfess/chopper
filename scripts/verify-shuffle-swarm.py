#!/usr/bin/env python3
"""Independent recipe/CSV/manifest checks; no product invocation."""
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath

csv.field_size_limit(2 * 1024 * 1024)
NAMES = ('seventeen', 'named-zero', 'thirty-three', 'fifty')
WEIGHTS = (17, 0, 33, 50)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def quotas(n, weights=WEIGHTS):
    total = sum(weights)
    counts = [n * w // total for w in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(n * weights[i] % total), i))
    for i in order[:n - sum(counts)]:
        counts[i] += 1
    return counts


def recipes():
    uniform = {'type': 'shuffle', 'strategy': 'uniform'}
    auto = {'type': 'shuffle', 'strategy': 'auto'}
    fy = {'type': 'shuffle', 'strategy': 'fisher_yates'}
    exact = {'type': 'assign', 'groups': [dict(name=n, percent=str(w)) for n, w in zip(NAMES, WEIGHTS)]}
    second = {'type': 'assign', 'groups': [dict(name='left', percent='50'), dict(name='right', percent='50')]}
    balance = lambda n: {'type': 'balanced', 'files': n}
    partition = {'type': 'partition', 'columns': ['key']}
    specs = [
        ('exact-fit', 12003, 64, False, [uniform, exact]),
        ('exact-spill', 50003, 192, False, [uniform, exact]),
        ('exact-many', 25703, 64, False, [balance(257), uniform, exact]),
        ('exact-wide', 12003, 64, True, [uniform, exact]),
        ('exact-downstream', 50003, 192, False, [uniform, exact, second]),
        ('mixed-fit', 4003, 256, False, [auto, fy]),
        ('mixed-retained', 40003, 256, False, [auto, balance(8), auto, fy]),
        ('mixed-wide', 4003, 64, True, [auto, fy]),
        ('mixed-upstream', 4003, 256, False, [partition, auto, fy]),
        ('mixed-downstream', 40003, 256, False, [auto, balance(8), auto, fy, exact]),
        ('adaptive-fit', 12000, 192, False, [auto]),
        ('adaptive-spill', 50000, 192, False, [auto]),
        ('balanced-fit', 4003, 192, False, [balance(1), uniform, balance(8)]),
        ('balanced-spill', 100003, 192, False, [balance(1), uniform, balance(8)]),
        ('combined-fit', 12003, 64, False, [auto, fy, exact]),
    ]
    return {name: dict(name=name, rows=n, payload_bytes=size, wide=wide,
                       operations=ops) for name, n, size, wide, ops in specs}


def header(recipe):
    return ['id', 'key', 'payload'] + ([f'c{i}' for i in range(30)] if recipe['wide'] else [])


def fields(recipe, identity):
    # Quoting, UTF-8 and embedded newline exercise actual encoded CSV, not line counts.
    payload = 'x' * recipe['payload_bytes']
    if not recipe['name'].startswith('balanced-') and identity % 997 == 0:
        payload = 'é,"\n' + payload[5:]
    if recipe['wide'] and identity == recipe['rows'] - 7:
        payload = 'w' * (768 * 1024)
    return [str(identity), 'k' if recipe['name'].startswith('balanced-') else str(identity % 17), payload] + (
        [str((identity * (c + 1) + c) % 101) for c in range(30)] if recipe['wide'] else [])


def fixture(path, recipe):
    with Path(path).open('x', newline='', encoding='utf-8') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(header(recipe))
        for identity in range(recipe['rows']):
            writer.writerow(fields(recipe, identity))


def key(lineage):
    return json.dumps(lineage, sort_keys=True, separators=(',', ':'))


def expected(recipe):
    # Members are known only before randomization; preserve established parent bounds.
    groups = [(recipe['rows'], [], range(recipe['rows']))]
    stages = []
    constraints = {}
    for index, op in enumerate(recipe['operations']):
        before = len(groups)
        children = []
        for n, lineage, members in groups:
            if op['type'] == 'shuffle':
                children.append((n, lineage, None))
            elif op['type'] == 'balanced':
                count = op['files']
                require(n >= count, 'recipe requests empty balanced group')
                offset = 0
                for part in range(count):
                    size = n // count + (part < n % count)
                    child = lineage + [dict(operation=index, part=part + 1)]
                    known = members[offset:offset + size] if members is not None else None
                    if known is not None:
                        constraints[key(child)] = set(known)
                    children.append((size, child, known))
                    offset += size
            elif op['type'] == 'assign':
                weights = [int(g['percent']) for g in op['groups']]
                for size, group in zip(quotas(n, weights), op['groups']):
                    child = lineage + [dict(operation=index, allocation=group['name'])]
                    children.append((size, child, None))
            elif op['type'] == 'partition':
                require(members is not None, 'only source partition recipes supported')
                for value in sorted({str(i % 17) for i in members}):
                    known = [i for i in members if str(i % 17) == value]
                    child = lineage + [dict(operation=index, values=[value])]
                    constraints[key(child)] = set(known)
                    children.append((len(known), child, known))
            else:
                raise ValueError('unsupported recipe operation')
        groups = children
        sizes = [g[0] for g in groups]
        stages.append(dict(operation=index + 1, input_groups=before,
                           output_groups=len(sizes), smallest_group=min(sizes, default=0),
                           largest_group=max(sizes, default=0), empty_groups=sizes.count(0)))
    return groups, stages, constraints


def matches_config(actual, submitted):
    # Canonical Job serialization fills defaults in nested objects too.
    if isinstance(submitted, dict):
        return isinstance(actual, dict) and all(
            k in actual and matches_config(actual[k], value) for k, value in submitted.items())
    if isinstance(submitted, list):
        return isinstance(actual, list) and len(actual) == len(submitted) and all(
            matches_config(a, b) for a, b in zip(actual, submitted))
    return actual == submitted


def verify(destination, recipe, job, analysis):
    destination = Path(destination)
    require(destination.is_dir() and not destination.is_symlink(), 'missing/unsafe destination')
    manifest = destination / 'manifest.jsonl'
    require(manifest.is_file() and not manifest.is_symlink(), 'missing/unsafe manifest')
    records = [json.loads(line) for line in manifest.read_text(encoding='utf-8').splitlines()]
    require(records and records[0]['type'] == 'job', 'first manifest record must be job')
    require(records[0]['schema_version'] == 1, 'unsupported manifest schema')
    require(records[0]['analysis'] == analysis, 'stdout/manifest Analysis mismatch')
    for name, value in job.items():
        require(matches_config(records[0]['config'][name], value), f'manifest config mismatch: {name}')
    groups, stages, constraints = expected(recipe)
    require(analysis['stages'] == stages, 'logical stages/original operation indices mismatch')
    require(analysis['rows'] == recipe['rows'], 'Analysis input rows mismatch')
    require(analysis['columns'] == len(header(recipe)), 'Analysis columns mismatch')
    require(analysis['header'] == header(recipe), 'Analysis header mismatch')
    require(analysis['groups'] == len(groups), 'Analysis logical groups mismatch')
    require(analysis['workers'] == 1 and analysis['memory_budget_bytes'] == job['resources']['memory_mb'] * 1024**2,
            'effective resources mismatch')
    expected_counts = {key(lineage): n for n, lineage, _ in groups}
    actual_counts = dict.fromkeys(expected_counts, 0)
    group_order = []
    paths, seen = set(), set()
    receipts = []
    ordered = hashlib.sha256()
    total_bytes = 0
    for record in records[1:]:
        require(record['type'] == 'output', 'unexpected manifest record')
        relative = PurePosixPath(record['path'])
        require(not relative.is_absolute() and len(relative.parts) == 1
                and relative.name not in ('', '.', '..') and '\\' not in str(relative) and ':' not in str(relative)
                and relative.suffix == '.csv', 'unsafe output path')
        require(str(relative) not in paths, 'duplicate manifest path')
        paths.add(str(relative))
        path = destination / str(relative)
        require(path.is_file() and not path.is_symlink(), 'missing/unsafe output')
        size = path.stat().st_size
        require(size == record['csv_bytes'] == record['stored_bytes'], 'CSV byte metadata mismatch')
        require(job['limits'].get('bytes') is None or size <= job['limits']['bytes'], 'encoded CSV byte cap exceeded')
        require(record['compressed_target_exceeded'] is False, 'unexpected compressed target')
        lineage = record['lineage']
        group_key = key(lineage)
        require(group_key in expected_counts, 'unexpected lineage/name/operation')
        if not group_order or group_order[-1] != group_key:
            group_order.append(group_key)
        rows = 0
        with path.open(newline='', encoding='utf-8') as stream:
            reader = csv.reader(stream, strict=True)
            require(next(reader) == header(recipe), 'CSV header mismatch')
            for row in reader:
                identity = int(row[0])
                require(0 <= identity < recipe['rows'] and identity not in seen, 'duplicate/invalid ID')
                require(row == fields(recipe, identity), 'source formula/field corruption')
                for depth in range(1, len(lineage) + 1):
                    allowed = constraints.get(key(lineage[:depth]))
                    require(allowed is None or identity in allowed, 'earlier parent membership violated')
                seen.add(identity)
                rows += 1
                ordered.update(json.dumps([lineage, row], ensure_ascii=False).encode('utf-8') + b'\n')
        require(rows == record['rows'] and (job['limits'].get('rows') is None or rows <= job['limits']['rows']), 'row metadata/cap mismatch')
        actual_counts[group_key] += rows
        total_bytes += size
        receipts.append(dict(path=str(relative), rows=rows, bytes=size, sha256=sha(path)))
    require(group_order == list(expected_counts), 'configured group order/empty named group missing')
    require(actual_counts == expected_counts, 'per-parent/nested largest-remainder quota mismatch')
    require(seen == set(range(recipe['rows'])), 'input/output conservation mismatch')
    require({p.name for p in destination.iterdir()} == paths | {'manifest.jsonl'}, 'unlisted output artifacts')
    require(len(receipts) == analysis['output_files'], 'Analysis output count mismatch')
    require(total_bytes == analysis['output_csv_bytes'], 'Analysis CSV bytes mismatch')
    return dict(verified=True, rows=len(seen), groups=len(groups), output_files=receipts,
                output_csv_bytes=total_bytes, manifest_sha256=sha(manifest),
                ordered_digest=ordered.hexdigest(),
                verifier_sha256=sha(__file__))
