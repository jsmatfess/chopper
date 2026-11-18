#!/usr/bin/env python3
"""Query normalized observations and validation receipts without running experiments.

Extraction is separate from reviewed comparison eligibility. Source bytes remain
authoritative. Missing metadata stays null; no adjacent-record context is inherited.
"""
import argparse
import collections
import fnmatch
import functools
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path('docs/performance/views.v1.json')
INDEX = Path('docs/performance/evidence-views-index.v1.json')
VALIDATION_OVERVIEW = Path('docs/validation-index.md')
SPEC = importlib.util.spec_from_file_location('benchmark_catalog', Path(__file__).with_name('benchmark-catalog.py'))
CAT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAT)
SCHEMA_SPEC = importlib.util.spec_from_file_location('performance_registry', Path(__file__).with_name('performance-registry.py'))
SCHEMA = importlib.util.module_from_spec(SCHEMA_SPEC)
SCHEMA_SPEC.loader.exec_module(SCHEMA)
MISSING = object()


@functools.lru_cache(maxsize=2)
def output_schema(name):
    return read_json(ROOT / 'docs/performance' / (name + '.schema.json'))


def validate_output(row, name):
    schema = output_schema(name)
    SCHEMA.validate_schema(row, schema, schema['$defs'], row['source'] + ':' + str(row['location']))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, f'Duplicate JSON key in {path}: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)


