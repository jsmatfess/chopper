#!/usr/bin/env python3
"""Local-only evidence manifest preparation and retrieval verification (stdlib)."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import stat
import sys
import tarfile
import unicodedata
from urllib.parse import urlsplit
import zipfile


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs)


def write(path, value):
    # Never overwrite evidence, a plan, or an earlier verification attempt.
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def relative(name):
    require(isinstance(name, str) and name and '\\' not in name,
            'expected exact POSIX relative path')
    parts = name.split('/')
    require(all(p not in {'', '.', '..'} and not p.endswith(('.', ' '))
                and not any(ord(c) < 32 or c in ':*?<>|"' for c in p)
                and p.split('.')[0].upper() not in
                {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                 *(f'LPT{i}' for i in range(1, 10))} for p in parts),
            'unsafe path: ' + name)
    return name


def unique(names):
    seen = set()
    for name in names:
        relative(name)
        key = unicodedata.normalize('NFC', name).casefold()
        require(key not in seen, 'duplicate/ambiguous path: ' + name)
        require(not any(key.startswith(p + '/') or p.startswith(key + '/') for p in seen),
                'file/directory ambiguity: ' + name)
        seen.add(key)


def local(root, name):
    relative(name)
    root = Path(root).resolve()
    path = root
    for part in name.split('/'):
        path = path / part
        require(not path.is_symlink() and not getattr(path, 'is_junction', lambda: False)(), 'linked path: ' + name)
    require(path.is_file(), 'missing regular file: ' + name)
    return path


def digest(stream):
    sha, size = hashlib.sha256(), 0
    while block := stream.read(1024 * 1024):
        sha.update(block)
        size += len(block)
    return {'bytes': size, 'sha256': sha.hexdigest()}


def identity(path):
    before = path.stat()
    with path.open('rb') as stream:
        result = digest(stream)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns, before.st_ino) ==
            (after.st_size, after.st_mtime_ns, after.st_ino), 'file changed while hashing')
    return result


def valid_identity(value):
    require(set(value) == {'bytes', 'sha256'} and type(value['bytes']) is int
            and value['bytes'] >= 0 and isinstance(value['sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', value['sha256']), 'invalid byte identity')


def locator(value, sha):
    if value is None:
        return
    require(set(value) == {'bucket', 'key', 'version', 'access', 'reader'}, 'invalid locator fields')
    require(value['bucket'] in {'chopper-evidence-public', 'chopper-archive-private'}, 'unapproved bucket')
    require(value['key'] == 'sha256/' + sha, 'key must address full container hash')
    require(value['version'] == sha, 'version must be immutable content SHA256')
    public = value['bucket'] == 'chopper-evidence-public'
    require(value['access'] == ('public-https' if public else 'private-authenticated'), 'access mismatch')
    reader = urlsplit(value['reader'])
    require(not reader.query and not reader.fragment and not reader.username and not reader.password,
            'credentials, signed URLs and fragments forbidden')
    if public:
        require(reader.scheme == 'https' and reader.hostname and not reader.hostname.endswith('.r2.dev')
                and reader.path == '/' + value['key'], 'expected stable custom-domain object URL')
    else:
        require(value['reader'] == 'r2://' + value['bucket'] + '/' + value['key'], 'expected private stable R2 locator')


def members(path, kind):
    """Read archives without extracting; reject links and every non-file entry."""
    result = []
    if kind == 'zip':
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            unique([e.filename for e in entries])
            for entry in entries:
                mode = entry.external_attr >> 16
                require(not entry.is_dir() and stat.S_IFMT(mode) in {0, stat.S_IFREG},
                        'archive non-regular member')
                with archive.open(entry) as stream:
                    result.append({'path': entry.filename, **digest(stream)})
    elif kind == 'tar':
        with tarfile.open(path, 'r:*') as archive:
            entries = archive.getmembers()
            unique([e.name for e in entries])
            for entry in entries:
                require(entry.isfile() and not entry.issparse(), 'archive non-regular/sparse member')
                with archive.extractfile(entry) as stream:
                    result.append({'path': entry.name, **digest(stream)})
    else:
        require(kind == 'file', 'unsupported container kind')
    return sorted(result, key=lambda x: x['path'])


METADATA = {'run_id', 'outcome', 'failure', 'incomplete', 'exclusions', 'source',
            'build', 'vendor', 'features', 'harness', 'workload', 'configuration', 'commands'}


def validate(manifest):
    require(set(manifest) == {'schema_version', 'artifacts'} and manifest['schema_version'] == 1,
            'unsupported manifest schema')
    require(isinstance(manifest['artifacts'], list) and manifest['artifacts'], 'empty manifest')
    aliases, ids = [], []
    for artifact in manifest['artifacts']:
        require(set(artifact) == {'id', 'aliases', 'original', 'metadata', 'container', 'storage'},
                'invalid artifact fields')
        ids.append(artifact['id'])
        require(isinstance(artifact['id'], str) and artifact['id'], 'invalid artifact ID')
        require(isinstance(artifact['aliases'], list) and artifact['aliases'], 'missing aliases')
        aliases.extend(artifact['aliases'])
        valid_identity(artifact['original'])
        metadata = artifact['metadata']
        require(set(metadata) == METADATA, 'metadata fields missing/unknown')
        require(metadata['outcome'] in {None, 'passed', 'failed', 'incomplete', 'excluded'}, 'invalid outcome')
        require(metadata['incomplete'] is None or type(metadata['incomplete']) is bool, 'invalid incomplete flag')
        require(metadata['outcome'] != 'incomplete' or metadata['incomplete'] is True, 'inconsistent incomplete outcome')
        container = artifact['container']
        require(set(container) == {'kind', 'identity', 'members'}, 'invalid container')
        require(container['kind'] in {'file', 'zip', 'tar'}, 'invalid container kind')
        valid_identity(container['identity'])
        require(container['identity'] == artifact['original'], 'container must preserve original bytes')
        unique([m['path'] for m in container['members']])
        for member in container['members']:
            valid_identity({k: v for k, v in member.items() if k != 'path'})
        require(container['kind'] != 'file' or not container['members'], 'plain file has members')
        locator(artifact['storage'], artifact['original']['sha256'])
    unique(aliases)
    require(len(ids) == len(set(ids)), 'duplicate artifact ID')
    references = {alias: a['original'] for a in manifest['artifacts'] for alias in a['aliases']}
    for artifact in manifest['artifacts']:
        for field in ('source', 'build', 'vendor', 'harness'):
            refs = artifact['metadata'][field]
            require(refs is None or isinstance(refs, list) and refs, 'identity references must be null or nonempty list')
            for ref in refs or []:
                require(set(ref) == {'path', 'bytes', 'sha256'}, 'invalid provenance reference')
                relative(ref['path'])
                expected = {k: v for k, v in ref.items() if k != 'path'}
                valid_identity(expected)
                require(references.get(ref['path']) == expected, 'unresolved/mismatched provenance reference')


def prepare(root, plan):
    require(set(plan) == {'schema_version', 'artifacts'} and plan['schema_version'] == 1, 'invalid plan')
    output = {'schema_version': 1, 'artifacts': []}
    for item in plan['artifacts']:
        require(set(item) == {'id', 'aliases', 'kind', 'metadata', 'storage'}, 'invalid plan artifact')
        require(item['aliases'], 'missing aliases')
        paths = [local(root, alias) for alias in item['aliases']]
        original = identity(paths[0])
        require(all(identity(path) == original for path in paths), 'aliases have different bytes')
        archive_members = members(paths[0], item['kind'])
        require(all(identity(path) == original for path in paths), 'source changed during preparation')
        output['artifacts'].append({'id': item['id'], 'aliases': item['aliases'],
                                  'original': original, 'metadata': item['metadata'],
                                  'container': {'kind': item['kind'], 'identity': original,
                                                'members': archive_members},
                                  'storage': item['storage']})
    validate(output)
    return output


def verify(manifest_path, root, receipt):
    manifest_hash = identity(Path(manifest_path))['sha256']
    manifest = load(manifest_path)
    validate(manifest)
    require(set(receipt) == {'schema_version', 'manifest_sha256', 'reader', 'objects'}
            and receipt['schema_version'] == 1 and receipt['manifest_sha256'] == manifest_hash,
            'stale/invalid retrieval receipt')
    require(receipt['reader'] in {'local', 'intended-reader'}, 'invalid reader mode')
    require(set(receipt['objects']) == {a['id'] for a in manifest['artifacts']}, 'incomplete retrieval set')
    results = []
    for artifact in manifest['artifacts']:
        entry = receipt['objects'][artifact['id']]
        require(set(entry) == {'path', 'reader'}, 'invalid receipt object')
        if receipt['reader'] == 'intended-reader':
            require(artifact['storage'] is not None and entry['reader'] == artifact['storage']['reader'],
                    'reader differs from intended access path')
        else:
            require(entry['reader'] is None, 'local receipt must not claim external retrieval')
        path = local(root, entry['path'])
        require(identity(path) == artifact['original'], 'retrieved object hash/size mismatch')
        require(members(path, artifact['container']['kind']) == artifact['container']['members'],
                'archive member mismatch')
        require(identity(path) == artifact['original'], 'object changed during verification')
        results.append({'id': artifact['id'], 'result': 'verified', 'reader': entry['reader']})
    require(identity(Path(manifest_path))['sha256'] == manifest_hash, 'manifest changed during verification')
    return {'schema_version': 1, 'manifest_sha256': manifest_hash,
            'receipt_sha256': hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest(),
            'verified_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope': receipt['reader'], 'result': 'verified', 'objects': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('prepare')
    scan.add_argument('--plan', required=True)
    scan.add_argument('--root', required=True)
    scan.add_argument('--output', required=True)
    check = sub.add_parser('verify')
    check.add_argument('--manifest', required=True)
    check.add_argument('--downloads', required=True)
    check.add_argument('--receipt', required=True)
    check.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        result = (prepare(args.root, load(args.plan)) if args.command == 'prepare' else
                  verify(args.manifest, args.downloads, load(args.receipt)))
        write(args.output, result)
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, tarfile.TarError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
