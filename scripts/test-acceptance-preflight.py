"""External preparation controls; no product or browser is launched."""
import hashlib
import importlib.util
import json
import os
import ntpath
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).with_name('acceptance-preflight.py')
spec = importlib.util.spec_from_file_location('preflight', SCRIPT)
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class Controls(unittest.TestCase):
    def test_owned_preparation_role_is_exact_native_candidate_namespace(self):
        for profile,schema,root in (
                ('native-ui','chopper-native-ui-smoke-v1',r'C:\native105-smoke-role'),
                ('actual-picker','chopper-hosted-picker-qualification-v1',r'C:\hosted105-smoke-role')):
            value={'profile':profile,'plan':root+r'\candidate.json'}
            plan={'schema':schema,'root':root}
            self.assertEqual(str(preflight.owned_preparation_root(value,plan)),root)
            self.assertIsNone(preflight.owned_preparation_root(dict(value,profile='native'),plan))
            self.assertIsNone(preflight.owned_preparation_root(value,dict(plan,schema='wrong')))
            self.assertIsNone(preflight.owned_preparation_root(dict(value,plan=root+r'\candidate-old.json'),plan))
            for other in (root+r'\nested',r'\\server\share\hosted105-smoke-role',r'C:\unowned-role'):
                self.assertIsNone(preflight.owned_preparation_root(dict(value,plan=other+r'\candidate.json'),dict(plan,root=other)))

    def test_supervisor_owns_case_preflight_and_keeps_artifact_closure(self):
        request,value=self.fixture('native-ui')
        root=self.root/'native105-smoke-role';root.mkdir()
        source=self.root/'immutable';source.mkdir();input_file=source/'code';input_file.write_bytes(b'fixed')
        plan=dict(schema='chopper-native-ui-smoke-v1',root=str(root),controller_root=str(source),
                  input_directories={str(source):[str(input_file)]},runtime_roots=[],inputs=[{'path':str(input_file)}],owned_roots=[str(root)],
                  preparation_root_observation={'value':{'volume':{'root':root.anchor},'roots':101}})
        candidate=root/'candidate.json';candidate.write_text(json.dumps(plan));value.update(plan=str(candidate),plan_sha256=hashlib.sha256(candidate.read_bytes()).hexdigest())
        request.write_text(json.dumps(value));directory=root/'preflight';budget=preflight.Budget(value['limits'],directory)
        runner=Mock()
        def run(plan_path,unused,*,guard):
            emitted=json.loads(plan_path.read_text());step=emitted['steps'][0]
            self.assertEqual(step['inputs'],[str(request.resolve()),str(candidate),str(SCRIPT.resolve())])
            self.assertEqual(step['artifacts'],[str(directory/'worker-result.json')])
            guard();(directory/'worker-result.json').write_text(json.dumps(dict(status='passed',usage={})))
            return 0
        runner.run.side_effect=run
        # Only the Windows C: lexical role maps to this real portable fixture.
        with patch.object(preflight,'owned_preparation_root',return_value=root),patch.object(preflight,'load',return_value=runner):
            self.assertEqual(preflight.supervise(request,directory,value,budget,preflight.result_base(value,request)),0)
            with self.assertRaisesRegex(ValueError,'fresh preparation'):
                preflight.supervise(request,directory,value,budget,preflight.result_base(value,request))
        runner.run.assert_called_once()
        self.assertTrue((directory/'result.json').is_file())

    def test_typed_roots_preserve_all_roles_and_ignore_prepared_observations(self):
        root=self.root/'case';root.mkdir();(root/'candidate.json').write_bytes(b'{}');controller=self.root/'controller';controller.mkdir()
        runtime=self.root/'runtime';runtime.mkdir();inputs=self.root/'inputs';inputs.mkdir()
        retained=self.root/'retained';retained.mkdir()
        observation={'value':{'volume':{'root':root.anchor},'capacity':{'root':root.anchor},'roots':101}}
        base=dict(root=str(root),controller_root=str(controller),input_directories={str(inputs):[]},
                  runtime_roots=[str(runtime)],inputs=[],preparation_root_observation=observation,
                  diagnostic_custody={'nested':{'root':root.anchor}})
        native=dict(base,schema='chopper-native-ui-smoke-v1',owned_roots=[str(root),str(retained)])
        expected={str(root),str(controller),str(inputs),str(runtime),str(retained)}
        self.assertEqual(set(preflight.declared_source_roots(native,'native-ui')),expected)
        self.assertIn(root.anchor,preflight.declared_source_roots(native)) # Other profiles retain the generic precaution.
        custody=self.root/'custody.json';custody.write_text(json.dumps({'ownedRoots':[str(retained)]}))
        picker=dict(base,schema='chopper-hosted-picker-qualification-v1',documents={'custody.json':str(custody)},
                    inputs=[{'path':str(custody),'sha256':hashlib.sha256(custody.read_bytes()).hexdigest()}])
        self.assertEqual(set(preflight.declared_source_roots(picker,'actual-picker')),expected)
        for profile,plan in [('native-ui',native),('actual-picker',picker)]:
            with patch.object(preflight,'owned_preparation_root',return_value=root):
                preflight.check_preparation_destination(root/'preflight',plan,{'profile':profile,'plan':str(root/'candidate.json')})
                for change in (dict(input_directories={root.anchor:[]}),dict(runtime_roots=[root.anchor])):
                    with self.assertRaises(preflight.UnsafeDestination):
                        preflight.check_preparation_destination(root/'preflight',dict(plan,**change),{'profile':profile,'plan':str(root/'candidate.json')})
        custody.write_text('{"ownedRoots":[]}')
        with self.assertRaisesRegex(AssertionError,'expected hash drift'):
            preflight.declared_source_roots(picker,'actual-picker')

    def test_owned_candidate_pin_denies_before_collector_or_mkdir(self):
        for profile in ('native-ui','actual-picker'):
            request,value=self.fixture(profile);value['plan_sha256']='a'*64
            destination=self.root/('early-'+profile);budget=preflight.Budget(value['limits'],destination)
            with patch.object(preflight,'check_preparation_destination') as collector:
                with self.assertRaisesRegex(ValueError,'selected plan drift before output admission'):
                    preflight.supervise(request,destination,value,budget,preflight.result_base(value,request))
            collector.assert_not_called();self.assertFalse(destination.exists())

    def test_owned_preflight_still_denies_immutable_and_other_root_collisions(self):
        root=self.root/'native105-smoke-role';root.mkdir();directory=root/'preflight'
        source=self.root/'immutable';source.mkdir();candidate=root/'candidate.json';candidate.write_bytes(b'{}')
        value={'profile':'native-ui','plan':str(candidate)}
        base=dict(root=str(root),controller_root=str(source),input_directories={},inputs=[],owned_roots=[str(root)])
        with patch.object(preflight,'owned_preparation_root',return_value=root):
            preflight.check_preparation_destination(directory,base,value)
            for change in (dict(controller_root=str(root)),dict(input_directories={str(root):[]}),
                           dict(inputs=[{'path':str(directory/'future-input')}]),
                           dict(input_directories={str(directory):[]}),dict(history_roots=[str(root.parent)])):
                with self.assertRaises(preflight.UnsafeDestination):
                    preflight.check_preparation_destination(directory,dict(base,**change),value)
            for other in (root/'other-output',root/'preflight'/'nested'):
                with self.assertRaises(preflight.UnsafeDestination):
                    preflight.check_preparation_destination(other,base,value)
            (root/'attempt1').mkdir()
            with self.assertRaisesRegex(preflight.UnsafeDestination,'attempted case'):
                preflight.check_preparation_destination(directory,base,value)
        with patch.object(preflight,'owned_preparation_root',return_value=None):
            with self.assertRaises(preflight.UnsafeDestination):
                preflight.check_preparation_destination(directory,base,value)
        self.assertFalse(directory.exists())

    def test_owned_preflight_alias_and_hardlinked_candidate_deny_before_output(self):
        root=self.root/'native105-smoke-role';root.mkdir();candidate=root/'candidate.json';candidate.write_bytes(b'{}')
        directory=root/'preflight';source=self.root/'source';source.mkdir()
        plan=dict(root=str(root),controller_root=str(source),input_directories={},inputs=[])
        value=dict(profile='native-ui',plan=str(candidate))
        with patch.object(preflight,'owned_preparation_root',return_value=root):
            os.link(candidate,root/'candidate-copy')
            with self.assertRaisesRegex(preflight.UnsafeDestination,'ordinary owned candidate'):
                preflight.check_preparation_destination(directory,plan,value)
        alias=self.root/'case-alias'
        try:alias.symlink_to(root,target_is_directory=True)
        except OSError:pass # Hosts without directory-link privileges still exercise the hardlink denial.
        else:
            with patch.object(preflight,'owned_preparation_root',return_value=alias):
                with self.assertRaisesRegex(preflight.UnsafeDestination,'plain existing'):
                    preflight.check_preparation_destination(alias/'preflight',plan,value)
        self.assertFalse(directory.exists())

    def test_supervisor_declares_exact_files_without_cross_volume_relpath(self):
        with self.assertRaises(ValueError):
            ntpath.relpath(r'C:\native105-smoke-processing-cancel-r1\candidate.json',
                           r'\\wsl.localhost\Ubuntu\home\example\source')
        request,value=self.fixture()
        directory=self.root/'external-preflight'
        budget=preflight.Budget(value['limits'],directory)
        runner=Mock()
        def run(plan_path,unused,*,guard):
            plan=json.loads(plan_path.read_text());step=plan['steps'][0]
            self.assertEqual(step['inputs'],[str(request.resolve()),value['plan'],str(SCRIPT.resolve())])
            self.assertTrue(all(Path(name).is_absolute() for name in step['inputs']+step['artifacts']))
            self.assertEqual(step['artifacts'],[str(directory/'worker-result.json')])
            (directory/'worker-result.json').write_text(json.dumps(dict(status='passed',usage={})))
            return 0
        runner.run.side_effect=run
        with patch.object(preflight,'load',return_value=runner), \
             patch.object(preflight.os.path,'relpath',side_effect=AssertionError('cross-volume conversion forbidden')):
            self.assertEqual(preflight.supervise(request,directory,value,budget,preflight.result_base(value,request)),0)
        runner.run.assert_called_once()

    def test_browser_scale_external_inventory_shortfall_precedes_hashing(self):
        _,value=self.fixture('browser-scale');value['host_os']='Windows'
        blob=self.root/'source.bin';blob.write_bytes(b'x')
        runtime=self.root/'runtime.bin';runtime.write_bytes(b'x'*128)
        group=dict(root=str(self.root),sha256={'source.bin':'a'*64})
        plan=dict(python={'path':sys.executable},external_runtime={'inputs':[{'path':str(runtime)}]},
            **{key:group for key in ('product','harness','assets','evidence')})
        path=Path(value['plan']);path.write_text(json.dumps(plan))
        value['plan_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        limits=dict(value['limits'],read_bytes=64)
        budget=preflight.Budget(limits,self.root/'evidence')
        with patch.object(preflight.platform,'system',return_value='Windows'), \
             patch('scale_acceptance.browser_scale_identity.validate_packet') as validate, \
             patch('scale_acceptance.browser_scale_identity.ScaleIdentity') as identity:
            with self.assertRaisesRegex(ValueError,'declared full inventory requires at least'):
                preflight.inspect(value,budget)
            validate.assert_called_once_with(plan,preparation=True)
            identity.assert_not_called()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def fixture(self, profile='small'):
        plan = self.root / 'selected.json'
        plan.write_text('{}')
        value = dict(schema=preflight.SCHEMA, profile=profile, host_os=platform.system(),
            plan=str(plan), plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
            limits=dict(seconds=10, read_bytes=64*1024**2, visits=100000,
                        capture_bytes=65536, storage_bytes=1024**2))
        request = self.root / 'request.json'
        request.write_text(json.dumps(value))
        return request, value

    def run_cli(self, request, script=SCRIPT):
        evidence = self.root / 'evidence'
        completed = subprocess.run([sys.executable, '-B', str(script), 'preflight', str(request), str(evidence)],
                                   capture_output=True, text=True, timeout=20)
        self.assertTrue((evidence / 'result.json').exists(), completed.stdout + completed.stderr)
        result = json.loads((evidence / 'result.json').read_text())
        self.assertFalse(result['workload_started'])
        self.assertFalse(result['acceptance_window_started'])
        self.assertFalse(result['scale_slot_consumed'])
        self.assertFalse((self.root / 'product-output').exists())
        self.assertFalse(list(self.root.rglob('*-consumed.json')))
        self.assertFalse(list(self.root.rglob('*-started.json')))
        return completed, result

    def test_invalid_plan_retains_failed_receipt_and_never_dispatches(self):
        request, _ = self.fixture()
        completed, result = self.run_cli(request)
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('schema', result['error'])
        self.assertEqual(result['host']['os'], platform.system())
        self.assertGreater(result['usage']['charged_read_bytes'], 0)

    def test_stale_selected_plan_denied_before_adapter(self):
        request, value = self.fixture()
        Path(value['plan']).write_text('{"changed": true}')
        completed, result = self.run_cli(request)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('selected plan drift', result['error'])

    def test_wrong_actual_host_denied(self):
        request, value = self.fixture()
        value['host_os'] = 'Windows' if platform.system() == 'Linux' else 'Linux'
        request.write_text(json.dumps(value))
        _, result = self.run_cli(request)
        self.assertIn('actual host', result['error'])

    def test_picker_preparation_dispatch_checks_inventory_before_inspector(self):
        from hosted_picker import config
        request, value = self.fixture('actual-picker')
        plan = dict(inputs=[dict(path=str(request))])
        selected = Path(value['plan'])
        selected.write_text(json.dumps(plan))
        value['plan_sha256'] = hashlib.sha256(selected.read_bytes()).hexdigest()
        budget = preflight.Budget(value['limits'], self.root)
        order = []
        with patch.object(preflight, 'minimum_inventory', side_effect=lambda paths, b: order.append(('inventory', paths))), \
             patch.object(config, 'inspect', side_effect=lambda p, b, **kw: order.append(('inspect', p)) or dict(runtime_pending=['actual journey'])):
            result = preflight.inspect(value, budget)
        self.assertEqual(order, [('inventory', [str(request)]), ('inspect', plan)])
        self.assertEqual(result['runtime_pending'], ['actual journey'])

    @unittest.skipUnless(os.name != 'nt', 'negative actual-host control')
    def test_picker_preparation_on_linux_never_dispatches_native_work(self):
        request, value = self.fixture('actual-picker')
        Path(value['plan']).write_text('{"inputs": []}')
        value['plan_sha256'] = hashlib.sha256(Path(value['plan']).read_bytes()).hexdigest()
        request.write_text(json.dumps(value))
        completed, result = self.run_cli(request)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('actual native Windows preparation required', result['error'])

    def test_picker_checker_identity_includes_nested_helpers(self):
        helpers = set(SCRIPT.parent.joinpath('hosted_picker').rglob('*.py'))
        self.assertTrue(helpers)
        self.assertLessEqual(helpers, set(preflight.checker_sources()))

    def test_native_ui_dispatch_checks_inventory_before_selected_inspector(self):
        from native_smoke import config
        request,value=self.fixture('native-ui')
        plan=dict(inputs=[dict(path=str(request))])
        selected=Path(value['plan']);selected.write_text(json.dumps(plan))
        value['plan_sha256']=hashlib.sha256(selected.read_bytes()).hexdigest()
        request.write_text(json.dumps(value));self.assertEqual(preflight.request(request)['profile'],'native-ui')
        budget=preflight.Budget(value['limits'],self.root);order=[]
        with patch.object(preflight,'minimum_inventory',side_effect=lambda paths,b:order.append(('inventory',paths))),patch.object(config,'inspect',side_effect=lambda p,b,**kw:order.append(('inspect',p)) or {'runtime_pending':['actual Native UI']}):
            self.assertEqual(preflight.inspect(value,budget),{'runtime_pending':['actual Native UI']})
        self.assertEqual(order,[('inventory',[str(request)]),('inspect',plan)])

    def test_native_ui_checker_closure_includes_all_adapter_code(self):
        sources=set(preflight.checker_sources())
        self.assertLessEqual(set(SCRIPT.parent.joinpath('native_smoke').glob('*.py')),sources)
        self.assertIn(SCRIPT.parent/'native_smoke/browser.cjs',sources)

    def test_native_inventory_adapter_covers_tiny_windows_but_not_denied_large(self):
        from scale_acceptance import native_preflight
        request, value = self.fixture('native')
        for selected in (dict(os='Linux'), dict(os='Windows', qualification={}), dict(os='Windows')):
            with self.subTest(plan=selected):
                plan = dict(selected, python=dict(path=sys.executable), harness=dict(root=str(self.root)))
                Path(value['plan']).write_text(json.dumps(plan))
                value['plan_sha256'] = hashlib.sha256(Path(value['plan']).read_bytes()).hexdigest()
                budget = preflight.Budget(value['limits'], self.root)
                order = []
                with patch.object(native_preflight, 'preparation_inputs', return_value=['proof.json']) as inputs, \
                     patch.object(preflight, 'minimum_inventory', side_effect=lambda paths, b: order.append(('inventory', paths))), \
                     patch.object(native_preflight, 'inspect', side_effect=lambda *a, **k: order.append(('inspect', None)) or dict(status='blocked')):
                    preflight.inspect(value, budget)
                if selected == dict(os='Windows'):
                    inputs.assert_not_called()
                    self.assertEqual(order, [('inspect', None)])
                else:
                    inputs.assert_called_once_with(plan)
                    self.assertEqual(order, [('inventory', ['proof.json']), ('inspect', None)])

    def test_missing_import_helper_denied_without_workload(self):
        request, _ = self.fixture()
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ('acceptance-preflight.py', 'acceptance-syntax.mjs', 'validation-runner.py', 'browser-small-runner.py'):
            shutil.copyfile(SCRIPT.with_name(name), scripts / name)
        _, result = self.run_cli(request, scripts / SCRIPT.name)
        self.assertIn('browser-small-windows.py', result['error'])

    def test_short_read_and_visit_allowances_fail(self):
        for key in ('read_bytes', 'visits'):
            with self.subTest(key=key):
                request, value = self.fixture()
                value['limits'][key] = 1
                request.write_text(json.dumps(value))
                _, result = self.run_cli(request)
                self.assertIn('allowance', result['error'])
                shutil.rmtree(self.root / 'evidence')

    def test_deterministic_capture_storage_shortfall_denied_before_directory(self):
        request, value = self.fixture()
        value['limits']['storage_bytes'] = 1
        request.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'storage shortfall'):
            preflight.preflight(request, self.root / 'evidence')
        self.assertFalse((self.root / 'evidence').exists())

    def test_windows_admission_block_is_not_promoted_to_pass(self):
        request, _ = self.fixture()
        evidence = self.root / 'worker'
        evidence.mkdir()
        with patch.object(preflight, 'inspect', return_value=dict(status='blocked', runtime_pending=['Windows admission'])):
            # Use an isolated child for production audit hooks; this control
            # replaces installation to observe the returned protocol only.
            with patch.object(preflight.Budget, 'install'):
                code = preflight.worker(request, evidence)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads((evidence / 'worker-result.json').read_text())['status'], 'blocked')

    def test_final_budget_failure_invalidates_adapter_pass(self):
        request, _ = self.fixture()
        evidence = self.root / 'worker'
        evidence.mkdir()
        reached_pass = []
        def inspect(*args):
            reached_pass.append(True)
            return dict(status='passed', runtime_pending=['tiny'])
        def check(*args):
            if reached_pass:
                raise OSError('preparation deadline exceeded')
        with patch.object(preflight, 'inspect', side_effect=inspect), \
             patch.object(preflight.Budget, 'install'), \
             patch.object(preflight.Budget, 'check', side_effect=check):
            code = preflight.worker(request, evidence)
        self.assertTrue(reached_pass)
        self.assertEqual(code, 1)
        result = json.loads((evidence / 'worker-result.json').read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertIn('deadline exceeded', result['error'])

    def test_fresh_evidence_is_mandatory(self):
        request, _ = self.fixture()
        evidence = self.root / 'evidence'
        evidence.mkdir()
        with self.assertRaisesRegex(ValueError, 'fresh'):
            preflight.preflight(request, evidence)

    def test_offline_windows_destination_uses_the_same_root_and_overlap_rules(self):
        from pathlib import PureWindowsPath as WindowsPath
        selected = dict(root='C:/source', history_roots=['C:/history'],
                        input_directories={'C:/other-inputs': []},
                        nested=[dict(controller_root='C:/controller')])
        protected = [WindowsPath('C:/checker/scripts'),
                     *(WindowsPath(value) for value in preflight.declared_source_roots(selected))]
        for path in ('C:/source/outside-inventories/evidence', 'C:/history/evidence',
                     'C:/other-inputs/evidence', 'C:/controller/evidence', 'C:/checker/scripts/evidence'):
            with self.subTest(path=path), self.assertRaises(preflight.UnsafeDestination):
                preflight.check_evidence_destination(WindowsPath(path), protected)
        preflight.check_evidence_destination(WindowsPath('C:/metadata/evidence'), protected)
        self.assertEqual(list(self.root.iterdir()), [])  # declarations never write evidence

    def test_evidence_cannot_dirty_selected_inventory_even_on_failure(self):
        request, value = self.fixture()
        source = self.root / 'selected-source'
        source.mkdir()
        Path(value['plan']).write_text(json.dumps(dict(root=str(source))))
        value['plan_sha256'] = hashlib.sha256(Path(value['plan']).read_bytes()).hexdigest()
        request.write_text(json.dumps(value))
        evidence = source / 'new-attempt'
        completed = subprocess.run([sys.executable, '-B', str(SCRIPT), 'preflight', str(request), str(evidence)],
                                   capture_output=True, text=True, timeout=20)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn('overlaps', json.loads(completed.stdout)['error'])
        self.assertEqual(list(source.iterdir()), [])

    def test_picker_evidence_cannot_dirty_controller_or_inventory_mapping(self):
        request, value = self.fixture('actual-picker')
        source = self.root / 'picker-source'
        source.mkdir()
        for binding in (dict(controller_root=str(source)), dict(input_directories={str(source): []})):
            with self.subTest(binding=binding):
                Path(value['plan']).write_text(json.dumps(binding))
                value['plan_sha256'] = hashlib.sha256(Path(value['plan']).read_bytes()).hexdigest()
                request.write_text(json.dumps(value))
                completed = subprocess.run([sys.executable, '-B', str(SCRIPT), 'preflight', str(request), str(source / 'evidence')],
                                           capture_output=True, text=True, timeout=20)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn('overlaps', json.loads(completed.stdout)['error'])
                self.assertEqual(list(source.iterdir()), [])

    def test_worker_artifact_identity_survives_parent_failure_receipt(self):
        request, _ = self.fixture()
        _, result = self.run_cli(request)
        evidence = self.root / 'evidence'
        state = json.loads((evidence / 'runner/status.json').read_text())
        artifact = next(iter(state['attempts'][0]['artifacts'].values()))
        worker = evidence / 'worker-result.json'
        self.assertEqual(artifact['sha256'], hashlib.sha256(worker.read_bytes()).hexdigest())
        self.assertEqual(artifact['mtime_ns'], worker.stat().st_mtime_ns)
        self.assertEqual(result['worker_receipt_sha256'], artifact['sha256'])
        self.assertGreater(result['supervisor_usage']['charged_read_bytes'], 0)

    def test_fixed_probe_uses_read_only_null_stdin_under_source_guard(self):
        code = '''import importlib.util,os,pathlib,sys
spec=importlib.util.spec_from_file_location('preflight',sys.argv[1])
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
b=p.Budget(dict(seconds=5,read_bytes=16777216,visits=100000,capture_bytes=4096,storage_bytes=65536),sys.argv[2])
b.null_input=open(os.devnull,'rb');b.install()
try:
 p.probe([sys.executable,'-B','-c',"print('setup-only')"],b,'fixed-probe')
finally:
 b.active=False;b.null_input.close()
'''
        completed = subprocess.run([sys.executable, '-B', '-c', code, str(SCRIPT), str(self.root)],
                                   capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((self.root / 'fixed-probe.log').read_text(), 'setup-only\n')

    def test_windows_formatted_audit_command_requires_exact_approval(self):
        _, value = self.fixture()
        budget = preflight.Budget(value['limits'], self.root)
        argv = [r'C:\Program Files\node\node.exe', r'C:\selected\syntax.mjs', 'argument with spaces']
        formatted = subprocess.list2cmdline(argv)
        budget.allowed_commands.add(budget.command_key(argv))
        budget.active = True
        budget.audit('subprocess.Popen', (None, formatted, None, None))
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            budget.audit('subprocess.Popen', (None, formatted + ' --unexpected', None, None))
        budget.active = False

    def test_compiled_helper_must_be_in_frozen_input_manifest(self):
        _, value = self.fixture()
        main, helper, compiler = [self.root / name for name in ('main.mjs', 'helper.mjs', 'compiler.js')]
        for path in (main, helper, compiler):
            path.write_text('export const value = 1;')
        output = self.root / 'syntax.log'
        output.write_text(json.dumps(dict(status='passed', compiler=str(compiler), packages=[],
            metafile=dict(inputs={'main.mjs': {}, 'helper.mjs': {}}))))
        budget = preflight.Budget(value['limits'], self.root)
        with patch.object(preflight, 'probe', return_value=output):
            with self.assertRaisesRegex(ValueError, 'outside declared'):
                preflight.javascript(str(self.root), 'unused-node', [str(main)], budget, [str(main), str(compiler)])
            result = preflight.javascript(str(self.root), 'unused-node', [str(main)], budget,
                                          [str(main), str(helper), str(compiler)])
        self.assertEqual(result['status'], 'passed')

    def test_parent_identity_work_exhausts_deadline_before_worker_start(self):
        request, value = self.fixture()
        value['limits']['seconds'] = 1
        request.write_text(json.dumps(value))
        runner = preflight.load('validation-runner')
        original = runner.digest
        def slow_digest(path):
            time.sleep(.4)
            return original(path)
        with patch.object(runner, 'digest', side_effect=slow_digest), \
             patch.object(preflight, 'load', return_value=runner):
            code = preflight.preflight(request, self.root / 'evidence')
        self.assertEqual(code, 1)
        evidence = self.root / 'evidence'
        self.assertFalse((evidence / 'worker-result.json').exists())
        result = json.loads((evidence / 'result.json').read_text())
        self.assertEqual(result['status'], 'failed')
        self.assertGreaterEqual(result['supervisor_usage']['seconds'], 1)
        self.assertFalse(result['acceptance_window_started'])
        self.assertEqual(result['host']['os'], platform.system())
        self.assertEqual(result['request_sha256'], hashlib.sha256(request.read_bytes()).hexdigest())
        self.assertEqual(result['plan_sha256'], value['plan_sha256'])
        self.assertEqual(result['profile'], value['profile'])
        self.assertEqual(result['checker']['sha256'], hashlib.sha256(SCRIPT.read_bytes()).hexdigest())

    def test_complete_inventory_size_denies_before_payload_reads(self):
        _, value = self.fixture()
        payload = self.root / 'selected-tool.bin'
        payload.write_bytes(b'x' * 8192)
        value['limits']['read_bytes'] = 4096
        budget = preflight.Budget(value['limits'], self.root)
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('payload must not be read')):
            with self.assertRaisesRegex(ValueError, 'requires at least 8192'):
                preflight.minimum_inventory([str(payload)], budget)
        self.assertEqual(payload.stat().st_size, 8192)
        self.assertEqual(budget.read_bytes, 0)

    def test_browser_scale_same_version_other_python_denies_before_identity_or_probes(self):
        request, value = self.fixture('browser-scale')
        selected = dict(python=dict(path=str(self.root / 'other-python'), version=sys.version))
        Path(value['plan']).write_text(json.dumps(selected))
        value.update(host_os='Windows', plan_sha256=hashlib.sha256(Path(value['plan']).read_bytes()).hexdigest())
        budget = preflight.Budget(value['limits'], self.root)
        with patch.object(preflight.platform, 'system', return_value='Windows'), \
             patch('scale_acceptance.browser_scale_identity.ScaleIdentity') as identity, \
             patch.object(preflight, 'probe') as probe:
            with self.assertRaisesRegex(ValueError, 'selected Python'):
                preflight.inspect(value, budget)
        identity.assert_not_called()
        probe.assert_not_called()

    def test_supervisor_polling_is_charged_and_small_allowance_never_passes(self):
        for visits, expected in ((1200, 1), (50000, 0)):
            with self.subTest(visits=visits):
                request, value = self.fixture()
                value['limits'].update(seconds=20, visits=visits)
                request.write_text(json.dumps(value))
                runner = preflight.load('validation-runner')
                evidence = self.root / ('polling-' + str(visits))
                def fake_run(plan, directory, guard):
                    directory.mkdir()
                    (directory / 'status.json').write_text('{}')
                    (directory / '1-stdout.log').write_text('')
                    for _ in range(100):
                        guard()
                    (evidence / 'worker-result.json').write_text(json.dumps(dict(status='passed', usage=dict(
                        charged_read_bytes=0, directory_entries_and_opens=0))))
                    return 0
                actual_stats = []
                original_stat = os.stat
                def counted_stat(*args, **kwargs):
                    actual_stats.append(1)
                    return original_stat(*args, **kwargs)
                with patch.object(runner, 'run', side_effect=fake_run), \
                     patch.object(preflight, 'load', return_value=runner), \
                     patch.object(os, 'stat', side_effect=counted_stat):
                    code = preflight.preflight(request, evidence)
                result = json.loads((evidence / 'result.json').read_text())
                self.assertEqual(code, expected)
                self.assertGreaterEqual(result['supervisor_usage']['directory_entries_and_opens'], len(actual_stats))
                self.assertFalse(result['workload_started'])
                if expected:
                    self.assertEqual(result['status'], 'failed')
                    self.assertIn('allowance shortfall', result['error'])
                else:
                    self.assertEqual(result['status'], 'passed')




class HostedPacketControls(unittest.TestCase):
    def setUp(self):
        from scale_acceptance import hosted_qualification
        self.q = hosted_qualification
        # These are receipt-consumer controls, not actual-host preflight.
        owning=patch.object(self.q,'preflight');owning.start();self.addCleanup(owning.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    @staticmethod
    def write_source(path, text):
        # Source pins compare bytes with Git objects, not text-mode newlines.
        path.write_bytes(text.encode('utf-8'))

    def native_fixture(self, value):
        path=Path(value)
        try:relative=path.relative_to(self.root)
        except ValueError:
            native=self.q.PureWindowsPath(str(value))
            if native.is_absolute():return str(native)
            relative=Path(path.name)
        return str(self.q.PureWindowsPath(r'\\server\share')/relative.as_posix())

    def test_fixture_source_bytes_and_entrypoint_hierarchy_match_real_provenance(self):
        from types import SimpleNamespace
        repo=self.root/'repo';common=repo/'scripts/acceptance-preflight.py'
        common.parent.mkdir(parents=True);body='def inspect(): return 1\n'
        self.write_source(common,body)
        def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL)
        git('init');git('config','user.email','fixture@example.invalid');git('config','user.name','Fixture')
        git('config','core.autocrlf','true');git('add','.');git('commit','-m','fixture')
        self.assertEqual(common.read_bytes(),body.encode('utf-8'))
        self.assertEqual(git('show','HEAD:scripts/acceptance-preflight.py'),common.read_bytes())
        checker=SimpleNamespace(checker_sources=lambda:[common])
        pin=dict(path=self.native_fixture(common),sha256=hashlib.sha256(common.read_bytes()).hexdigest())
        self.assertEqual(self.q.PureWindowsPath(pin['path']).parts[-2:],('scripts','acceptance-preflight.py'))
        self.assertEqual(self.native_fixture(r'C:\borrowed\node.exe'),r'C:\borrowed\node.exe')
        with patch.object(self.q,'native_path',side_effect=self.native_fixture):
            self.assertEqual(self.q.host_implementation(dict(preparation_code=[pin]),None,repo,checker)['status'],'identical-producer')
            flat=dict(pin,path=r'\\server\share\acceptance-preflight.py')
            with self.assertRaisesRegex(ValueError,'unique historical producer entrypoint'):
                self.q.host_implementation(dict(preparation_code=[flat]),None,repo,checker)

    def test_scale_projection_keeps_conflicting_git_roles_and_complete_dependency_closure(self):
        from scale_acceptance.browser_scale_identity import ASSETS,HARNESS_INPUTS
        from types import SimpleNamespace
        repo=self.root/'repo';repo.mkdir()
        def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL).decode().strip()
        git('init');git('config','user.email','packet@example.invalid');git('config','user.name','Packet Control')
        (repo/'scripts').mkdir();script=repo/'scripts/acceptance-preflight.py';script.write_text('product role')
        (repo/'Cargo.toml').write_text('product')
        git('add','.');git('commit','-m','product');product=git('rev-parse','HEAD')
        script.write_text('harness role');git('add','.');git('commit','-m','harness');harness=git('rev-parse','HEAD')
        files=[dict(relative='ui/dist/'+n,sha256='a'*64,bytes=1)for n in ASSETS]
        files += [dict(relative=n+'/required',sha256='b'*64,bytes=1)for n in HARNESS_INPUTS if n.startswith('ui/node_modules/')]
        checker=SimpleNamespace(checker_sources=lambda:[script])
        payload=dict(native_root='C:/borrowed',files=files)
        result=self.q.browser_scale_projection(repo,product,harness,payload,checker)
        self.assertNotEqual(result['product']['scripts/acceptance-preflight.py'],result['harness']['scripts/acceptance-preflight.py'])
        self.assertEqual(len(result['assets']),7);self.assertEqual(result['harness_inputs'],sorted(HARNESS_INPUTS))
        with self.assertRaisesRegex(ValueError,'production assets'):
            self.q.browser_scale_projection(repo,product,harness,dict(payload,files=files[1:]),checker)
        with self.assertRaisesRegex(ValueError,'build dependencies'):
            self.q.browser_scale_projection(repo,product,harness,dict(payload,files=files[:-1]),checker)
        with self.assertRaisesRegex(ValueError,'traversal'):
            self.q.browser_scale_projection(repo,product,harness,dict(payload,files=files+[dict(relative='../escape')]),checker)
        script.write_text('dirty checker')
        with self.assertRaisesRegex(ValueError,'clean selected harness'):
            self.q.browser_scale_projection(repo,product,harness,payload,checker)

    def test_scale_host_declarations_normalize_retained_separator_format_without_changing_receipt(self):
        raw=r'C:\\Program Files\\Git\\ucrt64\\libexec\\git-core'
        file=raw+r'\\git.exe';canonical=str(self.q.PureWindowsPath(file))
        observed=dict(git_exec_path=raw,tools={},inputs=[],input_sizes={},input_directories={},
            preparation=dict(tools=dict(git=dict(path=file,sha256='a'*64)),
                inputs=[dict(path=file,sha256='a'*64)],input_sizes={file:10},input_directories={raw:[file]}))
        original=json.loads(json.dumps(observed));derived=self.q.browser_scale_host_bindings(observed)
        self.assertEqual(observed,original)
        self.assertEqual(derived['preparation']['inputs'],[dict(path=canonical,sha256='a'*64)])
        self.assertEqual(derived['preparation']['input_directories'],{str(self.q.PureWindowsPath(raw)):[canonical]})
        observed['preparation']['inputs'].append(dict(path=canonical,sha256='b'*64))
        with self.assertRaisesRegex(ValueError,'conflicting canonical runtime pin'):self.q.browser_scale_host_bindings(observed)

    def test_native_paths_reject_rooted_without_drive_and_relative(self):
        for bad in ('home/x.json',r'\home\x.json','C:relative.json'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                self.q.native_path(bad)
        self.assertEqual(self.q.native_path(r'C:\selected\x.json'),r'C:\selected\x.json')
        self.assertEqual(self.q.native_path(r'\\server\share\x.json'),r'\\server\share\x.json')

    def test_namespaces_are_one_derivation_and_partition_denies_ancestor_alias(self):
        paths = self.q.preparation_paths('C:/selected-r9')
        self.assertEqual(paths['root'],r'C:\selected-r9-source\checkout')
        for bad in ('C:/a/b','C:/a/../b','D:/selected','C:/selected space'):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.q.preparation_paths(bad)
        for bad in (['C:/one','C:/one/child'],['C:/ONE','C:/one']):
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.q._disjoint_native_roots(bad)

    def test_pin_mismatch_reports_actual_from_single_bounded_read(self):
        path = self.root/'input';path.write_bytes(b'changed')
        budget = preflight.Budget(dict(seconds=10,read_bytes=1024,visits=100),self.root)
        with self.assertRaisesRegex(ValueError,'expected='+('0'*64)+' actual='+hashlib.sha256(b'changed').hexdigest()):
            self.q._pinned_bytes(dict(path=str(path),sha256='0'*64),budget)
        self.assertEqual(budget.read_bytes,7)

    def test_actual_dual_git_projection_and_missing_checker_counterexample(self):
        repo = self.root/'repo';repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL).decode().strip()
        git('init');git('config','user.email','packet@example.invalid');git('config','user.name','Packet Control')
        for name,body in {'Cargo.toml':'product','ui/src/product.ts':'selected-product','scripts/build-browser.mjs':'product-build'}.items():
            p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
        git('add','.');git('commit','-m','product');product=git('rev-parse','HEAD')
        git('checkout','--orphan','harness')
        script=repo/'scripts/acceptance-preflight.py';script.write_text('checker')
        helper=repo/'scripts/required.mjs';helper.write_text('required checker helper')
        git('add','.');git('commit','-m','harness');harness=git('rev-parse','HEAD')
        payload=dict(native_root='C:/borrowed',files=[])
        projection=self.q.selected_source_projection(repo,product,harness,payload,'C:/selected/checkout',[script,helper])
        self.assertEqual(set(projection['required_checker_sources']),{'scripts/acceptance-preflight.py','scripts/required.mjs'})
        self.assertEqual(next(r for r in projection['files'] if r['relative']=='ui/src/product.ts')['git_commit'],product)
        helper.write_text('changed working tree')
        with self.assertRaisesRegex(ValueError,'clean harness'):
            self.q.selected_source_projection(repo,product,harness,payload,'C:/selected/checkout',[script,helper])
        helper.write_text('required checker helper')
        missing=repo/'scripts/omitted.mjs';missing.write_text('untracked omission')
        with self.assertRaisesRegex(ValueError,'closure missing'):
            self.q.selected_source_projection(repo,product,harness,payload,'C:/selected/checkout',[script,helper,missing])
        bundle=self.root/'dual.bundle';git('bundle','create',str(bundle),'HEAD',product)
        clone=self.root/'transport'
        subprocess.run(['git','clone','--quiet','--no-checkout',str(bundle),str(clone)],check=True,capture_output=True)
        for row in projection['files']:
            actual=subprocess.check_output(['git','-C',str(clone),'show',row['git_commit']+':'+row['git_path']])
            self.assertEqual(hashlib.sha256(actual).hexdigest(),row['sha256'])

    def test_complete_retained_pool_and_bound_legacy_recovery_ledger(self):
        method=self.q.STORAGE_LEDGER_METHOD
        old=dict(owned_root=r'C:\old-runtime',history_roots=[],retained_origin_manifest=r'C:\old-prep\origin.json',
                 inputs=[dict(path=r'C:\old-prep\origin.json',sha256='a'*64)])
        origin=dict(adopted_roots=[r'C:\old-prep'],metadata=dict(storage_priming=dict(ledger=dict(cumulative_owned_bytes=100))))
        history=dict(configuration=dict(path='configuration',sha256='b'*64),origin=dict(path='origin',sha256='a'*64),
                     ledger=dict(path=r'C:\recovery\preparation\storage-ledger.json',sha256='c'*64))
        roots=[r'C:\old-runtime',r'C:\old-prep',r'C:\later-runtime']
        ledger=dict(method=method,cumulative_owned_bytes=200,covered_roots=roots)
        data=dict(configuration=old,origin=origin)
        def read(binding):
            return ledger if binding['path']==history['ledger']['path'] else data[binding['path']]
        with patch.object(self.q,'_local_binding',side_effect=read):
            self.assertEqual(self.q.retained_storage_ledger(history),(ledger,roots))
            with self.assertRaisesRegex(ValueError,'input closure'):self.q.retained_storage_ledger(history,declared=[])
            for changed in (dict(ledger,covered_roots=roots[1:]),dict(ledger,cumulative_owned_bytes=99),dict(ledger,method='unbound')):
                with patch.dict(ledger,changed,clear=True),self.assertRaises(ValueError):self.q.retained_storage_ledger(history)
            ledger.pop('method')
            with self.assertRaisesRegex(ValueError,'method'):self.q.retained_storage_ledger(history)
            paths=self.q.recovery_paths(r'C:\recovery')
            context=dict(packet=dict(path='packet',sha256='d'*64),after_exit=dict(path=paths['after_exit']+r'\result.json',sha256='e'*64))
            history['ledger']['recovery_context']=context
            data['packet']=dict(schema=self.q.PACKET_SCHEMA,profile='browser-scale',operation=self.q.RECOVERY_OPERATION,
                recovery=dict(path='recovery',sha256='f'*64),paths=paths,
                storage_priming=dict(covered_roots=roots,ledger=dict(cumulative_owned_bytes=200)))
            data['recovery']=dict(root=r'C:\recovery',browser_receipt={'path':'old-main','sha256':'1'*64},
                independent={'path':'old-indie','sha256':'2'*64},consumed_claim={'path':'old-claim','sha256':'3'*64})
            ledger['covered_roots']=[*roots,r'C:\recovery'];ledger['cumulative_owned_bytes']=300
            audit=dict(status='passed-after-exit',operation=self.q.RECOVERY_OPERATION,packet_sha256='d'*64,
                recovery_passed=True,original_byte0_available=True,probe_closed=True,timer_joined=True,cumulative_owned_bytes=300)
            audit.update(original_failed_run=data['recovery']['browser_receipt'],original_independent=data['recovery']['independent'],
                         consumed_claim=data['recovery']['consumed_claim'])
            data[context['after_exit']['path']]=audit
            self.assertEqual(self.q.retained_storage_ledger(history),(ledger,ledger['covered_roots']))
            for key,value in (('packet_sha256','0'*64),('recovery_passed',False),('probe_closed',False),('cumulative_owned_bytes',299)):
                with patch.dict(audit,{key:value}),self.assertRaises(ValueError):self.q.retained_storage_ledger(history)
            with patch.dict(ledger,{'covered_roots':roots}),self.assertRaises(ValueError):self.q.retained_storage_ledger(history)

    def test_small_materialize_forecast_keeps_frozen_overall_clock(self):
        from types import SimpleNamespace
        import datetime
        iso=lambda t:datetime.datetime.fromtimestamp(t,datetime.timezone.utc).isoformat()
        window=dict(schema='chopper-unattended-continuation-v1',non_time_allowances_renewed=False,
                    launch_cutoff_utc=iso(9900),deadline_utc=iso(10000))
        packet=dict(schema=self.q.PACKET_SCHEMA,host=self.q.host(),profile='small',window={},configuration=dict(overall_deadline_ms=10000000))
        for now,exception in ((9099,KeyError),(9100,ValueError)):
            with patch.object(self.q,'os',SimpleNamespace(name='nt')),patch.object(self.q,'bound_json',side_effect=[packet,window]), \
                 patch.object(self.q,'packet_declarations'),patch.object(self.q.time,'time',return_value=now), \
                 self.assertRaises(exception):
                self.q.materialize_packet('selected.json',self.root/'uncreated','a'*64,Mock())
            self.assertFalse((self.root/'uncreated').exists())

    def test_real_packet_generation_derives_commands_and_both_transported_roles(self):
        from types import SimpleNamespace
        repo=self.root/'repo';repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL).decode().strip()
        git('init');git('config','user.email','packet@example.invalid');git('config','user.name','Packet')
        for name in ('Cargo.toml','ui/src/product.ts','ui/package.json','ui/package-lock.json','scripts/build-browser.mjs'):
            p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
        git('add','.');git('commit','-m','product');product=git('rev-parse','HEAD');tree=git('rev-parse','HEAD^{tree}')
        git('checkout','--orphan','harness')
        for name in ('acceptance-preflight.py','local-ci.py','required.mjs'):
            (repo/'scripts'/name).write_text('# current '+name)
        git('add','.');git('commit','-m','harness')
        scripts=[repo/'scripts'/name for name in ('acceptance-preflight.py','required.mjs')]
        release=dict(release_source_commit=product,release_source_tree=tree,
            artifact_receipt=dict(name='receipt.json',sha256='a'*64,bytes=100),
            packages={name:dict(sha256='b'*64,bytes=1024) for name in ('one.zip','two.zip','three.zip')},
            hosted={name:dict(sha256=hashlib.sha256(name.encode()).hexdigest()) for name in ('a','b','c','d','e','f','g')})
        payload=dict(selected_product=product,files=[dict(relative='ui/dist/'+n,bytes=len(n),sha256=v['sha256']) for n,v in release['hosted'].items()])
        payload['files'] += [dict(relative='ui/node_modules/'+n+'/package.json',bytes=2,sha256=hashlib.sha256(b'{}').hexdigest()) for n in ('playwright','playwright-core')]
        tools={role:dict(path='C:\\tools\\'+role+'.exe',sha256='c'*64,signature=dict(status='Valid')) for role in ('git','python','node','browser','powershell')}
        observed=dict(schema='chopper-hosted-host-v1',status='passed',preparation=dict(
            input_sizes={tools[role]['path']:100 for role in ('git','powershell')},
            tools={role:tools[role] for role in ('git','powershell')},
            inputs=[dict(path=tools[role]['path'],sha256=tools[role]['sha256']) for role in ('git','powershell')],input_directories={}),host=dict(os='Windows'),channel='chrome',tools=tools,browser_version='fixture',
            zstd_dll=r'C:\tools\zstd.dll',input_sizes={v['path']:100 for role,v in tools.items() if role not in ('git','powershell')},inputs=[dict(path=v['path'],sha256=v['sha256']) for role,v in tools.items() if role not in ('git','powershell')]+[dict(path=r'C:\tools\zstd.dll',sha256='d'*64)],input_directories={})
        old=dict(owned_root=r'C:\old-runtime',history_roots=[],retained_origin_manifest=r'C:\old-preparation\origin.json',
            inputs=[dict(path=r'C:\old-preparation\origin.json',sha256='e'*64)])
        origin=dict(adopted_roots=[r'C:\old-source',r'C:\old-preparation'])
        ledger=dict(method='sum of per-file identity high-water bytes; deleted identities retained; unknown deletion races deny',cumulative_owned_bytes=100000)
        data={'release':release,'payload':payload,'host':observed,'config':old,'origin':origin,'ledger':ledger,
            'window':dict(schema='chopper-unattended-continuation-v1',non_time_allowances_renewed=False,
                          launch_cutoff_utc='2099-01-01T00:00:00+00:00',deadline_utc='2099-01-02T00:00:00+00:00')}
        selection=dict(schema='chopper-hosted-packet-selection-v1',profile='small',namespace='C:/packet-control',
            release=dict(path='release',sha256='1'*64),payload=dict(manifest=dict(path='payload',sha256='2'*64),native_root='C:/borrowed'),
            host=dict(path='host',sha256='3'*64),tool_signature_status={role:'Valid' for role in tools},packages='C:/packages',
            history=dict(configuration=dict(path='config',sha256='4'*64),origin=dict(path='origin',sha256='e'*64),
                ledger=dict(path=r'C:\old-runtime\storage-ledger.json',sha256='f'*64)),retained_preparation_bytes=1000,
            window=dict(path='window',sha256='5'*64),dispatch=dict(checkout='C:/native',commit='6'*40))
        select=self.root/'selection.json';select.write_text(json.dumps(selection))
        actual_small=preflight.load('browser-small-runner')
        small=SimpleNamespace(PRODUCT=product,PRODUCT_TREE=tree,VARIANTS=actual_small.VARIANTS,
                              ORIGIN_PORTS=actual_small.ORIGIN_PORTS,LIMITS=actual_small.LIMITS,command_specs=actual_small.command_specs)
        checker=SimpleNamespace(__file__=str(scripts[0]),SCHEMA=preflight.SCHEMA,load=lambda _:small,
            checker_sources=lambda:scripts,check_evidence_destination=preflight.check_evidence_destination,probe=preflight.probe)
        observed['preparation_code']=[dict(path=self.native_fixture(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in scripts]
        def binding(value):
            name=value['path'] if value['path'] in data else self.q.PureWindowsPath(value['path']).name
            return data['ledger' if name.endswith('storage-ledger.json') else name]
        with patch.object(self.q,'_local_binding',side_effect=binding),patch.object(self.q,'native_path',side_effect=self.native_fixture):
            receipt=self.q.prepare_packet(select,self.root/'packet',checker)
        packet=json.loads(Path(receipt['path']).read_text())
        self.assertEqual(receipt['commands'],15)
        self.assertEqual(packet['configuration']['overall_deadline_ms'],int(packet['timing']['deadline']*1000))
        legacy_deadline=json.loads(json.dumps(packet));del legacy_deadline['configuration']['overall_deadline_ms']
        with patch.object(self.q,'_local_binding',side_effect=binding),patch.object(self.q,'native_path',side_effect=self.native_fixture):
            self.q.packet_declarations(legacy_deadline,checker)
        wrong_deadline=json.loads(json.dumps(packet));wrong_deadline['configuration']['overall_deadline_ms']-=1
        with patch.object(self.q,'_local_binding',side_effect=binding),self.assertRaisesRegex(ValueError,'overall deadline'):
            self.q.packet_declarations(wrong_deadline,checker)
        self.assertEqual([c['phase'] for c in packet['commands']],['safe-import-denial','preflight','prepare','qualify','after-exit'])
        self.assertEqual(packet['configuration']['commands'][0]['origin'],'http://127.0.0.1:8422')
        self.assertEqual(packet['configuration']['owned_root'],r'C:\packet-control-runtime')
        self.assertEqual(packet['origin']['metadata']['storage_priming']['ledger']['cumulative_owned_bytes'],100000)
        for row in packet['origin']['metadata']['history'].values():
            self.assertTrue(self.q.PureWindowsPath(row['path']).is_absolute())
            self.assertFalse(row['path'].startswith('/'))
        for command in packet['commands']:self.assertEqual(command['argv'][:4],[tools['python']['path'],'-E','-s','-B'])
        self.assertNotIn(tools['git']['path'],[row['path'] for row in packet['configuration']['inputs']])
        self.assertIn(tools['git']['path'],[row['path'] for row in packet['configuration']['preparation']['inputs']])
        self.assertFalse(packet['workload_started']);self.assertFalse(packet['acceptance_window_started'])
        self.assertEqual(set(packet['configuration']['volumes']),{self.q.PureWindowsPath(row['path']).anchor
            for row in [*packet['configuration']['inputs'],*packet['configuration']['preparation']['inputs']]})
        self.assertIn(r'\\server\share'+'\\',packet['configuration']['volumes'])
        # Recovery publication used this captured producer shape: no method,
        # complete covered roots, and a separately bound successful audit.
        original_ledger=dict(ledger)
        roots=[r'C:\old-runtime',r'C:\old-source',r'C:\old-preparation']
        rp=self.q.recovery_paths(r'C:\recovery')
        data['context.json']=dict(schema=self.q.PACKET_SCHEMA,profile='browser-scale',operation=self.q.RECOVERY_OPERATION,
            paths=rp,recovery=dict(path='recovery.json',sha256='8'*64),
            storage_priming=dict(covered_roots=roots,ledger=dict(cumulative_owned_bytes=25633493021)))
        data['recovery.json']=dict(root=r'C:\recovery',browser_receipt={'path':'failed-main','sha256':'1'*64},
            independent={'path':'old-indie','sha256':'2'*64},consumed_claim={'path':'consumed','sha256':'3'*64})
        data['result.json']=dict(status='passed-after-exit',operation=self.q.RECOVERY_OPERATION,packet_sha256='7'*64,
            recovery_passed=True,original_byte0_available=True,probe_closed=True,timer_joined=True,cumulative_owned_bytes=27654631453,
            original_failed_run=data['recovery.json']['browser_receipt'],original_independent=data['recovery.json']['independent'],
            consumed_claim=data['recovery.json']['consumed_claim'])
        ledger.clear();ledger.update(cumulative_owned_bytes=27654631453,covered_roots=[*roots,r'C:\recovery'])
        selection['history']['ledger']=dict(path=rp['metadata']+r'\storage-ledger.json',sha256='f'*64,recovery_context=dict(
            packet=dict(path=str(self.root/'context.json'),sha256='7'*64),
            after_exit=dict(path=rp['after_exit']+r'\result.json',sha256='9'*64)))
        selection['namespace']='C:/packet-recovery';select.write_text(json.dumps(selection))
        with patch.object(self.q,'_local_binding',side_effect=binding),patch.object(self.q,'native_path',side_effect=self.native_fixture):
            recovered=self.q.prepare_packet(select,self.root/'recovery-packet',checker)
            emitted=json.loads(Path(recovered['path']).read_text())
            self.q.packet_declarations(emitted,checker)
            context=emitted['origin']['metadata']['history']['ledger']['recovery_context']
            self.assertTrue(context['packet']['path'].startswith(r'\\server\share'))
            self.assertIn(context['packet']['path'],[row['path']for row in emitted['configuration']['inputs']])
            self.assertEqual(emitted['origin']['metadata']['storage_priming']['covered_roots'],[*roots,r'C:\recovery'])
            wrong=json.loads(json.dumps(emitted));wrong['origin']['metadata']['storage_priming']['covered_roots']=roots
            with self.assertRaisesRegex(ValueError,'partition/history'):self.q.packet_declarations(wrong,checker)
        ledger.clear();ledger.update(original_ledger)
        selection['history']['ledger']=dict(path=r'C:\old-runtime\storage-ledger.json',sha256='f'*64)
        selection['coverage']='first-command-control';selection['namespace']='C:/packet-first'
        selection['retained_after_ledger']=dict(path='newroots',sha256='9'*64)
        data['newroots']=dict(schema='chopper-hosted-retained-roots-v1',base_ledger_sha256='f'*64,
            roots=[dict(root=r'C:\component',inputs=[dict(path=r'C:\component\result.json',sha256='8'*64,bytes=100)])])
        select.write_text(json.dumps(selection))
        with patch.object(self.q,'_local_binding',side_effect=binding),patch.object(self.q,'native_path',side_effect=self.native_fixture):
            first=self.q.prepare_packet(select,self.root/'first-packet',checker)
        control=json.loads(Path(first['path']).read_text())
        self.assertEqual(first['commands'],1)
        partition=control['origin']['metadata']['storage_priming']
        self.assertEqual(partition['fresh_roots'][0],r'C:\component')
        self.assertNotIn(r'C:\component',partition['covered_roots'])
        self.assertEqual(self.q.retained_packet_roots(control),{r'C:\component':[r'C:\component\result.json']})
        self.assertIn(r'C:\component',control['configuration']['input_directories'])
        # The next authoritative ledger already charged this closed input forest.
        # Real emitted packets must retain its pins without declaring it fresh again.
        saved_ledger=json.loads(json.dumps(ledger))
        ledger['covered_roots']=[old['owned_root'],*origin['adopted_roots'],r'C:\component']
        selection['namespace']='C:/packet-covered-input';select.write_text(json.dumps(selection))
        with patch.object(self.q,'_local_binding',side_effect=binding),patch.object(self.q,'native_path',side_effect=self.native_fixture):
            produced=self.q.prepare_packet(select,self.root/'covered-input-packet',checker)
            covered_packet=json.loads(Path(produced['path']).read_text())
            self.q.packet_declarations(covered_packet,checker)
        covered_partition=covered_packet['origin']['metadata']['storage_priming']
        self.assertEqual(covered_partition['ledger']['cumulative_owned_bytes'],ledger['cumulative_owned_bytes'])
        self.assertEqual(self.q.retained_packet_roots(covered_packet),self.q.retained_packet_roots(control))
        self.assertEqual(self.q.retained_packet_roots(covered_packet,fresh=True),{})
        self.assertIn(r'C:\component',covered_packet['configuration']['input_directories'])
        self.assertNotIn(r'C:\component',covered_partition['fresh_roots'])
        self.assertEqual(covered_packet['origin']['adopted_roots'].count(r'C:\component'),1)
        ledger.clear();ledger.update(saved_ledger)
        # Broad disk authorization amends only the cumulative preparation cap.
        # A retained 2GiB campaign can continue; equality at the new 4GiB
        # prospective limit still denies before creating any output.
        selection['retained_preparation_bytes']=2*1024**3
        selection['namespace']='C:/packet-cap-positive'
        select.write_text(json.dumps(selection))
        with patch.object(self.q,'_local_binding',side_effect=binding),patch.object(self.q,'native_path',side_effect=self.native_fixture):
            extended=self.q.prepare_packet(select,self.root/'cap-positive',checker)
        admitted=json.loads(Path(extended['path']).read_text())
        self.assertEqual(admitted['retained_preparation_bytes'],2*1024**3)
        self.assertEqual(admitted['limits']['storage_bytes'],512*1024**2)
        self.assertEqual(admitted['limits']['read_bytes'],2*1024**3)
        self.assertEqual(admitted['preflight_limits']['storage_bytes'],5*1024**2)
        self.assertEqual(admitted['configuration']['limits'],actual_small.LIMITS)
        selection['retained_preparation_bytes']=self.q.SMALL_PREPARATION_CAMPAIGN_BYTES-self.q.SMALL_PREPARATION['storage_bytes']
        selection['namespace']='C:/packet-cap-denied'
        select.write_text(json.dumps(selection))
        with patch.object(self.q,'_local_binding',side_effect=binding),patch.object(self.q,'native_path',side_effect=self.native_fixture):
            with self.assertRaisesRegex(ValueError,'cumulative preparation allowance'):
                self.q.prepare_packet(select,self.root/'cap-denied',checker)
        self.assertFalse((self.root/'cap-denied').exists())
        history_reads=patch.object(self.q,'_local_binding',side_effect=binding)
        history_reads.start();self.addCleanup(history_reads.stop)
        qualifier=next(c for c in control['commands'] if c['phase']=='qualify')
        self.assertIn('--first-command-control',qualifier['argv'])
        qualifier['argv'].remove('--first-command-control')
        with self.assertRaisesRegex(ValueError,'coverage/qualify mode mismatch'):self.q.packet_declarations(control,checker)
        observer=next(c for c in packet['commands'] if c['phase']=='after-exit')
        self.assertEqual(self.q.PureWindowsPath(observer['argv'][4]).parts[-2:],('scripts','acceptance-preflight.py'))
        self.assertTrue(any(row['path']==observer['argv'][4] for row in packet['preparation_code']))
        wrong=json.loads(json.dumps(packet))
        next(c for c in wrong['commands'] if c['phase']=='after-exit')['argv'][4]=r'C:\packet-control-source\checkout\scripts\acceptance-preflight.py'
        with patch.object(self.q,'native_path',side_effect=self.native_fixture):
            self.q.packet_declarations(packet,checker)
            with self.assertRaisesRegex(ValueError,'observer entrypoint/preparation pin mismatch'):
                self.q.packet_declarations(wrong,checker)
        bad=json.loads(json.dumps(packet));bad['configuration']['owned_root']=r'C:\unused-r3-runtime'
        with self.assertRaisesRegex(ValueError,'namespace drift'):self.q.packet_declarations(bad,checker)
        bad=json.loads(json.dumps(packet));bad['bundle']['path']='/home/example/bundle'
        with self.assertRaisesRegex(ValueError,'native drive/share'):self.q.packet_declarations(bad,checker)
        bad=json.loads(json.dumps(packet));bad['projection']['files']=[r for r in bad['projection']['files'] if r['relative']!='scripts/required.mjs']
        with self.assertRaisesRegex(ValueError,'complete selected checker'):self.q.packet_declarations(bad,checker)

        # Captured complete-input worker shape grew beyond the old 5MiB cap.
        # Emit the allowance through the owning producer, then run the actual
        # parent supervisor over a bounded, synthetic version of that shape.
        saved=(list(observed['inputs']),dict(observed['input_sizes']),dict(observed['input_directories']))
        names=[str(self.q.PureWindowsPath('C:/test-runtime')/('x'*96)/f'input-{i:05d}.dat')for i in range(10226)]
        observed['inputs'] += [dict(path=name,sha256='a'*64)for name in names]
        observed['input_sizes'].update({name:100 for name in names})
        observed['input_directories'][r'C:\test-runtime']=names
        selection.update(namespace='C:/rich-preflight-storage',coverage='full15',retained_preparation_bytes=1000)
        select.write_text(json.dumps(selection))
        with patch.object(self.q,'_local_binding',side_effect=binding),patch.object(self.q,'native_path',side_effect=self.native_fixture):
            rich=self.q.prepare_packet(select,self.root/'rich-packet',checker)
        emitted=json.loads(Path(rich['path']).read_text())
        limits=emitted['preflight_limits'];self.assertGreater(limits['storage_bytes'],5*1024**2)
        self.assertLessEqual(limits['storage_bytes'],self.q.SMALL_PREPARATION['storage_bytes'])
        worker=dict(schema=preflight.SCHEMA,status='passed',profile='small',workload_started=False,
            acceptance_window_started=False,scale_slot_consumed=False,
            bindings=dict(inputs=[dict(row,stat=[2**64-1]*5)for row in emitted['configuration']['inputs']],
                          inventories={r'C:\test-runtime':names}),usage=dict(charged_read_bytes=0,directory_entries_and_opens=0))
        raw=(json.dumps(worker,indent=2,sort_keys=True)+'\n').encode()
        self.assertGreater(len(raw),5*1024**2)
        request=self.root/'metadata-request.json';selected=self.root/'metadata-selected.json';selected.write_text('{}')
        for label,storage,code in (('old',5*1024**2,1),('derived',limits['storage_bytes'],0)):
            value=dict(schema=preflight.SCHEMA,profile='small',host_os=platform.system(),plan=str(selected),
                plan_sha256=hashlib.sha256(selected.read_bytes()).hexdigest(),limits=dict(limits,storage_bytes=storage))
            request.write_text(json.dumps(value));directory=self.root/('metadata-'+label)
            def run(plan_path,runner_directory,*,guard):
                (directory/'worker-result.json').write_bytes(raw);guard();return 0
            owned_runner=SimpleNamespace(stop=lambda process:None,run=run)
            with patch.object(preflight,'load',return_value=owned_runner):
                actual=preflight.supervise(request,directory,value,preflight.Budget(value['limits'],directory),preflight.result_base(value,request))
            self.assertEqual(actual,code)
            result=json.loads((directory/'result.json').read_text())
            self.assertEqual(result['status'],'failed'if code else'passed')
            if code:self.assertIn('storage stop exceeded',result['error'])
            else:
                self.assertEqual(result['bindings'],worker['bindings'])
                self.assertEqual(result['worker_receipt_sha256'],hashlib.sha256(raw).hexdigest())
                self.assertLess(sum(p.stat().st_size for p in directory.rglob('*')if p.is_file()),storage)
        observed['inputs'],observed['input_sizes'],observed['input_directories']=saved

        # The same owning producer emits a separate clean BrowserScale packet;
        # feed its exact generated command into the actual CLI parser/dispatch.
        from scale_acceptance import browser_scale_identity as scale_identity
        release['hosted']={name:dict(sha256=hashlib.sha256(name.encode()).hexdigest()) for name in scale_identity.ASSETS}
        payload['files']=[dict(relative='ui/dist/'+n,bytes=len(n),sha256=v['sha256']) for n,v in release['hosted'].items()]
        payload['files'] += [dict(relative=n+'/package.json',bytes=2,sha256=hashlib.sha256(b'{}').hexdigest())
            for n in scale_identity.HARNESS_INPUTS if n.startswith('ui/node_modules/')]
        release['packages']['selected-hosted.zip']=dict(sha256='c'*64,bytes=1024)
        observed['git_exec_path']=r'C:\tools\libexec\git-core'
        selection.update(profile='browser-scale',namespace='C:/scale-control',retained_preparation_bytes=1000,hosted_package='selected-hosted.zip',
            retained_input_bytes=1010080,shape='D',origin_port=8431,plan_id='scale-control',approval_reference='reviewed-control')
        select.write_text(json.dumps(selection))
        with patch.object(scale_identity,'SOURCE',product),patch.object(scale_identity,'TREE',tree),             patch.object(self.q,'_local_binding',side_effect=binding),             patch.object(self.q,'native_path',side_effect=self.native_fixture):
            generated=self.q.prepare_packet(select,self.root/'scale-packet',checker)
            scale_packet=json.loads(Path(generated['path']).read_text())
            self.q.packet_declarations(scale_packet,checker)
        argv=next(row['argv'] for row in scale_packet['commands'] if row['phase']=='qualify')
        cli_spec=importlib.util.spec_from_file_location('scale_cli_control',SCRIPT.with_name('scale-acceptance.py'))
        cli=importlib.util.module_from_spec(cli_spec);cli_spec.loader.exec_module(cli)
        with patch.object(sys,'argv',['scale-acceptance.py',*argv[5:]]),patch.object(cli,'run_scale',return_value=0)as run:
            self.assertEqual(cli.main(),0)
        self.assertEqual(run.call_args.args,tuple(Path(scale_packet['paths'][key])for key in ('plan','policy','approval')))
        self.assertEqual(scale_packet['fixture']['bytes'],12800)
        self.assertNotEqual(scale_packet['paths']['product'],scale_packet['paths']['root'])
        data['ledger']['covered_roots']=[old['owned_root'],*origin['adopted_roots'],r'C:\prior-scale-source',r'C:\prior-scale-preparation']
        selection['namespace']='C:/scale-next';select.write_text(json.dumps(selection))
        with patch.object(scale_identity,'SOURCE',product),patch.object(scale_identity,'TREE',tree),             patch.object(self.q,'_local_binding',side_effect=binding),             patch.object(self.q,'native_path',side_effect=self.native_fixture):
            next_receipt=self.q.prepare_packet(select,self.root/'scale-next',checker)
        next_packet=json.loads(Path(next_receipt['path']).read_text());partition=next_packet['origin']['metadata']['storage_priming']
        self.assertIn(r'C:\prior-scale-source',partition['covered_roots'])
        self.assertNotIn(r'C:\prior-scale-source',partition['fresh_roots'])
        self.assertEqual(partition['ledger']['cumulative_owned_bytes'],100000)
        for proof_role in ('frozen_batch','campaign_qualification','large_reservation','peer'):
            bad=json.loads(json.dumps(scale_packet))
            bad[proof_role]=dict(path='/home/runner/proofs/chrome-frozen-batch.json',sha256='a'*64)
            if proof_role=='frozen_batch':bad['execution_kind']='batch'
            with patch.object(self.q,'native_path',side_effect=self.native_fixture):
                with self.assertRaisesRegex(ValueError,'absolute native exact pin'):
                    self.q.packet_declarations(bad,checker)
        for mutate in ('pin','output','qualify','closure','port'):
            bad=json.loads(json.dumps(scale_packet))
            if mutate=='pin':bad['bundle']['path']='/home/bad.bundle'
            elif mutate=='output':bad['paths']['approval']=bad['paths']['plan']
            elif mutate=='qualify':bad['commands'][2]['argv'].insert(7,'--policy')
            elif mutate=='port':bad['selection']['origin_port']='8431;Write-Host unexpected'
            else:bad['projection']['harness'].pop('scripts/required.mjs')
            with patch.object(self.q,'native_path',side_effect=self.native_fixture):
                with self.assertRaises(ValueError):self.q.packet_declarations(bad,checker)

    def test_retained_roots_require_exact_base_pin_disjointness_and_complete_file_declarations(self):
        pin=dict(path=r'C:\component\result.json',sha256='a'*64,bytes=100)
        packet=dict(paths=dict(source=r'C:\new-source',metadata=r'C:\new-meta',owned_root=r'C:\new-runtime'),
            configuration=dict(inputs=[dict(path=pin['path'],sha256=pin['sha256'])]),
            origin=dict(metadata=dict(storage_priming=dict(covered_roots=[r'C:\closed'],ledger=dict(sha256='b'*64)))),
            retained_after_ledger=dict(schema='chopper-hosted-retained-roots-v1',base_ledger_sha256='b'*64,
                roots=[dict(root=r'C:\component',inputs=[pin])]))
        self.assertEqual(self.q.retained_packet_roots(packet),{r'C:\component':[pin['path']]})
        self.assertEqual(self.q.retained_packet_roots(packet,fresh=True),{r'C:\component':[pin['path']]})
        covered=json.loads(json.dumps(packet))
        covered['origin']['metadata']['storage_priming']['covered_roots'].append(r'C:\component')
        self.assertEqual(self.q.retained_packet_roots(covered),{r'C:\component':[pin['path']]})
        self.assertEqual(self.q.retained_packet_roots(covered,fresh=True),{})
        for root in (r'C:\component\nested',r'C:\COMPONENT'):
            bad=json.loads(json.dumps(covered))
            bad['origin']['metadata']['storage_priming']['covered_roots']=[root]
            with self.subTest(covered=root),self.assertRaises(ValueError):self.q.retained_packet_roots(bad)
        for fault in ('overlap','ledger','pin','traversal','bytes','duplicate'):
            bad=json.loads(json.dumps(packet))
            value=bad['retained_after_ledger']
            if fault=='overlap':value['roots'][0]['root']=r'C:\closed'
            if fault=='ledger':value['base_ledger_sha256']='c'*64
            if fault=='pin':bad['configuration']['inputs'][0]['sha256']='c'*64
            if fault=='traversal':value['roots'][0]['inputs'][0]['path']=r'C:\component\..\foreign'
            if fault=='bytes':value['roots'][0]['inputs'][0]['bytes']=-1
            if fault=='duplicate':value['roots']*=2
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.q.retained_packet_roots(bad)

    def test_host_provenance_reuses_only_unrelated_selector_functions(self):
        from types import SimpleNamespace
        mapping=patch.object(self.q,'native_path',side_effect=self.native_fixture)
        mapping.start();self.addCleanup(mapping.stop)
        repo=self.root/'repo';(repo/'scripts/scale_acceptance').mkdir(parents=True)
        def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL).decode().strip()
        git('init');git('config','user.email','control@example.invalid');git('config','user.name','Control')
        common=repo/'scripts/acceptance-preflight.py';self.write_source(common,'# source anchor')
        producer=repo/'scripts/scale_acceptance/hosted_qualification.py'
        self.write_source(producer,'def host(): return 1\ndef prepare_packet(): return 1\n')
        small_path=repo/'scripts/browser-small-runner.py';self.write_source(small_path,'def stamp(): return 1\ndef qualify(): return 1\n')
        windows=repo/'scripts/browser-small-windows.py';self.write_source(windows,'def process_identity(): return 1\n')
        writer=repo/'scripts/validation-runner.py';self.write_source(writer,'import os\ndef contain_session(): return 1\ndef write_json(path,value):\n temporary=path\n os.replace(temporary,path)\n')
        consumer=repo/'scripts/scale_acceptance/browser_scale_watchdog.py';self.write_source(consumer,'class Watchdog: pass\n')
        files=[common,producer,small_path,windows,writer,consumer]
        git('add','.');git('commit','-m','actual producer');commit=git('rev-parse','HEAD')
        observed=dict(preparation_code=[dict(path='//server/historical/'+p.relative_to(repo).as_posix(),
            sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files])
        self.write_source(producer,'def host(): return 1\ndef prepare_packet(): return 2\ndef host_implementation(): pass\n')
        self.write_source(small_path,'def stamp(): return 1\ndef qualify(): return 2\ndef command_specs(): pass\n')
        self.write_source(windows,'import stat\nfrom pathlib import Path\ndef process_identity(): return 1\ndef read_control_snapshot(): return 2\nclass ControlFileError(OSError): pass\n')
        self.write_source(writer,'import os\ndef contain_session(): return 1\ndef write_json(path,value,*,replace=None):\n temporary=path\n (os.replace if replace is None else replace)(temporary,path)\n')
        consumer.write_bytes(SCRIPT.parent.joinpath('scale_acceptance/browser_scale_watchdog.py').read_bytes())
        checker=SimpleNamespace(__file__=str(common),checker_sources=lambda:files)
        proof=self.q.host_implementation(observed,commit,repo,checker)
        self.assertEqual(proof['status'],'observer-and-metadata-helpers-identical')
        self.assertIn('scripts/scale_acceptance/browser_scale_watchdog.py',proof['pinned_consumer_bodies'])
        reviewed=consumer.read_bytes();consumer.write_bytes(reviewed+b'\nUNREVIEWED=True\n')
        with self.assertRaisesRegex(ValueError,'observer/helper implementation changed'):
            self.q.host_implementation(observed,commit,repo,checker)
        consumer.write_bytes(reviewed)
        for path, before, after in ((producer,'def host(): return 1','def host(): return 9'),
                                    (small_path,'def stamp(): return 1','def stamp(): return 9'),
                                    (windows,'def process_identity(): return 1','def process_identity(): return 9'),
                                    (writer,'def contain_session(): return 1','def contain_session(): return 9'),
                                    (writer,'os.replace if replace is None','os.unlink if replace is None'),
                                    (windows,'import stat','import sys')):
            original=path.read_text()
            self.write_source(path,original.replace(before,after))
            with self.assertRaisesRegex(ValueError,'observer/helper implementation changed'):
                self.q.host_implementation(observed,commit,repo,checker)
            self.write_source(path,original)
        self.assertEqual(self.q.host_implementation(observed,commit,repo,checker)['status'],
                         'observer-and-metadata-helpers-identical')

    def test_extra_runtime_inventory_preserves_default_and_complete_nested_closure(self):
        from types import SimpleNamespace
        from hosted_picker.config import inventory
        runtime=self.root/'python';runtime.mkdir();lib=runtime/'Lib';lib.mkdir()
        (runtime/'python.dll').write_bytes(b'dll');(lib/'module.py').write_bytes(b'code')
        node=self.root/'node';node.mkdir();(node/'node.exe').write_bytes(b'node')
        small=SimpleNamespace(inventory=inventory);destination=self.root/'evidence'
        default=self.q.host_runtime_inventory({}, {lib},destination,small)
        self.assertEqual(default,{str(lib):inventory(lib)})
        actual=self.q.host_runtime_inventory(dict(extra_runtime_roots=[str(runtime),str(node)]),{lib},destination,small)
        self.assertEqual(set(actual),{str(runtime),str(lib),str(node)})
        unique={name for rows in actual.values() for name in rows}
        self.assertEqual(len(unique),3);self.assertEqual(sum(Path(name).stat().st_size for name in unique),11)
        self.assertEqual(actual[str(runtime)],inventory(runtime))
        for roots in ([str(runtime)]*2,['relative'],[str(destination)], [str(self.root)]):
            with self.subTest(roots=roots),self.assertRaises(ValueError):
                self.q.host_runtime_inventory(dict(extra_runtime_roots=roots),{lib},destination,small)
        with self.assertRaises(AssertionError):
            self.q.host_runtime_inventory(dict(extra_runtime_roots=[str(self.root/'missing')]),{lib},destination,small)

    def test_signature_probe_suppresses_progress_before_any_cmdlet(self):
        import base64
        from types import SimpleNamespace
        class Boundary(RuntimeError):pass
        small=SimpleNamespace(runner=SimpleNamespace(contain_session=lambda:None),stamp=lambda _:[1,1,1,1,1])
        budget=SimpleNamespace(install=lambda:None,active=False,usage=lambda:dict(charged_read_bytes=123))
        def probe(argv,budget,name):
            self.assertEqual(name,'tool-signatures')
            script=base64.b64decode(argv[-1]).decode('utf-16-le')
            self.assertTrue(script.startswith("$ProgressPreference='SilentlyContinue';$p=ConvertFrom-Json"))
            self.assertIn('Get-AuthenticodeSignature -LiteralPath',script)
            raise Boundary()
        checker=SimpleNamespace(__file__=str(SCRIPT),check_evidence_destination=preflight.check_evidence_destination,
            Budget=lambda *a,**k:budget,load=lambda _:small,probe=probe)
        value=dict(schema='chopper-hosted-host-selection-v1',channel='chrome',
            tools={role:str(Path(sys.executable)) for role in ('git','python','node','browser','powershell')})
        path=self.root/'selection.json';path.write_text(json.dumps(value))
        timer=SimpleNamespace(cancel=lambda:None,join=lambda:None,is_alive=lambda:False)
        with patch.object(self.q.os,'name','nt'),patch.object(self.q,'Path',type(self.root)),patch.object(self.q,'host',return_value={}):
            with self.assertRaises(Boundary):
                self.q.observe_packet_host(path,self.root/'observation',hashlib.sha256(path.read_bytes()).hexdigest(),checker,timer=timer)

    def test_signature_progress_is_not_stripped_and_decode_error_names_capture(self):
        path=self.root/'tool-signatures.log'
        path.write_bytes(b'#< CLIXML\r\n{"python":{"status":"Valid"}}\r\n<Objs/>')
        with self.assertRaisesRegex(ValueError,'tool-signatures JSON decode at') as denied:self.q.signature_facts(path)
        self.assertIn(str(path),str(denied.exception))
        self.assertIsInstance(denied.exception.__cause__,json.JSONDecodeError)
        path.write_bytes(b'{"python":{"status":"Valid"}}\r\n')
        self.assertEqual(self.q.signature_facts(path),dict(python=dict(status='Valid')))

    def test_platform_preload_is_contained_before_audit_and_runtime_freeze(self):
        from types import SimpleNamespace
        events=[]
        class Boundary(RuntimeError):pass
        def stop_stamp(_):events.append('metadata');raise Boundary()
        small=SimpleNamespace(runner=SimpleNamespace(contain_session=lambda:events.append('contain')),stamp=stop_stamp)
        budget=SimpleNamespace(install=lambda:events.append('audit'),active=False,usage=lambda:dict(charged_read_bytes=123))
        checker=SimpleNamespace(__file__=str(SCRIPT),check_evidence_destination=preflight.check_evidence_destination,
            Budget=lambda *a,**k:budget,load=lambda _:small)
        selected=dict(schema='chopper-hosted-host-selection-v1',channel='chrome',
            tools={role:str(Path(sys.executable)) for role in ('git','python','node','browser','powershell')})
        path=self.root/'selection.json';path.write_text(json.dumps(selected))
        timer=SimpleNamespace(cancel=lambda:events.append('cancel'),join=lambda:events.append('join'),is_alive=lambda:False)
        with patch.object(self.q.os,'name','nt'),patch.object(self.q,'Path',type(self.root)), \
             patch.object(self.q,'host',side_effect=lambda:events.append('host') or {}):
            with self.assertRaises(Boundary):
                self.q.observe_packet_host(path,self.root/'observation',hashlib.sha256(path.read_bytes()).hexdigest(),checker,timer=timer)
        failed=json.loads((self.root/'observation/failure.json').read_text())
        self.assertEqual(failed['usage']['charged_read_bytes'],123)
        self.assertEqual(failed['phase'],'bootstrap')
        self.assertTrue(failed['timer_joined'])
        self.assertEqual(events,['contain','host','audit','metadata','cancel','join'])
        self.assertFalse((self.root/'observation/host.json').exists())

    def test_materialization_budget_only_extends_explicit_mutation_roots(self):
        evidence=self.root/'evidence';source=self.root/'source';outside=self.root/'outside'
        limits=dict(seconds=10,read_bytes=1024,visits=100)
        default=preflight.Budget(limits,evidence)
        default.active=True
        with self.assertRaisesRegex(ValueError,'mutation denied'):default.audit('os.mkdir',(str(source),))
        stage=preflight.Budget(limits,evidence,mutation_roots=[evidence,source])
        stage.active=True
        stage.audit('os.mkdir',(str(source/'fresh'),))
        with self.assertRaisesRegex(ValueError,'mutation denied'):stage.audit('os.mkdir',(str(outside),))
        with self.assertRaisesRegex(ValueError,'rename destination'):
            stage.audit('os.rename',(str(source/'one'),str(outside/'two')))

    def test_cold_tool_body_and_membership_are_checked_without_live_freeze(self):
        small=preflight.load('browser-small-runner')
        root=self.root/'cold';root.mkdir()
        git=root/'git.exe';git.write_bytes(b'cold Git')
        dll=root/'runtime.dll';dll.write_bytes(b'cold library')
        members=small.inventory(root)
        pins=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in (git,dll)]
        config=dict(preparation=dict(tools=dict(git=pins[0]),inputs=pins,input_directories={str(root):members}))
        state=small.preparation_state(config)
        self.assertEqual(state['git'],str(git));small.check_inputs(state)
        dll.write_bytes(b'changed')
        with self.assertRaisesRegex(OSError,'Preparation tool body drift'):small.preparation_state(config)
        dll.write_bytes(b'cold library');(root/'unexpected.dll').write_bytes(b'new')
        with self.assertRaisesRegex(OSError,'membership drift'):small.preparation_state(config)
        self.assertEqual(small.preparation_state({}),dict(git='git',frozen=[],inventories={}))

    def test_current_fact_collector_never_adopts_history_and_preserves_unknowns(self):
        documents=[dict(runner_pid=12,inputs=[dict(pid=999,created=100)],history=[dict(pid=888)],
            process_identities=[dict(pid=12,created=120)],sample_trace=[dict(census_pids=[12,13],
                completed_processes=[dict(pid=12,created=120)],causes=[dict(pid=13,
                    held_observation=dict(pid=13,birth=130),fresh_census=dict(pids=[14]),
                    census_child_observation=dict(runner_pid=12,runner_birth=120,pids=[12,15],
                        process=dict(pid=16,created=160)))])])]
        self.assertEqual(self.q.current_process_facts(iter(documents)),[
            dict(pid=12,created=[120]),dict(pid=13,created=[130]),dict(pid=14,created=None),
            dict(pid=15,created=None),dict(pid=16,created=[160])])
        with self.assertRaisesRegex(ValueError,'fact bound'):
            self.q.current_process_facts(documents,maximum=2)

    def test_small_afterexit_consumes_complete_large_binding_without_adopting_input_pids(self):
        from types import SimpleNamespace
        small=preflight.load('browser-small-runner')
        owned=self.root/'closed-runtime';owned.mkdir()
        packet=dict(paths=dict(root=str(self.root/'source'),owned_root=str(owned)))
        selected=self.root/'packet.json';selected.write_text(json.dumps(packet))
        (owned/'job.json').write_text(json.dumps(dict(pid=10)))
        (owned/'reservation-released.json').write_text(json.dumps(dict(original_lock_identity=[1,2],passed=False)))
        # A real browser binding includes the full declared manifest on one line.
        binding=dict(type='binding',actual=dict(pid=30),inputs=[dict(path='C:/input/'+str(i),sha256='a'*64,pid=999)
            for i in range(20000)])
        body=json.dumps(binding).encode()+b'\n';self.assertGreater(len(body),1024**2)
        (owned/'command-1.jsonl').write_bytes(body)
        checker=SimpleNamespace(Budget=preflight.Budget,load=lambda _:small,
            check_evidence_destination=preflight.check_evidence_destination)
        def observe(windows,facts,release,original,deadline,result):
            self.assertEqual(facts,[dict(pid=10,created=None)])
            self.assertFalse(release['passed'])
            result['ownership_only']=True
        with patch.object(self.q,'os',SimpleNamespace(name='nt')),patch.object(self.q,'packet_declarations'), \
                patch.object(self.q,'independent_observation',side_effect=observe), \
                patch.object(small,'module',return_value=SimpleNamespace(host_lock_path=lambda:self.root/'original')):
            with patch.object(small.Receipts,'MAX_BYTES',1024**2),self.assertRaisesRegex(ValueError,'line memory bound'):
                self.q.after_exit(selected,self.root/'old-denied',hashlib.sha256(selected.read_bytes()).hexdigest(),checker)
            result=self.q.after_exit(selected,self.root/'new-accepted',hashlib.sha256(selected.read_bytes()).hexdigest(),checker)
        self.assertEqual(result['status'],'passed-after-exit');self.assertTrue(result['ownership_only'])
        self.assertIn(str(owned/'command-1.jsonl'),[row['path'] for row in result['source_receipts']])

    def test_held_afterexit_object_requires_positive_birth_and_end_proof(self):
        import ctypes
        from types import SimpleNamespace
        def observe(birth=20,expected=20,wait=0,code=0,close=True,handle=1,error=0):
            proxy=SimpleNamespace(set_last_error=lambda _:None,get_last_error=lambda:error,byref=ctypes.byref)
            windows=SimpleNamespace(ctypes=proxy,W=SimpleNamespace(DWORD=ctypes.c_uint32),
                checked=lambda value:self.assertTrue(value),_held_birth=lambda kernel,h:birth)
            def exit_code(h,pointer):pointer._obj.value=code;return True
            kernel=SimpleNamespace(OpenProcess=lambda *a:handle,GetProcessId=lambda _:7,
                WaitForSingleObject=lambda *a:wait,GetExitCodeProcess=exit_code,CloseHandle=lambda _:close)
            return self.q.process_observation(windows,kernel,7,expected)
        self.assertEqual(observe(handle=0,error=87)['status'],'absent')
        self.assertEqual(observe(handle=0,error=5)['status'],'unavailable')
        self.assertEqual(observe()['status'],'ended-known-birth-signaled')
        self.assertEqual(observe(birth=21,wait=258,code=259)['status'],'pid-reused-unrelated-original-ended')
        self.assertEqual(observe(expected=None)['status'],'exists-unattributed-or-live')
        self.assertEqual(observe(wait=258,code=259)['status'],'exists-unattributed-or-live')
        self.assertEqual(observe(close=False)['status'],'handle-close-unproven')

    def test_window_gate_keeps_full_preparation_runtime_cleanup_forecast(self):
        import datetime
        epoch=datetime.datetime(2030,1,1,tzinfo=datetime.timezone.utc).timestamp()
        value=dict(schema='chopper-unattended-continuation-v1',non_time_allowances_renewed=False,
            launch_cutoff_utc='2030-01-01T02:00:00+00:00',deadline_utc='2030-01-01T03:00:00+00:00')
        self.q._window(value,now=epoch)
        with self.assertRaisesRegex(ValueError,'cannot fit'):
            self.q._window(value,now=epoch+3000)

    def test_materialize_cli_denies_unbound_import_before_output(self):
        selected=self.root/'packet.json';selected.write_text(json.dumps(dict(preparation_code=[])))
        output=self.root/'out'
        completed=subprocess.run([sys.executable,'-E','-s','-B',str(SCRIPT),'materialize',str(selected),str(output),
            '--sha256',hashlib.sha256(selected.read_bytes()).hexdigest()],capture_output=True,text=True,timeout=10)
        self.assertEqual(completed.returncode,1)
        self.assertIn('pre-import checker closure mismatch',completed.stdout)
        self.assertFalse(output.exists())


class FrozenBatchControls(unittest.TestCase):
    def setUp(self):
        from scale_acceptance import hosted_qualification
        self.q = hosted_qualification
        own_preflight = patch.object(self.q,'preflight')
        own_preflight.start();self.addCleanup(own_preflight.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.selected = dict(source={'commit':'product'},harness_source={'commit':'harness'},
            product={'sha256':{'product':'a'}},harness={'sha256':{'runtime.py':'b'}},
            assets={'sha256':{'engine.wasm':'c'}},package={'sha256':'d'},evidence={'sha256':{'receipt':'e'}},
            browser={'sha256':'f'},python={'sha256':'g'},node={'sha256':'h'},git={'sha256':'i'},
            toolchains={'python':'selected'},external_runtime={'inputs':[{'sha256':'j'}]},
            host={'os':'Windows','node':'fixture'},channel='chrome',browser_version='selected',
            features=[],fixture={'bytes':12800},shape='D',mode='qualify',storage={'owned_limit_bytes':24*1024**3},build_receipts=['receipt'])
        self.bridge(self.selected,self.root/'original-harness',self.root/'original-product')

    def pin(self, name, value):
        path = self.root/name
        path.write_text(json.dumps(value))
        return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def bridge(self, selected, root, product):
        root.mkdir(exist_ok=True)
        entry = ('import '+json.dumps(str(product/'ui/src/app.ts'))+';\n'
            'import {browserApi, executionHistory} from '+json.dumps(str(product/'ui/src/browser/client.ts'))+';\n'
            'import {installPageAdapter} from '+json.dumps(str(root/'scripts/scale_acceptance/browser-page.mjs'))+';\n'
            'installPageAdapter(browserApi, () => executionHistory);')
        selected['harness']['root']=str(root);selected['product']['root']=str(product)
        selected.update(bundle='bridge.js',bundle_provenance='bridge.json')
        selected['harness']['sha256']['bridge.js']='bridge-body'
        value=dict(entry_sha256=hashlib.sha256(entry.encode()).hexdigest(),bundle_sha256='bridge-body',
            inputs={'product':{'product':'a'}},esbuild_version='fixture',hosted=True)
        pin=self.pin(str(root/'bridge.json'),value)
        selected['harness']['sha256']['bridge.json']=pin['sha256']

    def test_root_derived_bridge_record_varies_but_execution_projection_stays_exact(self):
        before=self.q.batch_projection(self.selected,'browser-scale')
        other=json.loads(json.dumps(self.selected))
        self.bridge(other,self.root/'other-harness',self.root/'other-product')
        self.assertNotEqual(self.selected['harness']['sha256']['bridge.json'],other['harness']['sha256']['bridge.json'])
        self.assertEqual(before,self.q.batch_projection(other,'browser-scale'))
        original=json.loads((self.root/'other-harness/bridge.json').read_text())
        for fault in ('entry_sha256','inputs','bundle_sha256','esbuild_version'):
            changed=dict(original);changed[fault]='changed'
            pin=self.pin(str(self.root/'other-harness/bridge.json'),changed)
            other['harness']['sha256']['bridge.json']=pin['sha256']
            if fault in ('entry_sha256','bundle_sha256'):
                with self.subTest(fault=fault),self.assertRaises(ValueError):self.q.batch_projection(other,'browser-scale')
            else:
                self.assertNotEqual(before,self.q.batch_projection(other,'browser-scale'))
        other['harness']['sha256']['bridge.json']='f'*64
        with self.assertRaises(ValueError):self.q.batch_projection(other,'browser-scale')

    def definition(self):
        verifier = self.root/'verifier.py';verifier.write_text('# exact separate verifier')
        self.selected['harness']['sha256']['scripts/scale_acceptance/verify.py']=hashlib.sha256(verifier.read_bytes()).hexdigest()
        config = self.pin('config.json', self.selected)
        pref = dict(schema=preflight.SCHEMA,status='passed',profile='browser-scale',
            plan_sha256=config['sha256'],host=self.selected['host'],checker={'files':{}},bindings={},
            workload_started=False,acceptance_window_started=False,scale_slot_consumed=False)
        worker = self.pin('worker-result.json',pref)
        pref['worker_receipt_sha256'] = worker['sha256']
        preparation = self.pin('preflight.json',pref)
        tiny = self.pin('tiny.json',dict(schema=self.q.SCHEMA,passed=True,scale_acceptance=False,
            profile='browser-scale',channel='chrome',host=self.selected['host'],preflight=preparation,
            qualifies_other_profiles=False,qualifies_other_channels=False))
        audit = self.pin('independent.json',dict(status='passed-after-exit',qualification_passed=True,
            qualification_receipt=tiny,original_byte0_available=True,probe_closed=True,timer_joined=True))
        verifier = self.root/'verifier.py';verifier.write_text('# exact separate verifier')
        return dict(schema='chopper-frozen-batch-selection-v1',profile='browser-scale',channel='chrome',
            configuration=config,preflight=preparation,tiny=tiny,independent=audit,
            verifier=dict(path=str(verifier),sha256=hashlib.sha256(verifier.read_bytes()).hexdigest()))

    def test_sealed_definition_admits_only_root_schedule_variation(self):
        selected = self.definition()
        selection = self.pin('selection.json',selected)
        output = self.root/'definition.json'
        generated = self.q.prepare_batch_definition(selection['path'],output)
        current = dict(self.selected,profile='fresh-root',origin='fresh-origin',plan_id='fresh-attempt',
                       execution_kind='batch',frozen_batch={key:generated[key] for key in ('path','sha256')})
        proof = self.q.batch_admission(current,'browser-scale','chrome')
        self.assertEqual(proof['qualification'],selected['tiny'])
        self.assertFalse(generated['workload_started'])
        with self.assertRaises(ValueError):
            self.q.prepare_batch_definition(selection['path'],output)

    def test_relevant_drift_has_actionable_named_denial_before_launch(self):
        selection = self.pin('selection.json',self.definition())
        generated = self.q.prepare_batch_definition(selection['path'],self.root/'definition.json')
        for key in ('product','harness','assets','package','browser','external_runtime','host','browser_version'):
            current = json.loads(json.dumps(self.selected))
            if key in ('product','harness','assets'):current[key]['sha256']['changed']='changed'
            elif isinstance(current[key],dict):current[key]['changed']='changed'
            else:current[key]='changed'
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.q.qualified_batch(generated,current,'browser-scale','chrome')
        current = json.loads(json.dumps(self.selected));current['harness']['sha256']['runtime.py']='changed'
        with self.assertRaisesRegex(ValueError,'harness; regenerate and requalify'):
            self.q.qualified_batch(generated,current,'browser-scale','chrome')
        with self.assertRaisesRegex(ValueError,'profile/channel'):
            self.q.qualified_batch(generated,self.selected,'browser-scale','msedge')

    def test_failed_or_unjoined_original_qualification_cannot_seal(self):
        for key in ('qualification_passed','original_byte0_available','probe_closed','timer_joined'):
            selected = self.definition()
            audit = json.loads(Path(selected['independent']['path']).read_text());audit[key]=False
            selected['independent']=self.pin('independent.json',audit)
            selection=self.pin('selection.json',selected)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'independent'):
                self.q.prepare_batch_definition(selection['path'],self.root/'definition.json')
            self.assertFalse((self.root/'definition.json').exists())

    def test_batch_cannot_drop_definition_or_launch_large(self):
        with self.assertRaisesRegex(ValueError,'matching frozen batch'):
            self.q.batch_admission(dict(self.selected,execution_kind='batch'),'browser-scale','chrome')
        with self.assertRaisesRegex(ValueError,'Large'):
            self.q.batch_admission(dict(self.selected,mode='scale'),'browser-scale','chrome')
        with self.assertRaisesRegex(ValueError,'masquerade'):
            self.q.batch_admission(dict(self.selected,frozen_batch={}),'browser-scale','chrome')

    def test_native_projection_keeps_tools_policy_and_full_source_maps(self):
        source=dict(root='/old',commit='product',tree='tree',sha256={'runtime.py':'a'},git_blobs={'runtime.py':'git'})
        selected=dict(product=source,harness=source,dependencies=[source],host={'os':'fixture'},
            python={'path':'python','sha256':'a'},tools=[{'path':'git','sha256':'b'}],features=[],limits={'cold':30},
            **{key:{'path':'/old/'+key,'sha256':key} for key in
               ('package','executable','package_receipt','build_proof','selected639_lineage')})
        before=self.q.batch_projection(selected,'native')
        changed=json.loads(json.dumps(selected));changed['harness']['root']='/new'
        changed['harness']['commit']='docs-only';changed['harness']['tree']='docs-only'
        self.assertEqual(before,self.q.batch_projection(changed,'native'))
        for key in ('tools','limits','dependencies','product'):
            value=json.loads(json.dumps(selected))
            if key=='tools':value[key][0]['sha256']='changed'
            elif key=='limits':value[key]['cold']=31
            elif key=='dependencies':value[key][0]['sha256']['runtime.py']='changed'
            else:value[key]['commit']='changed'
            self.assertNotEqual(before,self.q.batch_projection(value,'native'))

    def test_definition_rejects_mismatched_receipts_and_verifier_bytes(self):
        for mutation in ('preflight','tiny','worker','verifier'):
            selected=self.definition()
            if mutation=='verifier':Path(selected['verifier']['path']).write_text('# changed')
            elif mutation=='worker':
                path=self.root/'worker-result.json';value=json.loads(path.read_text());value['status']='failed';path.write_text(json.dumps(value))
            else:
                value=json.loads(Path(selected[mutation]['path']).read_text())
                if mutation=='preflight':value['plan_sha256']='0'*64
                else:value['passed']=False
                selected[mutation]=self.pin(mutation+'.json',value)
            path=self.pin('selection.json',selected)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                self.q.prepare_batch_definition(path['path'],self.root/'definition.json')
            self.assertFalse((self.root/'definition.json').exists())

    def test_arbitrary_correctly_hashed_verifier_is_not_the_qualified_oracle(self):
        selected=self.definition()
        other=self.root/'other.py';other.write_text('# unrelated verifier')
        selected['verifier']=dict(path=str(other),sha256=hashlib.sha256(other.read_bytes()).hexdigest())
        path=self.pin('selection.json',selected)
        with self.assertRaisesRegex(ValueError,'not the qualified independent oracle'):
            self.q.prepare_batch_definition(path['path'],self.root/'definition.json')

    def test_picker_case_requires_real_output_oracle_and_positive_normal_cleanup(self):
        code=self.root/'oracle.py';code.write_text('# exact oracle')
        digest=hashlib.sha256(code.read_bytes()).hexdigest()
        cfg=dict(schema='chopper-hosted-picker-qualification-v1',case='success',channel='chrome',
            controller_root=r'C:\frozen',qualification_source={'commit':'original'},
            inputs=[dict(path=r'C:\frozen\scripts\hosted_picker\suite.py',sha256=digest)])
        pref=dict(schema=preflight.SCHEMA,status='passed',profile='actual-picker',plan_sha256='config-sha',
            checker={},bindings={},host={'version':'10.0.26300'},worker_receipt_sha256='worker',
            workload_started=False,acceptance_window_started=False,scale_slot_consumed=False)
        oracle=dict(complete=True,rows=2,csvBytes=66,strictCsvCapBytes=40,
            marker=dict(complete=True,engine='chopper-browser',files=3,version=1),
            files={name:dict(bytes=33,sha256='a'*64) for name in ('CHOPPER-COMPLETE.json','manifest.jsonl','part-00000001.csv','part-00000002.csv')})
        report=dict(profile='actual-picker',channel='chrome',case='success',configSha256='config-sha',
            preflight={'path':'pref','sha256':'pref-sha'},tinyCaseQualified=True,scaleAcceptance=False,acceptance=False,
            windowsVersion=[10,0,26300,2,''],privateCleanup=dict(complete=True,errors=[],jobPids=[2],reaped=2,
            eof=dict(browser=dict(stdout=True,stderr=True),uia=dict(stdout=True,stderr=True))),
            reservation={'owner':{'pid':1}},workerBirth={'pid':2},observationComplete=True,
            originalReservationClosedAfterQuiescence=True,parentPipeEOF=dict(stdout=True,stderr=True),
            innerFinal={'pids':[]},outerFinal={'pids':[1]},tinyExportComplete=True,exportOracle=oracle)
        outcome=dict(receipt_sha256='tiny-sha',status='passed',head='original',export_oracle=oracle)
        mapping={'cfg':cfg,'pref':pref,'tiny':report,'outcome':outcome,'worker-result.json':pref}
        proof={key:dict(path=name,sha256=name+'-sha') for key,name in
            [('configuration','cfg'),('preflight','pref'),('tiny','tiny'),('independent','outcome')]}
        proof['configuration']['sha256']='config-sha'
        proof['verifier']=dict(path=str(code),sha256=digest)
        with patch.object(self.q,'_local_binding',side_effect=lambda pin:mapping[pin['path']]):
            self.assertIs(self.q.picker_case(proof,'chrome'),cfg)
            for key in ('originalReservationClosedAfterQuiescence','tinyExportComplete'):
                report[key]=False
                with self.subTest(key=key),self.assertRaises(ValueError):self.q.picker_case(proof,'chrome')
                report[key]=True
            outcome['receipt_sha256']='unrelated'
            with self.assertRaisesRegex(ValueError,'receipt chain mismatch'):self.q.picker_case(proof,'chrome')

    def test_borrowed_fixture_emits_only_metadata_and_keeps_original_identity(self):
        from scale_acceptance import generate
        from scale_acceptance.browser_scale_identity import tiny_fixture
        source=self.root/'old';source.mkdir()
        generate.prepare(source/'D','D','browser',127)
        path=source/'D/input.csv';expected=tiny_fixture('D')
        proof=self.pin('old-tiny.json',dict(schema=self.q.SCHEMA,passed=True,profile='browser-scale',
            details=dict(generated_input_bytes=expected['bytes'],fixture=expected)))
        borrowed=dict(path=str(path),owner_root=str(source),qualification=proof,
            stat=self.q.borrowed_input_stamp(path),bytes=expected['bytes'],sha256=expected['sha256'])
        target=self.root/'new'
        generate.prepare(target,'D','browser',127,borrowed=borrowed)
        self.assertEqual(sorted(p.name for p in target.iterdir()),['fixture.json','job.json'])
        self.assertEqual(json.loads((target/'job.json').read_text())['input'],str(path))
        self.assertEqual(self.q.borrowed_input_stamp(path),borrowed['stat'])
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'drift'):
            generate.prepare(self.root/'denied','D','browser',127,borrowed=borrowed)
        self.assertFalse((self.root/'denied').exists())


if __name__ == '__main__':
    unittest.main()