def escape(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def pointer(value, path, default=MISSING):
    if path == '':
        return value
    require(path.startswith('/'), 'Expected JSON pointer: ' + path)
    try:
        for part in path[1:].split('/'):
            require(re.search(r'~(?![01])', part) is None, 'Invalid JSON pointer escape')
            part = part.replace('~1', '/').replace('~0', '~')
            if isinstance(value, list):
                require(re.fullmatch(r'0|[1-9][0-9]*', part) is not None, 'Invalid JSON array index')
                value = value[int(part)]
            else:
                value = value[part]
        return value
    except (KeyError, IndexError, TypeError, ValueError):
        return default


def select(value, pattern):
    """Yield explicit JSON pointers; * traverses an array, never object keys."""
    require(pattern == '' or pattern.startswith('/'), 'Invalid selector')
    parts = pattern[1:].split('/') if pattern else []

    def walk(current, remaining, location):
        if not remaining:
            yield location, current
        elif remaining[0] == '*':
            if isinstance(current, list):
                for index, child in enumerate(current):
                    yield from walk(child, remaining[1:], location + '/' + str(index))
        else:
            child = pointer(current, '/' + remaining[0])
            if child is not MISSING:
                yield from walk(child, remaining[1:], location + '/' + remaining[0])
    yield from walk(value, parts, '')


def load_config(root):
    config = read_json(root / CONFIG)
    require(config['schema_version'] == 1, 'Unsupported evidence view schema')
    require(set(config) == {'schema_version', 'metrics', 'dimensions', 'observation_layouts', 'validation_layouts',
                            'classes', 'runtime_aliases', 'comparison_bindings', 'validation_bindings'}, 'Unknown view configuration')
    for metric in config['metrics']:
        require(set(metric) == {'pointer', 'name', 'unit', 'source_unit', 'scale', 'scope'}, 'Invalid metric definition')
        require(type(metric['scale']) in (int, float) and math.isfinite(metric['scale']) and metric['scale'] > 0,
                'Invalid metric unit scale')
        require(metric['unit'] in {'seconds', 'bytes', 'count'}, 'Unknown metric unit')
        require(metric['source_unit'] in {'seconds', 'bytes', 'KiB', 'count'}, 'Unknown source metric unit')
        require(isinstance(metric['pointer'], str) and metric['pointer'].startswith('/'), 'Invalid metric pointer')
    classes = {'measurement', 'allocation-census', 'summary', 'failure', 'diagnostic', 'contract-duration', 'unclassified'}
    require(all(value in classes for value in config['classes'].values()), 'Unknown record classification')
    for collection in ('observation_layouts', 'validation_layouts'):
        for layout in config[collection]:
            require(set(layout) <= {'id', 'selector', 'classification'} and {'id', 'selector'} <= set(layout),
                    'Invalid layout definition')
            require(layout['selector'] == '' or layout['selector'].startswith('/'), 'Invalid layout selector')
            require('classification' not in layout or layout['classification'] in classes, 'Unknown layout classification')
    identifiers = []
    for binding in config['comparison_bindings']:
        require(set(binding) == {'id', 'source', 'sha256', 'timing_scope', 'clock_pointer', 'runtime', 'review', 'baseline', 'candidate'},
                'Invalid reviewed comparison definition')
        identifiers.append(binding['id'])
        review = binding['review']
        require(set(review) == ({'source', 'basis'} if review['source'] == CONFIG.as_posix() else {'source', 'sha256', 'pointer'}),
                'Invalid comparison review provenance')
        for role in ('baseline', 'candidate'):
            require(isinstance(binding[role], list) and binding[role], 'Empty reviewed comparison population')
            for location in binding[role]:
                validate_location(location)
    require(len(identifiers) == len(set(identifiers)), 'Duplicate comparison IDs')
    for binding in config['validation_bindings']:
        require(set(binding) == {'source', 'sha256', 'location', 'check_id', 'contract', 'contract_refs', 'runtime', 'browser', 'features'},
                'Invalid validation binding definition')
        validate_location(binding['location'])
        require(isinstance(binding['contract_refs'], list) and binding['contract_refs'], 'Missing contract references')
        require(binding['features'] is None or (isinstance(binding['features'], list) and
                all(isinstance(x, str) for x in binding['features'])), 'Invalid binding feature flags')
    for binding in config['comparison_bindings'] + config['validation_bindings']:
        require(isinstance(binding['sha256'], str) and re.fullmatch('[a-f0-9]{64}', binding['sha256']), 'Invalid binding identity')
        require(binding['runtime'] is None or isinstance(binding['runtime'], str), 'Invalid binding runtime')
    return config


def validate_location(location):
    require(isinstance(location, dict) and set(location) in ({'pointer'}, {'line', 'pointer'}), 'Invalid observation location')
    require(isinstance(location['pointer'], str) and (location['pointer'] == '' or location['pointer'].startswith('/')),
            'Invalid observation pointer')
    if 'line' in location:
        require(type(location['line']) is int and location['line'] > 0, 'Invalid physical JSONL line')


def checked_artifact(root, entry):
    path = CAT.original_path(root / entry['path'])
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == entry['sha256'] and len(raw) == entry['bytes'],
            'Artifact differs from catalog: ' + entry['path'])
    return path


def source_envelope(entry, location, aliases):
    identity = entry['sha256'] + ':' + json.dumps(location, sort_keys=True)
    return {'schema_version': 1, 'id': hashlib.sha256(identity.encode()).hexdigest(),
            'source': entry['path'], 'source_sha256': entry['sha256'],
            'aliases': aliases, 'location': location}


def metrics(record, config):
    output = []
    for spec in config['metrics']:
        value = pointer(record, spec['pointer'])
        if value is MISSING or value is None:
            continue
        # Object-valued summary statistics are not scalar observations.
        if isinstance(value, dict):
            continue
        require(type(value) in (float, int) and (type(value) is int or math.isfinite(value)) and value >= 0,
                'Invalid scalar metric: ' + spec['pointer'])
        if spec['pointer'].startswith('/cpu/') and pointer(record, '/cpu/ok', None) is False:
            continue
        output.append({'name': spec['name'], 'value': value * spec['scale'], 'unit': spec['unit'],
                       'source_pointer': spec['pointer'], 'source_value': value,
                       'source_unit': spec['source_unit'], 'scale': spec['scale'], 'scope': spec['scope']})
    return output


def scalar(value):
    return value if value is None or type(value) in (str, int, float, bool) else None


