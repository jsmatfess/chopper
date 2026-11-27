#!/usr/bin/env python3
"""Build and qualify the native libraries and CLI from one local candidate tag."""

import argparse
from email.parser import BytesParser
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = 'scripts/qualify-library-release.py'
RUNNER = 'scripts/validation-runner.py'
INSTALLED_TEST = 'crates/chopper-python/tests/installed_wheel.py'
PACKAGE_TEST = 'scripts/test-cargo-packages.py'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def capture(*command):
    return subprocess.check_output(command, cwd=ROOT, encoding='utf-8', timeout=30).strip()


def toml(path):
    with (ROOT / path).open('rb') as stream:
        return tomllib.load(stream)


def tagged_source(tag):
    ref = f'refs/tags/{tag}'
    commit = capture('git', 'rev-parse', '--verify', 'HEAD')
    require(capture('git', 'rev-parse', '--verify', ref + '^{commit}') == commit,
            f'HEAD must match the local candidate tag {tag}')
    require(not capture('git', '--no-optional-locks', 'status', '--porcelain', '--untracked-files=all'),
            'Qualification requires a clean candidate checkout')
    return {'tag': tag, 'tag_object': capture('git', 'rev-parse', '--verify', ref),
            'commit': commit, 'tree': capture('git', 'rev-parse', 'HEAD^{tree}')}


def platform_info():
    require(sys.implementation.name == 'cpython' and sys.version_info >= (3, 11)
            and not sysconfig.get_config_var('Py_GIL_DISABLED'),
            'Use a GIL-enabled CPython 3.11 or newer interpreter')
    require(platform.machine().lower() in ('amd64', 'x86_64') and sys.maxsize > 2**32,
            'Use a native 64-bit x86 host and Python interpreter')
    if sys.platform == 'win32':
        return 'x86_64-pc-windows-msvc', 'win_amd64', '.exe', None
    if sys.platform == 'linux':
        libc = os.confstr('CS_GNU_LIBC_VERSION')
        require(libc == 'glibc 2.28', 'Use the manylinux_2_28_x86_64 runtime with glibc 2.28')
        return 'x86_64-unknown-linux-gnu', 'manylinux_2_28_x86_64', '', libc
    raise ValueError('Use native Windows or Linux')


def tool(name):
    path = shutil.which(name)
    require(path, f'{name} is required on PATH')
    return str(Path(path).absolute())


def tracked(*paths):
    raw = subprocess.check_output(['git', 'ls-files', '-z', '--', *paths], cwd=ROOT)
    return sorted({os.fsdecode(path) for path in raw.split(b'\0') if path})


def verify_artifacts(plan_path):
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    version = plan['version']
    candidate = plan['candidate']
    require(tagged_source(candidate['tag']) == candidate, 'Candidate source or tag changed')
    require(capture(plan['cli'], '--version') == f'chopper {version}', 'CLI version differs from candidate')
    wheel = Path(plan['wheel'])
    tag = plan['wheel_tag']
    require(list(wheel.parent.glob('*.whl')) == [wheel], 'Expected exactly the candidate wheel')
    prefix = f'chopper_csv-{version}.dist-info'
    with ZipFile(wheel) as archive:
        require(len(archive.namelist()) == len(set(archive.namelist())), 'Duplicate wheel members')
        metadata = BytesParser().parsebytes(archive.read(f'{prefix}/METADATA'))
        wheel_info = BytesParser().parsebytes(archive.read(f'{prefix}/WHEEL'))
        require(metadata['Name'] == 'chopper-csv' and metadata['Version'] == version
                and metadata['Requires-Python'] == '>=3.11'
                and metadata['License-Expression'] == 'MIT', 'Unexpected wheel project metadata')
        require(wheel_info.get_all('Tag') == [tag] and wheel_info['Root-Is-Purelib'] == 'false',
                'Unexpected wheel ABI or platform tag')
        require(set(metadata.get_all('License-File', [])) == set(plan['wheel_notices']),
                'Wheel notice inventory differs from source')
        for notice in plan['wheel_notices']:
            require(archive.read(f'{prefix}/licenses/{notice}') == (ROOT / notice).read_bytes(),
                    f'Wheel notice differs from source: {notice}')
    print(f'Verified chopper {version} and {wheel.name}')


