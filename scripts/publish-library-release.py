#!/usr/bin/env python3
"""Preview or publish the native artifacts from one qualified Chopper candidate."""

import argparse
from dataclasses import dataclass
import hashlib
from http.client import HTTPException
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import tomllib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


spec = importlib.util.spec_from_file_location('qualification', Path(__file__).with_name('qualify-library-release.py'))
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)
require = qualification.require
UPSTREAM = 'https://github.com/jsmatfess/chopper.git'
CRATES_UPLOAD = 'https://crates.io/api/v1/crates/new'
PYPI_UPLOAD = 'https://upload.pypi.org/legacy/'
PROJECT = 'chopper-csv'
TWINE_CREDENTIALS = ('TWINE_USERNAME', 'TWINE_PASSWORD')
RELEASE_CREDENTIALS = ('CARGO_REGISTRY_TOKEN', *TWINE_CREDENTIALS)
TRANSPORT_ERRORS = (ConnectionError, TimeoutError, URLError, HTTPException)
# Keep the packages ahead of all dependents in the registry index.
CRATES = {
    'chopper-flate2': 'vendor/flate2-1.1.10/Cargo.toml',
    'chopper-serde-json': 'vendor/serde_json-1.0.151/Cargo.toml',
    'chopper-zip': 'vendor/zip-2.4.2/Cargo.toml',
    'chopper-core': 'crates/chopper-core/Cargo.toml',
    PROJECT: 'crates/chopper/Cargo.toml',
}
PLATFORMS = {
    'linux': (PurePosixPath, 'x86_64-unknown-linux-gnu', 'cp311-abi3-manylinux_2_28_x86_64', 'glibc 2.28'),
    'windows': (PureWindowsPath, 'x86_64-pc-windows-msvc', 'cp311-abi3-win_amd64', None),
}
REQUIRED_STEPS = {
    'cli-build', 'wheel-build', 'verify-artifacts', 'cargo-packages', 'wheel-venv', 'wheel-install',
    'installed-wheel', 'cli-reference', 'cli-recipes', 'cli-manifest', 'cli-upgrade', 'candidate-recheck',
}


@dataclass(frozen=True)
class Artifact:
    name: str
    version: str
    path: Path
    data: bytes
    sha256: str
    cargo_metadata: dict | None = None


def read_file(root, relative):
    path = root / relative
    require(path.is_file() and path.resolve() == path, f'Expected a regular evidence file: {path}')
    return path.read_bytes()


def checked_identity(data, record, path, size_field='size'):
    digest = hashlib.sha256(data).hexdigest()
    require((record[size_field], record['sha256']) == (len(data), digest),
            f'Qualified byte identity differs: {path}')
    return digest


def wheel_name(version, tag):
    return f'chopper_csv-{version}-{tag}.whl'


def crate_metadata(path, data, name, version):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        def read(member):
            return archive.extractfile(f'{path.stem}/{member}').read().decode('utf-8')

        manifest = tomllib.loads(read('Cargo.toml'))
        package = manifest['package']
        require((package['name'], package['version']) == (name, version), f'Wrong crate identity: {path}')
        readme = package.get('readme') or None
        # crates.io reads dependencies and other package metadata from the tarball manifest.
        return {'name': name, 'vers': version, 'readme_file': readme, 'readme': read(readme) if readme else None}


def qualified_artifacts(directory, platform, candidate, version, crate_versions):
    path_type, target, tag, glibc = PLATFORMS[platform]
    plan_bytes = read_file(directory, 'qualification.json')
    plan = json.loads(plan_bytes)
    require(plan == json.loads(read_file(directory, 'manifest.json'))
            and (plan['candidate'], plan['version'], plan['native_target'], plan['wheel_tag'],
                 plan['toolchains']['glibc']) == (candidate, version, target, tag, glibc),
            f'{platform} qualification plan does not match the candidate and platform')
    recorded_wheel = path_type(plan['wheel'])
    recorded_root = recorded_wheel.parent.parent
    wheel_relative = f'wheels/{wheel_name(version, tag)}'
    require(recorded_root.is_absolute() and recorded_wheel == recorded_root / wheel_relative,
            f'{platform} qualification has an unexpected wheel location')
    status = json.loads(read_file(directory, 'status.json'))
    steps = {step['id']: step for step in plan['steps']}
    latest = {attempt['id']: attempt for attempt in status['attempts']}
    require(REQUIRED_STEPS <= steps.keys() == latest.keys()
            and len(steps) == len(plan['steps'])
            and status['summary'] == {'passed': len(steps), 'incomplete': 0},
            f'{platform} qualification is incomplete')
    for name, step in steps.items():
        attempt = latest[name]
        require(attempt['status'] == 'passed' and attempt['exit_code'] == 0
                and attempt['argv'] == step['argv']
                and attempt['dependencies'] == {dep: latest[dep]['attempt'] for dep in step['depends']},
                f'{platform} qualification step is not a current pass: {name}')

    def check(data, relative, step, records):
        return checked_identity(data, latest[step][records][str(recorded_root / relative)],
                                directory / relative)

    check(plan_bytes, 'qualification.json', 'candidate-recheck', 'inputs')
    wheel = read_file(directory, wheel_relative)
    wheel_digest = check(wheel, wheel_relative, 'wheel-build', 'artifacts')
    check(wheel, wheel_relative, 'installed-wheel', 'inputs')
    receipt_relative = 'cargo-packages/receipt.json'
    receipt_bytes = read_file(directory, receipt_relative)
    check(receipt_bytes, receipt_relative, 'cargo-packages', 'artifacts')
    receipt = json.loads(receipt_bytes)
    require(receipt['source'] == {'commit': candidate['commit'], 'tree': candidate['tree'], 'dirty': False}
            and receipt['packages'].keys() == crate_versions.keys(), f'{platform} Cargo receipt mismatch')
    crates = []
    for name, release in crate_versions.items():
        relative = f'cargo-packages/package-target/package/{name}-{release}.crate'
        path = directory / relative
        record = receipt['packages'][name]
        require(record['version'] == release and path_type(record['path']) == recorded_root / relative,
                f'{platform} Cargo receipt has an unexpected version or location: {name}')
        data = read_file(directory, relative)
        digest = check(data, relative, 'cargo-packages', 'artifacts')
        checked_identity(data, record, path, 'bytes')
        crates.append(Artifact(name, release, path, data, digest, crate_metadata(path, data, name, release)))
    return crates, Artifact(PROJECT, version, directory / wheel_relative, wheel, wheel_digest)


