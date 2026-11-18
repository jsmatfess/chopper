"""Separate full-scale identity. Hashes identify evidence; they never grant approval."""
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from .browser_identity import stamp
from .guard import frozen_metadata, load_runner
from .verify import read_json, require, sha256

SOURCE = '639d1fe97d985b1544df0932321c6a93cca2567b'
TREE = 'b3bde79d552ee29760cb283d07938f9248cee0bb'
ASSETS = ('engine.wasm', 'engine-worker.js', 'storage-worker.js', 'app.js', 'index.html', 'style.css', '_headers')
PRODUCT_INPUTS = {'Cargo.toml', 'Cargo.lock', 'crates', 'vendor', 'ui/src', 'ui/package.json', 'ui/package-lock.json', 'ui/public', 'ui/index.html', 'ui/style.css', 'scripts'}
HARNESS_INPUTS = {'scripts', 'scripts/scale-acceptance.py', 'scripts/validation-runner.py',
                  'scripts/local-ci.py', 'scripts/browser-small-windows.py',
                  'scripts/browser-artifacts.mjs', 'scripts/scale_acceptance',
                  'ui/node_modules/playwright', 'ui/node_modules/playwright-core',
                  'ui/node_modules/esbuild', 'ui/node_modules/@esbuild'}


def scale_fixture(shape):
    # Cold hash-only observations of the exact generate.header/row stream. Actual
    # generation, Node admission and the independent verifier still read/check it.
    require(shape in ('D', 'G'), 'selected scale shape required')
    width, rows, digest = ((100, 9_999_999, 'b9f39def15561eebc6eeb72f6cb4ff1c1c0e35f0d76cd06d7e8775aec82f0b5a')
        if shape == 'D' else (1000, 999_999, 'ab6750fb7f09ee0a1f07d29eb3f030f95433ef2218f316c4282aeae44712bd99'))
    return dict(width=width, rows=rows, bytes=1_000_000_000, sha256=digest)


def tiny_fixture(shape, rows=127):
    from .generate import fixture_identity
    require(shape in ('D', 'G') and type(rows) is int and 1 <= rows <= 127, '1..127 qualification rows required')
    return fixture_identity(shape, 'browser', rows)


def real_path(value):
    path = Path(value)
    require(path.is_absolute() and '..' not in path.parts, 'absolute identity path required')
    require(all(not p.is_symlink() for p in [path, *path.parents]), 'identity symlink ancestry')
    return path


def digest(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'concrete SHA-256 required')
    return value


def concrete(value):
    if isinstance(value, dict):
        return bool(value) and all(concrete(v) for v in value.values())
    if isinstance(value, list):
        return bool(value) and all(concrete(v) for v in value)
    return isinstance(value, (str, int)) and not isinstance(value, bool) and bool(value) and not (
        isinstance(value, str) and (value.lower() in ('unknown', 'unrun', 'null', 'todo', 'placeholder') or '<' in value))


