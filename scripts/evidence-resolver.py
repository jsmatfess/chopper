#!/usr/bin/env python3
"""Resolve archived evidence aliases through an explicit, hash-verified local cache.

Hydration is a separate authenticated network operation. Reading or auditing
evidence never downloads implicitly and never substitutes sanitized derivatives.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

REGISTRY = Path('docs/evidence-registry.v1.json')
CACHE = Path('scratch/evidence-cache')
INDEX = Path('docs/evidence-originals.md')


def identity(path):
    sha = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            sha.update(block)
            size += len(block)
    return {'bytes': size, 'sha256': sha.hexdigest()}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def safe_path(value):
    require(isinstance(value, str) and value and '\\' not in value,
            'expected POSIX evidence path')
    require(all(p not in {'', '.', '..'} and not any(c in p for c in ':*?<>|"')
                for p in value.split('/')), 'unsafe evidence path')
    return value


def valid_identity(value):
    require(set(value) == {'bytes', 'sha256'} and type(value['bytes']) is int
            and value['bytes'] >= 0 and isinstance(value['sha256'], str)
            and re.fullmatch('[a-f0-9]{64}', value['sha256']), 'invalid evidence identity')


def registry(root):
    path = root / REGISTRY
    if not path.exists():
        return {'schema_version': 1, 'bundles': {}, 'artifacts': {}}
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate evidence registry key')
            result[key] = value
        return result
    result = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=pairs)
    require(set(result) == {'schema_version', 'bundles', 'artifacts'}
            and result['schema_version'] == 1, 'unsupported evidence registry')
    require(isinstance(result['bundles'], dict) and isinstance(result['artifacts'], dict),
            'invalid evidence registry collections')
    for sha, bundle in result['bundles'].items():
        require(set(bundle) == {'bytes', 'sha256', 'reader'}, 'invalid evidence bundle')
        valid_identity({k: bundle[k] for k in ('bytes', 'sha256')})
        require(sha == bundle['sha256'] and bundle['reader'] ==
                'r2://chopper-archive-private/sha256/' + sha, 'unapproved evidence reader')
    for alias, artifact in result['artifacts'].items():
        safe_path(alias)
        require(alias.startswith('docs/benchmarks/'), 'alias outside benchmark evidence')
        require(set(artifact) == {'bytes', 'sha256', 'bundle', 'member'}, 'invalid evidence artifact')
        valid_identity({k: artifact[k] for k in ('bytes', 'sha256')})
        require(artifact['bundle'] in result['bundles'] and
                artifact['member'] == 'objects/' + artifact['sha256'], 'invalid evidence member')
    return result


def checked_path(root, relative):
    path = root
    for part in safe_path(relative).split('/'):
        path = path / part
        require(not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(),
                'linked evidence path')
    return path


def resolve(root, alias):
    """Return the local original, or an exact cached original for its alias."""
    root = Path(root)
    source = checked_path(root, alias)
    if source.is_file():
        return source
    entry = registry(root)['artifacts'].get(alias)
    if entry is None:
        raise FileNotFoundError('Missing evidence: ' + alias)
    cached = checked_path(root, (CACHE / entry['sha256']).as_posix())
    require(cached.is_file(), 'Archived evidence is not hydrated: ' + alias +
            '; run python scripts/evidence-resolver.py hydrate --wrangler PATH_TO_WRANGLER_JS')
    require(identity(cached) == {k: entry[k] for k in ('bytes', 'sha256')},
            'Cached evidence hash/size mismatch: ' + alias)
    return cached


def hydrate(root, wrangler=None, s3_client=None):
    """Download fixed private keys, verify full bundles, then cache exact members."""
    root = Path(root).resolve()
    data = registry(root)
    cache = checked_path(root, CACHE.as_posix())
    cache.mkdir(parents=True, exist_ok=True)
    count = 0
    for sha, bundle in sorted(data['bundles'].items()):
        target = checked_path(root, (CACHE / ('bundle-' + sha + '.tar')).as_posix())
        expected = {k: bundle[k] for k in ('bytes', 'sha256')}
        if target.exists():
            require(identity(target) == expected, 'Existing bundle cache mismatch')
        else:
            with tempfile.TemporaryDirectory(prefix='download-', dir=cache) as tmp:
                download = Path(tmp) / 'bundle.tar'
                if s3_client is None:
                    require(wrangler is not None, 'Select an authenticated reader')
                    subprocess.run(['node', str(wrangler), 'r2', 'object', 'get',
                                    'chopper-archive-private/sha256/' + sha, '--remote',
                                    '--file', str(download)], cwd=root, check=True, timeout=240)
                else:
                    response = s3_client.get_object(Bucket='chopper-archive-private', Key='sha256/' + sha)
                    body = response['Body']
                    try:
                        require(response['ContentLength'] == bundle['bytes'], 'S3 object length mismatch')
                        size = 0
                        with download.open('xb') as stream:
                            while block := body.read(1024 * 1024):
                                size += len(block)
                                require(size <= bundle['bytes'], 'Oversized S3 object')
                                stream.write(block)
                    finally:
                        body.close()
                require(identity(download) == expected, 'Downloaded bundle hash/size mismatch')
                # Exclusive creation preserves an existing cache entry on races.
                with download.open('rb') as src, target.open('xb') as dst:
                    while block := src.read(1024 * 1024):
                        dst.write(block)
        with tarfile.open(target) as archive:
            entries = archive.getmembers()
            require(len({e.name for e in entries}) == len(entries), 'Duplicate bundle members')
            require(all(e.isfile() and not e.issparse() and
                        re.fullmatch('objects/[a-f0-9]{64}', e.name) for e in entries),
                    'Unsafe bundle member')
            for alias, item in sorted(data['artifacts'].items()):
                if item['bundle'] != sha:
                    continue
                expected_item = {k: item[k] for k in ('bytes', 'sha256')}
                destination = checked_path(root, (CACHE / item['sha256']).as_posix())
                if destination.exists():
                    require(identity(destination) == expected_item, 'Existing original cache mismatch')
                else:
                    member = archive.getmember(item['member'])
                    require(member.size == item['bytes'], 'Archive member size mismatch')
                    with tempfile.TemporaryDirectory(prefix='member-', dir=cache) as tmp:
                        scratch = Path(tmp) / 'original'
                        with archive.extractfile(member) as src, scratch.open('xb') as dst:
                            while block := src.read(1024 * 1024):
                                dst.write(block)
                        require(identity(scratch) == expected_item, 'Archive member hash mismatch')
                        with scratch.open('rb') as src, destination.open('xb') as dst:
                            while block := src.read(1024 * 1024):
                                dst.write(block)
                count += 1
    return count


def materialize(root):
    """Restore exact aliases for older consumers, without overwriting any file."""
    root = Path(root)
    count = 0
    for alias, item in registry(root)['artifacts'].items():
        cached = resolve(root, alias)
        require(identity(cached) == {k: item[k] for k in ('bytes', 'sha256')},
                'Original differs from frozen registry: ' + alias)
        target = checked_path(root, alias)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            with cached.open('rb') as src, target.open('xb') as dst:
                while block := src.read(1024 * 1024):
                    dst.write(block)
        count += 1
    return count


def render_index(data):
    groups = {}
    for alias, item in sorted(data['artifacts'].items()):
        group = groups.setdefault(item['sha256'], {'aliases': [], 'bytes': item['bytes']})
        require(group['bytes'] == item['bytes'], 'Inconsistent original size')
        group['aliases'].append(alias)
    lines = ['# Archived evidence originals', '',
             'Generated by `python scripts/evidence-resolver.py index`; do not edit manually.', '',
             'These are preserved original identities, not public download grants or new performance samples. '
             'Sensitive or unreviewed originals remain in private R2. '
             '[Retrieval and verification](evidence-storage.md#archived-original-alias-resolution) '
             'uses the [versioned registry](evidence-registry.v1.json). '
             'Unknown historical replay/provenance remains unknown; current source never substitutes for missing bytes.', '']
    for sha, item in sorted(groups.items(), key=lambda pair: pair[1]['aliases'][0]):
        lines += [f'<a id="sha256-{sha}"></a>', '',
                  '## ' + Path(item['aliases'][0]).name, '',
                  '\n'.join('- `' + alias + '`' for alias in item['aliases']), '',
                  f"Original: {item['bytes']:,} bytes; SHA-256 `{sha}`. "
                  'Private bundle/member locator: [registry](evidence-registry.v1.json).', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['check', 'hydrate', 'index'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--wrangler', type=Path)
    parser.add_argument('--s3', action='store_true',
                        help='use separate R2_READ credentials from the environment (optional Boto3 SDK)')
    parser.add_argument('--restore-aliases', action='store_true',
                        help='after hydration, restore exact aliases for legacy consumers')
    parser.add_argument('--if-missing', action='store_true',
                        help='skip network/credentials when all exact originals are already local')
    parser.add_argument('--check', action='store_true', help='check the generated alias index without writing')
    args = parser.parse_args()
    if args.command == 'index':
        output = render_index(registry(args.root)).encode('utf-8')
        path = args.root / INDEX
        if args.check:
            require(path.is_file() and path.read_bytes() == output, 'Archived evidence index is stale')
        else:
            path.write_bytes(output)
        print('Archived evidence index ' + ('checked.' if args.check else 'written.'))
        return
    if args.check:
        parser.error('--check applies only to index')
    if args.command == 'hydrate':
        if (args.wrangler is None) == (not args.s3):
            parser.error('hydrate requires exactly one of --wrangler or --s3')
        if args.if_missing:
            items = registry(args.root)['artifacts']
            if all(checked_path(args.root, alias).is_file() and
                   identity(checked_path(args.root, alias)) == {k: item[k] for k in ('bytes', 'sha256')}
                   for alias, item in items.items()):
                print('All exact originals are already local; no authenticated download needed.')
                return
        client = None
        if args.s3:
            try:
                import boto3
                from botocore.config import Config
            except ImportError:
                parser.error('S3 hydration requires python -m pip install -r scripts/requirements-evidence.txt')
            endpoint = os.environ.get('R2_ENDPOINT', '')
            require(re.fullmatch(r'https://[a-z0-9.-]+\.r2\.cloudflarestorage\.com/?', endpoint),
                    'Expected R2_ENDPOINT HTTPS S3 endpoint')
            access = os.environ.get('R2_READ_ACCESS_KEY_ID')
            secret = os.environ.get('R2_READ_SECRET_ACCESS_KEY')
            require(access and secret, 'Missing independent R2_READ credentials')
            require(access != os.environ.get('R2_UPLOAD_ACCESS_KEY_ID'), 'Reader must differ from uploader')
            client = boto3.client('s3', endpoint_url=endpoint, region_name='auto',
                                  aws_access_key_id=access, aws_secret_access_key=secret,
                                  config=Config(connect_timeout=15, read_timeout=60,
                                                retries={'max_attempts': 0}, signature_version='s3v4'))
        print(f'Hydrated {hydrate(args.root, args.wrangler, client)} exact original aliases.')
        if args.restore_aliases:
            print(f'Materialized {materialize(args.root)} exact original aliases.')
    else:
        if args.restore_aliases or args.if_missing:
            parser.error('--restore-aliases/--if-missing require hydrate')
        data = registry(args.root)
        for alias, item in data['artifacts'].items():
            require(identity(resolve(args.root, alias)) == {k: item[k] for k in ('bytes', 'sha256')},
                    'Original differs from frozen registry: ' + alias)
        print(f"Verified {len(data['artifacts'])} original aliases.")


if __name__ == '__main__':
    main()