def require_landed(candidate, version):
    final = f'refs/tags/v{version}'
    git = qualification.capture
    require(git('git', 'rev-parse', '--verify', f'{final}^{{commit}}') == candidate['commit'],
            f'The final v{version} tag must identify the qualified commit')
    require(git('git', 'ls-remote', '--get-url', UPSTREAM) == UPSTREAM,
            'Git is configured to rewrite the official Chopper remote URL')
    main = 'refs/heads/main'
    refs = {ref: oid for oid, ref in (line.split() for line in
            git('git', 'ls-remote', UPSTREAM, main, final, final + '^{}').splitlines())}
    require(refs.get(final + '^{}', refs.get(final)) == candidate['commit'],
            f'The final v{version} tag on GitHub must identify the qualified commit')
    tip = refs.get(main, '')
    require(re.fullmatch(r'[0-9a-f]{40}', tip), 'Could not read the current GitHub main commit')
    subprocess.run(['git', 'fetch', '--no-tags', UPSTREAM, tip], cwd=qualification.ROOT,
                   check=True, timeout=120)
    result = subprocess.run(['git', 'merge-base', '--is-ancestor', candidate['commit'], tip],
                            cwd=qualification.ROOT, timeout=30)
    require(result.returncode == 0, 'The qualified commit must be reachable from GitHub main')


def request(url, *, body=None, token=None):
    headers = {'User-Agent': 'Chopper release (https://github.com/jsmatfess/chopper)',
               'Cache-Control': 'no-cache'}
    if body is not None:
        headers.update({'Content-Type': 'application/octet-stream', 'Accept': 'application/json'})
    req = Request(url, data=body, headers=headers, method='PUT' if body is not None else 'GET')
    if body is not None:
        require(token and re.fullmatch(r'[!-~]+', token), 'Set a valid CARGO_REGISTRY_TOKEN')
        req.add_unredirected_header('Authorization', token)
    try:
        with urlopen(req, timeout=30) as response:
            return response.read()
    except HTTPError as error:
        if error.code == 404 and body is None:
            return None
        raise ValueError(f'{req.get_method()} {url} returned HTTP {error.code}') from None


def available(artifact):
    if artifact.cargo_metadata is not None:
        name = artifact.name
        data = request(f'https://index.crates.io/{name[:2]}/{name[2:4]}/{name}')
        if data is None:
            return False
        matches = [(row['cksum'], row['yanked']) for row in map(json.loads, data.splitlines())
                   if row['vers'] == artifact.version]
    else:
        data = request(f'https://pypi.org/pypi/{PROJECT}/{artifact.version}/json')
        if data is None:
            return False
        files = json.loads(data)['urls']
        expected = {wheel_name(artifact.version, tag) for _, _, tag, _ in PLATFORMS.values()}
        require(all(file['filename'] in expected for file in files), 'PyPI release has an unexpected artifact')
        matches = [(file['digests']['sha256'], file['yanked']) for file in files
                   if file['filename'] == artifact.path.name]
    if not matches:
        return False
    require(len(matches) == 1, f'Ambiguous registry record: {artifact.path.name}')
    digest, yanked = matches[0]
    require(digest == artifact.sha256 and not yanked,
            f'Registry version is yanked or differs from qualified bytes: {artifact.path.name}')
    return True


def twine(*args, timeout, credentials=None):
    environment = {key: value for key, value in os.environ.items() if key not in RELEASE_CREDENTIALS}
    if credentials is not None:
        environment.update({key: credentials[key] for key in TWINE_CREDENTIALS})
    subprocess.run([sys.executable, '-I', '-m', 'twine', *args], env=environment, stdout=sys.stderr,
                   check=True, timeout=timeout)