def observation(entry, location, record, config, aliases, forced_class=None):
    if not isinstance(record, dict):
        return None
    kind = CAT.kind(record)
    classification = forced_class or config['classes'].get(kind, 'summary' if kind.startswith('derived_') else 'unclassified')
    values = metrics(record, config)
    if not values:
        return None
    dimensions = {name: (pointer(record, source, None) if name == 'features' else scalar(pointer(record, source, None)))
                  for name, source in config['dimensions'].items()}
    result = source_envelope(entry, location, aliases)
    result.update(record_kind=kind, classification=classification, dimensions=dimensions,
                  timing_scope=record.get('timing_scope', record.get('scope')) if
                  isinstance(record.get('timing_scope', record.get('scope')), str) else None,
                  verification=record.get('verified') if type(record.get('verified')) is bool else None,
                  metrics=values, comparisons=[], eligibility='unreviewed')
    result['diagnostic_refs'] = [{**location, 'pointer': location['pointer'] + '/' + escape(field)}
                                 for field in ('diagnostics', 'reported_analysis_diagnostics', 'flags', 'statistical_flags',
                                               'warnings', 'error', 'failure') if field in record]
    return result


def normalized_status(record):
    status = record.get('status')
    mapping = {'passed': 'passed', 'failed': 'failed', 'blocked': 'blocked', 'unrun': 'unrun',
               'timeout': 'incomplete', 'interrupted': 'incomplete', 'invalidated': 'invalidated',
               'running': 'incomplete', 'skipped': 'skipped',
               'incomplete': 'incomplete', 'unknown': 'unknown'}
    if isinstance(status, str) and status in mapping:
        result = mapping[status]
    elif status is not None:
        result = 'unknown'
    elif type(record.get('passed')) is bool:
        result = 'passed' if record['passed'] else 'failed'
    elif type(record.get('ok')) is bool:
        result = 'passed' if record['ok'] else 'failed'
    else:
        result = 'unknown'
    require(not (result == 'passed' and record.get('exit_code') not in (None, 0)), 'Passed validation has nonzero exit code')
    return result


def validation(entry, location, record, config, aliases):
    if not isinstance(record, dict):
        return None
    result = source_envelope(entry, location, aliases)
    platform = record.get('platform')
    result.update(record_kind=CAT.kind(record), check_id=scalar(record.get('id', record.get('name', record.get('test')))),
                  attempt=record.get('attempt'), status=normalized_status(record), raw_status=record.get('status'),
                  exit_code=record.get('exit_code'), runtime=config['runtime_aliases'].get(platform) if isinstance(platform, str) else None,
                  reported_platform=platform, batch=record.get('batch'), contract=None, contract_refs=[],
                  browser=None, features=None, build_identity=None, command=record.get('argv'), logs=record.get('logs'),
                  inputs=record.get('inputs'), artifacts=record.get('artifacts'),
                  runtime_identity=record.get('runtime'), duration_seconds=record.get('duration_seconds'),
                  error=record.get('error'),
                  freshness='historical; not revalidated', latest=None)
    return result


