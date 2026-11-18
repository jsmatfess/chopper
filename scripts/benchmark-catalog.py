#!/usr/bin/env python3
"""Index immutable benchmark artifacts, or export lossless records with provenance.

No metric normalization, inferred run eligibility, or statistical pooling occurs.
Only the Python standard library is required. Run from any working directory.
"""
import argparse
import collections
import fnmatch
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = Path('docs/benchmarks')
GENERATED = {'README.md', 'INDEX.md', 'catalog.json', '.gitignore'}
# Historical mentions retain their original names; navigation follows the owning
# removal archive rather than implying the old harness is still executable.
SCRIPT_ARCHIVES = {'scripts/validate-parallel-groups.py':
                   'docs/history/rejected-parallel-groups-2026-10-25/validate-parallel-groups.py'}
SCRIPT_ARCHIVES.update({
    'scripts/benchmark-flexible.py': 'docs/history/shuffle-harnesses-2026-11-16/benchmark-flexible.py',
    'scripts/benchmark-allocation-ranges.py': 'docs/history/shuffle-harnesses-2026-11-16/benchmark-allocation-ranges.py',
    'scripts/validate-allocation-ranges.py': 'docs/history/shuffle-harnesses-2026-11-16/validate-allocation-ranges.py',
    'scripts/validate-partition-first.py': 'docs/history/shuffle-harnesses-2026-11-16/validate-partition-first.py',
    'scripts/benchmark-partition-first.py': 'docs/history/shuffle-harnesses-2026-11-16/benchmark-partition-first.py',
    'scripts/benchmark-random-buckets.py': 'docs/history/shuffle-harnesses-2026-11-16/benchmark-random-buckets.py',
    'scripts/benchmark-fast-rng.py': 'docs/history/shuffle-harnesses-2026-11-16/benchmark-fast-rng.py',
    'scripts/followup-bucket-window.py': 'docs/history/shuffle-harnesses-2026-11-16/followup-bucket-window.py',
    'scripts/reproduce-bucket-window.py': 'docs/history/shuffle-harnesses-2026-11-16/reproduce-bucket-window.py',
})
RESOLVER_SPEC = importlib.util.spec_from_file_location('evidence_resolver', Path(__file__).with_name('evidence-resolver.py'))
RESOLVER = importlib.util.module_from_spec(RESOLVER_SPEC)
RESOLVER_SPEC.loader.exec_module(RESOLVER)
DOCUMENTS_SPEC = importlib.util.spec_from_file_location('evidence_documents', Path(__file__).with_name('evidence-documents.py'))
DOCUMENTS = importlib.util.module_from_spec(DOCUMENTS_SPEC)
DOCUMENTS_SPEC.loader.exec_module(DOCUMENTS)


def artifact_paths(root):
    local = {p.relative_to(root).as_posix() for p in (root / ARTIFACTS).iterdir()
             if p.is_file() and p.name not in GENERATED}
    return [root / alias for alias in sorted(local | set(RESOLVER.registry(root)['artifacts']))]


def original_path(path):
    if path.is_file():
        return path
    # Catalog aliases are direct children of docs/benchmarks, including in tests.
    root = path.parent.parent.parent
    return RESOLVER.resolve(root, path.relative_to(root).as_posix())


def records(path):
    """Yield stable JSON pointers or physical JSONL line numbers, including nulls."""
    if path.suffix == '.jsonl':
        with original_path(path).open(encoding='utf-8') as stream:
            for line, value in enumerate(stream, 1):
                if value.strip():
                    try:
                        yield {'line': line}, json.loads(value)
                    except ValueError as error:
                        raise ValueError(f'{path}:{line}: {error}') from error
    elif path.suffix == '.json':
        # A summary/report is one document, not extra independent observations.
        try:
            yield {'pointer': ''}, json.loads(original_path(path).read_text(encoding='utf-8'))
        except ValueError as error:
            raise ValueError(f'{path}: {error}') from error


def kind(value):
    if not isinstance(value, dict):
        return 'untyped'
    tag = value.get('type', value.get('event'))
    return str(tag) if tag is not None else 'untyped'


sections = DOCUMENTS.sections
performance_sections = DOCUMENTS.performance_sections


def build_catalog(root):
    artifacts = artifact_paths(root)
    performance = root / 'docs/performance.md'
    experiments = []
    for section in performance_sections(root):
        if section['title'] == 'Reading guide':
            continue
        body = '\n'.join(section['lines'])
        # Include code/plain references as well as Markdown links, without
        # assigning an artifact to an experiment solely from a filename prefix.
        linked = [p.relative_to(root).as_posix() for p in artifacts if p.name in body]
        scripts = sorted(set(re.findall(r'scripts/[\w.\-]+\.(?:py|mjs|sh)', body)))
        experiment = {'title': section['title'],
                      'evidence': 'docs/performance.md#' + section['anchor'],
                      'artifacts': linked, 'scripts': scripts}
        if 'narrative' in section:
            experiment['narrative'] = section['narrative']
        experiments.append(experiment)
    entries = []
    hashes = collections.defaultdict(list)
    for path in artifacts:
        relative = path.relative_to(root).as_posix()
        counts, fields, contexts = collections.Counter(), set(), []
        for location, value in records(path):
            tag = kind(value)
            counts[tag] += 1
            if isinstance(value, dict):
                fields.update(value)
            if tag in {'environment', 'context', 'design', 'fixture', 'fixture_summary'}:
                contexts.append({**location, 'kind': tag})
        original = original_path(path)
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        hashes[digest].append(relative)
        entries.append({'path': relative, 'sha256': digest,
                        'bytes': original.stat().st_size,
                        'format': path.suffix.lstrip('.'),
                        'record_counts': dict(sorted(counts.items())),
                        'fields': sorted(fields), 'context_records': contexts,
                        'evidence': [e['evidence'] for e in experiments if relative in e['artifacts']]})
    result = {'schema_version': 1,
            'scope': 'Inventory and source locations; no inferred eligibility or pooled performance claims.',
            'evidence_document': {'path': 'docs/performance.md',
                                  'sha256': hashlib.sha256(performance.read_bytes()).hexdigest()},
            'experiments': experiments, 'artifacts': entries,
            'identical_content': [paths for paths in hashes.values() if len(paths) > 1]}
    registry = root / RESOLVER.REGISTRY
    if (root / DOCUMENTS.MANIFEST).is_file():
        result['narrative_manifest'] = {'path': DOCUMENTS.MANIFEST.as_posix(),
                                       'sha256': DOCUMENTS.sha256((root / DOCUMENTS.MANIFEST).read_bytes())}
    if registry.is_file():
        result['archive_registry'] = {'path': RESOLVER.REGISTRY.as_posix(),
                                      'sha256': hashlib.sha256(registry.read_bytes()).hexdigest()}
    return result


