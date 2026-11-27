#!/usr/bin/env python3
"""Package the Chopper Cargo crates and run a fresh registry-style consumer."""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import sys
import tarfile
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CRATES_IO_INDEX = 'https://github.com/rust-lang/crates.io-index'
PACKAGES = {
    'chopper-flate2': 'vendor/flate2-1.1.10',
    'chopper-serde-json': 'vendor/serde_json-1.0.151',
    'chopper-zip': 'vendor/zip-2.4.2',
    'chopper-core': 'crates/chopper-core',
    'chopper-csv': 'crates/chopper',
}
LICENSES = {
    'chopper-flate2': ('LICENSE-MIT', 'LICENSE-APACHE'),
    'chopper-serde-json': ('LICENSE-MIT', 'LICENSE-APACHE'),
    'chopper-zip': ('LICENSE',),
    'chopper-core': ('LICENSE',),
    'chopper-csv': ('LICENSE',),
}
ROWS = [
    ('1', 'CA', 'first "quote"\r\ncanada'),
    ('2', 'US', 'second "quote"\r\namerica'),
    ('3', 'CA', 'third "quote"\r\ncanada'),
    ('4', 'US', 'fourth "quote"\r\namerica'),
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def version(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def source_identity():
    return {
        'commit': version('git', '-C', ROOT, 'rev-parse', 'HEAD'),
        'tree': version('git', '-C', ROOT, 'rev-parse', 'HEAD^{tree}'),
        'dirty': bool(version('git', '-C', ROOT, 'status', '--porcelain')),
    }


def run(command, cwd, log, commands):
    command = list(map(str, command))
    commands.append({'argv': command, 'cwd': str(cwd), 'stdout': str(log),
                     'stderr': str(log.with_suffix('.stderr'))})
    print(f'{log.stem} [{cwd}]', flush=True)
    with log.open('wb') as stdout, log.with_suffix('.stderr').open('wb') as stderr:
        result = subprocess.run(command, cwd=cwd, stdout=stdout, stderr=stderr, timeout=1200)
    commands[-1]['exit_code'] = result.returncode
    if result.returncode:
        raise ValueError(f'{log.stem} exited {result.returncode}; see {log.with_suffix(".stderr")}')


def stage_workspace(path):
    cargo = (ROOT / 'Cargo.toml').read_text(encoding='utf-8')
    source = tomllib.loads(cargo)['workspace']
    members = list(dict.fromkeys([*source['members'], *PACKAGES.values()]))
    path.mkdir()
    workspace = ('[workspace]\n'
                 f'members = {json.dumps(members)}\n'
                 f'resolver = {json.dumps(source["resolver"])}\n\n'
                 '[workspace.package]' + cargo.split('[workspace.package]', 1)[1])
    (path / 'Cargo.toml').write_text(workspace, encoding='utf-8')
    for directory in members:
        shutil.copytree(ROOT / directory, path / directory, ignore=shutil.ignore_patterns('target'))
    for name in ('Cargo.lock', 'LICENSE', 'docs/user/libraries.md'):
        dest = path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    # A nested staging directory may be inside the source checkout's ignored scratch/.
    # Give Cargo its own tree for file selection.
    subprocess.run(['git', 'init', '-q', path], check=True, timeout=30)


def index_dependencies(manifest, target=None):
    result = []
    for key, kind in (('dependencies', 'normal'), ('build-dependencies', 'build'),
                      ('dev-dependencies', 'dev')):
        for name, info in manifest.get(key, {}).items():
            if isinstance(info, str):
                info = {'version': info}
            package = info.get('package', name)
            require('path' not in info and 'git' not in info and 'registry' not in info,
                    f'Expected normalized registry dependency: {name}')
            # The test index owns only the Chopper packages. All other
            # dependencies still resolve and download normally from crates.io.
            result.append({'name': name, 'package': info.get('package'), 'req': info['version'],
                           'features': info.get('features', []), 'optional': info.get('optional', False),
                           'default_features': info.get('default-features', True), 'kind': kind,
                           'target': target, 'registry': None if package in PACKAGES else CRATES_IO_INDEX})
    return result


def make_index(index, artifacts):
    (index / 'ch/op').mkdir(parents=True)
    write_json(index / 'config.json', {'dl': artifacts.as_uri() + '/{crate}-{version}.crate'})
    packages = {}
    for crate in sorted(artifacts.glob('*.crate')):
        prefix = crate.stem
        with tarfile.open(crate, 'r:gz') as archive:
            manifest = tomllib.loads(archive.extractfile(f'{prefix}/Cargo.toml').read().decode())
            package = manifest['package']
            name = package['name']
            require(name in PACKAGES and name not in packages, f'Unexpected package: {name}')
            license_dir = ROOT / PACKAGES[name] if PACKAGES[name].startswith('vendor/') else ROOT
            for license in LICENSES[name]:
                require(archive.extractfile(f'{prefix}/{license}').read() == (license_dir / license).read_bytes(),
                        f'License mismatch: {name}/{license}')
        archive_identity = identity(crate)
        packages[name] = {'version': package['version'], 'path': str(crate), **archive_identity}
        dependencies = index_dependencies(manifest)
        for cfg, target in manifest.get('target', {}).items():
            dependencies.extend(index_dependencies(target, cfg))
        index_row = {'name': name, 'vers': package['version'], 'deps': dependencies,
                     'cksum': archive_identity['sha256'], 'features': {},
                     'features2': manifest.get('features', {}), 'v': 2, 'yanked': False}
        (index / 'ch/op' / name).write_text(json.dumps(index_row) + '\n', encoding='utf-8')
    require(packages.keys() == PACKAGES.keys(), 'Missing packaged crate')
    for args in (['init', '-q'], ['add', '.'],
                 ['-c', 'user.name=Chopper fixture', '-c', 'user.email=fixture@example.invalid',
                  '-c', 'commit.gpgsign=false', 'commit', '-qm', 'Local Cargo package index']):
        subprocess.run(['git', *args], cwd=index, check=True, timeout=30)
    return packages


def external_project(path, index, packages):
    (path / '.cargo').mkdir(parents=True)
    (path / 'src').mkdir()
    (path / '.cargo/config.toml').write_text(f'[registries.stage]\nindex = "{index.as_uri()}"\n',
                                          encoding='utf-8')
    (path / 'Cargo.toml').write_text('''[package]
name = "chopper-cargo-smoke"
version = "0.0.0"
edition = "2021"

[workspace]

[features]
admission = ["chopper/resource-contract-tests"]

[dependencies]
''' + f'chopper = {{ package = "chopper-csv", version = "={packages["chopper-csv"]["version"]}" }}\n'
        '''flate2 = { version = "=1.1.10", default-features = false, features = ["zlib-rs"] }
hashbrown = "=0.17.1"
indexmap = { version = "=2.14.2", features = ["serde"] }
serde_json = { version = "=1.0.151", features = ["arbitrary_precision", "float_roundtrip", "preserve_order"] }

[patch.crates-io]
''' + ''.join(f'{name} = {{ version = "={package["version"]}", registry = "stage" }}\n'
              for name, package in packages.items()), encoding='utf-8')
    shutil.copyfile(ROOT / 'scripts/fixtures/cargo-library/main.rs', path / 'src/main.rs')

    source = io.StringIO(newline='')
    writer = csv.writer(source)
    writer.writerow(('id', 'country', 'note'))
    writer.writerows(ROWS)
    with zipfile.ZipFile(path / 'input.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('nested/records.csv', b'\xff\xfe' + source.getvalue().encode('utf-16le'))
        archive.writestr('ignored.txt', b'not the selected member')
    with zipfile.ZipFile(path / 'too-many-members.zip', 'x') as archive:
        archive.writestr('nested/records.csv', b'id,country\n1,CA\n')
        for index in range(8192):
            archive.writestr(f'other/{index:04d}.txt', b'')


def check_result(manifest, version):
    job, *entries = [json.loads(line) for line in manifest.read_text(encoding='utf-8').splitlines()]
    require(job['type'] == 'job' and len(entries) == 4, 'Unexpected manifest records')
    require(job['application_version'] == version, 'Manifest application version mismatch')
    rows = []
    total_bytes = 0
    for entry in entries:
        chunk = manifest.parent / entry['path']
        size = chunk.stat().st_size
        require(entry['type'] == 'output' and entry['rows'] == 1
                and size == entry['csv_bytes'] == entry['stored_bytes'] <= 53,
                f'Serialized cap or manifest mismatch: {chunk}')
        with chunk.open(encoding='utf-8', newline='') as stream:
            header, row = csv.reader(stream)
        require(header == ['id', 'country', 'note'] and entry['lineage'][0]['values'] == [row[1]],
                f'Group or header mismatch: {chunk}')
        rows.append(tuple(row))
        total_bytes += size
    require(sorted(rows) == ROWS, 'Changed or missing CSV records')
    require(job['analysis']['rows'] == 4 and job['analysis']['output_files'] == 4
            and job['analysis']['output_csv_bytes'] == total_bytes, 'Manifest aggregate mismatch')
    return total_bytes


def qualify(out, cli):
    source = source_identity()
    out.mkdir(parents=True)
    commands = []
    try:
        stage = out / 'stage'
        stage_workspace(stage)
        target = out / 'package-target'
        run(['cargo', 'package', '--locked', '--allow-dirty', '--no-verify', '--target-dir', target,
             *[flag for name in PACKAGES for flag in ('-p', name)]], stage,
            out / 'package.log', commands)
        index = out / 'index'
        packages = make_index(index, target / 'package')
        release_version = packages['chopper-csv']['version']
        require(packages['chopper-core']['version'] == release_version, 'Chopper crate version mismatch')
        consumer = out / 'consumer'
        external_project(consumer, index, packages)
        target = out / 'consumer-target'
        run(['cargo', 'run', '--quiet', '--target-dir', target], consumer, out / 'run.log', commands)
        lock = tomllib.loads((consumer / 'Cargo.lock').read_text(encoding='utf-8'))['package']
        for name, package in packages.items():
            resolved = next(candidate for candidate in lock if candidate['name'] == name)
            require(resolved['source'] == f'registry+{index.as_uri()}'
                    and resolved['checksum'] == package['sha256'], f'Unpackaged dependency: {name}')
        report = json.loads((out / 'run.log').read_text(encoding='utf-8'))
        require(check_result(consumer / report['manifest_path'], release_version) == report['output_csv_bytes'],
                'Run report byte count differs from manifest')
        require(not (consumer / 'denied').exists(), 'Denied run published output')

        host = target / 'debug' / ('chopper-cargo-smoke.exe' if sys.platform == 'win32' else 'chopper-cargo-smoke')
        stack_reserve = None
        if sys.platform == 'win32':
            data = host.read_bytes()
            pe_header = struct.unpack_from('<I', data, 0x3C)[0]
            require(data[pe_header:pe_header + 6] == b'PE\x00\x00\x64\x86', 'Expected x86-64 PE host')
            stack_reserve = struct.unpack_from('<Q', data, pe_header + 24 + 72)[0]
            require(stack_reserve == 1024 * 1024, 'Unexpected linker stack override in Windows host')
        host = Path(shutil.copy2(host, out / host.name))
        if cli:
            run([cli, '--version'], consumer, out / 'cli-version.log', commands)
            require((out / 'cli-version.log').read_text().strip() == f'chopper {release_version}',
                    'Candidate CLI version mismatch')
            run([cli, 'run', '--config', 'recipes/cli.json', '--yes', '--summary'], consumer,
                out / 'cli.log', commands)
            check_result(consumer / 'cli/manifest.jsonl', release_version)

        run(['cargo', 'run', '--quiet', '--locked', '--target-dir', target, '--features', 'admission',
             '--', 'admission'], consumer, out / 'admission.log', commands)
        admission = out / 'admission.log'
        control = json.loads(admission.read_text(encoding='utf-8'))
        require({'zip_metadata', 'zip_codec', 'gzip_codec', 'output_deflate_codec'} <= control.keys(),
                'Missing downstream codec admission controls')
        require(source == source_identity(), 'Source changed during packaging')
        receipt = {'source': source, 'platform': platform.platform(), 'rustc': version('rustc', '-vV'),
                   'cargo': version('cargo', '--version'), 'python': sys.version,
                   'packages': packages, 'consumer_lock': identity(consumer / 'Cargo.lock'),
                   'consumer': {'native_host': identity(host), 'pe_stack_reserve': stack_reserve,
                                'run': report, 'admission_report': identity(admission)},
                   'cli': identity(cli) if cli else None}
        write_json(out / 'receipt.json', receipt)
    finally:
        write_json(out / 'commands.json', commands)
    print(out / 'receipt.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='new directory for packages, fixture and logs')
    parser.add_argument('--cli', type=Path, help='candidate CLI executable for saved Job replay')
    args = parser.parse_args()
    try:
        qualify(args.output.resolve(), args.cli.resolve(strict=True) if args.cli else None)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
