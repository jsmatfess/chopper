"""Synthetic identity/plan controls, not production integration receipts."""
import copy
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
from .browser_identity import BrowserIdentity
from . import browser_plan
from .guard import frozen_metadata, load_runner
from .verify import sha256


class BrowserIdentityControls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.root.joinpath('scratch').mkdir()
        patterns = ['Cargo.toml', 'Cargo.lock', 'crates', 'vendor', 'ui/src', 'ui/package.json',
                    'ui/package-lock.json', 'ui/dist', 'scripts/*.py', 'scripts/*.mjs',
                    'scripts/scale_acceptance/*.py', 'scripts/scale_acceptance/*.mjs',
                    'ui/node_modules/playwright', 'ui/node_modules/playwright-core',
                    'ui/node_modules/esbuild', 'ui/node_modules/@esbuild']
        for directory in ('crates', 'vendor', 'ui/node_modules/playwright', 'ui/node_modules/playwright-core',
                          'ui/node_modules/esbuild', 'ui/node_modules/@esbuild'):
            self.file(directory + '/source', 'source')
        for name in ('Cargo.toml', 'Cargo.lock', 'ui/package.json', 'ui/package-lock.json',
                     'ui/src/app.ts', 'ui/src/browser/client.ts', 'scripts/scale_acceptance/browser-page.mjs',
                     'scripts/scale_acceptance/module.py', 'scripts/tool.py', 'scripts/tool.mjs',
                     'ui/dist/engine.wasm', 'ui/dist/engine-worker.js', 'ui/dist/storage-worker.js',
                     'ui/dist/app.js', 'ui/dist/index.html', 'ui/dist/style.css', 'ui/dist/_headers',
                     'scratch/bridge.js', 'scratch/build-receipt.json'):
            self.file(name, name)
        provenance = dict(bundle_sha256=sha256(self.root / 'scratch/bridge.js'), inputs={
            name: sha256(self.root / name) for name in ('ui/src/app.ts', 'ui/src/browser/client.ts', 'scripts/scale_acceptance/browser-page.mjs')})
        self.file('scratch/provenance.json', json.dumps(provenance))
        patterns += ['scratch/bridge.js', 'scratch/provenance.json', 'scratch/build-receipt.json']
        self.packet = dict(version=1, runtime='browser', mode='tiny', parent_scheduled=True, features=[],
                           source=dict(clean=True, commit='a' * 40), host=dict(os='Windows'), storage=dict(volume='owned'),
                           toolchains=dict(node='synthetic'), build_receipts=['scratch/build-receipt.json'],
                           channel='msedge', browser_version='synthetic', origin='http://127.0.0.1:8421',
                           inputs=patterns, bundle='scratch/bridge.js', bundle_provenance='scratch/provenance.json')
        for name in ('browser', 'node', 'python', 'reservation'):
            self.file('scratch/' + name, name)
            self.packet[name] = dict(path=str(self.root / 'scratch' / name), sha256=sha256(self.root / 'scratch' / name))
        identity = load_runner().identity(self.root, patterns)
        self.packet['input_sha256'] = {Path(k).as_posix(): v['sha256'] for k, v in identity.items() if not v.get('directory')}
        self.git = patch('scale_acceptance.browser_identity.subprocess.check_output', side_effect=self.git_output)
        self.git.start()

    def git_output(self, argv, **kwargs):
        return b'' if 'status' in argv else 'a' * 40 + '\n'

    def tearDown(self):
        self.git.stop()
        self.temp.cleanup()

    def file(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
        return path

    def admit(self, packet=None):
        self.file('scratch/packet.json', json.dumps(packet or self.packet))
        return BrowserIdentity(dict(root=str(self.root), packet=str(self.root / 'scratch/packet.json'),
                                    sha256=sha256(self.root / 'scratch/packet.json')))

    def test_real_files_admission_and_drift(self):
        for name in ('ui/dist/engine.wasm', 'ui/src/browser/client.ts', 'scratch/bridge.js',
                     'scratch/build-receipt.json', 'scratch/packet.json', 'scratch/browser', 'scratch/reservation',
                     'ui/node_modules/playwright-core/source'):
            with self.subTest(name=name):
                identity = self.admit()
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b'x')
                with self.assertRaisesRegex(OSError, 'drift'):
                    identity.check()
                path.write_bytes(original)

    def test_inventory_addition_removal(self):
        identity = self.admit()
        added = self.file('ui/dist/unexpected-test.js', 'test')
        with self.assertRaisesRegex(OSError, 'drift'):
            identity.check()
        added.unlink()
        identity = self.admit()
        (self.root / 'ui/dist/engine.wasm').unlink()
        with self.assertRaisesRegex(OSError, 'drift'):
            identity.check()

    def test_wrong_hash_provenance_mode_platform_and_source(self):
        mutations = [lambda p: p.update(mode='scale'), lambda p: p.update(runtime='native'),
                     lambda p: p.update(features=['experimental']), lambda p: p.update(parent_scheduled=False),
                     lambda p: p['host'].update(os='Linux'), lambda p: p.update(origin='http://remote:8421'),
                     lambda p: p.update(build_receipts=['unfrozen']), lambda p: p.update(bundle='ui/dist/app.js'),
                     lambda p: p['input_sha256'].update({'ui/dist/engine.wasm': '0' * 64}),
                     lambda p: p['browser'].update(sha256='0' * 64),
                     lambda p: p.update(inputs=[name for name in p['inputs'] if name != 'vendor'])]
        for mutation in mutations:
            packet = copy.deepcopy(self.packet)
            mutation(packet)
            with self.subTest(packet=packet['mode']), self.assertRaises((ValueError, OSError)):
                self.admit(packet)
        self.file('scratch/bridge.js', 'different bundle')
        self.packet['input_sha256']['scratch/bridge.js'] = sha256(self.root / 'scratch/bridge.js')
        with self.assertRaisesRegex(ValueError, 'bundle hash'):
            self.admit()

    def test_symlink_and_parent_traversal(self):
        with self.assertRaisesRegex(ValueError, 'source root'):
            BrowserIdentity(dict(root=str(self.root), packet=str(self.root / 'scratch/../packet.json'), sha256='0' * 64))
        link = self.root / 'ui/dist/link'
        try:
            link.symlink_to(self.root / 'Cargo.toml')
        except OSError:
            self.skipTest('symlink creation unavailable')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            frozen_metadata(self.root, ['ui/dist'])

    def test_concrete_tiny_plan_and_browser_prelaunch_denial(self):
        from .guard import run
        selected_python = Path(sys.executable).resolve()
        self.packet['python'] = dict(path=str(selected_python), sha256=sha256(selected_python))
        self.admit()
        with patch.object(browser_plan, 'ROOT', self.root):
            made = browser_plan.make_browser(self.root / 'scratch/attempt', self.root / 'scratch/packet.json', 2000)
        manifest = json.loads(Path(made['plan']).read_text())
        policy = json.loads(Path(made['policy']).read_text())
        self.assertEqual(len(manifest['steps']), 5)
        self.assertEqual(manifest['batch_timeout_seconds'], 600)
        self.assertEqual(policy['owned_bytes'], 64 * 1024**2)
        self.assertEqual([s['id'] for s in manifest['steps']],
                         ['generate-D', 'generate-G', 'tiny-production-browser', 'verify-D', 'verify-G'])
        for step in manifest['steps'][:2]:
            self.assertEqual(step['argv'][-2:], ['--rows', '2000'])
        self.file('ui/dist/engine-worker.js', 'drift before launch')
        batch = self.root / 'scratch/attempt/batch'
        with self.assertRaisesRegex(ValueError, 'hashes changed'):
            run(made['plan'], batch, made['policy'])
        self.assertEqual(json.loads((batch / 'guard-failure.json').read_text())['checkpoint'], 'prelaunch')
        self.assertFalse((batch / '1-stdout.log').exists())

    def test_tiny_plan_refuses_expansion_before_identity_or_creation(self):
        for rows in (0, 2001, None, True):
            with self.assertRaisesRegex(ValueError, '1..2000'):
                browser_plan.make_browser(self.root / 'scratch/never', 'absent', rows)
        with patch.object(browser_plan, 'ROOT', self.root):
            for path in (self.root / 'scratch/../escape', self.root / 'outside'):
                with self.assertRaises(ValueError):
                    browser_plan.make_browser(path, 'absent')
        self.assertFalse((self.root / 'scratch/never').exists())