def extract(root, entry, config, aliases):
    checked_artifact(root, entry)
    observations, validations, layouts = [], [], set()
    seen_observations, seen_validations = set(), set()
    for location, document in CAT.records(root / entry['path']):
        if entry['format'] == 'jsonl':
            row = observation(entry, {**location, 'pointer': ''}, document, config, aliases)
            if row:
                observations.append(row)
                layouts.add('jsonl-record')
            if isinstance(document, dict) and CAT.kind(document) in {'validation', 'contract', 'failure'}:
                validations.append(validation(entry, {**location, 'pointer': ''}, document, config, aliases))
                layouts.add('jsonl-validation')
            continue
        for layout in config['observation_layouts']:
            for path, record in select(document, layout['selector']):
                if path in seen_observations:
                    continue
                row = observation(entry, {'pointer': path}, record, config, aliases, layout.get('classification'))
                if row:
                    observations.append(row)
                    seen_observations.add(path)
                    layouts.add(layout['id'])
        for layout in config['validation_layouts']:
            for path, record in select(document, layout['selector']):
                if path in seen_validations:
                    continue
                row = validation(entry, {'pointer': path}, record, config, aliases)
                if row:
                    validations.append(row)
                    seen_validations.add(path)
                    layouts.add(layout['id'])
    # Explicit document context remains a reference, never inherited as row facts.
    if entry['format'] == 'json':
        refs = [{'pointer': '/' + field, 'source': entry['path'], 'source_sha256': entry['sha256']}
                for field in ('source_sha256', 'source_base', 'base_commit', 'runtime', 'job', 'workload',
                              'timing_scope', 'native_attestation', 'builds', 'native_cli',
                              'context', 'cohorts', 'raw_evidence', 'derived_from', 'analysis_sources',
                              'batches', 'production_assets', 'bounds', 'runner')
                if isinstance(document, dict) and field in document]
        for row in observations + validations:
            row['metadata_refs'] = refs
    return observations, validations, sorted(layouts)


def raw_records(root, pattern, selected_pointer, line=None):
    require(pattern != '*', 'Source-record queries require an explicit --source selector')
    catalog = read_json(root / 'docs/benchmarks/catalog.json')
    for entry in catalog['artifacts']:
        if entry['format'] not in {'json', 'jsonl'} or not (
                fnmatch.fnmatchcase(entry['path'], pattern) or fnmatch.fnmatchcase(Path(entry['path']).name, pattern)):
            continue
        checked_artifact(root, entry)
        found = False
        for location, value in CAT.records(root / entry['path']):
            if line is not None and location.get('line') != line:
                continue
            selected = pointer(value, selected_pointer)
            require(selected is not MISSING, 'Missing source pointer: ' + selected_pointer)
            found = True
            yield {**source_envelope(entry, {**location, 'pointer': selected_pointer}, [entry['path']]), 'data': selected}
        require(found, 'Missing source record/line: ' + entry['path'])


def comparison_map(root, catalog, config):
    entries = {a['path']: a for a in catalog['artifacts']}
    output = collections.defaultdict(list)
    bindings = []
    for binding in config['comparison_bindings']:
        review = binding['review']
        if review['source'] != CONFIG.as_posix():
            require(review['source'] in entries and entries[review['source']]['sha256'] == review['sha256'],
                    'Reviewed comparison analysis identity changed')
        for role in ('baseline', 'candidate'):
            require(binding[role], 'Empty reviewed comparison population')
            for location in binding[role]:
                bindings.append({**{k: binding[k] for k in ('id', 'source', 'sha256', 'timing_scope', 'clock_pointer')},
                                 'location': location, 'role': role,
                                 'runtime': binding['runtime'], 'review': review,
                                 'mapping_source': CONFIG.as_posix(), 'mapping_sha256': hashlib.sha256((root / CONFIG).read_bytes()).hexdigest()})
    for binding in bindings:
        require(binding['source'] in entries and entries[binding['source']]['sha256'] == binding['sha256'],
                'Reviewed comparison source drift: ' + binding['source'])
        key = (binding['sha256'], json.dumps(binding['location'], sort_keys=True))
        assignment = {k: v for k, v in binding.items() if k not in {'source', 'sha256', 'location'}}
        require(assignment not in output[key], 'Duplicate comparison assignment')
        require(not any(a['id'] == assignment['id'] and a['role'] != assignment['role'] for a in output[key]),
                'One observation cannot be both arms of a comparison')
        output[key].append(assignment)
    return output


def validate_bindings(root, catalog, config):
    entries = {a['path']: a for a in catalog['artifacts']}
    for binding in config['validation_bindings']:
        require(binding['source'] in entries and entries[binding['source']]['sha256'] == binding['sha256'],
                'Validation binding source drift')
        for reference in binding['contract_refs']:
            relative, _, anchor = reference.partition('#')
            path = root / relative
            require(relative.startswith('docs/') and '..' not in Path(relative).parts and path.is_file(), 'Invalid contract reference')
            if anchor:
                require(anchor in {s['anchor'] for s in CAT.sections(path.read_text(encoding='utf-8'))}, 'Missing contract anchor')


