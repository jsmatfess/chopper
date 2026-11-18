"""Actual parent admission/release paths with no native processes or locks."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import config
import control
from scale_acceptance import hosted_qualification


class Parent(unittest.TestCase):
    def run_parent(self, fault):
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            root = Path(directory)
            class AttemptPath(type(root)):
                def mkdir(self, *args, **kwargs):
                    value = super().mkdir(*args, **kwargs)
                    if self == out and fault == 'existing-profile':
                        (self/'profile').mkdir(exist_ok=True)
                    return value
            out = AttemptPath(root/'attempt1')
            selected = root/'selected.json'
            selected.write_text('{}')
            dependency = root/'dependency.py'
            dependency.write_text('original')
            complete_metadata_check = config.check
            order, closed, owner = [], [], [None]
            plan = dict(case='observe-input', channel='msedge',
                        input=dict(path=str(root/'tiny.csv')),
                        profile=dict(path=str(out/'profile'), reuse=fault=='retained-profile'))
            plan.update(inputs=[dict(path=str(dependency),stat=config.stamp(dependency))],
                        input_directories={})
            custody = dict(reusedInput={})
            accounting = dict(absolute_stop_utc='2100-01-01T00:00:00+00:00')
            def mark(name, result=None):
                def action(*args, **kwargs):
                    order.append(name)
                    if fault=='input-drift-after-out' and name=='complete-metadata':
                        complete_metadata_check(plan)
                    if fault=='pending-disk' and name=='environment':
                        raise OSError('environment')
                    if fault == name:
                        raise OSError(name)
                    if fault == 'locked-'+name and 'original-reservation' in order:
                        raise OSError(name+' under lock')
                    if fault=='setup-aged-custody' and name=='authorize' and 'watch-allocation' in order:
                        raise OSError('custody expired during cold setup')
                    return result
                return action
            class Thread:
                def __init__(self, *args, **kwargs):
                    self.alive = False
                    if 'target' in kwargs:
                        mark('watch-allocation')()
                def start(self): self.alive = True
                def cancel(self): pass
                def join(self, timeout=None): self.alive = False
                def is_alive(self): return self.alive
            class Reservation:
                def __init__(self, windows):
                    order.append('original-reservation')
                    self.fd = 1234
                    if fault == 'input-drift-after-out':
                        assert out.is_dir()
                        dependency.write_text('changed after attempt creation')
                receipt = mark('reservation-receipt', {})
                check = mark('original-identity')
            class Environment(dict):
                copy = mark('environment', {})
            windows = SimpleNamespace(query_job=lambda job: dict(pids=[os.getpid()], kill_on_close=True),
                                      close=Mock(), terminate=Mock())
            suite = SimpleNamespace(authorize=mark('authorize'),authorize_history=mark('authorize'),check_inputs_storage=mark('live-custody'),
                baseline_completed=mark('baseline', {}), input_inventory=mark('input-inventory', {}),
                preflight=mark('live-custody'), verify_reused_input=mark('reused-input'),
                verify_profile=Mock(side_effect=mark('retained-profile')),
                dir_identity=lambda path: dict(dev=1, ino=2), PROFILE=str(out/'profile'),
                REUSED_INPUT=str(root/'tiny.csv'))
            modules = {'suite':suite, 'browser-small-windows':windows,
                       'validation-runner':SimpleNamespace(contain_session=mark('contain-session'), _SESSION_JOB=1),
                       'reservation':SimpleNamespace(Reservation=Reservation)}
            stack.enter_context(patch.multiple(control, ROOT=root, OUT=out, PLAN=plan,
                CONFIG_PATH=str(selected), CONFIG_SHA=hashlib.sha256(selected.read_bytes()).hexdigest(),
                PREPARATION=dict(path='passed-native-preflight', sha256='a'*64),
                os=SimpleNamespace(name='nt', getpid=os.getpid, environ=Environment(), close=closed.append),
                sys=SimpleNamespace(flags=SimpleNamespace(isolated=True, dont_write_bytecode=True, optimize=0),
                                    path=[], executable='never-launched-python', getwindowsversion=lambda:()),
                threading=SimpleNamespace(Timer=Thread, Thread=Thread, Event=threading.Event)))
            disk = SimpleNamespace(start=Mock(), stop=Mock(), pending=fault=='pending-disk',
                after=lambda marker: dict(value=dict(owned=0)),
                read=lambda: dict(value=dict(owned=0)))
            stack.enter_context(patch.object(control, 'disk_observer', return_value=disk))
            stack.enter_context(patch.object(control, 'load', side_effect=lambda name:modules[name]))
            stack.enter_context(patch.object(control, 'document', side_effect=lambda name:
                accounting if name=='accounting.json' else custody))
            stack.enter_context(patch.object(control, 'owned_roots', return_value=[root]))
            stack.enter_context(patch.object(control, 'owned_size', return_value=0))
            stack.enter_context(patch.object(control, 'live_custody', side_effect=mark('late-custody', ({},{},0))))
            stack.enter_context(patch.object(control, 'verify_custody', side_effect=mark('runtime-bindings', custody)))
            stack.enter_context(patch.object(control, 'native_volume', return_value=dict(filesystem='NTFS')))
            stack.enter_context(patch.object(control, 'guard_check'))
            stack.enter_context(patch.object(control, 'disk_guard'))
            stack.enter_context(patch.object(config, 'check', side_effect=mark('complete-metadata')))
            hashes = stack.enter_context(patch.object(config, 'validate', side_effect=mark('unexpected-cold-hash')))
            stack.enter_context(patch.object(hosted_qualification, 'preflight', side_effect=mark('matching-preflight')))
            stack.enter_context(patch.object(control.subprocess, 'CREATE_NO_WINDOW', 0, create=True))
            popen = stack.enter_context(patch.object(control.subprocess, 'Popen', side_effect=OSError('unknown-spawn')))
            error = None
            try:
                result = control.parent(owner)
            except BaseException as caught:
                error, result = caught, None
            receipt = json.loads((out/'receipt.json').read_text()) if (out/'receipt.json').exists() else None
            return SimpleNamespace(order=order, closed=closed, owner=owner[0], result=result,
                error=error, receipt=receipt, profile=(out/'profile').exists(),
                popen_calls=popen.call_count, full_hash_calls=hashes.call_count,
                profile_checks=suite.verify_profile.call_count)

    def test_pending_disk_thread_fences_original_release_without_worker(self):
        value = self.run_parent('pending-disk')
        self.assertIsNotNone(value.error)
        self.assertEqual(value.closed, [])
        self.assertEqual(value.popen_calls, 0)
        self.assertFalse(value.receipt['originalReservationClosedAfterQuiescence'])
        self.assertIn('disk observation still owns a pending call', value.receipt['releaseBlocked'])

    def test_no_child_setup_failure_releases_without_profile_birth(self):
        value = self.run_parent('environment')
        self.assertIsNone(value.error)
        self.assertEqual(value.result, 1)
        self.assertEqual(value.closed, [1234])
        self.assertFalse(value.profile)
        self.assertEqual(value.profile_checks, 0)
        self.assertEqual(value.popen_calls, 0)
        self.assertTrue(value.receipt['noWorkerLaunched'])
        self.assertTrue(value.receipt['originalReservationClosedAfterQuiescence'])
        self.assertFalse(value.receipt['tinyCaseQualified'])
        self.assertEqual(value.receipt['error'], 'environment')
        self.assertNotIn('browserProfile', value.receipt)
        self.assertEqual(value.full_hash_calls, 0)
        for phase in ('matching-preflight','complete-metadata','baseline','input-inventory','live-custody','runtime-bindings','contain-session','watch-allocation'):
            self.assertLess(value.order.index(phase), value.order.index('original-reservation'))

    def test_expired_custody_and_invalid_preflight_never_acquire_original(self):
        for fault in ('matching-preflight','complete-metadata','input-inventory','live-custody','runtime-bindings'):
            with self.subTest(fault=fault):
                value = self.run_parent(fault)
                self.assertIsInstance(value.error, OSError)
                self.assertIsNone(value.owner)
                self.assertNotIn('original-reservation', value.order)
                self.assertEqual(value.popen_calls, 0)
                self.assertEqual(value.closed, [])

    def test_uncertain_spawn_does_not_receive_no_child_release(self):
        value = self.run_parent('unknown-spawn')
        self.assertIsInstance(value.error, AssertionError)
        self.assertEqual(value.popen_calls, 1)
        self.assertEqual(value.closed, [])
        self.assertFalse(value.receipt['originalReservationClosedAfterQuiescence'])
        self.assertIn('launch attempted', value.receipt['releaseBlocked'])

    def test_fresh_or_retained_profile_drift_precedes_original(self):
        for fault in ('existing-profile','retained-profile'):
            with self.subTest(fault=fault):
                value = self.run_parent(fault)
                self.assertIsInstance(value.error, (OSError, AssertionError))
                self.assertIsNone(value.owner)
                self.assertNotIn('original-reservation', value.order)
                self.assertEqual(value.popen_calls, 0)

    def test_cold_containment_and_allocation_failure_never_acquire_original(self):
        for fault in ('contain-session','watch-allocation','setup-aged-custody'):
            with self.subTest(fault=fault):
                value = self.run_parent(fault)
                self.assertIsInstance(value.error, OSError)
                self.assertIsNone(value.owner)
                self.assertEqual(value.closed, [])
                self.assertEqual(value.popen_calls, 0)

    def test_locked_metadata_or_custody_denial_cannot_spawn_or_leak_owner(self):
        for phase in ('complete-metadata','input-inventory','baseline','live-custody','late-custody'):
            with self.subTest(phase=phase):
                value = self.run_parent('locked-'+phase)
                self.assertIsNone(value.error)
                self.assertEqual(value.result, 1)
                self.assertEqual(value.popen_calls, 0)
                self.assertEqual(value.closed, [1234])
                self.assertTrue(value.receipt['noWorkerLaunched'])
                self.assertTrue(value.receipt['originalReservationClosedAfterQuiescence'])
                self.assertFalse(value.receipt['tinyCaseQualified'])
                self.assertEqual(value.receipt['error'], phase+' under lock')

    def test_input_drift_after_attempt_creation_denies_before_spawn_and_releases(self):
        value = self.run_parent('input-drift-after-out')
        self.assertIsNone(value.error)
        self.assertEqual(value.result, 1)
        self.assertEqual(value.popen_calls, 0)
        self.assertEqual(value.closed, [1234])
        self.assertTrue(value.receipt['noWorkerLaunched'])
        self.assertTrue(value.receipt['originalReservationClosedAfterQuiescence'])
        self.assertIn('input metadata changed', value.receipt['error'])

    def test_no_worker_gate_requires_complete_quiescence(self):
        outer = dict(kill_on_close=True, pids=[os.getpid()])
        control.no_worker_release_gate(False, None, None, None, outer, False)
        for values in ((True,None,None,None,outer,False),
                       (False,object(),None,None,outer,False),
                       (False,None,object(),None,outer,False),
                       (False,None,None,1,outer,False),
                       (False,None,None,None,dict(kill_on_close=True,pids=[os.getpid(),999]),False),
                       (False,None,None,None,outer,True)):
            with self.subTest(values=values), self.assertRaises(AssertionError):
                control.no_worker_release_gate(*values)


if __name__ == '__main__': unittest.main()
