"""Read-only adapter controls; no native sessions, locks, Jobs or workloads."""
import copy
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import subprocess
import tempfile
import sys
import types
import unittest
from unittest.mock import Mock, patch

from scale_acceptance import native_preflight as preflight
from scale_acceptance import native_scale_control as control
from scale_acceptance import native_scale_identity as identity
from scale_acceptance.verify import sha256


class Controls(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()

    def plan(self):
        plan = json.loads(Path(__file__).with_name('scale_acceptance').joinpath(
            'native-plan.DISABLED.example.json').read_text())
        source = self.root/'source'
        plan.update(host=dict(os='Linux'), campaign=str(self.root/'campaign'),
            owned_root=str(self.root/'data'),
            owned_roots=[str(self.root/'data'), str(self.root/'campaign')],
            source_reservation=dict(id='source', owner='parent', bytes=1024, roots=[str(source)]),
            reservation=dict(id='host', owner='parent', os='Linux', lock_path=str(self.root/'lock')),
            volumes=[str(self.root)], peers={})
        for role in ('product', 'harness'):
            plan[role] = dict(root=str(source/role), commit=role+'-commit', tree=role+'-tree')
        for role in ('python', 'package', 'executable', 'package_receipt', 'build_proof'):
            plan[role] = dict(path=str(source/role), sha256='a'*64)
        return plan

    def test_windows_scale_declaration_routes_to_existing_preparer_and_denies_missing_parent_before_write(self):
        definition=dict(schema='native-windows-scale-preparation-v1',previous_plan={},previous_preflight={},
            frozen_batch={},namespace='C:/fresh-large',authorization={},continuation={},preflight_limits={},
            retained_source_point={},linux={},peers={},input_root='C:/fresh-bootstrap',claim_parent=dict(python='/private/python',
                python_sha256='a'*64,runner='/frozen/scripts/native-scale-runner.py'),
            preparation_limits=dict(seconds=180,read_bytes=1024**3,visits=1000000,storage_bytes=64*1024**2))
        directory=self.root/'metadata'
        with patch.object(preflight,'prepare_windows_scale',return_value=dict(disabled=True))as prepare:
            self.assertEqual(preflight.prepare_current(definition,directory,Mock()),dict(disabled=True))
            prepare.assert_called_once()
        for field in ('claim_parent','previous_preflight','frozen_batch','retained_source_point'):
            changed=copy.deepcopy(definition);changed.pop(field)
            with patch.object(preflight,'prepare_windows_scale')as prepare:
                with self.assertRaises(ValueError):preflight.prepare_current(changed,directory,Mock())
                prepare.assert_not_called()
            self.assertFalse(directory.exists())

    def test_windows_scale_observation_accepts_only_semantic_default_kind_before_baseline_or_writes(self):
        from scale_acceptance import native_tiny as tiny, hosted_qualification
        def pin(name,value):
            file=self.root/name;file.write_text(json.dumps(value))
            return dict(path=str(file),sha256=sha256(file))
        previous=self.plan()
        previous.update(os='Windows',host=dict(os='Windows'),actions_enabled=True,parent_scheduled=True,
            execution_kind='qualification',python=dict(path=str(Path(sys.executable).resolve()),version=sys.version),
            qualification=dict(namespace=str(self.root/'retained'),windows_history=pin('history.json',{})))
        observed=copy.deepcopy(previous);observed.pop('execution_kind')
        observed.update(actions_enabled=False,parent_scheduled=False)
        input_root=self.root/'inputs';input_root.mkdir();(input_root/'pin.json').write_text('{}')
        declaration=dict(previous_plan=pin('previous.json',previous),previous_preflight=pin('preflight.json',{}),frozen_batch={},
            namespace=str(self.root/'large'),input_root=str(input_root),
            continuation=pin('continuation.json',dict(schema='chopper-unattended-continuation-v1',
                non_time_allowances_renewed=False,launch_cutoff_utc='2099-01-01T00:00:00+00:00',
                deadline_utc='2099-01-02T00:00:00+00:00')))
        for fault in ('none','policy','batch','extra-proof'):
            current=copy.deepcopy(observed)
            if fault=='policy':current['limits']['owned_bytes']+=1
            elif fault=='batch':current['execution_kind']='batch'
            elif fault=='extra-proof':current['frozen_batch']={'sha256':'0'*64}
            point=dict(complete=True,qualification=False,plan=pin('observed.json',current))
            declaration['retained_source_point']=pin('point.json',point)
            destination=self.root/('output-'+fault)
            with patch.object(preflight,'os',types.SimpleNamespace(name='nt')), \
                 patch.object(preflight,'host',return_value=previous['host']), \
                 patch.object(tiny,'preflight'),patch.object(tiny,'reference',return_value={}), \
                 patch.object(tiny,'retained_roots',return_value=set()), \
                 patch.object(hosted_qualification,'qualified_batch',return_value={}), \
                 patch.object(preflight,'observe_baseline',side_effect=RuntimeError('baseline reached')) as baseline:
                with self.assertRaisesRegex(RuntimeError if fault=='none' else ValueError,
                        'baseline reached' if fault=='none' else 'exact previous disabled observation'):
                    preflight.prepare_windows_scale(declaration,destination,Mock())
                self.assertEqual(baseline.call_count,1 if fault=='none' else 0)
            self.assertFalse(destination.exists())
            self.assertFalse(Path(declaration['namespace']).exists())

    def test_disabled_plan_structure_does_not_enable_execution(self):
        plan = self.plan()
        before = copy.deepcopy(plan)
        control.validate_preparation(plan)
        self.assertEqual(plan, before)
        with self.assertRaisesRegex(ValueError, 'actions disabled'):
            control.validate(plan)

    def packet_definition(self):
        plan = self.plan()
        selected_os='Windows' if os.name=='nt' else 'Linux'
        plan.update(os=selected_os,host={**plan['host'],'os':selected_os},
                    reservation={**plan['reservation'],'os':selected_os})
        namespace = self.root/'tiny'
        plan.update(actions_enabled=False, parent_scheduled=False, dependencies=[],
            qualification=dict(namespace=str(namespace), metadata_per_process=dict(read_bytes=1024**2, visits=10000)), owned_root=str(namespace/'data'),
            campaign=str(namespace/'campaign'),
            owned_roots=[str(namespace/'data'), str(namespace/'campaign')])
        for role in ('product', 'harness'):
            plan[role].update(git_blobs={}, sha256={})
        plan_file, authority = self.root/'disabled.json', self.root/'authority.json'
        plan_file.write_text(json.dumps(plan))
        authority.write_text('{"scope":"test-only; no execution"}')
        return dict(schema='native-tiny-preparation-v1',
            plan=dict(path=str(plan_file), sha256=sha256(plan_file)),
            authorization=dict(path=str(authority), sha256=sha256(authority)),
            preflight_limits=dict(seconds=60, read_bytes=1024**2, visits=10000,
                storage_bytes=1024**2, capture_bytes=65536)), plan

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux preparation')
    def test_linux_preparation_derives_fresh_attempt_preserving_inventory_caps_and_history(self):
        from scale_acceptance import native_tiny as tiny
        original, previous = self.packet_definition()
        lock = Path(previous['reservation']['lock_path']);lock.write_bytes(b'')
        continuation = self.root/'continuation.json'
        continuation.write_text(json.dumps(dict(schema='chopper-unattended-continuation-v1',
            non_time_allowances_renewed=False,launch_cutoff_utc='2099-01-01T00:00:00+00:00',
            deadline_utc='2099-01-02T00:00:00+00:00')))
        harness = dict(previous['harness'], root=str(Path(preflight.__file__).resolve().parents[2]))
        declaration = dict(schema='native-tiny-linux-preparation-v1',previous_plan=original['plan'],
            harness={key:harness[key] for key in ('root','commit')},namespace=str(self.root/'new-tiny'),
            authorization=original['authorization'],continuation=dict(path=str(continuation),sha256=sha256(continuation)),
            preparation_limits=dict(seconds=60,read_bytes=1024**2,visits=10000,storage_bytes=1024**2),
            preflight_limits=original['preflight_limits'])
        declaration['metadata_per_process'] = dict(read_bytes=512*1024,visits=5000)
        scale = copy.deepcopy(previous);scale.pop('qualification')
        directory=self.root/'prepared'
        with patch.object(tiny,'validate',return_value=scale), \
             patch.object(preflight,'observe_source',return_value=harness), \
             patch.object(preflight,'validate_preparation'),patch.object(preflight,'source_map'), \
             patch.object(preflight,'preparation_inputs',return_value=[original['authorization']['path']]):
            result=preflight.prepare_current(declaration,directory,Mock())
        packet=json.loads(Path(result['packet']).read_text())
        operator=json.loads((directory/'operator.json').read_text())
        derived=json.loads(Path(operator['disabled_plan']['path']).read_text())
        reference=json.loads(Path(derived['qualification']['scale_plan']['path']).read_text())
        for key in ('product','dependencies','python','tools','limits','package','executable','build_proof'):
            self.assertEqual(derived.get(key),previous.get(key),key)
        self.assertEqual(derived['source_reservation']['bytes'],previous['source_reservation']['bytes'])
        self.assertTrue(set(previous['owned_roots']) <= set(derived['owned_roots']))
        self.assertTrue(set(previous['source_reservation']['roots']) <= set(derived['source_reservation']['roots']))
        self.assertEqual(derived['qualification']['metadata_per_process'],declaration['metadata_per_process'])
        self.assertEqual(operator['metadata_grant']['total_read_bytes'],25*512*1024)
        invalid = dict(declaration, metadata_per_process=dict(read_bytes=1024**2+1,visits=5000))
        with patch.object(tiny,'validate',return_value=scale):
            with self.assertRaisesRegex(ValueError,'must not increase'):
                preflight.prepare_current(invalid,self.root/'upward-denied',Mock())
        self.assertFalse((self.root/'upward-denied').exists())
        self.assertFalse((self.root/'upward-denied-inputs').exists())
        self.assertEqual(reference['harness'],harness)
        self.assertEqual(derived['source_reservation'],reference['source_reservation'])
        self.assertEqual(derived['qualification']['namespace'],declaration['namespace'])
        self.assertFalse(Path(declaration['namespace']).exists())
        self.assertFalse(derived['actions_enabled'])
        self.assertEqual(packet['commands']['supervise'][-1],'--execute')

    def test_linux_declaration_rejects_missing_fields_and_nonfinite_preparation_budget(self):
        declaration=dict(schema='native-tiny-linux-preparation-v1')
        with self.assertRaisesRegex(ValueError,'complete Linux'):
            preflight.validate_definition(declaration)
        declaration.update(previous_plan={},harness=dict(root='source',commit='commit'),namespace='fresh',
            authorization={},continuation={},preflight_limits={},
            preparation_limits=dict(seconds=float('inf'),read_bytes=1,visits=1,storage_bytes=1))
        with self.assertRaisesRegex(ValueError,'finite preparation'):
            preflight.validate_definition(declaration)
        declaration['preparation_limits']['seconds']=60
        declaration['execution_kind']='batch'
        with self.assertRaisesRegex(ValueError,'batch requires'):
            preflight.validate_definition(declaration)

    def test_packet_output_shortfall_denies_before_writing_a_record(self):
        definition,plan=self.packet_definition()
        directory=self.root/'short-output'
        with patch.object(preflight,'validate_preparation'),patch.object(preflight,'source_map'), \
             patch.object(preflight,'preparation_inputs',return_value=[definition['authorization']['path']]):
            with self.assertRaisesRegex(ValueError,'output ceiling before write'):
                preflight.prepare_packet(definition,directory,Mock(),output_limit=1)
        self.assertEqual(list(directory.iterdir()),[])
        self.assertFalse(Path(plan['qualification']['namespace']).exists())

    def test_packet_derives_paths_commands_and_complete_closure_without_launch(self):
        definition, plan = self.packet_definition()
        directory = self.root/'prepared'
        # Schema validation has its own owning controls; these exercise derivation.
        with patch.object(preflight, 'validate_preparation') as validate, \
             patch.object(preflight, 'preparation_inputs', return_value=[definition['authorization']['path']]), \
             patch.object(preflight, 'source_map') as source, \
             patch.object(control, 'Campaign') as campaign:
            result = preflight.prepare_packet(definition, directory, Mock())
        packet = json.loads(Path(result['packet']).read_text())
        self.assertFalse(result['actions_enabled'])
        self.assertFalse(packet['parent_scheduled'])
        self.assertEqual(packet['paths']['plan'], str(self.root/'tiny/tiny-plan.json'))
        self.assertEqual(packet['paths']['request'], str(self.root/'tiny/request.json'))
        self.assertEqual(packet['preparation_inputs'][definition['authorization']['path']]['sha256'],
                         definition['authorization']['sha256'])
        self.assertFalse((self.root/'tiny').exists())
        operator = json.loads((directory/'operator.json').read_text())
        self.assertEqual(operator['namespace'], packet['namespace'])
        self.assertEqual(operator['disabled_plan'], definition['plan'])
        self.assertEqual(packet['commands']['supervise'][-2], sha256(directory/'operator.json'))
        self.assertEqual(packet['commands']['supervise'][-1], '--execute')
        self.assertEqual(packet['commands']['after_exit'][-1], sha256(directory/'operator.json'))
        self.assertFalse(any(arg.startswith('@') for argv in packet['commands'].values() for arg in argv))
        self.assertEqual(operator['source_maps']['sha256'], sha256(directory/'source-maps.json'))
        validate.assert_called_once_with(plan)
        campaign.assert_not_called()

    def test_packet_owning_validation_denies_before_creating_output(self):
        definition, plan = self.packet_definition()
        plan['limits']['owned_bytes'] += 1
        Path(definition['plan']['path']).write_text(json.dumps(plan))
        definition['plan']['sha256'] = sha256(definition['plan']['path'])
        with self.assertRaises(ValueError):
            preflight.prepare_packet(definition, self.root/'prepared', Mock())
        self.assertFalse((self.root/'prepared').exists())

    def test_attempt_commands_use_fresh_leaf_not_retained_namespace_parent(self):
        plan = dict(owned_root='C:/retained/full-r10/data', campaign='C:/retained/full-r10/campaign',
                    qualification=dict(namespace='C:/retained'))
        self.assertEqual(preflight.attempt_root(plan, PureWindowsPath), PureWindowsPath('C:/retained/full-r10'))
        plan['campaign'] = 'C:/retained/full-r9/campaign'
        with self.assertRaises(ValueError):
            preflight.attempt_root(plan, PureWindowsPath)

    def test_packet_rejects_output_overlap_collision_and_invalid_authority(self):
        for kind in ('source', 'namespace', 'existing', 'pin'):
            with self.subTest(kind=kind):
                definition, plan = self.packet_definition()
                directory = self.root/'prepared'
                if kind == 'source':
                    directory = Path(plan['harness']['root'])/'packet'
                elif kind == 'namespace':
                    directory = self.root/'tiny/preflight'
                elif kind == 'existing':
                    directory.mkdir(exist_ok=True)
                else:
                    definition['authorization']['sha256'] = '0'*64
                with patch.object(preflight, 'validate_preparation'), \
                     patch.object(preflight, 'preparation_inputs') as inputs, \
                     self.assertRaises(ValueError):
                    preflight.prepare_packet(definition, directory, Mock())
                inputs.assert_not_called()

    def test_packet_budget_failure_preserves_no_output(self):
        definition, _ = self.packet_definition()
        meter = Mock()
        meter.check.side_effect = ValueError('declared preparation budget')
        with self.assertRaisesRegex(ValueError, 'declared preparation budget'):
            preflight.prepare_packet(definition, self.root/'prepared', meter)
        self.assertFalse((self.root/'prepared').exists())

    def test_observed_baseline_roundtrips_owning_storage_and_denies_drift(self):
        from scale_acceptance.native_scale_monitor import Storage
        source = self.root/'retained'
        (source/'nested').mkdir(parents=True)
        (source/'nested/a').write_bytes(b'original')
        observed = preflight.observe_baseline([source], Mock())
        self.assertEqual([item['path'] for item in observed['roots']], [str(source)])
        self.assertEqual(len(observed['entries']), 1)
        self.assertEqual(len(observed['entries'][0]['stat']), 9)
        prior = dict(sum_bytes=observed['sum_bytes'], entry_count=1,
            carry_bytes=observed['sum_bytes'], prior_sampled_aggregate_highwater_bytes=observed['sum_bytes'])
        Storage(observed, prior)
        (source/'nested/a').write_bytes(b'changed body')
        with self.assertRaises(ValueError):
            Storage(observed, prior)

    @unittest.skipIf(os.name == 'nt', 'symlink fixture requires Linux; Windows reparse controls are native')
    def test_baseline_rejects_skipped_directory_link_and_nested_roots(self):
        source = self.root/'retained'
        source.mkdir()
        (source/'link').symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'nonsymlink'):
            preflight.observe_baseline([source], Mock())
        with self.assertRaisesRegex(ValueError, 'overlapping'):
            preflight.observe_baseline([source, source/'nested'], Mock())

    @unittest.skipUnless(shutil.which('git'), 'Git unavailable')
    def test_source_observation_derives_git_blobs_and_detects_dirty_body(self):
        source = self.root/'git'
        source.mkdir()
        def git(*argv):
            return subprocess.check_output(['git', '-C', str(source), *argv], timeout=5).decode().strip()
        git('init', '--quiet')
        git('config','core.autocrlf','false')
        (source/'fixture').write_bytes(b'complete selected file\n')
        git('add', 'fixture')
        git('-c', 'user.name=control', '-c', 'user.email=control@example.invalid',
            'commit', '--quiet', '-m', 'fixture')
        commit = git('rev-parse', 'HEAD')
        with patch.object(identity, 'REQUIRED', {'fixture'}):
            observed = preflight.observe_source(source, commit, Mock())
            self.assertEqual(observed['sha256'], {'fixture': sha256(source/'fixture')})
            self.assertEqual(set(observed['git_blobs']), {'fixture'})
            (source/'fixture').write_bytes(b'changed\n')
            with self.assertRaisesRegex(ValueError, 'dirty'):
                preflight.observe_source(source, commit, Mock())

    @unittest.skipIf(os.name=='nt','actual source staging is Linux/WSL-only; native route rejects it')
    @unittest.skipUnless(shutil.which('git'), 'Git unavailable')
    def test_actual_stage_fetch_checkout_has_complete_independent_objects_and_clean_nonzero(self):
        donor = self.root/'donor'
        donor.mkdir()
        def git(*args):
            return subprocess.check_output(['git','-C',str(donor),*args],timeout=5).decode().strip()
        git('init','--quiet')
        (donor/'fixture').write_text('selected complete blob\n')
        git('add','fixture')
        git('-c','user.name=control','-c','user.email=control@example.invalid','commit','--quiet','-m','fixture')
        commit = git('rev-parse','HEAD')
        budget = Mock(remaining_seconds=30)
        destination = self.root/'fresh'
        receipts = preflight.stage_checkout(donor,destination,commit,budget,maximum_bytes=1024**2)
        self.assertEqual((destination/'fixture').read_bytes(),(donor/'fixture').read_bytes())
        self.assertTrue(all(row['eof_reaped'] and row['process_group_absent'] for row in receipts))
        self.assertFalse((destination/'.git/objects/info/alternates').exists())
        with self.assertRaisesRegex(ValueError,'fresh checkout'):
            preflight.stage_checkout(donor,destination,commit,budget,maximum_bytes=1024**2)
        with self.assertRaisesRegex(ValueError,'Git command failed'):
            preflight.stage_checkout(donor,self.root/'failed-stage','0'*40,budget,maximum_bytes=1024**2)

    def test_authority_clocks_reject_implicit_timezone_cap_reset_and_reversed_window(self):
        value = dict(schema='chopper-unattended-continuation-v1',non_time_allowances_renewed=False,
            launch_cutoff_utc='2026-11-14T03:31:25+00:00',deadline_utc='2026-11-14T04:31:25+00:00')
        cutoff,stop = preflight.authority_clocks(value)
        self.assertEqual(stop-cutoff,3600)
        for mutation in (dict(non_time_allowances_renewed=True),dict(deadline_utc=value['launch_cutoff_utc']),
                         dict(launch_cutoff_utc='2026-11-14T03:31:25')):
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                preflight.authority_clocks(dict(value,**mutation))

    def test_lifecycle_capture_failure_before_actor_construction_exits_failed_without_retention(self):
        from scale_acceptance import native_scale_host as host
        source = self.root/'source'
        source.mkdir()
        directory = self.root/'evidence'
        directory.mkdir()
        original = Path.open
        def opening(current,*args,**kwargs):
            if current.name == 'lifecycle-stdout.log':raise OSError('capture denied before actor')
            return original(current,*args,**kwargs)
        with patch.object(host,'module',return_value=Mock()), \
             patch.object(host.windows_bootstrap,'SuspendedWorker') as actor, \
             patch.object(Path,'open',opening), \
             patch('time.sleep',side_effect=AssertionError('unstarted actor retained')):
            with self.assertRaisesRegex(OSError,'capture denied before actor'):
                preflight.lifecycle_check(dict(harness=dict(root=str(source/'harness')),attempt='fresh'),
                    dict(source_reservation=dict(roots=[str(source)])),directory,Mock())
        actor.assert_not_called()
        failure = json.loads((directory/'lifecycle-failed.json').read_text())
        self.assertTrue(failure['actor_closed'])
        self.assertTrue(failure['keeper_scope_closed'])
        self.assertFalse(failure['ownership_uncertain'])

    def test_retained_refinement_resolves_only_declared_byte_identical_local_pin_before_writes(self):
        for fault in ('none','missing','wrong-sha','wrong-root'):
            root=self.root/fault;root.mkdir();q=6291456000
            def pin(name,value):
                file=root/(name+'.json');file.write_text(json.dumps(value))
                return dict(path=str(file),sha256=sha256(file))
            refinement=dict(schema='native-preparation-reservation-refinement-v1',
                root='C:/wrong-owner' if fault=='wrong-root' else 'C:/old-preparation',
                previous_reserved_bytes=64*1024**2,reserved_bytes=80*1024**2,source_q_bytes=q)
            body_pin=pin('actual-local-refinement',refinement)
            historical=dict(path='/historical/linux-only/refinement.json',sha256=body_pin['sha256'])
            local=dict(path='C:/bootstrap/current-refinement.json',sha256=body_pin['sha256'])
            preparation=pin('immutable-old-preparation',dict(source_q_bytes=q,
                preparation_limits=dict(storage_bytes=64*1024**2),preparation_reservation_updates=[historical]))
            stage=pin('immutable-old-stage',dict(schema='native-tiny-stage-v1',output='C:/old-preparation',
                destination='C:/retained-source/h1',limits=dict(output_bytes=4*1024**2,source_bytes=64*1024**2),
                preparation=preparation))
            manifest=pin('immutable-old-manifest',dict(preparation=preparation,stage=stage))
            record=dict(manifest=manifest,stage=stage,preparation=preparation)
            original=Path(preparation['path']).read_bytes()
            def native_load(item):
                if item['path']==historical['path']:
                    raise ValueError('historical Linux path is not a native absolute path')
                file=Path(body_pin['path']) if item['path']==local['path'] else Path(item['path'])
                before=file.stat();raw=file.read_bytes();after=file.stat()
                self.assertEqual((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns),
                    (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns))
                self.assertEqual(sha256(file),item['sha256'])
                return json.loads(raw)
            aliases=[] if fault=='missing' else [dict(local,sha256='0'*64) if fault=='wrong-sha' else local]
            with patch.object(control,'create',side_effect=AssertionError('admission must not write C records')) as create, \
                 patch.object(preflight,'stage_checkout',side_effect=AssertionError('admission must not stage source')) as checkout:
                if fault=='none':
                    rows,staged=preflight.retained_preparation_reservations([record,record],native_load,q,
                        local_refinement_pins=aliases)
                    self.assertEqual(sum(row['reserved_bytes'] for row in rows),84*1024**2)
                    self.assertEqual(staged,64*1024**2)
                    self.assertEqual(next(row['reserved_bytes'] for row in rows if
                        PureWindowsPath(row['root'])==PureWindowsPath('C:/old-preparation')),80*1024**2)
                else:
                    with self.assertRaises(ValueError):
                        preflight.retained_preparation_reservations([record],native_load,q,local_refinement_pins=aliases)
                create.assert_not_called();checkout.assert_not_called()
            self.assertEqual(Path(preparation['path']).read_bytes(),original)
            self.assertEqual(json.loads(original)['preparation_reservation_updates'],[historical])

    def test_failed_preparation_envelopes_survive_missing_observation_point(self):
        manifest = dict(stage=dict(sha256='a'*64),preparation=dict(sha256='b'*64))
        stage = dict(schema='native-tiny-stage-v1',output='C:/old-data',
                     preparation=dict(sha256='b'*64),limits=dict(output_bytes=4*1024**2,source_bytes=64*1024**2))
        definition = dict(source_q_bytes=1000,preparation_limits=dict(storage_bytes=64*1024**2))
        values = dict(manifest=manifest,stage=stage,preparation=definition)
        records = [{key:dict(path=key,sha256={'manifest':'c','stage':'a','preparation':'b'}[key]*64)
                    for key in values}]
        rows,staged = preflight.retained_preparation_reservations(records,lambda pin:values[pin['path']],1000)
        self.assertEqual(staged,64*1024**2)
        self.assertEqual(2_781_755_392+160_679_200+134_217_728+staged+
            sum(row['reserved_bytes'] for row in rows)+64*1024**2+68*1024**2,3_353_476_384)
        self.assertEqual(sum(row['reserved_bytes'] for row in rows),68*1024**2)
        self.assertEqual(rows[1]['root'],'C:\\old-data-inputs')
        _,total,new = preflight.preparation_reservations([],rows,['C:/source'])
        first = preflight.source_admission_bound(100,100,0,total,new)
        self.assertEqual(first,100+68*1024**2)
        # Once in the retained point, it is not a newly admitted envelope again.
        _,total,new = preflight.preparation_reservations(rows,[],['C:/source'])
        self.assertEqual(preflight.source_admission_bound(100,first,0,total,new),first)
        manifest['stage']['sha256'] = 'd'*64
        with self.assertRaisesRegex(ValueError,'manifest/declaration binding'):
            preflight.retained_preparation_reservations(records,lambda pin:values[pin['path']],1000)

    def test_explicit_current_tool_selection_keeps_roles_and_pins_body(self):
        old = [dict(path='C:\\Git\\git.exe',sha256='a'*64)]
        current = [dict(path=old[0]['path'],sha256='b'*64)]
        pin = Mock(return_value=current[0])
        self.assertEqual(preflight.selected_tools(old,current,pin),current)
        pin.assert_called_once_with(old[0]['path'])
        with self.assertRaisesRegex(ValueError,'current tool bytes changed'):
            preflight.selected_tools(old,current,lambda name:old[0])
        with self.assertRaisesRegex(ValueError,'role/path set'):
            preflight.selected_tools(old,[dict(path='C:\\other.exe',sha256='b'*64)],pin)
        with self.assertRaisesRegex(ValueError,'role/path set'):
            preflight.selected_tools(old,current*2,pin)

    def test_preparation_data_destination_and_carried_reservation(self):
        observed = self.root/'observed'
        observed.mkdir()
        with self.assertRaisesRegex(ValueError,'fresh separate bootstrap DATA'):
            preflight.preparation_destination(observed/'old-output',[observed])
        output = self.root/'fresh-output'
        bootstrap = preflight.preparation_destination(output,[observed])
        bootstrap.mkdir()
        preflight.preparation_destination(output,[observed],staged_bootstrap=True)
        rows = [dict(root='C:/prep-old',reserved_bytes=68)]
        current = [dict(root='C:/prep-new',reserved_bytes=68)]
        carried,total,new = preflight.preparation_reservations(rows,current,['C:/source'])
        self.assertEqual((total,new),(136,68))
        self.assertEqual(preflight.source_admission_bound(100,168,0,total,new),236)
        # Advancing the point and moving DATA never refunds or re-adds old rows.
        newest = [dict(root='C:/prep-next',reserved_bytes=68)]
        _,total,new = preflight.preparation_reservations(carried,newest,['C:/source'])
        self.assertEqual(preflight.source_admission_bound(90,236,0,total,new),304)
        self.assertEqual(preflight.source_admission_bound(500,236,0,total,new),704)
        _,total,new=preflight.preparation_reservations(carried,rows,['C:/source'])
        self.assertEqual((total,new),(136,0))
        with self.assertRaisesRegex(ValueError,'disjoint preparation'):
            preflight.preparation_reservations([], [dict(root='C:/source/data',reserved_bytes=68)], ['C:/source'])

    def test_same_preparation_reservation_refinement_is_monotone_and_counted_once(self):
        old=[dict(root='C:/prep',reserved_bytes=64)]
        active=[dict(root='C:/prep',reserved_bytes=80)]
        rows,total,delta=preflight.preparation_reservations(old,active,['C:/source'])
        self.assertEqual((total,delta),(80,16))
        for history in ([*old,*rows,*old],[*rows,*old,*rows]):
            merged,total,delta=preflight.preparation_reservations(history,active,['C:/source'])
            self.assertEqual((total,delta),(80,0))
            self.assertEqual(len(merged),1)
        with self.assertRaisesRegex(ValueError,'decreased'):
            preflight.preparation_reservations(rows,old,['C:/source'])
        with self.assertRaisesRegex(ValueError,'disjoint'):
            preflight.preparation_reservations(rows,[dict(root='C:/prep/nested',reserved_bytes=1)],['C:/source'])

    def test_preparation_refinement_requires_pinned_existing_owner_and_q(self):
        from scale_acceptance.native_tiny import pinned_json
        file=self.root/'refinement.json'
        value=dict(schema='native-preparation-reservation-refinement-v1',root='C:/prep',
                   previous_reserved_bytes=64,reserved_bytes=80,source_q_bytes=1000)
        file.write_text(json.dumps(value));pin=dict(path=str(file),sha256=sha256(file))
        definition=dict(source_q_bytes=1000,preparation_reservation_updates=[pin])
        load=lambda item:pinned_json(item,1024**2)[0]
        known=[dict(root='C:/prep',reserved_bytes=64)]
        rows=preflight.preparation_reservation_updates(definition,load,known)
        self.assertEqual(rows,[dict(root='C:\\prep',reserved_bytes=80)])
        with self.assertRaisesRegex(ValueError,'hash/size'):
            preflight.preparation_reservation_updates(dict(definition,preparation_reservation_updates=[dict(pin,sha256='0'*64)]),load,known)
        for changes in (dict(root='C:/wrong'),dict(reserved_bytes=63),dict(reserved_bytes=1001),dict(source_q_bytes=999)):
            file.write_text(json.dumps(dict(value,**changes)));pin['sha256']=sha256(file)
            with self.assertRaises(ValueError):preflight.preparation_reservation_updates(definition,load,known)

    def test_historical_refinement_refs_are_order_independent_and_keep_all_provenance(self):
        source_q=20*1024**2
        values={}
        def save(name,value):
            values[name]=value
            return dict(path=name,sha256={'old':'a','new':'b'}.get(name,'c')*64)
        refinement=save('update',dict(schema='native-preparation-reservation-refinement-v1',root='C:/prep',
            previous_reserved_bytes=64,reserved_bytes=80,source_q_bytes=source_q))
        records=[]
        for name,updates in (('old',[]),('new',[refinement])):
            prep=save(name+'prep',dict(source_q_bytes=source_q,preparation_limits=dict(storage_bytes=64),
                preparation_reservation_updates=updates))
            stage=save(name+'stage',dict(schema='native-tiny-stage-v1',destination='C:/source/harness',output='C:/prep',
                preparation=prep,limits=dict(output_bytes=4*1024**2,source_bytes=128)))
            manifest=save(name+'manifest',dict(stage=stage,preparation=prep))
            records.append(dict(manifest=manifest,stage=stage,preparation=prep))
        for refs in (records,records[::-1],records*2):
            rows,staged=preflight.retained_preparation_reservations(refs,lambda item:values[item['path']],source_q)
            self.assertEqual(staged,128)
            self.assertEqual(sum(row['reserved_bytes']for row in rows),80+4*1024**2)
            self.assertEqual(len(rows),2)

    def test_stage_rejects_bootstrap_allowance_above_recorded_envelope_before_reads(self):
        definition = dict(schema='native-tiny-stage-v1',commit='a'*40,destination='C:/source/new',
            preparation=dict(path='/missing/input.json',sha256='b'*64),output='C:/prep-new',
            limits=dict(seconds=60,read_bytes=1024**2,visits=10000,source_bytes=1024**2,
                        output_bytes=4*1024**2+1))
        with patch.object(preflight,'read_json',side_effect=AssertionError('premature read')), \
             patch.object(preflight,'stage_checkout') as checkout:
            denial=('Linux/WSL source stage definition required' if os.name=='nt' else
                    'bootstrap DATA allowance exceeds recorded envelope')
            with self.assertRaisesRegex(ValueError,denial):
                preflight.stage_current(definition,self.root/'receipt.json',Mock())
        checkout.assert_not_called()

    def test_stage_uses_owning_preparation_schema_before_any_git_or_destination_write(self):
        bad = self.root/'missing-required-field.json'
        bad.write_text(json.dumps(dict(schema='native-tiny-preparation-v1')))
        definition = dict(schema='native-tiny-stage-v1',commit='a'*40,destination='C:/source/new',
            preparation=dict(path=str(bad),sha256=sha256(bad)),output='C:/observe/new',
            limits=dict(seconds=60,read_bytes=1024**2,visits=10000,source_bytes=1024**2,output_bytes=1024**2))
        with patch.object(preflight,'stage_checkout') as checkout, \
             patch.object(Path,'mkdir',side_effect=AssertionError('premature destination write')) as mkdir:
            # Windows rejects the WSL-only route before pathname mapping; the
            # same owning schema check is exercised directly on either platform.
            with self.assertRaisesRegex(ValueError,'complete native preparation definition fields'):
                preflight.validate_definition(json.loads(bad.read_text()))
            denial=('Linux/WSL source stage definition required' if os.name=='nt' else
                    'complete native preparation definition fields')
            with self.assertRaisesRegex(ValueError,denial):
                preflight.stage_current(definition,self.root/'receipt.json',Mock())
        checkout.assert_not_called()
        mkdir.assert_not_called()

    def test_preparation_retains_fixed_recipes_and_limits(self):
        for change in ('recipe', 'limit', 'lineage'):
            plan = self.plan()
            if change == 'recipe':
                plan['fixtures']['D']['tiny'] = True
            elif change == 'limit':
                plan['limits']['owned_bytes'] += 1
            else:
                plan['selected639_lineage']['sha256'] = '0'*64
            with self.subTest(change=change), self.assertRaises(ValueError):
                control.validate_preparation(plan)

    def test_native_adapter_uses_full_identity_without_session_authority(self):
        plan = self.plan()
        before = copy.deepcopy(plan)
        budget = Mock()
        with patch.object(preflight, 'host', return_value=plan['host']), \
             patch.object(preflight, 'selected_identity') as identity, \
             patch.object(control, 'Campaign') as campaign, \
             patch.object(control, 'create') as create:
            result = preflight.inspect(plan, budget)
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['runtime_pending'])
        identity.assert_called_once_with(plan)
        identity.return_value.assert_called_once_with(plan)
        identity.return_value.return_value.check.assert_called_once_with()
        campaign.assert_not_called()
        create.assert_not_called()
        self.assertEqual(plan, before)
        self.assertEqual(budget.check.call_count, 2)

    def test_identity_failure_cannot_be_relabelled_passed(self):
        plan = self.plan()
        with patch.object(preflight, 'host', return_value=plan['host']), \
             patch.object(preflight, 'selected_identity', side_effect=ValueError('missing helper')):
            with self.assertRaisesRegex(ValueError, 'missing helper'):
                preflight.inspect(plan, Mock())

    def test_runtime_coverage_failure_names_missing_paths_without_allowing_them(self):
        plan = self.plan()
        plan['dependencies'] = []
        missing = self.root / 'new-runtime-library'
        class Identity:
            def __init__(self, plan):
                raise ValueError('actual Python runtime/dependency coverage missing')
        Identity.__module__ = 'preflight_missing_runtime_control'
        selected = types.SimpleNamespace(runtime_requirements=lambda: ([], {missing}), path=Path)
        with patch.object(preflight, 'host', return_value=plan['host']), \
             patch.object(preflight, 'selected_identity', return_value=Identity), \
             patch.dict(sys.modules, {Identity.__module__: selected}):
            with self.assertRaises(ValueError) as raised:
                preflight.inspect(plan, Mock())
        self.assertIn(json.dumps(str(missing)), str(raised.exception))

    def test_selected_identity_uses_external_harness_and_its_relative_helpers(self):
        directory = self.root/'scripts/scale_acceptance'
        directory.mkdir(parents=True)
        (directory/'helper.py').write_text('value = "selected helper"\n')
        (directory/'native_scale_identity.py').write_text(
            'from .helper import value\nclass Identity:\n'
            '    source = __file__\n    helper = value\n')
        plan = dict(harness=dict(root=str(self.root)))
        with patch.object(preflight, 'source_map', return_value=(self.root, {})) as verify:
            identity = preflight.selected_identity(plan)
        verify.assert_called_once_with(plan['harness'])
        self.assertEqual(Path(identity.source), directory/'native_scale_identity.py')
        self.assertEqual(identity.helper, 'selected helper')

    def test_source_drift_denies_before_selected_definitions_are_loaded(self):
        directory = self.root/'scripts/scale_acceptance'
        directory.mkdir(parents=True)
        (directory/'native_scale_identity.py').write_text('raise AssertionError("must not import")\n')
        with patch.object(preflight, 'source_map', side_effect=ValueError('source drift')):
            with self.assertRaisesRegex(ValueError, 'source drift'):
                preflight.selected_identity(dict(harness=dict(root=str(self.root))))

    def test_wrong_host_denies_before_identity(self):
        plan = self.plan()
        with patch.object(preflight, 'host', return_value={}), \
             patch.object(preflight, 'selected_identity') as identity:
            with self.assertRaisesRegex(ValueError, 'actual native OS/host'):
                preflight.inspect(plan, Mock())
            identity.assert_not_called()

    def test_exhausted_preparation_never_reaches_identity_or_passes(self):
        plan = self.plan()
        for when in ('before', 'after'):
            budget = Mock()
            budget.check.side_effect = ([OSError('preparation deadline')]
                if when == 'before' else [None, OSError('preparation deadline')])
            with self.subTest(when=when), \
                 patch.object(preflight, 'host', return_value=plan['host']), \
                 patch.object(preflight, 'selected_identity') as identity:
                with self.assertRaisesRegex(OSError, 'preparation deadline'):
                    preflight.inspect(plan, budget)
                if when == 'before':
                    identity.assert_not_called()

    def test_windows_admission_remains_blocked_without_identity_or_work(self):
        plan = self.plan()
        plan.update(os='Windows', host={**plan['host'], 'os': 'Windows'},
                    reservation={**plan['reservation'], 'os': 'Windows'},
                    peers={s: dict(slot='Linux'+s, sha256='a'*64,
                        source_sha256='b'*64, plan_sha256='c'*64) for s in ('D', 'G')})
        with patch.object(preflight, 'host', return_value=plan['host']), \
             patch.object(preflight, 'selected_identity') as identity:
            result = preflight.inspect(plan, Mock())
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('Windows admission deferred', result['diagnostics'][0])
        identity.assert_not_called()
        plan['actions_enabled'] = plan['parent_scheduled'] = True
        with self.assertRaisesRegex(ValueError, 'Windows admission deferred'):
            control.validate(plan)

    def test_preparation_components_inherit_point_discover_owned_output_and_deny_bad_evidence(self):
        for fault in ('none','duplicate','missing','wrong-sha','wrong-owner','plan','blob','unclosed','hardlink'):
            root=self.root/fault;root.mkdir()
            def pin(name,value):
                file=root/(name+'.json');file.write_text(json.dumps(value))
                return dict(path=str(file),sha256=sha256(file))
            previous=self.plan();previous['execution_kind']='qualification'
            observed=copy.deepcopy(previous);observed.pop('execution_kind')
            observed.update(actions_enabled=False,parent_scheduled=False)
            if fault=='plan':observed['features']=['unqualified-drift']
            legacy=pin('legacy',dict(passed=True,qualification=False,current_fixture_inventory=[],
                source_growth_envelope=12,parent_positive_logicalEOF_delta=0))
            if fault=='blob':legacy=pin('blob',dict(passed=True,qualification=False))
            inherited=dict(legacy,sha256='0'*64) if fault=='wrong-sha' else legacy
            point=pin('point',dict(complete=True,qualification=False,plan=pin('observed',observed),retained_component_points=[inherited]))
            owner=pin('old-preparation',dict(harness=dict(root='C:/source/harness'),attempt='old'))
            stage=pin('old-stage',dict(output='C:/old-output',preparation=owner))
            folder=root/'output';folder.mkdir();file=folder/'lifecycle.json'
            fixture=PureWindowsPath('C:/source/lifecycle-old')
            value=dict(schema='native-lock-owner-lifecycle-v1',passed=True,qualification=False,cleanup_passed=True,
                original_touched=False,product_runs=0,fixture_byte0_available_unlocked_closed=True,
                normal_owner=dict(path=str(fixture/'fixture.lock')),current_fixture_inventory=[],
                source_growth_envelope=0,parent_positive_logicalEOF_delta=0)
            if fault=='wrong-owner':value['normal_owner']['path']='C:/unrelated/fixture.lock'
            if fault=='unclosed':value['cleanup_passed']=False
            file.write_text(json.dumps(value))
            if fault=='hardlink':os.link(file,folder/'extra-link')
            definition=dict(previous_plan=pin('previous',previous),retained_source_point=point,
                retained_component_points=[legacy,legacy] if fault=='duplicate' else [],
                retained_preparations=[dict(stage=stage,preparation=owner)])
            if fault=='missing':Path(legacy['path']).unlink()
            def load(item):
                local=file if PureWindowsPath(item['path'])==PureWindowsPath('C:/old-output/lifecycle.json') else Path(item['path'])
                require=preflight.require
                require(sha256(local)==item['sha256'],'wrong input SHA: '+item['path'])
                return json.loads(local.read_bytes())
            def resolve(name):
                self.assertEqual(PureWindowsPath(name),PureWindowsPath('C:/old-output/lifecycle.json'))
                return file
            with patch.object(control,'create',side_effect=AssertionError('must derive before C writes')), \
                 patch.object(preflight,'stage_checkout',side_effect=AssertionError('must derive before source staging')):
                if fault in ('none','duplicate'):
                    result=preflight.preparation_components(definition,load,resolve_path=resolve)
                    self.assertEqual({item['sha256'] for item in result},{legacy['sha256'],sha256(file)})
                    self.assertEqual(len(result),2)
                    plan=self.plan();plan['dependencies']=[];plan['tools']=[]
                    for role in ('product','harness'):plan[role]['sha256']={}
                    plan.update(os='Windows',qualification=dict(scale_plan=dict(path='scale-proof',sha256='a'*64),
                        windows_history=dict(path='history-proof',sha256='b'*64)))
                    proof=dict(source_reconciliation=dict(path='reconciliation',sha256='c'*64),runner_receipts=[])
                    with patch.object(preflight,'read_json',side_effect=lambda name,limit:
                            dict(provenance=result) if name=='history-proof' else proof):
                        closure=preflight.preparation_inputs(plan)
                    self.assertTrue({item['path']for item in result}<=set(closure))
                else:
                    with self.assertRaises((ValueError,KeyError,FileNotFoundError)):
                        preflight.preparation_components(definition,load,resolve_path=resolve)
            self.assertFalse((root/'C-output').exists())


if __name__ == '__main__':
    unittest.main()
