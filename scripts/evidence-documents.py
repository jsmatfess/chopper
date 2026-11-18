"""Performance narrative storage, legacy identities, and verified public derivatives."""
import collections
import hashlib
import importlib.util
import json
from pathlib import Path
import posixpath
import re

MANIFEST = Path('docs/performance/narratives.v1.json')
LEGACY = Path('docs/performance.md')
DIRECTORY = Path('docs/performance/investigations')
RESOLVER_SPEC = importlib.util.spec_from_file_location('evidence_resolver', Path(__file__).with_name('evidence-resolver.py'))
RESOLVER = importlib.util.module_from_spec(RESOLVER_SPEC)
RESOLVER_SPEC.loader.exec_module(RESOLVER)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def sections(text):
    """Read real H2 sections, ignoring fenced reproduction-code headings."""
    found, current, fence = [], None, None
    used = collections.Counter()
    for line in text.splitlines():
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
        if fence is None and line.startswith('## '):
            title = line[3:].strip()
            anchor = re.sub(r'[^\w\- ]', '', title.lower()).replace(' ', '-')
            suffix = used[anchor]
            used[anchor] += 1
            current = {'title': title, 'anchor': anchor + (f'-{suffix}' if suffix else ''), 'lines': []}
            found.append(current)
        if current:
            current['lines'].append(line)
    return found


def map_links(text, transform):
    """Relocate Markdown destinations, leaving fenced reproduction commands intact."""
    fence, ordinal, output = None, 0, []
    for line in text.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            token = marker[1]
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            output.append(line)
            continue
        if fence is not None:
            output.append(line)
            continue

        def replace(match):
            nonlocal ordinal
            target = match['target']
            result = transform(ordinal, target)
            ordinal += 1
            return match[0][:match.start('target') - match.start()] + result + match[0][match.end('target') - match.start():]
        # Inline/image links and reference-style definitions. Angle brackets are
        # retained by the caller; titles after destinations are unchanged.
        line = re.sub(r'\]\((?P<target><[^>\n]+>|[^\s)]+)', replace, line)
        line = re.sub(r'^\s*\[[^\]\n]+\]:\s*(?P<target><[^>\n]+>|\S+)', replace, line)
        output.append(line)
    return ''.join(output)


def relocate(text, destination, archived=None, *, already_relocated=False):
    """Move legacy links, or update only archived destinations in a standalone narrative."""
    relocations = []
    original_path = destination if already_relocated else LEGACY.as_posix()

    def change(ordinal, token):
        angle = token.startswith('<') and token.endswith('>')
        target = token[1:-1] if angle else token
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith(('/', '//')):
            return token
        path, marker, anchor = target.partition('#')
        source = posixpath.join(posixpath.dirname(original_path), path) if path else original_path
        archive = (archived or {}).get(posixpath.normpath(source))
        if archive:
            source, marker, anchor = 'docs/evidence-originals.md', '#', 'sha256-' + archive['sha256']
        elif already_relocated:
            return token
        moved = posixpath.relpath(source, posixpath.dirname(destination)) + (marker + anchor if marker else '')
        result = '<' + moved + '>' if angle else moved
        if result != token:
            relocations.append({'ordinal': ordinal, 'from': token, 'to': result})
        return result
    return map_links(text, change), relocations


def restore(text, relocations):
    lookup = {item['ordinal']: item for item in relocations}
    require(len(lookup) == len(relocations), 'Duplicate narrative relocation ordinal')
    seen = set()

    def change(ordinal, target):
        if ordinal not in lookup:
            return target
        item = lookup[ordinal]
        require(target == item['to'], 'Narrative link changed; review relocation metadata')
        seen.add(ordinal)
        return item['from']
    result = map_links(text, change)
    require(seen == set(lookup), 'Narrative relocation no longer exists')
    return result


def original_text(raw, entry):
    separators = entry.get('separator_newlines', 0)
    require(type(separators) is int and separators >= 0, 'Invalid narrative separator count')
    return restore(raw.decode('utf-8') + '\n' * separators, entry['relocations'])


def historical_issue_target(target, destination):
    match = re.fullmatch(r'https://github\.com/jsmatfess/chopper/(?:issues|pull)/([1-9][0-9]*)(?:#[^\s]*)?', target)
    if match and int(match[1]) <= 196:
        return posixpath.relpath('docs/history/prior-issues.md', posixpath.dirname(destination)) + '#issue-' + match[1]
    return target


