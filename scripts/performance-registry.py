#!/usr/bin/env python3
"""Validate performance decisions, generate their overview, or query without hydration.

The registry records reviewed interpretation, not normalized benchmark samples.
Only Python's standard library is required. No commands or downloads are launched.
"""
import argparse
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
RECORDS = Path('docs/performance/decisions')
SCHEMA = Path('docs/performance/decision.schema.json')
OVERVIEW = Path('docs/performance-overview.md')
SPEC = importlib.util.spec_from_file_location('benchmark_catalog', Path(__file__).with_name('benchmark-catalog.py'))
CAT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAT)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f'{path}: duplicate key {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_pairs)


def validate_schema(value, schema, definitions, location):
    """Validate the JSON Schema subset used by our checked-in record schema.

    This is not a general JSON Schema implementation; unsupported assertions fail
    closed so extending the schema requires extending and testing this checker.
    """
    supported = {'$schema', '$id', '$defs', '$ref', 'title', 'description', 'type',
                 'const', 'enum', 'properties', 'required', 'additionalProperties',
                 'items', 'minItems', 'uniqueItems', 'minLength', 'pattern', 'format'}
    require(not set(schema) - supported, f'{location}: unsupported schema assertion')
    if 'format' in schema:
        require(schema['format'] == 'date', f'{location}: unsupported schema format')
    if '$ref' in schema:
        ref = schema['$ref']
        require(ref.startswith('#/$defs/'), f'{location}: unsupported schema reference')
        validate_schema(value, definitions[ref.removeprefix('#/$defs/')], definitions, location)
    types = {'object': (dict,), 'array': (list,), 'string': (str,), 'integer': (int,),
             'number': (int, float), 'boolean': (bool,), 'null': (type(None),)}
    if 'type' in schema:
        allowed = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        require(any(type(value) in types[t] for t in allowed), f'{location}: expected {allowed}')
    if 'const' in schema:
        require(value == schema['const'], f'{location}: unsupported value/version')
    if 'enum' in schema:
        require(value in schema['enum'], f'{location}: expected one of {schema["enum"]}')
    if isinstance(value, dict):
        require(set(schema.get('required', [])) <= set(value), f'{location}: missing required fields')
        properties = schema.get('properties', {})
        if schema.get('additionalProperties') is False:
            require(not set(value) - set(properties), f'{location}: unknown fields {set(value) - set(properties)}')
        for key in value.keys() & properties.keys():
            validate_schema(value[key], properties[key], definitions, f'{location}/{key}')
    if isinstance(value, list):
        require(len(value) >= schema.get('minItems', 0), f'{location}: too few items')
        if schema.get('uniqueItems'):
            require(len({json.dumps(x, sort_keys=True) for x in value}) == len(value), f'{location}: duplicate items')
        if 'items' in schema:
            for i, item in enumerate(value):
                validate_schema(item, schema['items'], definitions, f'{location}/{i}')
    if isinstance(value, str):
        require(len(value.strip()) >= schema.get('minLength', 0), f'{location}: empty text')
        if 'pattern' in schema:
            require(re.search(schema['pattern'], value) is not None, f'{location}: invalid format')
        if schema.get('format') == 'date':
            require(date.fromisoformat(value).isoformat() == value, f'{location}: invalid date')


def local_path(root, value):
    require(value and '\\' not in value and not Path(value).is_absolute()
            and all(p not in {'', '.', '..'} for p in value.split('/')),
            f'Unsafe repository path: {value}')
    path = root / value
    require(path.resolve().is_relative_to(root.resolve()), f'Path outside repository: {value}')
    return path


def section_index(path):
    return {s['anchor']: s for s in CAT.sections(path.read_text(encoding='utf-8'))}


def section_hash(section):
    # Hash exactly the parser's H2 lines joined with LF, with no added newline.
    return hashlib.sha256('\n'.join(section['lines']).encode('utf-8')).hexdigest()


def check_link(root, link):
    relative, marker, anchor = link.partition('#')
    path = local_path(root, relative)
    require(path.is_file(), f'Missing reference: {link}')
    if marker:
        require(anchor in section_index(path), f'Missing H2 anchor: {link}')
    return path, anchor


