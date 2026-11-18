"""Independent streaming oracle for only the public fixed-width D/G dialect.

Intentionally does not import generate, recipe, or any engine implementation.
The ID bitmap is mmap-backed; output bytes and order/membership digests stream.
G parity is a peer comparison, not independent random draw reconstruction.
"""
import hashlib
import json
import mmap
import re
import tempfile
from pathlib import Path

VERSION = 'release-acceptance-v1'
MAX_LINE = 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def read_json(path, limit=MAX_LINE):
    with Path(path).open('rb') as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, 'JSON exceeds bounded metadata limit')
    return json.loads(data, object_pairs_hook=unique_object)


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def expected_header(width):
    return ('id,region,' + 'p' * (width - 11) + '\n').encode('ascii')


def inspect_row(raw, width, total):
    require(len(raw) == width and raw.endswith(b'\n'), 'row width or terminator changed')
    fields = raw[:-1].split(b',')
    require(len(fields) == 3 and re.fullmatch(rb'[0-9]{12}', fields[0]), 'invalid ID/field count')
    index = int(fields[0])
    require(index < total, 'ID out of range')
    require(fields[1] == ('r' + str(index % 8)).encode(), 'region field changed')
    text = hashlib.sha256(('release-acceptance-v1:' + str(index)).encode()).hexdigest()
    length = width - 17
    payload = (text * (length // len(text) + 1))[:length].encode('ascii')
    require(fields[2] == payload, 'payload field changed')
    return index


def quotas(total):
    base = [total * 80 // 100, total * 20 // 100]
    order = sorted(range(2), key=lambda i: (-(total * (80, 20)[i] % 100), i))
    for arm in order[:total - sum(base)]:
        base[arm] += 1
    return base


def validate_job(config, metadata):
    width, shape, runtime = metadata['width'], metadata['shape'], metadata['runtime']
    require((shape, width) in (('D', 100), ('G', 1000)), 'shape/width mismatch')
    require(runtime in ('native', 'browser') and metadata['generator'] == VERSION, 'unsupported fixture')
    total = metadata['rows']
    require(type(total) is int and 1 <= total < 10**12, 'invalid row count')
    require(type(metadata['tiny']) is bool, 'tiny flag must be boolean')
    if metadata['tiny']:
        require(total <= 2000, 'tiny row ceiling')
    else:
        require((total + 1) * width == (10_000_000_000 if runtime == 'native' else 1_000_000_000),
                'scale size mismatch')
    require(metadata['bytes'] == (total + 1) * width, 'fixture byte arithmetic mismatch')
    dialect = dict(encoding='utf-8', headers=True, delimiter=',', quote='"', escape=None,
                   line_ending='lf', bom=False, skip_empty_lines=False)
    operations = [] if shape == 'D' else [dict(type='partition', columns=['region']),
                  dict(type='assign', groups=[dict(name='treatment', percent='80'),
                                             dict(name='control', percent='20')], strata=[]),
                  dict(type='shuffle', strategy='uniform')]
    expected = dict(version=1, input=config['input'], output=config['output'], zip_member=None,
                    input_csv=dialect, output_csv=dialect, compression='none', seed=VERSION,
                    full_shuffle_policy='seeded_v1', full_shuffle_rng='blake3_counter_v1',
                    full_shuffle_algorithm='adaptive_v1', operations=operations,
                    limits=dict(bytes=10_000_000, rows=1_000_000, compressed_bytes=None),
                    resources=dict(memory_mb=64, workers=1, temp_dir=config['resources']['temp_dir'],
                                   temp_bytes=107_374_182_400 if runtime == 'native' else 8_589_934_592,
                                   max_files=4096, max_record_bytes=4096, grouping='auto'))
    if metadata['tiny']:
        expected['limits'] = config['limits']
    require(config == expected, 'unsupported Job recipe/dialect')
    require(runtime != 'browser' or config['resources']['temp_dir'] is None, 'browser temp_dir')
    caps = config['limits']
    require(set(caps) == {'rows', 'bytes', 'compressed_bytes'} and caps['compressed_bytes'] is None,
            'unsupported caps')
    require(all(type(caps[k]) is int and caps[k] > 0 for k in ('rows', 'bytes')), 'invalid cap')
    require(caps['bytes'] >= width * 2, 'header plus row cannot fit')


def safe_file(folder, name):
    require(isinstance(name, str) and re.fullmatch(r'(?:region-r[0-7]-allocation-(?:treatment|control)-)?part-[0-9]{8}\.csv', name), 'unsafe output name')
    path = folder / name
    require(not path.is_symlink() and path.is_file(), 'output must be a regular file')
    return path


def marker(folder, files):
    path = folder / 'CHOPPER-COMPLETE.json'
    require(not path.is_symlink(), 'marker symlink')
    value = read_json(path, 256)
    require(value == dict(complete=True, files=files + 1, engine='chopper-browser', version=1)
            and type(value.get('files')) is int and type(value.get('version')) is int
            and value.get('complete') is True, 'invalid completion marker schema/count')


def verify(job_path, fixture_path, folder=None, bitmap_dir=None, peer=None):
    config, meta = read_json(job_path), read_json(fixture_path)
    validate_job(config, meta)
    width, total, shape = meta['width'], meta['rows'], meta['shape']
    source = Path(config['input'])
    require(not source.is_symlink() and source.stat().st_size == meta['bytes'], 'source byte count')
    # Independently validate the source, not just a generator-provided digest.
    source_digest = hashlib.sha256()
    with source.open('rb') as stream:
        raw = stream.readline(width + 1)
        require(raw == expected_header(width), 'source header')
        source_digest.update(raw)
        for index in range(total):
            raw = stream.readline(width + 1)
            require(inspect_row(raw, width, total) == index, 'source ID order')
            source_digest.update(raw)
            if index % 100000 == 0:
                print(json.dumps(dict(phase='verify-source', rows=index + 1)), flush=True)
        require(stream.read(1) == b'', 'extra source bytes')
    require(source_digest.hexdigest() == meta['sha256'], 'source digest mismatch')
    folder = Path(folder or config['output'])
    manifest = folder / 'manifest.jsonl'
    require(not folder.is_symlink() and not manifest.is_symlink(), 'symlink manifest/folder')
    names, chunks, groups = set(), [], {}
    count = 0
    capacity = min(config['limits']['rows'], config['limits']['bytes'] // width - 1)
    expected_groups = [(f'r{i}', arm) for i in range(min(total, 8)) for arm in ('treatment', 'control')]
    expected_populations = {key: quotas((total + 7 - int(key[0][1:])) // 8)[0 if key[1] == 'treatment' else 1]
                            for key in expected_groups}
    with tempfile.TemporaryFile(dir=bitmap_dir) as bitmap_file, tempfile.TemporaryFile(dir=bitmap_dir) as arm_file:
        bitmap_file.truncate((total + 7) // 8)
        arm_file.truncate((total + 7) // 8)
        with mmap.mmap(bitmap_file.fileno(), 0) as seen, mmap.mmap(arm_file.fileno(), 0) as arms, manifest.open('rb') as stream:
            def entry():
                raw = stream.readline(MAX_LINE + 1)
                if not raw:
                    return None
                require(len(raw) <= MAX_LINE and raw.endswith(b'\n'), 'truncated/overlarge manifest line')
                return json.loads(raw, object_pairs_hook=unique_object)
            first = entry()
            require(first and first.get('type') == 'job' and first.get('schema_version') == 1,
                    'missing/versioned job manifest')
            require(first.get('algorithm_version') == 'chopper-v1-blake3-1', 'unsupported algorithm version')
            manifest_config = first['config'].copy()
            for key, default in [('full_shuffle_policy', 'seeded_v1'), ('full_shuffle_rng', 'blake3_counter_v1'),
                                 ('full_shuffle_algorithm', 'adaptive_v1')]:
                manifest_config.setdefault(key, default)
            # The worker mounts the selected CSV, export and temporary directory
            # at these fixed WASI paths; every other submitted field must match.
            expected_config = config.copy()
            if meta['runtime'] == 'browser':
                expected_config.update(input='/input.csv', output='/results',
                                       resources={**config['resources'], 'temp_dir': '/tmp'})
            require(manifest_config == expected_config, 'manifest config mismatch')
            require(first['analysis']['rows'] == total and type(first['analysis']['rows']) is int, 'manifest parent row total')
            require(first['analysis']['groups'] == (1 if shape == 'D' else len(expected_groups)), 'manifest logical group total')
            while True:
                item = entry()
                if item is None:
                    break
                require(len(chunks) < 4096 and item.get('type') == 'output', 'unexpected/excess manifest record')
                require(set(item) == {'type', 'path', 'rows', 'csv_bytes', 'stored_bytes', 'lineage', 'compressed_target_exceeded'},
                        'output manifest schema')
                require(all(type(item[k]) is int and item[k] >= 0 for k in ('rows', 'csv_bytes', 'stored_bytes')),
                        'invalid manifest count type')
                name = item['path']
                path = safe_file(folder, name)
                require(name not in names, 'duplicate output name')
                names.add(name)
                size = path.stat().st_size
                require(size <= config['limits']['bytes'] and size == item['csv_bytes'] == item['stored_bytes'],
                        'CSV byte cap/manifest byte mismatch')
                require(item.get('compressed_target_exceeded') is False, 'unexpected compression advisory')
                if shape == 'D':
                    require(item['lineage'] == [], 'D lineage')
                    group = ('all', 'all')
                    require(count < total, 'extra D chunk after final row')
                    expected_count = min(capacity, total - count)
                else:
                    lineage = item['lineage']
                    require(isinstance(lineage, list) and len(lineage) == 2, 'G lineage length')
                    part, arm = lineage
                    require(set(part) == {'operation', 'values'} and part['operation'] == 0
                            and len(part['values']) == 1 and set(arm) == {'operation', 'allocation'}
                            and arm['operation'] == 1, 'G lineage schema')
                    group = (part['values'][0], arm['allocation'])
                    require(group in expected_populations, 'unknown region/arm')
                    if group not in groups:
                        require(group == expected_groups[len(groups)], 'region/configuration group order')
                    else:
                        require(group == next(reversed(groups)), 'noncontiguous group')
                    remaining = expected_populations[group] - groups.get(group, {}).get('rows', 0)
                    require(remaining > 0 or group not in groups, 'extra empty chunk')
                    expected_count = min(capacity, remaining)
                prefix = '' if shape == 'D' else f'region-{group[0]}-allocation-{group[1]}-'
                require(name == prefix + f'part-{len(chunks) + 1:08d}.csv', 'name order/lineage mismatch')
                accumulator = groups.setdefault(group, dict(rows=0, order=hashlib.sha256(), membership=hashlib.sha256()))
                digest = hashlib.sha256()
                actual = 0
                with path.open('rb') as csv:
                    raw = csv.readline(width + 1)
                    require(raw == expected_header(width), 'output header changed')
                    digest.update(raw)
                    while True:
                        raw = csv.readline(width + 1)
                        if not raw:
                            break
                        index = inspect_row(raw, width, total)
                        byte, mask = divmod(index, 8)
                        require(not seen[byte] & (1 << mask), 'duplicate ID')
                        seen[byte] |= 1 << mask
                        if shape == 'G' and group[1] == 'control':
                            arms[byte] |= 1 << mask
                        require(shape != 'D' or index == count, 'D global order changed')
                        require(shape != 'G' or group[0] == f'r{index % 8}', 'wrong region membership')
                        digest.update(raw)
                        accumulator['order'].update(index.to_bytes(8, 'little'))
                        actual += 1
                        count += 1
                        if count % 100000 == 0:
                            print(json.dumps(dict(phase='verify-output', rows=count)), flush=True)
                require(actual == item['rows'] == expected_count and actual <= config['limits']['rows'],
                        'row cap/quota/greedy chunk boundary mismatch')
                accumulator['rows'] += actual
                chunks.append(dict(name=name, rows=actual, bytes=size, sha256=digest.hexdigest(), group=list(group)))
            require(count == total, 'missing IDs/conservation')
            # Unique in-range IDs plus exact count proves conservation. Also inspect bits explicitly.
            for index in range((total + 7) // 8):
                expected = 255 if index < total // 8 else (1 << (total % 8)) - 1
                require(seen[index] == expected, 'missing ID bitmap bit')
            if shape == 'G':
                require(list(groups) == expected_groups, 'missing named arm, including zero quota')
                require(all(groups[key]['rows'] == value for key, value in expected_populations.items()), 'exact quota')
            for index in range(total):
                arm = 'control' if arms[index // 8] & (1 << (index % 8)) else 'treatment'
                key = ('all', 'all') if shape == 'D' else (f'r{index % 8}', arm)
                groups[key]['membership'].update(index.to_bytes(8, 'little'))
                if index % 100000 == 0:
                    print(json.dumps(dict(phase='verify-membership', rows=index + 1)), flush=True)
    allowed = names | {'manifest.jsonl'} | ({'CHOPPER-COMPLETE.json'} if meta['runtime'] == 'browser' else set())
    require({path.name for path in folder.iterdir()} == allowed, 'unlisted/missing output artifact')
    if meta['runtime'] == 'browser':
        marker(folder, len(chunks))
    analysis = first['analysis']
    require(analysis['output_files'] == len(chunks) and analysis['output_csv_bytes'] == sum(c['bytes'] for c in chunks),
            'manifest output totals mismatch')
    receipt = dict(format=VERSION, algorithm='chopper-v1-blake3-1', limits=config['limits'], source_sha256=meta['sha256'], shape=shape, rows=count,
                   chunks=chunks, groups=[dict(group=list(key), rows=value['rows'],
                                             order_sha256=value['order'].hexdigest(),
                                             membership_sha256=value['membership'].hexdigest()) for key, value in groups.items()],
                   random_draws='not reconstructed; peer parity does not prove uniformity')
    if peer:
        require(receipt == read_json(peer, 8 * MAX_LINE), 'peer name/membership/order/hash parity mismatch')
    return receipt