def build_plan(tag, output):
    candidate = tagged_source(tag)
    target, platform_tag, suffix, libc = platform_info()
    workspace = toml('Cargo.toml')['workspace']
    version = workspace['package']['version']
    require(re.fullmatch(r'\d+\.\d+\.\d+', version) and
            toml('crates/chopper-python/Cargo.toml')['package']['version'] == version,
            'Cargo and Python candidate versions differ')
    package_versions = {'chopper-core': version, 'chopper-csv': version}
    vendor = [path for path in workspace['exclude'] if path.startswith('vendor/')]
    for path in vendor:
        package = toml(f'{path}/Cargo.toml')['package']
        package_versions[package['name']] = package['version']
    packages = output / 'cargo-packages'
    archives = [packages / 'package-target/package' / f'{name}-{release}.crate'
                for name, release in package_versions.items()]

    project = toml('pyproject.toml')
    notices = project['project']['license-files']
    required_notices = {'LICENSE', 'docs/releases/native-usage.txt',
                        *tracked('crates/chopper-python/licenses')}
    for path in vendor:
        required_notices.update(p for p in tracked(path) if Path(p).parent.as_posix() == path
                                and Path(p).name.startswith('LICENSE'))
    require(required_notices <= set(notices) <= set(tracked(*notices)),
            'Python wheel license-files must include the tracked project and upstream notices')

    cargo, rustc, maturin = (tool(name) for name in ('cargo', 'rustc', 'maturin'))
    python = sys.executable
    rust_version = capture(rustc, '-vV')
    maturin_version = capture(maturin, '--version')
    require(f'host: {target}' in rust_version.splitlines(), 'Use a native Rust toolchain')
    require(maturin_version == 'maturin 1.16.0'
            and 'maturin==1.16.0' in project['build-system']['requires'],
            'Use the pinned Maturin 1.16.0 builder')

    cli_target = output / 'cli-target'
    cli = cli_target / target / 'release' / f'chopper{suffix}'
    wheel_tag = f'cp311-abi3-{platform_tag}'
    wheels = output / 'wheels'
    wheel = wheels / f'chopper_csv-{version}-{wheel_tag}.whl'
    installed = output / 'installed'
    installed_python = installed / ('Scripts/python.exe' if suffix else 'bin/python')
    plan_path = output / 'qualification.json'
    steps = []
    sources = tracked('Cargo.toml', 'Cargo.lock', '.cargo', 'crates', 'vendor', 'pyproject.toml',
                      'docs/user/libraries.md', *notices)

    def step(name, args, inputs, artifacts=(), timeout=300):
        steps.append({'id': name, 'argv': list(map(str, args)), 'timeout_seconds': timeout,
                      'inputs': list(map(str, inputs)), 'artifacts': list(map(str, artifacts)),
                      'depends': [steps[-1]['id']] if steps else []})

    step('cli-build', [cargo, 'build', '--release', '--locked', '-p', 'chopper-csv', '--bin',
                       'chopper', '--target', target, '--target-dir', cli_target],
         [*sources, rustc], [cli], timeout=1200)
    wheel_args = [maturin, 'build', '--locked', '--release', '--interpreter', python,
                  '--target', target, '--target-dir', output / 'wheel-target', '--out', wheels]
    if libc:
        wheel_args += ['--compatibility', 'manylinux_2_28', '--auditwheel', 'check']
    step('wheel-build', wheel_args, [*sources, python, cargo, rustc], [wheel], timeout=1200)
    step('verify-artifacts', [python, SCRIPT, '--verify-artifacts', plan_path],
         [SCRIPT, plan_path, cli, wheel, *notices])
    step('cargo-packages', [python, PACKAGE_TEST, packages, '--cli', cli],
         [*sources, *tracked(PACKAGE_TEST, 'scripts/fixtures/cargo-library'), cli, cargo, rustc],
         [*archives, packages / 'receipt.json', packages / 'consumer/Cargo.lock'], timeout=1800)
    step('wheel-venv', [python, '-I', '-m', 'venv', '--copies', installed],
         [SCRIPT], [installed_python, installed / 'pyvenv.cfg'])
    step('wheel-install', [installed_python, '-I', '-m', 'pip', 'install', '--no-index',
                           '--no-deps', '--disable-pip-version-check', wheel],
         [wheel, installed / 'pyvenv.cfg'])
    step('installed-wheel', [installed_python, '-I', INSTALLED_TEST, cli],
         [INSTALLED_TEST, 'examples/customers.csv', wheel, cli, installed / 'pyvenv.cfg'])
    for name, script, paths, args in (
        ('cli-reference', 'scripts/cli-reference.py', ('docs/cli-reference.md',
                                                     'docs/cli-reference-data.json'), ('--check',)),
        ('cli-recipes', 'scripts/test-job-recipes.py', ('docs/job-recipes.md', 'examples/customers.csv',
                                                      'examples/quickstart-job.json'), ()),
        ('cli-manifest', 'scripts/test-native-manifest.py', ('examples/verify_manifest.py',), ()),
        ('cli-upgrade', 'scripts/test-release-upgrade.py', ('examples/verify_manifest.py',
                                                          'scripts/fixtures/release-upgrade'), ()),
    ):
        step(name, [python, script, cli, *args], [*tracked(script, *paths), cli])
    step('candidate-recheck', [python, SCRIPT, '--verify-artifacts', plan_path],
         [SCRIPT, plan_path, cli, wheel, *notices, *archives, packages / 'receipt.json'])

    return {'root': str(ROOT), 'candidate': candidate, 'version': version, 'native_target': target,
            'cli': str(cli), 'wheel': str(wheel), 'wheel_tag': wheel_tag, 'wheel_notices': notices,
            'batch_timeout_seconds': 5400, 'estimated_seconds': 1800,
            'estimated_disk_bytes': 12 * 1024**3,
            'toolchains': {'platform': platform.platform(), 'glibc': libc, 'python': sys.version,
                           'cargo': capture(cargo, '--version'), 'rustc': rust_version,
                           'maturin': maturin_version, 'git': capture('git', '--version')},
            'features': ['default native engine', 'Python cp311-abi3'],
            'fixtures': ['packaged Cargo consumer', INSTALLED_TEST, 'native CLI compatibility'],
            'steps': steps}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tag', help='local candidate tag at the clean checked out commit')
    parser.add_argument('output', type=Path, help='fresh evidence directory')
    if len(sys.argv) == 3 and sys.argv[1] == '--verify-artifacts':
        verify_artifacts(Path(sys.argv[2]))
        return 0
    args = parser.parse_args()
    output = args.output.resolve()
    require(not args.output.is_symlink() and not output.exists(), 'Choose a fresh output directory')
    if output.is_relative_to(ROOT):
        ignored = subprocess.run(['git', 'check-ignore', '-q', '--', output], cwd=ROOT, check=False)
        require(ignored.returncode == 0, 'Choose an output directory outside the checkout or in scratch')
    plan = build_plan(args.tag, output)
    output.mkdir(parents=True)
    plan_path = output / 'qualification.json'
    plan_path.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    return subprocess.run([sys.executable, RUNNER, plan_path, output], cwd=ROOT, check=False).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, BadZipFile, subprocess.SubprocessError) as error:
        print(f'library qualification: {error}', file=sys.stderr)
        raise SystemExit(1)
