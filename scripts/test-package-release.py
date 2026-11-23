#!/usr/bin/env python3
"""Tiny local controls: no product build, execution or release assets."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

spec = importlib.util.spec_from_file_location('packaging', Path(__file__).with_name('package-release.py'))
pkg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pkg)

LEGACY_PAYLOADS = {'LICENSE': 'LICENSE',
                   'licenses/zip-2.4.2/LICENSE': 'vendor/zip-2.4.2/LICENSE',
                   'README.txt': 'docs/releases/native-usage.txt'}


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        def write(name, value):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value, encoding='utf-8', newline='\n')
        write('Cargo.toml', '[workspace.package]\nversion="0.2.0"\n')
        write('Cargo.lock', ''.join(f'[[package]]\nname="{n}"\nversion="0.2.0"\n'
                                  for n in ('chopper', 'chopper-core', 'chopper-browser')))
        write('ui/package.json', '{"version":"0.2.0"}')
        write('ui/package-lock.json', '{"version":"0.2.0","packages":{"":{"version":"0.2.0"}}}')
        for path in pkg.PAYLOADS.values():
            path = path.format(version='0.2.0')
            write(path, f'Synthetic fixture: {path}\n')
        write('docs/releases/native-quickstart.txt', 'Chopper @VERSION@\nhttps://github.com/jsmatfess/chopper/blob/v@VERSION@/README.md#native-quickstart\n')
        (self.source / 'scripts').mkdir()
        for name in ('package-release.py', 'browser-artifacts.mjs'):
            shutil.copyfile(Path(__file__).with_name(name), self.source / 'scripts' / name)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.source), *args], stderr=subprocess.DEVNULL).decode().strip()
        git('init', '-q')
        git('config', 'core.autocrlf', 'false')
        git('add', '.')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture')
        self.hosted = self.root / 'hosted'
        self.hosted.mkdir()
        for name in pkg.HOSTED:
            (self.hosted / name).write_bytes(b'\0asm\x01\0\0\0' if name == 'engine.wasm' else b'fixture\n')
        self.manifest = {'schema_version': 1, 'packaging_schema_version': 1, 'version': '0.2.0',
                         'release_source_commit': git('rev-parse', 'HEAD'),
                         'release_source_tree': git('rev-parse', 'HEAD^{tree}'),
                         'dirty_source': False, 'native': {},
                         'hosted': {n: pkg.identity((self.hosted / n).read_bytes()) for n in pkg.HOSTED},
                         'packaging_inputs': {'hosted_directory': str(self.hosted)}}
        for kind, (_, executable, target) in pkg.PLATFORMS.items():
            path = self.root / executable
            path.write_bytes(b'Synthetic executable, never launched')
            self.manifest['native'][kind] = {**pkg.identity(path.read_bytes()), 'target': target}
            self.manifest['packaging_inputs'][kind] = str(path)
        self.plan = self.root / 'input.json'
        self.output = self.root / 'output'

    def assemble(self):
        self.plan.write_text(json.dumps(self.manifest))
        return pkg.assemble(self.source, self.plan, self.output)

    def test_round_trip_and_linux_permissions(self):
        result = self.assemble()
        self.assertEqual(pkg.verify(self.output, result['artifact_receipt']['sha256']), result)
        with zipfile.ZipFile(self.output / 'chopper-0.2.0-linux-x86_64.zip') as archive:
            self.assertEqual(archive.getinfo('chopper').external_attr >> 16 & 0o777, 0o755)
        receipt = json.loads((self.output / 'chopper-0.2.0-artifact-receipt.json').read_text())
        self.assertIsNone(receipt['toolchains'])
        self.assertIsNone(receipt['validation_attempts'])
        self.assertFalse(receipt['publication_approved'])
        self.assertEqual(set(receipt['hosted']), set(pkg.HOSTED))
        with self.assertRaisesRegex(ValueError, 'new path'):
            self.assemble()

    def test_native_packages_contain_the_release_quickstart_and_notices(self):
        self.assemble()
        for platform in ('linux', 'windows'):
            with self.subTest(platform=platform), zipfile.ZipFile(
                self.output / f'chopper-0.2.0-{platform}-x86_64.zip'
            ) as archive:
                readme = archive.read('README.txt')
                self.assertIn(b'Chopper 0.2.0\n', readme)
                self.assertIn(b'/blob/v0.2.0/README.md#native-quickstart', readme)
                self.assertEqual(
                    archive.read('THIRD-PARTY-NOTICES.txt'),
                    (self.source / 'docs/releases/native-usage.txt').read_bytes(),
                )
                self.assertEqual(archive.read('quickstart/customers.csv'),
                                 (self.source / 'examples/customers.csv').read_bytes())
                self.assertEqual(archive.read('quickstart/job.json'),
                                 (self.source / 'examples/quickstart-job.json').read_bytes())
                self.assertEqual(archive.read('job.schema.json'),
                                 (self.source / 'schemas/0.2.0/job.schema.json').read_bytes())

    def test_smoke_rejects_unverified_bytes_before_extraction(self):
        self.assemble()
        suffix = 'windows-x86_64' if os.name == 'nt' else 'linux-x86_64'
        archive = self.output / f'chopper-0.2.0-{suffix}.zip'
        extracted = self.root / 'fresh extraction'
        with self.assertRaisesRegex(ValueError, 'Archive SHA-256 mismatch'):
            pkg.smoke(archive, '0' * 64, extracted)
        self.assertFalse(extracted.exists())

    def test_legacy_four_member_native_archives_still_verify(self):
        with patch.object(pkg, 'PAYLOADS', LEGACY_PAYLOADS):
            result = self.assemble()
        self.assertEqual(pkg.verify(self.output, result['artifact_receipt']['sha256']), result)

    def test_current_release_rejects_legacy_inventory(self):
        for name in ('Cargo.toml', 'Cargo.lock', 'ui/package.json', 'ui/package-lock.json'):
            path = self.source / name
            path.write_text(path.read_text().replace('0.2.0', '0.5.0'))
        pkg.git(self.source, 'add', '.')
        pkg.git(self.source, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                '-c', 'commit.gpgsign=false', 'commit', '-qm', 'candidate version')
        self.manifest.update(version='0.5.0',
                             release_source_commit=pkg.git(self.source, 'rev-parse', 'HEAD'),
                             release_source_tree=pkg.git(self.source, 'rev-parse', 'HEAD^{tree}'))
        with patch.object(pkg, 'PAYLOADS', LEGACY_PAYLOADS):
            result = self.assemble()
        with self.assertRaisesRegex(ValueError, 'Receipt member inventory mismatch'):
            pkg.verify(self.output, result['artifact_receipt']['sha256'])

    def test_output_cannot_dirty_source(self):
        self.output = self.source / 'packages'
        with self.assertRaisesRegex(ValueError, 'must be ignored'):
            self.assemble()
        self.assertFalse(self.output.exists())

    def test_repeat_assembly_retains_stable_bytes(self):
        first = self.assemble()
        self.output = self.root / 'output2'
        self.assertEqual(self.assemble(), first)

    def test_bad_input_identity(self):
        self.manifest['native']['windows_x86_64']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            self.assemble()
        self.assertFalse(self.output.exists())

    def test_unknown_identity(self):
        self.manifest['hosted']['app.js']['sha256'] = None
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.assemble()

    def test_source_identity_and_version(self):
        self.manifest['release_source_commit'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'commit mismatch'):
            self.assemble()
        self.manifest['release_source_commit'] = pkg.git(self.source, 'rev-parse', 'HEAD')
        self.manifest['version'] = '0.3.0'
        with self.assertRaisesRegex(ValueError, 'Version metadata'):
            self.assemble()

    def test_packaging_tool_must_match_frozen_source(self):
        (self.source / 'scripts/browser-artifacts.mjs').write_text('changed guard')
        subprocess.run(['git', '-C', str(self.source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.source), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', '-c', 'commit.gpgsign=false',
                        'commit', '-qm', 'change guard'], check=True)
        self.manifest['release_source_commit'] = pkg.git(self.source, 'rev-parse', 'HEAD')
        self.manifest['release_source_tree'] = pkg.git(self.source, 'rev-parse', 'HEAD^{tree}')
        with self.assertRaisesRegex(ValueError, 'tools must match'):
            self.assemble()

    def test_dirty_source(self):
        (self.source / 'LICENSE').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'clean'):
            self.assemble()

    def test_untracked_source(self):
        (self.source / 'untracked').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'clean'):
            self.assemble()

    def test_extra_and_missing_hosted_member(self):
        (self.hosted / 'tests.html').write_text('test')
        with self.assertRaisesRegex(ValueError, 'seven'):
            self.assemble()
        (self.hosted / 'tests.html').unlink()
        (self.hosted / 'style.css').unlink()
        with self.assertRaisesRegex(ValueError, 'seven'):
            self.assemble()

    def test_both_resource_reactors_rejected_as_extra_members(self):
        for name in ('engine-resource-tests.wasm', 'engine-resource-tests-shuffle-partition.wasm'):
            with self.subTest(name=name):
                path = self.hosted / name
                path.write_bytes(b'not a production asset')
                with self.assertRaisesRegex(ValueError, 'seven'):
                    self.assemble()
                self.assertFalse(self.output.exists())
                path.unlink()

    def test_symlink_input(self):
        path = self.hosted / 'app.js'
        path.unlink()
        try:
            path.symlink_to(self.hosted / 'style.css')
        except OSError as error:
            self.skipTest(f'Host cannot create symlinks: {error}')
        with self.assertRaisesRegex(ValueError, 'regular file'):
            self.assemble()

    def test_resource_engine_and_invalid_wasm(self):
        # Valid tiny WASM with a memory export bearing the forbidden test name.
        name = b'chopper_resource_contracts'
        exports = b'\x01' + bytes([len(name)]) + name + b'\x02\x00'
        wasm = b'\0asm\x01\0\0\0\x05\x03\x01\x00\x01\x07' + bytes([len(exports)]) + exports
        for data in (wasm, b'not wasm'):
            with self.subTest(data=data):
                (self.hosted / 'engine.wasm').write_bytes(data)
                self.manifest['hosted']['engine.wasm'] = pkg.identity(data)
                with self.assertRaisesRegex(ValueError, 'Production WASM validation failed'):
                    self.assemble()
                self.assertFalse(self.output.exists())

    def test_checksum_and_receipt_tampering(self):
        result = self.assemble()
        digest = result['artifact_receipt']['sha256']
        with self.assertRaisesRegex(ValueError, 'Receipt identity'):
            pkg.verify(self.output, '0' * 64)
        (self.output / 'SHA256SUMS').write_text('wrong')
        with self.assertRaisesRegex(ValueError, 'SHA256SUMS'):
            pkg.verify(self.output, digest)

    def test_outer_archive_tampering(self):
        result = self.assemble()
        path = self.output / 'chopper-0.2.0-hosted.zip'
        path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'identity mismatch'):
            pkg.verify(self.output, result['artifact_receipt']['sha256'])

    def test_member_names_hashes_permissions_and_crc(self):
        self.assemble()
        path = self.output / 'chopper-0.2.0-linux-x86_64.zip'
        expected = json.loads((self.output / 'chopper-0.2.0-artifact-receipt.json').read_text())['package_members'][path.name]
        members = {n: b'fixture' for n in pkg.expected_members('linux_x86_64')}
        for fault in ('extra', 'hash', 'permission', 'crc', 'duplicate'):
            with self.subTest(fault=fault):
                path.unlink()
                actual = dict(members)
                identities = {n: pkg.identity(b) for n, b in actual.items()}
                if fault == 'extra':
                    actual['../outside'] = b'unsafe'
                if fault == 'hash':
                    actual['LICENSE'] = b'wrong'
                pkg.write_zip(path, actual, None if fault == 'permission' else 'chopper')
                if fault == 'crc':
                    data = bytearray(path.read_bytes())
                    # Corrupt the first central-directory CRC, leaving member bytes intact.
                    offset = data.index(b'PK\x01\x02') + 16
                    data[offset] ^= 1
                    path.write_bytes(data)
                if fault == 'duplicate':
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore', UserWarning)
                        with zipfile.ZipFile(path, 'a') as archive:
                            archive.writestr('LICENSE', b'duplicate')
                with self.assertRaises((ValueError, zipfile.BadZipFile)):
                    pkg.inspect_zip(path, 'linux_x86_64', identities)
        with self.assertRaisesRegex(ValueError, 'inventory'):
            pkg.inspect_zip(path, 'linux_x86_64', {**expected, 'extra': pkg.identity(b'x')})


if __name__ == '__main__':
    unittest.main()
