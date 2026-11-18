"""The two explicit release-acceptance-v1 Job recipes (no engine imports)."""
VERSION = 'release-acceptance-v1'
CSV = dict(encoding='utf-8', headers=True, delimiter=',', quote='"', escape=None,
           line_ending='lf', bom=False, skip_empty_lines=False)
OPERATIONS = [dict(type='partition', columns=['region']),
              dict(type='assign', groups=[dict(name='treatment', percent='80'),
                                         dict(name='control', percent='20')], strata=[]),
              dict(type='shuffle', strategy='uniform')]


def dimensions(shape, runtime, rows=None):
    if shape not in ('D', 'G') or runtime not in ('native', 'browser'):
        raise ValueError('only D/G and native/browser are supported')
    width = 100 if shape == 'D' else 1000
    count = (10_000_000_000 if runtime == 'native' else 1_000_000_000) // width - 1
    if rows is not None:
        if type(rows) is not int or not 1 <= rows <= 2000:
            raise ValueError('tiny controls require 1..2000 rows')
        count = rows
    return width, count, (count + 1) * width


def job(shape, runtime, source, output, temp):
    import copy
    dimensions(shape, runtime)
    return dict(version=1, input=str(source), output=str(output), zip_member=None,
                input_csv=CSV.copy(), output_csv=CSV.copy(), compression='none', seed=VERSION,
                full_shuffle_policy='seeded_v1', full_shuffle_rng='blake3_counter_v1',
                full_shuffle_algorithm='adaptive_v1',
                operations=[] if shape == 'D' else copy.deepcopy(OPERATIONS),
                limits=dict(bytes=10_000_000, rows=1_000_000, compressed_bytes=None),
                resources=dict(memory_mb=64, workers=1, temp_dir=str(temp) if runtime == 'native' else None,
                               temp_bytes=107_374_182_400 if runtime == 'native' else 8_589_934_592,
                               max_files=4096, max_record_bytes=4096, grouping='auto'))


def validate(config, shape, runtime, tiny=False):
    expected = job(shape, runtime, config['input'], config['output'], config['resources']['temp_dir'])
    if tiny:
        # Explicit verifier controls may force chunking. Production recipes stay fixed.
        expected['limits'] = config['limits']
        if (set(config['limits']) != {'bytes', 'rows', 'compressed_bytes'}
                or config['limits']['compressed_bytes'] is not None
                or any(type(config['limits'][key]) is not int or config['limits'][key] <= 0
                       for key in ('rows', 'bytes'))):
            raise ValueError('invalid tiny cap')
    if config != expected:
        raise ValueError('unsupported Job: exact D/G recipe required')