def derivative_original(root, raw, entry):
    derivative = entry['sanitized_derivative']
    require(isinstance(derivative, dict) and set(derivative) == {'policy', 'original_sha256'}
            and derivative['policy'] in {'windows-workstation-root-v1', 'workstation-and-historical-issues-v1'},
            'Unsupported sanitized narrative policy')
    alias = 'docs/benchmarks/' + entry['id'] + '-private-narrative.md'
    artifacts = RESOLVER.registry(root)['artifacts']
    archived_identity = artifacts.get(alias)
    require(archived_identity is not None and archived_identity['sha256'] == derivative['original_sha256'],
            f'Archived narrative identity differs: {alias}')
    archived = RESOLVER.resolve(root, alias).read_bytes()
    require(len(archived) == archived_identity['bytes'] and sha256(archived) == archived_identity['sha256'],
            f'Archived narrative bytes differ: {alias}')
    normalized = re.sub(rb'(?<=`)C:/Users/[A-Za-z0-9_.-]+(?=/[^`\r\n]*`)', b'C:/Users/USER', archived)
    text = normalized.decode('utf-8')
    if derivative['policy'] == 'workstation-and-historical-issues-v1':
        text = map_links(text, lambda ordinal, target: historical_issue_target(target, entry['path']))
    expected, _ = relocate(text, entry['path'], artifacts, already_relocated=True)
    require(normalized != archived and raw == expected.encode('utf-8'), f'Sanitized narrative differs: {entry["path"]}')
    return archived


def read_manifest(root):
    data = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    require(data['schema_version'] == 1 and data['type'] == 'performance_narrative_manifest',
            'Unsupported performance narrative manifest')
    return data


def performance_sections(root):
    if not (root / MANIFEST).exists():
        return sections((root / LEGACY).read_text(encoding='utf-8'))
    data = read_manifest(root)
    result, paths, anchors, restored = [], set(), set(), []
    for entry in data['investigations']:
        path = Path(entry['path'])
        require(path.parent == DIRECTORY and path.suffix == '.md' and path.stem == entry['id'],
                'Unsafe or inconsistent narrative path')
        require(entry['id'] == entry['anchor'] and re.fullmatch(r'[\w-]+', entry['id']), 'Invalid narrative ID')
        require(entry['path'] not in paths, 'Duplicate narrative path')
        require(not (root / path).is_symlink(), 'Linked narrative file')
        raw = (root / path).read_bytes()
        require(sha256(raw) == entry['sha256'], f'Narrative hash changed; review manifest: {path}')
        if 'sanitized_derivative' in entry:
            # Historical relocation metadata applies to the archived standalone bytes.
            raw = derivative_original(root, raw, entry)
        original = original_text(raw, entry)
        parsed = sections(original)
        require(len(parsed) == 1 and parsed[0]['title'] == entry['title'], f'Narrative must own exactly one H2: {path}')
        section = parsed[0]
        section['anchor'] = entry['anchor']
        require(sha256('\n'.join(section['lines']).encode()) == entry['original_section_sha256'],
                f'Original narrative identity changed: {path}')
        for anchor in entry['legacy_anchors']:
            require(re.fullmatch(r'[\w-]+', anchor), 'Invalid legacy anchor')
            require(anchor not in anchors, f'Duplicate legacy narrative anchor: {anchor}')
            anchors.add(anchor)
        require(entry['anchor'] in entry['legacy_anchors'], 'Missing legacy H2 anchor')
        paths.add(entry['path'])
        restored.append(original)
        section['narrative'] = {key: entry[key] for key in ('path', 'sha256', 'topic')}
        result.append(section)
    actual = {p.relative_to(root).as_posix() for p in (root / DIRECTORY).glob('*.md')}
    require(actual == paths, 'Unregistered or missing investigation documents')
    count = data['migrated_count']
    require(type(count) is int and 0 <= count <= len(restored), 'Invalid migrated narrative count')
    original = data['original_preamble'] + ''.join(restored[:count])
    require(sha256(original.encode()) == data['original_document_sha256'], 'Original performance document reconstruction differs')
    return result


def render_compatibility(data):
    original_title = data['original_preamble'].splitlines()[0].lstrip('# ').strip()
    original_anchor = re.sub(r'[^\w\- ]', '', original_title.lower()).replace(' ', '-')
    lines = ['# Performance evidence', '',
             f'<a id="{original_anchor}"></a>', '',
             '<!-- Generated by scripts/performance-narratives.py; edit investigation documents and their manifest. -->', '',
             'Start with the [current decisions](performance-overview.md),',
             '[architecture](architecture.md) or [evidence queries](performance/README.md).',
             'The dated narratives now live in individual investigation documents.',
             'This compatibility index preserves former section anchors, including nested headings.',
             'Topics reuse the reviewed strategy-family assignments; they do not establish comparison eligibility.', '',
             '| Investigation | Evidence topic |', '| --- | --- |']
    for entry in data['investigations']:
        anchors = ''.join(f'<a id="{a}"></a>' for a in entry['legacy_anchors'])
        link = entry['path'].removeprefix('docs/')
        title = entry['title'].replace('|', '\\|')
        lines.append(f'| {anchors}[{title}]({link}) | {entry["topic"]} |')
    return '\n'.join(lines) + '\n'


def narrative_link(root, legacy):
    if not (root / MANIFEST).exists():
        return legacy
    for entry in read_manifest(root)['investigations']:
        if legacy == LEGACY.as_posix() + '#' + entry['anchor']:
            return entry['path']
    raise ValueError('Unknown narrative reference: ' + legacy)
