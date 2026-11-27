#!/usr/bin/env python3
"""Assemble supplied release bytes locally; never build, publish or certify builds."""
import argparse
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import time
import tomllib
import zipfile

HOSTED = ('_headers', 'app.js', 'engine-worker.js', 'engine.wasm', 'index.html',
          'storage-worker.js', 'style.css')
PLATFORMS = {'windows_x86_64': ('windows-x86_64', 'chopper.exe', 'x86_64-pc-windows-msvc'),
             'linux_x86_64': ('linux-x86_64', 'chopper', 'x86_64-unknown-linux-gnu')}
LICENSES = {'LICENSE': 'LICENSE',
            'licenses/zip-2.4.2/LICENSE': 'vendor/zip-2.4.2/LICENSE'}
PAYLOADS = {**LICENSES,
            'README.txt': 'docs/releases/native-quickstart.txt',
            'THIRD-PARTY-NOTICES.txt': 'docs/releases/native-usage.txt',
            'job.schema.json': 'schemas/{version}/job.schema.json',
            'quickstart/customers.csv': 'examples/customers.csv',
            'quickstart/job.json': 'examples/quickstart-job.json'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def match(data, expected):
    require(isinstance(expected, dict), 'Missing identity record')
    require(type(expected.get('bytes')) is int and expected['bytes'] > 0,
            'Missing positive byte size')
    require(re.fullmatch('[0-9a-f]{64}', expected.get('sha256') or '') is not None,
            'Missing full SHA-256')
    require(identity(data) == {k: expected[k] for k in ('bytes', 'sha256')},
            'Input/member identity mismatch')


def read_regular(path):
    require(path.is_file() and not path.is_symlink(), f'Not a regular file: {path}')
    return path.read_bytes()


def production_wasm(data):
    # Reuse the production boundary; no second WASM export parser.
    helper = Path(__file__).with_name('browser-artifacts.mjs').resolve().as_uri()
    result = subprocess.run(['node', '--input-type=module', '-e',
                    "import {readFileSync} from 'node:fs'; "
                    f"import {{assertProductionWasm}} from {json.dumps(helper)}; "
                    'assertProductionWasm(readFileSync(0));'], input=data, check=False,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    require(result.returncode == 0, 'Production WASM validation failed: ' +
            result.stderr.decode(errors='replace').strip())


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args]).decode().strip()


def frozen_source(source, manifest):
    require(not git(source, 'status', '--porcelain', '--untracked-files=all'), 'Source must be clean')
    require(git(source, 'rev-parse', 'HEAD') == manifest['release_source_commit'], 'Source commit mismatch')
    require(git(source, 'rev-parse', 'HEAD^{tree}') == manifest['release_source_tree'], 'Source tree mismatch')
    require(manifest['dirty_source'] is False, 'Frozen source must declare dirty_source false')
    version = manifest['version']
    require(re.fullmatch(r'\d+\.\d+\.\d+', version) is not None, 'Invalid version')
    cargo = tomllib.loads((source / 'Cargo.toml').read_text())
    lock = tomllib.loads((source / 'Cargo.lock').read_text())
    ui = json.loads((source / 'ui/package.json').read_text())
    ui_lock = json.loads((source / 'ui/package-lock.json').read_text())
    versions = [cargo['workspace']['package']['version'], ui['version'], ui_lock['version'],
                ui_lock['packages']['']['version']]
    versions += [p['version'] for p in lock['package'] if p['name'] in
                 ('chopper', 'chopper-csv', 'chopper-core', 'chopper-browser')]
    require(len(versions) == 7 and all(v == version for v in versions), 'Version metadata mismatch')
    required_paths = {path.format(version=version) for path in PAYLOADS.values()}
    required_paths.update({'Cargo.toml', 'Cargo.lock', 'ui/package.json',
                           'ui/package-lock.json', 'scripts/package-release.py',
                           'scripts/browser-artifacts.mjs'})
    tracked = set(git(source, 'ls-files', '-z').split('\0'))
    require(required_paths <= tracked, 'Source payload/version/tool files must be tracked')
    for name in ('package-release.py', 'browser-artifacts.mjs'):
        require(read_regular(source / 'scripts' / name) == read_regular(Path(__file__).with_name(name)),
                'Packaging tools must match frozen source')