def upload(artifact, credentials, staged_wheel=None):
    if artifact.cargo_metadata is not None:
        metadata = json.dumps(artifact.cargo_metadata, separators=(',', ':')).encode()
        # Cargo's registry API framing carries the prequalified .crate unchanged.
        body = struct.pack('<I', len(metadata)) + metadata + struct.pack('<I', len(artifact.data)) + artifact.data
        result = json.loads(request(CRATES_UPLOAD, body=body, token=credentials['CARGO_REGISTRY_TOKEN']))
        require(not result.get('errors'), f'crates.io rejected {artifact.path.name}')
    else:
        require(staged_wheel.read_bytes() == artifact.data, f'Staged wheel changed: {artifact.path.name}')
        twine('upload', '--non-interactive', '--disable-progress-bar', '--repository-url', PYPI_UPLOAD,
              staged_wheel, credentials=credentials, timeout=180)


def publish_artifacts(artifacts, publish, credentials):
    pending = [artifact for artifact in artifacts if not available(artifact)]
    report = {artifact.path.name: {'sha256': artifact.sha256,
                                   'status': 'pending' if artifact in pending else 'already published'}
              for artifact in artifacts}
    if not publish or not pending:
        return report

    if any(artifact.cargo_metadata is not None for artifact in pending):
        require(credentials.get('CARGO_REGISTRY_TOKEN'), 'Set CARGO_REGISTRY_TOKEN for crates.io publication')
    wheels = [artifact for artifact in pending if artifact.cargo_metadata is None]
    if wheels:
        require(credentials.get('TWINE_USERNAME') == '__token__'
                and re.fullmatch(r'[!-~]+', credentials.get('TWINE_PASSWORD') or ''),
                'Set TWINE_USERNAME=__token__ and a valid TWINE_PASSWORD for PyPI publication')

    with tempfile.TemporaryDirectory(prefix='chopper-release-') as directory:
        staged = {}
        for wheel in wheels:
            path = Path(directory) / wheel.path.name
            path.write_bytes(wheel.data)
            staged[wheel.path.name] = path
        if staged:
            twine('check', '--strict', *staged.values(), timeout=60)
        for artifact in artifacts:
            if available(artifact):
                report[artifact.path.name]['status'] = 'already published'
                continue
            require(artifact in pending, f'Registry state changed for {artifact.path.name}. Repeat the preview.')
            print(f'Publishing {artifact.path.name}', file=sys.stderr, flush=True)
            try:
                upload(artifact, credentials, staged.get(artifact.path.name))
            except (*TRANSPORT_ERRORS, subprocess.TimeoutExpired):
                print(f'Upload response unavailable for {artifact.path.name}. Checking the registry.', file=sys.stderr)
            # The registry may finish indexing after accepting the upload.
            deadline = time.monotonic() + 90
            while True:
                try:
                    if available(artifact):
                        break
                except TRANSPORT_ERRORS:
                    pass
                require(time.monotonic() < deadline,
                        f'Registry has not indexed {artifact.path.name}. Retry the same release after indexing.')
                time.sleep(3)
            report[artifact.path.name]['status'] = 'published'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('tag', help='the local candidate tag used on both qualification hosts')
    parser.add_argument('--linux', type=Path, required=True, help='Linux qualification directory')
    parser.add_argument('--windows', type=Path, required=True, help='Windows qualification directory')
    parser.add_argument('--publish', action='store_true', help='upload to crates.io and PyPI')
    args = parser.parse_args()
    credentials = {}
    for key in RELEASE_CREDENTIALS:
        if args.publish:
            credentials[key] = os.environ.pop(key, None)
        else:
            os.environ.pop(key, None)
    candidate = qualification.tagged_source(args.tag)
    version = qualification.toml('Cargo.toml')['workspace']['package']['version']
    require(re.fullmatch(r'\d+\.\d+\.\d+', version), 'Expected a stable distribution version')
    crate_versions = {name: qualification.toml(path)['package'].get('version', version)
                      for name, path in CRATES.items()}
    crate_versions = {name: release if isinstance(release, str) else version
                      for name, release in crate_versions.items()}
    linux, linux_wheel = qualified_artifacts(args.linux.resolve(), 'linux', candidate, version, crate_versions)
    windows, windows_wheel = qualified_artifacts(args.windows.resolve(), 'windows', candidate, version, crate_versions)
    require([a.sha256 for a in linux] == [a.sha256 for a in windows],
            'Windows and Linux qualification used different Cargo archive bytes')
    if args.publish:
        require_landed(candidate, version)
    result = publish_artifacts([*linux, linux_wheel, windows_wheel], args.publish, credentials)
    print(json.dumps({'mode': 'publish' if args.publish else 'preview', 'candidate': candidate,
                      'version': version, 'artifacts': result}, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError) as error:
        print(f'library publication: {error}', file=sys.stderr)
        raise SystemExit(1)
