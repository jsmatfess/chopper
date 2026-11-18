"""Browser-specific frozen identities; native packet assertions do not apply."""
from pathlib import Path
import re
import subprocess
from .guard import frozen_metadata, load_runner
from .verify import read_json, require, sha256


def stamp(path):
    value = path.stat()
    return tuple(getattr(value, key) for key in (
        "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode"))


class BrowserIdentity:
    def __init__(self, binding):
        self.root = Path(binding['root']).resolve()
        self.packet_path = Path(binding['packet']).absolute()
        require(self.packet_path.is_relative_to(self.root) and '..' not in self.packet_path.parts, 'browser packet outside source root')
        require(all(not p.is_symlink() for p in [self.packet_path, *self.packet_path.parents]), 'browser packet symlink ancestry')
        require(sha256(self.packet_path) == binding['sha256'], 'browser packet hash changed')
        self.packet = p = read_json(self.packet_path)
        require(p['version'] == 1 and p['runtime'] == 'browser' and p['mode'] == 'tiny'
                and p['features'] == [] and p['parent_scheduled'] is True, 'parent-scheduled default tiny browser freeze required')
        require(p['source']['clean'] is True and re.fullmatch('[0-9a-f]{40}', p['source']['commit']), 'clean source identity required')
        for key in ('host', 'storage', 'toolchains', 'build_receipts'):
            require(bool(p[key]), 'missing browser identity: ' + key)
        require(p['channel'] in ('chrome', 'msedge', 'bundled-chromium'), 'unsupported browser channel')
        require(p['browser_version'] and (p['channel'] == 'bundled-chromium' or p['host']['os'] == 'Windows'),
                'installed acceptance requires Windows host')
        require(re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{3,4}', p['origin'])
                and int(p['origin'].rsplit(':', 1)[1]) <= 65535, 'explicit loopback origin required')
        required = {'Cargo.toml', 'Cargo.lock', 'crates', 'vendor', 'ui/src', 'ui/package.json',
                    'ui/package-lock.json', 'ui/dist', 'scripts/*.py', 'scripts/*.mjs',
                    'scripts/scale_acceptance/*.py', 'scripts/scale_acceptance/*.mjs',
                    'ui/node_modules/playwright', 'ui/node_modules/playwright-core',
                    'ui/node_modules/esbuild', 'ui/node_modules/@esbuild'}
        require(required <= set(p['inputs']), 'complete browser source/assets/scripts required')
        self.patterns = [*p['inputs'], self.packet_path.relative_to(self.root).as_posix()]
        before = frozen_metadata(self.root, self.patterns)
        runner = load_runner()
        identity = runner.identity(self.root, p['inputs'])
        require(not runner.incomplete_identity(identity), 'incomplete browser input identity')
        actual = {Path(name).as_posix(): value['sha256'] for name, value in identity.items() if not value.get('directory')}
        require(actual == p['input_sha256'], 'browser input hashes changed')
        for name in ('engine.wasm', 'engine-worker.js', 'storage-worker.js', 'app.js', 'index.html', 'style.css', '_headers'):
            require('ui/dist/' + name in actual, 'missing production asset: ' + name)
        # The bundle is separate from deployable assets and bound to its actual esbuild inputs.
        bundle = self.root / p['bundle']
        require(bundle.is_relative_to(self.root / 'scratch') and '..' not in bundle.parts,
                'external bundle must stay under scratch')
        require(p['bundle'] in actual and p['bundle_provenance'] in actual, 'bundle/provenance must be frozen inputs')
        provenance = read_json(self.root / p['bundle_provenance'])
        require(provenance['bundle_sha256'] == sha256(bundle), 'bundle hash mismatch')
        require(provenance['inputs'] and all(actual.get(name) == digest for name, digest in provenance['inputs'].items()),
                'bundle source provenance mismatch')
        require('ui/src/app.ts' in provenance['inputs'] and 'ui/src/browser/client.ts' in provenance['inputs'] and
                'scripts/scale_acceptance/browser-page.mjs' in provenance['inputs'], 'production client bridge required')
        for name in p['build_receipts']:
            require(name in actual, 'build receipt must be a frozen input')
        self.external = {}
        for key in ('browser', 'node', 'python', 'reservation'):
            item = p[key]
            path = Path(item['path'])
            require(path.is_absolute() and '..' not in path.parts, 'absolute selected tool/reservation required')
            require(all(not parent.is_symlink() for parent in [path, *path.parents]), 'tool/reservation symlink')
            before_external = stamp(path)
            require(path.is_file() and sha256(path) == item['sha256'], 'selected tool/reservation hash changed')
            self.external[path] = before_external
            require(stamp(path) == before_external, 'selected tool changed during admission')
        self.metadata = frozen_metadata(self.root, self.patterns)
        require(self.metadata == before and sha256(self.packet_path) == binding['sha256'], 'browser drift during admission')
        require(subprocess.check_output(['git', 'status', '--porcelain'], cwd=self.root).strip() == b'', 'browser source must be clean')
        self.check()

    def check(self):
        try:
            require(frozen_metadata(self.root, self.patterns) == self.metadata, 'browser source/assets/packet drift')
            require(all(stamp(path) == value for path, value in self.external.items()), 'browser tool/reservation drift')
            require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=self.root, text=True).strip()
                    == self.packet['source']['commit'], 'browser source commit drift')
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
            raise OSError('browser frozen drift: ' + str(error)) from error