def archive_name(version, kind):
    return f'chopper-{version}-{kind}.zip'


def expected_members(kind, legacy=False):
    if kind == 'hosted':
        return set(HOSTED)
    payloads = {*LICENSES, 'README.txt'} if legacy else set(PAYLOADS)
    return payloads | {PLATFORMS[kind][1]}


def write_zip(path, members, executable=None):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if name == executable else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def inspect_zip(path, kind, expected, legacy=False):
    require(set(expected) == expected_members(kind, legacy), 'Receipt member inventory mismatch')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and set(names) == set(expected), 'ZIP member inventory mismatch')
        require(archive.testzip() is None, 'ZIP CRC mismatch')
        for info in archive.infolist():
            mode = info.external_attr >> 16
            require(info.create_system == 3 and stat.S_ISREG(mode), 'ZIP nonregular member')
            require(not info.flag_bits & 1, 'Encrypted ZIP member')
            executable = kind == 'linux_x86_64' and info.filename == 'chopper'
            require(stat.S_IMODE(mode) == (0o755 if executable else 0o644), 'ZIP member permission mismatch')
            data = archive.read(info)
            match(data, expected[info.filename])
            if kind == 'hosted' and info.filename == 'engine.wasm':
                production_wasm(data)


def verify(directory, receipt_sha256):
    receipts = list(directory.glob('chopper-*-artifact-receipt.json'))
    require(len(receipts) == 1, 'Expected one artifact receipt')
    receipt_bytes = read_regular(receipts[0])
    require(identity(receipt_bytes)['sha256'] == receipt_sha256, 'Receipt identity mismatch')
    receipt = json.loads(receipt_bytes)
    version = receipt['version']
    require(re.fullmatch(r'\d+\.\d+\.\d+', version) is not None, 'Invalid version')
    require(receipts[0].name == f'chopper-{version}-artifact-receipt.json', 'Receipt name mismatch')
    require(receipt['schema_version'] == 1 and receipt['packaging_schema_version'] == 1,
            'Unsupported receipt schema')
    packages = {archive_name(version, v[0]): k for k, v in PLATFORMS.items()}
    packages[archive_name(version, 'hosted')] = 'hosted'
    require(set(receipt['packages']) == set(packages), 'Package inventory mismatch')
    require(set(receipt['package_members']) == set(packages), 'Member receipt inventory mismatch')
    require(set(p.name for p in directory.iterdir()) == set(packages) | {receipts[0].name, 'SHA256SUMS'},
            'Unexpected package output')
    legacy = tuple(map(int, version.split('.'))) < (0, 5, 0) and all(
        set(receipt['package_members'][name]) == expected_members(kind, legacy=True)
        for name, kind in packages.items() if kind != 'hosted'
    )
    checksums = {}
    for name, kind in packages.items():
        path = directory / name
        match(read_regular(path), receipt['packages'][name])
        inspect_zip(path, kind, receipt['package_members'][name], legacy)
        checksums[name] = receipt['packages'][name]['sha256']
        members = receipt['package_members'][name]
        if kind == 'hosted':
            require(members == receipt['hosted'], 'Hosted receipt mismatch')
        else:
            require(members[PLATFORMS[kind][1]] == {k: receipt['native'][kind][k]
                    for k in ('bytes', 'sha256')}, 'Native receipt mismatch')
    checksums[receipts[0].name] = receipt_sha256
    sums = ''.join(f'{digest}  {name}\n' for name, digest in sorted(checksums.items())).encode()
    require(read_regular(directory / 'SHA256SUMS') == sums, 'SHA256SUMS mismatch')
    return {'artifact_receipt': identity(receipt_bytes), 'checksums': identity(sums),
            'scope': 'local archive integrity only; no build provenance or acceptance certification'}