def load_records(root):
    schema = read_json(root / SCHEMA)
    catalog = read_json(root / 'docs/benchmarks/catalog.json')
    artifacts = {a['path']: a for a in catalog['artifacts']}
    experiments = {e['evidence']: e for e in catalog['experiments']}
    paths = sorted((root / RECORDS).glob('*.json'))
    require(paths, 'No performance decision records')
    records = []
    sections = {}
    for path in paths:
        record = read_json(path)
        validate_schema(record, schema, schema['$defs'], str(path.relative_to(root)))
        require(path.stem == record['id'], f'{path}: filename must match stable ID')
        linked_artifacts = set()
        for source in record['sources']:
            link = source['section']
            relative, _, anchor = link.partition('#')
            require(relative == 'docs/performance.md' and anchor,
                    f'{link}: expected a performance H2 section')
            if relative not in sections:
                sections[relative] = {s['anchor']: s for s in CAT.performance_sections(root)}
            require(anchor in sections[relative], f'Missing source section: {link}')
            require(section_hash(sections[relative][anchor]) == source['sha256'],
                    f'{record["id"]}: source section changed; review interpretation: {link}')
            require(link in experiments, f'Source missing from benchmark catalog: {link}')
            linked_artifacts.update(experiments[link]['artifacts'])
        for artifact in record['artifacts']:
            alias = artifact['path']
            local_path(root, alias)
            require(alias in linked_artifacts, f'{record["id"]}: artifact not linked by its source sections: {alias}')
            require(alias in artifacts and artifact['sha256'] == artifacts[alias]['sha256'],
                    f'{record["id"]}: artifact identity differs from catalog: {alias}')
            # Check present raw files; archived originals stay behind the resolver.
            raw = root / alias
            if raw.is_file():
                require(hashlib.sha256(raw.read_bytes()).hexdigest() == artifact['sha256'],
                        f'{record["id"]}: local artifact hash mismatch: {alias}')
        for contract in record['contracts']:
            check_link(root, contract)
        records.append(record)
    by_id = {r['id']: r for r in records}
    require(len(by_id) == len(records), 'Duplicate decision IDs')
    for record in records:
        for previous in record['supersedes']:
            require(previous in by_id, f'{record["id"]}: unknown superseded ID {previous}')
            require(by_id[previous]['date'] <= record['date'], f'{record["id"]}: supersedes a later decision')
        if record['disposition'] in {'reject', 'block-promotion'}:
            require(record['delivery'] == 'unapplied', f'{record["id"]}: rejected/blocked variant must be unapplied')
    visited, active = set(), set()

    def visit(identifier):
        require(identifier not in active, f'Supersession cycle at {identifier}')
        if identifier in visited:
            return
        active.add(identifier)
        for previous in by_id[identifier]['supersedes']:
            visit(previous)
        active.remove(identifier)
        visited.add(identifier)
    for identifier in by_id:
        visit(identifier)
    return sorted(records, key=lambda r: (r['date'], r['id']), reverse=True)


def superseded_ids(records):
    return {identifier for record in records for identifier in record['supersedes']}


def cell(value):
    return value.replace('|', '\\|').replace('\n', ' ')