def validate_packet(p, *, preparation=False):
    require(p['version'] == 1 and p['runtime'] == 'browser' and p['mode'] in ('scale', 'qualify')
            and p['features'] == [] and type(p['parent_scheduled']) is bool
            and (preparation is True or p['parent_scheduled'] is True), 'explicit default scale freeze required')
    require(p['source']['commit'] == SOURCE and p['source']['tree'] == TREE and p['source']['clean'] is True,
            'selected product source/tree required')
    require(p['harness_source']['clean'] is True and
            all(re.fullmatch('[0-9a-f]{40}', p['harness_source'][key]) for key in ('commit', 'tree')), 'clean separate harness source/tree required')
    require(p['channel'] in ('chrome', 'msedge'), 'full scale requires installed Chrome/Edge')
    require(p['host']['os'] == 'Windows' and concrete(p['host']), 'concrete Windows identity required')
    for key in ('package', 'build_receipts', 'toolchains', 'storage', 'browser_version', 'profile', 'plan_id'):
        require(concrete(p[key]), 'concrete identity required: ' + key)
    require(re.fullmatch('[a-zA-Z0-9_-]{1,80}', p['plan_id']), 'simple unique plan_id required')
    require(re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{3,4}', p['origin'])
            and int(p['origin'].rsplit(':', 1)[1]) <= 65535, 'explicit loopback origin required')
    require(p['shape'] in ('D', 'G'), 'one selected shape required')
    for key in ('product', 'harness', 'assets', 'evidence'):
        group = p[key]
        real_path(group['root'])
        require(group['inputs'] and group['sha256'], 'complete identity map required: ' + key)
        for value in group['sha256'].values():
            digest(value)
    require(PRODUCT_INPUTS <= set(p['product']['inputs']), 'full product inputs required')
    require(HARNESS_INPUTS <= set(p['harness']['inputs']), 'full harness/dependency inputs required')
    require(p['assets']['inputs'] == ['*'], 'inventory the entire production asset directory')
    require(set(p['assets']['sha256']) == set(ASSETS), 'exactly seven production assets required')
    require(p['build_receipts'] and all(name in p['evidence']['sha256'] for name in p['build_receipts']),
            'build receipts must be frozen evidence')
    require(p['package']['path'] in p['evidence']['sha256'] and
            p['package']['sha256'] == p['evidence']['sha256'][p['package']['path']], 'package hash binding required')
    require(p['bundle'] in p['harness']['sha256'] and p['bundle_provenance'] in p['harness']['sha256'],
            'bridge/provenance must be frozen harness inputs')
    for key in ('browser', 'node', 'python', 'reservation'):
        real_path(p[key]['path'])
        digest(p[key]['sha256'])
    require('external_runtime' in p and 'git' in p,'complete live Git and external runtime required')
    runtime=p['external_runtime'];rows=runtime['inputs']
    require(rows and len({row['path'] for row in rows})==len(rows),'complete unique external runtime')
    pins={row['path']:digest(row['sha256']) for row in rows}
    require(all(pins.get(p[key]['path'])==p[key]['sha256'] for key in ('browser','node','python','git')),
            'selected live tool missing from external runtime')
    exec_path=Path(runtime['git_exec_path'])
    require({exec_path,exec_path.parent.parent/'bin'} <= {Path(d) for d in runtime['input_directories']},
            'complete live Git executable and DLL directories required')
    require(all(members and len(members)==len(set(members)) and all(name in pins for name in members)
        for members in runtime['input_directories'].values()),'external runtime membership lacks pins')
    fixture = p['fixture']
    width = 100 if p['shape'] == 'D' else 1000
    if p['mode'] == 'qualify':
        require(type(fixture['rows']) is int and 1 <= fixture['rows'] <= 127,
                'qualification requires 1..127 tiny rows')
        require(fixture['width'] == width and fixture['bytes'] == (fixture['rows'] + 1) * width
                and fixture['bytes'] <= 128000, 'exact tiny qualification counts required')
        require(not p.get('peer'), 'tiny qualification cannot establish scale peer coverage')
        require(fixture == tiny_fixture(p['shape'], fixture['rows']), 'deterministic tiny fixture hash mismatch')
    else:
        require(fixture == scale_fixture(p['shape']), 'exact scale counts and deterministic hash required')
    digest(fixture['sha256'])
    if 'borrowed_input' in p:
        require(p['mode'] == 'qualify' and p['shape'] == 'D' and fixture == tiny_fixture('D'),
                'borrowed input cannot admit Large or another recipe')
        from .hosted_qualification import check_borrowed_input
        check_borrowed_input(p['borrowed_input'])
        require(p['borrowed_input']['sha256'] == fixture['sha256'] and
                p['borrowed_input']['bytes'] == fixture['bytes'], 'borrowed fixture identity mismatch')
    if p.get('peer'):
        real_path(p['peer']['path'])
        digest(p['peer']['sha256'])