def assemble(source, manifest_path, output):
    manifest_bytes = read_regular(manifest_path)
    manifest = json.loads(manifest_bytes)
    require(manifest['schema_version'] == 1 and manifest['packaging_schema_version'] == 1,
            'Unsupported candidate packaging schema')
    frozen_source(source, manifest)
    version = manifest['version']
    require(not output.exists(), 'Output must be a new path')
    if output.is_relative_to(source):
        relative = output.relative_to(source).as_posix() + '/'
        ignored = subprocess.run(['git', '-C', str(source), 'check-ignore', '-q', relative],
                                 check=False).returncode == 0
        require(ignored, 'Output inside source must be ignored')
    hosted_dir = Path(manifest['packaging_inputs']['hosted_directory'])
    require(hosted_dir.is_absolute(), 'Hosted directory must be absolute')
    require(set(p.name for p in hosted_dir.iterdir()) == set(HOSTED), 'Hosted directory must contain exactly seven production members')
    require(set(manifest['native']) == set(PLATFORMS) and set(manifest['hosted']) == set(HOSTED),
            'Candidate inventory mismatch')
    hosted = {name: read_regular(hosted_dir / name) for name in HOSTED}
    for name, data in hosted.items():
        match(data, manifest['hosted'][name])
    production_wasm(hosted['engine.wasm'])
    payloads = {name: read_regular(source / path.format(version=version))
                for name, path in PAYLOADS.items()}
    payloads['README.txt'] = payloads['README.txt'].replace(b'@VERSION@', version.encode('ascii'))
    bundles = {'hosted': hosted}
    for kind, (_, executable, target) in PLATFORMS.items():
        entry = manifest['native'][kind]
        require(entry['target'] == target, 'Unsupported native target')
        path = Path(manifest['packaging_inputs'][kind])
        require(path.is_absolute(), 'Executable path must be absolute')
        data = read_regular(path)
        match(data, entry)
        bundles[kind] = {**payloads, executable: data}
    # Read all bytes first; recheck source before writing. Artifact hashes bind the
    # actual bytes captured, not paths that could subsequently change.
    frozen_source(source, manifest)
    receipt = {k: copy.deepcopy(manifest[k]) for k in
               ('schema_version', 'version', 'release_source_commit', 'release_source_tree',
                'dirty_source', 'native', 'hosted')}
    receipt.update(packaging_schema_version=1, candidate_revision=1,
                   status='assembled locally; build provenance, acceptance and publication pending',
                   version_approved=False, publication_approved=False,
                   source_input_sets=None, toolchains=None, validation_attempts=None,
                   packaging_input_manifest=identity(manifest_bytes),
                   packaging_tools={name: identity(read_regular(Path(__file__).with_name(name)))
                                    for name in ('package-release.py', 'browser-artifacts.mjs')},
                   provenance_scope='Source identity and provided byte hashes checked; build-to-source relationship not certified',
                   packages={}, package_members={})
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep failures for inspection; never overwrite an earlier attempt.
    output.mkdir()
    for kind, members in bundles.items():
        suffix = 'hosted' if kind == 'hosted' else PLATFORMS[kind][0]
        name = archive_name(version, suffix)
        write_zip(output / name, members, 'chopper' if kind == 'linux_x86_64' else None)
        receipt['packages'][name] = identity((output / name).read_bytes())
        receipt['package_members'][name] = {n: identity(b) for n, b in sorted(members.items())}
    receipt_name = f'chopper-{version}-artifact-receipt.json'
    receipt_bytes = (json.dumps(receipt, indent=2) + '\n').encode()
    (output / receipt_name).write_bytes(receipt_bytes)
    sums = {n: v['sha256'] for n, v in receipt['packages'].items()}
    sums[receipt_name] = identity(receipt_bytes)['sha256']
    (output / 'SHA256SUMS').write_bytes(''.join(f'{v}  {n}\n' for n, v in sorted(sums.items())).encode())
    return verify(output, sums[receipt_name])


