"""Offline controls for the qualified native artifact publisher."""

import contextlib
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import call, patch


spec = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('publish-library-release.py'))
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)
VERSION = '0.7.0'
CANDIDATE = {'tag': 'v0.7.0-rc.3', 'tag_object': '1' * 40, 'commit': '2' * 40, 'tree': '3' * 40}
CRATE_VERSIONS = {name: VERSION for name in publisher.CRATES}
STEPS = ('cli-build', 'wheel-build', 'verify-artifacts', 'cargo-packages', 'wheel-venv', 'wheel-install',
         'installed-wheel', 'cli-reference', 'cli-recipes', 'cli-manifest', 'cli-upgrade', 'candidate-recheck')


def identity(data, size='size'):
    return {size: len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def crate_bytes(name, version):
    contents = {
        'Cargo.toml': f'''[package]
name = "{name}"
version = "{version}"
readme = "README.md"
license = "MIT"

[target.'cfg(windows)'.dependencies]
codec = {{ package = "chopper-flate2", version = "=1.1.10", default-features = false }}
''',
        'README.md': 'Package readme\n',
    }
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w') as archive:
        for member, value in contents.items():
            data = value.encode()
            entry = tarfile.TarInfo(f'{name}-{version}/{member}')
            entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), mtime=0)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def qualification(self, platform):
        path_type, target, tag, glibc = publisher.PLATFORMS[platform]
        recorded = path_type('/evidence/candidate-linux' if platform == 'linux' else 'C:/evidence/candidate-win')
        directory = self.root / platform

        def write(relative, data):
            path = directory / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return str(recorded / relative), identity(data)

        wheel_rel = f'wheels/{publisher.wheel_name(VERSION, tag)}'
        wheel = write(wheel_rel, f'{platform} installed wheel bytes'.encode())
        receipt = {'source': {'commit': CANDIDATE['commit'], 'tree': CANDIDATE['tree'], 'dirty': False},
                   'packages': {}}
        artifacts = {}
        for name, version in CRATE_VERSIONS.items():
            relative = f'cargo-packages/package-target/package/{name}-{version}.crate'
            data = crate_bytes(name, version)
            old_path, digest = write(relative, data)
            artifacts[old_path] = digest
            receipt['packages'][name] = {'path': old_path, 'version': version, **identity(data, 'bytes')}
        artifacts.update([write('cargo-packages/receipt.json', json.dumps(receipt).encode())])
        steps = [{'id': name, 'argv': ['qualified-command', name], 'depends': list(STEPS[i-1:i])}
                 for i, name in enumerate(STEPS)]
        plan = {'candidate': CANDIDATE, 'version': VERSION, 'native_target': target, 'wheel_tag': tag,
                'toolchains': {'glibc': glibc}, 'wheel': wheel[0], 'steps': steps}
        plan_bytes = json.dumps(plan).encode()
        write('manifest.json', plan_bytes)
        plan_binding = write('qualification.json', plan_bytes)
        attempts = [{'id': name, 'attempt': i+1, 'status': 'passed', 'exit_code': 0, 'argv': steps[i]['argv'],
                     'dependencies': {dep: i for dep in steps[i]['depends']}, 'artifacts': {}, 'inputs': {}}
                    for i, name in enumerate(STEPS)]
        by_step = {attempt['id']: attempt for attempt in attempts}
        by_step['cargo-packages']['artifacts'] = artifacts
        by_step['wheel-build']['artifacts'] = dict([wheel])
        by_step['installed-wheel']['inputs'] = dict([wheel])
        by_step['candidate-recheck']['inputs'] = dict([plan_binding])
        status = {'summary': {'passed': len(STEPS), 'incomplete': 0}, 'attempts': attempts}
        write('status.json', json.dumps(status).encode())
        return directory, by_step, status

    def artifact(self, platform='linux', cargo=False):
        directory, _, _ = self.qualification(platform)
        crates, wheel = publisher.qualified_artifacts(directory, platform, CANDIDATE, VERSION, CRATE_VERSIONS)
        return crates[0] if cargo else wheel

    def test_preview_uses_remapped_evidence_and_public_only_queries(self):
        linux, _, _ = self.qualification('linux')
        windows, _, _ = self.qualification('windows')
        argv = ['publisher', CANDIDATE['tag'], '--linux', str(linux), '--windows', str(windows)]
        version_manifest = {'workspace': {'package': {'version': VERSION}}, 'package': {'version': VERSION}}
        def tagged_source(tag):
            self.assertEqual(tag, CANDIDATE['tag'])
            self.assertTrue(set(publisher.RELEASE_CREDENTIALS).isdisjoint(os.environ))
            return CANDIDATE

        with (patch.object(sys, 'argv', argv), patch.object(publisher.qualification, 'tagged_source', side_effect=tagged_source),
              patch.dict(os.environ, dict.fromkeys(publisher.RELEASE_CREDENTIALS, 'fake')),
              patch.object(publisher.qualification, 'toml', return_value=version_manifest),
              patch.object(publisher, 'require_landed') as landed, patch.object(publisher, 'upload') as upload,
              patch.object(publisher, 'request', return_value=None) as request, contextlib.redirect_stdout(io.StringIO()) as stdout):
            publisher.main()
        report = json.loads(stdout.getvalue())
        self.assertEqual(report['mode'], 'preview')
        self.assertEqual(len(report['artifacts']), 7)
        self.assertEqual({entry['status'] for entry in report['artifacts'].values()}, {'pending'})
        self.assertEqual(request.call_count, 7)
        self.assertTrue(all(not hit.kwargs for hit in request.call_args_list))
        landed.assert_not_called()
        upload.assert_not_called()

    def test_changed_wheel_and_failed_latest_attempt_are_rejected(self):
        directory, by_step, status = self.qualification('windows')
        wheel = next((directory / 'wheels').iterdir())
        wheel.write_bytes(b'other wheel bytes')
        with self.assertRaisesRegex(ValueError, 'Qualified byte identity differs'):
            publisher.qualified_artifacts(directory, 'windows', CANDIDATE, VERSION, CRATE_VERSIONS)
        status['attempts'].append({**by_step['installed-wheel'], 'attempt': 13, 'status': 'failed'})
        (directory / 'status.json').write_text(json.dumps(status))
        with self.assertRaisesRegex(ValueError, 'not a current pass: installed-wheel'):
            publisher.qualified_artifacts(directory, 'windows', CANDIDATE, VERSION, CRATE_VERSIONS)

    def test_cargo_upload_frames_only_the_qualified_archive(self):
        artifact = self.artifact(cargo=True)
        with patch.object(publisher, 'request', return_value=b'{}') as request:
            publisher.upload(artifact, {'CARGO_REGISTRY_TOKEN': 'fake-credential'})
        (url,), options = request.call_args
        self.assertEqual(url, publisher.CRATES_UPLOAD)
        self.assertEqual(options['token'], 'fake-credential')
        body = options['body']
        metadata_end = 4 + struct.unpack_from('<I', body)[0]
        metadata = json.loads(body[4:metadata_end])
        self.assertEqual(metadata, {'name': artifact.name, 'vers': artifact.version,
                                    'readme': 'Package readme\n', 'readme_file': 'README.md'})
        self.assertEqual(struct.unpack_from('<I', body, metadata_end)[0], len(artifact.data))
        self.assertEqual(body[metadata_end+4:], artifact.data)

    def test_invalid_cargo_header_is_rejected_without_reporting_token(self):
        with patch.object(publisher, 'urlopen') as network:
            with self.assertRaises(ValueError) as error:
                publisher.request(publisher.CRATES_UPLOAD, body=b'', token='fixture\nprivate')
        self.assertEqual(str(error.exception), 'Set a valid CARGO_REGISTRY_TOKEN')
        network.assert_not_called()

    def test_wheel_upload_hands_twine_an_exact_copy_and_fixed_endpoint(self):
        artifact = self.artifact()
        staged = self.root / artifact.path.name
        staged.write_bytes(artifact.data)

        def twine(args, **options):
            self.assertEqual(args[1:5], ['-I', '-m', 'twine', 'upload'])
            self.assertIn('--non-interactive', args)
            self.assertEqual(args[args.index('--repository-url')+1], publisher.PYPI_UPLOAD)
            self.assertEqual(args[-1].name, artifact.path.name)
            self.assertEqual(args[-1].read_bytes(), artifact.data)
            self.assertNotIn('CARGO_REGISTRY_TOKEN', options['env'])
            self.assertEqual(options['env']['TWINE_PASSWORD'], 'fixture-token')

        with (patch.object(publisher.subprocess, 'run', side_effect=twine) as run,
              patch.dict(os.environ, {'CARGO_REGISTRY_TOKEN': 'fake', 'TWINE_PASSWORD': 'ambient-value'})):
            publisher.upload(artifact, {'TWINE_USERNAME': '__token__', 'TWINE_PASSWORD': 'fixture-token'}, staged)
        run.assert_called_once()

    def test_registry_checks_identical_checksum_and_unyanked_state(self):
        artifact = self.artifact(cargo=True)
        row = {'vers': artifact.version, 'cksum': artifact.sha256, 'yanked': False}
        with patch.object(publisher, 'request', return_value=json.dumps(row).encode()):
            self.assertTrue(publisher.available(artifact))
        for bad in ({**row, 'yanked': True}, {**row, 'cksum': '0' * 64}):
            with (patch.object(publisher, 'request', return_value=json.dumps(bad).encode()),
                  self.assertRaisesRegex(ValueError, 'yanked or differs')):
                publisher.available(artifact)

    def test_partial_retry_skips_exact_registry_bytes_and_keeps_upload_order(self):
        directory, _, _ = self.qualification('linux')
        crates, wheel = publisher.qualified_artifacts(directory, 'linux', CANDIDATE, VERSION, CRATE_VERSIONS)
        uploaded = {crates[0].path.name}
        env = {'CARGO_REGISTRY_TOKEN': 'fake', 'TWINE_USERNAME': '__token__', 'TWINE_PASSWORD': 'fake'}
        with (patch.dict(os.environ, env, clear=True), patch.object(publisher.subprocess, 'run') as run,
              patch.object(publisher, 'available', side_effect=lambda artifact: artifact.path.name in uploaded),
              patch.object(publisher, 'upload',
                           side_effect=lambda artifact, creds, path: uploaded.add(artifact.path.name)) as upload,
              contextlib.redirect_stderr(io.StringIO())):
            ordered = [*crates, wheel]
            result = publisher.publish_artifacts(ordered, True, env)
            self.assertTrue(set(publisher.RELEASE_CREDENTIALS).isdisjoint(run.call_args.kwargs['env']))
            self.assertEqual(run.call_args.args[0][4:6], ['check', '--strict'])
            staged = run.call_args.args[0][-1]
            self.assertEqual(upload.call_args_list, [call(a, env, None) for a in crates[1:]] + [call(wheel, env, staged)])
            self.assertEqual(result[crates[0].path.name]['status'], 'already published')
            upload.reset_mock()
            publisher.publish_artifacts(ordered, True, {})
            upload.assert_not_called()

    def test_lost_upload_response_polls_without_repeating_upload(self):
        artifact = self.artifact(cargo=True)
        credentials = {'CARGO_REGISTRY_TOKEN': 'fake'}
        with (patch.object(publisher, 'available', side_effect=[False, False, False, True]),
              patch.object(publisher, 'upload', side_effect=TimeoutError) as upload,
              patch.object(publisher.time, 'sleep') as sleep, contextlib.redirect_stderr(io.StringIO())):
            report = publisher.publish_artifacts([artifact], True, credentials)
        upload.assert_called_once_with(artifact, credentials, None)
        sleep.assert_called_once()
        self.assertEqual(report[artifact.path.name]['status'], 'published')

    def test_wheel_metadata_failure_precedes_any_registry_upload(self):
        directory, _, _ = self.qualification('linux')
        crates, wheel = publisher.qualified_artifacts(directory, 'linux', CANDIDATE, VERSION, CRATE_VERSIONS)
        credentials = {'CARGO_REGISTRY_TOKEN': 'fake', 'TWINE_USERNAME': '__token__', 'TWINE_PASSWORD': 'fake'}

        def check(args, **options):
            self.assertEqual(args[4:6], ['check', '--strict'])
            self.assertEqual(args[-1].read_bytes(), wheel.data)
            self.assertTrue(set(publisher.RELEASE_CREDENTIALS).isdisjoint(options['env']))
            raise subprocess.CalledProcessError(1, 'offline metadata check')

        with (patch.object(publisher, 'available', return_value=False), patch.object(publisher, 'upload') as upload,
              patch.object(publisher.subprocess, 'run', side_effect=check)):
            with self.assertRaises(subprocess.CalledProcessError):
                publisher.publish_artifacts([*crates, wheel], True, credentials)
        upload.assert_not_called()

    def test_only_literal_publish_flag_can_enable_uploads(self):
        argv = ['publisher', CANDIDATE['tag'], '--linux', 'linux', '--windows', 'windows', '--pub']
        with (patch.object(sys, 'argv', argv), patch.object(publisher.qualification, 'tagged_source') as tag,
              contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error):
            publisher.main()
        self.assertEqual(error.exception.code, 2)
        tag.assert_not_called()

    def test_final_tag_and_current_official_main_are_live_gates(self):
        final = f'refs/tags/v{VERSION}'
        tip = '4' * 40
        matching_refs = f'{tip}\trefs/heads/main\n{CANDIDATE["commit"]}\t{final}'
        with (patch.object(publisher.qualification, 'capture',
                           side_effect=[CANDIDATE['commit'], publisher.UPSTREAM, matching_refs]),
              patch.object(publisher.subprocess, 'run', side_effect=[None, subprocess.CompletedProcess([], 1)]) as run):
            with self.assertRaisesRegex(ValueError, 'reachable from GitHub main'):
                publisher.require_landed(CANDIDATE, VERSION)
        self.assertEqual(run.call_args_list[0].args[0], ['git', 'fetch', '--no-tags', publisher.UPSTREAM, tip])
        with (patch.object(publisher.qualification, 'capture',
                           side_effect=[CANDIDATE['commit'], publisher.UPSTREAM, f'{tip}\t{final}']),
              patch.object(publisher.subprocess, 'run') as run):
            with self.assertRaisesRegex(ValueError, 'tag on GitHub'):
                publisher.require_landed(CANDIDATE, VERSION)
        run.assert_not_called()
        with patch.object(publisher.qualification, 'capture',
                          side_effect=[CANDIDATE['commit'], 'https://mirror.example/chopper']) as git:
            with self.assertRaisesRegex(ValueError, 'rewrite the official Chopper remote'):
                publisher.require_landed(CANDIDATE, VERSION)
        self.assertEqual(git.call_count, 2)


if __name__ == '__main__':
    unittest.main()
