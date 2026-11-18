#!/usr/bin/env python3
"""Check extracted narrative identities, build the compatibility index, or query topics."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('evidence_documents', Path(__file__).with_name('evidence-documents.py'))
DOC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DOC)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--query', action='store_true')
    mode.add_argument('--register', metavar='PATH', help='Register a new reviewed investigation document')
    parser.add_argument('--topic')
    parser.add_argument('--match', default='')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if not (args.query or args.register) and (args.topic or args.match or args.json):
        parser.error('filters require --query')
    try:
        data = DOC.read_manifest(root)
        if args.register:
            path = Path(args.register)
            DOC.require(path.parent == DOC.DIRECTORY and path.suffix == '.md' and args.topic,
                        'Registration requires an investigation .md path and --topic')
            DOC.require(not (root / path).is_symlink(), 'Linked investigation document')
            raw = (root / path).read_bytes()
            DOC.require(b'\r' not in raw, 'Investigation documents must use LF line endings; save as LF before registering')
            parsed = DOC.sections(raw.decode('utf-8'))
            DOC.require(len(parsed) == 1 and parsed[0]['anchor'] == path.stem,
                        'New document must own one H2 whose anchor matches its filename')
            DOC.require(not any(e['id'] == path.stem for e in data['investigations']), 'ID already registered')
            s = parsed[0]
            data['investigations'].append({'id': path.stem, 'title': s['title'], 'anchor': path.stem,
                'path': path.as_posix(), 'topic': args.topic, 'legacy_anchors': [path.stem],
                'original_section_sha256': DOC.sha256('\n'.join(s['lines']).encode()),
                'sha256': DOC.sha256(raw), 'relocations': []})
            manifest = root / DOC.MANIFEST
            original = manifest.read_bytes()
            try:
                manifest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')
                DOC.performance_sections(root)
            except (OSError, ValueError, KeyError, TypeError):
                manifest.write_bytes(original)
                raise
            (root / DOC.LEGACY).write_bytes(DOC.render_compatibility(data).encode())
            print('Registered ' + path.as_posix())
            return 0
        sections = DOC.performance_sections(root)
        if args.query:
            selected = [{key: e[key] for key in ('id', 'title', 'topic', 'path', 'sha256', 'legacy_anchors')}
                        for e in data['investigations'] if (not args.topic or args.topic == e['topic'])
                        and args.match.lower() in (e['title'] + ' ' + e['topic']).lower()]
            if args.json:
                print(json.dumps({'schema_version': 1, 'investigations': selected}, indent=2, ensure_ascii=False))
            else:
                for e in selected:
                    print(f'{e["path"]}\t{e["topic"]}\t{e["title"]}')
        else:
            output = DOC.render_compatibility(data).encode()
            if args.check:
                DOC.require((root / DOC.LEGACY).read_bytes() == output, 'Performance compatibility index is stale')
            else:
                (root / DOC.LEGACY).write_bytes(output)
            print(f'{len(sections)} narratives {"checked" if args.check else "indexed"}; original content reconstruction verified')
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Performance narratives: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