def render(records, root=ROOT):
    superseded = superseded_ids(records)
    lines = ['# Current performance decisions', '',
             '<!-- Generated by scripts/performance-registry.py; edit decision records instead. -->', '',
             'Start here for selected current decisions, then follow the linked records for workload,',
             'validation, exclusions, limitations and evidence identities. This is a reviewed subset',
             'of the historical corpus, not exhaustive coverage or a ranking of speedups.', '',
             '[Architecture](architecture.md) · [Registry guide and queries](performance/README.md) ·',
             '[All historical evidence](benchmarks/INDEX.md) · [Validation coverage](validation.md)', '',
             'Measured outcome, decision and delivery are independent fields. Favorable evidence',
             'does not imply default activation. Scope applies to the recorded builds/workloads;',
             'current contracts remain authoritative. Older baselines stay in the historical log.', '',
             f'Registry coverage: {len(records)} records; latest recorded decision {max(r["date"] for r in records)}.',
             f'{len(superseded)} superseded records remain queryable but are omitted below.', '']
    groups = [
        ('Delivered in default builds', lambda r: r['delivery'] == 'default'),
        ('Delivered as opt-in', lambda r: r['delivery'] == 'opt-in'),
        ('Adopted, awaiting delivery', lambda r: r['disposition'] == 'adopt'
         and r['delivery'] not in {'default', 'opt-in'}),
        ('Retained experiments', lambda r: r['disposition'] == 'retain-experimental'
         and r['delivery'] not in {'default', 'opt-in'}),
        ('Rejected or blocked variants', lambda r: r['disposition'] in {'reject', 'block-promotion'}),
        ('Diagnostics', lambda r: r['disposition'] == 'informational'
         and r['delivery'] not in {'default', 'opt-in'})]
    for title, predicate in groups:
        selected = [r for r in records if r['id'] not in superseded and predicate(r)]
        if not selected:
            continue
        lines.extend([f'## {title}', '', '| Decision record | Outcome and scope | Interpretation |',
                      '| --- | --- | --- |'])
        for record in selected:
            scope = record['scope']
            link = 'performance/decisions/' + record['id'] + '.json'
            source = CAT.DOCUMENTS.narrative_link(root, record['sources'][0]['section']).removeprefix('docs/')
            description = f"{record['outcome']}; {', '.join(scope['runtimes'])}. {record['summary']}"
            lines.append(f"| [{cell(record['title'])}]({link}) | {cell(description)} | [Evidence]({source}) |")
        lines.append('')
    lines.extend(['## Reading boundaries', '',
                  'The registry does not normalize observations, pool historical effects or verify',
                  'archived raw bytes without hydration. Section hashes detect interpretation drift;',
                  'artifact identities are checked against the catalog and any present local raw file.',
                  'Historical evidence checks independently verify archived originals. Test durations,',
                  'working reservations, RSS, logical traffic and physical I/O remain distinct.', '',
                  'Future work stays in [GitHub Issues](https://github.com/jsmatfess/chopper/issues). Adding a record does not authorize an experiment.', ''])
    return '\n'.join(lines)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Reject invalid records or stale overview; never write')
    mode.add_argument('--query', action='store_true', help='List matching decisions (current by default)')
    mode.add_argument('--show', metavar='ID', help='Print a full decision record as JSON')
    parser.add_argument('--subsystem')
    parser.add_argument('--runtime')
    parser.add_argument('--disposition')
    parser.add_argument('--delivery')
    parser.add_argument('--include-superseded', action='store_true')
    parser.add_argument('--json', action='store_true', help='Emit query results as JSON')
    args = parser.parse_args(argv)
    filters = ('subsystem', 'runtime', 'disposition', 'delivery')
    if not args.query and (any(getattr(args, f) for f in filters) or args.include_superseded or args.json):
        parser.error('query filters require --query')
    try:
        records = load_records(root)
        if args.show:
            selected = [r for r in records if r['id'] == args.show]
            require(selected, f'Unknown decision ID: {args.show}')
            print(json.dumps(selected[0], indent=2, ensure_ascii=False))
        elif args.query:
            superseded = superseded_ids(records)
            selected = [r for r in records if (args.include_superseded or r['id'] not in superseded)
                        and all(not getattr(args, f) or r[f] == getattr(args, f)
                                for f in filters if f != 'runtime')
                        and (not args.runtime or args.runtime in r['scope']['runtimes'])]
            if args.json:
                print(json.dumps({'schema_version': 1, 'coverage': 'selected decisions only',
                                  'records': selected}, indent=2, ensure_ascii=False))
            else:
                for record in selected:
                    print(f"{record['id']}\t{record['disposition']}\t{record['delivery']}\t{record['summary']}")
        else:
            output = render(records, root).encode('utf-8')
            if args.check:
                require((root / OVERVIEW).read_bytes() == output,
                        'Performance overview is stale; review records then run scripts/performance-registry.py')
            else:
                (root / OVERVIEW).write_bytes(output)
            print(f'{len(records)} performance decisions {"checked" if args.check else "written"}')
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Performance registry: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