def apply_bindings(entry, observations, validations, config, comparisons):
    for row in observations:
        key = (entry['sha256'], json.dumps(row['location'], sort_keys=True))
        row['comparisons'] = comparisons.get(key, [])
        if row['comparisons']:
            require(row['classification'] == 'measurement' or
                    (row['classification'] == 'unclassified' and row['record_kind'] == 'untyped'),
                    'Reviewed comparison points to excluded record class')
            require(row['verification'] is not False, 'Reviewed comparison contains failed verification')
            for assignment in row['comparisons']:
                require(sum(m['name'] == 'wall_time' and m['source_pointer'] == assignment['clock_pointer']
                            for m in row['metrics']) == 1, 'Reviewed comparison clock is not a unique scalar wall metric')
            row['eligibility'] = 'reviewed-for-named-comparisons-only'
    used = set()
    for binding in config['validation_bindings']:
        if binding['sha256'] != entry['sha256']:
            continue
        matches = [row for row in validations if row['location'] == binding['location']]
        require(len(matches) == 1, 'Validation binding does not identify exactly one check')
        row = matches[0]
        require(row['check_id'] == binding['check_id'], 'Validation binding check identity changed')
        require(row['id'] not in used, 'Multiple contract bindings for one check')
        used.add(row['id'])
        row.update({k: binding[k] for k in ('contract', 'contract_refs', 'runtime', 'browser', 'features')})


def sources(root, pattern='*'):
    catalog = read_json(root / 'docs/benchmarks/catalog.json')
    config = load_config(root)
    validate_bindings(root, catalog, config)
    comparisons = comparison_map(root, catalog, config)
    groups = collections.defaultdict(list)
    for entry in catalog['artifacts']:
        groups[entry['sha256']].append(entry)
    for digest, group in sorted(groups.items()):
        selected = [entry for entry in group if fnmatch.fnmatchcase(entry['path'], pattern)
                    or fnmatch.fnmatchcase(Path(entry['path']).name, pattern)]
        if not selected:
            continue
        # Keep one canonical record location even when querying another alias.
        entry = sorted(group, key=lambda a: a['path'])[0]
        if entry['format'] not in {'json', 'jsonl'}:
            yield entry, [], [], [], [a['path'] for a in group]
            continue
        aliases = sorted(a['path'] for a in group)
        observations, validations, layouts = extract(root, entry, config, aliases)
        apply_bindings(entry, observations, validations, config, comparisons)
        for row in observations:
            validate_output(row, 'observation')
        for row in validations:
            validate_output(row, 'validation-receipt')
        yield entry, observations, validations, layouts, aliases


