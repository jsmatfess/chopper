"""Tiny oracle/mutation and real subprocess guard controls; never launches Chopper."""
import argparse
import copy
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from scale_acceptance import generate, recipe, verify, guard, plan
from scale_acceptance.browser_identity_controls import BrowserIdentityControls


class Controls(unittest.TestCase):
    def test_hash_only_identity_matches_actual_stream_without_creating_files(self):
        before = set(self.root.iterdir())
        for (shape, rows), directory in self.datasets.items():
            metadata = verify.read_json(directory/'fixture.json')
            identity = generate.fixture_identity(shape, metadata['runtime'], rows)
            self.assertEqual(identity, {key:metadata[key] for key in ('width','rows','bytes','sha256')})
            self.assertEqual(identity['sha256'], verify.sha256(directory/'input.csv'))
        self.assertEqual(set(self.root.iterdir()), before)

    @classmethod
    def setUpClass(cls):
        cls.temporary = None if cls.work_root else tempfile.TemporaryDirectory(prefix='chopper-scale-controls-')
        cls.root = Path(tempfile.mkdtemp(prefix='retained-controls-', dir=cls.work_root)) if cls.work_root else Path(cls.temporary.name)
        cls.datasets = {}
        for shape, rows, runtime in [('D', 127, 'native'), ('G', 137, 'native'), ('G', 8, 'browser')]:
            directory = cls.root / f'{shape}-{rows}'
            generate.prepare(directory, shape, runtime, rows)
            job = verify.read_json(directory / 'job.json')
            job['limits']['rows'] = 7
            job['limits']['bytes'] = (100 if shape == 'D' else 1000) * 6
            (directory / 'job.json').write_text(json.dumps(job))
            cls.datasets[(shape, rows)] = directory
        cls.fixture_bytes = sum((d / 'input.csv').stat().st_size for d in cls.datasets.values())
        assert cls.fixture_bytes < 3 * 1024**2

    @classmethod
    def tearDownClass(cls):
        if cls.temporary:
            cls.temporary.cleanup()

    def setUp(self):
        self.sandbox = tempfile.TemporaryDirectory(dir=self.root)
        self.output = Path(self.sandbox.name) / 'output'
        self.output.mkdir()

    def tearDown(self):
        self.sandbox.cleanup()

    def synthesize(self, shape='D', rows=127):
        directory = self.datasets[(shape, rows)]
        config = verify.read_json(directory / 'job.json')
        meta = verify.read_json(directory / 'fixture.json')
        records = (directory / 'input.csv').read_bytes().splitlines(keepends=True)
        header, records = records[0], records[1:]
        capacity = min(config['limits']['rows'], config['limits']['bytes'] // meta['width'] - 1)
        if shape == 'D':
            groups = [(None, records)]
        else:
            groups = []
            for region in range(min(rows, 8)):
                members = records[region::8]
                treatment = verify.quotas(len(members))[0]
                for arm, values in [('treatment', members[:treatment]), ('control', members[treatment:])]:
                    groups.append(((f'r{region}', arm), list(reversed(values))))
        outputs = []
        for key, values in groups:
            for start in range(0, max(len(values), 1), capacity):
                selected = values[start:start + capacity]
                prefix = '' if key is None else f'region-{key[0]}-allocation-{key[1]}-'
                name = prefix + f'part-{len(outputs) + 1:08d}.csv'
                content = header + b''.join(selected)
                (self.output / name).write_bytes(content)
                outputs.append(dict(type='output', path=name, rows=len(selected), csv_bytes=len(content),
                                    stored_bytes=len(content), compressed_target_exceeded=False,
                                    lineage=[] if key is None else [dict(operation=0, values=[key[0]]),
                                                                    dict(operation=1, allocation=key[1])]))
        # Emulate serde's omitted default versioned randomization fields.
        manifest_config = copy.deepcopy(config)
        for key in ('full_shuffle_policy', 'full_shuffle_rng', 'full_shuffle_algorithm'):
            del manifest_config[key]
        if meta['runtime'] == 'browser':
            manifest_config.update(input='/input.csv', output='/results')
            manifest_config['resources']['temp_dir'] = '/tmp'
        first = dict(type='job', schema_version=1, algorithm_version='chopper-v1-blake3-1', config=manifest_config,
                     analysis=dict(rows=rows, groups=1 if shape == 'D' else min(rows, 8) * 2, output_files=len(outputs), output_csv_bytes=sum(o['csv_bytes'] for o in outputs)))
        self.write_manifest([first, *outputs])
        if meta['runtime'] == 'browser':
            (self.output / 'CHOPPER-COMPLETE.json').write_text(json.dumps(dict(complete=True,
                files=len(outputs) + 1, engine='chopper-browser', version=1)))
        return directory, [first, *outputs]

    def write_manifest(self, records):
        (self.output / 'manifest.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in records))

    def check(self, directory, **kwargs):
        return verify.verify(directory / 'job.json', directory / 'fixture.json', self.output, self.root, **kwargs)

    def test_disk_completed_facts_keep_oldest_start(self):
        clock = [0.0]
        sampler = guard.DiskObservation(lambda: None, clock=lambda: clock[0])
        sampler.started, sampler.finished = 0, 29
        sampler.value = dict(value={'bytes': 7}, started=0, finished=29)
        sampler.done.set()  # A stopped sample still expires from its original start.
        clock[0] = 89
        self.assertEqual(sampler.read()['value']['bytes'], 7)
        clock[0] = 90.001
        with self.assertRaisesRegex(ValueError, 'stale from observation start'):
            sampler.read()
        # A fresh publication time cannot refresh its oldest observation start.
        sampler.finished = 90
        with self.assertRaisesRegex(ValueError, 'stale from observation start'):
            sampler.read()

    def test_disk_start_then_raise_keeps_unknown_thread_owned(self):
        release, entered = threading.Event(), threading.Event()
        threads = []
        def launch(call):
            thread = threading.Thread(target=call, daemon=True)
            threads.append(thread)
            thread.start()
            self.assertTrue(entered.wait(1))
            raise OSError('launch result lost')
        def sample():
            entered.set()
            release.wait(2)
        sampler = guard.DiskObservation(sample, launch=launch)
        try:
            with self.assertRaisesRegex(OSError, 'result lost'):
                sampler.start()
            self.assertTrue(sampler.pending)
            with self.assertRaisesRegex(ValueError, 'ownership uncertain'):
                sampler.stop(.01)
        finally:
            release.set()
            for thread in threads:
                thread.join(1)
        self.assertTrue(sampler.pending, 'No returned handle means no manufactured join proof')

    def test_disk_after_equal_start_requests_strictly_new_census(self):
        sampler = guard.DiskObservation(lambda: 7).start()
        try:
            first = sampler.after(0, 1)
            second = sampler.after(first['started'], 1)
            self.assertGreater(second['started'], first['started'])
        finally:
            sampler.stop(1)

    def test_disk_missed_start_cadence_is_denied(self):
        clock = [45.001]
        sampler = guard.DiskObservation(lambda: None, clock=lambda: clock[0])
        sampler.started, sampler.finished = 0, 1
        sampler.value = dict(value=7, started=0, finished=1)
        with self.assertRaisesRegex(ValueError, 'cadence exceeded'):
            sampler.read()

    def test_pending_disk_does_not_publish_or_block_hot_checks(self):
        entered, release = threading.Event(), threading.Event()
        clock = [0.0]
        def sample():
            entered.set()
            release.wait(2)
            return {'bytes': 9}
        sampler = guard.DiskObservation(sample, clock=lambda: clock[0]).start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(sampler.pending)
            with self.assertRaisesRegex(ValueError, 'no completed'):
                sampler.read()
            # Independent hot checks remain executable while the disk call waits.
            self.assertTrue(entered.is_set())
            with self.assertRaisesRegex(ValueError, 'pending call'):
                sampler.stop(.01)
            clock[0] = 30.001
            with self.assertRaisesRegex(ValueError, 'late/blocked'):
                sampler.check()
            release.set()
            sampler.thread.join(1)
            self.assertFalse(sampler.pending)
            self.assertIsNone(sampler.value)
            with self.assertRaisesRegex(ValueError, 'late/blocked'):
                sampler.read()
        finally:
            release.set()
            sampler.stop(1)

    def test_disk_after_requires_new_completed_census_and_joins(self):
        calls = []
        sampler = guard.DiskObservation(lambda: calls.append(time.monotonic()) or len(calls)).start()
        try:
            first = sampler.after(0, 1)
            marker = time.monotonic()
            second = sampler.after(marker, 1)
            self.assertGreaterEqual(second['started'], marker)
            self.assertGreater(second['value'], first['value'])
        finally:
            sampler.stop(1)
        self.assertFalse(sampler.pending)

    def test_dimensions_and_formula(self):
        for shape, width, native, browser in [('D', 100, 99_999_999, 9_999_999), ('G', 1000, 9_999_999, 999_999)]:
            for runtime, rows, size in [('native', native, 10_000_000_000), ('browser', browser, 1_000_000_000)]:
                self.assertEqual(recipe.dimensions(shape, runtime), (width, rows, size))
                config = recipe.job(shape, runtime, 'input', 'output', 'temp')
                recipe.validate(config, shape, runtime)
                self.assertEqual(config['resources']['max_record_bytes'], 4096)
            for index in (0, 1, 7, 8, 999_999_999_999):
                self.assertEqual(len(generate.header(width)), width)
                self.assertEqual(verify.inspect_row(generate.row(index, width), width, 10**12), index)
        with self.assertRaises(ValueError):
            recipe.dimensions('D', 'native', 2001)
        with self.assertRaises(FileExistsError):
            generate.prepare(self.datasets[('D', 127)], 'D', 'native', 1)
        self.assertNotIn('generate', verify.__dict__)
        self.assertEqual(verify.quotas(17), [14, 3])
        self.assertEqual(verify.quotas(18), [14, 4])

    def test_known_quota_answers(self):
        self.assertEqual([verify.quotas(n) for n in range(11)],
                         [[0, 0], [1, 0], [2, 0], [2, 1], [3, 1], [4, 1],
                          [5, 1], [6, 1], [6, 2], [7, 2], [8, 2]])

    def test_direct_and_grouped_pass(self):
        for key in [('D', 127), ('G', 137), ('G', 8)]:
            with self.subTest(key=key):
                for path in self.output.iterdir():
                    path.unlink()
                directory, records = self.synthesize(*key)
                result = self.check(directory)
                self.assertEqual(result['rows'], key[1])
                peer = self.root / 'peer.json'
                peer.write_text(json.dumps(result))
                self.check(directory, peer=peer)
                if key == ('G', 8):
                    self.assertEqual(sum(r['rows'] == 0 for r in records[1:]), 8)

    def test_browser_worker_config_paths_and_resource_mutations(self):
        directory, records = self.synthesize('G', 8)
        self.check(directory)
        original = copy.deepcopy(records[0]['config'])
        mutations = [('input', '/other.csv'), ('output', '/other'),
                     ('temp_dir', None), ('temp_dir', '/other'),
                     ('memory_mb', 128), ('workers', 2)]
        for key, value in mutations:
            with self.subTest(key=key, value=value):
                records[0]['config'] = copy.deepcopy(original)
                target = records[0]['config'] if key in ('input', 'output') else records[0]['config']['resources']
                target[key] = value
                self.write_manifest(records)
                with self.assertRaisesRegex(ValueError, 'manifest config mismatch'):
                    self.check(directory)

    def test_mutations_fail(self):
        mutations = ['duplicate', 'missing', 'id', 'payload', 'region', 'header', 'order',
                     'cap', 'rows', 'manifest-config', 'manifest-total', 'manifest-path',
                     'manifest-truncate', 'extra-file', 'extra-manifest', 'extra-empty', 'peer-order']
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                for path in self.output.iterdir():
                    path.unlink()
                directory, records = self.synthesize()
                path = self.output / records[1]['path']
                raw = path.read_bytes()
                if mutation == 'duplicate':
                    path.write_bytes(raw[:200] + raw[100:200] + raw[300:])
                elif mutation == 'missing':
                    path.write_bytes(raw[:-100])
                elif mutation == 'id':
                    path.write_bytes(raw[:100] + b'999999999999' + raw[112:])
                elif mutation == 'payload':
                    path.write_bytes(raw[:120] + (b'z' if raw[120:121] != b'z' else b'y') + raw[121:])
                elif mutation == 'region':
                    path.write_bytes(raw[:114] + b'7' + raw[115:])
                elif mutation == 'header':
                    path.write_bytes(b'x' + raw[1:])
                elif mutation == 'order':
                    path.write_bytes(raw[:100] + raw[200:300] + raw[100:200] + raw[300:])
                elif mutation == 'cap':
                    path.write_bytes(raw + raw[-100:])
                elif mutation == 'rows':
                    records[1]['rows'] -= 1
                    self.write_manifest(records)
                elif mutation == 'manifest-config':
                    records[0]['config']['seed'] = 'wrong'
                    self.write_manifest(records)
                elif mutation == 'manifest-total':
                    records[0]['analysis']['output_files'] += 1
                    self.write_manifest(records)
                elif mutation == 'manifest-path':
                    records[1]['path'] = '../input.csv'
                    self.write_manifest(records)
                elif mutation == 'manifest-truncate':
                    manifest = self.output / 'manifest.jsonl'
                    manifest.write_bytes(manifest.read_bytes()[:-1])
                elif mutation == 'extra-file':
                    (self.output / 'unexpected').touch()
                elif mutation == 'extra-manifest':
                    self.write_manifest(records + [records[-1]])
                elif mutation == 'extra-empty':
                    extra = copy.deepcopy(records[-1])
                    extra.update(path=f'part-{len(records):08d}.csv', rows=0, csv_bytes=100, stored_bytes=100)
                    (self.output / extra['path']).write_bytes(raw[:100])
                    records.append(extra)
                    records[0]['analysis']['output_files'] += 1
                    records[0]['analysis']['output_csv_bytes'] += 100
                    self.write_manifest(records)
                else:
                    result = self.check(directory)
                    result['chunks'][0]['sha256'] = '0' * 64
                    peer = self.root / 'wrong-peer.json'
                    peer.write_text(json.dumps(result))
                    with self.assertRaisesRegex(ValueError, 'peer'):
                        self.check(directory, peer=peer)
                    continue
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.check(directory)

    def test_grouped_order_and_membership_peer_controls(self):
        for change in ('order', 'membership'):
            with self.subTest(change=change):
                for path in self.output.iterdir():
                    path.unlink()
                directory, records = self.synthesize('G', 137)
                peer = self.root / 'grouped-peer.json'
                original = self.check(directory)
                peer.write_text(json.dumps(original))
                first = self.output / records[1]['path']
                a = first.read_bytes()
                if change == 'order':
                    first.write_bytes(a[:1000] + a[2000:3000] + a[1000:2000] + a[3000:])
                else:
                    control = next(r for r in records[1:] if r['lineage'][1]['allocation'] == 'control')
                    second = self.output / control['path']
                    b = second.read_bytes()
                    first.write_bytes(a[:1000] + b[1000:2000] + a[2000:])
                    second.write_bytes(b[:1000] + a[1000:2000] + b[2000:])
                # Lawful quotas/conservation alone cannot determine seeded draws/order.
                changed = self.check(directory)
                self.assertNotEqual(original['groups'], changed['groups'])
                with self.assertRaisesRegex(ValueError, 'peer'):
                    self.check(directory, peer=peer)

    def test_group_and_zero_quota_mutations(self):
        for mutation in ['wrong-region', 'wrong-arm', 'quota', 'missing-zero', 'duplicate-zero', 'marker-missing', 'marker-count', 'marker-type']:
            with self.subTest(mutation=mutation):
                for path in self.output.iterdir():
                    path.unlink()
                directory, records = self.synthesize('G', 8)
                if mutation == 'wrong-region':
                    records[1]['lineage'][0]['values'] = ['r7']
                elif mutation == 'wrong-arm':
                    records[1]['lineage'][1]['allocation'] = 'control'
                elif mutation == 'quota':
                    # Put a real, valid row in a zero-quota arm; update counts/bytes.
                    path = self.output / records[2]['path']
                    source = (self.output / records[1]['path']).read_bytes()
                    path.write_bytes(source)
                    records[2].update(rows=1, csv_bytes=2000, stored_bytes=2000)
                elif mutation == 'missing-zero':
                    (self.output / records[2]['path']).unlink()
                    del records[2]
                elif mutation == 'duplicate-zero':
                    records.insert(3, records[2])
                else:
                    marker = self.output / 'CHOPPER-COMPLETE.json'
                    if mutation == 'marker-missing':
                        marker.unlink()
                    else:
                        value = verify.read_json(marker)
                        value['files' if mutation == 'marker-count' else 'complete'] = 0 if mutation == 'marker-count' else 1
                        marker.write_text(json.dumps(value))
                self.write_manifest(records)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.check(directory)

    def policy(self):
        root = Path(self.sandbox.name)
        return dict(version=1, owned_roots=[str(root)], volumes=[str(root)], owned_bytes=1024**2,
                    start_free_bytes=1, stop_free_bytes=1, deadline_seconds=5,
                    no_progress_seconds=1, sample_seconds=0.01, progress_paths=[str(root / 'progress')])

    def test_scale_hot_guard_rejects_identity_drift_while_disk_is_pending(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        entered, release = threading.Event(), threading.Event()
        calls = []
        def disk_sample():
            calls.append(1)
            if len(calls)>1:
                entered.set()
                release.wait(2)
            return dict(owned=17, free=[200*1024**3])
        sampler = guard.DiskObservation(disk_sample).start()
        try:
            sampler.after(0, 1)
            tick = [0.0]
            control = guard.Guard(self.policy(), Path(self.sandbox.name)/'async-capacity.jsonl', clock=lambda:tick[0], disk=sampler)
            sampler.wake.set()
            self.assertTrue(entered.wait(1))
            control.frozen = SimpleNamespace(check=Mock(side_effect=OSError('source drift')))
            with self.assertRaisesRegex(OSError, 'source drift'):
                control()
            control.frozen.check.assert_called_once_with()
        finally:
            release.set()
            sampler.stop(1)

    def test_guard_capacity_progress_deadline_reservation(self):
        for reason in ['capacity', 'space', 'progress', 'deadline', 'reservation', 'quota']:
            with self.subTest(reason=reason):
                policy = self.policy()
                tick = [0.0]
                if reason == 'capacity':
                    policy['owned_bytes'] = 1
                if reason == 'space':
                    policy['start_free_bytes'] = 10**30
                if reason == 'reservation':
                    lock = Path(self.sandbox.name) / 'host-lock'
                    lock.write_text('parent')
                    policy['reservation'] = dict(path=str(lock), sha256='0' * 64)
                if reason == 'quota':
                    quota = Path(self.sandbox.name) / 'quota.json'
                    quota.write_text(json.dumps(dict(sampled_unix=time.time(), usable_bytes=0)))
                    policy['browser_quota'] = dict(path=str(quota), start_bytes=1, stop_bytes=1)
                log = Path(self.sandbox.name) / 'capacity.jsonl'
                if reason in ['progress', 'deadline']:
                    control = guard.Guard(policy, log, clock=lambda: tick[0])
                    tick[0] = 2 if reason == 'progress' else 6
                    with self.assertRaisesRegex(OSError, 'no progress' if reason == 'progress' else 'deadline'):
                        control()
                else:
                    # Ensure at least one owned byte exists before the capacity test.
                    log.touch()
                    log.write_text('sample\n')
                    with self.assertRaises(OSError):
                        guard.Guard(policy, log, clock=lambda: tick[0])

    def test_capacity_census_allows_retired_temporary_children(self):
        root = Path(self.sandbox.name)
        retired = root / 'retired-spool'
        retired.write_text('temporary')
        def retiring_walk(folder, **kwargs):
            # Deterministically retire a name after enumeration, before stat.
            retired.unlink()
            yield str(folder), [], [retired.name]
        with patch.object(guard.os, 'walk', retiring_walk):
            guard.Guard(self.policy(), root / 'retirement-samples.jsonl')
        self.assertFalse(retired.exists())

    def test_wrapper_retains_prelaunch_denial(self):
        root = Path(self.sandbox.name)
        policy = root / 'policy.json'
        policy.write_text(json.dumps(self.policy()))
        manifest = root / 'plan.json'
        manifest.write_text(json.dumps(dict(root=str(root), steps=[dict(id='never-run', inputs=['source'])])))
        batch = root / 'denied-batch'
        with self.assertRaisesRegex(ValueError, 'policy must be a declared input'):
            guard.run(manifest, batch, policy)
        failure = verify.read_json(batch / 'guard-failure.json')
        self.assertEqual(failure['checkpoint'], 'prelaunch')
        self.assertEqual(failure['unrun_steps'], ['never-run'])
        self.assertTrue((batch / 'requested-plan.json').exists())
        self.assertTrue((batch / 'guard-policy.json').exists())

    def frozen_fixture(self, root=None):
        root = Path(self.sandbox.name) if root is None else root
        root.mkdir(parents=True, exist_ok=True)
        (root / 'scratch').mkdir(exist_ok=True)
        source_files = ['Cargo.toml', 'Cargo.lock', 'crates/source.rs', 'vendor/source.c',
                        'ui/public/app.js', 'ui/index.html', 'ui/style.css']
        for name in source_files:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('tiny frozen source: ' + name)
        executable = root / 'frozen-synthetic-executable'
        executable.write_bytes(b'not a product; plan schema test only')
        lock = root / 'reservation'
        lock.write_text('synthetic parent reservation')
        frozen = root / 'frozen.json'
        packet = dict(runtime='native', features=[], parent_scheduled=True,
                      source=dict(clean=True, commit='0' * 40), package={'scope': 'synthetic control'},
                      host={'scope': 'synthetic control'}, storage={'volumes': [str(root)]},
                      toolchains={'scope': 'synthetic control'}, inputs=['Cargo.toml', 'Cargo.lock', 'crates',
                                  'vendor', 'ui/public', 'ui/index.html', 'ui/style.css'],
                      input_sha256={name: verify.sha256(root / name) for name in source_files},
                      executable=str(executable), executable_sha256=verify.sha256(executable),
                      reservation=dict(path=str(lock), sha256=verify.sha256(lock)))
        frozen.write_text(json.dumps(packet))
        return root, frozen, packet, executable

    def test_concrete_native_manifests_without_execution(self):
        root, frozen, packet, executable = self.frozen_fixture()
        original = plan.ROOT
        try:
            plan.ROOT = root
            for shape in ('D', 'G'):
                result = plan.make(root / 'scratch' / shape, shape, frozen)
                manifest = verify.read_json(result['plan'])
                self.assertEqual([s['id'] for s in manifest['steps']],
                                 ['generate-' + shape, 'run-' + shape, 'verify-' + shape])
                self.assertEqual(manifest['steps'][1]['depends'], ['generate-' + shape])
                self.assertEqual(manifest['steps'][2]['depends'], ['run-' + shape])
                self.assertEqual([s['timeout_seconds'] for s in manifest['steps']], [3600, 7200, 3600])
                self.assertFalse((root / 'scratch' / shape / 'data').exists())
                for step in manifest['steps']:
                    self.assertIn(str(Path(result['policy']).relative_to(root)), step['inputs'])
                    self.assertTrue(step['artifacts'])
            packet['parent_scheduled'] = False
            frozen.write_text(json.dumps(packet))
            with self.assertRaisesRegex(ValueError, 'parent-scheduled'):
                plan.make(root / 'scratch' / 'blocked', 'D', frozen)
        finally:
            plan.ROOT = original

    def test_plan_rejects_parent_traversal_before_creation(self):
        root = Path(self.sandbox.name)
        (root / 'scratch').mkdir()
        original = plan.ROOT
        try:
            plan.ROOT = root
            with self.assertRaises(ValueError):
                plan.make(root / 'scratch' / '..' / 'outside')
            self.assertFalse((root / 'outside').exists())
        finally:
            plan.ROOT = original

    def test_plan_rejects_symlink_ancestry_before_creation(self):
        root = Path(self.sandbox.name)
        (root / 'scratch').mkdir()
        outside = root / 'outside'
        outside.mkdir()
        link = root / 'scratch' / 'linked'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest('directory symlinks unavailable: ' + str(error))
        original = plan.ROOT
        try:
            plan.ROOT = root
            with self.assertRaises(ValueError):
                plan.make(link / 'attempt')
            self.assertFalse((outside / 'attempt').exists())
        finally:
            plan.ROOT = original

    def frozen_run_fixture(self, root):
        root, frozen, packet, executable = self.frozen_fixture(root)
        policy = self.policy()
        policy.update(owned_roots=[str(root)], volumes=[str(root)],
                      progress_paths=[str(root / 'progress')],
                      frozen=dict(root=str(root), packet=str(frozen), sha256=verify.sha256(frozen)))
        policy_file = root / 'policy.json'
        policy_file.write_text(json.dumps(policy))
        manifest = dict(root=str(root), batch_timeout_seconds=3, estimated_seconds=1,
                        estimated_disk_bytes=1024, toolchains={'python': sys.version}, features=[], fixtures=[],
                        steps=[dict(id='control', argv=[sys.executable, '-c',
                            'from pathlib import Path; Path("launched").write_text("started")'],
                            timeout_seconds=2, inputs=['policy.json', 'frozen.json', *packet['inputs']],
                            artifacts=['launched'], depends=[])])
        manifest_file = root / 'plan.json'
        manifest_file.write_text(json.dumps(manifest))
        return root, frozen, executable, manifest_file, policy_file

    def test_frozen_drift_is_rejected_before_any_step(self):
        for mutation in ['executable', 'source', 'added-source', 'missing-source', 'packet']:
            with self.subTest(mutation=mutation):
                root, frozen, executable, manifest_file, policy_file = self.frozen_run_fixture(
                    Path(self.sandbox.name) / mutation)
                if mutation == 'executable':
                    executable.write_bytes(b'replacement package')
                elif mutation == 'source':
                    (root / 'crates/source.rs').write_text('changed frozen source')
                elif mutation == 'added-source':
                    (root / 'crates/new.rs').write_text('new unapproved source')
                elif mutation == 'missing-source':
                    (root / 'vendor/source.c').unlink()
                else:
                    frozen.write_text('{}')
                batch = root / 'batch'
                try:
                    result = guard.run(manifest_file, batch, policy_file)
                except (ValueError, OSError):
                    pass
                else:
                    self.fail(f'frozen mutation was not rejected at admission: return={result}, '
                              f'status={verify.read_json(batch / "status.json")}')
                self.assertFalse((root / 'launched').exists())
                failure = verify.read_json(batch / 'guard-failure.json')
                self.assertEqual(failure['checkpoint'], 'prelaunch')
                self.assertEqual(failure['unrun_steps'], ['control'])

    def test_frozen_wrapper_accepts_unchanged_inputs(self):
        root, _, _, manifest, policy = self.frozen_run_fixture(Path(self.sandbox.name) / 'valid')
        self.assertEqual(guard.run(manifest, root / 'batch', policy), 0)
        self.assertEqual((root / 'launched').read_text(), 'started')
        self.assertEqual(verify.read_json(root / 'batch/status.json')['summary'],
                         {'passed': 1, 'incomplete': 0})

    def test_frozen_drift_is_checked_between_capacity_samples(self):
        root, frozen, _, executable = self.frozen_fixture()
        policy = self.policy()
        policy['sample_seconds'] = 5
        policy['frozen'] = dict(root=str(root), packet=str(frozen), sha256=verify.sha256(frozen))
        control = guard.Guard(policy, root / 'frozen-samples.jsonl')
        executable.write_bytes(b'replacement package after admission')
        with self.assertRaisesRegex(OSError, 'frozen'):
            control()

    def test_identical_checkpoints_are_not_progress(self):
        policy = self.policy()
        path = Path(policy['progress_paths'][0])
        path.write_text('Reading | 1 rows | 0 MiB temporary\n')
        tick = [0.0]
        control = guard.Guard(policy, Path(self.sandbox.name) / 'samples.jsonl', clock=lambda: tick[0])
        path.write_text(path.read_text() * 3)
        tick[0] = 2
        with self.assertRaisesRegex(OSError, 'no progress'):
            control()

    def test_runner_failure_artifact_drift_timeout_and_reap(self):
        runner = guard.load_runner()
        root = Path(self.sandbox.name)
        source = root / 'source'
        source.write_text('original')
        for case in ['nonzero', 'missing-artifact', 'drift', 'timeout', 'guard-denial']:
            with self.subTest(case=case):
                source.write_text('original')
                command = {
                    'nonzero': 'raise SystemExit(7)',
                    'missing-artifact': 'print("no artifact")',
                    'drift': 'from pathlib import Path; Path("source").write_text("changed")',
                    'timeout': 'import time; time.sleep(10)',
                    'guard-denial': 'import time; time.sleep(10)'}[case]
                manifest = dict(root=str(root), batch_timeout_seconds=3, estimated_seconds=1,
                                estimated_disk_bytes=1024, toolchains={'python': sys.version}, features=[], fixtures=[],
                                steps=[dict(id='control', argv=[sys.executable, '-c', command], timeout_seconds=0.2 if case == 'timeout' else 2,
                                            inputs=['source'], artifacts=['absent'] if case == 'missing-artifact' else [], depends=[])])
                file = root / f'{case}.json'
                file.write_text(json.dumps(manifest))
                calls = [0]
                def denial():
                    calls[0] += 1
                    if calls[0] > 2:
                        raise OSError('injected capacity denial')
                started = time.monotonic()
                self.assertEqual(runner.run(file, root / case, guard=denial if case == 'guard-denial' else None), 1)
                self.assertLess(time.monotonic() - started, 3)
                status = verify.read_json(root / case / 'status.json')
                attempt = status['attempts'][0]
                self.assertEqual(attempt['status'], 'timeout' if case == 'timeout' else 'invalidated' if case == 'drift' else 'failed')
                self.assertTrue((root / case / '1-stdout.log').exists())
                self.assertFalse((root / case / 'runner.lock').exists())
        if os.name != 'nt':
            # Exercise the real group kill with a child and grandchild, retaining evidence.
            pidfile = root / 'descendant.pid'
            code = ('import subprocess,sys,time; from pathlib import Path; '
                    'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(20)"]); '
                    'Path("descendant.pid").write_text(str(p.pid)); time.sleep(20)')
            process = subprocess.Popen([sys.executable, '-c', code], cwd=root, start_new_session=True)
            try:
                deadline = time.monotonic() + 2
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pidfile.exists())
                runner.stop(process)
                self.assertIsNotNone(process.returncode)
                descendant = int(pidfile.read_text())
                status = Path(f'/proc/{descendant}/stat')
                # The leader has exited. Give the signaled descendant time to
                # finish exiting or be reaped before sampling its final state.
                deadline = time.monotonic() + 2
                while True:
                    try:
                        if status.read_text().split()[2] == 'Z':
                            break
                    except (FileNotFoundError, ProcessLookupError):
                        break
                    self.assertLess(time.monotonic(), deadline, 'signaled descendant is still running')
                    time.sleep(0.01)
            finally:
                if process.poll() is None:
                    runner.stop(process)
        if self.work_root:
            shutil.copytree(root, self.root / 'retained-runner-attempts')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--work-root', type=Path)
    args, rest = parser.parse_known_args()
    Controls.work_root = args.work_root
    started = time.monotonic()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Controls)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(BrowserIdentityControls))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.receipt:
        generate.write_new(args.receipt, dict(status='passed' if result.wasSuccessful() else 'failed',
            tests=result.testsRun, fixture_bytes=Controls.fixture_bytes, retained_root=str(Controls.root) if args.work_root else None, seconds=time.monotonic() - started,
            scope='tiny synthetic verifier/runner controls; no frozen-product/browser integration'))
    raise SystemExit(0 if result.wasSuccessful() else 1)