class ScaleIdentity:
    def __init__(self, binding, *, preparation=False):
        self.packet_path = real_path(binding['packet'])
        self.external = {}
        self.borrowed = None
        self.pin(self.packet_path, binding['sha256'])
        self.packet = p = read_json(self.packet_path, 64 * 1024**2)
        validate_packet(p, preparation=preparation)
        self.groups = []
        runner = load_runner()
        for key in ('product', 'harness', 'assets', 'evidence'):
            group = p[key]
            root = real_path(group['root'])
            before = frozen_metadata(root, group['inputs'])
            identities = runner.identity(root, group['inputs'])
            require(not runner.incomplete_identity(identities), 'incomplete ' + key)
            actual = {Path(name).as_posix(): item['sha256'] for name, item in identities.items() if not item.get('directory')}
            require(actual == group['sha256'], key + ' hash/map mismatch; regenerate configuration and requalify the affected profile')
            require(frozen_metadata(root, group['inputs']) == before, key + ' changed during admission')
            self.groups.append((root, group['inputs'], before))
        if p.get('execution_kind') == 'batch':
            from .hosted_qualification import batch_inputs
            for row in batch_inputs(p['frozen_batch']):
                self.pin(real_path(row['path']),row['sha256'])
            if p['mode']=='scale':
                for row in batch_inputs(p['campaign_qualification']):
                    self.pin(real_path(row['path']),row['sha256'])
                self.pin(real_path(p['campaign_reservation']['path']),p['campaign_reservation']['sha256'])
        if 'time_continuation'in p:
            from .hosted_qualification import browser_scale_time_inputs
            for row in browser_scale_time_inputs(p['time_continuation'],history=p.get('time_continuation_history')):self.pin(real_path(row['path']),row['sha256'])
        if 'borrowed_input' in p:
            self.pin(real_path(p['borrowed_input']['path']), p['borrowed_input']['sha256'])
            self.borrowed = p['borrowed_input']
        for key in ('browser', 'node', 'python', 'reservation'):
            self.pin(real_path(p[key]['path']), p[key]['sha256'])
        if p.get('peer'):
            self.pin(real_path(p['peer']['path']), p['peer']['sha256'])
        provenance = read_json(Path(p['harness']['root']) / p['bundle_provenance'])
        require(provenance['hosted'] is True and provenance['esbuild_version'] == p['toolchains']['esbuild_version'], 'bridge compiler identity mismatch')
        require(provenance['bundle_sha256'] == p['harness']['sha256'][p['bundle']], 'bridge hash mismatch')
        expected = {'product': p['product']['sha256'], 'harness': p['harness']['sha256']}
        require(provenance['inputs'] and all(expected[part].get(name) == value
                for part, values in provenance['inputs'].items() for name, value in values.items()), 'bridge provenance mismatch')
        require({'ui/src/app.ts', 'ui/src/browser/client.ts'} <= set(provenance['inputs']['product'])
                and 'scripts/scale_acceptance/browser-page.mjs' in provenance['inputs']['harness'], 'production bridge seam required')
        for row in p['external_runtime']['inputs']:
            self.pin(real_path(row['path']), row['sha256'])
        self.runtime_directories = {}
        for directory, members in p['external_runtime']['input_directories'].items():
            root = real_path(directory); metadata = frozen_metadata(root.parent, [root.name])
            require(sorted(str(root.parent/name) for name in metadata if (root.parent/name).is_file()) == sorted(members),
                    'external runtime membership drift')
            self.runtime_directories[root] = metadata
        self.check()
        require(self.git('status', '--porcelain', '--untracked-files=no') == '', 'product must be clean')
        require(self.git('status', '--porcelain', '--untracked-files=no', group='harness') == '', 'harness must be clean')

    def pin(self, path, expected):
        before = stamp(path)
        require(path.is_file() and sha256(path) == digest(expected) and stamp(path) == before,
                'external/packet hash drift: ' + str(path)+'; regenerate configuration and requalify the affected profile')
        self.external[path] = before

    def git(self, *args, group='product'):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        environment['GIT_OPTIONAL_LOCKS'] = '0'
        return subprocess.check_output([self.packet['git']['path'], '-c', 'core.fsmonitor=false', *args],
            cwd=self.packet[group]['root'], env=environment, text=True, timeout=4).strip()

    def check(self):
        try:
            if self.borrowed:
                from .hosted_qualification import borrowed_input_stamp
                require(borrowed_input_stamp(self.borrowed['path']) == self.borrowed['stat'], 'borrowed input metadata drift')
            for root, patterns, before in self.groups:
                require(frozen_metadata(root, patterns) == before, 'frozen identity drift')
            require(all(stamp(path) == before for path, before in self.external.items()), 'external identity drift')
            for directory, metadata in getattr(self, 'runtime_directories', {}).items():
                require(frozen_metadata(directory.parent, [directory.name]) == metadata, 'external runtime membership/metadata drift')
            require(self.git('rev-parse', 'HEAD') == SOURCE and self.git('rev-parse', 'HEAD^{tree}') == TREE,
                    'product source/tree drift')
            require(self.git('rev-parse', 'HEAD', group='harness') == self.packet['harness_source']['commit']
                    and self.git('rev-parse', 'HEAD^{tree}', group='harness') == self.packet['harness_source']['tree'],
                    'harness source/tree drift')
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            raise OSError('scale frozen drift: ' + str(error)) from error

    def require_windows(self):
        p = self.packet
        require(os.name == 'nt' and platform.system() == 'Windows', 'actual Windows required for full mode')
        require(p['toolchains']['python_version'] == sys.version, 'actual Python version mismatch')
        require(p['host']['release'] == platform.release() and p['host']['version'] == platform.version()
                and p['host']['machine'] == platform.machine() and p['host']['node'] == platform.node(), 'actual Windows OS mismatch')