def render_index(catalog, archived=None):
    archived = archived or {}
    def artifact_link(path):
        return ('../evidence-originals.md#sha256-' + archived[path]['sha256']
                if path in archived else Path(path).name)
    lines = ['# Benchmark evidence index', '',
             'Generated by `python3 scripts/benchmark-catalog.py`. Do not edit manually.', '',
             '[Comparison rules and export](README.md) · [Machine-readable catalog](catalog.json) · [Active issues](https://github.com/jsmatfess/chopper/issues)', '',
             f"{len(catalog['artifacts'])} artifacts; {len(catalog['experiments'])} evidence sections. "
             'Counts describe records/documents, not independent performance samples. '
             'A document may cover several experiments, and a section may reference several passes.', '',
             '## Evidence and reproduction', '',
             '| Evidence section | Referenced artifacts | Scripts mentioned |',
             '| --- | ---: | --- |']
    for experiment in catalog['experiments']:
        url = ('../' + experiment['narrative']['path'].removeprefix('docs/')
               if 'narrative' in experiment else '../performance.md#' + experiment['evidence'].split('#', 1)[1])
        scripts = ', '.join(f'[{Path(s).name}](../../{SCRIPT_ARCHIVES.get(s, s)})' for s in experiment['scripts']) or '—'
        lines.append(f"| [{experiment['title']}]({url}) | {len(experiment['artifacts'])} | {scripts} |")
    lines += ['', '## Artifact inventory', '',
              'Search filenames or record kinds here, or filter `catalog.json` for field names and source locations. '
              '“Linked” means an explicit filename reference in a top-level performance section; '
              'an unlinked artifact may still be discussed in another document or summary. '
              'Filenames are navigation hints, not eligibility labels. Initial, partial, invalid and failure records remain preserved.', '',
              '| Artifact | Format | Records by declared kind | Evidence |',
              '| --- | --- | --- | --- |']
    for entry in catalog['artifacts']:
        name = Path(entry['path']).name
        counts = ', '.join(f'{tag}: {count}' for tag, count in entry['record_counts'].items()) or 'text log'
        evidence = ', '.join(f'[section {i + 1}](../performance.md#{link.split("#", 1)[1]})'
                             for i, link in enumerate(entry['evidence'])) or 'unlinked'
        link = artifact_link(entry['path'])
        lines.append(f"| [{name}]({link}) | {entry['format']} | {counts} | {evidence} |")
    lines += ['', '## Identical content', '',
              'Identical bytes do not create additional independent evidence. Paths are retained for stable citations.', '']
    lines += ['- ' + ', '.join(f'[{Path(p).name}]({artifact_link(p)})' for p in paths)
              for paths in catalog['identical_content']] or ['No byte-identical artifact files.']
    return '\n'.join(lines) + '\n'


def export_records(root, pattern, stream):
    for path in artifact_paths(root):
        if path.name in GENERATED or path.suffix not in {'.json', '.jsonl'} or not fnmatch.fnmatchcase(path.name, pattern):
            continue
        digest = hashlib.sha256(original_path(path).read_bytes()).hexdigest()
        for location, value in records(path):
            envelope = {'schema_version': 1, 'source': path.relative_to(root).as_posix(),
                        'source_sha256': digest, **location, 'kind': kind(value), 'data': value}
            stream.write(json.dumps(envelope, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='fail if generated catalog/index are stale')
    mode.add_argument('--export-records', action='store_true', help='emit lossless source envelopes to stdout')
    parser.add_argument('--match', default='*', help='artifact filename glob for export (default: all)')
    args = parser.parse_args()
    if args.export_records:
        export_records(ROOT, args.match, sys.stdout)
        return 0
    if args.match != '*':
        parser.error('--match requires --export-records')
    catalog = build_catalog(ROOT)
    outputs = {'catalog.json': json.dumps(catalog, indent=2, ensure_ascii=False, allow_nan=False) + '\n',
               'INDEX.md': render_index(catalog, RESOLVER.registry(ROOT)['artifacts'])}
    stale = []
    for name, content in outputs.items():
        path = ROOT / ARTIFACTS / name
        encoded = content.encode('utf-8')
        if args.check:
            if not path.exists() or path.read_bytes() != encoded:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.write_bytes(encoded)
    if stale:
        print('Stale: ' + ', '.join(stale) + '; run python3 scripts/benchmark-catalog.py', file=sys.stderr)
        return 1
    print(f"{'Checked' if args.check else 'Indexed'} {len(catalog['artifacts'])} artifacts and {len(catalog['experiments'])} evidence sections.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