def runner_receipts(directory):
    """Read explicit local runner files; never reissue a reusable validation pass."""
    manifest_path, status_path = directory / 'manifest.json', directory / 'status.json'
    manifest = read_json(manifest_path)
    state = read_json(status_path) if status_path.is_file() else {'attempts': []}
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    status_hash = hashlib.sha256(status_path.read_bytes()).hexdigest() if status_path.is_file() else None
    receipt_id = hashlib.sha256((str(directory.resolve()) + ':' + manifest_hash).encode()).hexdigest()
    ids = [s['id'] for s in manifest['steps']]
    require(len(ids) == len(set(ids)), 'Duplicate runner step IDs')
    require(all(a['id'] in ids for a in state['attempts']), 'Receipt contains unknown step')
    numbers = [a['attempt'] for a in state['attempts']]
    require(all(type(n) is int and n > 0 for n in numbers) and len(numbers) == len(set(numbers)),
            'Receipt attempt numbers must be unique positive integers')
    for step in manifest['steps']:
        coverage = step.get('coverage', {})
        require(isinstance(coverage, dict), 'Receipt coverage must be an object')
        require(not set(coverage) - {'contract', 'contract_refs', 'runtime', 'browser', 'features'}, 'Unknown receipt coverage fields')
        for field in ('contract', 'runtime', 'browser'):
            require(coverage.get(field) is None or isinstance(coverage[field], str), 'Invalid receipt coverage scalar')
        for field in ('contract_refs', 'features'):
            require(coverage.get(field) is None or (isinstance(coverage[field], list) and
                    all(isinstance(x, str) for x in coverage[field])), 'Invalid receipt coverage list')
        attempts = [(i, a) for i, a in enumerate(state['attempts']) if a['id'] == step['id']]
        for index, attempt in attempts or [(None, {'id': step['id'], 'status': 'unrun'})]:
            location = {'pointer': '/attempts/' + str(index)} if index is not None else {'manifest_pointer': '/steps/' + str(ids.index(step['id']))}
            entry = {'path': str(status_path if index is not None else manifest_path),
                     'sha256': status_hash if index is not None else manifest_hash}
            config = {'runtime_aliases': {}}
            row = validation(entry, location, attempt, config, [str(status_path)])
            row.update(manifest={'source': str(manifest_path), 'sha256': manifest_hash},
                       receipt_id=receipt_id, attempt_key=f'{receipt_id}:{step["id"]}:{attempt.get("attempt", "unrun")}',
                       latest=index is None or index == attempts[-1][0],
                       command=attempt.get('argv', step.get('argv')),
                       features=coverage.get('features', manifest.get('features')),
                       contract=coverage.get('contract'), contract_refs=coverage.get('contract_refs', []),
                       runtime=coverage.get('runtime'), browser=coverage.get('browser'),
                       build_identity={'inputs': attempt.get('inputs'), 'artifacts': attempt.get('artifacts')})
            if attempt.get('attempt') is not None:
                logs = {}
                for channel in ('stdout', 'stderr'):
                    path = directory / f'{attempt["attempt"]}-{channel}.log'
                    content = path.read_bytes() if path.is_file() else None
                    logs[channel] = {'path': str(path), 'available': content is not None,
                                     'sha256': hashlib.sha256(content).hexdigest() if content is not None else None,
                                     'bytes': len(content) if content is not None else None}
                row['logs'] = logs
            validate_output(row, 'validation-receipt')
            yield row


def generate_index(root):
    verify_reviewed_comparisons(root)
    output = {'schema_version': 1, 'type': 'derived_evidence_view_inventory',
              'scope': 'Extraction coverage, not independent samples, passing test totals or comparison eligibility.',
              'catalog_sha256': hashlib.sha256((root / 'docs/benchmarks/catalog.json').read_bytes()).hexdigest(),
              'config_sha256': hashlib.sha256((root / CONFIG).read_bytes()).hexdigest(),
              'adapter_sources': [{'path': 'scripts/' + name,
                                   'sha256': hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()}
                                  for name in ('evidence-views.py', 'benchmark-catalog.py', 'evidence-documents.py', 'evidence-resolver.py', 'performance-registry.py')],
              'output_schemas': [{'path': 'docs/performance/' + name + '.schema.json',
                                  'sha256': hashlib.sha256((ROOT / 'docs/performance' / (name + '.schema.json')).read_bytes()).hexdigest()}
                                 for name in ('observation', 'validation-receipt')],
              'sources': []}
    comparisons_seen, validations_seen = set(), set()
    for entry, observations, validations, layouts, aliases in sources(root):
        for row in validations:
            if row['contract'] is not None:
                validations_seen.add((entry['sha256'], json.dumps(row['location'], sort_keys=True),
                                      row['check_id'], row['contract']))
        for row in observations:
            for assignment in row['comparisons']:
                comparisons_seen.add((entry['sha256'], json.dumps(row['location'], sort_keys=True), assignment['id'], assignment['role']))
        output['sources'].append({'source': entry['path'], 'source_sha256': entry['sha256'], 'aliases': aliases,
                                  'format': entry['format'], 'layouts': layouts,
                                  'observation_records': len(observations), 'validation_records': len(validations),
                                  'classes': dict(sorted(collections.Counter(r['classification'] for r in observations).items())),
                                  'coverage': 'adapted' if layouts else 'not-adapted'})
    config = load_config(root)
    for binding in config['validation_bindings']:
        require((binding['sha256'], json.dumps(binding['location'], sort_keys=True), binding['check_id'], binding['contract'])
                in validations_seen, 'Validation binding was not consumed: ' + binding['source'])
    expected = comparison_map(root, read_json(root / 'docs/benchmarks/catalog.json'), config)
    for (sha, location), assignments in expected.items():
        for assignment in assignments:
            require((sha, location, assignment['id'], assignment['role']) in comparisons_seen,
                    'Reviewed comparison observation not extracted: ' + assignment['id'])
    validation_text = (root / 'docs/validation.md').read_text(encoding='utf-8')
    output['validation_narratives'] = [
        {'section': 'docs/validation.md#' + s['anchor'], 'title': s['title'],
         'section_sha256': hashlib.sha256('\n'.join(s['lines']).encode()).hexdigest(),
         'status': 'not-inferred-from-prose'} for s in CAT.sections(validation_text)]
    return output