def verify_quickstart(output, version, source_rows):
    parts = {f'part-{i:08}.csv': count for i, count in enumerate((5, 5, 2), 1)}
    require({p.name for p in output.iterdir()} == {*parts, 'manifest.jsonl'},
            'Quickstart output inventory mismatch')
    manifest = [json.loads(line) for line in
                (output / 'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
    job, *files = manifest
    require(job['type'] == 'job' and job['application_version'] == version
            and job['analysis']['rows'] == 12 and job['config']['limits']['rows'] == 5,
            'Quickstart job record mismatch')
    require([(f['path'], f['rows']) for f in files] == list(parts.items()),
            'Quickstart manifest filenames or row counts mismatch')
    all_rows = []
    for entry in files:
        path = output / entry['path']
        size = path.stat().st_size
        require(entry['type'] == 'output' and entry['csv_bytes'] == entry['stored_bytes'] == size,
                f'Quickstart manifest size mismatch: {path.name}')
        with path.open(encoding='utf-8', newline='') as file:
            header, *rows = csv.reader(file)
        require(header == source_rows[0] and len(rows) == parts[path.name],
                f'Quickstart header or row count mismatch: {path.name}')
        all_rows.extend(rows)
    require(all_rows == source_rows[1:], 'Quickstart CSV records or order mismatch')
    return parts


def smoke(archive_path, sha256, output):
    started = time.monotonic()
    data = read_regular(archive_path)
    require(identity(data)['sha256'] == sha256.lower(), 'Archive SHA-256 mismatch')
    kinds = {'win32': 'windows_x86_64', 'linux': 'linux_x86_64'}
    require(sys.platform in kinds and platform.machine().lower() in ('amd64', 'x86_64'),
            'Quickstart smoke requires x86-64 Windows or Linux')
    kind = kinds[sys.platform]
    suffix, executable, _ = PLATFORMS[kind]
    filename = re.fullmatch(rf'chopper-([0-9]+\.[0-9]+\.[0-9]+)-{suffix}\.zip', archive_path.name)
    require(filename, f'Expected a native {suffix} release archive')
    version = filename[1]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)) and set(names) == expected_members(kind),
                'Quickstart archive inventory mismatch')
        output.mkdir()
        archive.extractall(output)
    binary = output / executable
    if sys.platform == 'linux':
        binary.chmod(0o755)
    actual_version = subprocess.check_output([binary, '--version'], cwd=output, text=True, timeout=60)
    require(actual_version.strip() == f'chopper {version}', 'Packaged executable version mismatch')
    with (output / 'quickstart/customers.csv').open(encoding='utf-8', newline='') as file:
        source_rows = list(csv.reader(file))
    config = output / 'quickstart/job.json'
    job = json.loads(config.read_text(encoding='utf-8'))
    with (output / 'quickstart/run-report.json').open('wb') as report:
        subprocess.run([binary, 'run', '--config', 'quickstart/job.json', '--yes'],
                       cwd=output, stdout=report, check=True, timeout=60)
    parts = verify_quickstart(output / 'quickstart-output', version, source_rows)
    job['output'] = 'quickstart-output-rerun'
    (output / 'quickstart/rerun-job.json').write_text(json.dumps(job) + '\n', encoding='utf-8')
    with (output / 'quickstart/rerun-report.json').open('wb') as report:
        subprocess.run([binary, 'run', '--config', 'quickstart/rerun-job.json', '--yes'],
                       cwd=output, stdout=report, check=True, timeout=60)
    verify_quickstart(output / 'quickstart-output-rerun', version, source_rows)
    return {'archive': str(archive_path), 'sha256': sha256.lower(), 'version': version,
            'extracted': str(output), 'parts': parts, 'manifest': 'manifest.jsonl',
            'elapsed_seconds': round(time.monotonic() - started, 3)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    assembly = commands.add_parser('assemble')
    assembly.add_argument('--source', type=Path, required=True)
    assembly.add_argument('--manifest', type=Path, required=True)
    assembly.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('--directory', type=Path, required=True)
    check.add_argument('--receipt-sha256', required=True, help='Trusted receipt hash retained outside package')
    quickstart = commands.add_parser('smoke', help='Run the bundled Job from a verified native archive')
    quickstart.add_argument('--archive', type=Path, required=True)
    quickstart.add_argument('--sha256', required=True, help='Trusted archive hash from SHA256SUMS')
    quickstart.add_argument('--output', type=Path, required=True, help='New extraction directory')
    args = parser.parse_args()
    try:
        if args.command == 'assemble':
            result = assemble(args.source.resolve(), args.manifest.resolve(), args.output.resolve())
        elif args.command == 'verify':
            result = verify(args.directory.resolve(), args.receipt_sha256)
        else:
            result = smoke(args.archive.resolve(), args.sha256, args.output.resolve())
        print(json.dumps(result, indent=2))
    except (ValueError, KeyError, TypeError, OSError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(1, f'Packaging failed: {error}\n')


if __name__ == '__main__':
    main()
