"""Fake controller controls and explicitly selected native lifecycle components.

All fixtures <=137 rows. Raw mutation reasons/partial files are retained under
the explicitly supplied fresh scratch directory, including failed test runs.
"""
import argparse
import copy
from contextlib import nullcontext
import hashlib
import importlib.util
import io
import json
import os
import queue
import stat
import subprocess
from pathlib import Path
import sys
import threading
import time
import traceback
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
_LIFECYCLE_MODES = {'--native-lifecycle-faults','--native-lifecycle-owner',
                    '--native-lifecycle-caretaker','--native-lifecycle-worker','--native-lifecycle-descendant','--native-lifecycle-audit'}
_SELECTED_MODES = _LIFECYCLE_MODES | {'--native-job-exit-compare','--native-job-transition-compare','--native-job-exit-audit'}
_SELECTED_SCRIPTS = (Path(sys.argv[2])/'scripts' if len(sys.argv)>2 and sys.argv[1] in _SELECTED_MODES
                     else Path(__file__).resolve().parent)
if len(sys.argv)>2 and sys.argv[1] in _SELECTED_MODES:
    sys.path.insert(0,str(_SELECTED_SCRIPTS))
from scale_acceptance import generate
from scale_acceptance import native_scale_control as control
from scale_acceptance import native_scale_identity as identity
from scale_acceptance import native_scale_host as host
from scale_acceptance import native_scale_monitor as monitor
from scale_acceptance.native_scale_fixture import checkpoint
from scale_acceptance._native_file import _allocated_bytes
from scale_acceptance.verify import read_json, sha256

spec = importlib.util.spec_from_file_location('native_controller', _SELECTED_SCRIPTS/'native-scale-runner.py')
controller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(controller)


class Controls(unittest.TestCase):
    root = None

    def setUp(self):
        self.work = self.root/self.id().split('.')[-1]
        self.work.mkdir()
        self.failures = []
        self.runtime_discovery = identity.runtime_requirements
        self.runtime_patch = patch.object(identity, 'runtime_requirements',
            return_value=({self.work/'artifacts/runtime'}, {self.work/'artifacts/loader'}))
        self.runtime_patch.start()
        self.monitor_lineage_patch = patch.object(monitor, 'Lineage', return_value=None)
        self.monitor_lineage_patch.start()
        self.addCleanup(self.monitor_lineage_patch.stop)
        self.addCleanup(self.runtime_patch.stop)

    def test_retention_keeps_the_original_lock_after_reporting_and_wait_errors(self):
        driver = """
import sys
from pathlib import Path
from scale_acceptance import owner_retention
from scale_acceptance.native_scale_host import module

root = Path(sys.argv[1])
ci = module('local-ci')
ci.host_lock_path = lambda: root / 'original.lock'
sleep = owner_retention.time.sleep
interrupted = False

def report():
    with (root / 'report-attempts').open('a') as output:
        output.write('attempted\\n')
    raise OSError('diagnostic write failed')

def wait(seconds):
    global interrupted
    if not interrupted:
        interrupted = True
        raise KeyboardInterrupt
    (root / 'waiting').touch()
    sleep(seconds)

with ci.host_lock():
    owner_retention.time.sleep = wait
    owner_retention.retain_owner(report)
"""
        lock = self.work / 'original.lock'
        lock.touch()
        original = lock.stat()
        ci = host.module('local-ci')
        with (self.work / 'owner-stderr.log').open('wb') as stderr:
            owner = subprocess.Popen([sys.executable, '-B', '-c', driver, str(self.work)],
                                     cwd=host.HERE, stderr=stderr)
            try:
                deadline = time.monotonic() + 5
                while not (self.work / 'waiting').is_file():
                    self.assertIsNone(owner.poll(), 'retention owner exited before it could wait')
                    self.assertLess(time.monotonic(), deadline, 'retention owner did not enter the wait')
                    time.sleep(.02)
                self.assertEqual((self.work / 'report-attempts').read_text(), 'attempted\n')
                with patch.object(ci, 'host_lock_path', return_value=lock):
                    with self.assertRaisesRegex(ValueError, 'Cannot acquire host lock'), ci.host_lock():
                        self.fail('another owner took the original lock')
                self.assertTrue(os.path.samestat(original, lock.stat()))
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.wait(timeout=5)
        # The probe owns the test process and may stop it administratively.
        with patch.object(ci, 'host_lock_path', return_value=lock), ci.host_lock():
            self.assertTrue(os.path.samestat(original, lock.stat()))

    def tearDown(self):
        control.create(self.work/'raw-negative-controls.json', self.failures)

    def deny(self, action, contains=None):
        try:
            action()
        except (ValueError, OSError, KeyError) as error:
            self.failures.append(dict(error=repr(error), expected=contains))
            if contains:
                self.assertIn(contains, str(error))
        else:
            self.fail('mutation was accepted')

    def fixture(self, shape='D'):
        data = self.work/shape
        generate.prepare(data, shape, 'native', 127 if shape == 'D' else 137)
        return data, read_json(data/'fixture.json')

    def plan(self):
        product, harness, artifacts, data, campaign = [self.work/name for name in ('product', 'harness', 'artifacts', 'data', 'campaign')]
        for p in (product, harness, artifacts, data, campaign):
            p.mkdir()
        for root in (product, harness):
            (root/'source.py').write_text('frozen source')
            (root/'.git').mkdir()
            (root/'.git/HEAD').write_text('a'*40+'\n')  # Synthetic detached HEAD; no Git command runs.
        (artifacts/'runtime').mkdir()
        (artifacts/'runtime/stdlib.py').write_text('fake stdlib')
        (artifacts/'loader').write_text('fake loaded image')
        external = artifacts/'tool'
        external.write_text('fake executable/proof bytes')
        item = dict(path=str(external), sha256=sha256(external))
        group = lambda p: dict(root=str(p), commit='c'*40, tree='d'*40, sha256={'source.py': sha256(p/'source.py')})
        # Policy fixtures simulate Linux; actual Windows admission has its own builder.
        return dict(schema='native-scale-v1', limits=control.LIMITS.copy(), actions_enabled=True, parent_scheduled=True,
                    selected639_lineage=dict(path=identity.LINEAGE_PATH, sha256=identity.LINEAGE_SHA),
                    os='Linux', host={**identity.host(), 'os':'Linux'}, features=[], campaign=str(self.work/'campaign'),
                    owned_root=str(data), owned_roots=[str(data), str(campaign)], product=group(product), harness=group(harness),
                    reservation=dict(id='test-host-reservation', owner='parent', os='Linux', lock_path=str(self.work/'local-ci.lock')),
                    source_reservation=dict(id='source-capacity', owner='parent', roots=list(map(str, (product, harness, artifacts))), bytes=1024**2),
                    volumes=[dict(path=str(self.work), device=str(self.work.stat().st_dev))],
                    fixtures={s: control.native_recipe(s) for s in ('D', 'G')}, peers={},
                    python=item, executable=item, package_receipt=item, package=item, build_proof=item, tools=[item],
                    dependencies=[dict(root=str(artifacts), inputs=['runtime', 'loader'],
                        sha256={n: sha256(artifacts/n) for n in ('runtime/stdlib.py', 'loader')})])

    def host_plan(self):
        plan = self.plan()
        observed = identity.host()
        plan.update(os=observed['os'], host=observed)
        plan['reservation']['os'] = observed['os']
        return plan

    def tiny_recipe(self, meta):
        # Only injected unit-control commitments; validate(plan) rejects these.
        recipe = control.native_recipe(meta['shape'])
        recipe.update({k: v for k, v in meta.items() if k != 'sha256'})
        return recipe

    def bound_run(self, data, meta):
        plan = dict(os='Linux', fixtures={meta['shape']: self.tiny_recipe(meta)})
        checked = checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta))
        control.create(data/'checkpoint.json', checked)
        payload = dict(slot='Linux'+meta['shape'], checkpoint=checked, input_sha256=checked['sha256'],
                       actual={str(data/n): dict(stat=identity.stamp(data/n), sha256=sha256(data/n))
                               for n in ('job.json', 'fixture.json', 'checkpoint.json')})
        operation = dict(shape=meta['shape'], stage='Run', data=str(data), plan_sha256='c'*64)
        return plan, operation, payload

    def approve_run(self, operation, payload, name='Run'):
        proposal, approval = self.work/(name+'-proposal.json'), self.work/(name+'-approved.json')
        control.proposal(proposal, 'Run', operation['plan_sha256'], payload)
        control.approve(proposal, approval, sha256(proposal))
        return dict(operation, proposal=str(proposal), approval=str(approval), proposal_sha256=sha256(proposal))

    def adoption_fixture(self):
        p = self.plan()
        old, meta = self.fixture()
        control.create(old/'checkpoint.json', checkpoint(old/'job.json', old/'fixture.json', self.tiny_recipe(meta)))
        history = self.work/'old-campaign'
        history.mkdir()
        def item(file):
            s = file.stat()
            return dict(path=str(file), sha256=sha256(file), stat=dict(dev=s.st_dev, ino=s.st_ino,
                        size=s.st_size, mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns, mode=s.st_mode, nlink=s.st_nlink))
        def directory(file):
            value = item_stat(file)
            return dict(path=str(file), stat=value)
        def item_stat(file):
            s = file.stat()
            return dict(dev=s.st_dev, ino=s.st_ino, size=s.st_size, mtime_ns=s.st_mtime_ns,
                        ctime_ns=s.st_ctime_ns, mode=s.st_mode, nlink=s.st_nlink)
        oldplan = self.work/'old-plan.json'
        control.create(oldplan, dict(historical=True))
        control.create(history/'Linux-started.json', dict(started=0, plan_sha256=sha256(oldplan)))
        control.create(history/'session-result.json', dict(passed=False, error='source freeze drift'))
        custody = self.work/'custody.json'
        control.create(custody, dict(old_plan_sha256=sha256(oldplan), original_lock_available_and_released=True,
                       processes=[dict(pid_absent=True)], owned_cgroup_census=[dict(pids=[])]))
        log = self.work/'old-capacity.jsonl'
        log.write_text('synthetic retained capacity evidence\n')
        baseline = {}
        source_history = self.work/'old-source'
        source_history.mkdir()
        (source_history/'retained').write_bytes(b'old source bytes')
        for pool, roots in (('native', [old, history]), ('source', [source_history])):
            entries = []
            for root in roots:
                for file in root.rglob('*'):
                    if file.is_file():
                        s = file.stat()
                        entries.append(dict(path=str(file), stat=item_stat(file), charge_bytes=max(s.st_size, _allocated_bytes(file, s))))
            count = sum(e['charge_bytes'] for e in entries)
            b = self.work/(pool+'-baseline.json')
            control.create(b, dict(entries=entries, sum_bytes=count, roots=[directory(r) for r in roots]))
            baseline[pool] = dict(**item(b), retained_roots=[directory(r) for r in roots],
                       entry_count=len(entries), sum_bytes=count, prior_sampled_aggregate_highwater_bytes=count+8192,
                       carry_bytes=count+8192, capacity_log=item(log))
        baseline['source_reservation_bytes'] = p['source_reservation']['bytes']
        ledger = self.work/'family'
        p['owned_roots'] += [str(ledger), str(old), str(history)]
        p['source_reservation']['roots'].append(str(source_history))
        stat_artifact = self.work/'stat-only-artifact'
        stat_artifact.write_bytes(b'synthetic stat-only commitment')
        v = dict(schema='selected639-lineage-v1', selected_product=dict(commit=identity.PRODUCT,
                 artifacts=[dict(path=str(stat_artifact), stat=item_stat(stat_artifact), expected_sha256='d'*64)]),
                 current=dict(campaign=p['campaign'], linux_os_root=p['owned_root'],
                              canonical_slot_ledger=str(ledger), windows_os_root='C:\\never-start'),
                 old_plan=item(oldplan), old_campaign=str(history), prior_generation_ms=324064,
                 prior_storage=dict(Linux=baseline, Windows=dict(admission='deferred', may_start=False)),
                 parent_custody=item(custody),
                 prior_records=dict(original_start=item(history/'Linux-started.json'),
                                    original_result=item(history/'session-result.json')),
                 prior_absence=dict(observed_campaign_entries=sorted(f.name for f in history.iterdir()), completion_seals=[dict(path=str(history/'Linux-completed.json'))],
                    slots=[{key: dict(path=str(history/(slot+'-'+key+'.json'))) for key in ('consumed', 'verified')}
                           for slot in control.SLOTS]),
                 adopt_linux_d=dict(data_directory=str(old), data_directory_stat=item_stat(old),
                    original_entries=sorted(f.name for f in old.iterdir()),
                    input=dict(path=str(old/'input.csv'), stat=item_stat(old/'input.csv'), expected_sha256=meta['sha256']),
                    **{key: item(old/(key+'.json')) for key in ('job', 'fixture', 'checkpoint')}))
        descriptor = self.work/'lineage.json'
        control.create(descriptor, v)
        p['selected639_lineage'] = dict(path=str(descriptor), sha256=sha256(descriptor))
        p['fixtures']['D'] = self.tiny_recipe(meta)
        for target, name, value in ((identity, 'LINEAGE_PATH', str(descriptor)), (identity, 'LINEAGE_SHA', sha256(descriptor)),
                                    (control, 'LINEAGE_PATH', str(descriptor)), (control, 'LINEAGE_SHA', sha256(descriptor)),
                                    (controller, 'LINEAGE_SHA', sha256(descriptor))):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        data = Path(p['owned_root'])/'D-data'
        proposal, approval = self.work/'adopt-proposal.json', self.work/'adopt-approved.json'
        control.proposal(proposal, 'checkpoint-adoption', 'c'*64, controller.adoption_payload(p, data))
        op = dict(stage='checkpoint-adoption', shape='D', data=str(data), proposal=str(proposal),
                  approval=str(approval), proposal_sha256=sha256(proposal), plan_sha256='c'*64)
        return p, v, op

    def test_adoption_new_approval_and_no_generator_or_copy(self):
        p, v, op = self.adoption_fixture()
        old = Path(v['adopt_linux_d']['data_directory'])
        before = {f: f.read_bytes() for f in old.iterdir() if f.is_file()}
        with patch.object(generate, 'prepare') as generator, patch.object(controller, 'checkpoint', wraps=checkpoint) as reader, \
                patch('shutil.copyfile') as copier:
            self.deny(lambda: controller.phase(p, op), 'NEW checkpoint-adoption')
            reader.assert_not_called()
            for stage, plan_sha in (('generation', 'c'*64), ('checkpoint-adoption', 'd'*64), ('Run', 'c'*64)):
                bad = self.work/(stage+'-'+plan_sha[:1]+'.json')
                control.proposal(bad, stage, plan_sha, controller.adoption_payload(p, op['data']))
                approval = bad.with_suffix('.approved')
                control.approve(bad, approval, sha256(bad))
                altered = dict(op, proposal=str(bad), approval=str(approval), proposal_sha256=sha256(bad))
                self.deny(lambda: controller.phase(p, altered), 'stage/plan/payload')
            reader.assert_not_called()
            control.approve(op['proposal'], op['approval'], op['proposal_sha256'])
            controller.phase(p, op)
            generator.assert_not_called()
            copier.assert_not_called()
        data = Path(op['data'])
        self.assertEqual({f.name for f in data.iterdir()}, {'job.json', 'fixture.json', 'checkpoint.json', 'temp'})
        self.assertEqual(read_json(data/'job.json')['input'], str(old/'input.csv'))
        self.assertEqual(read_json(data/'job.json')['output'], str(data/'output'))
        self.assertEqual(before, {f: f.read_bytes() for f in before})
        self.assertEqual(controller.actual_checkpoint(p, 'D', data), read_json(old/'checkpoint.json'))
        execution = controller.runner_plan(p, op, self.work/'plan.json', self.work/'op.json', self.work/'worker')
        step = execution['steps'][0]
        self.assertEqual(step['timeout_seconds'], 3275.936)
        self.assertNotIn(str((old/'input.csv').relative_to(execution['root'])), step['inputs'])
        self.assertEqual(len(step['artifacts']), 3)
        self.assertIn('-B', step['argv'])
        self.deny(lambda: controller.phase(p, dict(op, stage='generation')), 'regeneration forbidden')

    def test_matched_stale_operation_and_approval_reject_actual_plan_before_source_access(self):
        plan, _, op = self.adoption_fixture()
        actual = self.work/'actual-plan.json'
        other = self.work/'other-plan.json'
        control.create(actual, plan)
        changed = copy.deepcopy(plan)
        changed['reservation']['id'] += '-other'
        control.create(other, changed)
        stale_proposal = self.work/'other-adoption.json'
        stale_approval = self.work/'other-adoption-approved.json'
        control.proposal(stale_proposal, 'checkpoint-adoption', sha256(other),
                         controller.adoption_payload(plan, op['data']))
        control.approve(stale_proposal, stale_approval, sha256(stale_proposal))
        stale = dict(op, plan_sha256=sha256(other), proposal=str(stale_proposal),
                     approval=str(stale_approval), proposal_sha256=sha256(stale_proposal))
        # The stale pair agrees internally; actual plan admission must still deny it.
        controller.adoption_binding(plan, stale)
        operation = self.work/'stale-operation.json'
        control.create(operation, stale)
        self.deny(lambda: controller.operation_plan_binding(actual, stale), 'actual plan')
        controller.operation_plan_binding(other, stale)
        with patch.object(sys, 'argv', ['native-scale-runner.py', '_phase', str(actual), str(operation)]), \
                patch.dict(os.environ, CHOPPER_NATIVE_PHASE_PLAN_SHA256=sha256(actual),
                           CHOPPER_NATIVE_PHASE_OPERATION_SHA256=sha256(operation)), \
                patch.object(controller, 'validate') as validate, \
                patch.object(controller, 'phase') as phase, \
                patch.object(controller, 'checkpoint') as source:
            self.deny(controller.main, 'actual plan')
            validate.assert_not_called()
            phase.assert_not_called()
            source.assert_not_called()

    def test_adoption_corruption_inode_ancestor_and_metadata_drift(self):
        p, v, op = self.adoption_fixture()
        control.approve(op['proposal'], op['approval'], op['proposal_sha256'])
        source = Path(v['adopt_linux_d']['input']['path'])
        # Isolate the streaming oracle from stat admission: same-size bad bytes
        # must still fail even when an attacker could forge a stat result.
        raw = source.read_bytes()
        source.write_bytes(raw[:110]+b'x'+raw[111:])
        with patch.object(identity, 'sealed_stat', side_effect=lambda item: Path(item['path'])):
            self.deny(lambda: controller.phase(p, op))
        self.assertFalse(Path(op['data']).exists())
        self.deny(lambda: identity.Lineage(p), 'sealed stat')
        source.unlink()
        source.write_bytes(raw)
        self.deny(lambda: identity.Lineage(p), 'sealed stat')
        ancestor = source.parent
        original_is_symlink = Path.is_symlink
        # Model the ancestor observation without requiring Windows link privilege.
        with patch.object(Path, 'is_symlink', lambda q: q == ancestor or original_is_symlink(q)):
            self.deny(lambda: identity.Lineage(p), 'nonsymlink')
        self.assertFalse(Path(op['data']).exists())

    def test_adoption_original_metadata_mutation_during_checkpoint(self):
        p, v, op = self.adoption_fixture()
        control.approve(op['proposal'], op['approval'], op['proposal_sha256'])
        original = controller.report_progress
        def mutate(phase, rows):
            original(phase, rows)
            with Path(v['adopt_linux_d']['fixture']['path']).open('a') as stream:
                stream.write(' ')
        with patch.object(controller, 'report_progress', side_effect=mutate):
            self.deny(lambda: controller.phase(p, op), 'drift')
        self.assertFalse(Path(op['data']).exists())

    def test_adoption_stat_only_sealed_artifact_is_watched_without_hashing(self):
        p, v, _ = self.adoption_fixture()
        lineage = identity.Lineage(p)
        artifact = Path(v['selected_product']['artifacts'][0]['path'])
        artifact.write_bytes(b'changed stat-only artifact')
        self.deny(lineage.check, 'metadata drift')
        self.deny(lambda: identity.Lineage(p), 'sealed stat')

    def test_adoption_lineage_authority_carry_debit_and_clock(self):
        p, v, _ = self.adoption_fixture()
        lineage = identity.Lineage(p)
        for key, value in (('owned_root', str(self.work/'another-root')), ('campaign', str(self.work/'another-campaign')),
                           ('selected639_lineage', dict(path=p['selected639_lineage']['path'], sha256='0'*64)),
                           ('owned_roots', [p['owned_root']]), ('source_reservation', dict(bytes=0, roots=[]))):
            self.deny(lambda: identity.Lineage({**p, key: value}))
        tick = [100.]
        c = control.Campaign(self.work/'new-clock', 'Linux', 'c'*64, lambda: tick[0], lambda: tick[0], lineage=lineage)
        tick[0] += 28800-324.064-.001
        c.check()
        tick[0] += .002
        self.deny(c.check, 'clock')
        self.assertEqual(read_json(c.root/'Linux-started.json')['prior_generation_ms'], 324064)
        descriptor = Path(p['selected639_lineage']['path'])
        for change in ('debit', 'carry', 'history'):
            bad = copy.deepcopy(v)
            if change == 'debit': bad['prior_generation_ms'] = 0
            if change == 'carry': bad['prior_storage']['Linux']['native']['carry_bytes'] = 0
            if change == 'history': bad['prior_records'].clear()
            descriptor.write_text(json.dumps(bad))
            self.deny(lambda: identity.Lineage(p), 'SHA mismatch')

    @unittest.skipIf(os.name == 'nt', 'canonical writer is Linux only')
    def test_canonical_claim_exclusion_partial_and_crash_burn(self):
        p, v, _ = self.adoption_fixture()
        lineage = identity.Lineage(p)
        ledger = Path(v['current']['canonical_slot_ledger'])
        results = []
        def contender():
            try: results.append(control.canonical_claim(lineage, 'LinuxD', dict(actual='approved-run'), lambda: None))
            except (OSError, ValueError) as error: self.failures.append(dict(race=str(error)))
        threads = [threading.Thread(target=contender) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(results), 1)
        self.deny(lambda: control.canonical_claim(lineage, 'LinuxD', {}, lambda: None), 'consumed')
        for content in ('', '{partial', '{}'):
            results[0].write_text(content)
            self.deny(lambda: control.canonical_claim(lineage, 'LinuxD', {}, lambda: None), 'consumed')
        c = control.Campaign(Path(p['campaign'])/'clock', 'Linux', 'c'*64, lineage=lineage)
        self.deny(lambda: c.consume('LinuxD', self.work/'adopt-proposal.json', results[0]))
        self.assertFalse((c.root/'LinuxD-consumed.json').exists())
        # Crash after fsync: canonical bytes survive and local absence grants nothing.
        self.assertTrue((ledger/'LinuxD-consumed.json').exists())
        (Path(v['old_campaign'])/'LinuxD-consumed.json').write_text('')
        self.deny(lambda: lineage.check(), 'old consumed')

    @unittest.skipIf(os.name == 'nt', 'canonical writer is Linux only')
    def test_public_claim_actual_run_authority_and_irreversible_local_consumption(self):
        p, v, op = self.adoption_fixture()
        control.approve(op['proposal'], op['approval'], op['proposal_sha256'])
        controller.phase(p, op)
        plan_file = self.work/'new-plan.json'
        control.create(plan_file, p)
        plan_sha = sha256(plan_file)
        lineage = identity.Lineage(p)
        campaign = control.Campaign(p['campaign'], 'Linux', plan_sha, lineage=lineage)
        root, data = Path(p['owned_root']), Path(op['data'])
        lockfile = Path(p['reservation']['lock_path'])
        lockfile.write_text('fake held lock inode')
        held = dict(path=str(lockfile), stat=identity.stamp(lockfile), mechanism='flock-exclusive', owner_pid=12345)
        authority = root/'reservation.json'
        control.create(authority, dict(actual_lock=held, plan=p['reservation'], owner_start_ticks='123'))
        sample = dict(sample_started_unix=control.time.time(), sampled_unix=control.time.time(), reservation=held, owned_sampled_highwater=100000, source_sampled_highwater=10000)
        (root/'capacity.jsonl').write_text(json.dumps(sample)+'\n')
        actual = controller.actual_checkpoint(p, 'D', data)
        source = Path(v['adopt_linux_d']['input']['path'])
        proposal, approval = root/'D-Run-proposal.json', root/'D-Run-approved.json'
        payload = dict(slot='LinuxD', checkpoint=actual, input_sha256=actual['sha256'],
                       actual={str(data/n): dict(stat=identity.stamp(data/n), sha256=sha256(data/n))
                               for n in ('job.json', 'fixture.json', 'checkpoint.json')},
                       source=dict(path=str(source), stat=identity.stamp(source)), lineage_sha256=identity.LINEAGE_SHA,
                       executable=p['executable'], python=p['python'], tools=p['tools'], limits=control.LIMITS,
                       source_roles=dict(product=p['product'], harness=p['harness']), peer={}, reservation=held,
                       session_authority=dict(start_sha256=sha256(Path(p['campaign'])/'Linux-started.json'),
                                              reservation_sha256=sha256(authority)))
        control.proposal(proposal, 'Run', plan_sha, payload)
        s = lockfile.stat()
        kernel = f'1: FLOCK ADVISORY WRITE 12345 {os.major(s.st_dev):02x}:{os.minor(s.st_dev):02x}:{s.st_ino} 0 EOF\n'
        def fake_path(*parts):
            file = Path(*parts)
            if str(file) == '/proc/locks': return SimpleNamespace(read_text=lambda: kernel)
            if str(file) == '/proc/12345/stat': return SimpleNamespace(read_text=lambda: '12345 (fake owner) '+' '.join(['0']*19+['123']))
            return file
        with patch.object(controller, 'validate') as validation, patch.object(controller, 'Path', side_effect=fake_path), \
                patch.object(controller, 'HostLock') as host_lock:
            self.deny(lambda: controller.claim_run(plan_file, plan_sha, proposal), 'approval')
            self.assertFalse(Path(v['current']['canonical_slot_ledger']).exists())
            control.approve(proposal, approval, sha256(proposal))
            (root/'capacity.jsonl').write_text(json.dumps({**sample, 'sample_started_unix': 0})+'\n')
            self.deny(lambda: controller.claim_run(plan_file, plan_sha, proposal), 'sample stale')
            self.assertFalse(Path(v['current']['canonical_slot_ledger']).exists())
            (root/'capacity.jsonl').write_text(json.dumps(sample)+'\n')
            claim = controller.claim_run(plan_file, plan_sha, proposal)
            validation.assert_called_with(p)
            host_lock.assert_not_called()
            self.assertFalse((Path(p['campaign'])/'LinuxD-consumed.json').exists())
            # Crash before local consume burns the canonical slot forever.
            self.deny(lambda: controller.claim_run(plan_file, plan_sha, proposal), 'consumed')
            campaign.consume('LinuxD', proposal, claim)
            self.deny(lambda: campaign.consume('LinuxD', proposal, claim))
        operation = dict(stage='Run', shape='D', data=str(data), proposal=str(proposal), approval=str(approval),
                         proposal_sha256=sha256(proposal), plan_sha256=plan_sha, claim_sha256=sha256(claim))
        controller.run_binding(p, operation)
        execution = controller.runner_plan(p, operation, plan_file, self.work/'run-op.json', self.work/'run-worker')
        source_name = str(source.relative_to(execution['root']))
        self.assertIn(source_name, execution['steps'][0]['inputs'])
        attempt = dict(runtime=dict(executable=p['executable']['path'], executable_sha256=p['executable']['sha256']),
                       inputs={str(Path(name).relative_to(execution['root'])): dict(sha256=value['sha256'])
                               for name, value in payload['actual'].items()})
        attempt['inputs'][source_name] = dict(sha256=actual['sha256'])
        controller.check_run_inputs(attempt, execution['root'], operation, p, payload)
        attempt['inputs'][source_name]['sha256'] = '0'*64
        self.deny(lambda: controller.check_run_inputs(attempt, execution['root'], operation, p, payload), 'input SHA')
        self.deny(lambda: controller.run_binding(p, {**operation, 'claim_sha256': '0'*64}), 'claim drift')
        # Partial local bytes never give another claim or a runnable binding.
        (Path(p['campaign'])/'LinuxD-consumed.json').write_text('{partial')
        self.deny(lambda: controller.run_binding(p, operation))
        self.assertTrue(claim.exists())

    def test_adoption_storage_carry_no_refund_or_input_double_charge(self):
        p, v, _ = self.adoption_fixture()
        lineage = identity.Lineage(p)
        prior = v['prior_storage']['Linux']['native']
        roots = [Path(r['path']) for r in prior['retained_roots']]
        storage = monitor.Storage(lineage.baselines['native'], prior)
        self.assertEqual(storage.sample(roots), prior['carry_bytes'])
        source = Path(v['adopt_linux_d']['input']['path'])
        original = source.read_bytes()
        with source.open('ab') as stream: stream.write(b'x'*8192)
        grown = storage.sample(roots)
        self.assertGreater(grown, prior['carry_bytes'])
        source.write_bytes(b'')
        self.assertEqual(storage.sample(roots), grown)
        # Retain the old identity outside observed roots: Windows cannot unlink
        # an open file, and retaining it prevents file-ID reuse in this oracle.
        source.rename(self.work/'retired-input.csv')
        self.assertEqual(storage.sample(roots), grown)
        source.write_bytes(original)
        replaced = storage.sample(roots)
        self.assertGreater(replaced, grown)
        extra = source.with_name('extra')
        extra.write_bytes(b'new allocation')
        self.assertGreater(storage.sample(roots), replaced)
        self.deny(lambda: monitor.Storage(lineage.baselines['native'], prior), 'sealed stat')
        self.deny(lambda: monitor.Storage(lineage.baselines['source'], {**v['prior_storage']['Linux']['source'], 'carry_bytes': 0}), 'carry')

    def test_retained_storage_admission_queries_each_file_once(self):
        plan, value, _ = self.adoption_fixture()
        lineage = identity.Lineage(plan)
        baseline = lineage.baselines['source']
        prior = value['prior_storage']['Linux']['source']
        with patch.object(monitor, '_allocated_bytes', wraps=_allocated_bytes) as sampled, \
             patch.object(identity, '_allocated_bytes', wraps=_allocated_bytes) as sealed:
            storage = monitor.Storage(baseline, prior)
        self.assertEqual(sampled.call_count+sealed.call_count, len(baseline['entries']))
        self.assertEqual(storage.sample([Path(r['path']) for r in baseline['roots']]), prior['carry_bytes'])

    def test_retained_storage_single_census_preserves_all_sealed_fields_and_charge(self):
        plan, value, _ = self.adoption_fixture()
        lineage = identity.Lineage(plan)
        baseline = lineage.baselines['source']
        prior = value['prior_storage']['Linux']['source']
        item = baseline['entries'][0]
        file = Path(item['path'])
        item['stat'] = identity.stat_fields(file.stat(), _allocated_bytes(file, file.stat()))
        monitor.Storage(baseline, prior)
        for field in item['stat']:
            with self.subTest(field=field):
                changed = copy.deepcopy(baseline)
                changed['entries'][0]['stat'][field] += 1
                self.deny(lambda: monitor.Storage(changed, prior), 'sealed stat')
        changed = copy.deepcopy(baseline)
        changed['entries'][0]['charge_bytes'] += 1
        changed['sum_bytes'] += 1
        counters = {**prior, 'sum_bytes': changed['sum_bytes']}
        self.deny(lambda: monitor.Storage(changed, counters), 'baseline charge')
        with patch.object(monitor, '_allocated_bytes', return_value=item['stat']['allocated_bytes']+4096):
            self.deny(lambda: monitor.Storage(baseline, prior), 'sealed stat')

    def windows_sampler_paths(self):
        class NativePath(type(Path())):
            def stat(self, **kwargs):
                value = super().stat(**kwargs)
                fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_nlink', 'st_blocks')
                return SimpleNamespace(**{name:getattr(value, name, 0) for name in fields}, st_file_attributes=0)
            def lstat(self):
                return self.stat(follow_symlinks=False)
        def walk(root, **kwargs):
            for folder, directories, files in os.walk(root, **kwargs):
                yield folder, sorted(directories), sorted(files)
        return NativePath, SimpleNamespace(name='nt', walk=walk, path=os.path)

    def test_windows_storage_bounds_batches_and_joins_workers_before_return(self):
        native_path, native_os = self.windows_sampler_paths()
        root = native_path(self.work/'sample')
        root.mkdir()
        for index in range(17):
            (root/str(index)).write_bytes(b'x')
        executors, calls = [], []
        mutex = threading.Lock()
        active = peak = 0
        real_executor = monitor.ThreadPoolExecutor
        def executor(**kwargs):
            self.assertEqual(kwargs['max_workers'], 8)
            pool = real_executor(**kwargs)
            executors.append(pool)
            return pool
        def allocated(p, observed):
            nonlocal active, peak
            with mutex:
                active += 1
                peak = max(peak, active)
                calls.append(str(p))
            time.sleep(.01)
            with mutex:
                active -= 1
            return 4096
        storage = monitor.Storage()
        with patch.object(monitor, 'os', native_os), patch.object(monitor, 'Path', native_path), \
             patch.object(monitor, '_allocated_bytes', side_effect=allocated), \
             patch.object(monitor, 'ThreadPoolExecutor', side_effect=executor):
            self.assertEqual(storage.sample([root]), 17*4096)
        self.assertEqual(len(calls), 17)
        self.assertGreater(peak, 1)
        self.assertLessEqual(peak, 8)
        self.assertEqual(active, 0)
        self.assertTrue(all(not thread.is_alive() for pool in executors for thread in pool._threads))

    def test_windows_storage_failed_batch_merges_sibling_success_and_stops_submission(self):
        native_path, native_os = self.windows_sampler_paths()
        root = native_path(self.work/'sample')
        root.mkdir()
        for index in range(12):
            (root/('file-'+str(index).zfill(2))).write_bytes(b'x')
        calls = []
        failed = threading.Event()
        def allocated(p, observed):
            calls.append(p.name)
            if p.name == 'file-00':
                failed.set()
                raise OSError('selected allocation failure')
            self.assertTrue(failed.wait(1))
            return 8192
        storage = monitor.Storage(prior=dict(prior_sampled_aggregate_highwater_bytes=1000, carry_bytes=1000))
        with patch.object(monitor, 'os', native_os), patch.object(monitor, 'Path', native_path), \
             patch.object(monitor, '_allocated_bytes', side_effect=allocated):
            self.deny(lambda: storage.sample([root]), 'selected allocation failure')
        self.assertEqual(len(calls), 8)
        self.assertEqual(len(storage.high), 7)
        self.assertEqual(sum(storage.high.values()), 7*8192)
        for file in root.iterdir():
            file.unlink()
        self.assertEqual(storage.sample([root]), 1000+7*8192)

    def test_windows_mutable_storage_reconciles_only_transient_name_races(self):
        native_path, native_os = self.windows_sampler_paths()
        root = native_path(self.work/'sample')
        root.mkdir()
        for index in range(9):
            (root/str(index)).write_bytes(b'x')
        calls = 0
        def walk(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                yield str(root), [], ['owner-sample.tmp']
            else:
                yield str(root), [], sorted(p.name for p in root.iterdir())
        native_os.walk = walk
        storage = monitor.Storage()
        with patch.object(monitor, 'os', native_os), patch.object(monitor, 'Path', native_path), \
                patch.object(monitor, '_allocated_bytes', return_value=4096):
            self.assertEqual(storage.sample([root], mutable_roots=(root,)), 9*4096)
            self.assertEqual(calls, 2)
            calls = 0
            with self.assertRaises(FileNotFoundError):
                storage.sample([root], sealed_entries={}, mutable_roots=(root,))
            self.assertEqual(calls, 1)
            calls = 0
            with self.assertRaises(FileNotFoundError):storage.sample([root])
            calls = 0
            storage.baseline[(str(root/'owner-sample.tmp'), 0, 0)] = 1
            with self.assertRaises(FileNotFoundError):storage.sample([root], mutable_roots=(root,))
            storage.baseline.clear()
        for variant in ('allocation-race', 'reparse', 'baseline-race', 'endless'):
            calls = 0
            first = True
            def allocated(p, observed):
                nonlocal first
                if variant == 'endless' or (p.name == '0' and first):
                    first = False
                    raise FileNotFoundError('observed mutable publication retired')
                if variant == 'baseline-race' and p.name == '1':
                    raise FileNotFoundError('immutable baseline name missing')
                if variant == 'reparse' and p.name == '1':
                    raise ValueError('owned reparse point')
                return 8192
            def steady_walk(*args, **kwargs):
                nonlocal calls
                calls += 1
                yield str(root), [], sorted(p.name for p in root.iterdir())
            native_os.walk = steady_walk
            storage = monitor.Storage()
            if variant == 'baseline-race':
                storage.baseline[(str(root/'1'), 0, 0)] = 0
            with patch.object(monitor, 'os', native_os), patch.object(monitor, 'Path', native_path), \
                    patch.object(monitor, '_allocated_bytes', side_effect=allocated):
                if variant == 'allocation-race':
                    self.assertEqual(storage.sample([root], mutable_roots=(root,)), 9*8192)
                    self.assertEqual(calls, 2)
                elif variant == 'baseline-race':
                    self.deny(lambda: storage.sample([root], mutable_roots=(root,)), 'baseline name')
                    self.assertEqual(calls, 1)
                elif variant == 'reparse':
                    self.deny(lambda: storage.sample([root], mutable_roots=(root,)), 'reparse')
                    self.assertEqual(calls, 1)
                    self.assertGreater(sum(storage.high.values()), 0)
                else:
                    with self.assertRaises(FileNotFoundError):storage.sample([root], mutable_roots=(root,))
                    self.assertEqual(calls, 8)

    def test_typed_mutable_change_preserves_measured_old_new_charges_and_scope(self):
        native_path,native_os=self.windows_sampler_paths()
        root=native_path(self.work/'sample');root.mkdir()
        file=root/'owner-sample.json';file.write_bytes(b'x')
        observed=file.stat()
        opened=SimpleNamespace(**vars(observed));opened.st_ino+=100
        for variant in ('mutable','immutable','baseline','sealed'):
            storage=monitor.Storage();storage.high[(str(file),observed.st_dev,observed.st_ino)]=8192
            if variant=='baseline':storage.baseline[(str(file),observed.st_dev,observed.st_ino)]=8192
            count=0
            def allocated(p,s):
                nonlocal count
                count+=1
                if count==1:raise monitor._AllocationChange(p,((s,0),(opened,16384)))
                return 4096
            with patch.object(monitor,'os',native_os),patch.object(monitor,'Path',native_path), \
                    patch.object(monitor,'_allocated_bytes',side_effect=allocated):
                if variant=='mutable':
                    self.assertEqual(storage.sample([root],mutable_roots=(root,)),24576)
                    self.assertEqual(count,2)
                else:
                    with self.assertRaises(monitor._AllocationChange):
                        storage.sample([root],mutable_roots=(root,) if variant!='immutable' else (),
                                       sealed_entries={} if variant=='sealed' else None)
                    self.assertEqual(count,1)
            if variant!='sealed':self.assertEqual(sum(storage.high.values()),24576)

    def test_allocation_diagnostic_survives_the_real_session_failure_boundary(self):
        values=[SimpleNamespace(st_dev=1,st_ino=2,st_size=n,st_mtime_ns=n,st_ctime_ns=1,
            st_mode=stat.S_IFREG|0o600,st_nlink=1,st_file_attributes=0)for n in (1,2,3)]
        error=monitor._AllocationChange('x'*2000,tuple((value,8192)for value in values),kind='growth',
            query=dict(size=2,allocation=8192,links=1,deleted=False))
        controller.session_failure_record(self.work,error)
        record=read_json(self.work/'session-failure.json')
        for label in ('observed','opened','after'):
            self.assertTrue(any(repr(label) in note for note in record['notes']))
        self.assertTrue(all(len(note)<=1024 for note in record['notes']))
        self.assertTrue(any('allocation_query=' in note for note in record['notes']))

    def test_continuous_checked_growth_is_one_complete_mutable_observation_only(self):
        native_path,native_os=self.windows_sampler_paths()
        root=native_path(self.work/'growth');root.mkdir()
        for i in range(9):(root/str(i)).write_bytes(b'x')
        for variant in ('mutable','immutable','baseline','sealed'):
            storage=monitor.Storage();calls=[]
            if variant=='baseline':storage.baseline[(str(root/'0'),0,0)]=0
            def allocation(p,before):
                calls.append(str(p));after=SimpleNamespace(**vars(before));after.st_size+=1
                raise monitor._AllocationChange(p,((before,0),(after,8192)),kind='growth')
            with patch.object(monitor,'os',native_os),patch.object(monitor,'Path',native_path), \
                    patch.object(monitor,'_allocated_bytes',side_effect=allocation):
                if variant=='mutable':
                    self.assertEqual(storage.sample([root],mutable_roots=(root,)),9*8192)
                    self.assertEqual(len(calls),9)  # No whole-root retry under continuous growth.
                else:
                    with self.assertRaises(ValueError):
                        storage.sample([root],mutable_roots=(root,) if variant!='immutable' else (),
                                       sealed_entries={} if variant=='sealed' else None)
                    self.assertLessEqual(len(calls),8)

    def test_windows_storage_traversal_failure_drains_workers_and_retains_original_owner_while_blocked(self):
        native_path, native_os = self.windows_sampler_paths()
        root = native_path(self.work/'sample')
        root.mkdir()
        for name in ('first', 'second'):
            (root/name).write_bytes(b'x')
        def walk(*args, **kwargs):
            yield str(root), [], ['first', 'second']
            raise OSError('selected walk failure')
        native_os.walk = walk
        gate, started = threading.Event(), threading.Event()
        mutex = threading.Lock()
        workers = []
        def allocated(p, observed):
            with mutex:
                workers.append(threading.current_thread())
                if len(workers) == 2:
                    started.set()
            gate.wait(5)
            return 4096
        storage = monitor.Storage()
        owner = host.HostLock()
        owner.owner = Mock()
        try:
            with patch.object(monitor, 'os', native_os), patch.object(monitor, 'Path', native_path), \
                 patch.object(monitor, '_allocated_bytes', side_effect=allocated):
                self.deny(lambda: host.bounded(lambda: storage.sample([root]), seconds=.05), 'blocked/stale')
                self.assertTrue(started.wait(1))
                self.assertTrue(host.pending_calls())
                with patch.object(host, 'retain_host_lock', side_effect=OSError('original owner retained')):
                    self.deny(lambda: owner.__exit__(None, None, None), 'original owner retained')
                owner.owner.close.assert_not_called()
                gate.set()
                for call in host.pending_calls():
                    call.join(timeout=2)
        finally:
            gate.set()
            for call in host.pending_calls():
                call.join(timeout=2)
        self.assertFalse(host.pending_calls())
        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(sum(storage.high.values()), 8192)

    def test_adoption_monitor_applies_both_carries_and_guards_old_input(self):
        p, v, _ = self.adoption_fixture()
        self.enterContext(patch.object(monitor,'host',return_value=p['host']))
        ledger = Path(v['current']['canonical_slot_ledger'])
        ledger.mkdir()
        lineage = identity.Lineage(p)
        with patch.object(monitor, 'Lineage', return_value=lineage):
            m = monitor.Monitor(p, Mock(), Mock(), self.work/'carry-samples.jsonl')
        m.lock.proof.return_value = dict(fake=True)
        free = Mock(free=201*control.GIB)
        with patch.object(monitor.shutil, 'disk_usage', return_value=free):
            sample = m.sample(start=True)
            self.assertGreaterEqual(sample['owned_sampled_highwater'], v['prior_storage']['Linux']['native']['carry_bytes'])
            self.assertGreaterEqual(sample['source_sampled_highwater'], v['prior_storage']['Linux']['source']['carry_bytes'])
            with patch.dict(m.plan['source_reservation'], bytes=1):
                self.deny(m.sample, 'reservation exceeded')
            with patch.dict(monitor.LIMITS, owned_bytes=1):
                self.deny(m.sample, 'storage high water')
            free.free = 19*control.GIB
            self.deny(m.sample, 'physical free')
            free.free = 201*control.GIB
            oldjob = Path(v['adopt_linux_d']['job']['path'])
            oldjob.write_text(oldjob.read_text()+' ')
            self.deny(m.sample, 'drift')

    def test_windows_adoption_entry_denies_before_start_without_future_proofs(self):
        p, _, _ = self.adoption_fixture()
        for peers in ({}, {'D': dict(plan_sha256='0'*64, source_sha256='0'*64)}):
            bad = {**p, 'os': 'Windows', 'host': {**p['host'], 'os': 'Windows'}, 'peers': peers}
            file = self.work/('windows-'+str(len(peers))+'.json')
            control.create(file, bad)
            with patch.object(controller, 'HostLock') as lock, patch.object(controller, 'Campaign') as campaign:
                self.deny(lambda: controller.session(file, sha256(file)), 'Windows admission deferred')
                lock.assert_not_called()
                campaign.assert_not_called()
        self.assertFalse((Path(p['campaign'])/'Windows-started.json').exists())

    def test_exact_recipe_without_prior_digest_and_optional_additional_digest(self):
        packet = read_json(Path(__file__).parent/'scale_acceptance/native-plan.DISABLED.example.json')
        self.assertEqual(packet['fixtures'], {s: control.native_recipe(s) for s in ('D', 'G')})
        self.deny(lambda: control.validate(packet), 'actions disabled')
        plan = self.plan()
        plan['host']['os'] = 'Linux'
        control.validate(plan)
        for key, value in (('generator', 'unknown'), ('shape', 'G'), ('width', 1000),
                           ('rows', 127), ('bytes', 12800), ('tiny', True), ('tiny', 0),
                           ('job', {**plan['fixtures']['D']['job'], 'seed': 'other'}),
                           ('job', {**plan['fixtures']['D']['job'], 'version': True}),
                           ('sha256', None), ('sha256', 'unknown')):
            bad = copy.deepcopy(plan)
            bad['fixtures']['D'][key] = value
            self.deny(lambda: control.validate(bad))
        for key in plan['fixtures']['D']:
            bad = copy.deepcopy(plan)
            del bad['fixtures']['D'][key]
            self.deny(lambda: control.validate(bad))
        plan['fixtures']['D']['sha256'] = 'a'*64
        control.validate(plan)
        windows = copy.deepcopy(plan)
        del windows['fixtures']['D']['sha256']
        windows.update(os='Windows', host={**windows['host'], 'os': 'Windows'},
                       reservation={**windows['reservation'], 'os': 'Windows'},
                       peers={s: dict(slot='Linux'+s, sha256='b'*64, source_sha256='a'*64,
                                      plan_sha256='c'*64) for s in ('D', 'G')})
        self.deny(lambda: control.validate(windows), 'Windows admission deferred')
        windows['peers']['D']['source_sha256'] = 'missing'
        self.deny(lambda: control.validate(windows), 'Windows admission deferred')
        data, meta = self.fixture()
        self.assertEqual(checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta))['sha256'], meta['sha256'])
        self.deny(lambda: checkpoint(data/'job.json', data/'fixture.json', control.native_recipe('D')), 'dimensions')
        self.assertEqual(checkpoint(data/'job.json', data/'fixture.json',
                         {**self.tiny_recipe(meta), 'sha256': meta['sha256']})['sha256'], meta['sha256'])

    def test_metadata_hash_never_substitutes_for_literal_header_or_order_checks(self):
        import hashlib
        data, meta = self.fixture()
        source, fixture = data/'input.csv', data/'fixture.json'
        original = source.read_bytes()
        for i, raw in enumerate((b'X'+original[1:], original[:118]+b'x'+original[119:],
                                 original[:100]+original[200:300]+original[100:200]+original[300:])):
            source.write_bytes(raw)
            fixture.write_text(json.dumps({**meta, 'sha256': hashlib.sha256(raw).hexdigest()}))
            self.deny(lambda: checkpoint(data/'job.json', fixture, self.tiny_recipe(meta)))
            (self.work/f'forged-literal-{i}.csv').write_bytes(raw)
        source.write_bytes(original)
        fixture.write_text(json.dumps({**meta, 'sha256': '0'*64}))
        self.deny(lambda: checkpoint(data/'job.json', fixture, self.tiny_recipe(meta)), 'metadata')

    def test_checkpoint_rejects_source_identity_change_during_scan(self):
        data, meta = self.fixture()
        source = data/'input.csv'
        def change(_):
            with source.open('ab') as stream:
                stream.write(b'x')
                stream.truncate(meta['bytes'])
            current = source.stat()
            os.utime(source, ns=(current.st_atime_ns, current.st_mtime_ns+1_000_000_000))
        self.deny(lambda: checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta), change),
                  'changed during checkpoint')

    def test_actual_run_approval_rejects_missing_stale_forged_and_changed_bindings(self):
        data, meta = self.fixture()
        plan, operation, payload = self.bound_run(data, meta)
        op = self.approve_run(operation, payload)
        self.assertEqual(controller.run_binding(plan, op)['input_sha256'], meta['sha256'])
        for i, fields in enumerate((dict(input_sha256='0'*64),
                                   dict(checkpoint={**payload['checkpoint'], 'sha256': '0'*64}),
                                   dict(actual={}), dict(slot='LinuxG'))):
            bad = self.approve_run(operation, {**payload, **fields}, str(i))
            self.deny(lambda: controller.run_binding(plan, bad))
        missing = copy.deepcopy(payload)
        del missing['input_sha256']
        self.deny(lambda: controller.run_binding(plan, self.approve_run(operation, missing, 'missing')))
        self.deny(lambda: controller.run_binding(plan, {**op, 'plan_sha256': 'd'*64}), 'plan')
        self.deny(lambda: controller.run_binding(plan, {**op, 'proposal_sha256': '0'*64}), 'approval')
        for name in ('job.json', 'fixture.json', 'checkpoint.json'):
            file = data/name
            original = file.read_bytes()
            file.write_bytes(original+b' ')
            self.deny(lambda: controller.run_binding(plan, op), 'metadata changed')
            file.write_bytes(original)
        # A mutually forged fixture/checkpoint digest still differs from the approved Run.
        (data/'fixture.json').write_text(json.dumps({**meta, 'sha256': '0'*64}))
        (data/'checkpoint.json').write_text(json.dumps({**payload['checkpoint'], 'sha256': '0'*64}))
        self.deny(lambda: controller.run_binding(plan, op), 'approved actual input')

    def test_windows_lineage_without_linux_key_still_binds_full_Run_policy_and_canonical_claim(self):
        data,meta=self.fixture()
        plan,operation,payload=self.bound_run(data,meta)
        campaign=self.work/'campaign';campaign.mkdir()
        plan.update(os='Windows',windows_lineage=dict(path=str(self.work/'lineage.json'),sha256='a'*64),
            campaign=str(campaign),executable=dict(path='selected.exe',sha256='a'*64),python=dict(path='selected-python',sha256='b'*64),
            tools=[dict(path='selected-git',sha256='d'*64)],product=dict(commit=identity.PRODUCT),harness=dict(commit='e'*40),peers={})
        self.assertNotIn('selected639_lineage',plan)
        payload.update(slot='WindowsD',source=dict(path=str(data/'input.csv'),stat=identity.stamp(data/'input.csv')),
            lineage_sha256=identity.LINEAGE_SHA,executable=plan['executable'],python=plan['python'],tools=plan['tools'],
            source_roles=dict(product=plan['product'],harness=plan['harness']),limits=control.LIMITS,peer={})
        operation=self.approve_run(operation,payload)
        canonical=self.work/'WindowsD-canonical.json'
        control.create(canonical,dict(proposal_sha256=operation['proposal_sha256'],plan_sha256=operation['plan_sha256'],
            lineage_sha256=identity.LINEAGE_SHA))
        control.create(campaign/'WindowsD-consumed.json',dict(slot='WindowsD',plan_sha256=operation['plan_sha256'],
            claim_sha256=sha256(canonical)))
        operation['claim_sha256']=sha256(canonical)
        lineage=SimpleNamespace(claim_path=lambda slot:canonical)
        with patch.object(controller,'peer_report',return_value=None),patch.object(controller,'Lineage',return_value=lineage)as admitted:
            controller.run_binding(plan,operation);admitted.assert_called_once_with(plan)
            for field in ('source','lineage_sha256','executable','python','tools','source_roles','limits','peer'):
                changed=copy.deepcopy(payload);changed[field]='wrong'
                bad=self.approve_run(operation,changed,'wrong-'+field)
                self.deny(lambda:controller.run_proposal_binding(plan,bad))
            self.deny(lambda:controller.run_binding(plan,dict(operation,claim_sha256='0'*64)),'canonical Run claim drift')
            canonical.write_text(json.dumps(dict(proposal_sha256='0'*64,plan_sha256=operation['plan_sha256'],lineage_sha256=identity.LINEAGE_SHA)))
            self.deny(lambda:controller.run_binding(plan,dict(operation,claim_sha256=sha256(canonical))),'local/canonical Run binding')

    def test_verification_uses_separate_run_approval_actual_digest(self):
        data, meta = self.fixture()
        plan, operation, payload = self.bound_run(data, meta)
        plan.update(product=dict(commit=identity.PRODUCT), host=dict(os='Linux'))
        op = self.approve_run(operation, payload)
        stdout = self.work/'stdout.json'
        control.create(stdout, dict(diagnostics={}))
        (data/'output').mkdir()
        op.update(stage='verify', report=str(self.work/'report.json'), run_stdout=str(stdout))
        with patch.object(controller, 'verify', return_value=dict(source_sha256='0'*64)):
            self.deny(lambda: controller.phase(plan, op), 'verified source')
        self.assertFalse(Path(op['report']).exists())
        with patch.object(controller, 'verify', return_value=dict(source_sha256=meta['sha256'])):
            controller.phase(plan, op)
        self.assertEqual(read_json(op['report'])['report']['source_sha256'], meta['sha256'])

    def fake_git(self, root, *args):
        if args == ('rev-parse', 'HEAD'):
            return 'c'*40
        if args == ('rev-parse', 'HEAD^{tree}'):
            return 'd'*40
        return ''

    def test_independent_checkpoint_streams_and_has_no_generator_import(self):
        for shape in ('D', 'G'):
            data, meta = self.fixture(shape)
            ticks = []
            result = checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta), ticks.append)
            self.assertEqual(result['rows'], meta['rows'])
            self.assertTrue(ticks)
        import scale_acceptance.native_scale_fixture as oracle
        self.assertNotIn('generate', oracle.__dict__)
        self.assertNotIn('row', oracle.__dict__)

    def test_windows_checkpoint_birthtime_and_descriptor_change_time(self):
        from scale_acceptance import native_scale_fixture as oracle
        data, meta = self.fixture()
        source = data/'input.csv'
        original_stat, original_fstat = Path.stat, os.fstat
        def metadata(value, change_time):
            fields = {key: getattr(value, key) for key in dir(value) if key.startswith('st_')}
            return SimpleNamespace(**{**fields, 'st_birthtime_ns': 1000, 'st_ctime_ns': change_time})
        def path_stat(path, *args, **kwargs):
            value = original_stat(path, *args, **kwargs)
            return metadata(value, 1000) if path == source else value
        for changed in (False, True):
            calls = []
            def descriptor(fd):
                calls.append(fd)
                return metadata(original_fstat(fd), 2000+int(changed and len(calls)>1))
            # Python's Windows path stat exposes birth time through ctime,
            # while fstat exposes change time. Both expose the same birth time.
            with patch.object(oracle, 'os', SimpleNamespace(name='nt', fstat=descriptor)), patch.object(Path, 'stat', path_stat):
                if changed:
                    self.deny(lambda: checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta)), 'during checkpoint')
                else:
                    self.assertEqual(checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta))['sha256'], meta['sha256'])
            self.assertEqual(len(calls), 2)

    def test_checkpoint_rejects_replacement_before_open_with_identical_bytes(self):
        data, meta = self.fixture()
        source = data/'input.csv'
        raw, before, original_open = source.read_bytes(), source.stat(), Path.open
        replaced = []
        def replace_before_open(path, mode='r', *args, **kwargs):
            if path == source and mode == 'rb' and not replaced:
                replacement = data/'replacement.tmp'
                replacement.write_bytes(raw)
                os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
                replacement.replace(source)
                replaced.append(True)
            return original_open(path, mode, *args, **kwargs)
        with patch.object(Path, 'open', replace_before_open):
            self.deny(lambda: checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta)), 'before checkpoint open')
        self.assertEqual(replaced, [True])

    def test_checkpoint_changed_field_duplicate_truncated_extra_recipe_sha(self):
        data, meta = self.fixture()
        source = data/'input.csv'
        original = source.read_bytes()
        variants = [original[:-1], original+b'x', original[:100]+original[200:300]+original[200:],
                    original[:118]+b'x'+original[119:]]
        for i, raw in enumerate(variants):
            source.write_bytes(raw)
            self.deny(lambda: checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta)))
            (self.work/f'failed-source-{i}.csv').write_bytes(raw)
        source.write_bytes(original)
        self.deny(lambda: checkpoint(data/'job.json', data/'fixture.json', {**self.tiny_recipe(meta), 'sha256': '0'*64}), 'recipe SHA')
        job = read_json(data/'job.json')
        job['resources']['workers'] = 2
        (data/'job.json').write_text(json.dumps(job))
        self.deny(lambda: checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta)), 'recipe')

    def test_generation_and_run_approval_are_separate_exact_one_shots(self):
        gen, run = self.work/'generation.json', self.work/'run.json'
        control.proposal(gen, 'generation', 'a'*64, dict(recipe='fixed'))
        control.proposal(run, 'Run', 'a'*64, dict(actual='checkpoint'))
        launched = Mock()
        self.assertFalse(control.approved(run, self.work/'run-approved.json'))
        self.assertFalse(launched.called)
        control.approve(gen, self.work/'gen-approved.json', sha256(gen))
        self.assertTrue(control.approved(gen, self.work/'gen-approved.json'))
        self.deny(lambda: control.approved(run, self.work/'gen-approved.json'), 'approval')
        self.deny(lambda: control.approve(run, self.work/'bad.json', '0'*64), 'exact')
        control.approve(run, self.work/'run-approved.json', sha256(run))
        self.assertTrue(control.approved(run, self.work/'run-approved.json'))
        self.deny(lambda: control.approve(run, self.work/'run-approved.json', sha256(run)))
        run.write_text(run.read_text()+' ')
        self.deny(lambda: control.approved(run, self.work/'run-approved.json'), 'approval')

    def test_permanent_consumed_failure_no_retry_and_four_slot_order(self):
        now = [100.]
        campaign = control.Campaign(self.work/'campaign', 'Linux', 'a'*64, lambda: now[0])
        proposal = self.work/'run.json'
        control.create(proposal, dict(frozen=True))
        self.deny(lambda: campaign.consume('LinuxG', proposal))
        campaign.consume('LinuxD', proposal)
        self.deny(lambda: campaign.consume('LinuxD', proposal), 'consumed')
        self.deny(lambda: campaign.consume('WindowsD', proposal), 'OS')
        self.deny(lambda: campaign.consume('LinuxG', proposal))
        self.assertEqual(control.SLOTS, ('LinuxD', 'LinuxG', 'WindowsD', 'WindowsG'))
        self.deny(lambda: control.Campaign(self.work/'campaign', 'Linux', 'b'*64), 'File exists')

    def test_unsealed_session_is_blocked_before_lock_or_campaign(self):
        plan = self.plan()
        del plan['selected639_lineage']
        plan_path = self.work/'selected639-plan.json'
        control.create(plan_path, plan)
        with patch.object(controller, 'HostLock') as lock, \
                patch.object(controller, 'Campaign') as campaign, \
                patch.object(controller, 'execute') as execute:
            self.deny(lambda: controller.session(plan_path, sha256(plan_path)),
                      'selected639_lineage')
            lock.assert_not_called()
            campaign.assert_not_called()
            execute.assert_not_called()

    def test_fixed_os_clock_includes_review_and_shapes(self):
        tick = [200.]
        campaign = control.Campaign(self.work, 'Linux', 'a'*64, lambda: tick[0])
        tick[0] += 7*3600
        campaign.check()
        tick[0] += 3600
        self.deny(campaign.check, 'OS clock')
        tick[0] = 199.
        self.deny(campaign.check, 'OS clock')
        self.assertEqual(control.LIMITS['generation_seconds'], 3600)
        self.assertEqual(control.LIMITS['run_seconds'], 7200)
        self.assertEqual(control.LIMITS['verify_seconds'], 3600)

    def test_native_lifecycle_events_wait_for_complete_newline_but_deny_malformed_publication(self):
        file=self.work/'event.json'
        with patch.object(Path,'exists',return_value=True), patch.object(Path,'read_bytes',
                side_effect=[b'{"complete":',b'{"complete":true}\n']), patch('time.sleep'):
            self.assertEqual(native_lifecycle_read(file,Mock()),dict(complete=True))
        with patch.object(Path,'exists',return_value=True), patch.object(Path,'read_bytes',return_value=b'{broken}\n'):
            with self.assertRaises(json.JSONDecodeError):native_lifecycle_read(file,Mock())

    def test_native_lifecycle_parent_and_worker_wait_for_actual_ready_before_descendants(self):
        case=self.work/'cancel-finish';case.mkdir()
        (case/'parent-captured-census.json').touch()
        events=[]
        windows=SimpleNamespace(process_identity=lambda pid:dict(pid=pid),
            query_job=lambda handle:events.append('query') or dict(pids=[11,22]))
        def read(name):
            events.append('read:'+name.name)
            if name.name=='descendant.json':
                self.assertIn('read:ready.json',events)
                return dict(pid=22)
            return {}
        with patch.object(host,'publish',side_effect=lambda path,value:events.append('publish:'+path.name)):
            native_lifecycle_child_handoff(case,read,windows,8,dict(pid=11),dict(pid=9))
        self.assertEqual(events,['read:containment.json','publish:capacity-sample.json',
            'publish:supervisor-ready.json','read:ready.json','read:descendant.json','query'])
        events=[]
        def publication(path,value):
            events.append(path.name)
            if path.name=='startup.json':(case/'ready.json').touch()
        runner=SimpleNamespace(contain_session=lambda:events.append('nested'),owned_windows_job=lambda:dict(handle=7))
        def launch(*args,**kwargs):
            self.assertTrue((case/'ready.json').exists())
            events.append('spawn');return SimpleNamespace(pid=22)
        with patch.object(host,'module',side_effect=lambda name:windows if name=='browser-small-windows' else runner), \
             patch.object(host,'publish',side_effect=publication),patch.object(subprocess,'Popen',side_effect=launch), \
             patch('time.sleep'),patch.object(sys,'argv',[__file__,'mode','harness','fixture','a'*64]):
            native_lifecycle_child('--native-lifecycle-worker',case)
        self.assertLess(events.index('startup.json'),events.index('spawn'))
        self.assertLess(events.index('spawn'),events.index('descendant.json'))

    def test_native_lifecycle_producer_failure_aborts_wait_and_only_proven_cleanup_releases(self):
        case=self.work/'case';case.mkdir()
        control.create(case/'caretaker-failure.json',dict(error='actual setup rejection'))
        closed=dict(remaining=[],cleanup_errors=[],monitor_threads_joined=True,capture_writers_reaped=True)
        control.create(case/'cleanup.json',closed)
        remaining=Mock()
        with self.assertRaisesRegex(ValueError,'actual setup rejection'):
            native_lifecycle_read(case/'never-ready.json',remaining,lambda:native_lifecycle_producer_terminal(case))
        remaining.assert_called_once()
        process=SimpleNamespace(poll=Mock(side_effect=[None,0]),stdin=SimpleNamespace(closed=True),
            stdout=SimpleNamespace(closed=True),_handle=SimpleNamespace(Close=Mock()))
        owner=SimpleNamespace(process=process,failed=False,request=Mock(),close=Mock(),
            capture_eof=True,reader=SimpleNamespace(is_alive=lambda:False))
        windows=SimpleNamespace(query_job=Mock(return_value=dict(pids=[])),close=Mock())
        with patch.object(host,'pending_calls',return_value=[]):
            proof=native_lifecycle_close_failed(owner,19,case,windows)
        self.assertTrue(proof['keeper_scope_closed'])
        owner.request.assert_called_once_with(dict(command='finish'),seconds=15)
        owner.close.assert_called_once();process._handle.Close.assert_called_once();windows.close.assert_called_once_with(19)
        owner.request.reset_mock();windows.close.reset_mock()
        (case/'cleanup.json').write_text(json.dumps(dict(closed,cleanup_errors=['unknown close']))+'\n')
        with patch.object(host,'pending_calls',return_value=[]),self.assertRaisesRegex(ValueError,'quiescence'):
            native_lifecycle_close_failed(owner,19,case,windows)
        owner.request.assert_not_called();windows.close.assert_not_called()
        with patch.object(host,'pending_calls',return_value=[object()]),self.assertRaisesRegex(ValueError,'pending'):
            native_lifecycle_close_failed(owner,19,case,windows)

    @unittest.skipIf(os.name=='nt','Linux-only import/early-denial control')
    def test_native_lifecycle_driver_loads_selected_harness_before_no_write_denial(self):
        driver=self.work/'staged-driver.py'
        driver.write_bytes(Path(__file__).read_bytes())
        fixture=self.work/'must-not-exist'
        selected=Path(__file__).resolve().parents[1]
        run=subprocess.run([sys.executable,'-B',str(driver),'--native-lifecycle-faults',
            str(selected),str(fixture),sha256(driver)],cwd=self.work,capture_output=True,text=True)
        self.assertNotEqual(run.returncode,0)
        self.assertIn('fresh native lifecycle fixture required',run.stderr)
        self.assertNotIn('ModuleNotFoundError',run.stderr)
        self.assertFalse(fixture.exists())

    def test_actual_lock_syscall_denial_not_reservation_file(self):
        fake = Mock()
        fake.host_lock_path.return_value = self.work/'local-ci.lock'
        # Denial comes from the exclusive OS API, never a JSON boolean/hash.
        fcntl = Mock(LOCK_EX=2, LOCK_NB=4)
        fcntl.flock.side_effect = OSError('exclusive lock busy')
        with patch.object(host, 'module', return_value=fake), patch.object(host, 'native_windows', return_value=False), \
                patch.dict(sys.modules, {'fcntl': fcntl}):
            self.deny(lambda: host.HostLock().__enter__(), 'exclusive lock busy')
        self.assertTrue((self.work/'local-ci.lock').exists())

    def test_windows_caretaker_requires_external_lock_owner_before_launch(self):
        lock = Mock()
        lock.start_caretaker.side_effect = OSError('lock handoff denied')
        with patch.object(host, 'native_windows', return_value=True), \
                patch.object(host.subprocess, 'Popen') as launch:
            self.deny(lambda: host.Caretaker(self.work/'plan', self.work/'op', self.work/'owner', lock),
                      'lock handoff denied')
            launch.assert_not_called()

    def test_windows_lock_owner_must_escape_supervisor_job_before_handoff(self):
        import ctypes
        from ctypes import wintypes as W
        dll = Mock()
        def assigned(process, job, result):
            ctypes.cast(result, ctypes.POINTER(W.BOOL)).contents.value = True
            return True
        dll.IsProcessInJob.side_effect = assigned
        self.deny(lambda: host.independent_windows_lock_owner(dll), 'outside inherited Jobs')
        dll.IsProcessInJob.side_effect = None
        dll.IsProcessInJob.return_value = False
        self.deny(lambda: host.independent_windows_lock_owner(dll), 'outside inherited Jobs')
        dll.IsProcessInJob.return_value = True
        host.independent_windows_lock_owner(dll)
        process = Mock(stdout=io.StringIO(''))
        process.pid = 123
        birth = dict(pid=123, created=456, parent=12, image='fake-python.exe')
        proof = dict(path=str(self.work/'shared.lock'), owner_pid=123, stat=[],
                     mechanism='msvcrt-byte-0', owner_identity=birth)
        with patch.object(host.subprocess, 'Popen', return_value=process) as launch, \
                patch.object(host.WindowsLockOwner, 'receive', return_value=dict(ok=True, lock=proof)), \
                patch.object(host, 'module', return_value=Mock(process_identity=Mock(return_value=birth))), \
                patch.object(host, 'stamp', return_value=[]):
            host.WindowsLockOwner(self.work/'shared.lock')
        self.assertEqual(launch.call_args.kwargs['creationflags'], 0x01000000)

    def test_windows_owner_failed_constructor_proves_reap_eof_close_or_preserves_uncertainty(self):
        for variant in ('closed', 'wait-failed', 'close-failed', 'not-signaled', 'birth-failed', 'handle-close-failed'):
            with self.subTest(variant=variant):
                process = Mock(pid=123, stdout=io.StringIO(''))
                process.wait.return_value = 1
                dll = Mock()
                dll.WaitForSingleObject.return_value = 258 if variant == 'not-signaled' else 0
                windows = Mock(_held_birth=Mock(return_value=456), kernel=Mock(return_value=dll))
                if variant == 'wait-failed':
                    process.wait.side_effect = subprocess.TimeoutExpired('fixture keeper', 4)
                elif variant == 'close-failed':
                    process.stdin.close.side_effect = OSError('stdin close unknown')
                elif variant == 'birth-failed':
                    windows._held_birth.side_effect = OSError('birth unavailable')
                elif variant == 'handle-close-failed':
                    process._handle.Close.side_effect = OSError('handle closure unknown')
                primary = ValueError('fixture startup rejection')
                with patch.object(host.subprocess, 'Popen', return_value=process), \
                     patch.object(host.WindowsLockOwner, 'receive', side_effect=primary), \
                     patch.object(host, 'module', return_value=windows), \
                     patch.object(host, 'pending_calls', return_value=[]):
                    with self.assertRaises(ValueError) as caught:
                        host.WindowsLockOwner(self.work/'fixture.lock')
                self.assertIs(caught.exception, primary)
                proof = getattr(primary, 'native_owner_no_start_closed', None)
                if variant == 'closed':
                    self.assertEqual(proof['created'], 456)
                    self.assertEqual(proof['caretaker_requests'], 0)
                    self.assertTrue(proof['original_closed_after_keeper_reap'])
                    process._handle.Close.assert_called_once_with()
                else:
                    self.assertIsNone(proof)
                    self.assertTrue(any('unproven' in note for note in primary.__notes__))

    def fake_windows_owner(self):
        owner = host.WindowsLockOwner.__new__(host.WindowsLockOwner)
        owner.path = self.work/'fake-shared.lock'
        owner.path.write_text('fake lock metadata; no lock syscall')
        owner.metadata = identity.stamp(owner.path)
        owner.proof = dict(path=str(owner.path), owner_pid=123, stat=owner.metadata,
                           mechanism='msvcrt-byte-0', owner_identity=dict(pid=123, created=456))
        owner.process = Mock(pid=123, stdin=io.StringIO())
        owner.process.poll.return_value = None
        owner.rpc_lock = threading.Lock()
        owner.failed = False
        return owner

    def test_windows_owner_startup_rejects_missing_or_different_birth(self):
        birth = dict(pid=123, created=456, parent=12, image='fake-python.exe')
        expected = dict(path=str(self.work/'shared.lock'), owner_pid=123, stat=[],
                        mechanism='msvcrt-byte-0', owner_identity=birth)
        for proof in (None, {**expected, 'owner_identity': {**birth, 'created': 789}},
                      {**expected, 'mechanism': 'copied-reservation'}):
            process = Mock(pid=123, stdout=io.StringIO(''))
            with patch.object(host.subprocess, 'Popen', return_value=process), \
                    patch.object(host.WindowsLockOwner, 'receive', return_value=dict(ok=True, lock=proof)), \
                    patch.object(host, 'module', return_value=Mock(process_identity=Mock(return_value=birth))), \
                    patch.object(host, 'stamp', return_value=[]):
                self.deny(lambda: host.WindowsLockOwner(self.work/'shared.lock'), 'startup identity mismatch')
            process.stdin.close.assert_called_once()
            process.wait.assert_called_once_with(timeout=4)

    def test_windows_owner_entry_observes_original_descriptor_under_byte_zero_lock(self):
        events, fd = [], 17
        birth = dict(pid=123, created=456, parent=12, image='fake-python.exe')
        lockfile = self.work/'fake-entry.lock'
        lockfile.write_text('no native lock')
        metadata = identity.stamp(lockfile)
        msvcrt = Mock(LK_NBLCK=1)
        msvcrt.locking.side_effect = lambda *args: events.append('byte-zero-locked')
        def loop(stream, reply, launch, stop, retain, observe, seal_capture):
            self.assertEqual(events, ['byte-zero-locked'])
            self.assertEqual(observe(), dict(path=str(lockfile), owner_pid=123, stat=metadata,
                             mechanism='msvcrt-byte-0', owner_identity=birth))
            events.append('observed')
        with patch.object(host, 'native_windows', return_value=True), \
                patch.object(host, 'independent_windows_lock_owner'), \
                patch.dict(sys.modules, {'msvcrt': msvcrt}), \
                patch.object(host.os, 'open', return_value=fd), \
                patch.object(host.os, 'close') as close, \
                patch.object(host.os, 'fstat', return_value=lockfile.stat()), \
                patch.object(host.os, 'getpid', return_value=123), \
                patch.object(host, 'module', return_value=Mock(process_identity=Mock(return_value=birth))), \
                patch.object(host, 'lock_owner_loop', side_effect=loop), \
                patch.object(host.sys, 'stdout', io.StringIO()) as output:
            host.windows_lock_owner(lockfile)
        msvcrt.locking.assert_called_once_with(fd, msvcrt.LK_NBLCK, 1)
        close.assert_called_once_with(fd)
        self.assertEqual(json.loads(output.getvalue())['lock']['owner_identity'], birth)
        self.assertEqual(events, ['byte-zero-locked', 'observed'])

    def test_windows_owner_rpc_requires_fresh_challenge_and_original_proof(self):
        owner = self.fake_windows_owner()
        def receive(*args):
            command = json.loads(owner.process.stdin.getvalue().splitlines()[-1])
            return dict(ok=True, challenge=command['challenge'], lock=owner.proof, pid=321)
        owner.receive = Mock(side_effect=receive)
        with patch.object(host.secrets, 'token_hex', side_effect=['a'*64, 'b'*64]):
            self.assertEqual(owner.request(dict(command='start')), dict(ok=True, pid=321))
            self.assertEqual(owner.request(dict(command='pulse')), dict(ok=True, pid=321))
        messages = [json.loads(line) for line in owner.process.stdin.getvalue().splitlines()]
        self.assertNotEqual(messages[0]['challenge'], messages[1]['challenge'])
        lock = host.HostLock()
        lock.owner = owner
        self.assertEqual(lock.proof(), owner.proof)
        returned = lock.proof()
        returned['owner_identity']['created'] = 789
        returned['stat'].clear()
        self.assertEqual(owner.proof['owner_identity']['created'], 456)
        self.assertEqual(owner.proof['stat'], identity.stamp(owner.path))
        # Startup/previous pulse bytes cannot acknowledge another request.
        owner.receive.side_effect = lambda *args: dict(ok=True, challenge='a'*64, lock=owner.proof)
        self.deny(lambda: owner.request(dict(command='pulse')), 'observation mismatch')
        before = owner.process.stdin.getvalue()
        self.deny(lambda: owner.request(dict(command='finish')), 'protocol already failed')
        self.assertEqual(owner.process.stdin.getvalue(), before)

    def test_windows_owner_rpc_denies_identity_drift_timeout_and_late_reply(self):
        owner = self.fake_windows_owner()
        for changed in ('owner_identity', 'stat', 'mechanism', 'path', 'missing', 'timeout', 'eof'):
            owner.failed = False
            def receive(*args):
                request = json.loads(owner.process.stdin.getvalue().splitlines()[-1])
                proof = copy.deepcopy(owner.proof)
                if changed == 'timeout':
                    raise OSError('Windows host lock handoff timed out')
                if changed == 'eof':
                    raise ValueError('Windows host lock handoff failed')
                if changed == 'owner_identity':
                    proof['owner_identity']['created'] += 1
                elif changed != 'missing':
                    proof[changed] = 'changed'
                return dict(ok=True, challenge=request['challenge'], **({} if changed == 'missing' else dict(lock=proof)))
            owner.receive = Mock(side_effect=receive)
            self.deny(lambda: owner.request(dict(command='pulse')))
            self.assertTrue(owner.failed)
            self.deny(lambda: owner.request(dict(command='pulse')), 'protocol already failed')

    def test_windows_owner_rpc_rejects_valid_ack_after_deadline(self):
        for delayed in ('sample', 'queue'):
            owner = self.fake_windows_owner()
            now = [0.0]
            owner.responses = Mock()
            def sample():
                if delayed == 'sample':
                    now[0] = 5.0
            def queued(**kwargs):
                request = json.loads(owner.process.stdin.getvalue().splitlines()[-1])
                now[0] = 5.0
                return dict(ok=True, challenge=request['challenge'], lock=owner.proof)
            owner.responses.get.side_effect = queued
            with patch.object(host.time, 'monotonic', side_effect=lambda: now[0]):
                self.deny(lambda: owner.request(dict(command='pulse'), sample, seconds=4), 'timed out')
            self.assertTrue(owner.failed)
            if delayed == 'sample':
                owner.responses.get.assert_not_called()
            before = owner.process.stdin.getvalue()
            self.deny(lambda: owner.request(dict(command='pulse')), 'protocol already failed')
            self.assertEqual(owner.process.stdin.getvalue(), before)

    def test_windows_owner_observes_lock_before_command_and_after_cleanup(self):
        process, events = Mock(pid=123), []
        proof = dict(owner_identity=dict(pid=123, created=456), mechanism='msvcrt-byte-0')
        def observe():
            events.append('observe-held-lock')
            return proof
        commands = [dict(command='start', challenge='a'*64), dict(command='pulse', challenge='b'*64),
                    dict(command='finish', challenge='c'*64)]
        replies = []
        host.lock_owner_loop(io.StringIO(''.join(json.dumps(c)+'\n' for c in commands)), replies.append,
                             lambda _: (process, self.work), lambda *_: events.append('stop-reap-empty'),
                             Mock(), observe)
        self.assertEqual([r['challenge'] for r in replies], ['a'*64, 'b'*64, 'c'*64])
        self.assertTrue(all(r['lock'] == proof for r in replies))
        self.assertEqual(events[-2:], ['stop-reap-empty', 'observe-held-lock'])
        for challenge in (None, '', 'a'*63, 'X'*64):
            launch = Mock()
            self.deny(lambda: host.lock_owner_loop(io.StringIO(json.dumps(dict(command='start', challenge=challenge))+'\n'),
                      Mock(), launch, Mock(), Mock(), observe), 'challenge required')
            launch.assert_not_called()
        launch = Mock()
        self.deny(lambda: host.lock_owner_loop(io.StringIO(json.dumps(commands[0])+'\n'), Mock(), launch,
                  Mock(), Mock(), Mock(side_effect=OSError('held host lock replaced'))), 'lock replaced')
        launch.assert_not_called()

    def owner_loop(self, stream, reply, launch, stop, retain):
        # Existing lifecycle controls inject observation, never a native API.
        commands = [dict(json.loads(line), challenge='a'*64) for line in stream]
        def ack(value):
            reply({k: v for k, v in value.items() if k not in ('challenge', 'lock')})
        host.lock_owner_loop(io.StringIO(''.join(json.dumps(c)+'\n' for c in commands)),
                             ack, launch, stop, retain, lambda: dict(fake_only=True))

    def test_windows_lock_owner_supervisor_eof_holds_lock_until_cleanup(self):
        events = []
        worker = Mock(pid=123)
        lock_held = [True]
        def launch(value):
            self.assertTrue(lock_held[0])
            events.append('launch')
            return worker, self.work
        def stop(process, directory):
            self.assertTrue(lock_held[0], 'shared CI contender must still be denied')
            events.append('stop-reap-empty')
        stream = io.StringIO(json.dumps(dict(command='start'))+'\n')
        self.owner_loop(stream, lambda ack: events.append(ack), launch, stop, Mock())
        lock_held[0] = False  # OS entry point closes only after this return
        self.assertEqual(events, ['launch', dict(ok=True, pid=123), 'stop-reap-empty'])
        control.create(self.work/'eof-order.json', events)

    def test_windows_lock_owner_retains_lock_when_cleanup_unproven(self):
        process = Mock(pid=123)
        retained = Mock(side_effect=OSError('lock retained; parent intervention'))
        stream = io.StringIO(json.dumps(dict(command='start'))+'\n')
        stop = Mock(side_effect=OSError('owned child still alive'))
        self.deny(lambda: self.owner_loop(stream, Mock(), lambda _: (process, self.work), stop, retained),
                  'lock retained')
        retained.assert_called_once()
        diagnostic=read_json(self.work/'lock-owner-stop-failure.json')
        self.assertIn('owned child still alive',diagnostic['error'])
        self.assertEqual(diagnostic['caretaker_pid'],123)
        self.assertFalse(diagnostic['source_armed'])
        # A malformed/missing cleanup proof also cannot end the lock lifetime.
        for proof in (dict(remaining=[123], cleanup_errors=[]), dict(remaining=[], cleanup_errors=['reap failed'])):
            (self.work/'cleanup.json').write_text(json.dumps(proof))
            self.deny(lambda: host.stop_locked_caretaker(process, self.work), 'cannot prove')
        (self.work/'cleanup.json').write_text(json.dumps(dict(remaining=[], cleanup_errors=[],monitor_threads_joined=True,capture_writers_reaped=True)))
        process.stdin.closed=True;process.wait.return_value=0
        host.stop_locked_caretaker(process, self.work)
        process.wait.assert_called_with(timeout=12)

    def test_control_snapshot_charges_before_open_and_read_and_keeps_large_native_bound(self):
        windows=host.module('browser-small-windows');file=self.work/'owner-sample.json'
        raw=json.dumps(dict(monotonic=1,payload='x'*70000)).encode();file.write_bytes(raw)
        events=[];real_open=os.open;real_read=os.read
        # Exercise budget admission with portable real descriptors; native opens
        # are covered by the separately selected Windows integration component.
        windows.os=SimpleNamespace(name='posix',open=os.open,read=os.read,close=os.close,fstat=os.fstat,
            O_RDONLY=os.O_RDONLY|getattr(os,'O_BINARY',0),O_NOFOLLOW=getattr(os,'O_NOFOLLOW',0))
        def acquire(*a,**k):events.append('open');return real_open(*a,**k)
        def read(*a,**k):events.append('read');return real_read(*a,**k)
        def charge(size):events.append(('charge',size))
        with patch.object(windows.os,'open',side_effect=acquire),patch.object(windows.os,'read',side_effect=read):
            self.assertEqual(windows.read_control_snapshot(file,1024**2,charge=charge),raw)
        self.assertLess(events.index(('charge',None)),events.index('open'))
        self.assertLess(events.index(('charge',len(raw))),events.index('read'))
        for denial in ('open','read'):
            def deny(size):
                if (size is None)==(denial=='open'):raise ValueError('budget admission denied')
            with patch.object(windows.os,'open',wraps=real_open)as opened, \
                 patch.object(windows.os,'read',wraps=real_read)as consumed, \
                 patch.object(windows.os,'close',wraps=os.close)as closed:
                self.deny(lambda:windows.read_control_snapshot(file,1024**2,charge=deny),'admission denied')
            consumed.assert_not_called()
            if denial=='open':opened.assert_not_called();closed.assert_not_called()
            else:opened.assert_called_once();closed.assert_called_once()

    def test_unknown_birth_audit_preserves_pid_api_access_and_error_and_stays_strict(self):
        import ctypes
        from scale_acceptance import native_tiny
        kernel=SimpleNamespace(OpenProcess=Mock(return_value=None),WaitForSingleObject=Mock(return_value=0),
                               CloseHandle=Mock(return_value=1))
        windows=SimpleNamespace(checked=lambda value:identity.require(value,'checked close'))
        with patch.object(ctypes,'set_last_error',create=True),patch.object(ctypes,'get_last_error',return_value=5,create=True):
            with self.assertRaises(OSError)as caught:native_tiny.unobserved_birth_exit(kernel,windows,39828,deadline=time.monotonic()+1)
        error=caught.exception
        self.assertEqual((error.api,error.pid,error.requested_access,error.winerror),('OpenProcess',39828,0x101000,5))
        self.assertIn('pid=39828',str(error));self.assertIn('winerror=5',str(error))
        kernel.CloseHandle.assert_not_called()
        with patch.object(ctypes,'set_last_error',create=True),patch.object(ctypes,'get_last_error',return_value=87,create=True):
            self.assertTrue(native_tiny.unobserved_birth_exit(kernel,windows,39828,deadline=time.monotonic()+1)['absent'])
            kernel.OpenProcess.return_value=17
            kernel.WaitForSingleObject.return_value=258
            with self.assertRaisesRegex(ValueError,'cannot infer'):native_tiny.unobserved_birth_exit(kernel,windows,39828,deadline=time.monotonic()+1)
            kernel.CloseHandle.assert_called_once_with(17)

    def test_unknown_open5_requires_complete_unique_snapshot_with_observer_and_target_absence(self):
        import ctypes
        from scale_acceptance import native_tiny
        for variant in ('absent','present','missing-canary','duplicate','incomplete','close-failed','late-close','expired'):
            state=SimpleNamespace(error=0,index=0,now=0.)
            rows=[0,os.getpid()]
            if variant=='present':rows.append(39828)
            if variant=='missing-canary':rows=[0]
            if variant=='duplicate':rows.append(os.getpid())
            def opening(*args):state.error=5;return None
            def first(handle,pointer):pointer._obj.pid=rows[0];return 1
            def following(handle,pointer):
                state.index+=1
                if state.index<len(rows):pointer._obj.pid=rows[state.index];return 1
                state.error=5 if variant=='incomplete' else 18
                return 0
            def close(handle):
                if variant=='late-close':state.now=2.
                return variant!='close-failed'
            kernel=SimpleNamespace(OpenProcess=Mock(side_effect=opening),
                CreateToolhelp32Snapshot=Mock(return_value=99),Process32FirstW=Mock(side_effect=first),
                Process32NextW=Mock(side_effect=following),CloseHandle=Mock(side_effect=close))
            windows=SimpleNamespace(checked=lambda value:identity.require(value,'checked close'))
            with patch.object(ctypes,'set_last_error',side_effect=lambda value:setattr(state,'error',value),create=True), \
                 patch.object(ctypes,'get_last_error',side_effect=lambda:state.error,create=True), \
                 patch.object(native_tiny.time,'monotonic',side_effect=lambda:state.now):
                deadline=-1 if variant=='expired' else 1
                if variant=='absent':
                    proof=native_tiny.unobserved_birth_exit(kernel,windows,39828,deadline=deadline)
                    self.assertTrue(proof['absent']);self.assertTrue(proof['birth_unknown'])
                    self.assertEqual(proof['open_winerror'],5)
                    self.assertEqual(proof['independent_absence']['rows'],2)
                    self.assertEqual(proof['independent_absence']['termination_winerror'],18)
                else:
                    with self.assertRaises(OSError)as caught:
                        native_tiny.unobserved_birth_exit(kernel,windows,39828,deadline=deadline)
                    self.assertEqual(caught.exception.winerror,5)
                    self.assertIn('snapshot rejected',' '.join(caught.exception.__notes__))
            if variant!='expired':kernel.CloseHandle.assert_called_once_with(99)
            else:kernel.CreateToolhelp32Snapshot.assert_not_called()

    def test_control_rename_buffer_has_explicit_terminator_at_every_utf16_alignment(self):
        import ctypes
        windows=host.module('browser-small-windows')
        for padding in range(4):
            for suffix in ('plain','nonBMP-\U0001f642'):
                target='C:/owned/'+'x'*padding+suffix+'.json'
                encoded=target.encode('utf-16le')
                info,size=windows._control_rename_information(target)
                self.assertEqual((info.flags,info.root,info.length),(3,None,len(encoded)))
                self.assertGreaterEqual(size,20+len(encoded)+2)
                self.assertEqual(ctypes.string_at(ctypes.addressof(info)+20,len(encoded)+2),encoded+b'\0\0')

    def test_only_explicit_mutable_control_reader_uses_native_snapshot_and_accounting(self):
        from scale_acceptance import native_tiny
        file=self.work/'capacity-sample.json';file.write_text('{"sample_started_monotonic":1}')
        budget=SimpleNamespace(visits=0,read_bytes=0,mutex=threading.RLock(),check=Mock())
        windows=host.module('browser-small-windows')
        def snapshot(path,maximum,*,charge):
            self.assertEqual(maximum,1024**2);charge(None);charge(file.stat().st_size)
            return file.read_bytes()
        windows.read_control_snapshot=Mock(side_effect=snapshot)
        with patch.object(host,'native_windows',return_value=True),patch.object(host,'module',return_value=windows), \
             patch.object(native_tiny,'budget',budget,create=True):
            self.assertEqual(host.read_control_json(file)['sample_started_monotonic'],1)
            self.assertEqual((budget.visits,budget.read_bytes),(1,file.stat().st_size))
            file.write_text('{"a":1,"a":2}')
            self.deny(lambda:host.read_control_json(file),'duplicate')
        with patch.object(host,'native_windows',return_value=False),patch.object(host,'module')as loaded:
            file.write_text('{"a":1}');self.assertEqual(host.read_control_json(file),dict(a=1));loaded.assert_not_called()

    def test_mutable_publish_is_opt_in_and_close_uncertainty_never_retries(self):
        runner=Mock();windows=host.module('browser-small-windows')
        close_error=windows.ControlFileCloseError('close',self.work/'owned',55,32)
        def select(name):return windows if name=='browser-small-windows'else runner
        with patch.object(host,'native_windows',return_value=True),patch.object(host,'module',side_effect=select), \
             patch('scale_acceptance.guard.load_runner',return_value=runner):
            host.publish(self.work/'immutable.json',{})
            self.assertNotIn('replace',runner.write_json.call_args.kwargs)
            host.publish(self.work/'capacity-sample.json',{},mutable=True)
            self.assertIs(runner.write_json.call_args.kwargs['replace'],windows.replace_control_snapshot)
            runner.write_json.reset_mock();runner.write_json.side_effect=close_error
            with self.assertRaises(windows.ControlFileCloseError):host.publish(self.work/'capacity-sample.json',{},mutable=True)
            self.assertEqual(runner.write_json.call_count,1)
            runner.write_json.reset_mock()
            runner.write_json.side_effect=windows.ControlFileError('SetFileInformationByHandle',self.work/'capacity-sample.json',55,5)
            with self.assertRaises(windows.ControlFileError):host.publish(self.work/'capacity-sample.json',{},mutable=True)
            self.assertEqual(runner.write_json.call_count,1,'Mutable API denial must not enter legacy retry')

    def test_parent_control_close_uncertainty_survives_proven_empty_finish(self):
        root=self.work;plan_path=root/'plan.json';control.create(plan_path,{})
        error=OSError('control handle close unproved');error.process_handle_close_uncertain=True
        count=[0]
        def sample(*a,**k):
            count[0]+=1
            if count[0]>1:raise error
        class Owner:
            def __init__(self,*args):args[2].mkdir()
            def ready(self,*args):pass
            def finish(self,*args):
                self.cleanup_proven=True;raise ValueError('failed phase with positive tree closure')
        lock=host.HostLock.__new__(host.HostLock);lock.owner=Mock(proof={})
        with patch.object(controller,'Caretaker',Owner),patch.object(controller,'disk_sample',side_effect=sample), \
             patch.object(controller,'progress'),patch.object(host,'pending_calls',return_value=[]), \
             patch.object(host,'retain_host_lock',side_effect=OSError('uncertain control retained')):
            with self.assertRaises(OSError)as raised:controller.execute(plan_path,dict(owned_root=str(root)),dict(stage='generation',shape='D'),Mock(),lock)
            self.assertIs(raised.exception,error)
            self.assertTrue(lock.cleanup_uncertain)
            self.deny(lambda:lock.__exit__(None,None,None),'uncertain control retained')
            lock.owner.close.assert_not_called()

    def test_cleanup_only_control_close_uncertainty_retains_after_proven_finish(self):
        root=self.work;plan_path=root/'plan.json';control.create(plan_path,{})
        error=OSError('final control handle close unproved');error.process_handle_close_uncertain=True
        count=[0]
        def sample(*args,**kwargs):
            count[0]+=1
            if count[0]>1:raise error
        class Owner:
            cleanup_proven=False
            def __init__(self,*args):
                args[2].mkdir();control.create(args[2]/'worker-result.json',dict(code=0))
            def ready(self,*args):pass
            def finish(self,*args):self.cleanup_proven=True
        lock=host.HostLock.__new__(host.HostLock);lock.owner=Mock(proof={})
        with patch.object(controller,'Caretaker',Owner),patch.object(controller,'disk_sample',side_effect=sample), \
             patch.object(host,'pending_calls',return_value=[]), \
             patch.object(host,'retain_host_lock',side_effect=OSError('uncertain final control retained')):
            with self.assertRaises(OSError)as raised:
                controller.execute(plan_path,dict(owned_root=str(root)),dict(stage='generation',shape='D'),Mock(),lock)
            self.assertIs(raised.exception,error)
            self.assertTrue(lock.cleanup_uncertain)
            self.deny(lambda:lock.__exit__(None,None,None),'uncertain final control retained')
            lock.owner.close.assert_not_called()

    def test_pipe_failure_preserves_failed_pulse_but_allows_proven_finish_close(self):
        for closed in (True,False):
            directory=self.work/str(closed);directory.mkdir()
            control.create(directory/'cleanup.json',dict(remaining=[],cleanup_errors=[],errors=['phase failed'],
                monitor_threads_joined=True,capture_writers_reaped=True))
            class Pipe:
                writes=0
                def write(self,value):self.writes+=1
                def flush(self):raise OSError(22,'primary pulse flush')
                def close(self):self.closed=closed;raise OSError(22,'secondary pipe close')
            pipe=Pipe();process=Mock(pid=321,stdin=pipe,wait=Mock(return_value=1))
            commands=[dict(command=name,challenge=letter*64)for name,letter in
                      [('start','a'),('pulse','b'),('pulse','c'),('finish','d'),('close','e')]]
            replies=[];retain=Mock(side_effect=OSError('uncertain original retained'));seal=Mock()
            run=lambda:host.lock_owner_loop(io.StringIO(''.join(json.dumps(x)+'\n'for x in commands)),
                replies.append,lambda value:(process,directory),host.stop_locked_caretaker,retain,
                lambda:dict(fake_held=True),seal)
            if closed:
                run();retain.assert_not_called();seal.assert_called_once()
                self.assertEqual(pipe.writes,1)
                self.assertTrue(all(x['caretaker_failed']for x in replies[1:4]))
                self.assertIn('primary pulse flush',replies[1]['error'])
                self.assertTrue(read_json(directory/'lock-owner-stop-failure.json')['cleanup_proven'])
            else:
                self.deny(run,'uncertain original retained');retain.assert_called_once();seal.assert_not_called()
            self.assertTrue(process.wait.called,'pipe error must not skip reap')

    def test_failed_pulse_marker_is_never_completed_progress(self):
        owner=host.Caretaker.__new__(host.Caretaker)
        owner.directory=self.work;owner.process=SimpleNamespace(pid=321);owner.freshness=Mock()
        owner.created=host.time.monotonic();owner.backup_job=None;owner.backup_cgroup=None;owner.capture=Mock()
        owner.lock_owner=Mock(request=Mock(return_value=dict(caretaker_failed=True,cleanup_proven=True,
            caretaker_pid=321,error='primary pipe failed')))
        with self.assertRaises(OSError)as raised:owner.pulse()
        self.assertTrue(raised.exception.caretaker_failed)
        self.assertTrue(owner.phase_failed['cleanup_proven'])
        self.assertIn('primary pipe failed',str(raised.exception))

    def test_windows_lock_owner_sequential_phases_and_failed_launch(self):
        process = Mock(pid=123)
        messages = [dict(command='start'), dict(command='pulse'), dict(command='finish'), dict(command='start')]
        replies, stopped = [], Mock()
        self.owner_loop(io.StringIO(''.join(json.dumps(m)+'\n' for m in messages)),
                             replies.append, lambda _: (process, self.work), stopped, Mock())
        self.assertEqual(stopped.call_count, 2)
        process.stdin.write.assert_called_once_with(b'.')
        self.assertEqual(len(replies), 4)
        launched = Mock(side_effect=OSError('failed lock-owner launch'))
        self.deny(lambda: self.owner_loop(io.StringIO(json.dumps(dict(command='start'))+'\n'),
                  Mock(), launched, Mock(), Mock()), 'failed lock-owner launch')

    def test_runtime_required_loader_stdlib_empty_unrelated_and_monitored_drift(self):
        p = self.host_plan()
        groups = p['dependencies']
        required = identity.runtime_requirements()
        identity.dependency_metadata(groups, required)
        for missing in ('loader', 'runtime/stdlib.py'):
            bad = copy.deepcopy(groups)
            del bad[0]['sha256'][missing]
            self.deny(lambda: identity.dependency_metadata(bad, required), 'runtime')
        with patch.object(monitor, 'git_metadata', return_value={}):
            m = monitor.Monitor(p, Mock(), Mock(), self.work/'samples.jsonl')
        with patch.object(identity, 'runtime_requirements', return_value=(required[0], {*required[1], self.work/'new-image'})):
            self.deny(m.sample, 'runtime native image/root drift')
        (self.work/'artifacts/runtime/new-module.py').write_text('unapproved new runtime module')
        with patch.object(monitor.shutil, 'disk_usage', return_value=Mock(free=201*control.GIB)), \
                patch.object(monitor, 'git_metadata', return_value={}):
            self.deny(m.sample, 'dependency')

    def test_runtime_drift_keeps_strict_denial_and_reports_actual_set_delta(self):
        value = identity.Identity.__new__(identity.Identity)
        value.lineage = Mock()
        value.runtime = ({self.work/'old-root'}, {self.work/'old.dll'})
        current = ({self.work/'new-root'}, {self.work/'new.dll'})
        with patch.object(identity, 'runtime_requirements', return_value=current):
            with self.assertRaisesRegex(ValueError, 'runtime native image/root drift') as caught:
                value.check()
            changes = json.loads(caught.exception.__notes__[0])
            self.assertEqual(changes, dict(roots_added=[str(self.work/'new-root')],
                roots_removed=[str(self.work/'old-root')],images_added=[str(self.work/'new.dll')],
                images_removed=[str(self.work/'old.dll')]))
            with patch.object(identity.json, 'dumps', side_effect=MemoryError('diagnostic failed')):
                self.deny(value.check, 'runtime native image/root drift')

    def test_windows_host_lazy_images_are_loaded_before_runtime_freeze(self):
        p = self.host_plan()
        image = self.work/'artifacts/host-native.dll'
        image.write_bytes(b'reviewed lazy host dependency')
        p['dependencies'][0]['inputs'].append(image.name)
        p['dependencies'][0]['sha256'][image.name] = sha256(image)
        required = identity.runtime_requirements()
        loaded = []
        def discover():
            return required[0], required[1] | ({image} if loaded else set())
        def observe_host():
            loaded.append(True)
            return p['host']
        fake_os = Mock(wraps=os)
        fake_os.name = 'nt'
        with patch.object(monitor, 'os', fake_os), patch.object(monitor, 'host', side_effect=observe_host) as observed, \
                patch.object(identity, 'runtime_requirements', side_effect=discover), \
                patch.object(monitor, 'git_metadata', return_value={}):
            m = monitor.Monitor(p, Mock(), Mock(), self.work/'lazy-host.jsonl')
            self.assertIn(image, m.runtime[1])
            m.hot_sample(reviewing=True)
            m.hot_sample(reviewing=True)
            self.assertGreaterEqual(observed.call_count, 3)
            with patch.object(identity, 'runtime_requirements', return_value=(required[0], {*m.runtime[1], self.work/'unreviewed-image'})):
                self.deny(m.hot_sample, 'runtime native image/root drift')

    def test_runtime_census_uses_actual_platform_images_with_fake_apis(self):
        p = self.plan()
        runtime = self.work/'artifacts/runtime'
        loader = self.work/'artifacts/loader'
        fake_sys = Mock(executable=str(loader), path=[])
        fake_os = Mock(wraps=os)
        fake_os.name = 'posix'
        def linux_path(value):
            return loader if value == '/fixture-loader' else Path(value)
        with patch.object(identity, 'runtime_requirements', self.runtime_discovery), \
                patch.object(identity, 'sys', fake_sys), patch.object(identity, 'os', fake_os), \
                patch.object(identity, 'Path', side_effect=linux_path), \
                patch.object(identity.sysconfig, 'get_path', return_value=str(runtime)), \
                patch.object(identity.sysconfig, 'get_config_var', return_value=None), \
                patch.object(Path, 'read_text', return_value='100-200 r-xp 0 00:00 1 /fixture-loader'):
            roots, files = identity.runtime_requirements()
            self.assertEqual(roots, {runtime})
            self.assertEqual(files, {loader})
            with patch.object(Path, 'read_text', return_value='100-200 r-xp 0 00:00 1 /fixture-loader (deleted)'):
                self.deny(identity.runtime_requirements, 'runtime mapped image deleted')
        import ctypes
        from ctypes import wintypes as W
        dll = Mock()
        def census(process, handles, size, needed):
            handles[0] = 123
            ctypes.cast(needed, ctypes.POINTER(W.DWORD)).contents.value = ctypes.sizeof(W.HMODULE)
            return True
        def image(process, handle, buffer, size):
            buffer.value = str(loader)
            return len(str(loader))
        dll.K32EnumProcessModules.side_effect = census
        dll.K32GetModuleFileNameExW.side_effect = image
        fake_os.name = 'nt'
        with patch.object(identity, 'runtime_requirements', self.runtime_discovery), \
                patch.object(identity, 'sys', fake_sys), patch.object(identity, 'os', fake_os), \
                patch.object(identity.sysconfig, 'get_path', return_value=str(runtime)), \
                patch.object(identity.sysconfig, 'get_config_var', return_value=None), \
                patch.object(ctypes, 'WinDLL', return_value=dll, create=True):
            self.assertEqual(identity.runtime_requirements(), ({runtime}, {loader}))
            dll.K32EnumProcessModules.side_effect = None
            dll.K32EnumProcessModules.return_value = False
            self.deny(identity.runtime_requirements, 'runtime native image census failed')

    def test_build_receipt_requires_one_executable_producing_attempt(self):
        source = {'Cargo.toml': 'a'*64, 'vendor/codec.c': 'b'*64}
        producer = dict(status='passed', exit_code=0,
                        inputs={n: dict(sha256=h) for n, h in source.items()},
                        artifacts={'chopper': dict(sha256='e'*64)})
        value = dict(summary=dict(incomplete=0), attempts=[producer])
        identity.build_receipt(value, source, 'e'*64)
        for mutation in ('split', 'stale-source', 'wrong-artifact', 'empty-source'):
            bad = copy.deepcopy(value)
            if mutation == 'split':
                bad['attempts'][0]['artifacts'] = {}
                bad['attempts'].append({**producer, 'inputs': {}})
            elif mutation == 'stale-source':
                bad['attempts'][0]['inputs']['Cargo.toml']['sha256'] = 'f'*64
            elif mutation == 'wrong-artifact':
                bad['attempts'][0]['artifacts']['chopper']['sha256'] = 'f'*64
            self.deny(lambda: identity.build_receipt(bad, {} if mutation == 'empty-source' else source, 'e'*64),
                      'build input/artifact')

    def test_selected639_build_binding_preserves_original_attempt(self):
        unchanged = {'Cargo.toml', 'vendor/codec.c'} | {f'source-{i}' for i in range(1114)}
        selected = {n: 'a'*64 for n in unchanged | identity.PACKAGING_DELTA}
        original = {**selected, **{n: hashlib.sha256(b'original packaging\n').hexdigest()
                                  for n in identity.PACKAGING_DELTA}}
        reconciliation = dict(selected_commit=identity.PRODUCT, selected_tree=identity.TREE,
                              artifact_build_commit=identity.BUILD, artifact_build_tree=identity.BUILD_TREE,
                              changed_paths=sorted(identity.PACKAGING_DELTA),
                              unchanged_product_source_files=sorted(unchanged))
        record = self.work/'reconciliation.json'
        control.create(record, reconciliation)
        producer = dict(status='passed', exit_code=0,
                        inputs={n: dict(sha256=original[n]) for n in ('Cargo.toml', 'vendor/codec.c')},
                        artifacts={'chopper': dict(sha256='e'*64)})
        receipt = self.work/'build.json'
        control.create(receipt, dict(summary=dict(incomplete=0), attempts=[producer]))
        item = lambda p: dict(path=str(p), sha256=sha256(p))
        plan = dict(product=dict(root=str(self.work), sha256=selected),
                    executable=dict(sha256='e'*64), package=dict(sha256='f'*64))
        proof = dict(schema='native-scale-build-binding-v2', features=[],
                     product_commit=identity.PRODUCT, product_tree=identity.TREE, source_sha256=selected,
                     executable_sha256='e'*64, package_sha256='f'*64,
                     package_receipt_sha256=identity.PACKAGE_RECEIPT,
                     source_reconciliation=item(record), artifact_build_commit=identity.BUILD,
                     artifact_build_tree=identity.BUILD_TREE, artifact_build_source_sha256=original,
                     runner_receipts=[item(receipt)])
        def fake_git(root, *args, raw=False):
            if args[0] == 'rev-parse':
                return identity.BUILD_TREE
            if args[0] == 'diff':
                return '\n'.join(sorted(identity.PACKAGING_DELTA))
            self.assertTrue(raw)
            return b'original packaging\n'
        pin = identity.Identity.__new__(identity.Identity)
        pin.external = {}
        with patch.object(identity, 'git', side_effect=fake_git), \
                patch.object(identity, 'RECONCILIATION', sha256(record)):
            identity.build_binding(plan, proof, pin.pin)
            self.assertEqual(set(pin.external), {record, receipt})
            for key, value in (('schema', 'native-scale-build-binding-v1'),
                               ('product_commit', identity.BUILD), ('product_tree', '0'*40),
                               ('source_sha256', original), ('executable_sha256', '0'*64),
                               ('package_sha256', '0'*64), ('package_receipt_sha256', '0'*64),
                               ('artifact_build_commit', identity.PRODUCT),
                               ('artifact_build_tree', identity.TREE),
                               ('artifact_build_source_sha256', selected), ('runner_receipts', []),
                               ('source_reconciliation', {**item(record), 'sha256': '0'*64})):
                self.deny(lambda: identity.build_binding(plan, {**proof, key: value}, pin.pin))
            split = self.work/'split-build.json'
            control.create(split, dict(summary=dict(incomplete=0), attempts=[
                {**producer, 'artifacts': {}}, {**producer, 'inputs': {}}]))
            self.deny(lambda: identity.build_binding(plan, {**proof, 'runner_receipts': [item(split)]}, pin.pin),
                      'build input/artifact')
            for key, value in (('selected_commit', identity.BUILD), ('artifact_build_commit', identity.PRODUCT),
                               ('changed_paths', sorted(identity.PACKAGING_DELTA | {'crates/engine.rs'})),
                               ('unchanged_product_source_files', sorted(unchanged)[:-1])):
                self.deny(lambda: identity.producing_source(self.work, selected, {**reconciliation, key: value}))
            with patch.object(identity, 'git', return_value='wrong tree or delta'):
                self.deny(lambda: identity.producing_source(self.work, selected, reconciliation), 'packaging/docs')
        self.deny(lambda: identity.Identity(dict(schema='native-scale-v1', features=[],
                  product=dict(commit=identity.BUILD, tree=identity.BUILD_TREE))), 'product639')

    def test_retained_input_cannot_be_adopted_by_repointing_fresh_job(self):
        data, meta = self.fixture()
        originals = {n: (data/n).read_bytes() for n in ('input.csv', 'fixture.json', 'job.json')}
        control.create(data/'checkpoint.json', checkpoint(data/'job.json', data/'fixture.json', self.tiny_recipe(meta)))
        originals['checkpoint.json'] = (data/'checkpoint.json').read_bytes()
        fresh = self.work/'fresh'
        fresh.mkdir()
        job = read_json(data/'job.json')
        job.update(output=str(fresh/'output'), resources={**job['resources'], 'temp_dir': str(fresh/'temp')})
        control.create(fresh/'job.json', job)
        control.create(fresh/'fixture.json', meta)
        self.deny(lambda: checkpoint(fresh/'job.json', fresh/'fixture.json', self.tiny_recipe(meta)), 'Job/path')
        self.assertEqual(originals, {n: (data/n).read_bytes() for n in originals})

    def test_windows_large_generation_requires_exact_separate_D_and_G_payloads(self):
        plan=self.plan();plan.update(os='Windows',host=dict(os='Windows'))
        root=Path(plan['owned_root']);reservation=dict(fake_only=True)
        control.create(root/'reservation.json',dict(actual_lock=reservation))
        for shape in ('D','G'):
            file=root/(shape+'-generation-proposal.json');approved=root/(shape+'-generation-approved.json')
            control.proposal(file,'generation','a'*64,dict(slot='Windows'+shape,recipe=plan['fixtures'][shape],
                data=str(root/(shape+'-data')),reservation=reservation,limits=control.LIMITS))
            control.approve(file,approved,sha256(file))
            operation=dict(stage='generation',shape=shape,data=str(root/(shape+'-data')),proposal=str(file),
                approval=str(approved),proposal_sha256=sha256(file),plan_sha256='a'*64)
            controller.generation_binding(plan,operation)
            self.deny(lambda:controller.generation_binding(plan,dict(operation,shape='G' if shape=='D' else 'D')))
            bad=read_json(file);bad['payload']['recipe']['bytes']-=1;file.write_text(json.dumps(bad))
            approved.write_text(json.dumps(dict(stage='generation',proposal_sha256=sha256(file),plan_sha256='a'*64)))
            self.deny(lambda:controller.generation_binding(plan,dict(operation,proposal_sha256=sha256(file))),'payload mismatch')

    def test_windows_large_G_cannot_pass_without_actual_positive_spill_and_merge(self):
        plan=self.plan();plan.update(os='Windows',host=dict(os='Windows'))
        data,meta=self.fixture('G');(data/'output').mkdir()
        control.create(data/'checkpoint.json',checkpoint(data/'job.json',data/'fixture.json',self.tiny_recipe(meta)))
        stdout=self.work/'analysis.json';report=self.work/'report.json'
        operation=dict(stage='verify',shape='G',data=str(data),report=str(report),run_stdout=str(stdout),plan_sha256='a'*64)
        binding=dict(input_sha256=meta['sha256'])
        for runs,merges in ((0,1),(1,0),(1,1)):
            stdout.write_text(json.dumps(dict(diagnostics=dict(sort_runs=runs,merge_operations=merges,temporary_cleanup_failures=0))))
            with patch.object(controller,'run_binding',return_value=binding),patch.object(controller,'peer_report',return_value=None), \
                 patch.object(controller,'verify',return_value=dict(source_sha256=meta['sha256'])):
                if runs and merges:controller.phase(plan,operation)
                else:self.deny(lambda:controller.phase(plan,operation),'spill/merge claim unmet')
        self.assertEqual(read_json(report)['external_memory_claim'],'present')

    def test_idle_windows_owner_observation_is_challenged_and_never_launches_work(self):
        launch=Mock();reply=Mock()
        self.owner_loop(io.StringIO(json.dumps(dict(command='observe'))+'\n'),reply,launch,Mock(),Mock())
        launch.assert_not_called();reply.assert_called_once_with(dict(ok=True,idle=True))
        self.deny(lambda:self.owner_loop(io.StringIO(json.dumps(dict(command='start'))+'\n'+
            json.dumps(dict(command='observe'))+'\n'),Mock(),lambda value:(Mock(),self.work),Mock(),
            Mock(side_effect=OSError('active owner retained'))),'no active work')

    def test_tiny_namespace_retirement_debt_charges_only_missing_upper_including_closed_tail(self):
        namespace=self.work/'namespace';root=namespace/'closed'
        plan=dict(owned_root=str(root/'data'),campaign=str(root/'campaign'),
            qualification=dict(namespace=str(namespace),new_bytes=64*1024**2))
        def baseline(current):
            rows=[dict(path=str(root/'data/input.csv'),stat=dict(dev=1,ino=1),charge_bytes=current),
                  dict(path=str(root/'parent-stderr.log'),stat=dict(dev=1,ino=2),charge_bytes=2*1024**2)]
            return dict(roots=[dict(path=str(namespace),stat={})],entries=rows,sum_bytes=sum(r['charge_bytes'] for r in rows))
        # Synthetic accounting fixtures only; these are not actual file allocation claims.
        self.assertEqual(controller.tiny.namespace_retirement_debt(plan,baseline(7*1024**2)),57*1024**2)
        self.assertEqual(controller.tiny.namespace_retirement_debt(plan,baseline(96*1024**2)),0)
        bad=baseline(7*1024**2);bad['roots']=[]
        self.deny(lambda:controller.tiny.namespace_retirement_debt(plan,bad))

    def windows_lineage_fixture(self):
        root=self.work/'windows';root.mkdir()
        def pin(name,value):
            file=root/(name+'.json');control.create(file,value);return dict(path=str(file),sha256=sha256(file))
        plan=self.plan();plan.update(os='Windows',host=dict(os='Windows'))
        old=dict(baselines={},prior_storage={},prior_generation_ms=123)
        storage=dict(baselines={},prior_storage={},prior_generation_ms=124,
            fresh_roots=[plan['owned_root'],plan['campaign']],allocation_origin=dict(
                kind='fresh-native-baseline; legacy metrics retained separately',legacy_records=[pin('legacy',dict(unknown=True))]))
        for pool,names in (('native',[str(self.work/'retained-native')]),('source',plan['source_reservation']['roots'])):
            for name in names:Path(name).mkdir(exist_ok=True)
            baseline=dict(roots=[dict(path=name,stat={})for name in names],entries=[],sum_bytes=0)
            old['baselines'][pool]=copy.deepcopy(baseline);storage['baselines'][pool]=copy.deepcopy(baseline)
            prior=dict(sum_bytes=0,entry_count=0,carry_bytes=100,prior_sampled_aggregate_highwater_bytes=100)
            old['prior_storage'][pool]=dict(prior);storage['prior_storage'][pool]=dict(prior)
        plan['owned_roots']=[str(self.work/'retained-native'),plan['owned_root'],plan['campaign']]
        storage['prior_storage']['native'].update(carry_bytes=100+64*1024**2,
            prior_sampled_aggregate_highwater_bytes=100+64*1024**2)
        previous=dict(os='Windows',host=plan['host'],owned_root=str(self.work/'retained-native/closed/data'),
            campaign=str(self.work/'retained-native/closed/campaign'),qualification=dict(
                namespace=str(self.work/'retained-native'),new_bytes=64*1024**2,windows_history=pin('old-history',old)))
        storage['retained_transition']=dict(previous_plan=pin('prior-plan',previous),previous_preflight=pin('prior-preflight',dict(passed=True)))
        linux=dict(plan=pin('linux-plan',dict(os='Linux',product=dict(commit=identity.PRODUCT),
            selected639_lineage=dict(path=identity.LINEAGE_PATH,sha256=identity.LINEAGE_SHA))),
            canonical_slot_ledger='/fixed/original/family',claims={},records={},consumed={})
        linux['completion']=pin('linux-completion',dict(passed=True,plan_sha256=linux['plan']['sha256']))
        plan['peers']={};hashes={}
        for shape in ('D','G'):
            report=dict(os='Linux',host=dict(os='Linux'),passed=True,product=identity.PRODUCT,slot='Linux'+shape,
                plan_sha256=linux['plan']['sha256'],external_memory_claim='present',report=dict(source_sha256='b'*64))
            peer=pin('linux-report'+shape,report);hashes[shape]=peer['sha256']
            plan['peers'][shape]=dict(peer,source_sha256='b'*64,plan_sha256=linux['plan']['sha256'],slot='Linux'+shape)
            claim=dict(slot='Linux'+shape,product=identity.PRODUCT,lineage_sha256=identity.LINEAGE_SHA,
                plan_sha256=linux['plan']['sha256'],proposal_sha256='c'*64)
            linux['claims'][shape]=pin('linux-claim'+shape,claim)
            linux['records'][shape]=pin('linux-record'+shape,dict(slot='Linux'+shape,passed=True,
                plan_sha256=linux['plan']['sha256'],sha256=peer['sha256']))
            linux['consumed'][shape]=pin('linux-consumed'+shape,dict(slot='Linux'+shape,
                plan_sha256=linux['plan']['sha256'],claim_sha256=linux['claims'][shape]['sha256'],proposal_sha256='c'*64))
        value=dict(schema='selected639-windows-lineage-v1',host=plan['host'],selected_product=identity.PRODUCT,
            provenance=[pin('provenance',dict(authority=True))],linux=linux,storage=storage)
        plan['windows_lineage']=pin('current-lineage',value)
        return plan,value,linux['plan']['sha256'],hashes

    def test_retained_windows_floor_and_closed_namespace_debt_are_not_refunded(self):
        empty=dict(entries=[],sum_bytes=0)
        current=dict(entries=[dict(path='/retained/file',stat=dict(dev=1,ino=2),charge_bytes=20)],sum_bytes=20)
        carry=controller.tiny.History.transition_carry(dict(carry_bytes=100),empty,current,
            retained=dict(floors=dict(source=500)),pool='source')
        self.assertEqual(carry,500)
        self.assertEqual(controller.tiny.History.transition_carry(dict(carry_bytes=100),current,current),100)
        namespace=self.work/'old-tiny';namespace.mkdir()
        previous=dict(owned_root=str(namespace/'leaf/data'),campaign=str(namespace/'leaf/campaign'),qualification=dict(namespace=str(namespace),new_bytes=64*1024**2))
        sealed=dict(roots=[dict(path=str(namespace))],entries=[],sum_bytes=0)
        carry=controller.tiny.History.transition_carry(dict(carry_bytes=100),empty,sealed,
            retained=dict(floors=dict(native=500)),pool='native',previous_plan=previous)
        self.assertEqual(carry,100+64*1024**2)
        self.assertGreaterEqual(carry,500)
        # Growth within the old closed namespace pays down its missing envelope once.
        file=namespace/'leaf/data/input.csv'
        measured=dict(roots=sealed['roots'],entries=[dict(path=str(file),stat=dict(dev=1,ino=2),charge_bytes=20)],sum_bytes=20)
        self.assertEqual(controller.tiny.History.transition_carry(dict(carry_bytes=100),empty,measured,
            retained=dict(floors=dict(native=500)),pool='native',previous_plan=previous),carry)

    def retained_windows_d_fixture(self, *, policy=None, retained_roots=(), floors=None, original_stat=None):
        plan,value,linux_sha,hashes=self.windows_lineage_fixture()
        plan['source_reservation']['bytes']=6291456000
        if policy:
            for key in ('product','reservation','executable','package','package_receipt','build_proof','limits','features'):
                plan[key]=copy.deepcopy(policy[key])
            plan['source_reservation']['bytes']=policy['source_reservation']['bytes']
        plan['product']['commit']=identity.PRODUCT
        old=copy.deepcopy(plan);base=self.work/'closed-large';data=base/'data';campaign=base/'campaign'
        data.mkdir(parents=True);campaign.mkdir()
        old.update(owned_root=str(data),campaign=str(campaign),owned_roots=[*plan['owned_roots'],*retained_roots,str(data),str(campaign)],
            windows_execution=dict(namespace=str(base),original_lock_stat=original_stat or [1,2,0,3,4,5]))
        old['harness']['sha256']['scripts/scale_acceptance/native_tiny.py']='e'*64
        def put(file,value):
            control.create(file,value);return dict(path=str(file),sha256=sha256(file))
        d={};d['plan']=put(base/'scale-plan.json',old)
        claim=dict(slot='WindowsD',product=identity.PRODUCT,lineage_sha256=identity.LINEAGE_SHA,
            plan_sha256=d['plan']['sha256'],proposal_sha256='c'*64,campaign=str(campaign),owned_root=str(data))
        d['canonical']=put(campaign/'WindowsD-canonical.json',claim)
        d['report']=put(data/'D-verified.json',dict(slot='WindowsD',product=identity.PRODUCT,passed=True,
            evidence_kind='native-scale',host=plan['host'],plan_sha256=d['plan']['sha256'],report=dict(source_sha256='b'*64)))
        d['consumed']=put(campaign/'WindowsD-consumed.json',dict(slot='WindowsD',plan_sha256=d['plan']['sha256'],
            claim_sha256=d['canonical']['sha256'],proposal_sha256='c'*64))
        d['verified']=put(campaign/'WindowsD-verified.json',dict(slot='WindowsD',passed=True,
            plan_sha256=d['plan']['sha256'],sha256=d['report']['sha256'],report=d['report']['path']))
        original=dict(path=old['reservation']['lock_path'],stat=old['windows_execution']['original_lock_stat'],original_descriptor_closed=True,
            capture_eof_joined=True,owner_pid=123)
        d['result']=put(data/'scale-result.json',dict(passed=False,scale_acceptance=False,plan_sha256=d['plan']['sha256'],
            os='Windows',host=old['host'],original_lock=original))
        d['independent']=put(base/'after-exit-proof.json',dict(schema='native103-windows-scale-after-exit-v1',
            qualification_passed=False,qualification_sha256=d['result']['sha256'],original_byte_zero_available=True,
            independent_probe_released=True,administrative_recovery=False,original_lock_stat=original['stat'],
            verifier_role=dict(sha256='e'*64),owned_births=[dict(absent=True)],
            phases=[dict(directory=str(data/('D-'+phase)),empty_owned_job=True) for phase in ('generation','Run','verify')]))
        capacity=data/'capacity.jsonl'
        floors=floors or dict(native=27741321144,source=4488463256)
        capacity.write_text(json.dumps(dict(reservation=dict(owner_pid=123),
            owned_sampled_highwater=floors['native'],source_sampled_highwater=floors['source']))+'\n')
        d['capacity_log']=dict(path=str(capacity),sha256=sha256(capacity))
        d['started']=put(campaign/'Windows-started.json',dict(plan_sha256=d['plan']['sha256'],started=1000,prior_generation_ms=900))
        d['linux_d_report']={k:v for k,v in plan['peers']['D'].items() if k in ('path','sha256')}
        return plan,value,d,linux_sha,hashes

    def test_retained_windows_d_consumes_original_chain_and_only_allows_fresh_G(self):
        plan,value,d,linux_sha,hashes=self.retained_windows_d_fixture()
        with patch.object(identity,'LINUX_SCALE_PLAN_SHA',linux_sha),patch.object(identity,'LINUX_SCALE_REPORTS',hashes):
            accepted=identity.retained_windows_d(plan,d)
            self.assertEqual(accepted['floors'],dict(native=27741321144,source=4488463256))
            descriptor=copy.deepcopy(value);descriptor['retained_windows_d']=d
            file=Path(plan['windows_lineage']['path']);file.write_text(json.dumps(descriptor));plan['windows_lineage']['sha256']=sha256(file)
            self.assertEqual(identity.execution_shapes(plan),('G',))
            lineage=SimpleNamespace(retained_d=accepted,value=dict(prior_generation_ms=900),
                check=lambda:None,claim_path=lambda slot:Path(plan['campaign'])/(slot+'-canonical.json'))
            fresh=self.work/'fresh-campaign'
            campaign=control.Campaign(fresh,'Windows','a'*64,lineage=lineage,now=lambda:1001,clock=lambda:0)
            campaign.predecessor('WindowsG')
            with self.assertRaisesRegex(ValueError,'cannot be executed again'):campaign.predecessor('WindowsD')
            campaign.check()
            campaign.now=lambda:1000+control.LIMITS['os_seconds']
            with self.assertRaisesRegex(ValueError,'original retained Windows OS deadline'):campaign.check()
            for name,field,bad in (('plan','host',{'os':'other'}),('plan','product',{'commit':'f'*40}),
                ('report','plan_sha256','f'*64),('report','passed',False),('canonical','proposal_sha256','f'*64),
                ('independent','independent_probe_released',False),('independent','administrative_recovery',True),
                ('result','passed',True)):
                changed=copy.deepcopy(d);target=Path(changed[name]['path']);original=target.read_bytes()
                body=json.loads(original);body[field]=bad;target.write_text(json.dumps(body));changed[name]['sha256']=sha256(target)
                try:
                    with self.assertRaises(ValueError):identity.retained_windows_d(plan,changed)
                finally:target.write_bytes(original)
            changed=copy.deepcopy(d);changed['report']['sha256']='0'*64
            with self.assertRaises(ValueError):identity.retained_windows_d(plan,changed)

    def test_composed_G_only_after_exit_consumes_emitted_current_and_historical_records(self):
        import ctypes
        from scale_acceptance import native_preflight
        original_work=self.work
        prefix=self.work/'qualified-prefix';prefix.mkdir();self.work=prefix
        try:previous,transition,_,_=self.windows_retained_transition_fixture()
        finally:self.work=original_work
        original=Path(previous['reservation']['lock_path']);original.write_bytes(b'')
        original_stat=identity.stamp(original)
        with patch.object(identity,'PRODUCT',previous['product']['commit']):
            plan,value,retained,linux_sha,hashes=self.retained_windows_d_fixture(policy=previous,
                original_stat=original_stat,floors=dict(native=100000,source=1000))
        historical={name:Path(pin['path']).read_bytes() for name,pin in retained.items()}
        old=read_json(retained['plan']['path'])
        # Exercise the actual selected-source checks and actual Lineage/preflight consumers.
        scripts=self.work/'selected-audit-harness/scripts';scripts.mkdir(parents=True)
        selected={}
        for name in ('native-scale-runner.py','browser-small-windows.py','test-native-file-allocation.py',
                     'scale_acceptance/native_tiny.py','scale_acceptance/native_scale_identity.py'):
            source=Path(controller.__file__).parent/name
            if not source.exists():source=Path(host.__file__).parent.parent/name
            target=scripts/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
            selected['scripts/'+name]=sha256(target)
        plan['harness']=dict(plan['harness'],root=str(scripts.parent),sha256=selected)
        prior=read_json(previous['qualification']['windows_history']['path'])
        native_roots=identity.windows_root_union([row['path']for row in prior['baselines']['native']['roots']],
            [previous['qualification']['namespace'],*old['owned_roots']])
        source_roots=identity.windows_root_union([row['path']for row in prior['baselines']['source']['roots']],
            [*old['source_reservation']['roots'],str(scripts.parent)])
        storage=value['storage'];storage['retained_transition']={key:transition['retained_transition'][key]
            for key in ('previous_plan','previous_preflight')}
        storage['prior_generation_ms']=900
        for pool,roots in (('native',native_roots),('source',source_roots)):
            baseline=native_preflight.observe_baseline(roots,Mock())
            before=controller.tiny.History._baseline_charges(prior['baselines'][pool])
            after=controller.tiny.History._baseline_charges(baseline)
            carry=prior['prior_storage'][pool]['carry_bytes']+sum(max(0,charge-before.get(key,0))for key,charge in after.items())
            if pool=='native':carry+=controller.tiny.namespace_retirement_debt(previous,baseline)
            floor=100000 if pool=='native' else 1000
            storage['baselines'][pool]=baseline
            storage['prior_storage'][pool]=dict(sum_bytes=baseline['sum_bytes'],entry_count=len(after),
                carry_bytes=max(carry,floor),prior_sampled_aggregate_highwater_bytes=max(carry,floor))
        value['retained_windows_d']=retained
        plan['source_reservation']['roots']=source_roots
        controls=host.module('test-native-file-allocation');windows=host.module('browser-small-windows')
        kernel=SimpleNamespace(OpenProcess=Mock(return_value=0),WaitForSingleObject=Mock(),
            GetProcessTimes=Mock(),CloseHandle=Mock(return_value=1))
        actual_module=host.module
        def module(name,**kwargs):
            return controls if name=='test-native-file-allocation' else windows if name=='browser-small-windows' else actual_module(name,**kwargs)
        try:
            import msvcrt
            crt=SimpleNamespace(**vars(msvcrt))
        except ImportError:crt=SimpleNamespace()
        crt.LK_NBLCK,crt.LK_UNLCK,crt.locking=2,0,Mock()
        for variant in ('complete','missing','extra','stale-count'):
            root=self.work/variant;root.mkdir();data=root/'data';data.mkdir();campaign=root/'campaign';campaign.mkdir()
            current=copy.deepcopy(plan);current.update(owned_root=str(data),campaign=str(campaign),
                owned_roots=[*native_roots,str(data),str(campaign)],windows_execution=dict(namespace=str(root),
                    original_lock_stat=original_stat,launch_cutoff_unix=time.time()+60,stop_unix=time.time()+120))
            lineage=copy.deepcopy(value);lineage['storage']['fresh_roots']=[str(data),str(campaign)]
            control.create(root/'lineage.json',lineage)
            current['windows_lineage']=dict(path=str(root/'lineage.json'),sha256=sha256(root/'lineage.json'))
            control.create(root/'scale-plan.json',current);exact=sha256(root/'scale-plan.json')
            owner=dict(path=str(original),stat=original_stat,mechanism='msvcrt-byte-0',owner_pid=800003,
                owner_identity=dict(pid=800003,created=3),original_descriptor_closed=True,capture_eof_joined=True)
            result=controller.windows_scale_result(current,exact,0,None,owner)
            self.assertEqual(result['scale_slots_consumed'],1)
            self.assertEqual(result['current_session_shapes'],['G'])
            failed=controller.windows_scale_result(current,exact,1,'controlled failure',owner)
            self.assertIsNone(failed['scale_slots_consumed']);self.assertFalse(failed['passed'])
            if variant=='stale-count':result['scale_slots_consumed']=2
            control.create(data/'scale-result.json',result)
            control.create(root/'qualify-exit.json',dict(code=0))
            control.create(root/'Root-freeze.json',dict(operator_identity=dict(pid=800001,created=1)))
            control.create(root/'controller-pid.json',dict(identity=dict(pid=800002,created=2)))
            control.create(data/'G-verified.json',dict(passed=True,slot='WindowsG',evidence_kind='native-scale',
                plan_sha256=exact,external_memory_claim='present'))
            control.create(campaign/'WindowsG-canonical.json',dict(slot='WindowsG',plan_sha256=exact))
            control.create(campaign/'WindowsG-consumed.json',dict(claim_sha256=sha256(campaign/'WindowsG-canonical.json')))
            control.create(campaign/'Windows-scale-completed.json',dict(passed=True,plan_sha256=exact,
                scale_result_sha256=sha256(data/'scale-result.json')))
            phases=['G-generation','G-Run','G-verify']
            if variant=='missing':phases.remove('G-verify')
            if variant=='extra':phases.append('D-Run')
            for index,name in enumerate(phases):
                directory=data/name;directory.mkdir()
                control.create(directory/'cleanup.json',dict(remaining=[],cleanup_errors=[],errors=[],controller_eof=True,
                    monitor_threads_joined=True,capture_writers_reaped=True))
                worker,caretaker=800010+index*2,800011+index*2
                control.create(directory/'containment.json',dict(worker_pid=worker))
                control.create(directory/'supervisor-ready.json',dict(caretaker_pid=caretaker))
                (directory/'process-census.jsonl').write_text(json.dumps(dict(processes=[dict(pid=worker,created=worker),
                    dict(pid=caretaker,created=caretaker)]))+'\n')
            close=Mock(wraps=os.close);crt.locking.reset_mock();kernel.OpenProcess.reset_mock()
            api=SimpleNamespace(name='nt',open=os.open,fstat=os.fstat,lseek=os.lseek,close=close,O_RDWR=os.O_RDWR,SEEK_SET=os.SEEK_SET)
            with patch.object(identity,'PRODUCT',previous['product']['commit']), \
                 patch.object(identity,'LINUX_SCALE_PLAN_SHA',linux_sha),patch.object(identity,'LINUX_SCALE_REPORTS',hashes), \
                 patch.object(host,'module',side_effect=module),patch.object(windows,'kernel',return_value=kernel), \
                 patch.object(ctypes,'set_last_error',create=True),patch.object(ctypes,'get_last_error',return_value=87,create=True), \
                 patch.dict(sys.modules,msvcrt=crt),patch.object(controller.tiny,'os',api),patch('sys.stdout',new=io.StringIO()):
                if variant=='complete':
                    controller.tiny.after_exit(root,exact,verifier_sha256=sha256(controller.tiny.__file__))
                    proof=read_json(root/'after-exit-proof.json')
                    self.assertEqual({Path(row['directory']).name for row in proof['phases']},set(phases))
                    self.assertEqual(len(proof['phases']),3)
                    self.assertEqual(proof['retained_windows_d'],retained)
                    self.assertEqual(proof['current_session_shapes'],['G'])
                    self.assertEqual(proof['qualification_sha256'],sha256(data/'scale-result.json'))
                    self.assertEqual(crt.locking.call_count,2);close.assert_called_once()
                    self.assertEqual(kernel.OpenProcess.call_count,9)
                    self.assertTrue(all(row['absent'] for row in proof['owned_births']))
                else:
                    with self.assertRaisesRegex(ValueError,'exact native acceptance scope' if variant=='stale-count' else 'complete exact phase roles'):
                        controller.tiny.after_exit(root,exact,verifier_sha256=sha256(controller.tiny.__file__))
                    self.assertFalse((root/'after-exit-proof.json').exists())
                    crt.locking.assert_not_called();close.assert_not_called()
            self.assertFalse((data/'D-verified.json').exists())
        self.assertTrue(all(Path(retained[name]['path']).read_bytes()==raw for name,raw in historical.items()))

    def test_fresh_G_Lineage_requires_retained_D_roots_floors_and_debit(self):
        plan,value,descriptor,linux_sha,hashes=self.retained_windows_d_fixture()
        old=read_json(descriptor['plan']['path']);fresh=self.work/'fresh-G';fresh.mkdir()
        data=fresh/'data';campaign=fresh/'campaign';data.mkdir();campaign.mkdir()
        retained=identity.windows_root_union(plan['owned_roots'],old['owned_roots'])
        plan.update(owned_root=str(data),campaign=str(campaign),owned_roots=[*retained,str(data),str(campaign)])
        value['retained_windows_d']=descriptor
        value['storage']['fresh_roots']=[str(data),str(campaign)]
        value['storage']['baselines']['native']['roots']=[dict(path=name,stat={})for name in retained]
        for pool,amount in (('native',27741321144),('source',4488463256)):
            value['storage']['prior_storage'][pool].update(carry_bytes=amount,prior_sampled_aggregate_highwater_bytes=amount)
        value['storage']['prior_generation_ms']=900
        file=Path(plan['windows_lineage']['path']);file.write_text(json.dumps(value));plan['windows_lineage']['sha256']=sha256(file)
        with patch.object(identity,'LINUX_SCALE_PLAN_SHA',linux_sha),patch.object(identity,'LINUX_SCALE_REPORTS',hashes), \
             patch.object(controller.tiny,'preflight'):
            actual=identity.Lineage(plan)
            self.assertEqual(actual.retained_d['descriptor'],descriptor)
            for fault in ('native-floor','source-floor','elapsed','old-root'):
                changed=copy.deepcopy(value)
                if fault.endswith('floor'):
                    pool=fault.split('-')[0]
                    changed['storage']['prior_storage'][pool].update(carry_bytes=100000000,prior_sampled_aggregate_highwater_bytes=100000000)
                elif fault=='elapsed':changed['storage']['prior_generation_ms']=899
                else:changed['storage']['baselines']['native']['roots'].pop()
                file.write_text(json.dumps(changed));plan['windows_lineage']['sha256']=sha256(file)
                with self.assertRaises(ValueError):identity.Lineage(plan)

    def test_retained_windows_d_claim_reader_uses_explicit_C_mapping_for_every_proof(self):
        from pathlib import PureWindowsPath
        plan,value,d,linux_sha,hashes=self.retained_windows_d_fixture()
        def native(item):
            if isinstance(item,dict):return {key:native(child) for key,child in item.items()}
            if isinstance(item,list):return [native(child) for child in item]
            if isinstance(item,str) and item.startswith(str(self.work)):
                return str(PureWindowsPath('C:/fixture')/Path(item).relative_to(self.work))
            return item
        bodies={name:read_json(pin['path']) for name,pin in d.items() if name!='capacity_log'}
        old_sha=None
        for name in ('plan','linux_d_report','canonical','report','consumed','verified','result','independent','started'):
            body=native(bodies[name])
            if 'plan_sha256' in body and name!='linux_d_report':body['plan_sha256']=old_sha
            if name=='consumed':body['claim_sha256']=d['canonical']['sha256']
            if name=='verified':body['sha256']=d['report']['sha256']
            if name=='independent':body['qualification_sha256']=d['result']['sha256']
            target=Path(d[name]['path']);target.write_text(json.dumps(body));d[name]['sha256']=sha256(target)
            if name=='plan':old_sha=d[name]['sha256']
        hashes['D']=d['linux_d_report']['sha256']
        d=native(d);plan=native(plan);mapped=[]
        def resolve(name):
            value=PureWindowsPath(name)
            self.assertTrue(value.is_absolute() and value.drive.upper()=='C:')
            self.assertEqual(value.parts[1],'fixture')
            mapped.append(name)
            return self.work.joinpath(*value.parts[2:])
        with patch.object(identity,'LINUX_SCALE_PLAN_SHA',linux_sha),patch.object(identity,'LINUX_SCALE_REPORTS',hashes):
            accepted=identity.retained_windows_d(plan,d,resolve_path=resolve)
        self.assertEqual(accepted['plan']['owned_root'],native(str(self.work/'closed-large/data')))
        self.assertTrue(all(pin['path'] in mapped for pin in d.values()))

    def test_windows_lineage_imports_exact_accepted_chain_and_denies_refund_or_missing_roots(self):
        plan,value,linux_sha,hashes=self.windows_lineage_fixture()
        with patch.object(identity,'LINUX_SCALE_PLAN_SHA',linux_sha),patch.object(identity,'LINUX_SCALE_REPORTS',hashes), \
             patch.object(controller.tiny,'preflight')as preflight:
            lineage=identity.Lineage(plan)
            self.assertEqual(lineage.claim_path('WindowsD'),Path(plan['campaign'])/'WindowsD-canonical.json')
            preflight.assert_called_once()
            for fault in ('carry','root','elapsed','peer','claim','native-debt'):
                changed=copy.deepcopy(value)
                if fault=='carry':
                    changed['storage']['prior_storage']['source'].update(carry_bytes=99,prior_sampled_aggregate_highwater_bytes=99)
                elif fault=='root':changed['storage']['baselines']['source']['roots']=[]
                elif fault=='elapsed':changed['storage']['prior_generation_ms']=122
                elif fault=='peer':changed['linux']['plan']['sha256']='0'*64
                elif fault=='native-debt':changed['storage']['prior_storage']['native'].update(carry_bytes=100,prior_sampled_aggregate_highwater_bytes=100)
                else:changed['linux']['claims']['D']['sha256']='0'*64
                file=Path(plan['windows_lineage']['path']);file.write_text(json.dumps(changed))
                plan['windows_lineage']['sha256']=sha256(file)
                self.deny(lambda:identity.Lineage(plan))

    @unittest.skipUnless(sys.platform.startswith('linux'),'actual POSIX canonical writer with scoped mounted-path adapter')
    def test_windows_claim_bridge_requires_fresh_owner_proof_before_irreversible_temp_family_write(self):
        for fault in ('none','owner','stale','proposal','parent','controller-pid','controller-birth','startup-birth','controller-record-drift'):
            root=self.work/fault;root.mkdir();drive=root/'drive';drive.mkdir()
            namespace=drive/'native103';namespace.mkdir();data=namespace/'data';data.mkdir();campaign=namespace/'campaign';campaign.mkdir()
            ledger=root/'family';ledger.mkdir()
            def put(file,value):control.create(file,value);return dict(path=str(file),sha256=sha256(file))
            claims={}
            for shape in ('D','G'):claims[shape]=put(ledger/('Linux'+shape+'-consumed.json'),dict(slot='Linux'+shape))
            family=root/'lineage.json';put(family,dict(current=dict(canonical_slot_ledger=str(ledger))))
            native_root='C:/native103'
            selected_harness=drive/'harness/scripts';selected_harness.mkdir(parents=True)
            (selected_harness/'native-scale-runner.py').write_bytes(Path(controller.__file__).read_bytes())
            descriptor=dict(linux=dict(canonical_slot_ledger=str(ledger),claims=claims),storage=dict(prior_generation_ms=0),
                claim_parent=dict(python=str(Path(sys.executable).resolve()),python_sha256=sha256(sys.executable),runner=str(Path(controller.__file__).resolve())))
            desc=put(namespace/'descriptor.json',descriptor)
            plan=dict(os='Windows',owned_root=native_root+'/data',campaign=native_root+'/campaign',
                host=dict(os='Windows'),harness=dict(root='C:/harness',sha256={'scripts/native-scale-runner.py':sha256(controller.__file__)}),
                windows_lineage=dict(path=native_root+'/descriptor.json',sha256=desc['sha256']),
                source_reservation=dict(bytes=10000),windows_execution=dict(launch_cutoff_unix=time.time()+60,stop_unix=time.time()+120))
            plan_file=namespace/'scale-plan.json';put(plan_file,plan);pin=sha256(plan_file)
            proposal=data/'D-Run-proposal.json';put(proposal,dict(schema='native-scale-proposal-v1',stage='Run',plan_sha256=pin,payload=dict(slot='WindowsD')))
            control.approve(proposal,data/'D-Run-approved.json',sha256(proposal))
            owner=dict(path='C:/temporary-lock',stat=[1,2,0,3,4,5],mechanism='msvcrt-byte-0',owner_pid=123,
                owner_identity=dict(pid=123,created=456))
            put(data/'reservation.json',dict(actual_lock=owner))
            put(campaign/'Windows-started.json',dict(plan_sha256=pin,prior_generation_ms=0,started=time.time()))
            controller_identity=dict(pid=789,created=987,parent=77,image='C:/selected-python.exe')
            put(namespace/'controller-pid.json',dict(pid=789,identity=controller_identity))
            put(namespace/'controller-startup-created.json',dict(identity=(dict(controller_identity,created=888)
                if fault=='startup-birth' else controller_identity),process_handle=11,primary_thread_handle=12))
            release=threading.Event();errors=[]
            def producer():
                try:
                    challenge_file=data/'D-claim-challenge.json'
                    while not challenge_file.exists():
                        if release.wait(.002):return
                    while True:
                        body=challenge_file.read_bytes()
                        if body.endswith(b'\n'):break
                        if release.wait(.002):return
                    challenge=json.loads(body)
                    proof=dict(schema='selected639-windows-claim-proof-v1',challenge=challenge,host=plan['host'],
                        owner=owner,controller=controller_identity,proposal_validated=True,idle_owner_acknowledged=True,observed_unix=time.time(),
                        session_start_sha256=sha256(campaign/'Windows-started.json'),session_authority_sha256=sha256(data/'reservation.json'),
                        capacity=dict(reservation=owner,sample_started_unix=time.time(),owned_sampled_highwater=0,source_sampled_highwater=0))
                    if fault=='owner':proof['owner']=dict(owner,owner_pid=999)
                    elif fault=='stale':proof['observed_unix']-=10
                    elif fault=='proposal':proof['challenge']=dict(challenge,proposal_sha256='0'*64)
                    elif fault=='controller-pid':proof['controller']=dict(controller_identity,pid=999)
                    elif fault=='controller-birth':proof['controller']=dict(controller_identity,created=999)
                    # Same exclusive complete-newline publication as the native producer.
                    put(data/'D-claim-proof.json',proof)
                except BaseException as error:errors.append(error)
            def mapped(value):
                value=str(value)
                return identity.path(str(drive/Path(value).relative_to('/mnt/c'))) if value.startswith('/mnt/c/') else identity.path(value)
            if fault=='parent':
                descriptor['claim_parent']['python_sha256']='0'*64
                (namespace/'descriptor.json').write_text(json.dumps(descriptor));plan['windows_lineage']['sha256']=sha256(namespace/'descriptor.json')
                plan_file.write_text(json.dumps(plan));pin=sha256(plan_file)
                proposal_value=read_json(proposal);proposal_value['plan_sha256']=pin;proposal.write_text(json.dumps(proposal_value))
                (data/'D-Run-approved.json').write_text(json.dumps(dict(stage='Run',plan_sha256=pin,proposal_sha256=sha256(proposal))))
            actual_claim=control.canonical_claim
            def canonical(*args):
                if fault=='controller-record-drift':
                    original=args[0].check
                    def changed():
                        # canonical_claim calls this only after acquiring its real temporary family flock.
                        record=namespace/'controller-pid.json'
                        record.write_text(json.dumps(dict(pid=789,identity=dict(controller_identity,created=999))))
                        original()
                    args[0].check=changed
                return actual_claim(*args)
            producer_thread=threading.Thread(target=producer);producer_thread.start()
            try:
                with patch.object(controller,'LINEAGE_PATH',str(family)),patch.object(controller,'LINEAGE_SHA',sha256(family)), \
                     patch.object(controller,'path',side_effect=mapped),patch.object(controller,'canonical_claim',side_effect=canonical):
                    if fault=='none':controller.claim_windows_run(plan_file,pin,proposal)
                    else:self.deny(lambda:controller.claim_windows_run(plan_file,pin,proposal))
            finally:release.set();producer_thread.join(timeout=1)
            self.assertFalse(producer_thread.is_alive());self.assertEqual(errors,[])
            target=ledger/'WindowsD-consumed.json';local=campaign/'WindowsD-canonical.json'
            self.assertEqual(target.exists(),fault=='none');self.assertEqual(local.exists(),fault=='none')
            self.assertFalse((ledger/'WindowsG-consumed.json').exists())
            if fault=='none':
                self.assertEqual(target.read_bytes(),local.read_bytes())
                receipt=read_json(target)
                self.assertEqual(receipt['controller_record_sha256'],sha256(namespace/'controller-pid.json'))
                self.assertEqual(receipt['controller_startup_created_sha256'],sha256(namespace/'controller-startup-created.json'))

    def test_windows_claim_wait_requires_complete_record_before_real_consume_and_preserves_clock(self):
        for fault in ('none','pending','slot','plan','proposal','lineage','malformed','oversized'):
            root=self.work/fault;root.mkdir();campaign_root=root/'campaign';campaign_root.mkdir()
            data=root/'data';data.mkdir();proposal=data/'D-Run-proposal.json';control.create(proposal,dict(stage='Run'))
            control.create(data/'reservation.json',dict(scope='temporary test only'))
            control.create(campaign_root/'Windows-started.json',dict(scope='temporary test only'))
            claim=campaign_root/'WindowsD-canonical.json'
            operation=dict(shape='D',plan_sha256='a'*64,proposal_sha256=sha256(proposal))
            receipt=dict(slot='WindowsD',plan_sha256=operation['plan_sha256'],proposal_sha256=operation['proposal_sha256'],
                lineage_sha256=controller.LINEAGE_SHA,product=identity.PRODUCT,campaign=str(campaign_root),owned_root=str(data),
                session_start_sha256=sha256(campaign_root/'Windows-started.json'),
                session_authority_sha256=sha256(data/'reservation.json'))
            if fault=='slot':receipt['slot']='WindowsG'
            elif fault=='plan':receipt['plan_sha256']='b'*64
            elif fault=='proposal':receipt['proposal_sha256']='b'*64
            elif fault=='lineage':receipt['lineage_sha256']='b'*64
            lineage=SimpleNamespace(claim_path=lambda slot:claim,check=lambda:None,
                value=dict(current=dict(windows_os_root=str(data))))
            campaign=object.__new__(control.Campaign)
            campaign.root,campaign.os,campaign.sha,campaign.lineage=campaign_root,'Windows',operation['plan_sha256'],lineage
            campaign.now=time.time;checks=[];polls=[]
            def check():
                checks.append(None)
                if fault=='pending' and len(checks)>2:raise ValueError('original absolute clock expired')
            campaign.check=check
            monitor=SimpleNamespace(campaign=campaign)
            def publish(*args,**kwargs):
                polls.append(None)
                if fault=='pending' or (fault=='none' and len(polls)==1):raw=b'{'
                elif fault=='malformed':raw=b'{broken}\n'
                elif fault=='oversized':raw=b'x'*65537
                else:raw=(json.dumps(receipt)+'\n').encode()
                claim.write_bytes(raw)
            with patch.object(controller,'disk_sample',side_effect=publish), \
                 patch.object(controller,'windows_claim_observation'),patch.object(controller.time,'sleep'):
                if fault=='none':
                    result=controller.wait_windows_claim({},root/'plan.json',operation,monitor,lineage)
                    self.assertEqual(result,claim);self.assertEqual(len(polls),2)
                    self.assertFalse((campaign_root/'WindowsD-consumed.json').exists())
                    campaign.consume('WindowsD',proposal,result)  # Actual remaining product/owner/session validation and exclusive consumed write.
                    self.assertEqual(read_json(campaign_root/'WindowsD-consumed.json')['claim_sha256'],sha256(claim))
                else:
                    with self.assertRaises((ValueError,json.JSONDecodeError)):
                        controller.wait_windows_claim({},root/'plan.json',operation,monitor,lineage)
                    self.assertFalse((campaign_root/'WindowsD-consumed.json').exists())
                    self.assertEqual(len(polls),2 if fault=='pending' else 1)

    def test_missing_stale_and_blocked_monitor_hash_gap(self):
        tick = [0.]
        watch = host.Freshness(lambda: tick[0])
        tick[0] = 4.9
        watch.completed()
        tick[0] = 10.
        self.deny(watch.check, 'monitor')
        blocked = threading.Event()
        try:
            self.deny(lambda: host.bounded(lambda: blocked.wait(), .01), 'blocked/stale')
        finally:
            blocked.set()
        # External caretaker receives no pulses while runner identity() blocks;
        # it does not depend on any runner guard callback being invoked.
        owner = host.Caretaker.__new__(host.Caretaker)
        owner.directory = self.work
        owner.backup_job, owner.backup_cgroup = None, None
        owner.freshness = host.Freshness(lambda: tick[0])
        owner.process = Mock()
        owner.process.poll.return_value = None
        tick[0] += 6
        self.deny(owner.pulse, 'monitor')
        owner.process.stdin.write.assert_not_called()
        owner.freshness = host.Freshness()
        owner.created = host.time.monotonic()-6
        self.deny(owner.pulse, 'census missing')

    def test_parent_death_cleanup_and_ownership_failures(self):
        owner = host.Caretaker.__new__(host.Caretaker)
        owner.directory = self.work
        owner.process = Mock()
        owner.process.wait.return_value = 1
        self.deny(owner.finish, 'stop/reap')
        owner.process.stdin.close.assert_called_once()
        owner.process.wait.return_value = 0
        control.create(self.work/'cleanup.json', dict(errors=['owned child still alive'], remaining=[101]))
        self.deny(owner.finish, 'cleanup')
        owner.process.poll.return_value = 5
        owner.freshness = host.Freshness()
        self.deny(owner.pulse, 'caretaker lost')
        # Bound actual membership and reject fabricated/missing cgroup proof.
        self.deny(lambda: host.census_linux(None), 'missing owned')
        group = self.work/'fake-cgroup'
        group.mkdir()
        (group/'cgroup.procs').write_text('101\n102\n')
        self.assertEqual(host.census_linux(group), [101, 102])
        (group/'cgroup.procs').write_text('\n'.join(map(str, range(1, 258))))
        self.deny(lambda: host.census_linux(group), 'bound')

    def test_job_image_exit_requires_held_membership_signal_and_fresh_removal(self):
        windows = host.module('browser-small-windows')
        dll = Mock()
        dll.OpenProcess.return_value = 55
        dll.CloseHandle.return_value = 1
        dll.WaitForSingleObject.return_value = 0
        def membership(handle, job, pointer):
            self.assertEqual((handle, job), (55, 77))
            pointer._obj.value = True
            return 1
        dll.IsProcessInJob.side_effect = membership
        census = dict(kill_on_close=True, pids=[123])
        empty = dict(kill_on_close=True, pids=[])
        for variant in ('exited', 'dead5', 'live', 'live5', 'still-member', 'unrelated-api', 'reused'):
            with self.subTest(variant=variant):
                dll.WaitForSingleObject.return_value = 258 if variant in ('live', 'live5') else 0
                error = OSError('unrelated API31') if variant == 'unrelated-api' else windows.ProcessImageQueryError(5 if variant in ('dead5', 'live5') else 31)
                with patch.object(windows, '_held_birth', return_value=9), \
                        patch.object(windows, '_held_identity', side_effect=error), \
                        patch.object(windows, 'query_job', return_value=census if variant == 'still-member' else empty):
                    if variant in ('exited', 'dead5'):
                        self.assertEqual(windows.job_processes(77, census, backend=dll), dict(census=empty, processes=[]))
                    else:
                        previous = [dict(pid=123, created=10)] if variant == 'reused' else []
                        self.deny(lambda: windows.job_processes(77, census, previous, dll))
                        if variant == 'live5':
                            self.assertTrue(any("'wait_state': 258" in note and "'image_error': 5" in note for note in error.__notes__))
                            self.assertTrue(any('fresh exact Job' in note for note in error.__notes__))
        dll.IsProcessInJob.side_effect = lambda handle, job, pointer: 1  # false membership
        with patch.object(windows, '_held_birth', return_value=9), \
                patch.object(windows, '_held_identity', side_effect=windows.ProcessImageQueryError(31)), \
                patch.object(windows, 'query_job', return_value=empty):
            self.deny(lambda: windows.job_processes(77, census, backend=dll), 'Unknown')
            self.assertEqual(windows.job_processes(77, census, [dict(pid=123, created=9)], dll)['processes'], [])
        self.assertEqual(dll.CloseHandle.call_count, 9)
        dll.IsProcessInJob.side_effect = membership
        for signaled in (0, 258):
            dll.WaitForSingleObject.return_value = signaled
            with patch.object(windows, '_held_birth', return_value=9), \
                    patch.object(windows, '_held_identity', return_value=dict(pid=123, created=9)), \
                    patch.object(windows, 'query_job', return_value=empty):
                if signaled == 0:
                    self.assertEqual(windows.job_processes(77, census, backend=dll)['processes'], [])
                else:
                    self.deny(lambda: windows.job_processes(77, census, backend=dll), 'not proven exited')
        dll.CloseHandle.reset_mock()
        dll.CloseHandle.return_value = 0
        both = dict(kill_on_close=True, pids=[123, 124])
        with patch.object(windows, '_held_birth', return_value=9), \
                patch.object(windows, '_held_identity', side_effect=lambda dll, h, pid: dict(pid=pid, created=9)), \
                patch.object(windows, 'query_job', return_value=both):
            with self.assertRaises(windows.ProcessHandleCloseError):
                windows.job_processes(77, both, backend=dll)
        self.assertEqual(dll.CloseHandle.call_count, 2)
        dll.CloseHandle.return_value = 1
        with patch.object(windows, '_held_birth', return_value=9), \
                patch.object(windows, '_held_identity', side_effect=lambda dll, h, pid: dict(pid=pid, created=9)), \
                patch.object(windows, 'query_job', return_value=both):
            result = windows.job_processes(77, census, backend=dll)
            self.assertEqual(result['census'], both)
            self.assertEqual({value['pid'] for value in result['processes']}, {123, 124})
        with patch.object(windows, '_held_birth', return_value=9), \
                patch.object(windows, '_held_identity', side_effect=lambda dll, h, pid: dict(pid=pid, created=9)), \
                patch.object(windows, 'query_job', return_value=both), patch.object(windows, 'MAX_PIDS', 1):
            self.deny(lambda: windows.job_processes(77, census, backend=dll), 'bound')

    def test_job_exit_rechecks_held_signal_and_exit_code_after_fresh_exclusion(self):
        windows=host.module('browser-small-windows')
        for variant in ('exits-during-census','live','still-active','exit-api-failed','post-birth-drift'):
            events=[]
            states=iter([258,258 if variant=='live' else 0])
            def wait(handle,timeout):events.append('wait');return next(states)
            def membership(handle,job,pointer):pointer._obj.value=True;return 1
            def exit_code(handle,pointer):
                events.append('exit');pointer._obj.value=259 if variant=='still-active' else 0
                return variant!='exit-api-failed'
            dll=SimpleNamespace(OpenProcess=lambda *args:55,CloseHandle=Mock(return_value=1),
                WaitForSingleObject=wait,IsProcessInJob=membership,GetExitCodeProcess=exit_code)
            def census(*args,**kwargs):events.append('fresh');return dict(kill_on_close=True,pids=[])
            error=windows.ProcessImageQueryError(5,123)
            births=iter([9,10 if variant=='post-birth-drift' else 9])
            with patch.object(windows,'_held_birth',side_effect=lambda *args:next(births)), \
                 patch.object(windows,'_held_identity',side_effect=error),patch.object(windows,'query_job',side_effect=census):
                if variant=='exits-during-census':
                    self.assertEqual(windows.job_processes(77,dict(pids=[123]),backend=dll)['processes'],[])
                else:
                    with self.assertRaises(windows.ProcessImageQueryError):windows.job_processes(77,dict(pids=[123]),backend=dll)
            self.assertLess(events.index('fresh'),events.index('wait',events.index('wait')+1))
            self.assertTrue(any('post-census held observation' in note for note in error.__notes__))
            dll.CloseHandle.assert_called_once_with(55)

    def test_job_exit_transitional_observation_uses_only_original_deadline(self):
        windows=host.module('browser-small-windows')
        for variant in ('exit','still-live','timeout','birth-drift'):
            now=[0.0];state=[258];censuses=[];closed=[]
            def wait(handle,timeout):
                if timeout:
                    now[0]+=timeout/1000
                    if variant=='exit':state[0]=0
                return state[0]
            def exit_code(handle,pointer):
                pointer._obj.value=259 if variant=='still-live'else 0;return 1
            def member(handle,job,pointer):pointer._obj.value=True;return 1
            dll=SimpleNamespace(OpenProcess=lambda *x:55,CloseHandle=lambda h:closed.append(h)or 1,
                WaitForSingleObject=wait,GetExitCodeProcess=exit_code,IsProcessInJob=member)
            def census(*a,**k):
                censuses.append(now[0]);return dict(kill_on_close=True,pids=[]if state[0]==0 else[123])
            births=[0]
            def birth(*a,**k):births[0]+=1;return 10 if variant=='birth-drift'and births[0]>1 else 9
            error=windows.ProcessImageQueryError(5,123)
            with patch.object(windows.time,'monotonic',side_effect=lambda:now[0]), \
                 patch.object(windows.time,'sleep',side_effect=lambda amount:now.__setitem__(0,now[0]+amount)), \
                 patch.object(windows,'_held_birth',side_effect=birth), \
                 patch.object(windows,'_held_identity',side_effect=error),patch.object(windows,'query_job',side_effect=census):
                if variant=='exit':self.assertEqual(windows.job_processes(77,dict(pids=[123]),backend=dll,deadline=.3)['processes'],[])
                else:
                    with self.assertRaises(windows.ProcessImageQueryError):windows.job_processes(77,dict(pids=[123]),backend=dll,deadline=.3)
            self.assertLessEqual(now[0],.3)
            self.assertEqual(closed,[55])
            if variant=='still-live':self.assertEqual(len(censuses),1)
            if variant in ('exit','timeout'):self.assertTrue(any('bounded exit reconciliation'in x for x in error.__notes__))

    def test_session_failure_keeps_callable_notes_and_diagnostic_failure_preserves_primary(self):
        error=OSError('bounded operation blocked/stale')
        error.add_note('call=Monitor.hot_sample file=native_scale_monitor.py line=9 seconds=2 elapsed=2.01')
        controller.session_failure_record(self.work,error)
        value=read_json(self.work/'session-failure.json')
        self.assertIn('call=Monitor.hot_sample',value['notes'][0])
        self.assertIn('seconds=2',value['traceback'])
        other=ValueError('primary remains')
        with patch.object(controller,'create',side_effect=MemoryError):controller.session_failure_record(self.work,other)
        self.assertEqual(str(other),'primary remains')
        self.assertTrue(any('diagnostic unavailable' in note for note in other.__notes__))

    def test_private_process_component_audit_requires_closed_result_and_exact_hash(self):
        directory=self.work/'private-component';directory.mkdir()
        result=dict(passed=True,callbacks_joined=True,Original_touched=False,
                    observer_identity=dict(pid=10,created=11),controls=[dict(before=dict(pid=12,created=13))])
        control.create(directory/'result.json',result)
        self.deny(lambda:native_job_exit_audit(directory,'0'*64),'exact completed')
        proof=Mock(exited_births=Mock(return_value=[dict(pid=10,absent=True),dict(pid=12,absent=True)]))
        with patch.object(host,'module',return_value=proof):
            native_job_exit_audit(directory,sha256(directory/'result.json'))
        proof.exited_births.assert_called_once_with([result['observer_identity'],result['controls'][0]['before']])
        self.assertFalse(read_json(directory/'after-exit.json')['Original_touched'])
        self.assertIn('result.json',read_json(directory/'after-exit.json')['closed_fixture_files'])

    def test_caretaker_fake_controller_death_queries_job_and_reaps_only_owned(self):
        for variant in ('parent-death', 'bad-job', 'cleanup-failure', 'diagnostic-failure'):
            directory = self.work/variant
            directory.mkdir()
            plan = directory/'plan.json'
            control.create(plan, {})
            control.create(directory/'startup.json', dict(pid=123, handle=456))
            control.create(directory/'supervisor-ready.json', dict(fake_only=True))
            process = Mock(pid=123)
            process.poll.return_value = None
            windows = Mock()
            windows.duplicate_job.return_value = 789
            windows.process_identity.return_value = dict(parent=os.getpid(), image=sys.executable)
            windows.query_job.side_effect = lambda handle: dict(kill_on_close=variant != 'bad-job' or handle == 777,
                pids=[123] if handle == 789 else [])
            # The outer startup census must still contain the worker.
            if variant != 'bad-job':
                windows.query_job.side_effect = [dict(kill_on_close=True, pids=[123]),
                    dict(kill_on_close=True, pids=[123]), dict(kill_on_close=True, pids=[])]
            if variant == 'cleanup-failure':
                windows.terminate.side_effect = OSError('injected owned terminate failure')
            def publish(file, value):
                if variant == 'diagnostic-failure' and file.name == 'caretaker-failure.json':
                    raise OSError('injected diagnostic write failure')
                return control.create(file, value)
            with patch.object(host, 'create', side_effect=publish), \
                    patch.object(host, 'native_windows', return_value=True), patch.object(host, 'module', return_value=windows), \
                    patch.object(host, 'independent_windows_lock_owner'), \
                    patch.object(host.windows_bootstrap, 'create_job', return_value=777), \
                    patch.object(host.windows_bootstrap, 'SuspendedWorker', return_value=process), \
                    patch.object(host.subprocess, 'Popen', return_value=process), patch.object(host, 'ControllerInput', return_value=Mock(read=Mock(return_value=b''))):
                self.assertEqual(host.caretaker(plan, directory/'op.json', directory), 1)
            windows.duplicate_job.assert_called_once_with(123, 456)
            windows.terminate.assert_called_once_with(777)
            self.assertEqual([c.args[0] for c in windows.close.call_args_list], [789, 777])
            process.wait.assert_called_once()
            receipt = read_json(directory/'cleanup.json')
            self.assertTrue(receipt['errors'])
            if variant == 'diagnostic-failure':
                self.assertIn('controller death/pipe closed before cleanup', receipt['errors'])
                self.assertTrue(any('diagnostic unavailable' in error for error in receipt['errors']))
            else:
                failure = read_json(directory/'caretaker-failure.json')
                self.assertIn('Traceback', failure['traceback'])
                self.assertIn('caretaker', failure['traceback'])
            self.assertEqual(receipt['remaining'], [])
            self.failures.append(receipt)

    def test_windows_earliest_entry_precedes_other_imports_and_missing_contract_denies(self):
        import contextlib
        prefix=Path(controller.__file__).read_text().split('import argparse\n',1)[0]
        for token in ('a'*64,''):
            with self.subTest(token=bool(token)):
                output=io.StringIO()
                with patch.object(sys,'platform','win32'), patch.object(sys,'argv',['runner','qualify']), \
                        patch.dict(os.environ,CHOPPER_NATIVE_STARTUP_TOKEN=token,CHOPPER_NATIVE_PREPARATION_UNTIL='180'), \
                        contextlib.redirect_stderr(output):
                    if token:exec(compile(prefix,'startup-prefix','exec'),{'__name__':'__main__'})
                    else:self.deny(lambda:exec(compile(prefix,'startup-prefix','exec'),{'__name__':'__main__'}),'supervised startup')
                self.assertTrue(output.getvalue().startswith('CHOPPER_NATIVE_PYTHON_ENTRY\n'))
                self.assertEqual('CHOPPER_NATIVE_STARTUP_ENTRY' in output.getvalue(),bool(token))

    def test_windows_controller_entry_requires_exact_ack_before_main(self):
        bootstrap = host.windows_bootstrap
        token = 'a'*64
        for line in ('', 'b'*64+'\n', token, token+'garbage\n'):
            with self.subTest(line=line):
                events = []
                self.deny(lambda: bootstrap.controller_entry(token, io.StringIO(line), events.append),
                          'acknowledgement missing')
                self.assertEqual(events, ['CHOPPER_NATIVE_STARTUP_READY '+token])
        events = []
        bootstrap.controller_entry(token, io.StringIO(token+'\n'), events.append)
        self.assertEqual(events[-1], 'CHOPPER_NATIVE_STARTUP_ACKNOWLEDGED '+token)

    def test_controller_startup_parent_deadline_rejects_missing_late_and_partial_entry(self):
        bootstrap=host.windows_bootstrap
        token='a'*64
        target=self.work/'stderr.log'
        normal=''.join('CHOPPER_NATIVE_STARTUP_'+name+' '+token+'\n'
                       for name in ('ENTRY','IMPORTS_COMPLETE','READY'))
        for variant in ('normal','missing','late','exited','partial','out-of-order'):
            with self.subTest(variant=variant):
                target.write_text(normal if variant not in ('missing','partial','out-of-order') else
                    ('' if variant=='missing' else normal[:-2] if variant=='partial' else
                     ''.join(reversed(normal.splitlines(keepends=True)))))
                child=bootstrap.SuspendedWorker(api=Mock(),dll=Mock(),handles=(11,12,123,456))
                ticks=iter([0.,31.] if variant=='late' else [0.,1.] if variant=='normal' else [0.,31.])
                with patch.object(child,'poll',return_value=1 if variant=='exited' else None), \
                        patch.object(bootstrap.time,'monotonic',side_effect=lambda:next(ticks)), \
                        patch.object(bootstrap.time,'sleep'):
                    if variant=='normal':self.assertTrue(child.wait_controller_entry(target,token,30)['ready'])
                    else:self.deny(lambda:child.wait_controller_entry(target,token,30))
                self.assertFalse(child.controller_ack_attempted)

    def test_controller_startup_crlf_and_split_line_preserve_raw_offsets(self):
        bootstrap=host.windows_bootstrap;token='a'*64
        target=self.work/'stderr.log'
        raw=''.join('CHOPPER_NATIVE_STARTUP_'+name+' '+token+'\r\n'
                    for name in ('ENTRY','IMPORTS_COMPLETE','READY')).encode()
        for split in (False,True):
            with self.subTest(split=split):
                target.write_bytes(raw[:-1] if split else raw)
                child=bootstrap.SuspendedWorker(api=Mock(),dll=Mock(),handles=(11,12,123,456))
                ticks=iter([0.,1.,2.])
                def append(_):
                    with target.open('ab') as stream:stream.write(b'\n')
                with patch.object(child,'poll',return_value=None), \
                        patch.object(bootstrap.time,'monotonic',side_effect=lambda:next(ticks)), \
                        patch.object(bootstrap.time,'sleep',side_effect=append):
                    self.assertEqual(child.wait_controller_entry(target,token,30)['stderr_bytes'],len(raw))

    def test_controller_entry_parent_eof_and_late_ack_cannot_enter_main(self):
        bootstrap=host.windows_bootstrap
        token='a'*64
        readfd,writefd=os.pipe();events=[];errors=[]
        with os.fdopen(readfd,'r') as stream:
            def child():
                try:bootstrap.controller_entry(token,stream,events.append)
                except OSError as error:errors.append(str(error))
            thread=threading.Thread(target=child)
            thread.start()
            until=time.monotonic()+1
            while not events and time.monotonic()<until:time.sleep(.001)
            self.assertEqual(events,['CHOPPER_NATIVE_STARTUP_READY '+token])
            os.close(writefd)  # parent leaves before ACK; child may only fail.
            thread.join(timeout=1)
            self.assertFalse(thread.is_alive())
            self.assertEqual(events,['CHOPPER_NATIVE_STARTUP_READY '+token])
            self.assertIn('acknowledgement missing',errors[0])

    def test_controller_caller_aborts_only_before_ack_and_retains_uncertain_cleanup(self):
        bootstrap=host.windows_bootstrap
        for variant in ('normal','create','assign','resume','entry','record','ack','cleanup'):
            with self.subTest(variant=variant):
                windows=Mock();windows._held_identity.return_value=dict(pid=123,created=456)
                child=bootstrap.SuspendedWorker(api=Mock(),dll=Mock(),handles=(11,12,123,456))
                events=[]
                def record(name,value):
                    events.append(name)
                    if variant=='record':raise OSError('record')
                def ack(*args):
                    child.controller_ack_attempted=True
                    if variant=='ack':raise OSError('ack')
                with patch.object(bootstrap,'create_job',return_value=777), \
                        patch.object(child,'start') as start, patch.object(child,'assign') as assign, \
                        patch.object(child,'resume') as resume, patch.object(child,'wait_controller_entry') as entry, \
                        patch.object(child,'acknowledge_controller',side_effect=ack), \
                        patch.object(child,'abort_controller_startup',return_value=dict(no_ack=True)) as abort:
                    for name,call in [('create',start),('assign',assign),('resume',resume),('entry',entry)]:
                        if variant==name or (variant=='cleanup' and name=='entry'):call.side_effect=OSError(name)
                    if variant=='cleanup':abort.side_effect=OSError('cleanup failed')
                    if variant=='normal':child.start_controller(['python'],Mock(),Mock(),{},self.work/'stderr',windows,'a'*64,record)
                    else:self.deny(lambda:child.start_controller(['python'],Mock(),Mock(),{},self.work/'stderr',windows,'a'*64,record))
                    if variant in ('normal','ack'):
                        abort.assert_not_called();windows.close.assert_not_called()
                    elif variant=='cleanup':
                        self.assertIsNone(child.controller_no_start_closed)
                        windows.close.assert_not_called()
                    else:
                        abort.assert_called_once_with(777,windows);windows.close.assert_called_once_with(777)
                        self.assertTrue(child.controller_no_start_closed['no_ack'])
                    if variant=='normal':
                        self.assertEqual(events,['created','entry-ready'])
                        self.assertIn('stdin',start.call_args.kwargs)
                        selected=start.call_args.args[3]
                        self.assertEqual(len(selected['CHOPPER_NATIVE_STARTUP_TOKEN']),64)
                        self.assertGreater(float(selected['CHOPPER_NATIVE_PREPARATION_UNTIL']),time.monotonic())

    def test_persisted_intent_failure_does_not_manufacture_ack_delivery(self):
        bootstrap=host.windows_bootstrap;real=host.module('browser-small-windows')
        windows=Mock();windows.Extended=real.Extended
        windows.query_job.return_value=dict(flags=0x2000,pids=[123])
        windows._held_identity.return_value=dict(pid=123,created=456)
        windows._held_birth.side_effect=lambda dll,handle:456
        def member(handle,job,value):value._obj.value=True;return 1
        windows.kernel.return_value.IsProcessInJob.side_effect=member
        child=bootstrap.SuspendedWorker(api=Mock(),dll=Mock(),handles=(11,12,123,456))
        intent=self.work/'intent.json'
        def record(event,value):
            if event=='ack-intent':
                control.create(intent,value)
                raise OSError('journal failed after persist')
        def entry(*args):child.controller_entry_deadline=time.monotonic()+30;return {}
        with patch.object(bootstrap,'create_job',return_value=777), \
                patch.object(child,'start'),patch.object(child,'assign'),patch.object(child,'resume'), \
                patch.object(child,'poll',return_value=None), \
                patch.object(child,'wait_controller_entry',side_effect=entry), \
                patch.object(child,'abort_controller_startup',return_value=dict(no_ack=True,code=91)) as abort:
            self.deny(lambda:child.start_controller(['python'],Mock(),Mock(),{},self.work/'stderr',windows,'a'*64,record),'journal failed')
        self.assertTrue(intent.exists())
        self.assertFalse(child.controller_ack_attempted)
        abort.assert_called_once_with(777,windows)
        self.assertTrue(child.controller_no_start_closed['no_ack'])
        child.dll.SetInformationJobObject.assert_not_called()

    def test_controller_ack_changes_only_held_startup_job_before_delivery(self):
        import ctypes
        bootstrap = host.windows_bootstrap
        real = host.module('browser-small-windows')
        for variant in ('normal', 'record-fails', 'transition-fails', 'write-fails', 'foreign'):
            with self.subTest(variant=variant):
                events = []
                dll, windows = Mock(), Mock()
                windows.Extended = real.Extended
                windows.query_job.side_effect = [dict(flags=0x2000,pids=[123]), dict(flags=0x800,pids=[123])]
                windows._held_birth.side_effect = lambda dll, handle: 456
                def membership(handle, job, value):
                    value._obj.value = variant != 'foreign'
                    return 1
                windows.kernel.return_value.IsProcessInJob.side_effect = membership
                def transition(job, kind, value, size):
                    events.append(('flags',value._obj.basic.flags))
                    return variant != 'transition-fails'
                dll.SetInformationJobObject.side_effect = transition
                child = bootstrap.SuspendedWorker(api=Mock(),dll=dll,handles=(11,12,123,456))
                child.controller_job = 777
                child.controller_entry_deadline = time.monotonic()+30
                def record(value):
                    events.append(('intent',value['created']))
                    if variant == 'record-fails':raise OSError('record failed')
                def write(line):
                    events.append(('ack',line))
                    if variant == 'write-fails':raise OSError('delivery uncertain')
                with patch.object(child,'poll',return_value=None):
                    if variant == 'normal':
                        proof = child.acknowledge_controller(777,windows,'a'*64,write,record)
                        self.assertTrue(proof['acknowledged'])
                    else:
                        self.deny(lambda: child.acknowledge_controller(777,windows,'a'*64,write,record))
                if variant in ('normal','write-fails'):
                    self.assertTrue(child.controller_ack_attempted)
                    self.deny(lambda:child.abort_controller_startup(777,windows),'quiescence')
                    windows.terminate.assert_not_called()
                else:self.assertFalse(child.controller_ack_attempted)
                if variant in ('normal','write-fails'):
                    self.assertEqual([name for name,_ in events],['intent','flags','ack'])
                else:self.assertFalse(any(name=='ack' for name,_ in events))
                if variant == 'record-fails':dll.SetInformationJobObject.assert_not_called()

    def test_ack_intent_or_delivery_past_deadline_retains_without_repeating_ack(self):
        bootstrap=host.windows_bootstrap;real=host.module('browser-small-windows')
        for after in ('intent','delivery'):
            with self.subTest(after=after):
                tick=[0.];events=[];windows=Mock();dll=Mock()
                windows.Extended=real.Extended
                windows.query_job.side_effect=[dict(flags=0x2000,pids=[123]),dict(flags=0x800,pids=[123])]
                windows._held_birth.side_effect=lambda dll,handle:456
                def member(handle,job,value):value._obj.value=True;return 1
                windows.kernel.return_value.IsProcessInJob.side_effect=member
                child=bootstrap.SuspendedWorker(api=Mock(),dll=dll,handles=(11,12,123,456))
                child.controller_job=777;child.controller_entry_deadline=30.
                def record(value):
                    events.append('intent')
                    if after=='intent':tick[0]=31.
                def write(line):events.append('delivery');tick[0]=31.
                with patch.object(child,'poll',return_value=None), \
                        patch.object(bootstrap.time,'monotonic',side_effect=lambda:tick[0]):
                    self.deny(lambda:child.acknowledge_controller(777,windows,'a'*64,write,record),'stale')
                self.assertEqual(child.controller_ack_attempted,after=='delivery')
                if after=='delivery':
                    self.deny(lambda:child.abort_controller_startup(777,windows),'quiescence')
                windows.terminate.assert_not_called()
                self.assertEqual(events,['intent'] if after=='intent' else ['intent','delivery'])

    def test_post_ack_finish_never_kills_and_requires_complete_empty_job(self):
        bootstrap=host.windows_bootstrap;real=host.module('browser-small-windows')
        for variant in ('normal','incomplete','live','close-fails','occupied'):
            with self.subTest(variant=variant):
                windows=Mock();windows.IncompleteJobCensus=real.IncompleteJobCensus
                child=bootstrap.SuspendedWorker(api=Mock(),dll=Mock(),handles=(11,12,123,456))
                child.controller_job=777;child.controller_ack_attempted=True
                windows.query_job.return_value=dict(flags=0x800,pids=[])
                if variant=='incomplete':windows.query_job.side_effect=[real.IncompleteJobCensus(1,0),dict(flags=0x800,pids=[])]
                if variant=='occupied':windows.query_job.return_value=dict(flags=0x800,pids=[999])
                with patch.object(child,'poll',return_value=None if variant=='live' else 1), \
                        patch.object(child,'wait',return_value=1), patch.object(child,'close') as close, \
                        patch.object(bootstrap.time,'monotonic',side_effect=iter([0.,4.]) if variant=='occupied' else lambda:0.), \
                        patch.object(bootstrap.time,'sleep'):
                    if variant=='close-fails':close.side_effect=OSError('close failed')
                    if variant in ('normal','incomplete'):
                        self.assertTrue(child.finish_controller(windows)['handles_closed'])
                        windows.close.assert_called_once_with(777)
                    else:
                        self.deny(lambda:child.finish_controller(windows))
                        windows.close.assert_not_called()
                    windows.terminate.assert_not_called()

    def test_unassigned_controller_is_stopped_only_while_held_and_never_resumed(self):
        bootstrap=host.windows_bootstrap;real=host.module('browser-small-windows')
        for resumed in (False,True):
            with self.subTest(resumed=resumed):
                api,windows=Mock(),Mock();windows.IncompleteJobCensus=real.IncompleteJobCensus
                windows.query_job.return_value=dict(flags=0x2000,pids=[])
                def member(handle,job,value):value._obj.value=False;return 1
                windows.kernel.return_value.IsProcessInJob.side_effect=member
                child=bootstrap.SuspendedWorker(api=api,dll=Mock(),handles=(11,12,123,456))
                child.controller_job=777;child.resume_attempted=resumed
                with patch.object(child,'poll',return_value=None), \
                        patch.object(child,'wait',return_value=91),patch.object(child,'close'):
                    if resumed:
                        self.deny(lambda:child.abort_controller_startup(777,windows),'uncontained')
                        api.TerminateProcess.assert_not_called();windows.terminate.assert_not_called()
                    else:
                        self.assertTrue(child.abort_controller_startup(777,windows)['direct_never_resumed_stop'])
                        api.TerminateProcess.assert_called_once_with(11,91)
                        windows.terminate.assert_called_once_with(777)

    def test_no_ack_cleanup_reaps_only_exact_job_and_keeps_failures_uncertain(self):
        bootstrap = host.windows_bootstrap
        for variant in ('normal','reap-fails','census-fails','close-fails'):
            with self.subTest(variant=variant):
                api, windows = Mock(),Mock()
                windows.IncompleteJobCensus=host.module('browser-small-windows').IncompleteJobCensus
                child = bootstrap.SuspendedWorker(api=api,dll=Mock(),handles=(11,12,123,456))
                child.controller_job=777
                def membership(handle,job,value):
                    value._obj.value=True
                    return 1
                windows.kernel.return_value.IsProcessInJob.side_effect=membership
                with patch.object(child,'wait',return_value=91) as wait, \
                        patch.object(child,'close') as close:
                    windows.query_job.return_value=dict(flags=0x2000,pids=[])
                    if variant=='reap-fails':wait.side_effect=[subprocess.TimeoutExpired('native worker',0),OSError('reap failed')]
                    if variant=='census-fails':windows.query_job.side_effect=OSError('census failed')
                    if variant=='close-fails':close.side_effect=OSError('close failed')
                    if variant=='normal':
                        self.assertTrue(child.abort_controller_startup(777,windows)['no_ack'])
                        close.assert_called_once_with()
                    else:self.deny(lambda:child.abort_controller_startup(777,windows))
                    windows.terminate.assert_called_once_with(777)
                    if variant=='reap-fails':close.assert_not_called()
                    if variant=='census-fails':close.assert_called_once_with()

    def test_windows_preparation_uses_one_deadline_and_linux_stays_direct(self):
        calls=[]
        with patch.object(controller,'_PREPARATION_UNTIL',None), patch.object(controller,'bounded') as bounded:
            self.assertEqual(controller.preparation_call('linux',lambda:threading.get_ident()),threading.get_ident())
            bounded.assert_not_called()
        tick=[10.]
        def bounded(call,seconds):
            calls.append(seconds)
            return call()
        with patch.object(controller,'_PREPARATION_UNTIL',190.), \
                patch.object(controller.time,'monotonic',side_effect=lambda:tick[0]), \
                patch.object(controller,'bounded',side_effect=bounded), \
                patch.object(controller.sys,'stderr',io.StringIO()):
            controller.preparation_call('first',lambda:None)
            tick[0]=70.
            controller.preparation_call('second',lambda:None)
            tick[0]=191.
            self.deny(lambda:controller.preparation_call('expired',lambda:self.fail('advanced')),'deadline expired')
        self.assertEqual(calls,[180.,120.])

    def test_preparation_timeout_reports_phase_and_waits_for_pending_query(self):
        import contextlib
        messages=io.StringIO();events=[];error=OSError('blocked')
        with patch.object(controller,'_PREPARATION_UNTIL',time.monotonic()+180), \
                patch.object(controller,'bounded',side_effect=error), \
                patch.object(controller,'pending_calls',side_effect=[['query'],['query'],[]]), \
                patch.object(controller.time,'sleep',side_effect=lambda _:events.append('wait')), \
                contextlib.redirect_stderr(messages):
            self.deny(lambda:controller.preparation_call('retained history',lambda:None),'blocked')
        self.assertIn('retained history',messages.getvalue())
        self.assertIn('"pending_calls": true',messages.getvalue())
        self.assertEqual(events,['wait'])

    def test_windows_prestartup_exit_uses_held_bootstrap_job(self):
        directory = self.work/'owner'
        directory.mkdir()
        plan = self.work/'plan.json'
        control.create(plan, {})
        process = Mock(pid=123)
        process.poll.return_value = 1
        windows = Mock()
        windows.query_job.return_value = dict(kill_on_close=True, pids=[])
        with patch.object(host, 'native_windows', return_value=True), \
                patch.object(host, 'module', return_value=windows), \
                    patch.object(host, 'independent_windows_lock_owner'), \
                    patch.object(host.windows_bootstrap, 'create_job', return_value=777), \
                    patch.object(host.windows_bootstrap, 'SuspendedWorker', return_value=process), \
                patch.object(host.subprocess, 'Popen', return_value=process), \
                patch.object(host, 'ControllerInput', return_value=Mock(read=Mock(return_value=b''))):
            self.assertEqual(host.caretaker(plan, self.work/'op.json', directory), 1)
        proof = read_json(directory/'cleanup.json')
        self.assertEqual(proof['cleanup_errors'], [])
        self.assertEqual(proof['remaining'], [])
        windows.terminate.assert_called_once_with(777)
        process.assign.assert_called_once_with(777)
        process.resume.assert_called_once()
        process.wait.assert_called_once()

    def test_windows_bootstrap_failures_through_lock_owner_cleanup(self):
        from contextlib import ExitStack
        variants = ('job-create', 'create', 'assign', 'resume', 'early-exit', 'missing-startup',
                    'missing-ack', 'foreign-job', 'bad-nested-job', 'parent-death', 'early-births',
                    'failed-proof', 'failed-census', 'failed-reap')
        for variant in variants:
            with self.subTest(variant=variant), ExitStack() as stack:
                directory = self.work/variant
                directory.mkdir()
                plan = directory/'plan.json'
                control.create(plan, {})
                if variant not in ('early-exit', 'missing-startup', 'early-births'):
                    control.create(directory/'startup.json', dict(pid=123, handle=456))
                if variant != 'missing-ack':
                    control.create(directory/'supervisor-ready.json', {})
                events = []
                process = Mock(pid=123)
                process.poll.return_value = 1 if variant in ('early-exit', 'early-births') else None
                process.assign.side_effect = lambda job: events.append('assign')
                process.resume.side_effect = lambda: events.append('resume')
                if variant in ('assign', 'resume'):
                    getattr(process, variant).side_effect = OSError('injected '+variant)
                if variant == 'failed-reap':
                    process.wait.side_effect = OSError('injected reap failure')
                windows = Mock()
                windows.duplicate_job.return_value = 789
                windows.process_identity.return_value = dict(parent=os.getpid(), image=sys.executable)
                terminated = [False]
                def terminate(job):
                    self.assertEqual(job, 777)
                    terminated[0] = True
                    events.append('stop')
                windows.terminate.side_effect = terminate
                survivor_seen = []
                def census(job):
                    if terminated[0]:
                        if variant == 'early-births' and not survivor_seen:
                            survivor_seen.append(124)
                            return dict(kill_on_close=True, pids=[124])
                        if variant == 'failed-census':
                            raise OSError('injected unknown census')
                        return dict(kill_on_close=True, pids=[])
                    return dict(kill_on_close=variant != 'bad-nested-job', pids=[123])
                windows.query_job.side_effect = census
                stack.enter_context(patch.object(host, 'native_windows', return_value=True))
                stack.enter_context(patch.object(host, 'module', return_value=windows))
                independent = stack.enter_context(patch.object(host, 'independent_windows_lock_owner'))
                if variant == 'foreign-job':
                    independent.side_effect = OSError('outside inherited Jobs required')
                stack.enter_context(patch.object(host, 'ControllerInput', return_value=Mock(read=Mock(return_value=b''))))
                make_job = stack.enter_context(patch.object(host.windows_bootstrap, 'create_job', return_value=777))
                if variant == 'job-create':
                    make_job.side_effect = OSError('injected Job creation failure')
                stack.enter_context(patch.object(host.windows_bootstrap, 'SuspendedWorker', return_value=process))
                launch = process.start
                if variant == 'create':
                    launch.side_effect = OSError('injected creation failure')
                if variant == 'failed-proof':
                    stack.enter_context(patch.object(host, 'create', side_effect=OSError('injected proof retention failure')))
                if variant in ('missing-startup', 'missing-ack'):
                    tick = iter(i*.5 for i in range(200))
                    stack.enter_context(patch.object(host.time, 'monotonic', side_effect=lambda: next(tick)))
                    stack.enter_context(patch.object(host.time, 'sleep'))
                popen = stack.enter_context(patch.object(host.subprocess, 'Popen'))
                replies = []
                def launch_caretaker(value):
                    caretaker = Mock(pid=321)
                    caretaker.stdin.closed=True
                    def wait(timeout):
                        self.assertEqual(replies, [dict(ok=True, pid=321)])
                        self.assertEqual(host.caretaker(plan, directory/'op.json', directory), 1)
                        return 1
                    caretaker.wait.side_effect = wait
                    return caretaker, directory
                retained = Mock(side_effect=OSError('original host lock retained'))
                run = lambda: self.owner_loop(io.StringIO('{"command":"start"}\n'), replies.append,
                    launch_caretaker, host.stop_locked_caretaker, retained)
                unknown = variant in ('job-create', 'foreign-job', 'failed-proof', 'failed-census', 'failed-reap')
                if unknown:
                    self.deny(run, 'original host lock retained')
                    retained.assert_called_once()
                else:
                    run()
                    retained.assert_not_called()
                    proof = read_json(directory/'cleanup.json')
                    self.assertEqual(proof['remaining'], [])
                    self.assertEqual(proof['cleanup_errors'], [])
                    self.assertTrue(proof['errors'])
                popen.assert_not_called()  # Windows must never fall back to an executing Popen.
                if variant in ('foreign-job', 'job-create'):
                    if variant == 'foreign-job':
                        make_job.assert_not_called()
                    launch.assert_not_called()
                elif variant == 'create':
                    process.assign.assert_not_called()
                    process.resume.assert_not_called()
                elif variant == 'assign':
                    process.resume.assert_not_called()
                    process.kill.assert_called_once()
                    process.wait.assert_called_once()
                else:
                    self.assertIn('stop', events)
                    process.wait.assert_called_once()
                    process.close.assert_called_once()
                if variant == 'early-births':
                    self.assertEqual(survivor_seen, [124])
                if variant not in ('job-create', 'foreign-job', 'create', 'assign', 'resume'):
                    self.assertLess(events.index('assign'), events.index('resume'))
                if variant == 'missing-ack':
                    self.assertFalse((directory/'ready.json').exists())
                    self.assertEqual(read_json(directory/'containment.json')['job_handle'], 777)
                if variant == 'parent-death':
                    self.assertIn('controller death', read_json(directory/'cleanup.json')['errors'][0])

    def test_windows_suspended_bootstrap_only_inherits_fresh_stdio(self):
        from scale_acceptance import native_scale_windows as bootstrap
        api, dll = Mock(), Mock()
        api.DuplicateHandle.side_effect = [101, 102, 103]
        api.CreateProcess.return_value = (201, 202, 123, 124)
        dll.ResumeThread.return_value = 1
        startup = SimpleNamespace()
        with patch.dict(sys.modules, {'_winapi': api, 'msvcrt': Mock()}), \
                patch.object(bootstrap, 'kernel', return_value=dll), \
                patch.object(bootstrap.subprocess, 'STARTUPINFO', return_value=startup, create=True), \
                patch.object(bootstrap.subprocess, 'STARTF_USESTDHANDLES', 256, create=True):
            worker = bootstrap.SuspendedWorker()
            worker.start(['python', '-c', 'pass'], Mock(), Mock(), {'ONLY': 'env'})
            args = api.CreateProcess.call_args.args
            self.assertEqual(args[5], 0x404)  # suspended + Unicode environment; no breakaway
            self.assertTrue(args[4])
            self.assertEqual(args[6], {'ONLY': 'env'})
            self.assertEqual(startup.lpAttributeList, dict(handle_list=[101, 102, 103]))
            self.assertEqual((startup.hStdInput, startup.hStdOutput, startup.hStdError), (101, 102, 103))
            dll.ResumeThread.assert_not_called()
            worker.assign(777)
            dll.AssignProcessToJobObject.assert_called_once_with(777, 201)
            worker.resume()
            dll.ResumeThread.assert_called_once_with(202)
            worker.close()
            self.assertEqual([c.args[0] for c in api.CloseHandle.call_args_list], [103, 102, 101, 202, 201])
        for failure in ('duplicate', 'create'):
            api.reset_mock()
            api.DuplicateHandle.side_effect = [101, OSError('duplicate failed')] if failure == 'duplicate' else [101, 102, 103]
            api.CreateProcess.side_effect = OSError('create failed')
            with patch.dict(sys.modules, {'_winapi': api, 'msvcrt': Mock()}), \
                    patch.object(bootstrap, 'kernel', return_value=dll), \
                    patch.object(bootstrap.subprocess, 'STARTUPINFO', return_value=startup, create=True), \
                    patch.object(bootstrap.subprocess, 'STARTF_USESTDHANDLES', 256, create=True):
                self.deny(lambda: bootstrap.SuspendedWorker().start(['python'], Mock(), Mock(), {}), 'failed')
            self.assertEqual([c.args[0] for c in api.CloseHandle.call_args_list],
                             [101] if failure == 'duplicate' else [103, 102, 101])

    def test_windows_constructor_failure_precedes_process_creation(self):
        from contextlib import ExitStack
        from scale_acceptance import native_scale_windows as bootstrap
        directory = self.work/'constructor-failure'
        directory.mkdir()
        plan = directory/'plan.json'
        control.create(plan, {})
        api, dll, windows = Mock(), Mock(), Mock()
        api.DuplicateHandle.side_effect = [101, 102, 103]
        api.CreateProcess.return_value = (201, 202, 123, 124)
        windows.query_job.return_value = dict(kill_on_close=True, pids=[])
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {'_winapi': api, 'msvcrt': Mock()}))
            stack.enter_context(patch.object(bootstrap, 'kernel', return_value=dll))
            stack.enter_context(patch.object(bootstrap.subprocess, 'STARTUPINFO', return_value=SimpleNamespace(), create=True))
            stack.enter_context(patch.object(bootstrap.subprocess, 'STARTF_USESTDHANDLES', 256, create=True))
            stack.enter_context(patch.object(host, 'native_windows', return_value=True))
            stack.enter_context(patch.object(host, 'module', return_value=windows))
            stack.enter_context(patch.object(host, 'independent_windows_lock_owner'))
            stack.enter_context(patch.object(host, 'ControllerInput', return_value=Mock()))
            stack.enter_context(patch.object(bootstrap, 'create_job', return_value=777))
            stack.enter_context(patch.object(bootstrap, 'SuspendedWorker', side_effect=MemoryError('owner allocation failed')))
            self.assertEqual(host.caretaker(plan, directory/'operation.json', directory), 1)
        self.assertEqual(api.CreateProcess.call_count, 0)
        self.assertEqual(read_json(directory/'cleanup.json')['cleanup_errors'], [])

    def test_windows_ambiguous_creation_cannot_use_empty_job_to_release_lock(self):
        from contextlib import ExitStack
        from scale_acceptance import native_scale_windows as bootstrap
        directory = self.work/'unknown-creation'
        directory.mkdir()
        plan = directory/'plan.json'
        control.create(plan, {})
        api, dll, windows = Mock(), Mock(), Mock()
        api.DuplicateHandle.side_effect = [101, 102, 103]
        api.CreateProcess.side_effect = MemoryError('post-create handle transfer failed')
        windows.query_job.return_value = dict(kill_on_close=True, pids=[])
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {'_winapi': api, 'msvcrt': Mock()}))
            stack.enter_context(patch.object(bootstrap, 'kernel', return_value=dll))
            stack.enter_context(patch.object(bootstrap.subprocess, 'STARTUPINFO', return_value=SimpleNamespace(), create=True))
            stack.enter_context(patch.object(bootstrap.subprocess, 'STARTF_USESTDHANDLES', 256, create=True))
            stack.enter_context(patch.object(host, 'native_windows', return_value=True))
            stack.enter_context(patch.object(host, 'module', return_value=windows))
            stack.enter_context(patch.object(host, 'independent_windows_lock_owner'))
            stack.enter_context(patch.object(host, 'ControllerInput', return_value=Mock()))
            stack.enter_context(patch.object(bootstrap, 'create_job', return_value=777))
            self.assertEqual(host.caretaker(plan, directory/'operation.json', directory), 1)
        self.assertEqual(api.CreateProcess.call_count, 1)
        proof = read_json(directory/'cleanup.json')
        self.assertTrue(any('creation ownership unknown' in error for error in proof['cleanup_errors']))
        self.deny(lambda: host.stop_locked_caretaker(Mock(), directory), 'cannot prove owned cleanup')

    def test_windows_bootstrap_job_configuration_and_denial(self):
        import ctypes
        windows = host.module('browser-small-windows')  # definitions only, no native API
        dll = Mock()
        dll.CreateJobObjectW.return_value = 777
        flags = []
        def configure(handle, kind, info, size):
            flags.append(ctypes.cast(info, ctypes.POINTER(windows.Extended)).contents.basic.flags)
            return True
        dll.SetInformationJobObject.side_effect = configure
        with patch.object(host.windows_bootstrap, 'kernel', return_value=dll), \
                patch.object(windows, 'close') as close:
            self.assertEqual(host.windows_bootstrap.create_job(windows), 777)
            self.assertEqual(flags, [0x2000])
            close.assert_not_called()
            dll.SetInformationJobObject.side_effect = None
            dll.SetInformationJobObject.return_value = False
            self.deny(lambda: host.windows_bootstrap.create_job(windows), 'Windows API failed')
            close.assert_called_once_with(777)
            dll.CreateJobObjectW.return_value = 0
            self.deny(lambda: host.windows_bootstrap.create_job(windows), 'Windows API failed')
            self.assertEqual(close.call_count, 1)

    def test_windows_primary_thread_failures_never_resume_again(self):
        from scale_acceptance import native_scale_windows as bootstrap
        dll, api = Mock(), Mock()
        worker = bootstrap.SuspendedWorker(api, dll, (201, 202, 123, 124))
        dll.AssignProcessToJobObject.return_value = False
        self.deny(lambda: worker.assign(777), 'assignment failed')
        dll.ResumeThread.assert_not_called()
        for result in (0, 2, 0xffffffff):
            dll.ResumeThread.return_value = result
            self.deny(worker.resume, 'resume failed')
        self.assertEqual(dll.ResumeThread.call_count, 3)
        api.WaitForSingleObject.return_value = 258
        self.assertIsNone(worker.poll())
        api.WaitForSingleObject.return_value = 0
        api.GetExitCodeProcess.return_value = 91
        self.assertEqual(worker.wait(1), 91)

    def test_controller_input_polls_owned_raw_read_end_and_closes(self):
        reader = host.ControllerInput.__new__(host.ControllerInput)
        reader.fd = 987
        with patch.object(host, 'native_windows', return_value=True), \
                patch.object(host.windows_bootstrap, 'pipe_available', side_effect=[1, -1, 0]), \
                patch.object(host.os, 'read', return_value=b'.') as read, \
                patch.object(host.os, 'close') as close:
            self.assertEqual(reader.read(), b'.')
            self.assertEqual(reader.read(), b'')
            self.assertIsNone(reader.read(timeout=0))
            read.assert_called_once_with(987, 1)
            reader.close()
            close.assert_called_once_with(987)
        with patch.object(host.os, 'dup', return_value=987) as duplicate, \
                patch.object(host.sys, 'stdin') as stream:
            owned = host.ControllerInput()
            duplicate.assert_called_once_with(stream.fileno.return_value)
            self.assertEqual(owned.fd, 987)

    def test_windows_publication_retries_only_transient_metadata_errors(self):
        from scale_acceptance import guard
        for windows, code, retry in ((True, 5, True), (True, 32, True), (False, 5, False), (True, 87, False), (True, None, False)):
            with self.subTest(windows=windows, code=code):
                error = OSError('injected publication conflict')
                error.winerror = code
                writer = Mock(side_effect=[error, None] if retry else error)
                with patch.object(host, 'native_windows', return_value=windows), patch.object(guard, 'load_runner', return_value=Mock(write_json=writer)):
                    if retry:
                        host.publish(self.work/'sample.json', dict(value=17))
                        self.assertEqual(writer.call_args_list[0], writer.call_args_list[1])
                    else:
                        self.deny(lambda: host.publish(self.work/'sample.json', dict(value=17)), 'publication conflict')
                self.assertEqual(writer.call_count, 2 if retry else 1)

    def test_windows_publication_conflict_cannot_extend_operation_bound(self):
        from scale_acceptance import guard
        error = OSError('persistent publication conflict')
        error.winerror = 5
        writer = Mock(side_effect=error)
        ticks = iter([0, .1, .2, .3, 1.2])
        with patch.object(host, 'native_windows', return_value=True), patch.object(guard, 'load_runner', return_value=Mock(write_json=writer)), patch.object(host.time, 'monotonic', side_effect=lambda: next(ticks, 1.2)), patch.object(host.time, 'sleep'):
            self.deny(lambda: host.publish(self.work/'sample.json', {}), 'persistent publication conflict')
        self.assertEqual(writer.call_count, 2)

    def test_publication_probe_saves_failure_before_pending_owner_retention(self):
        from scale_acceptance import native_tiny
        for pending in (False, True):
            with self.subTest(pending=pending):
                directory = self.work/str(pending)
                held = Mock()
                held.proof.return_value = dict(owner_pid=123)
                context = Mock(__enter__=Mock(return_value=held))
                def exit(*args):
                    saved = read_json(directory/'failure.json')
                    self.assertEqual(saved['error'], "OSError('probe query failed')")
                    self.assertEqual(saved['pending_callbacks'], pending)
                    self.assertTrue(held.cleanup_uncertain)
                    return False
                context.__exit__ = Mock(side_effect=exit)
                with patch.dict(native_storage_rename_probe.__globals__,os=SimpleNamespace(name='nt',getpid=os.getpid)), \
                        patch.object(native_tiny,'ReadBudget'), patch.object(native_tiny,'budget',None,create=True), \
                        patch.object(host,'module',return_value=Mock(process_identity=Mock(return_value=dict(pid=456)))), \
                        patch.object(host,'HostLock',return_value=context), \
                        patch.object(host,'bounded',side_effect=OSError('probe query failed')), \
                        patch.object(host,'pending_calls',return_value=[object()] if pending else []):
                    self.deny(lambda:native_storage_rename_probe(directory),'probe query failed')
                context.__exit__.assert_called_once()

    def test_initial_sample_readers_never_observe_partial_json(self):
        directory = self.work/'owner'
        directory.mkdir()
        plan = directory/'plan.json'
        control.create(plan, {})
        control.create(directory/'startup.json', dict(pid=123, handle=456))
        control.create(directory/'supervisor-ready.json', dict(fake_only=True))
        process = Mock(pid=123)
        process.poll.return_value = None
        windows = Mock()
        windows.duplicate_job.return_value = 789
        windows.process_identity.return_value = dict(parent=os.getpid(), image=sys.executable)
        windows.query_job.side_effect = [dict(kill_on_close=True, pids=[123]),
            dict(kill_on_close=True, pids=[123]), dict(kill_on_close=True, pids=[])]
        original_open = Path.open
        partial = []
        sample = directory/'owner-sample.json'
        windows.replace_control_snapshot.side_effect = os.replace  # Fake Windows API; real atomic publication.
        def reader_at_write(path, mode='r', *args, **kwargs):
            stream = original_open(path, mode, *args, **kwargs)
            if any(flag in mode for flag in 'wxa') and path.parent == directory and path.name.startswith('owner-sample') and sample.exists():
                try:
                    json.loads(sample.read_text())
                except json.JSONDecodeError as error:
                    partial.append(str(error))
            return stream
        with patch.object(host, 'native_windows', return_value=True), patch.object(host, 'module', return_value=windows), \
                    patch.object(host, 'independent_windows_lock_owner'), \
                    patch.object(host.windows_bootstrap, 'create_job', return_value=777), \
                    patch.object(host.windows_bootstrap, 'SuspendedWorker', return_value=process), patch.object(host.subprocess, 'Popen', return_value=process), patch.object(host, 'ControllerInput', return_value=Mock(read=Mock(return_value=b''))), patch.object(Path, 'open', reader_at_write):
            self.assertEqual(host.caretaker(plan, directory/'op.json', directory), 1)
        self.assertEqual(partial, [], 'reader observed a partially published initial sample')
        self.assertEqual(read_json(sample)['pids'], [123])

    def test_linux_fake_parent_death_retains_group_census_and_reaps(self):
        parent = self.work/'fake-delegation'
        parent.mkdir()
        (parent/'cgroup.controllers').write_text('fake-only kernel interface')
        plan = self.work/'plan.json'
        control.create(plan, dict(linux_cgroup_parent=str(parent)))
        directory = self.work/'owner'
        directory.mkdir()
        control.create(directory/'startup.json', dict(pid=123))
        control.create(directory/'supervisor-ready.json', dict(fake_only=True))
        process = Mock(pid=123)
        process.poll.return_value = None
        original = Path.mkdir
        def fake_kernel_mkdir(p, *args, **kwargs):
            original(p, *args, **kwargs)
            if p.name.startswith('chopper-native-'):
                (p/'cgroup.kill').write_text('fake only')
                (p/'cgroup.procs').write_text('')
        libc = Mock()
        libc.prctl.return_value = 0
        with patch.object(host, 'native_windows', return_value=False), patch.object(host, 'require_cgroup_v2') as kernel_check, \
                patch.object(Path, 'mkdir', fake_kernel_mkdir), patch.object(host.ctypes, 'CDLL', return_value=libc), \
                patch.object(host.subprocess, 'Popen', return_value=process), patch.object(host, 'census_linux', side_effect=[[123], []]), \
                patch.object(host.os, 'waitpid', side_effect=ChildProcessError), patch.object(host.os, 'WNOHANG', 1, create=True), \
                patch.object(host, 'ControllerInput', return_value=Mock(read=Mock(return_value=b''))):
            self.assertEqual(host.caretaker(plan, self.work/'op.json', directory), 1)
        kernel_check.assert_called_once_with(parent)
        libc.prctl.assert_called_once_with(36, 1, 0, 0, 0)
        process.wait.assert_called_once()
        receipt = read_json(directory/'cleanup.json')
        self.assertIn('controller death', receipt['errors'][0])
        self.assertEqual(receipt['remaining'], [])
        self.failures.append(receipt)

    def test_linux_unreaped_worker_retains_host_lock(self):
        parent = self.work/'fake-delegation'
        parent.mkdir()
        (parent/'cgroup.controllers').write_text('fake-only kernel interface')
        plan = self.work/'plan.json'
        control.create(plan, dict(linux_cgroup_parent=str(parent)))
        directory = self.work/'owner'
        directory.mkdir()
        control.create(directory/'startup.json', dict(pid=123))
        control.create(directory/'supervisor-ready.json', dict(fake_only=True))
        process = Mock(pid=123)
        process.poll.return_value = None
        process.wait.side_effect = TimeoutError('injected unreaped worker')
        original = Path.mkdir
        def fake_kernel_mkdir(p, *args, **kwargs):
            original(p, *args, **kwargs)
            if p.name.startswith('chopper-native-'):
                (p/'cgroup.kill').write_text('fake only')
                (p/'cgroup.procs').write_text('')
        libc = Mock()
        libc.prctl.return_value = 0
        with patch.object(host, 'native_windows', return_value=False), patch.object(host, 'require_cgroup_v2') as kernel_check, \
                patch.object(Path, 'mkdir', fake_kernel_mkdir), patch.object(host.ctypes, 'CDLL', return_value=libc), \
                patch.object(host.subprocess, 'Popen', return_value=process), patch.object(host, 'census_linux', side_effect=[[123], []]), \
                patch.object(host.os, 'waitpid', side_effect=ChildProcessError), patch.object(host.os, 'WNOHANG', 1, create=True), \
                patch.object(host, 'ControllerInput', return_value=Mock(read=Mock(return_value=b''))), \
                patch.object(host, 'retain_host_lock', side_effect=OSError('host lock retained'), create=True) as retained:
            self.deny(lambda: host.caretaker(plan, self.work/'op.json', directory), 'host lock retained')
        retained.assert_called_once_with('Linux')
        kernel_check.assert_called_once_with(parent)
        libc.prctl.assert_called_once_with(36, 1, 0, 0, 0)
        process.wait.assert_called_once()
        receipt = read_json(directory/'cleanup.json')
        self.assertIn('injected unreaped worker', receipt['cleanup_errors'])
        self.assertEqual(receipt['remaining'], [])
        self.failures.append(receipt)

    def test_caretaker_death_before_supervisor_pulse_still_cleans_captured_group(self):
        group = self.work/'synthetic-cgroup-interface'
        group.mkdir()
        (group/'cgroup.procs').write_text('')
        (group/'cgroup.kill').write_text('not yet stopped')
        s = group.stat()
        control.create(self.work/'containment.json', dict(worker_pid=123, cgroup=str(group),
                       cgroup_identity=[s.st_dev, s.st_ino]))
        owner = host.Caretaker.__new__(host.Caretaker)
        owner.directory = self.work
        owner.process = Mock()
        owner.process.poll.return_value = 1
        owner.process.wait.return_value = 1
        owner.backup_job, owner.backup_cgroup = None, None
        with patch.object(host, 'native_windows', return_value=False):
            self.deny(owner.finish, 'caretaker failure')
        self.assertEqual((group/'cgroup.kill').read_text(), '1')
        self.assertEqual(owner.backup_cgroup, group)

    def test_storage_retains_highwater_deleted_failures_and_symlink_denial(self):
        storage = monitor.Storage()
        f = self.work/'partial.csv'
        f.write_bytes(b'x'*1024)
        first = storage.sample([self.work])
        f.write_bytes(b'x')
        self.assertGreaterEqual(storage.sample([self.work]), first)
        f.unlink()
        self.assertGreaterEqual(storage.sample([self.work]), first)
        f.write_bytes(b'synthetic symlink observation')
        original = Path.lstat
        def symlink_metadata(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return os.stat_result((stat.S_IFLNK | 0o777, *value[1:])) if path == f else value
        with patch.object(Path, 'lstat', symlink_metadata):
            self.deny(lambda: storage.sample([self.work]), 'symlink')

    def test_numeric_progress_not_logs_quota_or_phase_oscillation(self):
        tick = [0.]
        m = monitor.Monitor.__new__(monitor.Monitor)
        m.disk_operation = threading.Lock()
        m.clock = lambda: tick[0]
        m.last_progress, m.progress = 0, None
        m.useful(('generated-bytes', 100))
        tick[0] = 1
        m.useful(('checkpoint', 10))
        tick[0] = 10
        m.useful(('generated-bytes', 100))
        m.useful(('checkpoint', 10))
        self.assertEqual(m.last_progress, 1)
        self.deny(lambda: m.useful(('quota-seconds', 100)), 'unknown')
        self.deny(lambda: m.useful(('native-rows', -1)), 'negative')

    def test_external_python_exe_expected_bytes_not_merely_recorded(self):
        obj = identity.Identity.__new__(identity.Identity)
        obj.external = {}
        tool = self.work/'python'
        tool.write_bytes(b'fake selected Python executable')
        obj.pin(dict(path=str(tool), sha256=sha256(tool)))
        self.deny(lambda: obj.pin(dict(path=str(tool), sha256='0'*64)), 'expected external bytes')
        self.deny(lambda: obj.pin(dict(path=str(tool), sha256='record-only')), 'SHA-256')

    def test_disabled_missing_fields_platform_source_reservation_and_limits(self):
        p = self.plan()
        p['host']['os'] = p['os']  # Synthetic Linux contract on either test host.
        control.validate(p)
        for field, value in (('actions_enabled', False), ('limits', {**control.LIMITS, 'generation_seconds': 7200}),
                             ('os', 'Windows'), ('source_reservation', dict(id='bare-label'))):
            bad = copy.deepcopy(p)
            bad[field] = value
            self.deny(lambda: control.validate(bad))
        for field in ('fixtures', 'reservation', 'volumes', 'source_reservation'):
            bad = copy.deepcopy(p)
            del bad[field]
            self.deny(lambda: control.validate(bad))

    def test_monitor_source_physical_volume_storage_lock_deadline_drifts(self):
        p = self.host_plan()
        lock, campaign = Mock(), Mock()
        lock.proof.return_value = dict(mechanism='fake-exclusive-test-interface')
        tick = [0.]
        m = monitor.Monitor(p, lock, campaign, self.work/'samples.jsonl', lambda: tick[0])
        free = Mock(free=201*control.GIB)
        with patch.object(monitor.shutil, 'disk_usage', return_value=free):
            m.sample(start=True)
            m.phase(3600)
            tick[0] = 601
            self.deny(m.hot_sample, 'no useful progress')
            tick[0] = 1
            free.free = 19*control.GIB
            self.deny(m.sample, 'physical free')
            free.free = 199*control.GIB
            self.deny(lambda: m.sample(start=True), 'physical free')
            free.free = 201*control.GIB
            with patch.object(m.storage, 'sample', return_value=160*control.GIB):
                self.deny(m.sample, 'storage high water')
            with patch.object(m.source_storage, 'sample', return_value=1024**2+1):
                self.deny(m.sample, 'source/cache/artifact')
            m.volumes[0] = (self.work, 'wrong-device')
            self.deny(m.sample, 'volume mapping')
            m.volumes[0] = (self.work, str(self.work.stat().st_dev))
            lock.check.side_effect = OSError('exclusive reservation ownership lost')
            self.deny(m.sample, 'reservation')
            lock.check.side_effect = None
            f = Path(p['product']['root'])/'source.py'
            f.write_text('drift')
            self.deny(m.sample, 'source freeze')
        m.deadline = 0
        self.deny(m.sample, 'phase deadline')

    def test_git_blob_maps_dirty_and_source_roles(self):
        root = self.work/'source'
        root.mkdir()
        f = root/'Cargo.toml'
        f.write_bytes(b'fixed')
        import hashlib
        oid = hashlib.sha1(b'blob 5\0fixed').hexdigest()
        group = dict(root=str(root), commit='c'*40, tree='d'*40,
                     git_blobs={'Cargo.toml': oid}, sha256={'Cargo.toml': sha256(f)})
        def git(_, *args):
            if args == ('rev-parse', 'HEAD'):
                return group['commit']
            if args == ('rev-parse', 'HEAD^{tree}'):
                return group['tree']
            if args[0] == 'status':
                return ''
            return '100644 blob '+oid+'\tCargo.toml\0'
        with patch.object(identity, 'git', side_effect=git), patch.object(identity, 'REQUIRED', {'Cargo.toml'}):
            identity.source_map(group)
            changed = copy.deepcopy(group)
            changed['git_blobs']['Cargo.toml'] = 'e'*40
            self.deny(lambda: identity.source_map(changed), 'blob map')
            f.write_bytes(b'drift')
            self.deny(lambda: identity.source_map(group), 'byte mismatch')
        with patch.object(identity, 'git', return_value='dirty'):
            self.deny(lambda: identity.source_map(group), 'Git source')
        with patch.object(identity, 'git', side_effect=lambda root, *args:
                          ' M Cargo.toml' if args[0] == 'status' else git(root, *args)):
            self.deny(lambda: identity.source_map(group), 'dirty source root')

    def test_full_identity_role_feature_build_package_python_mutations(self):
        p = self.host_plan()
        kind,member,target = (('windows_x86_64','chopper.exe','x86_64-pc-windows-msvc')
            if p['os']=='Windows' else ('linux_x86_64','chopper','x86_64-unknown-linux-gnu'))
        p['product'].update(commit=identity.PRODUCT, tree=identity.TREE)
        p['python'] = dict(path=str(Path(sys.executable).resolve()), sha256=sha256(Path(sys.executable).resolve()), version=sys.version)
        p['environment_sha256'] = identity.environment_digest()
        package_receipt = self.work/'artifacts/package-receipt.json'
        package_size = Path(p['package']['path']).stat().st_size
        control.create(package_receipt, dict(schema_version=1, packaging_schema_version=1,
               release_source_commit=identity.PRODUCT, release_source_tree=identity.TREE, dirty_source=False,
               native={kind:dict(target=target,sha256=p['executable']['sha256'])},
               packages={'tool': dict(bytes=package_size, sha256=p['package']['sha256'])},
               package_members={'tool': {member: dict(bytes=package_size, sha256=p['executable']['sha256'])}}))
        p['package_receipt'] = dict(path=str(package_receipt), sha256=sha256(package_receipt))
        (Path(p['product']['root'])/'Cargo.toml').write_text('fake Cargo source')
        p['product']['sha256']['Cargo.toml'] = sha256(Path(p['product']['root'])/'Cargo.toml')
        receipt = self.work/'artifacts/runner-status.json'
        control.create(receipt, dict(summary=dict(incomplete=0), attempts=[dict(status='passed', exit_code=0,
                       inputs={'Cargo.toml': dict(sha256=p['product']['sha256']['Cargo.toml'])}, artifacts={member: dict(sha256=p['executable']['sha256'])})]))
        proof = self.work/'artifacts/build-proof.json'
        reconciliation = self.work/'artifacts/reconciliation.json'
        control.create(reconciliation, dict(fake=True))
        raw = dict(schema='native-scale-build-binding-v2', features=[], product_commit=identity.PRODUCT,
                   product_tree=identity.TREE, source_sha256=p['product']['sha256'],
                   artifact_build_commit=identity.BUILD, artifact_build_tree=identity.BUILD_TREE,
                   artifact_build_source_sha256=p['product']['sha256'],
                   source_reconciliation=dict(path=str(reconciliation), sha256=sha256(reconciliation)),
                   executable_sha256=p['executable']['sha256'], package_receipt_sha256=p['package_receipt']['sha256'],
                   package_sha256=p['package']['sha256'], runner_receipts=[dict(path=str(receipt), sha256=sha256(receipt))])
        control.create(proof, raw)
        p['build_proof'] = dict(path=str(proof), sha256=sha256(proof))
        def fake_source(g):
            root = Path(g['root'])
            return root, identity.frozen_metadata(root, list(g['sha256']))
        with patch.object(identity, 'Lineage'), \
                patch.object(identity, 'source_map', side_effect=fake_source), \
                patch.object(identity, '__file__', str(Path(p['harness']['root'])/'scripts/scale_acceptance/native_scale_identity.py')), \
                patch.object(identity.shutil, 'which', return_value=p['tools'][0]['path']), \
                patch.object(identity, 'RECONCILIATION', sha256(reconciliation)), \
                patch.object(identity, 'producing_source', return_value=p['product']['sha256']), \
                patch.object(identity, 'PACKAGE_RECEIPT', p['package_receipt']['sha256']):
            identity.Identity(p)
            for label, dependencies in (('empty', [dict(root=p['dependencies'][0]['root'], inputs=[], sha256={})]),
                                        ('unrelated', [dict(root=p['dependencies'][0]['root'], inputs=['tool'], sha256={'tool': p['tools'][0]['sha256']})])):
                with self.subTest(bypass=label):
                    bad = copy.deepcopy(p)
                    bad['dependencies'] = dependencies
                    self.deny(lambda: identity.Identity(bad), 'runtime')
            with self.subTest(bypass='unrelated-build-attempts'):
                (Path(p['product']['root'])/'Cargo.toml').write_text('fake Cargo source')
                p['product']['sha256']['Cargo.toml'] = sha256(Path(p['product']['root'])/'Cargo.toml')
                raw['source_sha256'] = p['product']['sha256']
                receipt.write_text(json.dumps(dict(summary=dict(incomplete=0), attempts=[
                    dict(status='passed', exit_code=0, inputs={'Cargo.toml': dict(sha256=p['product']['sha256']['Cargo.toml'])}, artifacts={}),
                    dict(status='passed', exit_code=0, inputs={}, artifacts={member: dict(sha256=p['executable']['sha256'])})])))
                raw['runner_receipts'][0]['sha256'] = sha256(receipt)
                proof.write_text(json.dumps(raw))
                p['build_proof']['sha256'] = sha256(proof)
                self.deny(lambda: identity.Identity(p), 'build input/artifact')
            for key, value in (('features', ['unexpected-feature']), ('executable', {**p['executable'], 'sha256': '0'*64}),
                               ('python', {**p['python'], 'sha256': '0'*64}),
                               ('harness', {**p['harness'], 'root': p['product']['root']}),
                               ('product', {**p['product'], 'tree': 'f'*40}), ('environment_sha256', '0'*64)):
                bad = copy.deepcopy(p)
                bad[key] = value
                self.deny(lambda: identity.Identity(bad))
            proof.write_text(json.dumps({**raw, 'source_sha256': {'changed': '0'*64}}))
            p['build_proof']['sha256'] = sha256(proof)
            self.deny(lambda: identity.Identity(p), 'build/package/source proof')

    def test_windows_peer_strict_platform_size_shape_source_and_hash(self):
        p = self.work/'linux-report.json'
        raw = dict(os='Linux', slot='LinuxD', product=identity.PRODUCT, passed=True,
                   host=dict(os='Linux'), plan_sha256='b'*64,
                   report=dict(shape='D', source_sha256='a'*64, rows=99_999_999))
        p.write_text(json.dumps(raw))
        campaign = self.work/'campaign'
        campaign.mkdir()
        record = campaign/'LinuxD-verified.json'
        record.write_text(json.dumps(dict(sha256=sha256(p), plan_sha256='b'*64)))
        plan = dict(os='Windows', campaign=str(campaign), product=dict(commit=identity.PRODUCT), fixtures=dict(D=dict(sha256='a'*64)),
                    peers=dict(D=dict(path=str(p), sha256=sha256(p), source_sha256='a'*64, plan_sha256='b'*64)))
        self.assertEqual(controller.peer_report(plan, 'D'), raw['report'])
        self.assertEqual(controller.peer_report(plan, 'D', 'a'*64), raw['report'])
        self.deny(lambda: controller.peer_report(plan, 'D', 'c'*64), 'actual checkpoint SHA')
        for fields in (dict(os='Windows'), dict(slot='LinuxG'), dict(passed=False),
                       dict(report={**raw['report'], 'rows': 9_999_999}),
                       dict(report={**raw['report'], 'source_sha256': 'b'*64})):
            p.write_text(json.dumps({**raw, **fields}))
            plan['peers']['D']['sha256'] = sha256(p)
            record.write_text(json.dumps(dict(sha256=sha256(p), plan_sha256='b'*64)))
            self.deny(lambda: controller.peer_report(plan, 'D'))
        plan['peers']['D']['sha256'] = '0'*64
        self.deny(lambda: controller.peer_report(plan, 'D'), 'hash')

    def test_runner_additive_phases_never_chain_generation_into_run(self):
        data, _ = self.fixture()
        plan = dict(python=dict(path=sys.executable), executable=dict(path='/never/launch/chopper'),
                    fixtures=dict(D=dict(sha256='a'*64)))
        for stage in ('generation', 'Run', 'verify'):
            op = dict(stage=stage, shape='D', data=str(data), report=str(self.work/'report.json'),
                      proposal=str(self.work/'proposal.json'), approval=str(self.work/'approval.json'),
                      run_stdout=str(self.work/'run-stdout.log'))
            p = controller.runner_plan(plan, op, self.work/'plan.json', self.work/'op.json', self.work/'worker')
            self.assertEqual(len(p['steps']), 1)
            command = p['steps'][0]
            self.assertEqual(command['id'], stage)
            if stage == 'Run':
                self.assertEqual(command['argv'][0], '/never/launch/chopper')
                self.assertIn(str(Path('D')/'input.csv'), command['inputs'])
            else:
                self.assertNotIn('/never/launch/chopper', command['argv'])
        from scale_acceptance import recipe
        self.assertEqual(recipe.dimensions('D', 'native'), (100, 99_999_999, 10_000_000_000))
        self.assertEqual(recipe.dimensions('G', 'native'), (1000, 9_999_999, 10_000_000_000))

    def test_generation_phase_returns_checkpoint_without_run(self):
        data, meta = self.fixture()
        generated = self.work/'generated'
        original = generate.prepare
        def tiny_only(directory, shape, runtime):
            return original(directory, shape, runtime, 127)
        with patch.object(generate, 'prepare', side_effect=tiny_only), patch.object(controller, 'verify') as output_verify:
            controller.phase(dict(fixtures=dict(D=self.tiny_recipe(meta))),
                             dict(stage='generation', shape='D', data=str(generated)))
        self.assertEqual(read_json(generated/'checkpoint.json')['sha256'], meta['sha256'])
        self.assertFalse((generated/'output').exists())
        output_verify.assert_not_called()

    def test_prelaunch_actual_job_fixture_input_and_executable_hash_approval(self):
        data = self.work/'data'
        approved = dict(input_sha256='a'*64, checkpoint=dict(sha256='a'*64), actual={
            str(data/n): dict(sha256='a'*64) for n in ('job.json', 'fixture.json', 'checkpoint.json')})
        attempt = dict(runtime=dict(executable_sha256='b'*64, executable='/fake/chopper'),
                       inputs={str(Path('data')/n): dict(sha256='a'*64)
                               for n in ('input.csv', 'job.json', 'fixture.json', 'checkpoint.json')})
        op = dict(data=str(data), shape='D')
        plan = dict(executable=dict(path='/fake/chopper', sha256='b'*64), fixtures=dict(D=dict(sha256='a'*64)))
        controller.check_run_inputs(attempt, self.work, op, plan, approved)
        for name in ('input.csv', 'job.json', 'fixture.json', 'checkpoint.json'):
            bad = copy.deepcopy(attempt)
            bad['inputs'][str(Path('data')/name)]['sha256'] = '0'*64
            self.deny(lambda: controller.check_run_inputs(bad, self.work, op, plan, approved), 'hash' if name != 'input.csv' else 'SHA')
        bad = copy.deepcopy(attempt)
        bad['runtime']['executable_sha256'] = '0'*64
        self.deny(lambda: controller.check_run_inputs(bad, self.work, op, plan, approved), 'executable')
        self.deny(lambda: controller.check_run_inputs(attempt, self.work, op, plan, {**approved, 'actual': {}}), 'complete approved')
        for bad in ({**approved, 'input_sha256': '0'*64},
                    {**approved, 'checkpoint': dict(sha256='0'*64)},
                    {k: v for k, v in approved.items() if k != 'input_sha256'}):
            self.deny(lambda: controller.check_run_inputs(attempt, self.work, op, plan, bad))
        plan['python'] = dict(path='/fake/python', sha256='c'*64)
        attempt['runtime'] = dict(executable='/fake/python', executable_sha256='c'*64)
        controller.check_run_inputs(attempt, self.work, {**op, 'stage': 'verify'}, plan, approved)

    def test_execute_hash_gap_has_external_samples_and_cleanup_samples(self):
        plan_path = self.work/'plan.json'
        control.create(plan_path, dict(bound='fake plan'))
        p = dict(owned_root=str(self.work))
        m, lock = Mock(), Mock()
        calls = []
        class FakeOwner:
            def __init__(self, plan, op, directory, held_lock):
                self.directory = directory
                directory.mkdir()
                self.pulses = 0
            def ready(self, capacity, hot_check):
                pass
            def pulse(self, capacity=None):
                calls.append('external-pulse-during-runner-hash')
                self.pulses += 1
                if self.pulses == 2:
                    control.create(self.directory/'worker-result.json', dict(code=0))
            def finish(self, sample):
                calls.append('cleanup')
                sample()
        with patch.object(controller, 'Caretaker', FakeOwner), patch.object(controller.time, 'sleep'), \
                patch.object(controller, 'progress'):
            controller.execute(plan_path, p, dict(stage='generation', shape='D', data=str(self.work/'D')), m, lock)
        self.assertEqual(calls[:2], ['external-pulse-during-runner-hash']*2)
        self.assertIn('cleanup', calls)
        self.assertGreaterEqual(m.sample.call_count, 5)

    def test_execute_denies_hash_gap_monitor_failure_and_keeps_partial(self):
        plan_path = self.work/'plan.json'
        control.create(plan_path, dict(bound='fake plan'))
        p = dict(owned_root=str(self.work))
        m, lock, finished = Mock(), Mock(), []
        m.sample.side_effect = OSError('blocked HASH monitor')
        class FakeOwner:
            def __init__(self, plan, op, directory, held_lock):
                directory.mkdir()
                (directory/'partial.log').write_text('raw failed control')
            def pulse(self):
                raise AssertionError('failed sample must not pulse watchdog')
            def finish(self, sample):
                finished.append('stop/reap owned fake work')
        with patch.object(controller, 'Caretaker', FakeOwner), patch.object(controller, 'progress'):
            self.deny(lambda: controller.execute(plan_path, p,
                dict(stage='Run', shape='D', data=str(self.work/'D')), m, lock), 'blocked HASH')
        self.assertFalse(finished)
        self.assertFalse((self.work/'D-Run').exists())  # Fresh capacity denied before worker launch.

    def test_failed_windows_observation_drains_only_original_endpoint(self):
        for completed in (True,False):
            root=self.work/str(completed);root.mkdir();plan_path=root/'plan.json';control.create(plan_path,{})
            now=[0.0];active=[True]
            class Pending:
                def join(self,timeout):
                    now[0]+=timeout
                    if completed and now[0]>=.1:active[0]=False
            pending=Pending();calls=[]
            error=OSError('original hot pulse failed');error.native_disk_deadline=.3
            def disk(*a,**k):
                calls.append('disk')
                if len(calls)==2:raise error
            class Owner:
                def __init__(self,*args):args[2].mkdir()
                def ready(self,*args):pass
                def finish(self,*args):
                    self.cleanup_proven=True
                    raise ValueError('failed phase; positive work cleanup')
            lock=host.HostLock.__new__(host.HostLock);lock.owner=Mock(proof={})
            queue=lambda:[pending]if active[0]else[]
            with patch.object(controller,'Caretaker',Owner),patch.object(controller,'disk_sample',side_effect=disk), \
                 patch.object(controller,'bounded',side_effect=lambda call,**kw:call()),patch.object(controller,'progress'), \
                 patch.object(controller,'pending_calls',side_effect=queue),patch.object(host,'pending_calls',side_effect=queue), \
                 patch.object(controller,'os',SimpleNamespace(name='nt')), \
                 patch.object(controller,'time',SimpleNamespace(monotonic=lambda:now[0],sleep=lambda t:None)), \
                 patch.object(host,'retain_host_lock',side_effect=OSError('pending retained'))as retained:
                with self.assertRaises(OSError)as raised:
                    controller.execute(plan_path,dict(owned_root=str(root)),dict(stage='generation',shape='D'),Mock(),lock)
                self.assertIs(raised.exception,error)
                if completed:
                    lock.__exit__(None,None,None);retained.assert_not_called();lock.owner.close.assert_called_once()
                else:
                    self.deny(lambda:lock.__exit__(None,None,None),'pending retained');lock.owner.close.assert_not_called()
            self.assertLessEqual(now[0],.3)
            self.assertEqual(calls,['disk','disk'],'failed cleanup must not start another disk observation')

    def test_windows_failed_sample_retains_original_absolute_disk_deadline(self):
        value=monitor.Monitor.__new__(monitor.Monitor)
        value.plan={};value.log=self.work/'capacity.jsonl';value.clock=lambda:7
        value.hot_sample=Mock(side_effect=OSError('failed hot poll'))
        with patch.object(monitor,'os',SimpleNamespace(name='nt')):
            with self.assertRaises(OSError)as raised:value.sample()
        self.assertEqual(raised.exception.native_disk_deadline,7+control.LIMITS['disk_observation_seconds'])

    def test_output_mutations_and_cleanup_are_retained_without_product(self):
        data, meta = self.fixture()
        job = read_json(data/'job.json')
        output = data/'output'
        output.mkdir()
        name = 'part-00000001.csv'
        (output/name).write_bytes((data/'input.csv').read_bytes())
        first = dict(type='job', schema_version=1, algorithm_version='chopper-v1-blake3-1', config=job,
                     analysis=dict(rows=meta['rows'], groups=1, output_files=1, output_csv_bytes=meta['bytes']))
        item = dict(type='output', path=name, rows=meta['rows'], csv_bytes=meta['bytes'],
                    stored_bytes=meta['bytes'], lineage=[], compressed_target_exceeded=False)
        manifest = output/'manifest.jsonl'
        manifest.write_text(json.dumps(first)+'\n'+json.dumps(item)+'\n')
        from scale_acceptance.verify import verify
        original = verify(data/'job.json', data/'fixture.json', bitmap_dir=data/'temp')
        self.assertEqual(original['rows'], 127)
        for mutation in ('truncated-manifest', 'extra-output', 'changed-field'):
            target = self.work/mutation
            import shutil
            shutil.copytree(output, target)
            if mutation == 'truncated-manifest':
                f = target/'manifest.jsonl'
                f.write_bytes(f.read_bytes()[:-1])
            elif mutation == 'extra-output':
                (target/'extra.csv').write_bytes(b'failure retained')
            else:
                f = target/name
                raw = f.read_bytes()
                f.write_bytes(raw[:120]+b'x'+raw[121:])
            self.deny(lambda: verify(data/'job.json', data/'fixture.json', target, data/'temp'))


    def qualification_plan(self):
        tiny = controller.tiny
        scale = self.plan()
        reference = self.work/'scale-plan.json'
        control.create(reference, scale)
        plan = copy.deepcopy(scale)
        plan.update(owned_root=str(self.work/'tiny-namespace/data'), campaign=str(self.work/'tiny-namespace/campaign'))
        plan['owned_roots'] += [plan['owned_root'], plan['campaign']]
        plan['fixtures'] = {s: tiny.recipe(s) for s in ('D', 'G')}
        plan['qualification'] = dict(schema=tiny.SCHEMA, scale_plan=dict(path=str(reference), sha256=sha256(reference)),
            namespace=str(self.work/'tiny-namespace'),
            input_bytes=tiny.INPUT_BYTES, new_bytes=tiny.NEW_BYTES, metadata_per_process=tiny.METADATA.copy(),
            original_lock_stat=[1, 2, 0, 3, 4, 5], launch_cutoff_unix=100, stop_unix=200)
        return plan

    def supervisor_protocol(self, bad_terminal_receipt=False, linux=False, approval_failure=None, failed_release=True, broken_stderr=False):
        bootstrap = host.windows_bootstrap
        plan = self.qualification_plan()
        plan['qualification'].update(launch_cutoff_unix=time.time()+10000,stop_unix=time.time()+(5 if approval_failure else 20000))
        namespace = Path(plan['owned_root']).parent
        plan.update(os='Linux' if linux else 'Windows',host=dict(os='Linux' if linux else 'Windows'),actions_enabled=False,parent_scheduled=False,
            python=dict(path=str(Path(sys.executable).resolve())))
        plan['harness'] = dict(root=str(Path(__file__).resolve().parents[1]),commit='c'*40,tree='d'*40,
            sha256={'scripts/scale_acceptance/native_tiny.py':sha256(controller.tiny.__file__)} if linux else {})
        lock = Path(plan['reservation']['lock_path'])
        lock.write_bytes(b'')
        plan['qualification']['original_lock_stat'] = identity.stamp(lock)
        disabled = self.work/'disabled.json'
        maps = self.work/'maps.json'
        authority = self.work/'authority.json'
        control.create(disabled,plan)
        control.create(maps,{key:plan[key] for key in ('product','harness','dependencies')})
        control.create(authority,dict(fake_only=True))
        definition = self.work/'operator.json'
        control.create(definition,dict(schema='native-tiny-operator-v1',namespace=str(namespace),
            disabled_plan=dict(path=str(disabled),sha256=sha256(disabled)),
            source_maps=dict(path=str(maps),sha256=sha256(maps)),
            authorization=dict(path=str(authority),sha256=sha256(authority)),
            metadata_grant=dict(fake_only=True),preflight_limits=dict(fake_only=True)))
        stages = ('D-generation','D-Run','G-generation','G-Run','failure')
        def validate_actual(*args):
            controller.tiny_proposal_binding(*args)
            if approval_failure is not None:raise approval_failure
        validated = Mock(side_effect=validate_actual) if linux else Mock()
        signals=[]
        class Child:
            pid = 2147483646 if linux else 123
            controller_no_start_closed = None
            def start_controller(self,argv,out,err,env,capture,windows,token,record):
                record('created',dict(identity=dict(pid=123,created=456)))
                Path(plan['owned_root']).mkdir()
                control.create(Path(plan['owned_root'])/'reservation.json',dict(actual_lock=dict(
                    path=plan['reservation']['lock_path'],stat=plan['qualification']['original_lock_stat'],
                    **(dict(owner_pid=self.pid,mechanism='flock-exclusive') if linux else dict(owner_identity=dict(pid=789,created=888))))))
                if linux:
                    campaign=Path(plan['campaign']);campaign.mkdir()
                    control.create(campaign/'Linux-started.json',dict(component_only=True))
                    control.create(Path(plan['owned_root'])/'guard-initialization.json',dict(
                        completed=True,kind='cold-full-constructor',bound_seconds=2,seconds=.01))
                    (Path(plan['owned_root'])/'guard-operations.jsonl').write_text(json.dumps(dict(
                        kind='initial-full-sample',completed=True,error=None,bound_seconds=30,seconds=.02))+'\n')
                for name in stages:
                    stage = 'generation' if name.endswith('-generation') else 'Run' if name.endswith('-Run') else 'failure'
                    payload=dict(fake_only=True)
                    if linux:
                        root=Path(plan['owned_root']);shape=name[0];data=root/(shape+'-data')
                        reservation=read_json(root/'reservation.json')['actual_lock']
                        if stage=='generation':
                            payload=dict(slot='Linux'+shape,recipe=plan['fixtures'][shape],data=str(data),
                                reservation=reservation,limits=control.LIMITS)
                        elif stage=='Run':
                            generate.prepare(data,shape,'native',plan['fixtures'][shape]['rows'])
                            checked=checkpoint(data/'job.json',data/'fixture.json',plan['fixtures'][shape])
                            control.create(data/'checkpoint.json',checked)
                            source=controller.source_path(plan,shape,data)
                            payload=dict(slot='Linux'+shape,checkpoint=controller.actual_checkpoint(plan,shape,data),
                                actual={str(data/n):dict(stat=identity.stamp(data/n),sha256=sha256(data/n))
                                    for n in ('job.json','fixture.json','checkpoint.json')},input_sha256=checked['sha256'],
                                executable=plan['executable'],source=dict(path=str(source),stat=identity.stamp(source)),
                                lineage_sha256=identity.LINEAGE_SHA,session_authority=dict(
                                    start_sha256=sha256(campaign/'Linux-started.json'),reservation_sha256=sha256(root/'reservation.json')),
                                python=plan['python'],tools=plan['tools'],source_roles=dict(product=plan['product'],harness=plan['harness']),
                                peer=plan['peers'].get(shape,{}),reservation=reservation,limits=control.LIMITS)
                        else:
                            controller.tiny.prepare_failure(plan,root/'failure-data')
                            payload=controller.tiny.failure_payload(plan,root/'failure-data')
                    control.create(Path(plan['owned_root'])/(name+'-proposal.json'),dict(schema='native-scale-proposal-v1',
                        stage=stage,plan_sha256=sha256(namespace/'tiny-plan.json'),payload=payload))
                err.write((json.dumps(dict(native_preparation_complete=True))+'\n').encode())
                err.flush()
            def send_signal(self, signum):
                signals.append(signum)
                self.cancelled=True
            def poll(self):
                if getattr(self,'cancelled',False):return 1
                return 0 if all((Path(plan['owned_root'])/(name+'-approved.json')).exists() for name in stages) else None
            def wait(self,timeout=None):
                if linux and getattr(self,'cancelled',False):
                    assert 0 <= timeout <= 43 and timeout <= plan['qualification']['stop_unix']-time.time()+.02
                if linux:self.finish_controller(None)
                return 1 if getattr(self,'cancelled',False) else 0
            def finish_controller(self,windows):
                release = dict(original_descriptor_closed=True,
                    **read_json(Path(plan['owned_root'])/'reservation.json')['actual_lock'])
                release.update(original_owner_lock_absent=failed_release) if linux else release.update(capture_eof_joined=True)
                control.create(Path(plan['owned_root'])/'qualification-result.json',dict(
                    plan_sha256=sha256(namespace/'tiny-plan.json'),
                    passed=not getattr(self,'cancelled',False),scale_acceptance=bad_terminal_receipt,scale_slots_consumed=0,
                    original_lock=release,fake_only=True))
                if linux and not getattr(self,'cancelled',False):
                    control.create(Path(plan['campaign'])/'Linux-tiny-completed.json',dict(passed=True,
                        evidence_kind='native-tiny',scale_acceptance=False,scale_slots_consumed=0,
                        plan_sha256=sha256(namespace/'tiny-plan.json'),
                        qualification_sha256=sha256(Path(plan['owned_root'])/'qualification-result.json')))
                    for i in range(9):
                        phase=Path(plan['owned_root'])/('D-generation','D-Run','D-verify','G-generation','G-Run','G-verify',
                            'D-failure-prepare','D-failure','D-failure-verify')[i]
                        phase.mkdir()
                        control.create(phase/'containment.json',dict(worker_pid=2147483500+i,cgroup=str(phase/'absent-cgroup'),cgroup_identity=[]))
                        control.create(phase/'supervisor-ready.json',dict(caretaker_pid=2147483400+i))
                        control.create(phase/'cleanup.json',dict(controller_eof=True,monitor_threads_joined=True,
                            capture_writers_reaped=True,remaining=[],cleanup_errors=[],errors=[]))
                return dict(code=0,job=dict(pids=[]),handles_closed=True,fake_only=True)
        def selected(name):
            if name == 'native-scale-runner':return SimpleNamespace(tiny_proposal_binding=validated)
            if name == 'acceptance-preflight':return SimpleNamespace(request=Mock())
            if name == 'browser-small-windows':return SimpleNamespace(process_identity=lambda pid:dict(pid=pid,created=999))
            raise AssertionError(name)
        def run(argv,**kwargs):
            self.assertEqual(argv[3],'preflight')
            output = Path(argv[-1]);output.mkdir()
            control.create(output/'result.json',dict(fake_only=True))
            return SimpleNamespace(returncode=0)
        def git(root,*args):
            return plan['harness']['commit'] if args == ('rev-parse','HEAD') else plan['harness']['tree'] if args == ('rev-parse','HEAD^{tree}') else ''
        def popen(argv,stdout,stderr):
            self.assertTrue(linux)
            child=Child()
            child.start_controller(argv,stdout,stderr,None,None,None,None,lambda *args:None)
            return child
        stderr=Mock(write=Mock(side_effect=BrokenPipeError('closed operator stderr'))) if broken_stderr else io.StringIO()
        with patch('sys.stderr',new=stderr), patch.object(bootstrap,'os',SimpleNamespace(name='posix' if linux else 'nt',environ=os.environ,getpid=os.getpid)), \
             patch.object(bootstrap,'SuspendedWorker',Child), patch.object(bootstrap.subprocess,'run',side_effect=run), \
             patch.object(bootstrap.subprocess,'Popen',side_effect=popen), \
             patch.object(identity,'git',side_effect=git), patch.object(identity,'host',return_value=plan['host']), \
             patch.object(identity,'environment_digest',return_value='e'*64), patch.object(control,'validate_preparation'), \
             patch.object(control,'validate'), patch.object(controller.tiny,'launch_check'), \
             patch.object(controller.tiny,'check_clock'), patch.object(controller.tiny,'preflight'), \
             patch.object(controller.tiny,'ReadBudget',return_value=SimpleNamespace(read_bytes=1,visits=1,failed=False)) as meter, \
             patch.object(host,'module',side_effect=selected), patch.dict(os.environ), \
             patch.object(bootstrap.time,'sleep',side_effect=AssertionError('known closed actor retained')), \
             patch('sys.stdout',new=io.StringIO()):
            if approval_failure is not None and not failed_release:
                with self.assertRaisesRegex(AssertionError,'known closed actor retained'):
                    bootstrap.supervise(definition,sha256(definition),execute=True)
            elif approval_failure is not None:
                with self.assertRaises(type(approval_failure)) as raised:
                    bootstrap.supervise(definition,sha256(definition),execute=True)
                self.assertIs(raised.exception,approval_failure)
            elif bad_terminal_receipt:
                with self.assertRaisesRegex(ValueError,'terminal/Original-release'):
                    bootstrap.supervise(definition,sha256(definition),execute=True)
            else:
                self.assertEqual(bootstrap.supervise(definition,sha256(definition),execute=True),0)
        if linux:
            meter.assert_called_once()
            self.assertEqual(meter.call_args.args[0]['qualification']['metadata_per_process'],
                             plan['qualification']['metadata_per_process'])
            self.assertEqual(meter.call_args.args[1],Path(definition.parent/'disabled.json'))
        else:meter.assert_not_called()
        if approval_failure is not None:
            import signal
            self.assertEqual(signals,[signal.SIGINT])
            failure=read_json(namespace/'operator-failure.json')
            self.assertIs(failure['qualification'],False)
            self.assertIn(str(approval_failure),failure['error'])
            self.assertEqual((namespace/'qualify-failed-exit.json').exists(),failed_release)
            return
        if linux and not bad_terminal_receipt:
            # Real owning after-exit validator, with only process/cgroup roles simulated above.
            with patch('sys.stdout',new=io.StringIO()):
                self.assertEqual(controller.tiny.linux_after_exit(namespace,sha256(namespace/'tiny-plan.json')),0)
        self.assertEqual([call.args[2] for call in validated.call_args_list],list(stages))
        for name in stages:
            approval = read_json(Path(plan['owned_root'])/(name+'-approved.json'))
            self.assertEqual(approval['proposal_sha256'],sha256(Path(plan['owned_root'])/(name+'-proposal.json')))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux exact child cancellation')
    def test_linux_operator_approval_failure_signals_once_and_reaps_failed_original_release(self):
        self.supervisor_protocol(linux=True,approval_failure=ValueError('controlled parent validator rejection'))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux exact child cancellation')
    def test_linux_operator_interrupt_signals_once_and_reaps_failed_original_release(self):
        self.supervisor_protocol(linux=True,approval_failure=KeyboardInterrupt('controlled parent cancellation'))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux uncertain Original remains held')
    def test_linux_operator_missing_failed_original_proof_retains_after_exact_child_reap(self):
        self.supervisor_protocol(linux=True,approval_failure=ValueError('validator rejection'),failed_release=False)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux exact child cleanup')
    def test_linux_operator_broken_diagnostics_cannot_skip_failed_cleanup_or_replace_primary(self):
        self.supervisor_protocol(linux=True,approval_failure=ValueError('primary validator rejection'),broken_stderr=True)

    def test_maintained_supervisor_automatically_validates_all_five_before_owning_approval(self):
        self.supervisor_protocol()

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux supervisor branch')
    def test_linux_supervisor_uses_kernel_release_without_windows_pipe_receipt(self):
        self.supervisor_protocol(linux=True)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux supervisor branch')
    def test_linux_bad_terminal_receipt_fails_after_wait_without_retaining_closed_owner(self):
        self.supervisor_protocol(linux=True,bad_terminal_receipt=True)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux kernel absence checks')
    def test_linux_after_exit_requires_all_cleanup_empty_cgroups_and_absent_pids(self):
        tiny=controller.tiny
        for fault in ('none','cleanup','cgroup','pid','completion','role','other-lock','operator'):
            root=self.work/fault;root.mkdir()
            data=root/'data';data.mkdir();campaign=root/'campaign';campaign.mkdir()
            lock=root/'fake-lock';lock.write_bytes(b'')
            plan=dict(owned_root=str(data),campaign=str(campaign),
                qualification=dict(original_lock_stat=identity.stamp(lock)),
                harness=dict(sha256={'scripts/scale_acceptance/native_tiny.py':sha256(tiny.__file__)}))
            control.create(root/'tiny-plan.json',plan);pin=sha256(root/'tiny-plan.json')
            q=dict(passed=True,plan_sha256=pin,scale_acceptance=False,scale_slots_consumed=0,
                original_lock=dict(path=str(lock),stat=identity.stamp(lock),owner_pid=2147483647,
                    original_descriptor_closed=True,original_owner_lock_absent=True))
            control.create(data/'qualification-result.json',q)
            control.create(campaign/'Linux-tiny-completed.json',dict(passed=True,plan_sha256=pin,
                qualification_sha256=sha256(data/'qualification-result.json'),
                evidence_kind='native-tiny',scale_acceptance=False,scale_slots_consumed=1 if fault=='completion' else 0))
            control.create(root/'qualify-exit.json',dict(code=0))
            control.create(root/'controller-pid.json',dict(pid=os.getpid() if fault=='pid' else 2147483646))
            for i in range(9):
                phase=data/('D-generation','D-Run','D-verify','G-generation','G-Run','G-verify',
                    'D-failure-prepare','D-failure','D-failure-verify')[i]
                if fault=='role' and i==0:phase=data/'unexpected-role'
                phase.mkdir()
                cg=phase/'fake-cgroup'
                if fault=='cgroup' and i==0:
                    cg.mkdir();(cg/'cgroup.procs').write_text('42\n')
                    cg_id=[cg.stat().st_dev,cg.stat().st_ino]
                else:cg_id=[]
                control.create(phase/'containment.json',dict(worker_pid=2147483500+i,
                    cgroup=str(cg),cgroup_identity=cg_id))
                control.create(phase/'supervisor-ready.json',dict(caretaker_pid=2147483400+i))
                control.create(phase/'cleanup.json',dict(controller_eof=True,
                    monitor_threads_joined=not(fault=='cleanup' and i==0),
                    capture_writers_reaped=True,remaining=[],cleanup_errors=[],errors=[]))
            if fault=='operator':control.create(root/'operator-failure.json',dict(qualification=False))
            actual_read=Path.read_text
            def proc_locks(file,*args,**kwargs):
                if fault=='other-lock' and file==Path('/proc/locks'):
                    stat=lock.stat();device=f'{os.major(stat.st_dev):02x}:{os.minor(stat.st_dev):02x}:{stat.st_ino}'
                    return '1: FLOCK ADVISORY WRITE 999 '+device+' 0 EOF\n'
                return actual_read(file,*args,**kwargs)
            with patch('sys.stdout',new=io.StringIO()),patch.object(Path,'read_text',proc_locks):
                if fault=='none':self.assertEqual(tiny.linux_after_exit(root,pin),0)
                else:
                    with self.assertRaises(ValueError):tiny.linux_after_exit(root,pin)
            self.assertEqual((root/'after-exit-proof.json').exists(),fault=='none')

    def test_supervisor_post_cleanup_receipt_failure_exits_failed_without_retaining_closed_actor(self):
        self.supervisor_protocol(bad_terminal_receipt=True)

    def test_automatic_tiny_generation_approval_requires_whole_payload_and_real_guard_receipts(self):
        plan = self.qualification_plan()
        root = Path(plan['owned_root'])
        root.mkdir(parents=True)
        plan_file = self.work/'selected-plan.json'
        control.create(plan_file,plan)
        reservation = dict(mechanism='fake-only-unit-control',owner_pid=123)
        control.create(root/'reservation.json',dict(actual_lock=reservation))
        self.assertEqual(controller.tiny.cold_admission_seconds(dict(os='Linux')),2)
        self.assertEqual(controller.tiny.cold_admission_seconds(dict(os='Windows')),30)
        initialization = dict(completed=True,kind='cold-full-constructor',bound_seconds=controller.tiny.cold_admission_seconds(plan),seconds=.1)
        control.create(root/'guard-initialization.json',initialization)
        (root/'guard-operations.jsonl').write_text(json.dumps(dict(kind='initial-full-sample',completed=True,
            error=None,bound_seconds=30,seconds=.2))+'\n')
        value = dict(schema='native-scale-proposal-v1',stage='generation',plan_sha256=sha256(plan_file),
            payload=dict(slot=plan['os']+'D',recipe=plan['fixtures']['D'],data=str(root/'D-data'),
                reservation=reservation,limits=control.LIMITS))
        proposal = root/'D-generation-proposal.json'
        control.create(proposal,value)
        controller.tiny_proposal_binding(plan,plan_file,'D-generation',sha256(proposal))
        (root/'guard-initialization.json').write_text(json.dumps(dict(initialization,bound_seconds=30)))
        self.deny(lambda:controller.tiny_proposal_binding(plan,plan_file,'D-generation',sha256(proposal)),
                  'selected native cold admission')
        (root/'guard-initialization.json').write_text(json.dumps(initialization))
        for field in ('schema','stage','plan_sha256','slot','recipe','data','reservation','limits'):
            changed = copy.deepcopy(value)
            if field in ('schema','stage','plan_sha256'):
                changed[field] = 'wrong'
            else:
                changed['payload'][field] = 'wrong'
            proposal.write_text(json.dumps(changed))
            self.deny(lambda:controller.tiny_proposal_binding(plan,plan_file,'D-generation',sha256(proposal)),
                      'proposal mismatch')
        proposal.write_text(json.dumps(value))
        (root/'guard-initialization.json').write_text(json.dumps(dict(initialization,completed=False)))
        self.deny(lambda:controller.tiny_proposal_binding(plan,plan_file,'D-generation',sha256(proposal)),
                  'selected native cold admission')
        self.deny(lambda:controller.tiny_proposal_binding(plan,plan_file,'checkpoint-adoption',sha256(proposal)),
                  'only selected complete')

    def test_explicit_tiny_retains_scale_default_and_all_inventory(self):
        plan = self.qualification_plan()
        control.validate(plan)
        self.assertEqual(control.native_recipe('D')['bytes'], 10_000_000_000)
        self.assertEqual(plan['fixtures']['D']['bytes'], 12800)
        for mutation in ('guard', 'inventory', 'history', 'reservation', 'caps', 'rows', 'namespace'):
            changed = copy.deepcopy(plan)
            if mutation == 'guard':
                changed['limits']['stale_seconds'] += 1
            elif mutation == 'inventory':
                changed['dependencies'] = []
            elif mutation == 'history':
                changed['owned_roots'] = [plan['owned_root'], plan['campaign']]
            elif mutation == 'reservation':
                changed['source_reservation']['bytes'] += 1
            elif mutation == 'caps':
                changed['fixtures']['D']['job']['limits']['bytes'] = 1000
            elif mutation == 'rows':
                changed['fixtures']['G'] = controller.tiny.recipe('G', 1024)
            else:
                changed['campaign'] = controller.tiny.reference(plan)['campaign']
            with self.subTest(mutation=mutation):
                self.deny(lambda: control.validate(changed))

    def test_tiny_does_not_have_scale_slots_or_reset_parent_clock(self):
        plan = self.qualification_plan()
        lineage = SimpleNamespace(value=dict(prior_generation_ms=324064))
        campaign = control.TinyCampaign(plan, 'a'*64, lineage)
        self.assertEqual(campaign.debit, 324.064)
        self.deny(lambda: campaign.predecessor('LinuxD'), 'no scale slots')
        self.deny(lambda: campaign.consume('LinuxD', self.work/'unused'), 'cannot consume')
        self.assertEqual([p.name for p in campaign.root.iterdir()], ['Linux-started.json'])
        with patch.object(controller.tiny.time, 'time', return_value=201):
            self.deny(campaign.check, 'absolute stop')
        with patch.object(controller.tiny.time, 'time', return_value=101):
            self.deny(lambda: controller.tiny.launch_check(plan), 'cutoff')

    def test_tiny_requires_matching_preflight_before_lock_or_namespace_creation(self):
        plan = self.qualification_plan()
        file = self.work/'tiny-plan.json'
        control.create(file, plan)
        with patch.object(controller, 'HostLock') as lock:
            self.deny(lambda: controller.session(file, sha256(file)), 'matching preflight')
            lock.assert_not_called()
        self.assertFalse(Path(plan['owned_root']).exists())
        self.assertFalse(Path(plan['campaign']).exists())
        with patch.object(controller, 'Lineage') as lineage, patch.object(controller, 'canonical_claim') as claim:
            self.deny(lambda: controller.claim_run(file, sha256(file), self.work/'proposal'),
                      'Linux parent exact plan authority' if os.name=='nt' else 'cannot claim')
            lineage.assert_not_called()
            claim.assert_not_called()

    def test_windows_cold_admission_has_own_bound_before_unchanged_live_guard(self):
        from contextlib import ExitStack
        original = self.qualification_plan()
        lock_path = self.work/'original-lock'
        lock_path.write_bytes(b'')
        original['reservation']['lock_path'] = str(lock_path)
        original['qualification']['original_lock_stat'] = identity.stamp(lock_path)
        for platform, cost, admitted in (('nt', 9, True), ('nt', 31, False), ('posix', 9, False)):
            namespace = self.work/(platform+str(cost))
            namespace.mkdir()
            plan = copy.deepcopy(original)
            plan.update(os='Windows' if platform == 'nt' else 'Linux', owned_root=str(namespace/'data'),
                        campaign=str(namespace/'campaign'))
            plan['host'] = dict(os=plan['os'])
            plan['qualification']['namespace'] = str(namespace)
            file = namespace/'plan.json'
            control.create(file, plan)
            events, bounds, clock = [], [], [0]
            lineage = SimpleNamespace(allocation_origin={})
            campaign = SimpleNamespace(monotonic_started=0)
            lock = SimpleNamespace(path=lock_path, proof=lambda: dict(owner_pid=456, stat=identity.stamp(lock_path)),
                                   released=dict(original_descriptor_closed=True))
            class Held:
                def __enter__(self):
                    events.append('lock')
                    return lock
                def __exit__(self, *args):
                    events.append('release')
            def start_campaign(*args):
                events.append('clock')
                return campaign
            def construct(*args):
                self.assertIs(args[2], campaign)
                self.assertEqual(read_json(Path(plan['owned_root'])/'reservation.json')['actual_lock'], lock.proof())
                self.assertEqual(events, ['lock', 'clock'])
                events.append('constructor')
                clock[0] += cost
                def sample(start=False):
                    self.assertTrue(start)
                    self.assertEqual(bounds[-1], 30)
                    self.assertEqual(campaign.monotonic_started, 0)
                    events.append('live')
                    raise OSError('live full guard denied')
                return SimpleNamespace(externals={}, sample=sample)
            def bounded(call, seconds=2):
                bounds.append(seconds)
                before = clock[0]
                value = call()
                if clock[0]-before >= seconds:
                    raise OSError('cold constructor deadline')
                return value
            def fixture_path(*parts):
                if parts==('/proc',str(os.getpid()),'stat'):
                    return SimpleNamespace(read_text=lambda:'123 (fixture owner) '+' '.join(['0']*19+['123']))
                return Path(*parts)
            with ExitStack() as stack:
                for obj, name, value in (
                        (controller, 'Path', fixture_path),
                        (controller, 'validate', Mock()), (controller, 'HostLock', Held),
                        (controller, 'TinyCampaign', start_campaign), (controller, 'Monitor', construct),
                        (controller, 'bounded', bounded), (controller, 'pending_calls', lambda: []),
                        (controller, 'os', SimpleNamespace(name=platform,getpid=os.getpid)),
                        (controller, 'time', SimpleNamespace(monotonic=lambda: clock[0])),
                        (controller.tiny, 'preflight', Mock(return_value={})),
                        (controller.tiny, 'History', Mock(return_value=lineage)),
                        (controller.tiny, 'launch_check', Mock()), (controller.tiny, 'check_clock', Mock())):
                    stack.enter_context(patch.object(obj, name, value))
                lineage.check = Mock()
                caretaker = stack.enter_context(patch.object(controller, 'Caretaker'))
                self.assertEqual(controller.session(file, sha256(file), file, 'a'*64), 1)
                caretaker.assert_not_called()
            self.assertEqual(bounds[:2], [2, 30 if platform == 'nt' else 2])
            if admitted:
                self.assertIn(30, bounds[2:])
            else:
                self.assertTrue(all(value == 2 for value in bounds[2:]))
            self.assertEqual('live' in events, admitted)
            self.assertEqual(events[-1], 'release')
            self.assertEqual(read_json(Path(plan['owned_root'])/'reservation.json')['actual_lock'], lock.proof())
            self.assertFalse(read_json(Path(plan['owned_root'])/'session-result.json')['passed'])
            receipt = read_json(Path(plan['owned_root'])/'guard-initialization.json')
            self.assertEqual(receipt['bound_seconds'], 30 if platform == 'nt' else 2)
            self.assertEqual(receipt['completed'], admitted)

    def windows_qualification_plan(self):
        plan = self.qualification_plan()
        scale = controller.tiny.reference(plan)
        scale.update(os='Windows', host=dict(os='Windows'),
                     peers={s: dict(slot='Linux'+s, sha256='a'*64, source_sha256='b'*64, plan_sha256='c'*64)
                            for s in ('D', 'G')})
        scale['reservation']['os'] = 'Windows'
        reference = self.work/'windows-scale-plan.json'
        control.create(reference, scale)
        plan.update(os='Windows', host=scale['host'])
        plan['reservation']['os'] = 'Windows'
        plan['qualification']['scale_plan'] = dict(path=str(reference), sha256=sha256(reference))
        return plan, scale

    def test_tiny_windows_missing_actual_history_cannot_admit_large_or_tiny(self):
        plan, scale = self.windows_qualification_plan()
        control.validate(plan)
        self.deny(lambda: controller.tiny.History(plan), 'OS-local retained allocation/carry')
        self.deny(lambda: control.validate(scale), 'Windows admission deferred')

    def test_latest_source_carry_composes_monotone_floors_and_growth(self):
        def baseline(amount,root=None):
            root=str(self.work/'source')if root is None else root
            return dict(roots=[dict(path=root)],entries=[dict(path=str(Path(root)/'body'),
                stat=dict(dev=1,ino=2),charge_bytes=amount)],sum_bytes=amount)
        before=baseline(0);current=baseline(34048336)
        latest=dict(schema='native-tiny-windows-history-v1',baselines=dict(source=before),
            prior_storage=dict(source=dict(sum_bytes=0,entry_count=1,carry_bytes=4488463256,
                prior_sampled_aggregate_highwater_bytes=4488463256)))
        old=dict(carry_bytes=100)
        self.assertEqual(controller.tiny.History.transition_carry(old,before,current,pool='source',
            latest_source=latest),4522511592)
        self.assertEqual(controller.tiny.History.transition_carry(old,before,current,pool='source'),34048436)
        for fault in ('count','sum','carry','roots','pool'):
            bad=copy.deepcopy(latest);pool='source'
            if fault=='count':bad['prior_storage']['source']['entry_count']=0
            elif fault=='sum':bad['prior_storage']['source']['sum_bytes']=1
            elif fault=='carry':bad['prior_storage']['source']['prior_sampled_aggregate_highwater_bytes']-=1
            elif fault=='roots':bad['baselines']['source']['roots']=[dict(path=str(self.work/'foreign'))]
            else:pool='native'
            with self.assertRaises(ValueError):
                controller.tiny.History.transition_carry(old,before,current,pool=pool,latest_source=bad)

    def test_retained_preparation_metadata_output_is_closed_exact_and_counted_once(self):
        from pathlib import PureWindowsPath
        from scale_acceptance import native_preflight
        sequence=[0]
        def pin(value):
            sequence[0]+=1;file=self.work/(str(sequence[0])+'.json');control.create(file,value)
            return dict(path=str(file),sha256=sha256(file))
        def load(item):
            self.assertEqual(sha256(item['path']),item['sha256']);return read_json(item['path'])
        namespace=PureWindowsPath('C:/preparation-only-imports')
        root=self.work/'metadata';directory=root/'imports';directory.mkdir(parents=True)
        copies=[]
        for index in range(6):
            raw=json.dumps(dict(index=index)).encode();digest=hashlib.sha256(raw).hexdigest()
            file=directory/(digest+'.json');file.write_bytes(raw)
            copies.append(dict(path=str(namespace/'imports'/file.name),sha256=digest,bytes=len(raw)))
        def member(index):return {k:copies[index][k]for k in ('path','sha256')}
        selection=pin(dict(namespace_disk_bytes=256*1024**2))
        previous=dict(path='C:/old-plan.json',sha256='a'*64);pref=dict(path='C:/old-pref.json',sha256='b'*64)
        preparation=pin(dict(namespace=str(namespace),namespace_disk_authority=dict(selection=selection),source_q_bytes=1024**3,
            preparation_limits=dict(storage_bytes=64*1024**2),previous_plan=previous,previous_preflight=pref))
        stage=pin(dict(schema='native-tiny-stage-v1',output='C:/prepare',destination='C:/source/harness',
            preparation=preparation,limits=dict(source_bytes=64*1024**2,output_bytes=4*1024**2)))
        manifest=pin(dict(stage=stage,preparation=preparation))
        scale=pin(dict(owned_roots=['C:/old-data']))
        emitted=pin(dict(actions_enabled=False,parent_scheduled=False,qualification=dict(namespace=str(namespace),scale_plan=scale,
            peers=dict(D=dict(report=member(0),qualification=member(1),completion=member(2),campaign_record=member(3)),
                       G=dict(report=member(4),qualification=member(1),completion=member(2),campaign_record=member(5)))),
            source_reservation=dict(roots=['C:/source'])))
        point=pin(dict(complete=True,qualification=False,product_runs=0,scale_slots=0,previous_plan=previous,
            previous_preflight=pref,plan=emitted,preparation_data_reservations=[dict(root='C:/prepare',reserved_bytes=64*1024**2)]))
        lifecycle=pin(dict(passed=True,cleanup_passed=True,fixture_byte0_available_unlocked_closed=True,
            qualification=False,original_touched=False,product_runs=0))
        audit=pin(dict(cleanup_passed=True,fixture_byte0_available_unlocked_closed=True,qualification=False,
            original_touched=False,component_sha256=lifecycle['sha256'],actor_and_keepers=[dict(absent=True,error=87)]*3))
        imported=pin(dict(complete=True,original_proof_bytes_preserved=True,CSV_inputs_generated=0,
            records=copies,copied_bytes=sum(row['bytes']for row in copies)))
        terminal=pin(dict(code=1,EOF=True,reaped=True))
        extra=dict(root=str(namespace),reserved_bytes=256*1024**2,selection=selection,peer_imports=imported,
            observation=point,lifecycle=lifecycle,independent=audit,terminal=terminal)
        record=dict(manifest=manifest,stage=stage,preparation=preparation,metadata_output=extra)
        resolve=lambda name:root.joinpath(*PureWindowsPath(name).relative_to(namespace).parts)
        def consume(value):return native_preflight.retained_preparation_reservations(value,load,1024**3,resolve_path=resolve)
        rows,bound=consume([record]);self.assertEqual(len(rows),3)
        self.assertEqual(sum(row['reserved_bytes']for row in rows),(64+4+256)*1024**2)
        self.assertEqual(consume([record,record]),(rows,bound))
        legacy=dict(record);legacy.pop('metadata_output');self.assertEqual(len(consume([legacy])[0]),2)
        for fault in ('root','proof','duplicate','ceiling','members','alias'):
            bad=copy.deepcopy(record);side=None
            if fault=='root':bad['metadata_output']['root']='C:/foreign'
            elif fault=='proof':bad['metadata_output']['terminal']=pin(dict(code=1,EOF=False,reaped=True))
            elif fault=='duplicate':
                value=load(imported);value['records'].append(value['records'][0]);bad['metadata_output']['peer_imports']=pin(value)
            elif fault=='ceiling':bad['metadata_output']['reserved_bytes']=1
            elif fault=='members':side=directory/'foreign.json';side.write_text('{}')
            else:
                side=self.work/'alias.json'
                try:os.link(next(directory.iterdir()),side)
                except OSError:continue
            try:
                with self.assertRaises((ValueError,AssertionError)):consume([bad])
            finally:
                if side is not None:side.unlink()
        self.assertEqual(consume([record]),(rows,bound))

    def windows_retained_transition_fixture(self, *, peers=False):
        plan, scale = self.windows_qualification_plan()
        namespace = Path(plan['qualification']['namespace'])
        namespace.mkdir()
        if peers:
            imported=namespace/'imports';imported.mkdir()
            def pin(name,value):
                file=imported/(name+'.json');control.create(file,value)
                return dict(path=str(file),sha256=sha256(file))
            qualified=pin('qualified',dict(schema=controller.tiny.SCHEMA,passed=True,os='Linux',
                scale_acceptance=False,scale_slots_consumed=0,plan_sha256='a'*64,
                original_lock=dict(original_descriptor_closed=True,original_owner_lock_absent=True)))
            completed=pin('completed',dict(passed=True,evidence_kind='native-tiny',
                plan_sha256='a'*64,qualification_sha256=qualified['sha256']))
            plan['qualification']['peers']={}
            for shape in ('D','G'):
                report=pin(shape+'-report',dict(os='Linux',host=dict(os='Linux'),passed=True,
                    evidence_kind='native-tiny',slot='Linux'+shape,product=plan['product']['commit'],plan_sha256='a'*64,
                    report=dict(shape=shape,rows=plan['fixtures'][shape]['rows'],source_sha256='b'*64)))
                committed=pin(shape+'-record',dict(passed=True,evidence_kind='native-tiny',
                    plan_sha256='a'*64,sha256=report['sha256']))
                plan['qualification']['peers'][shape]=dict(report=report,qualification=qualified,
                    completion=completed,campaign_record=committed)
            for shape in ('D','G'):controller.tiny.peer_report(plan,shape)
        index = Path(plan['harness']['root'])/'.git/index'
        index.write_bytes(b'unchanged index content')
        proof = self.work/'old-measurement.json'
        control.create(proof, dict(fake_only=True))
        pin = dict(path=str(proof), sha256=sha256(proof))
        def baseline(roots):
            records, entries = [], []
            for name in roots:
                root = Path(name)
                s = root.stat()
                records.append(dict(path=name, stat=identity.stat_fields(s, getattr(s, 'st_blocks', 0)*512)))
                for file in root.rglob('*'):
                    if file.is_file():
                        s = file.stat()
                        allocated = _allocated_bytes(file, s)
                        entries.append(dict(path=str(file), stat=identity.stat_fields(s, allocated),
                                            charge_bytes=max(s.st_size, allocated)))
            return dict(roots=records, entries=entries, sum_bytes=sum(item['charge_bytes'] for item in entries))
        baselines = dict(native=baseline(scale['owned_roots']), source=baseline(scale['source_reservation']['roots']))
        prior = {pool: dict(sum_bytes=value['sum_bytes'], entry_count=len(value['entries']),
                            carry_bytes=value['sum_bytes'], prior_sampled_aggregate_highwater_bytes=value['sum_bytes'])
                 for pool, value in baselines.items()}
        history = dict(schema='native-tiny-windows-history-v1', host=plan['host'],
            scale_plan=plan['qualification']['scale_plan'], provenance=[pin], prior_generation_ms=0,
            allocation_origin=dict(kind='fresh-native-baseline; legacy metrics retained separately', legacy_records=[pin]),
            baselines=baselines, prior_storage=prior)
        old_file = self.work/'old-windows-history.json'
        control.create(old_file, history)
        plan['qualification']['windows_history'] = dict(path=str(old_file), sha256=sha256(old_file))
        admitted = controller.tiny.History(plan)
        for pool in baselines:
            monitor.Storage(admitted.baselines[pool], prior[pool])
        preparation_storage = {pool: dict(current_origin_bytes=value['sum_bytes'], historical_allocation_bound=None)
                               for pool, value in baselines.items()}
        old_plan = self.work/'old-tiny-plan.json'
        receipt, _, _ = self.preflight_fixture(plan, old_plan, preparation_storage)
        retired = next(item['charge_bytes'] for item in baselines['source']['entries'] if item['path'] == str(index))
        index.rename(self.work/'retired-index')
        index.write_bytes(b'unchanged index content')
        changed = copy.deepcopy(history)
        changed['baselines']['source'] = baseline(scale['source_reservation']['roots'])
        current = changed['baselines']['source']
        changed['prior_storage']['source'] = dict(sum_bytes=current['sum_bytes'], entry_count=len(current['entries']),
            carry_bytes=current['sum_bytes']+retired, prior_sampled_aggregate_highwater_bytes=current['sum_bytes']+retired)
        changed['retained_transition'] = dict(schema='native-tiny-retained-transition-v1',
            previous_plan=dict(path=str(old_plan), sha256=sha256(old_plan)),
            previous_preflight=dict(path=str(receipt), sha256=sha256(receipt)))
        return plan, changed, history, retired

    def test_closed_success_namespace_advancement_consumes_real_History_and_preserves_old_upper(self):
        plan,history,_,_=self.windows_retained_transition_fixture()
        namespace=Path(plan['qualification']['namespace']);old=namespace/'retained';old.mkdir();(old/'body').write_bytes(b'old')
        def baseline(roots):
            entries=[]
            for root in roots:
                for file in sorted(root.rglob('*')):
                    if file.is_file():
                        stat=file.stat();allocated=_allocated_bytes(file,stat)
                        entries.append(dict(path=str(file),stat=identity.stat_fields(stat,allocated),charge_bytes=max(stat.st_size,allocated)))
            return dict(roots=[dict(path=str(root),stat=identity.stat_fields(root.stat(),getattr(root.stat(),'st_blocks',0)*512))for root in roots],
                entries=entries,sum_bytes=sum(row['charge_bytes']for row in entries))
        def pin(file,value):control.create(file,value);return dict(path=str(file),sha256=sha256(file))
        anchor_roots=sorted(namespace.iterdir())
        anchor=baseline(anchor_roots);fields={row['path']:row['stat']for row in anchor['entries']};origin=4096
        point=pin(self.work/'old-point.json',dict(component_only=True,tiny_origin_carry=origin,unchanged_current_identities=dict(tiny=dict(
            files=len(fields),successful_charge_sum=anchor['sum_bytes'],sampled_bytes=origin+anchor['sum_bytes'],
            digest=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()))))
        prior=pin(self.work/'old-namespace.json',dict(schema='native-tiny-namespace-history-v1',namespace=str(namespace),
            observation=point,origin_carry_bytes=origin,baseline=anchor,prior_storage=dict(sum_bytes=anchor['sum_bytes'],entry_count=len(fields),
                carry_bytes=origin+anchor['sum_bytes'],prior_sampled_aggregate_highwater_bytes=origin+anchor['sum_bytes'])))
        root=namespace/'completed';root.mkdir();data=root/'data';data.mkdir();campaign=root/'campaign';campaign.mkdir()
        oldplan=pin(root/'tiny-plan.json',dict(os='Windows',host=plan['host'],owned_root=str(data),campaign=str(campaign),qualification=dict(
            namespace=str(namespace),namespace_history=prior,new_bytes=controller.tiny.NEW_BYTES)))
        original=plan['qualification']['original_lock_stat']
        q=pin(data/'qualification-result.json',dict(schema=controller.tiny.SCHEMA,host=plan['host'],passed=True,evidence_kind='native-tiny',
            scale_acceptance=False,scale_slots_consumed=0,plan_sha256=oldplan['sha256'],original_lock=dict(stat=original,
                original_descriptor_closed=True,capture_eof_joined=True)))
        completion=pin(campaign/'Windows-tiny-completed.json',dict(passed=True,plan_sha256=oldplan['sha256'],qualification_sha256=q['sha256']))
        roles=[shape+'-'+stage for shape in ('D','G')for stage in ('generation','Run','verify')]+['D-'+stage for stage in ('failure-prepare','failure','failure-verify')]
        audit=pin(root/'after-exit-proof.json',dict(schema='native178-full-tiny-after-exit-v1',qualification_passed=True,
            qualification_sha256=q['sha256'],original_lock_stat=original,administrative_recovery=False,
            independent_probe_released=True,original_byte_zero_available=True,owned_births=[dict(absent=True,error=87)],
            phases=[dict(directory=str(data/role),empty_owned_job=True)for role in roles]))
        completed=[dict(path=str(root),plan=oldplan,qualification=q,completion=completion,independent=audit)]
        current=baseline([*anchor_roots,root])
        advanced=controller.tiny.namespace_advancement(namespace,current,point,prior,completed,original,expected_host=plan['host'])
        self.assertGreaterEqual(advanced['tiny_origin_carry']+current['sum_bytes'],64*1024**2)
        newpoint=pin(self.work/'advanced-point.json',advanced)
        total=advanced['tiny_origin_carry']+current['sum_bytes']
        descriptor=dict(schema='native-tiny-namespace-history-v1',namespace=str(namespace),observation=newpoint,
            origin_carry_bytes=advanced['tiny_origin_carry'],baseline=current,completed_namespaces=completed,
            previous_observation=point,previous_history=prior,
            prior_storage=dict(sum_bytes=current['sum_bytes'],entry_count=len(current['entries']),carry_bytes=total,prior_sampled_aggregate_highwater_bytes=total))
        plan['qualification']['namespace_history']=pin(self.work/'advanced-history.json',descriptor)
        authority=pin(self.work/'disk-authority.json',dict(scope='unit fixture only'))
        selection=pin(self.work/'disk-selection.json',dict(schema='chopper-owner-disk-authority-selection-v1',
            namespace_disk_bytes=256*1024**2,previous_terminal_upper_bound_bytes=64*1024**2,authority=authority))
        plan['qualification'].update(new_bytes=256*1024**2,namespace_disk_authority=dict(selection=selection,authority=authority))
        admitted=controller.tiny.History(plan)
        storage=monitor.Storage(admitted.namespace_baseline,admitted.namespace_prior)
        self.assertEqual(storage.sample([namespace]),total)
        self.assertLess(total,plan['qualification']['new_bytes'])
        from scale_acceptance import native_preflight
        proof=dict(source_reconciliation=dict(path=str(self.work/'reconciliation.json'),sha256='a'*64),runner_receipts=[])
        actual_read=native_preflight.read_json
        with patch.object(native_preflight,'read_json',side_effect=lambda file,limit: proof if str(file)==plan['build_proof']['path'] else actual_read(file,limit)):
            inventory=native_preflight.preparation_inputs(plan)
        self.assertTrue({item['path'] for item in (point,prior,selection,authority)}<=set(inventory))
        admitted.check()
        for item in (selection,authority):
            file=Path(item['path']);body=file.read_bytes();file.write_bytes(body+b' ')
            self.deny(admitted.check,'retained namespace history drift')
            file.write_bytes(body)
            admitted=controller.tiny.History(plan)
        for fault in ('missing','mismatch','root','carry'):
            if fault=='carry':
                bad=copy.deepcopy(descriptor);bad['origin_carry_bytes']=0
                item=pin(self.work/'bad-carry.json',bad);changed=copy.deepcopy(plan);changed['qualification']['namespace_history']=item
                self.deny(lambda:controller.tiny.History(changed));continue
            siblings=copy.deepcopy(completed);scope=copy.deepcopy(current)
            if fault=='missing':siblings[0].pop('independent')
            elif fault=='mismatch':siblings[0]['qualification']['sha256']='0'*64
            else:scope['roots'].append(dict(path=str(namespace/'unknown'),stat={}))
            self.deny(lambda:controller.tiny.namespace_advancement(namespace,scope,point,prior,siblings,original,expected_host=plan['host']))

    def test_tiny_retained_namespace_baseline_charges_old_files_once_and_new_growth(self):
        plan, history, _, _ = self.windows_retained_transition_fixture()
        old = Path(plan['qualification']['namespace'])/'retained'
        old.mkdir()
        (old/'body').write_bytes(b'retained namespace bytes')
        namespace=Path(plan['qualification']['namespace'])
        entries=[]
        for file in sorted(namespace.rglob('*')):
            if file.is_file():
                value=file.stat();allocated=_allocated_bytes(file,value)
                entries.append(dict(path=str(file),stat=identity.stat_fields(value,allocated),
                                    charge_bytes=max(value.st_size,allocated)))
        charge=sum(item['charge_bytes'] for item in entries)
        baseline=dict(roots=[dict(path=str(root),stat=identity.stat_fields(root.stat(),getattr(root.stat(),'st_blocks',0)*512))
                             for root in namespace.iterdir()],entries=entries,sum_bytes=charge)
        fields={item['path']:item['stat'] for item in entries}
        point=dict(component_only=True,tiny_origin_carry=4096,
            unchanged_current_identities=dict(tiny=dict(files=len(entries),successful_charge_sum=charge,
                sampled_bytes=4096+charge,digest=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest())))
        point_file=self.work/'namespace-point.json';control.create(point_file,point)
        origin=dict(schema='native-tiny-namespace-history-v1',namespace=plan['qualification']['namespace'],
            observation=dict(path=str(point_file),sha256=sha256(point_file)),origin_carry_bytes=4096,
            baseline=baseline,prior_storage=dict(sum_bytes=charge,entry_count=len(entries),carry_bytes=4096+charge,
                prior_sampled_aggregate_highwater_bytes=4096+charge))
        origin_file=self.work/'namespace-history.json';control.create(origin_file,origin)
        plan['qualification']['namespace_history']=dict(path=str(origin_file),sha256=sha256(origin_file))
        history_file=self.work/'new-windows-history.json';control.create(history_file,history)
        plan['qualification']['windows_history']=dict(path=str(history_file),sha256=sha256(history_file))
        admitted=controller.tiny.History(plan)
        storage=monitor.Storage(admitted.namespace_baseline,admitted.namespace_prior)
        namespace=Path(plan['qualification']['namespace'])
        self.assertEqual(storage.sample([namespace]),4096+charge)
        fresh=namespace/'fresh';fresh.mkdir();(fresh/'new').write_bytes(b'new')
        grew=storage.sample([namespace])
        self.assertEqual(grew,4096+charge+max((fresh/'new').stat().st_size,_allocated_bytes(fresh/'new',(fresh/'new').stat())))
        (fresh/'new').unlink()
        self.assertEqual(storage.sample([namespace]),grew)
        for mutation in ('carry','namespace','point','overlap'):
            changed=copy.deepcopy(origin)
            if mutation=='carry':changed['origin_carry_bytes']+=1
            elif mutation=='namespace':changed['namespace']=str(self.work/'different')
            elif mutation=='point':changed['baseline']['entries'][0]['stat']['ino']+=1
            else:changed['baseline']['roots'][0]['path']=plan['owned_root']
            file=self.work/(mutation+'-namespace-history.json');control.create(file,changed)
            bad=copy.deepcopy(plan);bad['qualification']['namespace_history']=dict(path=str(file),sha256=sha256(file))
            self.deny(lambda:controller.tiny.History(bad),'namespace')
        (old/'body').unlink()
        self.deny(lambda:monitor.Storage(admitted.namespace_baseline,admitted.namespace_prior),'drift')

    def test_tiny_windows_retired_index_preserves_admitted_carry_through_storage(self):
        plan, history, old, retired = self.windows_retained_transition_fixture()
        file = self.work/'current-windows-history.json'
        control.create(file, history)
        plan['qualification']['windows_history'] = dict(path=str(file), sha256=sha256(file))
        admitted = controller.tiny.History(plan)
        self.deny(lambda: monitor.Storage(old['baselines']['source'], old['prior_storage']['source']), 'sealed stat')
        storage = monitor.Storage(admitted.baselines['source'], admitted.value['prior_storage']['Windows']['source'])
        roots = [Path(item['path']) for item in history['baselines']['source']['roots']]
        self.assertEqual(storage.sample(roots), history['baselines']['source']['sum_bytes']+retired)
        self.assertEqual(admitted.allocation_origin['retained_carry']['source']['retired_identity_bytes'], retired)
        self.assertGreater(retired, 0)
        index = Path(plan['harness']['root'])/'.git/index'
        index.write_bytes(b'')
        self.assertEqual(storage.sample(roots), storage.carry)
        worker = Path(history['retained_transition']['previous_preflight']['path']).parent/'worker-result.json'
        worker.write_bytes(b'changed previous evidence')
        self.deny(admitted.check, 'Windows retained history drift')

    def test_fresh_Tiny_History_consumes_retained_D_roots_and_exact_shared_carry(self):
        plan,history,_,_=self.windows_retained_transition_fixture(peers=True)
        old_namespace=plan['qualification']['namespace'];original_work=self.work
        proof_root=self.work/'closed-proof';proof_root.mkdir();self.work=proof_root
        try:
            with patch.object(identity,'PRODUCT',plan['product']['commit']):
                _,_,descriptor,linux_sha,hashes=self.retained_windows_d_fixture(policy=plan,
                    retained_roots=[old_namespace],floors=dict(native=100000,source=1000))
        finally:self.work=original_work
        from scale_acceptance import native_preflight
        old_plan=read_json(history['retained_transition']['previous_plan']['path'])
        def baseline(roots):
            entries=[]
            for name in roots:
                for file in Path(name).rglob('*'):
                    if file.is_file():
                        value=file.stat();allocated=_allocated_bytes(file,value)
                        entries.append(dict(path=str(file),stat=identity.stat_fields(value,allocated),
                            charge_bytes=max(value.st_size,allocated)))
            return dict(roots=[dict(path=name,stat={}) for name in roots],entries=entries,
                sum_bytes=sum(row['charge_bytes'] for row in entries))
        with patch.object(identity,'PRODUCT',plan['product']['commit']), \
             patch.object(identity,'LINUX_SCALE_PLAN_SHA',linux_sha),patch.object(identity,'LINUX_SCALE_REPORTS',hashes):
            accepted=identity.retained_windows_d(plan,descriptor)
            scale=controller.tiny.reference(plan)
            for pool in ('native','source'):
                names=identity.windows_root_union([row['path']for row in history['baselines'][pool]['roots']],
                    accepted['plan']['owned_roots'] if pool=='native' else accepted['plan']['source_reservation']['roots'])
                current=baseline(names)
                old_history=read_json(old_plan['qualification']['windows_history']['path'])
                carry=controller.tiny.History.transition_carry(old_history['prior_storage'][pool],
                    old_history['baselines'][pool],current,retained=accepted,pool=pool,previous_plan=old_plan)
                history['baselines'][pool]=current
                history['prior_storage'][pool]=dict(sum_bytes=current['sum_bytes'],entry_count=len(current['entries']),
                    carry_bytes=carry,prior_sampled_aggregate_highwater_bytes=carry)
                if pool=='native':scale['owned_roots']=names
                else:scale['source_reservation']=dict(scale['source_reservation'],roots=names)
            # A newer observed (not newly qualified) source floor composes with the accepted transition.
            latest=dict(schema='native-tiny-windows-history-v1',host=plan['host'],
                baselines=dict(source=copy.deepcopy(history['baselines']['source'])),
                prior_storage=dict(source=copy.deepcopy(history['prior_storage']['source'])))
            latest['prior_storage']['source']['carry_bytes']+=17
            latest['prior_storage']['source']['prior_sampled_aggregate_highwater_bytes']+=17
            latest_file=self.work/'latest-source-history.json';control.create(latest_file,latest)
            history['latest_source_history']=dict(path=str(latest_file),sha256=sha256(latest_file))
            old_history=read_json(old_plan['qualification']['windows_history']['path'])
            amount=controller.tiny.History.transition_carry(old_history['prior_storage']['source'],
                old_history['baselines']['source'],history['baselines']['source'],retained=accepted,pool='source',
                previous_plan=old_plan,latest_source=latest)
            history['prior_storage']['source'].update(carry_bytes=amount,prior_sampled_aggregate_highwater_bytes=amount)
            ref=self.work/'retained-scale.json';control.create(ref,scale)
            plan['qualification']['scale_plan']=history['scale_plan']=dict(path=str(ref),sha256=sha256(ref))
            fresh=self.work/'fresh-tiny'
            plan.update(owned_root=str(fresh/'leaf/data'),campaign=str(fresh/'leaf/campaign'),
                owned_roots=[*scale['owned_roots'],str(fresh/'leaf/data'),str(fresh/'leaf/campaign')],
                source_reservation=copy.deepcopy(scale['source_reservation']))
            plan['qualification']['namespace']=str(fresh)
            history['retained_windows_d']=descriptor
            history['prior_generation_ms']=900
            file=self.work/'retained-current-history.json';control.create(file,history)
            plan['qualification']['windows_history']=dict(path=str(file),sha256=sha256(file))
            with self.assertRaisesRegex(ValueError,'tiny peer imports must count toward namespace ceiling'):
                controller.tiny.History(plan)
            original={item['path']:Path(item['path']).read_bytes()for item in controller.tiny.peer_pins(old_plan)}
            for fault in ('wrong-sha','too-large','existing','hardlink','outer-policy'):
                previous=copy.deepcopy(old_plan);candidate=copy.deepcopy(plan)
                target=self.work/('bad-import-'+fault);candidate['qualification']['namespace']=str(target)
                link=None
                if fault=='wrong-sha':previous['qualification']['peers']['D']['report']['sha256']='0'*64
                elif fault=='too-large':candidate['qualification']['new_bytes']=1
                elif fault=='existing':target.mkdir()
                elif fault=='outer-policy':candidate['features']=['unapproved']
                else:
                    source=Path(previous['qualification']['peers']['D']['report']['path']);link=source.with_name('alias.json')
                    try:os.link(source,link)
                    except OSError:continue  # This filesystem cannot create the scoped hardlink counterexample.
                    previous['qualification']['peers']['D']['report']['path']=str(link)
                try:
                    with self.assertRaises(ValueError):native_preflight.import_tiny_peers(previous,candidate,Mock())
                    self.assertEqual(target.exists(),fault=='existing')
                    if fault=='existing':self.assertEqual(list(target.iterdir()),[])
                finally:
                    if link is not None:link.unlink()
            # Actual retained-D preparation adds an ancestor of these old phase roots.
            descendant=Path(old_namespace)/'old-phase'
            descendant.mkdir()
            plan['owned_roots'] += [str(descendant/'data'),str(descendant/'campaign')]
            before_roots=[Path(name)for name in plan['owned_roots']]
            with self.assertRaisesRegex(ValueError,'overlapping owned histories'):
                control.validate_preparation(plan)
            imports=native_preflight.import_tiny_peers(old_plan,plan,Mock())
            control.validate_preparation(plan)
            after_roots=[Path(name)for name in plan['owned_roots']]
            self.assertTrue(all(any(name==root or name.is_relative_to(root)for root in after_roots)for name in before_roots))
            self.assertTrue(all(not a.is_relative_to(b)and not b.is_relative_to(a)
                for index,a in enumerate(after_roots)for b in after_roots[index+1:]))
            self.assertTrue(imports['complete']);self.assertEqual(imports['CSV_inputs_generated'],0)
            self.assertEqual(controller.tiny.validate(plan),scale)
            for item in controller.tiny.peer_pins(plan):
                self.assertTrue(Path(item['path']).is_relative_to(fresh))
                self.assertEqual(sha256(item['path']),item['sha256'])
                self.assertIn(Path(item['path']).read_bytes(),original.values())
            with self.assertRaisesRegex(ValueError,'fresh Windows peer-import namespace'):
                native_preflight.import_tiny_peers(old_plan,plan,Mock())
            self.assertTrue(all(Path(name).read_bytes()==raw for name,raw in original.items()))
            actual=controller.tiny.History(plan)
            self.assertEqual(actual.retained_d['descriptor'],descriptor)
            self.assertEqual(identity.execution_shapes(plan),('D','G'))
            self.assertEqual(actual.baselines,history['baselines'])
            for fault in ('missing','wrong-sha','wrong-host'):
                candidate=copy.deepcopy(history);selected=copy.deepcopy(plan)
                if fault=='missing':candidate['latest_source_history']['path']=str(self.work/'missing-history.json')
                elif fault=='wrong-sha':candidate['latest_source_history']['sha256']='0'*64
                else:
                    wrong=copy.deepcopy(latest);wrong['host']=dict(plan['host'],release='foreign')
                    wrong_file=self.work/'wrong-host-history.json';control.create(wrong_file,wrong)
                    candidate['latest_source_history']=dict(path=str(wrong_file),sha256=sha256(wrong_file))
                candidate_file=self.work/('bad-latest-'+fault+'.json');control.create(candidate_file,candidate)
                selected['qualification']['windows_history']=dict(path=str(candidate_file),sha256=sha256(candidate_file))
                with self.assertRaises((ValueError,FileNotFoundError)):controller.tiny.History(selected)
            # All derived proof bodies, including JSONL, enter the owning input closure.
            proof=dict(source_reconciliation=dict(path=str(self.work/'reconciliation.json'),sha256='a'*64),runner_receipts=[])
            read=native_preflight.read_json
            with patch.object(native_preflight,'read_json',side_effect=lambda file,limit:proof if str(file)==plan['build_proof']['path'] else read(file,limit)):
                inputs=native_preflight.preparation_inputs(plan)
            self.assertTrue({pin['path']for pin in descriptor.values()}<=set(inputs))
            for pool in ('native','source'):
                bad=copy.deepcopy(history);bad['prior_storage'][pool]['carry_bytes']-=1
                bad['prior_storage'][pool]['prior_sampled_aggregate_highwater_bytes']-=1
                file.write_text(json.dumps(bad));plan['qualification']['windows_history']['sha256']=sha256(file)
                with self.assertRaisesRegex(ValueError,'cannot refund'):controller.tiny.History(plan)

    def test_tiny_windows_retained_transition_rejects_refund_and_unproven_predecessor(self):
        plan, history, _, _ = self.windows_retained_transition_fixture()
        for mutation in ('refund', 'inflated-carry', 'previous-plan', 'previous-preflight', 'roots'):
            changed = copy.deepcopy(history)
            if mutation == 'refund':
                changed['prior_storage']['source']['carry_bytes'] = changed['prior_storage']['source']['sum_bytes']
                changed['prior_storage']['source']['prior_sampled_aggregate_highwater_bytes'] = changed['prior_storage']['source']['sum_bytes']
            elif mutation == 'inflated-carry':
                changed['prior_storage']['source']['carry_bytes'] += 1
                changed['prior_storage']['source']['prior_sampled_aggregate_highwater_bytes'] += 1
            elif mutation == 'previous-plan':
                changed['retained_transition']['previous_plan']['sha256'] = '0'*64
            elif mutation == 'previous-preflight':
                changed['retained_transition']['previous_preflight']['sha256'] = '0'*64
            else:
                changed['baselines']['source']['roots'].pop()
            file = self.work/(mutation+'-history.json')
            control.create(file, changed)
            plan['qualification']['windows_history'] = dict(path=str(file), sha256=sha256(file))
            self.deny(lambda: controller.tiny.History(plan))

    def test_tiny_windows_retained_transition_allows_only_runtime_scale_refresh(self):
        plan, history, old, _ = self.windows_retained_transition_fixture()
        old_reference = copy.deepcopy(plan['qualification']['scale_plan'])
        refreshed = controller.tiny.reference(plan)
        dependency = refreshed['dependencies'][0]['sha256']
        dependency[next(iter(dependency))] = '0'*64
        refreshed['environment_sha256'] = 'c'*64
        refreshed['tools'][0]['sha256'] = 'd'*64
        reference_file = self.work/'refreshed-scale.json'
        control.create(reference_file, refreshed)
        new_reference = dict(path=str(reference_file), sha256=sha256(reference_file))
        plan['qualification']['scale_plan'] = new_reference
        plan['dependencies'] = copy.deepcopy(refreshed['dependencies'])
        plan['tools'] = copy.deepcopy(refreshed['tools'])
        plan['environment_sha256'] = refreshed['environment_sha256']
        history['scale_plan'] = new_reference
        file = self.work/'refreshed-history.json'
        control.create(file, history)
        plan['qualification']['windows_history'] = dict(path=str(file), sha256=sha256(file))
        admitted = controller.tiny.History(plan)
        self.assertEqual(admitted.scale, refreshed)
        self.assertEqual(old['scale_plan'], old_reference)
        self.assertNotEqual(old_reference, new_reference)
        self.deny(lambda: control.validate(refreshed), 'Windows admission deferred')
        extra_tool_field = copy.deepcopy(refreshed)
        extra_tool_field['tools'][0]['role'] = 'changed'
        self.assertFalse(controller.tiny.History._same_scale_policy(refreshed,extra_tool_field))
        for mutation in ('product', 'limits', 'roots', 'tools', 'new-history-reference', 'old-history-reference'):
            changed_plan, changed_history = copy.deepcopy(plan), copy.deepcopy(history)
            if mutation in ('product', 'limits', 'roots', 'tools'):
                scale = copy.deepcopy(refreshed)
                if mutation == 'product':
                    scale['product']['commit'] = 'a'*40
                    changed_plan['product'] = copy.deepcopy(scale['product'])
                elif mutation == 'limits':
                    scale['limits']['sample_seconds'] += 1
                    changed_plan['limits'] = copy.deepcopy(scale['limits'])
                elif mutation == 'tools':
                    scale['tools'][0]['path'] += '-other'
                    changed_plan['tools'] = copy.deepcopy(scale['tools'])
                else:
                    extra = self.work/'extra-scale-source'
                    extra.mkdir()
                    scale['source_reservation']['roots'].append(str(extra))
                    changed_plan['source_reservation']['roots'].append(str(extra))
                changed_reference = self.work/(mutation+'-scale.json')
                control.create(changed_reference, scale)
                pin = dict(path=str(changed_reference), sha256=sha256(changed_reference))
                changed_plan['qualification']['scale_plan'] = pin
                changed_history['scale_plan'] = pin
            elif mutation == 'new-history-reference':
                changed_history['scale_plan'] = old_reference
            else:
                previous_pin = changed_history['retained_transition']['previous_plan']
                previous_plan = read_json(previous_pin['path'])
                previous_history = read_json(previous_plan['qualification']['windows_history']['path'])
                previous_history['scale_plan'] = new_reference
                wrong_history = self.work/'wrong-old-reference-history.json'
                control.create(wrong_history, previous_history)
                previous_plan['qualification']['windows_history'] = dict(path=str(wrong_history), sha256=sha256(wrong_history))
                wrong_plan = self.work/'wrong-old-reference-plan.json'
                control.create(wrong_plan, previous_plan)
                changed_history['retained_transition']['previous_plan'] = dict(path=str(wrong_plan), sha256=sha256(wrong_plan))
            changed_file = self.work/(mutation+'-refresh-history.json')
            control.create(changed_file, changed_history)
            changed_plan['qualification']['windows_history'] = dict(path=str(changed_file), sha256=sha256(changed_file))
            reason = {'product': 'retained transition scale policy changed', 'limits': 'fixed native limits',
                      'roots': 'retained transition scale policy changed', 'tools': 'retained transition scale policy changed',
                      'new-history-reference': 'actual Windows history provenance',
                      'old-history-reference': 'previous retained history mismatch'}[mutation]
            self.deny(lambda: controller.tiny.History(changed_plan), reason)

    def test_malformed_tiny_failure_requires_actual_work_and_clean_output(self):
        plan = self.qualification_plan()
        root = Path(plan['owned_root'])
        root.mkdir(parents=True)
        data = root/'failure-data'
        controller.tiny.prepare_failure(plan, data)
        file, approval = root/'proposal.json', root/'approval.json'
        control.proposal(file, 'failure', 'c'*64, controller.tiny.failure_payload(plan, data))
        control.approve(file, approval, sha256(file))
        operation = dict(stage='failure', shape='D', data=str(data), proposal=str(file), approval=str(approval),
                         proposal_sha256=sha256(file), plan_sha256='c'*64)
        batch = root/'batch'
        batch.mkdir()
        attempt = dict(status='failed', exit_code=1,
            argv=[plan['executable']['path'], 'run', '--config', str(data/'job.json'), '--yes'],
            runtime=dict(executable_sha256=plan['executable']['sha256']),
            inputs={str((data/n).relative_to(root)): dict(sha256=sha256(data/n))
                    for n in ('input.csv', 'job.json', 'fixture.json', 'failure.json')})
        control.create(batch/'status.json', dict(summary=dict(passed=0, incomplete=1), attempts=[attempt]))
        message = 'Reading and writing CSV | 0 rows | 0 MiB temporary\nchopper: CSV record 129 has 1 fields, expected 3\n'
        (batch/'1-stderr.log').write_text(message)
        result = controller.tiny.expected_failure(plan, operation, batch, root)
        self.assertEqual(result['valid_rows_consumed'], 127)
        for text in ('invalid Job configuration', 'CSV error: record 1 (byte: 0): found record with 1 fields',
                     message.replace('record 129', 'record 128'), message.replace('expected 3', 'expected 2'),
                     'CSV error: record 128 (line: 129, byte: 12800): found record with 1 fields, but previous record has 3 fields'):
            (batch/'1-stderr.log').write_text(text)
            self.deny(lambda: controller.tiny.expected_failure(plan, operation, batch, root), 'actual-work')
        (batch/'1-stderr.log').write_text(message)
        (data/'temp/leak').write_bytes(b'failed temp')
        self.deny(lambda: controller.tiny.expected_failure(plan, operation, batch, root), 'leaked temp')

    @unittest.skipUnless(identity.shutil.which('git'), 'Git unavailable')
    def test_native_git_reads_canonical_objects_even_when_repository_has_replacements(self):
        repo=self.work/'temporary-git';repo.mkdir()
        env={key:value for key,value in os.environ.items() if not key.startswith('GIT_')}
        argv=[identity.shutil.which('git'),'-c','core.fsmonitor=false','-c','core.hooksPath='+os.devnull,'-C',str(repo)]
        def git(*args):return subprocess.check_output([*argv,*args],env=env,stderr=subprocess.PIPE,timeout=4)
        git('init','--quiet')
        original,replacement=repo/'original.txt',repo/'replacement.txt'
        original.write_bytes(b'canonical object\n');replacement.write_bytes(b'replacement object\n')
        first=git('hash-object','-w',str(original)).decode().strip()
        second=git('hash-object','-w',str(replacement)).decode().strip()
        git('replace',first,second)
        self.assertEqual(git('show',first),replacement.read_bytes())
        self.assertEqual(identity.git(repo,'show',first,raw=True),original.read_bytes())

    def git_metadata_fixture(self, label):
        root=self.work/(label+'-role');common=self.work/(label+'-common')
        gitdir=common/'worktrees/role';gitdir.mkdir(parents=True);root.mkdir()
        (root/'.git').write_text('gitdir: '+str(gitdir)+'\n')
        (root/'tracked.py').write_text('selected source\n')
        (gitdir/'commondir').write_text('../..\n')
        (gitdir/'HEAD').write_text('ref: refs/heads/selected\n')
        (gitdir/'index').write_bytes(b'own index')
        (common/'config').write_text('[core]\n bare = false\n')
        (common/'HEAD').write_text('ref: refs/heads/unrelated\n')
        (common/'index').write_bytes(b'other worktree index')
        selected=common/'refs/heads/selected';selected.parent.mkdir(parents=True)
        selected.write_text('a'*40+'\n')
        remote=common/'refs/remotes/origin/other';remote.parent.mkdir(parents=True)
        remote.write_text('b'*40+'\n')
        return root,gitdir,common,selected,remote

    def test_git_metadata_ignores_unrelated_shared_refs_and_other_worktree_index(self):
        for detached in (False,True):
            root,gitdir,common,selected,remote=self.git_metadata_fixture('detached' if detached else 'attached')
            if detached:(gitdir/'HEAD').write_text('a'*40+'\n')
            before=monitor.git_metadata(root)
            remote.write_text('c'*40+'\n');remote.with_suffix('.lock').write_bytes(b'pending unrelated fetch')
            (common/'HEAD').write_text('b'*40+'\n');(common/'index').write_bytes(b'other worktree refreshed')
            (common/'packed-refs').write_text('d'*40+' refs/remotes/origin/unrelated\n')
            self.assertEqual(monitor.git_metadata(root),before)

    def test_git_metadata_keeps_selected_head_index_config_ref_and_source_strict(self):
        for field in ('HEAD','index','config','config.worktree','selected'):
            root,gitdir,common,selected,remote=self.git_metadata_fixture(field.replace('.','-'))
            before=monitor.git_metadata(root)
            file=selected if field=='selected' else common/'config' if field=='config' else gitdir/field
            file.write_text('b'*40+'\n' if field in ('HEAD','selected') else 'changed metadata\n')
            self.assertNotEqual(monitor.git_metadata(root),before,field)
        root,_,_,_,_=self.git_metadata_fixture('actual-file')
        value=monitor.Monitor.__new__(monitor.Monitor);value.dependencies=[]
        value.groups=[(root,['tracked.py'],identity.frozen_metadata(root,['tracked.py']),{})]
        (root/'tracked.py').write_text('actual source drift\n')
        self.deny(value.filesystem_sample,'source freeze drift')

    def test_git_metadata_packed_ref_compares_selected_value_not_shared_container(self):
        root,gitdir,common,selected,_=self.git_metadata_fixture('packed')
        selected.unlink();packed=common/'packed-refs'
        packed.write_text('a'*40+' refs/heads/selected\n'+'b'*40+' refs/remotes/origin/other\n')
        before=monitor.git_metadata(root)
        packed.write_text('a'*40+' refs/heads/selected\n'+'c'*40+' refs/remotes/origin/other\n')
        self.assertEqual(monitor.git_metadata(root),before)
        packed.write_text('d'*40+' refs/heads/selected\n'+'c'*40+' refs/remotes/origin/other\n')
        self.assertNotEqual(monitor.git_metadata(root),before)
        packed.write_text('invalid packed row\n')
        self.deny(lambda:monitor.git_metadata(root),'packed Git ref row')

    def test_git_drift_denial_records_exact_root_path_and_metadata_field(self):
        root,gitdir,_,_,_=self.git_metadata_fixture('diagnostic')
        value=monitor.Monitor.__new__(monitor.Monitor)
        value.runtime='runtime';value.plan={'host':{}};value.lineage=None
        value.campaign,value.lock=Mock(),Mock();value.clock=time.monotonic
        value.last_progress=value.clock();value.deadline=float('inf');value.externals={}
        value.git_freezes=[(root,monitor.git_metadata(root))]
        (gitdir/'index').write_bytes(b'own index changed')
        with patch.object(identity,'runtime_requirements',return_value='runtime'),patch.object(monitor,'host',return_value={}):
            with self.assertRaisesRegex(ValueError,'Git/source-role metadata drift') as raised:value.hot_sample()
        details=json.loads(raised.exception.__notes__[0])
        self.assertTrue(any(str(gitdir/'index') in row['field'] and row['field'].endswith('/size')
                            for row in details['changed']))
        self.assertFalse(details['truncated'])
        self.assertLessEqual(len(raised.exception.__notes__[0]),8192)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'actual temporary Linux flock')
    def test_early_poll_error_drains_before_original_deadline_and_releases_temp_flock(self):
        import fcntl
        lock=self.work/'temporary-flock';primary=ValueError('hot identity rejected');done=threading.Event();fence=Mock()
        def disk():
            time.sleep(.16);done.set()
        def poll():
            def hot():raise primary
            return host.bounded(hot,seconds=.05)  # Nested hot failure does not reset the outer deadline.
        with patch.object(host,'module',return_value=SimpleNamespace(host_lock_path=lambda:lock)):
            started=time.monotonic()
            with self.assertRaises(ValueError) as raised:
                with host.HostLock() as held:host.bounded(disk,seconds=.5,fence=fence,poll=poll)
            self.assertIs(raised.exception,primary);self.assertTrue(done.is_set())
            self.assertEqual(host.pending_calls(),[]);self.assertLess(time.monotonic()-started,.5)
            fence.poison.assert_called_once()
            self.assertTrue(held.released['original_owner_lock_absent'])
        fd=os.open(lock,os.O_RDWR)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(fd,fcntl.LOCK_UN)
        finally:os.close(fd)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'actual temporary Linux flock')
    def test_early_poll_error_keeps_unfinished_call_fenced_and_temp_flock_retained(self):
        import fcntl
        lock=self.work/'temporary-pending-flock';release=threading.Event();fence=Mock();primary=ValueError('hot identity rejected')
        held=None
        try:
            with patch.object(host,'module',return_value=SimpleNamespace(host_lock_path=lambda:lock)):
                held=host.HostLock().__enter__()
                with self.assertRaises(ValueError) as raised:
                    host.bounded(lambda:release.wait(2),seconds=.15,fence=fence,poll=lambda:(_ for _ in ()).throw(primary))
                self.assertIs(raised.exception,primary);fence.poison.assert_called_once();self.assertTrue(host.pending_calls())
                with patch.object(host,'retain_host_lock',side_effect=OSError('temporary owner retained')):
                    self.deny(lambda:held.__exit__(None,None,None),'temporary owner retained')
                fd=os.open(lock,os.O_RDWR)
                try:
                    with self.assertRaises(BlockingIOError):fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                finally:os.close(fd)
        finally:
            running=host.pending_calls();release.set()
            for thread in running:thread.join(timeout=1)
            if held is not None:held.__exit__(None,None,None)
        self.assertEqual(host.pending_calls(),[])
        fd=os.open(lock,os.O_RDWR)
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(fd,fcntl.LOCK_UN)
        finally:os.close(fd)

    def test_direct_interrupt_does_not_drain_pending_callback(self):
        release=threading.Event();fence=Mock();primary=KeyboardInterrupt('direct caller interrupt')
        try:
            with patch.object(host.queue.Queue,'get',side_effect=primary):
                started=time.monotonic()
                with self.assertRaises(KeyboardInterrupt) as raised:
                    host.bounded(lambda:release.wait(2),seconds=.5,fence=fence,poll=Mock())
                self.assertIs(raised.exception,primary)
                self.assertLess(time.monotonic()-started,.2)
                self.assertTrue(host.pending_calls());fence.poison.assert_called_once()
        finally:
            running=host.pending_calls();release.set()
            for thread in running:thread.join(timeout=1)

    def test_interrupt_inside_poll_does_not_drain_pending_callback(self):
        for primary in (KeyboardInterrupt('poll interrupted'),SystemExit('poll exited')):
            release=threading.Event();fence=Mock()
            try:
                def poll():raise primary
                started=time.monotonic()
                with self.assertRaises(type(primary)) as raised:
                    host.bounded(lambda:release.wait(2),seconds=.6,fence=fence,poll=poll)
                self.assertIs(raised.exception,primary);self.assertLess(time.monotonic()-started,.3)
                self.assertTrue(host.pending_calls());fence.poison.assert_called_once()
            finally:
                running=host.pending_calls();release.set()
                for thread in running:thread.join(timeout=1)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'actual signal and temporary flock')
    def test_linux_cli_sigint_latch_drains_original_callback_or_retains_pending(self):
        import signal
        original=signal.getsignal(signal.SIGINT)
        for blocked in (False,True):
            lock=self.work/('pending-lock' if blocked else 'joined-lock')
            release=threading.Event();held=None
            def selected_session(*args,cancelled):
                nonlocal held
                campaign=control.Campaign(self.work/('pending-campaign' if blocked else 'joined-campaign'),
                    'Linux','a'*64,cancelled=cancelled)
                held=host.HostLock().__enter__()
                def disk():
                    if blocked:release.wait(2)
                    else:time.sleep(.16)
                os.kill(os.getpid(),signal.SIGINT)
                try:
                    host.bounded(disk,seconds=.22,fence=Mock(),poll=campaign.check)
                finally:
                    held.__exit__(None,None,None)
            try:
                with patch.object(host,'module',return_value=SimpleNamespace(host_lock_path=lambda:lock)), \
                     patch.object(controller,'session',side_effect=selected_session), \
                     patch.object(controller,'read_json',return_value={}),patch.object(controller.tiny,'enabled',return_value=False), \
                     patch.object(sys,'argv',['native-scale-runner.py','session',str(self.work/'plan'),'--sha256','a'*64]), \
                     patch.object(host,'retain_host_lock',side_effect=OSError('temporary pending owner retained')):
                    self.deny(controller.main,'temporary pending owner retained' if blocked else 'cancelled by SIGINT')
                self.assertEqual(signal.getsignal(signal.SIGINT),original)
                self.assertEqual(bool(host.pending_calls()),blocked)
                if not blocked:self.assertTrue(held.released['original_owner_lock_absent'])
            finally:
                running=host.pending_calls();release.set()
                for thread in running:thread.join(timeout=1)
                if blocked and held is not None:held.__exit__(None,None,None)

    def test_caretaker_pipe_close_error_preserves_failure_but_finishes_positive_cleanup(self):
        primary=BrokenPipeError('closed caretaker pipe')
        owner=host.Caretaker.__new__(host.Caretaker);owner.directory=self.work
        owner.backup_job=owner.backup_cgroup=None
        owner.process=Mock();owner.process.stdin.closed=True
        owner.process.stdin.close.side_effect=primary
        owner.process.wait.return_value=1;owner.process.poll.return_value=1
        owner.capture=Mock()
        control.create(self.work/'cleanup.json',dict(errors=['failed worker'],remaining=[],cleanup_errors=[],
            controller_eof=True,monitor_threads_joined=True,capture_writers_reaped=True))
        with self.assertRaises(BrokenPipeError) as raised:owner.finish()
        self.assertIs(raised.exception,primary);self.assertTrue(owner.cleanup_proven)
        owner.capture.assert_called_once();owner.process.wait.assert_called_once()

    def test_caretaker_pipe_error_stays_primary_when_cleanup_is_unproven(self):
        owner=host.Caretaker.__new__(host.Caretaker);owner.directory=self.work
        owner.backup_job=owner.backup_cgroup=None;owner.capture=Mock()
        primary=BrokenPipeError('caretaker pipe failed');owner.process=Mock()
        owner.process.stdin.closed=True;owner.process.stdin.close.side_effect=primary
        owner.process.wait.return_value=1;owner.process.poll.return_value=1
        with self.assertRaises(BrokenPipeError) as raised:owner.finish()
        self.assertIs(raised.exception,primary);self.assertFalse(owner.cleanup_proven)
        self.assertIn('cleanup proof',primary.__notes__[0])

    def test_bounded_threads_join_before_success_and_unproven_work_retains_lock(self):
        def identity_call():
            return threading.current_thread()
        thread = host.bounded(identity_call)
        self.assertFalse(thread.is_alive())
        self.assertEqual(host.pending_calls(), [])
        gate = threading.Event()
        try:
            def blocked_query():
                return gate.wait(5)
            with self.assertRaisesRegex(OSError, 'blocked/stale') as caught:
                host.bounded(blocked_query, seconds=.01)
            note = caught.exception.__notes__[0]
            self.assertIn('call='+blocked_query.__qualname__, note)
            self.assertIn('file='+__file__, note)
            self.assertIn('line='+str(blocked_query.__code__.co_firstlineno), note)
            self.assertIn('seconds=0.01 elapsed=', note)
            self.assertTrue(host.pending_calls())
            with patch.object(host, 'retain_host_lock', side_effect=OSError('retained original')) as retain:
                self.deny(lambda: host.HostLock().__exit__(None, None, None), 'retained original')
                retain.assert_called_once()
        finally:
            running = host.pending_calls()
            gate.set()
            for thread in running:
                thread.join(timeout=1)
        self.assertEqual(host.pending_calls(), [])

    def test_tiny_publication_observer_rejects_partial_public_directory(self):
        data, meta = self.fixture()
        watch = controller.tiny.PublicationWatch(data)
        (data/'output').mkdir()
        self.deny(watch.sample)
        config = read_json(data/'job.json')
        name = 'part-00000001.csv'
        (data/'output'/name).write_bytes((data/'input.csv').read_bytes())
        (data/'output/manifest.jsonl').write_text(json.dumps(dict(type='job', config=config))+'\n'+
            json.dumps(dict(type='output', path=name, rows=meta['rows'], csv_bytes=meta['bytes']))+'\n')
        watch.sample()
        self.assertTrue(watch.observed)

    def preflight_fixture(self, plan, file, preparation_storage=None):
        namespace = Path(plan['qualification']['namespace'])
        namespace.mkdir(exist_ok=True)
        checker = namespace/'checker'
        checker.mkdir()
        plan['source_reservation']['roots'].append(str(checker))
        actual = host.module('acceptance-preflight')
        source = Path(actual.__file__).parent
        scripts = [str(p.relative_to(source)) for p in actual.checker_sources()]
        for name in scripts:
            target=checker/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes((source/name).read_bytes() if name=='acceptance-preflight.py'
                               else b'fake helper source; never executed\n')
        files = {str(checker/n): sha256(checker/n) for n in scripts}
        plan['harness']['sha256']['scripts/acceptance-preflight.py']=files[str(checker/'acceptance-preflight.py')]
        control.create(file, plan)
        evidence = namespace/'preflight'
        (evidence/'runner').mkdir(parents=True)
        worker = evidence/'worker-result.json'
        control.create(worker, dict(status='passed', preparation_storage=preparation_storage))
        control.create(evidence/'preparation-plan.json', dict(root=str(self.work)))
        status = dict(summary=dict(passed=1, incomplete=0), attempts=[dict(status='passed', exit_code=0,
            inputs={str(file.relative_to(self.work)): dict(sha256=sha256(file))},
            artifacts={str(worker.relative_to(self.work)): dict(sha256=sha256(worker))})])
        control.create(evidence/'runner/status.json', status)
        receipt = evidence/'result.json'
        result = dict(schema='chopper-acceptance-preflight-v1', status='passed', profile='native',
            plan_sha256=sha256(file), workload_started=False, scale_slot_consumed=False,
            host={k: v for k, v in plan['host'].items() if k in ('os', 'node', 'machine', 'release', 'version')},
            worker_receipt_sha256=sha256(worker),
            checker=dict(path=str(checker/scripts[0]), sha256=files[str(checker/scripts[0])], files=files),
            bindings=dict(product=plan['product']['commit'], harness=plan['harness']['commit'],
                          harness_tree=plan['harness']['tree'], host=plan['host']))
        control.create(receipt, result)
        if preparation_storage is not None:
            result['preparation_storage'] = preparation_storage
            receipt.write_text(json.dumps(result))
        return receipt, result, status

    def test_tiny_preflight_matches_actual_host_checker_worker_and_runner_custody(self):
        tiny = controller.tiny
        plan = self.qualification_plan()
        plan['product']['commit'] = 'p'*40
        plan['harness'].update(commit='h'*40, tree='t'*40)
        file = self.work/'tiny-plan.json'
        receipt, result, status = self.preflight_fixture(plan, file)
        evidence = receipt.parent
        checker = Path(result['checker']['path']).parent
        tiny.preflight(file, plan, receipt, sha256(receipt))
        # Current common preflight declares absolute files; old receipts used relative keys.
        absolute = copy.deepcopy(status)
        for kind in ('inputs', 'artifacts'):
            absolute['attempts'][0][kind] = {str(self.work/name): value
                for name, value in status['attempts'][0][kind].items()}
        (evidence/'runner/status.json').write_text(json.dumps(absolute))
        tiny.preflight(file, plan, receipt, sha256(receipt))
        (evidence/'runner/status.json').write_text(json.dumps(status))
        self.assertIn(str(checker/'hosted_picker/config.py'),result['checker']['files'])
        self.assertIn(str(checker/'local-ci.py'),result['checker']['files'])
        for mutation in ('plan', 'host', 'checker', 'worker', 'runner', 'hosted-helper'):
            changed = copy.deepcopy(result)
            if mutation == 'plan':
                changed['plan_sha256'] = 'a'*64
            elif mutation == 'host':
                changed['host']['node'] = 'unrelated host'
            elif mutation == 'checker':
                changed['checker']['files'].pop(str(checker/'scale_acceptance/native_tiny.py'))
            elif mutation == 'worker':
                changed['worker_receipt_sha256'] = 'a'*64
            elif mutation == 'hosted-helper':
                changed['checker']['files'].pop(str(checker/'hosted_picker/config.py'))
            else:
                changed['status'] = 'blocked'
            other = evidence/(mutation+'.json')
            control.create(other, changed)
            self.deny(lambda: tiny.preflight(file, plan, other, sha256(other)))
        status['attempts'][0]['status'] = 'failed'
        (evidence/'runner/status.json').write_text(json.dumps(status))
        self.deny(lambda: tiny.preflight(file, plan, receipt, sha256(receipt)), 'terminal maintained')

    def test_preflight_rejection_retires_only_exact_closed_no_controller_scope(self):
        from scale_acceptance import native_preflight as preparation
        plan=self.qualification_plan();file=self.work/'failed-plan.json'
        receipt,_,_=self.preflight_fixture(plan,file)
        root=Path(plan['owned_root']).parent
        operator=self.work/'operator.json';control.create(operator,dict(namespace=str(root)))
        failed=dict(path=str(root),plan=dict(path=str(file),sha256=sha256(file)),
                    preflight=dict(path=str(receipt),sha256=sha256(receipt)))
        failure=dict(controller_pid=None,qualification=False,error='retained actual preflight consumer rejection')
        terminal=dict(returncode=1,reaped=True,capture_files_closed=True,
            argv=['python','-B',str(Path(plan['harness']['root'])/'scripts/native-scale-runner.py'),
                  'supervise',str(operator),'--sha256',sha256(operator),'--execute'])
        pins=preparation.preflight_no_controller(failed,plan,failure,terminal)
        self.assertEqual({Path(pin['path']) for pin in pins},
            {operator,receipt,receipt.parent/'worker-result.json',receipt.parent/'runner/status.json',
             receipt.parent/'preparation-plan.json'})
        for mutation in ('controller','qualification','zero','bool-code','unreaped','open-capture','wrong-command','wrong-pref-sha'):
            bad_failure=copy.deepcopy(failure);bad_terminal=copy.deepcopy(terminal);bad_failed=copy.deepcopy(failed)
            if mutation=='controller':bad_failure['controller_pid']=123
            elif mutation=='qualification':bad_failure['qualification']=True
            elif mutation=='zero':bad_terminal['returncode']=0
            elif mutation=='bool-code':bad_terminal['returncode']=True
            elif mutation=='unreaped':bad_terminal['reaped']=False
            elif mutation=='open-capture':bad_terminal['capture_files_closed']=False
            elif mutation=='wrong-command':bad_terminal['argv'][-6]=str(self.work/'unrelated.py')
            else:bad_failed['preflight']['sha256']='0'*64
            with self.subTest(mutation=mutation):
                self.deny(lambda:preparation.preflight_no_controller(bad_failed,plan,bad_failure,bad_terminal))
        for name in ('data','campaign','qualify-invocation.json','reservation.json','controller-pid.json',
                     'controller-startup-created.json','controller-startup-failure.json','startup.json'):
            item=root/name;item.write_bytes(b'boundary crossed')
            with self.subTest(record=name):
                self.deny(lambda:preparation.preflight_no_controller(failed,plan,failure,terminal),'no-controller boundary')
            item.unlink()

    def test_selected_checker_module_roots_do_not_share_loaded_state(self):
        roots=[self.work/'one',self.work/'two']
        for root in roots:
            root.mkdir();(root/'checker.py').write_text('origin=__file__\n')
        one=host.module('checker',scripts=roots[0]);two=host.module('checker',scripts=roots[1])
        self.assertEqual(Path(one.origin),roots[0]/'checker.py')
        self.assertEqual(Path(two.origin),roots[1]/'checker.py')
        self.assertIsNot(one,two)

    def test_preflight_never_loads_checker_code_outside_selected_harness_pin(self):
        tiny=controller.tiny;plan=self.qualification_plan();file=self.work/'tiny-plan.json'
        receipt,result,_=self.preflight_fixture(plan,file)
        checker=Path(result['checker']['path'])
        checker.write_text("raise AssertionError('untrusted checker executed')\n")
        result['checker']['sha256']=sha256(checker)
        result['checker']['files'][str(checker)]=sha256(checker)
        receipt.write_text(json.dumps(result))
        self.deny(lambda:tiny.preflight(file,plan,receipt,sha256(receipt)), 'not the selected harness')

    def test_response_capture_descriptor_eof_precedes_parent_eof(self):
        child = '''
import json, sys
from scale_acceptance.native_scale_host import lock_owner_loop, seal_response_capture
def reply(value):
    print(json.dumps(value), flush=True)
lock_owner_loop(sys.stdin, reply, lambda _: None, lambda *_: None,
                lambda: None, lambda: dict(fake_only=True), seal_response_capture)
'''
        process = subprocess.Popen([sys.executable, '-B', '-c', child],
            cwd=Path(__file__).resolve().parent, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        lines, eof = queue.Queue(), threading.Event()
        def read():
            try:
                for line in process.stdout:
                    lines.put(json.loads(line))
            finally:
                eof.set()
        reader = threading.Thread(target=read)
        reader.start()
        try:
            process.stdin.write(json.dumps(dict(command='close', challenge='a'*64))+'\n')
            process.stdin.flush()
            self.assertTrue(lines.get(timeout=3)['ok'])
            self.assertTrue(eof.wait(2), 'response EOF must precede parent stdin EOF')
            reader.join(timeout=2)
            self.assertFalse(reader.is_alive())
            self.assertIsNone(process.poll(), 'original owner must await parent EOF')
        finally:
            process.stdin.close()
            try:
                code = process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
                raise
            finally:
                reader.join(timeout=3)
                process.stdout.close()
                errors = process.stderr.read()
                process.stderr.close()
        self.assertEqual(code, 0, errors)

    def test_windows_normal_close_seals_capture_before_original_owner_eof(self):
        events = []
        message = json.dumps(dict(command='close', challenge='a'*64))+'\n'
        def stream():
            yield message
            self.assertEqual(events, ['ack', 'capture-eof'])
            events.append('parent-eof')
        host.lock_owner_loop(stream(), lambda value: events.append('ack'), Mock(), Mock(), Mock(),
                             lambda: dict(original_lock=True), lambda: events.append('capture-eof'))
        self.assertEqual(events, ['ack', 'capture-eof', 'parent-eof'])
        owner = host.WindowsLockOwner.__new__(host.WindowsLockOwner)
        owner.request = lambda value: events.append(value['command'])
        owner.reader = Mock()
        owner.reader.is_alive.return_value = False
        owner.reader.join.side_effect = lambda timeout: events.append('join')
        owner.process = Mock()
        owner.process.stdout.close.side_effect = lambda: events.append('capture-close')
        owner.process.stdin.close.side_effect = lambda: events.append('original-owner-eof')
        owner.process.wait.side_effect = lambda timeout: events.append('reap') or 0
        events.clear()
        owner.close()
        self.assertEqual(events, ['close', 'join', 'capture-close', 'original-owner-eof', 'reap'])

    def test_tiny_read_exhaustion_denies_admission_but_leaves_cleanup_available(self):
        budget = controller.tiny.ReadBudget.__new__(controller.tiny.ReadBudget)
        budget.read_bytes, budget.visits, budget.failed = 0, 0, False
        budget.local, budget.mutex = threading.local(), threading.RLock()
        budget.limits = dict(read_bytes=1, visits=100)
        file = self.work/'oversized-metadata'
        file.write_bytes(b'two bytes exceed this explicit test budget')
        self.deny(lambda: budget.audit('open', (str(file), 'r', 0)), 'allowance exceeded')
        self.assertTrue(budget.failed)
        # No subsequent cleanup open is rejected by the audit hook. The sticky
        # check still denies every later worker/monitor admission.
        budget.audit('open', (str(file), 'r', 0))
        self.deny(budget.check, 'allowance exceeded')

    def test_primary_worker_failure_stays_failed_with_proven_cleanup(self):
        owner = host.Caretaker.__new__(host.Caretaker)
        owner.directory = self.work
        owner.process = Mock()
        owner.process.poll.return_value = 1
        owner.process.wait.return_value = 1
        owner.backup_job, owner.backup_cgroup = None, None
        owner.process.stdin.closed=True
        control.create(self.work/'cleanup.json', dict(errors=['worker died without result'], cleanup_errors=[], remaining=[],
            controller_eof=True,monitor_threads_joined=True,capture_writers_reaped=True))
        self.deny(owner.finish, 'caretaker failure')
        self.assertTrue(owner.cleanup_proven)

    def test_tiny_failure_preparation_uses_existing_runner_without_missing_approvals(self):
        plan = self.qualification_plan()
        root = Path(plan['owned_root'])
        operation = dict(stage='failure-prepare', shape='D', data=str(root/'failure-data'))
        execution = controller.runner_plan(plan, operation, self.work/'tiny-plan.json',
            root/'D-failure-prepare.json', root/'D-failure-prepare')
        step = execution['steps'][0]
        self.assertEqual(step['id'], 'failure-prepare')
        self.assertEqual(len(step['inputs']), 2)
        self.assertEqual(step['timeout_seconds'], control.LIMITS['generation_seconds'])
        self.assertEqual(step['argv'][3], '_phase')

    def test_tiny_host_lock_open_cannot_create_a_replacement(self):
        lock = host.HostLock()
        lock.existing = True
        with patch.object(host, 'module', return_value=Mock(host_lock_path=Mock(return_value=self.work/'original.lock'))), \
             patch.object(host, 'native_windows', return_value=False), \
             patch.object(host,'os',SimpleNamespace(O_RDWR=os.O_RDWR,O_CREAT=os.O_CREAT,
                 O_NOFOLLOW=getattr(os,'O_NOFOLLOW',0x20000),open=Mock(side_effect=FileNotFoundError('original absent')))) as fixture_os:
            opened=fixture_os.open
            self.deny(lock.__enter__, 'original absent')
        self.assertEqual(opened.call_args.args[1] & os.O_CREAT, 0)

    def test_tiny_metadata_allowance_is_explicit_and_never_increased_by_failure(self):
        plan = self.qualification_plan()
        allowance = plan['qualification']['metadata_per_process']
        before = allowance.copy()
        controller.tiny.metadata_limits(allowance)
        self.assertEqual(allowance, before)
        for value in ({'read_bytes': 0, 'visits': 1}, {'read_bytes': True, 'visits': 1},
                      {'read_bytes': 1, 'visits': -1}, {'read_bytes': 1, 'visits': 1, 'retry': 1}):
            self.deny(lambda: controller.tiny.metadata_limits(value), 'explicit positive')
        # A separately reviewed plan may declare its own finite preparation
        # allowance. This changes neither the fixed scale LIMITS nor old plans.
        allowance['visits'] = 3_000_000
        control.validate(plan)
        self.assertEqual(plan['limits'], control.LIMITS)

    def test_tiny_windows_unstarted_scale_namespace_stays_absent(self):
        plan, scale = self.windows_qualification_plan()
        # Only a future, never-created scale namespace can be absent. A
        # genuine retained directory cannot be relabelled unstarted.
        plan['qualification']['unstarted_scale_roots'] = [scale['owned_root']]
        self.deny(lambda: control.validate(plan), 'namespace appeared')
        future = self.work/'unstarted-large-data'
        scale['owned_root'] = str(future)
        scale['owned_roots'].append(str(future))
        reference = self.work/'windows-unstarted-plan.json'
        control.create(reference, scale)
        plan['qualification']['scale_plan'] = dict(path=str(reference), sha256=sha256(reference))
        plan['qualification']['unstarted_scale_roots'] = [str(future)]
        control.validate(plan)
        self.assertFalse(future.exists())
        future.mkdir()
        self.deny(lambda: control.validate(plan), 'namespace appeared')

    def test_tiny_windows_measurement_origin_retains_legacy_metrics_without_inventing_history(self):
        plan, scale = self.windows_qualification_plan()
        namespace = Path(plan['qualification']['namespace'])
        namespace.mkdir()
        legacy = namespace/'legacy-logical-and-unmeasured.json'
        control.create(legacy, dict(fake_only=True, logical_cap=1024, historical_allocated_bytes=None))
        pin = dict(path=str(legacy), sha256=sha256(legacy))
        def root_record(root):
            s = Path(root).stat()
            return dict(path=root, stat=dict(dev=s.st_dev, ino=s.st_ino, size=s.st_size,
                        mtime_ns=s.st_mtime_ns, ctime_ns=s.st_ctime_ns, mode=s.st_mode, nlink=s.st_nlink))
        baseline = lambda roots: dict(roots=[root_record(r) for r in roots], entries=[], sum_bytes=0)
        counter = dict(sum_bytes=0, entry_count=0, carry_bytes=0, prior_sampled_aggregate_highwater_bytes=0)
        history = dict(schema='native-tiny-windows-history-v1', host=plan['host'],
            scale_plan=plan['qualification']['scale_plan'], provenance=[pin], prior_generation_ms=0,
            allocation_origin=dict(kind='fresh-native-baseline; legacy metrics retained separately', legacy_records=[pin]),
            baselines=dict(native=baseline(scale['owned_roots']), source=baseline(scale['source_reservation']['roots'])),
            prior_storage=dict(native=counter.copy(), source=counter.copy()))
        # History does not establish allocations. The real Monitor/preflight
        # Storage admission must still reject this deliberately empty source B.
        file = namespace/'history.json'
        control.create(file, history)
        plan['qualification']['windows_history'] = dict(path=str(file), sha256=sha256(file))
        admitted = controller.tiny.History(plan)
        self.assertEqual(admitted.allocation_origin['legacy_records'], [pin])
        self.deny(lambda: monitor.Storage(admitted.baselines['source'], history['prior_storage']['source']), 'baseline inventory drift')
        for field, value in (('prior_generation_ms', -1), ('allocation_origin', dict(kind='historical-zero', legacy_records=[pin]))):
            changed = copy.deepcopy(history)
            changed[field] = value
            other = namespace/(field+'.json')
            control.create(other, changed)
            plan['qualification']['windows_history'] = dict(path=str(other), sha256=sha256(other))
            self.deny(lambda: controller.tiny.History(plan))

    def test_tiny_windows_peer_requires_final_clean_linux_chain(self):
        plan, _ = self.windows_qualification_plan()
        namespace = Path(plan['qualification']['namespace'])
        namespace.mkdir()
        q = dict(schema=controller.tiny.SCHEMA, passed=True, os='Linux', scale_acceptance=False,
                 scale_slots_consumed=0, plan_sha256='a'*64,
                 original_lock=dict(original_descriptor_closed=True, original_owner_lock_absent=True))
        report = dict(shape='D', rows=127, source_sha256='b'*64)
        envelope = dict(os='Linux', host=dict(os='Linux'), passed=True, evidence_kind='native-tiny',
            slot='LinuxD', product=plan['product']['commit'], plan_sha256='a'*64, report=report)
        control.create(namespace/'report.json', envelope)
        control.create(namespace/'qualification.json', q)
        control.create(namespace/'completion.json', dict(passed=True, evidence_kind='native-tiny', plan_sha256='a'*64,
            qualification_sha256=sha256(namespace/'qualification.json')))
        control.create(namespace/'campaign_record.json', dict(passed=True, evidence_kind='native-tiny',
            plan_sha256='a'*64, sha256=sha256(namespace/'report.json')))
        pins = {k: dict(path=str(namespace/(k+'.json')), sha256=sha256(namespace/(k+'.json')))
                for k in ('report', 'qualification', 'completion', 'campaign_record')}
        plan['qualification']['peers'] = dict(D=pins, G=pins)
        self.assertEqual(controller.tiny.peer_report(plan, 'D', 'b'*64), report)
        self.deny(lambda: controller.tiny.peer_report(plan, 'D', 'c'*64), 'size/source')
        q['passed'] = False
        (namespace/'qualification.json').write_text(json.dumps(q))
        pins['qualification']['sha256'] = sha256(namespace/'qualification.json')
        self.deny(lambda: controller.tiny.peer_report(plan, 'D'), 'clean released')

    def test_tiny_windows_preflight_denies_invalid_actual_allocation_baseline(self):
        from scale_acceptance import native_preflight
        plan, _ = self.windows_qualification_plan()
        namespace = Path(plan['qualification']['namespace'])
        plan['qualification']['windows_history'] = dict(path=str(namespace/'history.json'), sha256='a'*64)
        pins = {k: dict(path=str(namespace/(k+'.json')), sha256='a'*64)
                for k in ('report', 'qualification', 'completion', 'campaign_record')}
        plan['qualification']['peers'] = dict(D=pins, G=pins)
        class Selected:
            def __init__(self, plan):
                self.lineage = SimpleNamespace(value=dict(prior_storage=dict(Windows=dict(native={}, source={}))),
                                               baselines=dict(native={}, source={}))
            def check(self):
                pass
        Selected.__module__ = '_selected_tiny_control.native_scale_identity'
        storage = Mock(side_effect=ValueError('actual allocation baseline drift'))
        selected_tiny = Mock()
        def load(name):
            return SimpleNamespace(Storage=storage) if name.endswith('native_scale_monitor') else selected_tiny
        with patch.object(native_preflight, 'host', return_value=plan['host']), \
             patch.object(native_preflight, 'selected_identity', return_value=Selected), \
             patch('importlib.import_module', side_effect=load), \
             patch.object(controller, 'HostLock') as lock:
            self.deny(lambda: native_preflight.inspect(plan, Mock()), 'actual allocation baseline drift')
            lock.assert_not_called()
        selected_tiny.peer_report.assert_not_called()

    def test_tiny_pinned_json_rejects_change_between_hash_and_decode(self):
        file = self.work/'receipt.json'
        control.create(file, dict(passed=True))
        pin = dict(path=str(file), sha256=sha256(file))
        def replaced(path):
            file.write_text(json.dumps(dict(passed=False, unrelated='different record')))
            return pin['sha256']
        with patch.object(controller.tiny, 'sha256', side_effect=replaced):
            self.deny(lambda: controller.tiny.pinned_json(pin, 4096), 'changed during admission')

    def test_tiny_full_guard_deadline_failure_retains_complete_operation_timing(self):
        value = monitor.Monitor.__new__(monitor.Monitor)
        value.disk_operation = threading.Lock()
        value.plan = dict(qualification={})
        value.log = self.work/'capacity.jsonl'
        clock = [0]
        value.clock = lambda: clock[0]
        value.hot_sample = Mock()
        def disk(start):
            clock[0] = 31
            return {}
        value.disk_sample = disk
        self.deny(value.sample, 'disk observation deadline')
        timing = json.loads((self.work/'guard-operations.jsonl').read_text())
        self.assertFalse(timing['completed'])
        self.assertEqual(timing['seconds'], 31)
        self.assertEqual(timing['bound_seconds'], 30)

    def test_owned_and_tiny_storage_share_only_current_mutable_scope(self):
        value = monitor.Monitor.__new__(monitor.Monitor)
        current, campaign, old = self.work/'current', self.work/'campaign', self.work/'old'
        value.plan = dict(owned_root=str(current),campaign=str(campaign),source_reservation=dict(roots=[str(old)],bytes=1000))
        value.roots, value.volumes = [old,current,campaign], []
        value.storage, value.source_storage, value.tiny_storage = Mock(), Mock(), Mock()
        for storage in (value.storage,value.source_storage,value.tiny_storage):storage.sample.return_value=1
        value.deadline,value.clock,value.last_lock_proof = float('inf'),time.monotonic,{}
        value._disk_sample()
        value.storage.sample.assert_called_with(value.roots,mutable_roots=(current,campaign))
        value.source_storage.sample.assert_called_with([old])
        value.plan['qualification'] = dict(namespace=str(self.work),new_bytes=1000)
        value._disk_sample()
        value.storage.sample.assert_called_with(value.roots,mutable_roots=(current,campaign))
        value.tiny_storage.sample.assert_called_with([self.work],mutable_roots=(current,campaign))

    def test_capacity_age_uses_oldest_start_and_never_pulse_completion(self):
        sample = dict(sample_started_monotonic=0, sample_completed_monotonic=29)
        host.capacity_fresh(sample, 89.999)
        self.deny(lambda: host.capacity_fresh(sample, 90), 'capacity')
        self.deny(lambda: host.capacity_fresh(sample, 28), 'capacity')
        self.deny(lambda: host.capacity_fresh({**sample, 'sample_completed_monotonic':30},30), 'capacity')
        self.deny(lambda: host.capacity_fresh({**sample, 'sample_completed_monotonic':89},89), 'capacity')

    def test_slow_disk_keeps_hot_identity_checks_and_old_capacity_timestamp(self):
        value = monitor.Monitor.__new__(monitor.Monitor)
        value.disk_operation = threading.Lock()
        value.plan = dict(host={},source_reservation=dict(roots=[],bytes=1000),owned_root=str(self.work/'owned'),campaign=str(self.work/'campaign'))
        value.log, value.clock = self.work/'capacity.jsonl', time.monotonic
        value.runtime, value.lineage = 'runtime', None
        value.groups, value.git_freezes, value.dependencies, value.roots, value.volumes = [],[],[],[],[]
        value.externals = {}
        value.last_progress,value.deadline = value.clock(),float('inf')
        value.campaign,value.lock = Mock(),Mock()
        value.lock.proof.return_value = {}
        value.storage,value.source_storage = Mock(),Mock()
        value.source_storage.sample.return_value = 10
        old = dict(sample_started_monotonic=value.clock()-10, sample_completed_monotonic=value.clock()-5)
        value.last_capacity = old
        allowed = threading.Event()
        checks, pulses = [], []
        def hot():
            checks.append(value.clock())
            if len(checks)>=2:allowed.set()
        value.lock.check.side_effect = hot
        def disk(roots, **kwargs):
            self.assertTrue(allowed.wait(3),'actual hot identity was suppressed by disk wait')
            return 10
        value.storage.sample.side_effect = disk
        def pulse():
            pulses.append(value.last_capacity)
            self.assertIs(value.last_capacity,old)
        with patch.object(monitor.identity,'runtime_requirements',return_value='runtime'), \
                patch.object(monitor,'host',return_value={}):
            result=value.sample(pulse=pulse)
        self.assertGreaterEqual(len(checks),3)
        self.assertTrue(pulses)
        self.assertGreater(result['sample_started_monotonic'],old['sample_started_monotonic'])
        self.assertIs(value.last_capacity,result)

    def test_hot_guards_keep_file_tokens_without_walking_complete_namespaces(self):
        p = self.host_plan()
        with patch.object(monitor, 'git_metadata', return_value={}):
            value = monitor.Monitor(p, Mock(), Mock(), self.work/'split-capacity.jsonl')
        with patch.object(monitor, 'frozen_metadata', side_effect=ValueError('complete filesystem audit')), \
                patch.object(monitor, 'git_metadata', return_value={}):
            value.hot_sample(reviewing=True)
            with patch.object(value, '_disk_sample', return_value={}):
                self.deny(value.disk_sample, 'complete filesystem audit')
        tool = Path(p['executable']['path'])
        tool.write_text('changed token')
        with patch.object(monitor, 'git_metadata', return_value={}):
            self.deny(value.hot_sample, 'tool/executable drift')

    def test_complete_filesystem_audit_gates_publication_while_hot_pulses_continue(self):
        value = monitor.Monitor.__new__(monitor.Monitor)
        value.disk_operation = threading.Lock()
        value.plan, value.log, value.clock = {}, self.work/'gated-capacity.jsonl', time.monotonic
        old = dict(sample_started_monotonic=value.clock()-10,sample_completed_monotonic=value.clock()-5)
        value.last_capacity = old
        released = threading.Event()
        checks = []
        def hot(reviewing=False):
            checks.append(True)
            if len(checks)>=2:released.set()
        value.hot_sample = hot
        value._disk_sample = Mock(return_value={})
        def filesystem():
            self.assertTrue(value.disk_operation.locked())
            self.assertIs(value.last_capacity,old)
            self.assertTrue(released.wait(3),'filesystem wait suppressed hot ownership checks')
            raise ValueError('complete source identity drift')
        value.filesystem_sample = filesystem
        self.deny(value.sample,'complete source identity drift')
        self.assertGreaterEqual(len(checks),2)
        self.assertIs(value.last_capacity,old)
        self.assertFalse(value.log.exists())
        self.assertFalse(value.disk_operation.locked())

    def test_mutable_input_token_stays_hot_during_complete_filesystem_audit(self):
        p = self.host_plan()
        value = monitor.Monitor(p, Mock(), Mock(), self.work/'input-capacity.jsonl')
        source = self.work/'selected-input.csv'
        source.write_text('before')
        value.externals[source] = identity.stamp(source)
        entered, release, changed, finished = [threading.Event() for _ in range(4)]
        value._disk_sample = Mock(return_value={})
        def filesystem():
            entered.set()
            try:self.assertTrue(release.wait(3))
            finally:finished.set()
        value.filesystem_sample = filesystem
        def mutate():
            if entered.wait(2):
                source.write_text('changed selected input')
                changed.set()
        writer = threading.Thread(target=mutate)
        writer.start()
        try:
            with patch.dict(monitor.LIMITS,disk_observation_seconds=.7):
                self.deny(value.sample,'tool/executable drift')
            self.assertTrue(changed.is_set())
            self.assertTrue(value.disk_operation.locked())
            self.assertTrue(host.pending_calls())
            self.assertFalse(hasattr(value,'last_capacity'))
            self.assertFalse(value.log.exists())
        finally:
            release.set();writer.join(timeout=1)
            self.assertTrue(finished.wait(1))
            until=time.monotonic()+1
            while value.disk_operation.locked() and time.monotonic()<until:time.sleep(.001)
        self.assertFalse(value.disk_operation.locked())

    def test_exact_owner_disk_timing_refresh_preserves_all_other_policy(self):
        current = self.plan()
        previous = copy.deepcopy(current)
        previous['limits'] = dict(current['limits'],sample_seconds=1,stale_seconds=5)
        previous['limits'].pop('disk_observation_seconds')
        policy = controller.tiny.History._same_scale_policy
        self.assertTrue(policy(previous,current))
        self.assertTrue(policy(current,current))
        for field in ('owned_bytes','start_free_bytes','no_progress_seconds'):
            bad=copy.deepcopy(current);bad['limits'][field]+=1
            self.assertFalse(policy(previous,bad))
        for field in ('sample_seconds','stale_seconds','disk_observation_seconds'):
            bad=copy.deepcopy(current);bad['limits'][field]+=1
            self.assertFalse(policy(previous,bad))
        bad=copy.deepcopy(current);bad['product']['commit']='f'*40
        self.assertFalse(policy(previous,bad))
        bad=copy.deepcopy(current);bad['source_reservation']['roots'].append('/unadmitted')
        self.assertFalse(policy(previous,bad))

    def test_failed_hot_poll_cannot_overlap_cleanup_disk_or_refund_highwater(self):
        value=monitor.Monitor.__new__(monitor.Monitor)
        value.disk_operation=threading.Lock()
        value.plan,value.log,value.clock={},self.work/'capacity.jsonl',time.monotonic
        release,done=threading.Event(),threading.Event()
        high,calls={},[]
        def hot(reviewing=False):
            calls.append('hot')
            if calls.count('hot')==2:raise ValueError('hot identity failed')
        value.hot_sample=hot
        entered=[]
        def disk(start=False):
            entered.append('disk')
            high['known']=max(high.get('known',0),4096)
            try:
                release.wait(3)
                high['known']=max(high['known'],8192)
                return {}
            finally:
                done.set()
        value._disk_sample=disk
        value.filesystem_sample=Mock()
        try:
            with patch.dict(monitor.LIMITS,disk_observation_seconds=.7):
                self.deny(value.sample,'hot identity failed')
            self.assertTrue(value.disk_operation.locked())
            self.assertTrue(host.pending_calls())
            self.deny(value.sample,'still pending')
            self.assertEqual(entered,['disk'])
            self.assertEqual(high,{'known':4096})
            self.assertFalse(hasattr(value,'last_capacity'))
            held=host.HostLock();held.owner=Mock()
            with patch.object(host,'retain_host_lock',side_effect=OSError('original owner retained')):
                self.deny(lambda:held.__exit__(None,None,None),'original owner retained')
            held.owner.close.assert_not_called()
        finally:
            release.set()
            self.assertTrue(done.wait(1))
            until=time.monotonic()+1
            while value.disk_operation.locked() and time.monotonic()<until:time.sleep(.001)
        self.assertFalse(value.disk_operation.locked())
        self.assertEqual(high,{'known':8192})

    def test_disk_start_interval_is_independent_of_completion_age(self):
        value=monitor.Monitor.__new__(monitor.Monitor)
        value.plan,value.log,value.clock={},self.work/'capacity.jsonl',lambda:45
        value.last_capacity=dict(sample_started_monotonic=0,sample_completed_monotonic=29)
        value.hot_sample=Mock()
        self.deny(value.sample,'start interval')
        value.hot_sample.assert_not_called()

    def test_disk_poll_failure_retains_pending_operation_and_generic_bound(self):
        import inspect
        self.assertEqual(inspect.signature(host.bounded).parameters['seconds'].default,2)
        release, done = threading.Event(), threading.Event()
        def disk():
            try:
                release.wait(2)
            finally:
                done.set()
        def failed_identity():
            raise ValueError('actual identity drift during disk observation')
        try:
            self.deny(lambda: host.bounded(disk,seconds=1,poll=failed_identity),'identity drift')
            self.assertTrue(host.pending_calls())
        finally:
            release.set()
            self.assertTrue(done.wait(1))

    def test_native_preparation_inventory_includes_proof_closure_but_not_old_large_payload(self):
        from scale_acceptance import native_preflight
        plan = self.plan()
        metadata = self.work/'old-checkpoint.json'
        old_csv = self.work/'old-10GB-input.csv'
        reconciliation, receipt = self.work/'reconciliation.json', self.work/'build-receipt.json'
        proof = dict(source_reconciliation=dict(path=str(reconciliation), sha256='a'*64),
                     runner_receipts=[dict(path=str(receipt), sha256='b'*64)])
        lineage = dict(adopt=dict(input=dict(path=str(old_csv), stat={}, expected_sha256='c'*64),
                                 checkpoint=dict(path=str(metadata), sha256='d'*64)))
        def read(file, limit):
            return proof if str(file) == plan['build_proof']['path'] else lineage
        with patch.object(native_preflight, 'read_json', side_effect=read):
            inventory = native_preflight.preparation_inputs(plan)
        self.assertTrue({str(metadata), str(reconciliation), str(receipt)} <= set(inventory))
        self.assertNotIn(str(old_csv), inventory)
        self.assertIn(str(Path(plan['harness']['root'])/'source.py'), inventory)

    def test_native_preparation_inventory_includes_tiny_windows_peers_and_legacy_records(self):
        from scale_acceptance import native_preflight
        plan, _ = self.windows_qualification_plan()
        namespace = Path(plan['qualification']['namespace'])
        history = namespace/'history.json'
        legacy = namespace/'legacy-metrics.json'
        peer = namespace/'linux-tiny-report.json'
        plan['qualification']['windows_history'] = dict(path=str(history), sha256='a'*64)
        plan['qualification']['peers'] = {s: {'report': dict(path=str(peer), sha256='b'*64)} for s in ('D', 'G')}
        proof = dict(source_reconciliation=dict(path=str(namespace/'reconciliation.json'), sha256='c'*64), runner_receipts=[])
        stored = dict(allocation_origin=dict(legacy_records=[dict(path=str(legacy), sha256='d'*64)]))
        def read(file, limit):
            return stored if str(file) == str(history) else proof
        with patch.object(native_preflight, 'read_json', side_effect=read):
            inventory = native_preflight.preparation_inputs(plan)
        self.assertTrue({str(history), str(legacy), str(peer), plan['qualification']['scale_plan']['path']} <= set(inventory))


def native_storage_rename_probe(directory, *, control_io=False):
    """Real NTFS atomic metadata publication races; no fake allocation values."""
    host.require(os.name == 'nt', 'native Windows component only')
    from scale_acceptance import native_tiny, _native_file as native_file
    native_tiny.budget = native_tiny.ReadBudget(dict(qualification=dict(metadata_per_process=dict(
        read_bytes=256*1024**2, visits=200000))), Path(__file__))
    parent_before = identity.stat_fields(directory.parent.stat(),0,directory.parent)
    directory.mkdir(parents=True, exist_ok=False)
    cases = []
    phase = 'reservation'
    io_result = None
    observer_identity = host.module('browser-small-windows').process_identity(os.getpid())
    with host.HostLock() as held:
        proof = held.proof()
        control.create(directory/'reservation.json', dict(original_lock=proof,observer_identity=observer_identity))
        def observe():
            nonlocal phase, io_result
            windows = host.module('browser-small-windows')
            for variant in ('before-lstat', 'before-allocation', 'after-fstat', 'replace-final', 'same-file-growth', 'replace-after-open'):
                phase = variant
                root = directory/variant
                root.mkdir()
                temporary, final = root/'owner-sample.tmp', root/'owner-sample.json'
                if variant in ('replace-final','replace-after-open'):
                    host.publish(final,dict(generation=0,pids=[]),mutable=control_io)
                elif variant == 'same-file-growth':
                    final.write_bytes(b'x'*64)
                else:
                    temporary.write_bytes(b'x'*64)
                moved = False
                leaf_stats = 0
                real_walk, real_allocation = os.walk, monitor._allocated_bytes
                def move():
                    nonlocal moved
                    if not moved:
                        if variant in ('replace-final','replace-after-open'):
                            host.publish(final,dict(generation=1,pids=[123]),mutable=control_io)
                        elif variant == 'same-file-growth':
                            with final.open('ab') as stream:stream.write(b'y')
                        else:
                            (windows.replace_control_snapshot if control_io else os.replace)(temporary, final)
                        moved = True
                class ProbePath(type(Path())):
                    def lstat(self):
                        nonlocal leaf_stats
                        if self == (final if variant == 'same-file-growth' else temporary):
                            leaf_stats += 1
                            if variant in ('after-fstat','same-file-growth') and leaf_stats == 2:
                                move()
                        return super().lstat()
                def walk(*args, **kwargs):
                    for value in real_walk(*args, **kwargs):
                        if variant == 'before-lstat':move()
                        yield value
                def allocation(p, observed):
                    if variant in ('before-allocation','replace-final'):move()
                    return real_allocation(p, observed)
                native_api = native_file._windows_api()
                queried = []
                publisher, publication_errors = None, []
                attempted = threading.Event()
                from scale_acceptance import guard
                runner = guard.load_runner()
                real_write = runner.write_json
                publication_attempts = []
                def write(*args, **kwargs):
                    try:
                        return real_write(*args, **kwargs)
                    except OSError as error:
                        publication_attempts.append(dict(error=str(error),winerror=getattr(error,'winerror',None)))
                        raise
                    finally:
                        attempted.set()
                def publish():
                    try:
                        move()
                    except BaseException as error:
                        publication_errors.append(error)
                class API:
                    def __getattr__(self, name):return getattr(native_api[0],name)
                    def GetFileInformationByHandleEx(self, handle, kind, pointer, size):
                        nonlocal publisher
                        if kind == 1 and variant == 'replace-after-open' and publisher is None:
                            # The publisher may retry after this reader closes; never wait
                            # for its completion while retaining the destination handle.
                            publisher = threading.Thread(target=publish)
                            publisher.start()
                            host.require(attempted.wait(2), 'publisher first attempt not observed')
                        result = native_api[0].GetFileInformationByHandleEx(handle,kind,pointer,size)
                        if result and kind == 1:
                            info = pointer._obj
                            queried.append(dict(deleted=bool(info.deleted),links=info.links,size=info.size,
                                                allocated=info.allocation,directory=bool(info.directory)))
                        return result
                storage = monitor.Storage()
                if variant in ('replace-final','same-file-growth','replace-after-open'):
                    storage.sample([root])  # Retain the completed old allocation.
                started = time.monotonic()
                completed, failure, charge = False, None, None
                before_path = final if final.exists() else temporary
                before = identity.stat_fields(before_path.stat(),real_allocation(before_path,before_path.stat()),before_path)
                try:
                    with patch.object(monitor, 'Path', ProbePath), patch.object(os, 'walk', walk), \
                            patch.object(monitor, '_allocated_bytes', side_effect=allocation), \
                            patch.object(native_file, '_windows_api', return_value=(API(),*native_api[1:])), \
                            patch.object(guard, 'load_runner', return_value=runner), \
                            patch.object(runner, 'write_json', side_effect=write):
                        try:
                            charge = storage.sample([root], mutable_roots=(root,))
                        finally:
                            if publisher is not None:
                                # The outer tracked 30s call fences a blocked publisher;
                                # its callback keeps these patches until every writer exits.
                                publisher.join()
                                for pending in host.pending_calls():
                                    if pending is not threading.current_thread():pending.join()
                        if publication_errors:raise publication_errors[0]
                        if variant == 'replace-after-open':
                            charge = storage.sample([root], mutable_roots=(root,))
                    completed = True
                except ValueError as error:
                    if not ((variant in ('replace-final','same-file-growth') and 'native file identity/metadata drift' in str(error)) or
                            (variant == 'replace-after-open' and str(error) in ('invalid native file allocation','native file identity/metadata drift'))):
                        raise
                    failure = dict(type=type(error).__name__,error=str(error))
                host.require(moved and final.is_file() and not temporary.exists(), 'real publication mutation not observed')
                if completed:
                    expected_count = 2 if variant in ('replace-final','replace-after-open') else 1
                    # A concurrent walk may also charge the publisher's temporary name.
                    count_ok = len(storage.high) >= expected_count if variant == 'replace-after-open' else len(storage.high) == expected_count
                    host.require(charge >= final.stat().st_size and count_ok and
                                 any(key[1:] == (before['dev'],before['ino']) for key in storage.high),
                                 'complete final allocation/retired highwater required')
                after = identity.stat_fields(final.stat(),real_allocation(final,final.stat()),final)
                cases.append(dict(variant=variant, completed=completed, failure=failure, before=before,after=after,
                                  charge=charge, queried_standard=queried, publication_attempts=publication_attempts,
                                  publisher_joined=publisher is None or not publisher.is_alive(), seconds=time.monotonic()-started,
                                  high=[dict(path=key[0],dev=key[1],ino=key[2],charge=value)for key,value in storage.high.items()]))
            if control_io:
                phase = 'held-control-snapshot'
                leaves = [directory/('capacity-sample'+'x'*padding+'.json')for padding in range(4)]
                residues = {len(str(leaf).encode('utf-16le'))//2%4 for leaf in leaves}
                host.require(residues=={0,1,2,3},'all UTF16 rename buffer alignments required')
                for leaf in leaves:host.publish(leaf,dict(generation=0,padding='x'*70000),mutable=True)
                retired_versions = []
                for generation in range(1,34):
                    leaf=leaves[(generation-1)%4]
                    observed = leaf.stat()
                    retired_versions.append(identity.stat_fields(observed,_allocated_bytes(leaf,observed),leaf))
                    def charge(size):
                        budget = native_tiny.budget
                        with budget.mutex:
                            if size is None:budget.visits += 1
                            else:budget.read_bytes += size
                            budget.check()
                        if size is not None:
                            host.publish(leaf,dict(generation=generation,padding='x'*70000),mutable=True)
                    old = json.loads(windows.read_control_snapshot(leaf,1024**2,charge=charge))
                    current = host.read_control_json(leaf)
                    host.require(old['generation']==max(0,generation-4) and current['generation']==generation,
                                 'held old snapshot/current Native channel mismatch')
                io_result = dict(publications=33,old_versions_checked=33,current_versions_checked=33,
                                 maximum=1024**2,body_above_64KiB=True,checked_closes=True,utf16_destination_residues=sorted(residues),
                                 retired_versions=retired_versions,
                                 retired_logical_allocation_envelope=sum(max(row['size'],row['allocated_bytes'])for row in retired_versions))
        try:
            host.bounded(observe, seconds=30)
            host.require(not host.pending_calls(), 'metadata queries not joined')
        except BaseException as error:
            pending = bool(host.pending_calls())
            held.cleanup_uncertain = True
            # Save immutable facts before HostLock may retain this process indefinitely.
            try:
                control.create(directory/'failure.json', dict(measurement_complete=False,candidate_supported=False,
                               qualification=False,component_only=True,phase=phase,error=repr(error),
                               traceback=''.join(traceback.format_exception(error))[-8192:],
                               pending_callbacks=pending,closure_proof='unproven after unexpected component failure',
                               cases=None if pending else copy.deepcopy(cases),original_lock=proof,
                               observer_identity=observer_identity))
            except BaseException:
                pass  # A diagnostic failure must not replace the primary error/owner fence.
            raise
    control.create(directory/'result.json', dict(measurement_complete=True,candidate_supported=all(case['completed']for case in cases),qualification=False,component_only=True,
                   cases=cases,release=held.released,parent_before=parent_before,control_io=io_result,producer='POSIX mutable control' if control_io else 'legacy publisher',original_lock=proof,observer_identity=observer_identity,callbacks_joined=True,metadata_usage=native_tiny.budget_usage()))


def native_storage_control_audit(directory, result_sha):
    """Independent completed publication/Original release and closed point."""
    from scale_acceptance.native_preflight import observe_baseline
    from scale_acceptance import native_tiny
    started = time.monotonic()
    def check():
        native_tiny.budget.check()
        host.require(time.monotonic()-started<30,'publication audit deadline')
    host.require(sha256(directory/'result.json')==result_sha,'exact completed publication result')
    result=read_json(directory/'result.json',1024**2)
    host.require(result['measurement_complete'] and result['callbacks_joined'] and
        len(result['cases'])==6 and result['control_io']['publications']==33 and
        result['control_io']['utf16_destination_residues']==[0,1,2,3] and
        result['candidate_supported']==all(case['completed']for case in result['cases']),
        'completed six-case POSIX/control snapshot measurement required')
    released=result['release']
    host.require(released['original_descriptor_closed'] and released['capture_eof_joined'],
                 'positive original owner release protocol required')
    births=host.module('test-native-file-allocation').exited_births(
        [result['observer_identity'],released['owner_identity']])
    lock=Path(released['path'])
    host.require(identity.stamp(lock)==released['stat'],'same original inode/stat')
    native_lifecycle_fixture_byte0(lock,available=True)
    host.require(identity.stamp(lock)==released['stat'],'original stat after probe close')
    point=observe_baseline([directory],SimpleNamespace(check=check))
    files={str(path.relative_to(directory)):dict(stat=identity.stamp(path),sha256=sha256(path))
           for path in directory.rglob('*')if path.is_file()}
    parent=identity.stat_fields(directory.parent.stat(),0,directory.parent)
    parent_delta=max(0,parent['size']-result['parent_before']['size'])
    current={(row['stat']['dev'],row['stat']['ino']):row['charge_bytes']for row in point['entries']}
    high=dict(current)
    for case in result['cases']:
        for row in case['high']:
            key=(row['dev'],row['ino']);high[key]=max(high.get(key,0),row['charge'])
    for row in result['control_io']['retired_versions']:
        key=(row['dev'],row['ino']);high[key]=max(high.get(key,0),row['size'],row['allocated_bytes'])
    retired=sum(high.values())-sum(current.values())
    directories=[identity.stat_fields(Path(folder).stat(),0,Path(folder))
                 for folder,_,_ in os.walk(directory)]
    directory_eof=sum(row['size']for row in directories)
    total=sum(high.values())+directory_eof+parent_delta
    host.require(total<=8*1024**2,'publication fixture charge envelope')
    check()
    control.create(directory.parent/(directory.name+'-after-exit.json'),dict(cleanup_passed=True,
        qualification=False,candidate_supported=result['candidate_supported'],result_sha256=result_sha,
        births=births,original_byte0_available_unlocked_closed=True,current_point=point,
        current_files=files,retained_observation_delta=retired,current_directories=directories,
        parent_positive_logicalEOF_delta=parent_delta,conservative_current_plus_retired=total,
        physical_peak='unknown',metadata_usage=native_tiny.budget_usage()))


def native_job_exit_probe(directory, candidate=None, *, transitional=False):
    """Owned tiny child exits after a real Job snapshot and before its image query."""
    import ctypes
    host.require(os.name == 'nt', 'native Windows component only')
    from scale_acceptance import native_tiny
    if not hasattr(native_tiny,'budget'):
        native_tiny.budget = native_tiny.ReadBudget(dict(qualification=dict(metadata_per_process=dict(
            read_bytes=256*1024**2, visits=200000))), Path(__file__))
    directory.mkdir(parents=True, exist_ok=False)
    windows = host.module('browser-small-windows')
    kernel = (candidate or windows).kernel()
    receipts = []
    observer_identity = windows.process_identity(os.getpid())
    scope = host.HostLock() if candidate is None else nullcontext(SimpleNamespace(cleanup_uncertain=False,proof=lambda:None))
    with scope as held:
        proof = held.proof()
        control.create(directory/'reservation.json', dict(original_lock=proof, observer_identity=observer_identity))
        def observe():
            variants = (('live-image31','live-image5','old-exit-during-census','candidate-exit-during-census') if candidate else
                        ('live-image31','live-image5','exit-image','exit-after-identity'))
            if transitional:variants=('live-image31','live-image5','old-pending-exit','candidate-pending-exit','expired-pending-exit')
            for variant in variants:
                selected = windows if candidate is None or variant.startswith('old-') else candidate
                root = directory/variant
                root.mkdir()
                gate = root/'exit'
                job = host.windows_bootstrap.create_job(windows)
                process = host.windows_bootstrap.SuspendedWorker()
                assigned = False
                try:
                    with (root/'stdout.log').open('xb') as out, (root/'stderr.log').open('xb') as err:
                        child = "from pathlib import Path;import time; p=Path(%r); end=time.monotonic()+10\nwhile not p.exists() and time.monotonic()<end:time.sleep(.01)\nraise SystemExit(0 if p.exists() else 2)" % str(gate)
                        process.start([sys.executable, '-I', '-B', '-c', child], out, err, dict(os.environ))
                        process.assign(job)
                        assigned = True
                        process.resume()
                    census = windows.query_job(job)
                    host.require(census['pids'] == [process.pid], 'owned test snapshot mismatch')
                    before = windows.process_identity(process.pid)
                    control.create(root/'identity.json',before)
                    image_errors, observations = [], []
                    class Backend:
                        def __getattr__(self, name):
                            return getattr(kernel, name)
                        def QueryFullProcessImageNameW(self, *args):
                            if variant == 'exit-image':
                                gate.write_bytes(b'x')
                                host.require(process.wait(5) == 0, 'controlled child exit failed')
                                result = kernel.QueryFullProcessImageNameW(*args)
                                image_errors.append(0 if result else ctypes.get_last_error())
                                return result
                            if variant in ('live-image31','live-image5','old-exit-during-census','candidate-exit-during-census','old-pending-exit','candidate-pending-exit','expired-pending-exit'):
                                code = 31 if variant == 'live-image31' else 5
                                image_errors.append(code)
                                ctypes.set_last_error(code)
                                return 0
                            result = kernel.QueryFullProcessImageNameW(*args)
                            image_errors.append(0 if result else ctypes.get_last_error())
                            return result
                        def WaitForSingleObject(self, handle, timeout):
                            value=kernel.WaitForSingleObject(handle,timeout)
                            observations.append(dict(operation='wait',state=value))
                            return value
                        def GetExitCodeProcess(self, handle, output):
                            if variant.endswith('pending-exit') and not gate.exists():
                                host.require(observations[-1]==dict(operation='wait',state=258),
                                             'real live wait required before controlled exit')
                                gate.write_bytes(b'x');host.require(process.wait(1)==0,'native pending-exit completion failed')
                                if variant=='expired-pending-exit':time.sleep(.06)
                            value=kernel.GetExitCodeProcess(handle,output)
                            observations.append(dict(operation='exit',api=bool(value),code=output._obj.value))
                            return value
                        def QueryInformationJobObject(self, *args):
                            if variant in ('old-exit-during-census','candidate-exit-during-census'):
                                host.require(observations and observations[0]['state']==258,'child must be live before fresh census')
                                gate.write_bytes(b'x')
                                host.require(process.wait(1)==0,'controlled in-census exit failed')
                                observations.append(dict(operation='fresh-census-after-reap'))
                            if variant == 'exit-after-identity':
                                gate.write_bytes(b'x')
                                host.require(process.wait(5) == 0, 'controlled post-identity exit failed')
                            value=kernel.QueryInformationJobObject(*args)
                            if value and args[1]==3:
                                body=args[2]._obj
                                observations.append(dict(operation='real-job-census',pids=list(body.pids[:body.count])))
                            return value
                    try:
                        started = time.monotonic()
                        endpoint=started+(.05 if variant=='expired-pending-exit' else 2)
                        kwargs=dict(deadline=endpoint) if transitional and not variant.startswith('old-') else {}
                        result = host.bounded(lambda: selected.job_processes(job,census,[before],Backend(),**kwargs), seconds=2)
                    except selected.ProcessImageQueryError as error:
                        expected_live = variant in ('live-image31','live-image5') and process.poll() is None
                        expected_old = variant in ('old-exit-during-census','old-pending-exit','expired-pending-exit') and process.poll()==0
                        host.require((expected_live or expected_old) and error.winerror==(31 if variant=='live-image31' else 5),
                                     'unexpected image-query failure')
                        result = dict(live_image_error_denied=error.winerror,notes=list(getattr(error,'__notes__',())))
                    else:
                        host.require(variant in ('exit-image','exit-after-identity','candidate-exit-during-census','candidate-pending-exit') and result['census']['pids'] == [] and result['processes'] == [],
                                     'exited image query not reconciled')
                    elapsed = time.monotonic()-started
                    host.require(elapsed < 2, 'component process census exceeded production hot bound')
                    expected_error = {'live-image31':31,'live-image5':5,'old-exit-during-census':5,'candidate-exit-during-census':5,'old-pending-exit':5,'candidate-pending-exit':5,'expired-pending-exit':5,'exit-after-identity':0}.get(variant)
                    host.require(image_errors == [expected_error] if expected_error is not None else
                                 len(image_errors) == 1 and image_errors[0] != 0,
                                 'expected native/injected image-query branch not observed')
                    receipts.append(dict(variant=variant, pid=process.pid, before=before, result=result, image_errors=image_errors,observations=observations, seconds=elapsed, bound_seconds=2))
                finally:
                    try:
                        if process.known_process():
                            if process.poll() is None:
                                gate.write_bytes(b'x')
                            process.wait(5)
                        if assigned:
                            host.require(windows.query_job(job)['pids'] == [], 'component Job not empty')
                        process.close()
                        windows.close(job)
                    except BaseException:
                        held.cleanup_uncertain = True
                        raise
        try:
            host.bounded(observe, seconds=25)
            host.require(not host.pending_calls(), 'component queries not joined')
        except BaseException as error:
            held.cleanup_uncertain = getattr(held, 'cleanup_uncertain', False) or bool(host.pending_calls())
            try:
                control.create(directory/'failed.json',dict(error=repr(error),
                    traceback=''.join(traceback.format_exception(error))[-8192:],
                    controls=None if host.pending_calls() else copy.deepcopy(receipts),
                    pending_callbacks=bool(host.pending_calls()),closure_uncertain=held.cleanup_uncertain,
                    Original_touched=candidate is None,qualification=False))
            except BaseException:pass
            if candidate is not None and held.cleanup_uncertain:
                host.retain_host_lock('private process component closure uncertain')
            raise
        proof = held.proof()
    control.create(directory/'result.json', dict(component_only=True, qualification=False, passed=True,
                   controls=receipts, original_lock=proof, Original_touched=candidate is None,observer_identity=observer_identity, callbacks_joined=True, metadata_usage=native_tiny.budget_usage()))


def native_job_exit_audit(directory, result_sha):
    identity.require(sha256(directory/'result.json')==result_sha,'exact completed process component required')
    result=read_json(directory/'result.json',65536)
    identity.require(result['passed'] and result['callbacks_joined'] and not result['Original_touched'],
                     'closed private process component required')
    births=[result['observer_identity']]+[case['before'] for case in result['controls']]
    exited=host.module('test-native-file-allocation').exited_births(births)
    files={str(path.relative_to(directory)):dict(stat=identity.stamp(path),sha256=sha256(path))
           for path in directory.rglob('*') if path.is_file()}
    identity.require(sum(value['stat'][2] for value in files.values())<=1024**2,'component fixture bound')
    control.create(directory/'after-exit.json',dict(passed=True,qualification=False,Original_touched=False,
        result_sha256=result_sha,births=exited,closed_fixture_files=files,metadata_usage=controller.tiny.budget_usage()))



def native_lifecycle_read(name, remaining, terminal=lambda:None):
    while True:
        remaining()
        if name.exists():
            raw=name.read_bytes()
            identity.require(len(raw)<=65536,'bounded fixture record')
            if raw.endswith(b'\n'):
                return json.loads(raw)  # A complete malformed publication is a genuine failure.
        terminal()
        time.sleep(.01)


def native_lifecycle_producer_terminal(directory):
    failure,cleanup=directory/'caretaker-failure.json',directory/'cleanup.json'
    if failure.exists() and cleanup.exists():
        bodies=[path.read_bytes() for path in (failure,cleanup)]
        identity.require(all(len(raw)<=65536 for raw in bodies),'bounded producer failure records')
        if all(raw.endswith(b'\n') for raw in bodies):
            producer,closed=map(json.loads,bodies)
            raise ValueError('fixture caretaker completed before handoff: '+producer['error'])


def native_lifecycle_close_failed(owner, backup, directory, windows):
    """Release an ordinary failed fixture only with positive owned closure."""
    identity.require(not [t for t in host.pending_calls() if t is not threading.current_thread()],
                     'fixture query remains pending')
    if owner is None:
        identity.require(backup is None,'fixture backup without keeper closure')
        return dict(keeper_scope_closed=True,no_keeper_started_or_already_closed=True)
    raw=(directory/'cleanup.json').read_bytes()
    identity.require(len(raw)<=65536 and raw.endswith(b'\n'),'completed fixture cleanup required')
    proof=json.loads(raw)
    identity.require(proof['remaining']==[] and proof['cleanup_errors']==[] and
        proof['monitor_threads_joined'] and proof['capture_writers_reaped'],'positive failed fixture quiescence')
    if backup is not None:
        identity.require(windows.query_job(backup)['pids']==[],'failed fixture backup not empty')
    if owner.process.poll() is None:
        identity.require(not owner.failed,'fixture RPC already poisoned')
        owner.request(dict(command='finish'),seconds=15)
        owner.close()
    identity.require(owner.process.poll()==0 and owner.capture_eof and not owner.reader.is_alive() and
        owner.process.stdin.closed and owner.process.stdout.closed,'failed fixture keeper closure unproven')
    owner.process._handle.Close()
    if backup is not None:windows.close(backup)
    return dict(keeper_scope_closed=True,backup_closed=True,cleanup=proof,capture_eof_joined=True,
                keeper_reaped=True,keeper_process_handle_closed=True)


def native_lifecycle_child_handoff(case, read, windows, backup, worker, caretaker):
    if case.name not in ('worker-failure','pipe-after-failure'):
        read(case/'containment.json')
        now=time.monotonic()
        host.publish(case/'capacity-sample.json',dict(sample_started_monotonic=now,sample_completed_monotonic=now))
        host.publish(case/'supervisor-ready.json',dict(caretaker_pid=caretaker['pid']))
        read(case/'ready.json')
    child=read(case/'descendant.json')
    if case.name not in ('worker-failure','pipe-after-failure'):
        identity.require(set(windows.query_job(backup)['pids'])=={worker['pid'],child['pid']},
                         'actual fixture descendant ownership')
    return child


def native_lifecycle_command(mode, directory):
    return [sys.executable,'-B',str(Path(__file__).resolve()),mode,
            str(_SELECTED_SCRIPTS.parent),str(directory),sys.argv[4]]


def native_lifecycle_child(mode, directory):
    """Only fixed fixture argv are substituted; runtime ownership stays selected."""
    if mode=='--native-lifecycle-descendant':
        time.sleep(20)
        return
    windows = host.module('browser-small-windows')
    if mode == '--native-lifecycle-owner':
        saved = subprocess.Popen
        def launch(argv,*args,**kwargs):
            identity.require(argv == [sys.executable,'-B',str(_SELECTED_SCRIPTS/'native-scale-runner.py'),
                '_caretaker',str(directory/'plan.json'),str(directory/'operation.json'),str(directory)],
                'fixed fixture caretaker argv required')
            return saved(native_lifecycle_command('--native-lifecycle-caretaker',directory),*args,**kwargs)
        retain = host.retain_host_lock
        def observed_retain(platform):
            host.publish(directory/'retaining.json',dict(pid=os.getpid(),reason=platform))
            return retain(platform)
        with patch.object(host.subprocess,'Popen',launch),patch.object(host,'retain_host_lock',observed_retain):
            host.windows_lock_owner(directory/'fixture.lock',existing=True)
        return
    if mode == '--native-lifecycle-caretaker':
        host.publish(directory/'caretaker-identity.json',windows.process_identity(os.getpid()))
        base = host.windows_bootstrap.SuspendedWorker
        class FixtureWorker(base):
            def start(self,argv,out,err,env):
                identity.require(argv == [sys.executable,'-B',str(_SELECTED_SCRIPTS/'native-scale-runner.py'),
                    '_worker',str(directory/'plan.json'),str(directory/'operation.json'),str(directory)],
                    'fixed fixture worker argv required')
                return super().start(native_lifecycle_command('--native-lifecycle-worker',directory),out,err,env)
            def assign(self,job):
                super().assign(job)
                census=windows.query_job(job)
                identity.require(census['kill_on_close'] and census['pids']==[self.pid] and
                    not (directory/'worker-identity.json').exists(),'suspended fixture assignment required')
                host.publish(directory/'before-resume.json',dict(caretaker=os.getpid(),job_handle=job,
                    worker=windows.process_identity(self.pid),census=census))
            def wait(self,timeout):
                code=super().wait(timeout)
                host.publish(directory/'worker-wait.json',dict(pid=self.pid,exit_code=code))
                return code
        create = host.create
        def publication(name,value):
            if Path(name).name=='cleanup.json' and directory.name=='retained-proof':
                host.publish(directory/'withheld-cleanup.json',value)
                raise OSError('injected fixture cleanup-publication failure')
            return create(name,value)
        with patch.object(host.windows_bootstrap,'SuspendedWorker',FixtureWorker),patch.object(host,'create',publication):
            host.caretaker(directory/'plan.json',directory/'operation.json',directory)
        return
    host.publish(directory/'worker-identity.json',windows.process_identity(os.getpid()))
    deadline=time.monotonic()+3
    while not (directory/'parent-captured-census.json').exists():
        identity.require(time.monotonic()<deadline,'fixture backup handoff timeout')
        time.sleep(.01)
    def descendant():
        child=subprocess.Popen(native_lifecycle_command('--native-lifecycle-descendant',directory),
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True)
        host.publish(directory/'descendant.json',windows.process_identity(child.pid))
    if directory.name in ('worker-failure','pipe-after-failure'):
        descendant()
        raise SystemExit(7)
    runner=host.module('validation-runner')
    runner.contain_session()
    nested=runner.owned_windows_job()
    host.publish(directory/'startup.json',dict(pid=os.getpid(),handle=nested['handle']))
    deadline=time.monotonic()+4
    while not (directory/'ready.json').exists():
        identity.require(time.monotonic()<deadline,'fixture actual-ready wait expired')
        time.sleep(.01)
    descendant()
    time.sleep(20)


def native_lifecycle_fixture_byte0(lock, *, available):
    import msvcrt
    before=identity.stamp(lock)
    fd=os.open(lock,os.O_RDWR|os.O_BINARY)
    try:
        observed=os.fstat(fd)
        fd_before=[observed.st_dev,observed.st_ino,observed.st_size,observed.st_mtime_ns,observed.st_ctime_ns,observed.st_mode]
        identity.require(fd_before[:4]==before[:4],
                         'fixture path/descriptor identity mismatch')
        try:msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
        except OSError:
            identity.require(not available,'fixture byte0 release missing')
        else:
            try:
                observed=os.fstat(fd)
                identity.require([observed.st_dev,observed.st_ino,observed.st_size,observed.st_mtime_ns,observed.st_ctime_ns,observed.st_mode]==fd_before,
                                 'fixture descriptor changed while byte0 held')
                identity.require(identity.stamp(lock)==before,'fixture path changed while byte0 held')
            finally:msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            identity.require(available,'fixture keeper failed to retain byte0')
        after=os.fstat(fd)
        identity.require([after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns,after.st_mode]==fd_before,
                         'fixture descriptor changed during byte0 observation')
        identity.require(identity.stamp(lock)==before,'fixture changed during byte0 observation')
    finally:os.close(fd)


def native_lifecycle_faults(directory):
    """Real selected caretaker failures, on temporary locks and fixed toy workers."""
    import ctypes
    identity.require(os.name=='nt' and not directory.exists(),'fresh native lifecycle fixture required')
    identity.require(Path(host.__file__).resolve()==_SELECTED_SCRIPTS/'scale_acceptance/native_scale_host.py',
                     'selected runtime import origin required')
    windows=host.module('browser-small-windows')
    helpers=host.module('test-native-file-allocation')
    directory.mkdir()
    started=time.monotonic()
    def remaining():
        value=90-(time.monotonic()-started)
        identity.require(value>0,'whole lifecycle observation deadline')
        identity.require(sum(p.stat().st_size for p in directory.rglob('*') if p.is_file())<=1024**2,
                         'fixture evidence allowance')
        return value
    def read(name):
        return native_lifecycle_read(name,remaining,lambda:native_lifecycle_producer_terminal(name.parent))
    # Same selected post-ACK flags; this component does not simulate a new ACK.
    job=host.windows_bootstrap.create_job(windows)
    dll=host.windows_bootstrap.kernel()
    info=windows.Extended();info.basic.flags=0x800
    windows.checked(dll.SetInformationJobObject(job,9,ctypes.byref(info),ctypes.sizeof(info)))
    windows.checked(dll.AssignProcessToJobObject(job,windows.kernel().GetCurrentProcess()))
    context=windows.query_job(job)
    identity.require(context['flags']==0x800 and context['pids']==[os.getpid()],'selected post-ACK fixture context')
    actor=windows.process_identity(os.getpid())
    host.publish(directory/'actor.json',dict(actor=actor,post_ack_context=context))
    results=[];births=[actor];owner=None;backup=None;case=directory
    complete=False
    try:
        for name in ('worker-failure','cancel-finish','controller-eof','retained-proof','pipe-after-failure'):
            remaining();case=directory/name;case.mkdir()
            host.publish(case/'plan.json',{})
            host.publish(case/'operation.json',dict(component_only=True))
            (case/'fixture.lock').touch(exist_ok=False)
            host.publish(case/'fixture-stat.json',dict(stat=identity.stamp(case/'fixture.lock')))
            saved=subprocess.Popen
            def launch(argv,*args,**kwargs):
                identity.require(argv==[sys.executable,'-B',str(_SELECTED_SCRIPTS/'native-scale-runner.py'),
                    '_lock_owner',str(case/'fixture.lock'),'--existing'],'fixed fixture keeper argv required')
                return saved(native_lifecycle_command('--native-lifecycle-owner',case),*args,**kwargs)
            with patch.object(host.subprocess,'Popen',launch):
                owner=host.WindowsLockOwner.__new__(host.WindowsLockOwner)
                owner.__init__(case/'fixture.lock',existing=True)
            owner_proof=copy.deepcopy(owner.proof);births.append(owner_proof['owner_identity'])
            host.publish(case/'keeper.json',owner_proof)
            native_lifecycle_fixture_byte0(case/'fixture.lock',available=False)
            ack=owner.request(dict(command='start',plan=str(case/'plan.json'),
                operation=str(case/'operation.json'),directory=str(case)))
            before=read(case/'before-resume.json')
            caretaker=read(case/'caretaker-identity.json')
            identity.require(caretaker['pid']==ack['pid']==before['caretaker'],'actual caretaker handoff')
            backup=windows.duplicate_job(caretaker['pid'],before['job_handle'])
            host.publish(case/'parent-captured.json',dict(actor=actor,backup_job_handle=int(backup),
                source_caretaker=caretaker,source_job_handle=before['job_handle'],
                driver_sha256=sha256(__file__),selected_harness=str(_SELECTED_SCRIPTS.parent)))
            initial=windows.query_job(backup)
            identity.require(initial['kill_on_close'] and initial['pids']==[before['worker']['pid']],
                             'exact live backup Job required')
            host.publish(case/'parent-captured-census.json',dict(census=initial))
            worker=read(case/'worker-identity.json')
            identity.require(worker==before['worker'],'same held worker birth')
            births += [caretaker,worker]
            child=native_lifecycle_child_handoff(case,read,windows,backup,worker,caretaker)
            births.append(child)
            if name not in ('worker-failure','pipe-after-failure'):owner.request(dict(command='pulse'))
            failed_pulse=None;closed_backup=None
            if name=='pipe-after-failure':
                read(case/'cleanup.json')
                # Cleanup publication precedes interpreter/process teardown.
                kernel=windows.kernel();ctypes.set_last_error(0)
                handle=kernel.OpenProcess(0x101000,False,caretaker['pid'])
                if handle:
                    try:
                        identity.require(windows._held_birth(kernel,handle,caretaker['pid'])==caretaker['created'],
                                         'same caretaker birth before exit wait')
                        state=kernel.WaitForSingleObject(handle,min(1000,max(1,int(remaining()*1000))))
                        identity.require(state==0 and windows._held_birth(kernel,handle,caretaker['pid'])==caretaker['created'],
                                         'bounded held caretaker exit required before failed pulse')
                        host.publish(case/'pre-pulse-exit.json',dict(identity=caretaker,wait_state=state,held_birth_stable=True))
                    finally:windows.checked(kernel.CloseHandle(handle),api='CloseHandle',pid=caretaker['pid'])
                else:
                    identity.require(ctypes.get_last_error()==87,'caretaker exit handle unavailable')
                helpers.exited_births((caretaker,worker,child))
                supervisor=host.Caretaker.__new__(host.Caretaker)
                supervisor.directory=case;supervisor.process=SimpleNamespace(pid=caretaker['pid'])
                supervisor.lock_owner=owner;supervisor.backup_job=backup;supervisor.backup_cgroup=None
                supervisor.created=time.monotonic();supervisor.freshness=host.Freshness()
                pulse_started=time.monotonic()
                try:host.bounded(supervisor.pulse)
                except OSError as error:
                    identity.require(getattr(error,'caretaker_failed',False),'actual failed pulse marker required')
                    failed_pulse=dict(error=str(error),payload=supervisor.phase_failed,
                        seconds=time.monotonic()-pulse_started,bound_seconds=2)
                    identity.require(failed_pulse['seconds']<2,'failed pulse exceeded existing hot bound')
                else:raise ValueError('failed actual caretaker pulse was accepted')
                native_lifecycle_fixture_byte0(case/'fixture.lock',available=False)
                identity.require(owner.process.poll() is None,'keeper must hold Original-equivalent fixture until close')
                closed_backup=windows.query_job(backup)
                identity.require(not closed_backup['pids'],'actual failed backup Job empty required')
                try:supervisor.finish()
                except ValueError:
                    identity.require(supervisor.cleanup_proven,'failed finish must prove cleanup')
                else:raise ValueError('failed phase incorrectly passed finish')
                backup=None
                owner.close()
            elif name in ('worker-failure','cancel-finish'):
                if name=='worker-failure':read(case/'cleanup.json')
                owner.request(dict(command='finish'),seconds=min(15,remaining()))
                owner.close()
            else:
                owner.process.stdin.close()
                if name=='retained-proof':
                    read(case/'retaining.json')
                    proof=read(case/'withheld-cleanup.json')
                    identity.require(proof['remaining']==[] and proof['cleanup_errors']==[] and
                        proof['monitor_threads_joined'] and proof['capture_writers_reaped'],
                        'positive fixture tree quiescence before retained-owner teardown')
                    helpers.exited_births((caretaker,worker,child))
                    identity.require(windows.query_job(backup)['pids']==[],'retained fixture Job not empty')
                    native_lifecycle_fixture_byte0(case/'fixture.lock',available=False)
                    identity.require(owner.process.poll() is None and windows._held_birth(windows.kernel(),
                        owner.process._handle)==owner_proof['owner_identity']['created'],'exact retained fixture keeper')
                    owner.process.terminate()  # Only this known fixture keeper, after positive tree closure.
                identity.require(owner.process.wait(timeout=min(15,remaining()))== (1 if name=='retained-proof' else 0),
                                 'fixture keeper EOF/expected administrative exit')
                owner.reader.join(timeout=2)
                identity.require(not owner.reader.is_alive() and owner.capture_eof,'fixture keeper EOF/join')
                owner.process.stdout.close()
            proof=read(case/('withheld-cleanup.json' if name=='retained-proof' else 'cleanup.json'))
            identity.require(proof['remaining']==[] and proof['cleanup_errors']==[] and
                proof['monitor_threads_joined'] and proof['capture_writers_reaped'],'current complete owned cleanup')
            waited=read(case/'worker-wait.json')
            identity.require(waited['pid']==worker['pid'] and
                (waited['exit_code']==7 if name in ('worker-failure','pipe-after-failure') else waited['exit_code']!=0),
                             'actual fixture worker exit/termination code')
            expected='containment startup failed' if name in ('worker-failure','pipe-after-failure') else 'controller death/pipe closed'
            identity.require(any(expected in value for value in proof['errors']),'expected real failure cause')
            census=windows.query_job(backup) if backup is not None else closed_backup
            identity.require(census['pids']==[],'fixture final backup Job nonempty')
            if backup is not None:windows.close(backup)
            backup=None
            identity.require(not [t for t in host.pending_calls() if t is not threading.current_thread()],'fixture pending query')
            owner.process._handle.Close();owner=None
            native_lifecycle_fixture_byte0(case/'fixture.lock',available=True)
            results.append(dict(scenario=name,passed=True,cleanup=proof,worker_wait=waited,failed_pulse=failed_pulse,
                fixture_keeper_administrative_teardown=name=='retained-proof',qualification=False))
        windows.close(job);job=None
        result=dict(passed=True,qualification=False,Original_touched=False,product_runs=0,
            actor=actor,births=births,selected_harness=str(_SELECTED_SCRIPTS.parent),
            driver_sha256=sha256(__file__),driver_stat=identity.stamp(Path(__file__)),post_ack_context=context,scenarios=results,
            metadata_usage=controller.tiny.budget_usage(),elapsed=time.monotonic()-started,fixture_bytes=sum(p.stat().st_size for p in directory.rglob('*') if p.is_file()))
        host.publish(directory/'result.json',result);complete=True
    except BaseException as error:
        closed=None
        if getattr(error,'native_owner_no_start_closed',None) is not None and backup is None:
            closed=error.native_owner_no_start_closed;owner=None
            births.append(dict(pid=closed['pid'],created=closed['created']))
        try:
            positive=native_lifecycle_close_failed(owner,backup,case,windows)
            if closed is not None:positive['constructor_closed_start']=closed
            closed=positive
            owner=None;backup=None
        except BaseException as cleanup_error:
            try:error.add_note('fixture failed cleanup: '+repr(cleanup_error))
            except BaseException:pass
        try:host.publish(directory/'failed.json',dict(error=repr(error),traceback=traceback.format_exc()[-8192:],
            passed=False,qualification=False,Original_touched=False,
            births=births,completed_scenarios=results,keeper_scope_closed=owner is None and backup is None,
            failed_cleanup=closed,pending=bool([t for t in host.pending_calls() if t is not threading.current_thread()])))
        except BaseException:pass
        raise
    finally:
        if not complete and (owner is not None or backup is not None or [t for t in host.pending_calls() if t is not threading.current_thread()]):
            while True:time.sleep(1)  # Exact unresolved fixture ownership stays observable for parent recovery.
        if job is not None:windows.close(job)


def native_lifecycle_audit(directory):
    result_file=directory/('result.json' if (directory/'result.json').exists() else 'failed.json')
    identity.require(sha256(result_file)==sys.argv[5],'exact completed fixture result required')
    result=read_json(result_file,1024**2)
    passed=result_file.name=='result.json'
    if passed:
        identity.require(result['passed'] and not result['qualification'] and not result['Original_touched'],
                         'complete component scope required')
    else:
        identity.require(result['keeper_scope_closed'] and not result['pending'] and
            result['failed_cleanup']['keeper_scope_closed'],'positive failed component closure required')
    windows=host.module('test-native-file-allocation')
    proof=windows.exited_births(tuple(result['births']))
    for lock in directory.glob('*/fixture.lock'):
        identity.require(identity.stamp(lock)==read_json(lock.parent/'fixture-stat.json')['stat'],
                         'same temporary fixture inode/stat required')
        native_lifecycle_fixture_byte0(lock,available=True)
    identity.require(not (directory/'after-exit.json').exists(),'fresh independent fixture audit')
    host.publish(directory/'after-exit.json',dict(passed=True,measurement_passed=passed,
        qualification=False,Original_touched=False,result_sha256=sha256(result_file),births=proof,
        all_temporary_byte0_available_closed=True,
        birth_scope='Recorded births; any unrecorded historical identifiers remain UNKNOWN on failed setup'))


def native_lock_owner_probe(directory, output):
    """Actual unchanged keeper in the selected post-ACK Job, on a temporary file.

    This never names the acceptance lock, requests a caretaker or launches Chopper.
    The second constructor rejection is injected; its reap/EOF/close are native.
    """
    import ctypes
    from ctypes import wintypes as W
    from scale_acceptance.native_preflight import observe_baseline
    from scale_acceptance._native_file import _directory_size
    if os.name != 'nt':
        raise ValueError('native Windows lifecycle probe required')
    started = time.monotonic()
    tiny = controller.tiny
    tiny.budget = tiny.ReadBudget(dict(qualification=dict(metadata_per_process=dict(
        read_bytes=128*1024**2, visits=2_000_000))), Path(__file__))
    windows = host.module('browser-small-windows')
    dll = windows.kernel()
    directory, output = directory.absolute(), output.absolute()
    if directory.exists() or output.exists() or output.is_relative_to(directory):
        raise ValueError('fresh separate fixture and evidence required')
    parent = directory.parent
    parent_stat = parent.stat()
    parent_size = _directory_size(parent, parent_stat)
    directory.mkdir()
    fixture = directory/'fixture.lock'
    fd = os.open(fixture, os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_BINARY, 0o600)
    os.close(fd)
    actor = windows.process_identity(os.getpid())
    owner = None
    complete = False
    try:
        owner = host.WindowsLockOwner.__new__(host.WindowsLockOwner)
        owner.__init__(fixture, existing=True)
        normal = copy.deepcopy(owner.proof)
        member = W.BOOL()
        ctypes.set_last_error(0)
        api = dll.IsProcessInJob(owner.process._handle, None, ctypes.byref(member))
        error = ctypes.get_last_error()
        identity.require(api and not member.value, 'actual keeper must pass unchanged any-Job guard')
        owner.check()
        contender = os.open(fixture, os.O_RDWR|os.O_BINARY)
        try:
            import msvcrt
            try:
                msvcrt.locking(contender, msvcrt.LK_NBLCK, 1)
            except OSError:
                denied = True
            else:
                msvcrt.locking(contender, msvcrt.LK_UNLCK, 1)
                denied = False
            identity.require(denied, 'actual keeper did not hold fixture byte zero')
        finally:
            os.close(contender)
        owner.close()
        identity.require(owner.capture_eof and owner.process.returncode == 0,
                         'normal keeper capture/reap required')
        owner.process._handle.Close()
        owner = None
        rejection = ValueError('injected no-worker constructor rejection')
        rejected = host.WindowsLockOwner.__new__(host.WindowsLockOwner)
        owner = rejected
        with patch.object(host.WindowsLockOwner, 'receive', side_effect=rejection):
            try:
                rejected.__init__(fixture, existing=True)
            except ValueError as actual:
                identity.require(actual is rejection, 'primary constructor failure replaced')
            else:
                raise ValueError('constructor rejection was bypassed')
        closed = getattr(rejection, 'native_owner_no_start_closed', None)
        identity.require(closed is not None and closed['caretaker_requests'] == 0,
                         'positive native failed-constructor closure required')
        owner = None
        fd = os.open(fixture, os.O_RDWR|os.O_BINARY)
        try:
            os.lseek(fd,0,os.SEEK_SET)
            msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
        finally:
            os.close(fd)
        class Budget:
            def check(self):
                identity.require(time.monotonic()-started < 60, 'lifecycle component deadline')
        baseline = observe_baseline([directory], Budget())
        inventory = [*baseline['roots'], *baseline['entries']]
        parent_after = parent.stat()
        identity.require((parent_after.st_dev,parent_after.st_ino) == (parent_stat.st_dev,parent_stat.st_ino),
                         'fixture parent identity changed')
        delta = max(0,_directory_size(parent,parent_after)-parent_size)
        directory_eof = sum(row['stat']['size'] for row in inventory if stat.S_ISDIR(row['stat']['mode']))
        growth = baseline['sum_bytes']+directory_eof+delta
        identity.require(growth <= 65536, 'temporary fixture growth ceiling')
        result = dict(schema='native-lock-owner-lifecycle-v1', passed=True, qualification=False,
            measurement_complete=True, candidate_supported=True, cleanup_passed=True,
            original_touched=False, product_runs=0, actor=actor, normal_owner=normal,
            keeper_any_job=dict(api_return=int(api),assigned=bool(member.value),error=error),
            constructor_rejection=dict(injected=True,primary_preserved=True,closed=closed),
            current_fixture_inventory=inventory, parent_positive_logicalEOF_delta=delta,
            source_growth_envelope=growth, fixture_byte0_available_unlocked_closed=True,
            job_scope='exact parent-held startup Job; inherited ancestor Jobs remain unknown',
            seconds=time.monotonic()-started,
            metadata_usage=tiny.budget_usage())
        raw = (json.dumps(result,indent=2)+'\n').encode()
        identity.require(len(raw) <= 65536, 'bounded lifecycle evidence')
        with output.open('xb') as stream:
            stream.write(raw)
        complete = True
    except BaseException as error:
        closed = getattr(error, 'native_owner_no_start_closed', None)
        if closed is not None and not host.pending_calls():
            owner = None
            with output.open('x') as stream:
                json.dump(dict(schema='native-lock-owner-lifecycle-v1', passed=False,qualification=False,
                    measurement_complete=True,candidate_supported=False,cleanup_passed=True,
                    original_touched=False,error=repr(error),actor=actor,closed=closed,
                    job_scope='parent-held startup Job',metadata_usage=tiny.budget_usage()),stream)
            complete = True
            return
        raise
    finally:
        if not complete:
            # An unresolved fixture keeper is positively owned but not a clean
            # lifecycle result. Preserve its caller/handles for exact recovery.
            try:
                with output.open('x') as stream:
                    json.dump(dict(passed=False,qualification=False,original_touched=False,
                        actor=actor,keeper_pid=owner.process.pid if owner and hasattr(owner,'process') else None,
                        pending=bool(host.pending_calls())),stream)
            except BaseException:
                pass
            if owner is not None:
                while True:time.sleep(1)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    Controls.root = args.directory.absolute()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Controls)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    control.create(Controls.root/'result.json', dict(tests=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors), fake_only=True,
                   containment_platform_probes='unrun; parent-owned'))
    return int(not result.wasSuccessful())


if __name__ == '__main__':
    if len(sys.argv)==6 and sys.argv[1] in ('--native-job-exit-compare','--native-job-transition-compare','--native-job-exit-audit'):
        directory=Path(sys.argv[3])
        controller.tiny.budget=controller.tiny.ReadBudget(dict(qualification=dict(metadata_per_process=dict(
            read_bytes=256*1024**2,visits=200000))),Path(__file__))
        driver_before=identity.stamp(Path(__file__))
        identity.require(sha256(__file__)==sys.argv[4] and identity.stamp(Path(__file__))==driver_before,
                         'exact staged maintained driver bytes required')
        if sys.argv[1]=='--native-job-exit-audit':
            native_job_exit_audit(directory,sys.argv[5])
        else:
            helper=Path(__file__).with_name('browser-small-windows.py')
            before=identity.stamp(helper)
            identity.require(sha256(helper)==sys.argv[5] and identity.stamp(helper)==before,'exact candidate process helper')
            spec=importlib.util.spec_from_file_location('candidate_windows',helper)
            candidate=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(candidate)
            native_job_exit_probe(directory,candidate,transitional=sys.argv[1]=='--native-job-transition-compare')
            identity.require(identity.stamp(helper)==before and sha256(helper)==sys.argv[5],'candidate process helper drift')
    elif len(sys.argv) in (5,6) and sys.argv[1] in _LIFECYCLE_MODES:
        mode,directory=sys.argv[1],Path(sys.argv[3])
        controller.tiny.budget=controller.tiny.ReadBudget(dict(qualification=dict(metadata_per_process=dict(
            read_bytes=32*1024**2,visits=2_000_000))),Path(__file__))
        driver_before=identity.stamp(Path(__file__))
        identity.require(sha256(__file__)==sys.argv[4] and identity.stamp(Path(__file__))==driver_before,
                         'exact staged maintained driver bytes required')
        identity.require(len(sys.argv)==(6 if mode=='--native-lifecycle-audit' else 5),'exact component arguments')
        if mode=='--native-lifecycle-faults':
            try:host.bounded(lambda:native_lifecycle_faults(directory),seconds=90)
            except BaseException:
                if host.pending_calls():host.retain_host_lock('native lifecycle fixture pending callback')
                raise
            identity.require(not host.pending_calls(),'component callback did not join')
        elif mode=='--native-lifecycle-audit':native_lifecycle_audit(directory)
        else:
            try:native_lifecycle_child(mode,directory)
            finally:
                control.create(directory/(mode[2:]+'-usage.json'),controller.tiny.budget_usage())
    elif len(sys.argv) == 4 and sys.argv[1] == '--native-storage-control-audit':
        controller.tiny.budget=controller.tiny.ReadBudget(dict(qualification=dict(metadata_per_process=dict(
            read_bytes=256*1024**2,visits=200000))),Path(__file__))
        native_storage_control_audit(Path(sys.argv[2]),sys.argv[3])
    elif len(sys.argv) == 3 and sys.argv[1] in ('--native-storage-rename-probe','--native-storage-control-probe'):
        native_storage_rename_probe(Path(sys.argv[2]),control_io=sys.argv[1]=='--native-storage-control-probe')
    elif len(sys.argv) == 3 and sys.argv[1] == '--native-job-exit-probe':
        native_job_exit_probe(Path(sys.argv[2]))
    else:
        raise SystemExit(main())