def verify_reviewed_comparisons(root):
    """CI checks exact historical membership; narrow queries need no audit hydration."""
    config = load_config(root)
    entries = {a['path']: a for a in read_json(root / 'docs/benchmarks/catalog.json')['artifacts']}
    audits = {}
    for binding in config['comparison_bindings']:
        review = binding['review']
        if review['source'] == CONFIG.as_posix():
            continue
        if review['source'] not in audits:
            audits[review['source']] = read_json(checked_artifact(root, entries[review['source']]))
        cell = pointer(audits[review['source']], review['pointer'])
        require(cell is not MISSING and cell['id'] == binding['id'] and
                cell['source_sha256'] == binding['sha256'] and
                'docs/benchmarks/' + cell['source'] == binding['source'] and
                cell['timing_scope'] == binding['timing_scope'], 'Historical comparison definition changed')
        for role in ('baseline', 'candidate'):
            expected = [{'line': sample['line'], 'pointer': ''} for sample in cell[role]['samples']]
            require(expected == binding[role], 'Historical comparison population changed')
            require(all('/' + sample['seconds_field'] == binding['clock_pointer'] for sample in cell[role]['samples']),
                    'Historical comparison clock changed')


def render_validation_index(root, index):
    config = load_config(root)
    lines = ['# Validation evidence index', '',
             '<!-- Generated by scripts/evidence-views.py --build; edit reviewed bindings or owning narratives. -->', '',
             'Query structured historical checks or import a local runner batch using the',
             '[evidence view commands](performance/README.md#normalized-observations-and-validation).',
             'Records retain individual attempts and source hashes. Missing status/platform/build',
             'metadata remains unknown; command success alone does not prove a broader contract.',
             'No test totals are added across passes. [Supported claims](validation.md) remain authoritative.', '',
             '## Reviewed contract routes', '',
             '| Contract | Runtime | Check | Evidence |', '| --- | --- | --- | --- |']
    for binding in config['validation_bindings']:
        source = 'benchmarks/' + Path(binding['source']).name
        archive = CAT.RESOLVER.registry(root)['artifacts'].get(binding['source'])
        if archive:
            source = 'evidence-originals.md#sha256-' + archive['sha256']
        lines.append(f'| `{binding["contract"]}` | {binding["runtime"]} | `{binding["check_id"]}` | '
                     f'[Source]({source}) `{binding["location"]["pointer"]}` |')
    lines += ['', '## Validation narratives', '',
              'These routes index all existing validation sections without converting prose into passing receipts.', '',
              '| Narrative | Recorded status |', '| --- | --- |']
    for section in index['validation_narratives']:
        lines.append(f'| [{section["title"]}]({section["section"].removeprefix("docs/")}) | Not inferred from prose |')
    lines += ['', '## Coverage boundaries', '',
              'The machine inventory records adapted and unsupported artifacts separately. A record count',
              'is an extraction count, not a count of verified jobs or independent tests. Registry links',
              'preserve workload and build limits. Local runner imports are historical snapshots; reuse',
              'still requires the validation runner to recheck identities. No command runs during import.', '']
    return '\n'.join(lines)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('view', nargs='?', choices=['observations', 'validation', 'coverage', 'record'], default='observations')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--build', action='store_true')
    mode.add_argument('--check', action='store_true')
    parser.add_argument('--source', default='*')
    parser.add_argument('--classification')
    parser.add_argument('--metric')
    parser.add_argument('--comparison')
    parser.add_argument('--contract')
    parser.add_argument('--runtime')
    parser.add_argument('--status')
    parser.add_argument('--batch', type=Path)
    parser.add_argument('--pointer', default='')
    parser.add_argument('--line', type=int)
    parser.add_argument('--limit', type=int, default=25)
    parser.add_argument('--all', action='store_true', help='Explicitly export all matching records as JSONL')
    args = parser.parse_args(argv)
    if args.limit <= 0:
        parser.error('Positive result limit required')
    if (args.pointer or args.line is not None) and args.view != 'record':
        parser.error('--pointer and --line require record view')
    try:
        if args.build or args.check:
            require(not args.batch, 'Batch imports are not committed corpus inputs')
            index = generate_index(root)
            outputs = {INDEX: json.dumps(index, indent=2, ensure_ascii=False) + '\n',
                       VALIDATION_OVERVIEW: render_validation_index(root, index)}
            for path, content in outputs.items():
                if args.check:
                    require((root / path).read_bytes() == content.encode(), 'Stale evidence view: ' + str(path))
                else:
                    (root / path).write_bytes(content.encode())
            print(f'{len(index["sources"])} content identities {"checked" if args.check else "indexed"}')
            return 0
        if args.view == 'record':
            require(not args.batch, 'Use a cataloged source for record queries')
            rows = raw_records(root, args.source, args.pointer, args.line)
        elif args.view == 'coverage':
            rows = iter(read_json(root / INDEX)['sources'])
        elif args.batch:
            require(args.view == 'validation', '--batch requires validation view')
            rows = runner_receipts(args.batch)
        else:
            rows = (row for _, observations, validations, _, _ in sources(root, args.source)
                    for row in (observations if args.view == 'observations' else validations))
        selected = 0
        for row in rows:
            if args.view == 'coverage' and not any(fnmatch.fnmatchcase(a, args.source) or
                    fnmatch.fnmatchcase(Path(a).name, args.source) for a in row['aliases']):
                continue
            if args.classification and row.get('classification') != args.classification:
                continue
            if args.runtime and row.get('runtime', row.get('dimensions', {}).get('runtime')) != args.runtime and not any(
                    c.get('runtime') == args.runtime for c in row.get('comparisons', [])):
                continue
            if args.status and row.get('status') != args.status:
                continue
            if args.contract and row.get('contract') != args.contract:
                continue
            if args.comparison and not any(c['id'] == args.comparison for c in row.get('comparisons', [])):
                continue
            if args.comparison:
                assignments = [c for c in row['comparisons'] if c['id'] == args.comparison]
                clocks = {c['clock_pointer'] for c in assignments}
                row = {**row, 'comparisons': assignments,
                       'metrics': [m for m in row['metrics'] if m['name'] != 'wall_time' or m['source_pointer'] in clocks]}
            if args.metric:
                values = [m for m in row.get('metrics', []) if m['name'] == args.metric]
                if not values:
                    continue
                row = {**row, 'metrics': values}
            print(json.dumps(row, ensure_ascii=False, allow_nan=False, sort_keys=True))
            selected += 1
            if not args.all and selected >= args.limit:
                print('Result limit reached; narrow filters or use --all for explicit export.', file=sys.stderr)
                break
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Evidence views: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
