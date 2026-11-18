"""Source-only full-scale contract controls. No browsers/products/large fixtures."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
from scale_acceptance.browser_scale_identity import ScaleIdentity, validate_packet, scale_fixture, SOURCE, TREE, ASSETS, PRODUCT_INPUTS, HARNESS_INPUTS
from scale_acceptance.browser_scale_plan import documents, LIMITS, GiB
from scale_acceptance.browser_scale_guard import approval_record, schedule, claim_slot, ScaleGuard, read_quota_journal, finish_scale, record_cleanup
from scale_acceptance.generate import write_new
from scale_acceptance.verify import sha256


class Controls(unittest.TestCase):
    def test_cold_future_reservation_uses_live_channel_union_without_refunding_history(self):
        from scale_acceptance import hosted_qualification as q
        from scale_acceptance.browser_scale_guard import channel_owned_roots, Guard
        tiny,direct,other,claims=[self.root/name for name in ('tiny','D','chrome','claims')]
        for root in (tiny,direct,other,claims):root.mkdir()
        (tiny/'closed').write_bytes(b'tiny');(direct/'closed').write_bytes(b'direct')
        (other/'ignored').write_bytes(b'other channel')
        reservation=dict(claims_root=str(claims),slots=[dict(channel='msedge',directory=str(direct)),
            dict(channel='msedge',directory=str(self.root/'future-G')),dict(channel='chrome',directory=str(other))],
            qualifications=[dict(channel='msedge',directory=str(tiny))])
        before=copy.deepcopy(reservation)
        roots=channel_owned_roots(reservation,'msedge')
        self.assertEqual(roots,[direct,tiny])
        actual=q.browser_scale_future_capacity(reservation,'msedge',[self.root])
        self.assertEqual(actual['current_owned_bytes'],len(b'tiny')+len(b'direct'))
        self.assertEqual(actual['future_bytes'],LIMITS['owned_bytes']-actual['current_owned_bytes'])
        self.assertEqual(reservation,before)
        # The full, already-reconciled historical charge stays in the baseline.
        baseline=32*GiB;metadata=512*1024**2
        self.assertGreater(baseline+LIMITS['owned_bytes']+metadata,56*GiB)
        with patch.object(Guard,'disk_values',return_value=dict(owned=3*GiB,free=[100*GiB])):
            remaining=q.browser_scale_future_capacity(reservation,'msedge',[self.root])
        self.assertEqual(baseline,32*GiB)
        self.assertLess(baseline+remaining['future_bytes']+metadata,56*GiB)
        for value in (-1,True,LIMITS['owned_bytes'],LIMITS['owned_bytes']+1):
            with self.subTest(owned=value),patch.object(Guard,'disk_values',return_value=dict(owned=value,free=[])), \
                    self.assertRaisesRegex(ValueError,'ceiling'):
                q.browser_scale_future_capacity(reservation,'msedge',[self.root])
        with patch.object(Guard,'disk_values',side_effect=OSError('query failed')),self.assertRaisesRegex(OSError,'query failed'):
            q.browser_scale_future_capacity(reservation,'msedge',[self.root])
        with self.assertRaisesRegex(ValueError,'outside reconciled'):
            q.browser_scale_future_capacity(reservation,'msedge',[tiny])
        with self.assertRaisesRegex(ValueError,'missing/overlapping'):
            q.browser_scale_future_capacity(dict(reservation,slots=[],qualifications=[]),'msedge',[self.root])
        for changed in (dict(reservation,slots=reservation['slots']+[reservation['slots'][0]]),
                dict(reservation,qualifications=[dict(channel='msedge',directory=str(direct/'nested'))])):
            (direct/'nested').mkdir(exist_ok=True)
            with self.assertRaisesRegex(ValueError,'overlapping'):
                q.browser_scale_future_capacity(changed,'msedge',[self.root])
        (claims/'active.lock').write_text('owner')
        with self.assertRaisesRegex(ValueError,'active/missing owner'):
            q.browser_scale_future_capacity(reservation,'msedge',[self.root])
        (claims/'active.lock').unlink()
        def owner_appears(*args):
            (claims/'active.lock').write_text('new owner')
            return dict(owned=10,free=[100*GiB])
        with patch.object(Guard,'disk_values',side_effect=owner_appears),self.assertRaisesRegex(ValueError,'owner appeared'):
            q.browser_scale_future_capacity(reservation,'msedge',[self.root])

    def test_live_runtime_and_git_cannot_be_omitted_as_whole_fields(self):
        for field in ('external_runtime','git'):
            packet=copy.deepcopy(self.packet);del packet[field]
            with self.assertRaisesRegex(ValueError,'complete live Git'):validate_packet(packet)

    def test_recorded_windows_syntax_dependencies_are_all_in_the_owning_harness_closure(self):
        from scale_acceptance.guard import load_runner
        observed=json.loads(Path(__file__).with_name('fixtures').joinpath('browser-scale-syntax-windows.json').read_text())
        root=self.root/'recorded-harness';root.mkdir()
        dependencies=set(observed['file_inputs']+[observed['compiler']]+observed['package_files'])
        for name in dependencies:
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'syntax-recorded dependency')
        for name in HARNESS_INPUTS:
            path=root/name
            if name.endswith(('.py','.mjs')):
                path.parent.mkdir(parents=True,exist_ok=True)
                if not path.exists():path.write_bytes(b'required helper')
            else:
                path.mkdir(parents=True,exist_ok=True)
                (path/'required').write_bytes(b'required directory member')
        runner=load_runner()
        def declared(patterns):
            return {Path(name).as_posix() for name,row in runner.identity(root,patterns).items()if not row.get('directory')}
        original_missing=dependencies-declared(sorted(HARNESS_INPUTS-{'scripts'}))
        self.assertEqual(original_missing,set(observed['undeclared_in_original']))
        self.assertEqual(dependencies-declared(sorted(HARNESS_INPUTS)),set())
        packet=copy.deepcopy(self.packet);packet['harness']['inputs'].remove('scripts')
        with self.assertRaisesRegex(ValueError,'full harness/dependency'):validate_packet(packet)

    def test_original_and_job_helpers_are_mandatory_runtime_inputs(self):
        for name in ('scripts/local-ci.py','scripts/browser-small-windows.py'):
            packet=copy.deepcopy(self.packet)
            packet['harness']['inputs'].remove(name)
            with self.assertRaisesRegex(ValueError,'full harness/dependency inputs'):
                validate_packet(packet)

    def test_frozen_metadata_rejects_reparse_before_walk_descends(self):
        from scale_acceptance import guard
        base=self.root/'runtime';base.mkdir();junction=base/'junction';junction.mkdir()
        original=Path.lstat
        def tagged(path,*args,**kwargs):
            value=original(path,*args,**kwargs)
            if path!=junction:return value
            return SimpleNamespace(**{name:getattr(value,name) for name in
                ('st_mode','st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink')},st_file_attributes=0x400)
        def walk(*args,**kwargs):
            yield str(base),['junction'],[]
            self.fail('walk descended before rejecting the reparse entry')
        with patch.object(Path,'lstat',tagged),patch.object(guard.os,'walk',side_effect=walk):
            with self.assertRaisesRegex(ValueError,'plain regular'):
                guard.frozen_metadata(self.root,['runtime'])

    def test_frozen_metadata_preserves_known_links_and_rejects_reparse_attributes(self):
        from scale_acceptance.guard import frozen_metadata
        base=self.root/'metadata';base.mkdir();path=base/'file';path.write_bytes(b'bytes')
        os.link(path,self.root/'known-link')
        before=frozen_metadata(base,['file'])
        self.assertEqual(before['file'][-2],2)  # Known borrowed links are valid.
        os.link(path,self.root/'new-link')
        self.assertNotEqual(frozen_metadata(base,['file']),before)
        original=Path.lstat
        def tagged(item,*args,**kwargs):
            value=original(item,*args,**kwargs)
            if item!=path:return value
            return SimpleNamespace(**{name:getattr(value,name)for name in
                ('st_mode','st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink')},st_file_attributes=0x400)
        with patch.object(Path,'lstat',tagged):
            with self.assertRaisesRegex(ValueError,'plain regular'):frozen_metadata(base,['file'])

    def ownership_fixture(self):
        ownership=dict(processes=[],launch_pending=False,runner_active=False,handle_uncertain=False)
        thread=lambda:SimpleNamespace(is_alive=lambda:False)
        watchdog=SimpleNamespace(done=Mock(),stop=Mock(),sampler=thread(),monitor=thread(),
            error=None,failure=None,termination_error=None,launch_uncertain=False)
        disk=SimpleNamespace(thread=object(),after=Mock(),stop=Mock(),pending=False)
        kernel=SimpleNamespace(GetProcessId=lambda handle:7,WaitForSingleObject=lambda handle,timeout:0)
        windows=SimpleNamespace(kernel=lambda:kernel,_held_birth=lambda *args:42,
            query_job=Mock(return_value=dict(kill_on_close=True,pids=[os.getpid()])))
        return ownership,windows,watchdog,disk

    def test_completed_denial_and_constructor_failure_release_only_after_quiescence(self):
        ownership,windows,watchdog,disk=self.ownership_fixture()
        ownership['launch_pending']=True  # synchronous constructor already unwound
        disk.after.side_effect=ValueError('capacity below floor')
        stopped=Mock()
        report=finish_scale(ownership,windows,1,watchdog,disk,[],stopped)
        self.assertTrue(report['original_release_safe']);self.assertTrue(report['errors'])
        stopped.assert_called_once();disk.stop.assert_called_once();watchdog.stop.assert_called_once()
        for pending in ('runner_active','handle_uncertain'):
            ownership[pending]=True
            self.assertFalse(finish_scale(ownership,windows,1,watchdog,disk,[],stopped)['original_release_safe'])
            ownership[pending]=False
        windows.query_job.return_value=dict(kill_on_close=True,pids=[os.getpid(),7])
        self.assertFalse(finish_scale(ownership,windows,1,watchdog,disk,[],stopped)['original_release_safe'])

    def test_wait_and_close_failures_still_stop_samplers_and_retain(self):
        for phase in ('wait','close'):
            ownership,windows,watchdog,disk=self.ownership_fixture()
            handle=SimpleNamespace(Close=Mock())
            process=SimpleNamespace(_handle=handle,wait=Mock(return_value=0))
            if phase=='wait':process.wait.side_effect=TimeoutError('wait unknown')
            else:handle.Close.side_effect=OSError('close unknown')
            ownership['processes']=[dict(process=process,pid=7,created=42,closed=False,close_attempted=False)]
            report=finish_scale(ownership,windows,1,watchdog,disk,[],Mock())
            self.assertFalse(report['original_release_safe'])
            disk.stop.assert_called_once();watchdog.stop.assert_called_once()
            if phase=='wait':handle.Close.assert_not_called()
            else:self.assertTrue(report['processes'][0]['close_attempted'])

    def test_watchdog_termination_error_stays_uncertain_after_later_empty_census(self):
        from scale_acceptance.browser_scale_watchdog import Watchdog
        original=ValueError('completed guard denial');cleanup=OSError('checked close failed')
        monitor=Watchdog(lambda:None,self.root/'watch-failure.json',terminate=Mock(side_effect=cleanup))
        monitor.fail(original)
        self.assertIs(monitor.error,original);self.assertIs(monitor.termination_error,cleanup)
        ownership,windows,_,disk=self.ownership_fixture()
        report=finish_scale(ownership,windows,1,monitor,disk,[],Mock())
        self.assertFalse(report['original_release_safe'])
        self.assertIn('checked close failed',report['termination_error']['error'])
        disk.stop.assert_called_once()

    def test_late_watchdog_error_latches_during_join_still_retain(self):
        for field in ('error','termination_error'):
            ownership,windows,watchdog,disk=self.ownership_fixture()
            error=OSError('late checked close')
            if field=='error':error.process_handle_close_uncertain=True
            watchdog.stop.side_effect=lambda:setattr(watchdog,field,error)
            report=finish_scale(ownership,windows,1,watchdog,disk,[],Mock())
            self.assertFalse(report['original_release_safe'])

    def test_receipt_error_is_failed_but_closed_unless_close_is_uncertain(self):
        from scale_acceptance.native_scale_host import module
        local=module('local-ci');lock=self.root/'private-original.lock'
        class Retained(BaseException):pass
        for uncertain in (False,True):
            error=OSError('injected completed evidence failure')
            if uncertain:error.process_handle_close_uncertain=True
            ownership=dict(handle_uncertain=False)
            runner=SimpleNamespace(write_json=Mock(side_effect=error))
            with patch.object(local,'host_lock_path',return_value=lock),local.host_lock():
                stamp=lock.stat()
                def retained(*args):
                    with self.assertRaises(ValueError):
                        with local.host_lock():pass
                    raise Retained()
                with patch('scale_acceptance.browser_scale_guard.retain_original',side_effect=retained) as keep:
                    action=lambda:record_cleanup(runner,self.root,dict(original_release_safe=True),ownership,{},lock,stamp,1)
                    if uncertain:
                        with self.assertRaises(Retained):action()
                        keep.assert_called_once()
                    else:action();keep.assert_not_called()
                with self.assertRaises(ValueError):
                    with local.host_lock():pass
            with patch.object(local,'host_lock_path',return_value=lock),local.host_lock():pass
            self.assertTrue(ownership['receipt_error'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.packet = self.fake_packet()

    def tearDown(self):
        self.temp.cleanup()

    def fake_packet(self):
        # Syntactically complete synthetic identities, NEVER admitted as acceptance.
        group = lambda inputs, names: dict(root=str(self.root), inputs=list(inputs), sha256={n: 'a' * 64 for n in names})
        p=dict(version=1, runtime='browser', mode='scale', features=[], parent_scheduled=True,
            source=dict(commit=SOURCE, tree=TREE, clean=True), harness_source=dict(commit=SOURCE, tree=TREE, clean=True), channel='chrome', shape='D',
            host=dict(os='Windows', release='11', version='synthetic', machine='AMD64', node='synthetic'),
            package=dict(path='package.zip', sha256='a' * 64), build_receipts=['build.json'],
            toolchains=dict(python_version=sys.version, node_version='synthetic', esbuild_version='synthetic'), storage=dict(volume='synthetic'), browser_version='synthetic',
            origin='http://127.0.0.1:8427', profile=str(self.root / 'work/profile'), plan_id='synthetic-D-chrome',
            product=group(PRODUCT_INPUTS, ['Cargo.toml']), harness=group(HARNESS_INPUTS, ['bridge.js', 'bridge.json']),
            assets=group(['*'], ASSETS), evidence=group(['package.zip', 'build.json'], ['package.zip', 'build.json']),
            bundle='bridge.js', bundle_provenance='bridge.json',
            browser=dict(path=str(self.root / 'browser'), sha256='a' * 64),
            node=dict(path=str(self.root / 'node'), sha256='a' * 64),
            python=dict(path=str(self.root / 'python'), sha256='a' * 64),
            reservation=dict(path=str(self.root / 'reservation.json'), sha256='a' * 64),
            fixture=scale_fixture('D'))
        p['git']=dict(path=str(self.root/'git'),sha256='a'*64)
        exec_path=self.root/'git-runtime'/'libexec'/'git-core';bin_path=exec_path.parent.parent/'bin'
        helper=exec_path/'helper';dll=bin_path/'git.dll'
        p['external_runtime']=dict(inputs=[p[key] for key in ('browser','node','python','git')]+[
            dict(path=str(helper),sha256='a'*64),dict(path=str(dll),sha256='a'*64)],git_exec_path=str(exec_path),
            input_directories={str(exec_path):[str(helper)],str(bin_path):[str(dll)]})
        return p

    def test_large_batch_reuses_only_tiny_workload_dimensions_with_real_pinned_receipts(self):
        import hashlib
        from scale_acceptance import hosted_qualification as q
        from scale_acceptance.browser_scale_identity import tiny_fixture
        def pin(name,value):
            path=self.root/name;path.write_text(json.dumps(value))
            return dict(path=str(path),sha256=sha256(path))
        selected=copy.deepcopy(self.packet)
        # This composed receipt fixture must bind the actual test host on Windows too.
        if os.name=='nt':selected['host']=q.host()
        oracle=self.root/'oracle.py';oracle.write_text('# synthetic independent oracle')
        selected['harness']['sha256']['scripts/scale_acceptance/verify.py']=sha256(oracle)
        quote=lambda value:json.dumps(str(value),ensure_ascii=False)
        entry=('import '+quote(self.root/'ui/src/app.ts')+';\n'
            'import {browserApi, executionHistory} from '+quote(self.root/'ui/src/browser/client.ts')+';\n'
            'import {installPageAdapter} from '+quote(self.root/'scripts/scale_acceptance/browser-page.mjs')+';\n'
            'installPageAdapter(browserApi, () => executionHistory);')
        provenance=dict(entry_sha256=hashlib.sha256(entry.encode()).hexdigest(),bundle_sha256='a'*64)
        bp=pin('bridge.json',provenance);selected['harness']['sha256']['bridge.json']=bp['sha256']
        reference=copy.deepcopy(selected);reference.update(mode='qualify',fixture=tiny_fixture('D'))
        config=pin('config.json',reference)
        import importlib.util
        checker_path=Path(__file__).with_name('acceptance-preflight.py')
        spec=importlib.util.spec_from_file_location('batch_fixture_checker',checker_path)
        checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
        # Derive the full receipt shape and checker closure from its owning producer.
        worker=checker.result_base(dict(plan_sha256=config['sha256'],profile='browser-scale'),Path(config['path']))
        worker.update(status='passed',host=selected['host'],bindings={})
        worker['checker']['files']={str(path):sha256(path) for path in checker.checker_sources()}
        wp=pin('worker-result.json',worker);pref=pin('result.json',dict(worker,worker_receipt_sha256=wp['sha256']))
        # Exercise the actual Windows consumer on Linux too; only its OS query is simulated.
        with patch.object(q,'host',return_value=selected['host']):
            self.assertEqual(q.preflight(pref,config['path'],'browser-scale')['checker'],worker['checker'])
        tiny=pin('tiny.json',dict(schema=q.SCHEMA,profile='browser-scale',channel='chrome',host=selected['host'],
            passed=True,scale_acceptance=False,qualifies_other_profiles=False,qualifies_other_channels=False,preflight=pref))
        audit=pin('indie.json',dict(status='passed-after-exit',original_byte0_available=True,probe_closed=True,
            timer_joined=True,qualification_passed=True,qualification_receipt=tiny))
        definition=dict(schema='chopper-frozen-batch-v1',profile='browser-scale',channel='chrome',
            configuration=config,preflight=pref,tiny=tiny,independent=audit,
            verifier=dict(path=str(oracle),sha256=sha256(oracle)),frozen=q.batch_projection(reference,'browser-scale'))
        campaign=pin('definition.json',definition)
        selected.update(execution_kind='batch',frozen_batch=campaign,
            campaign_qualification=campaign,campaign_reservation=reference['reservation'])
        self.assertEqual(q.batch_admission(selected,'browser-scale','chrome')['profile'],'browser-scale')
        if os.name!='nt':
            # Retained real selection-r2 used UNC; the original selection used POSIX.
            for native in (r'C:\proofs\definition.json',r'\\wsl.localhost\Ubuntu\proofs\definition.json'):
                transported=dict(campaign,path=native)
                with patch.object(q.subprocess,'check_output',return_value=str(self.root/'definition.json')+'\n') as convert:
                    self.assertEqual(q.qualified_batch(transported,selected,'browser-scale','chrome')['profile'],'browser-scale')
                    convert.assert_called_once_with(['wslpath','-u',native],text=True)
            for name in ('relative.json',r'C:relative.json',r'C:\proofs\..\definition.json'):
                with self.assertRaisesRegex(ValueError,'absolute receipt path required'):
                    q.qualified_batch(dict(campaign,path=name),selected,'browser-scale','chrome')
        bad=dict(selected,campaign_reservation=dict(path=str(self.root/'unqualified-reservation.json'),sha256='a'*64))
        with self.assertRaisesRegex(ValueError,'actual qualified Tiny reservation'):
            q.batch_admission(bad,'browser-scale','chrome')
        for shape in ('D','G'):
            current=dict(selected,shape=shape,fixture=scale_fixture(shape))
            q.check_qualified_batch(definition,current,'browser-scale','chrome')
        for fault in ('browser','harness','fixture','qualification'):
            changed=copy.deepcopy(selected)
            if fault=='browser':changed['browser']['sha256']='b'*64
            elif fault=='harness':changed['harness']['sha256']['bridge.js']='b'*64
            elif fault=='fixture':changed['fixture']['rows']-=1
            else:
                bad=copy.deepcopy(definition);bad['tiny']=pin('failed-tiny.json',dict(q.bound_json(tiny),passed=False))
                with self.assertRaises(ValueError):q.check_qualified_batch(bad,changed,'browser-scale','chrome')
                continue
            with self.subTest(fault=fault),self.assertRaises(ValueError):
                q.check_qualified_batch(definition,changed,'browser-scale','chrome')

    def test_cold_documents_target_verified_harness_without_changing_live_default(self):
        target=self.root/'staged';target.mkdir()
        p=copy.deepcopy(self.packet);p['harness']['root']=str(target)
        directory=target/'scratch'/'tiny';p['profile']=str(directory/'work'/'profile')
        binding=dict(packet=str(target/'scratch'/'frozen.json'),sha256='a'*64)
        with patch('scale_acceptance.browser_scale_plan.ROOT',self.root/'producer'):
            cold=documents(directory,binding,p,harness_root=target)
            with self.assertRaisesRegex(ValueError,'selected harness root'):documents(directory,binding,p)
        with patch('scale_acceptance.browser_scale_plan.ROOT',target):live=documents(directory,binding,p)
        self.assertEqual(cold,live);self.assertEqual(cold[0]['root'],str(target))

    def test_scale_rejects_valid_length_but_wrong_deterministic_digest(self):
        validate_packet(self.packet)
        changed=copy.deepcopy(self.packet);changed['fixture']['sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'deterministic hash'):validate_packet(changed)

    def test_explicit_tiny_keeps_complete_plan_limits_and_no_large_generation(self):
        from scale_acceptance.browser_scale_identity import tiny_fixture
        p = copy.deepcopy(self.packet)
        p['mode'] = 'qualify'
        p['fixture'] = tiny_fixture('D', 127)
        validate_packet(p)
        directory = self.root / 'scratch/tiny'
        p['profile'] = str(directory / 'work/profile')
        with patch('scale_acceptance.browser_scale_plan.ROOT', self.root):
            manifest, policy = documents(directory, dict(packet=str(self.root/'packet.json'),sha256='a'*64), p)
        self.assertEqual(manifest['contract'],'browser-scale-tiny-v1')
        self.assertEqual(manifest['steps'][0]['argv'][-2:], ['--rows','127'])
        for key,value in LIMITS.items():self.assertEqual(policy[key],value)
        self.assertEqual(policy['owned_bytes'],24*GiB)
        for fault in ('hash','rows','scale','peer'):
            changed = copy.deepcopy(p)
            if fault=='hash':changed['fixture']['sha256']='a'*64
            elif fault=='rows':changed['fixture']['rows']=128
            elif fault=='scale':changed['mode']='scale'
            else:changed['peer']=dict(path='peer',sha256='a'*64)
            with self.subTest(fault=fault),self.assertRaises(ValueError):validate_packet(changed)

    def test_borrowed_plan_has_no_csv_generation_or_copy_output(self):
        from scale_acceptance.browser_scale_identity import tiny_fixture
        p=copy.deepcopy(self.packet);p['mode']='qualify';p['fixture']=tiny_fixture('D')
        p['borrowed_input']={'path':str(self.root/'already-debited.csv')}
        directory=self.root/'scratch/tiny';p['profile']=str(directory/'work/profile')
        binding=dict(packet=str(self.root/'packet.json'),sha256='a'*64)
        with patch('scale_acceptance.browser_scale_plan.ROOT',self.root):
            manifest,policy=documents(directory,binding,p)
        first=manifest['steps'][0]
        self.assertIn('--borrowed-packet',first['argv'])
        self.assertNotIn('input.csv',' '.join(first['artifacts']))
        self.assertEqual(manifest['job']['input'],p['borrowed_input']['path'])
        self.assertEqual([row['id']for row in manifest['steps']],['generate','browser-scale','verify'])
        self.assertEqual(policy['owned_bytes'],LIMITS['owned_bytes'])

    def test_tiny_reservation_never_selects_a_scale_slot(self):
        from scale_acceptance.browser_scale_identity import tiny_fixture
        p=copy.deepcopy(self.packet);p['mode']='qualify';p['fixture']=tiny_fixture('D')
        claims=self.root/'claims';claims.mkdir()
        directory=self.root/'tiny'
        row=dict(plan_id=p['plan_id'],shape=p['shape'],channel=p['channel'],directory=str(directory))
        reservation=dict(version=1,parent_scheduled=True,campaign='synthetic',claims_root=str(claims),
            slots=[],qualifications=[row],channels={'chrome':dict(start_unix=1,deadline_unix=21601)})
        Path(p['reservation']['path']).write_text(json.dumps(reservation))
        schedule(p,directory,2)
        self.assertEqual(reservation['slots'],[])
        del reservation['qualifications'];reservation['slots']=[row]
        Path(p['reservation']['path']).write_text(json.dumps(reservation))
        with self.assertRaises(KeyError):schedule(p,directory,2)

    def test_packet_mutations(self):
        validate_packet(self.packet)
        for key, value in [('features', ['experimental']), ('mode', 'tiny'), ('channel', 'bundled-chromium'),
                           ('parent_scheduled', False), ('browser_version', None), ('storage', {}), ('package', None)]:
            p = copy.deepcopy(self.packet); p[key] = value
            with self.subTest(key=key), self.assertRaises((ValueError, TypeError)):
                validate_packet(p)

        for group, key, value in [('source', 'commit', 'b' * 40), ('source', 'tree', 'b' * 40),
                                 ('host', 'os', 'Linux'), ('fixture', 'rows', 2000), ('fixture', 'bytes', 1_000_000_001),
                                 ('fixture', 'width', 1000), ('browser', 'sha256', None), ('harness', 'sha256', {}),
                                 ('assets', 'sha256', {}), ('evidence', 'sha256', {})]:
            p = copy.deepcopy(self.packet); p[group][key] = value
            with self.subTest(group=group, key=key), self.assertRaises((ValueError, TypeError)):
                validate_packet(p)

    def test_disabled_preparation_keeps_immutable_contract_and_authority(self):
        p = copy.deepcopy(self.packet)
        p['parent_scheduled'] = False
        before = copy.deepcopy(p)
        with patch.object(Path, 'mkdir', side_effect=AssertionError('preparation created storage')), \
             patch('time.time', side_effect=AssertionError('preparation started a clock')):
            validate_packet(p, preparation=True)
        self.assertEqual(p, before)
        with self.assertRaisesRegex(ValueError, 'explicit default scale freeze'):
            validate_packet(p)
        for field, value in (('mode', 'tiny'), ('channel', 'bundled-chromium'),
                             ('parent_scheduled', None), ('parent_scheduled', 0)):
            invalid = copy.deepcopy(p)
            invalid[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_packet(invalid, preparation=True)

    def test_readonly_git_probe_has_finite_timeout(self):
        identity = ScaleIdentity.__new__(ScaleIdentity)
        identity.packet = self.packet
        with patch('scale_acceptance.browser_scale_identity.subprocess.check_output', return_value='selected\n') as command:
            self.assertEqual(identity.git('rev-parse', 'HEAD'), 'selected')
        self.assertEqual(command.call_args.kwargs['timeout'], 4)

    def test_selected_release_source(self):
        candidate = json.loads((Path(__file__).resolve().parents[1] /
                                'docs/releases/0.2.0-candidate.json').read_text())
        selected = dict(commit=candidate['release_source_commit'],
                        tree=candidate['release_source_tree'], clean=True)
        self.packet['source'] = selected
        validate_packet(self.packet)
        self.assertEqual((SOURCE, TREE), (selected['commit'], selected['tree']))
        historical = dict(commit='6069cef178f0b49cf45c2d5db94665c62d43ccc8',
                          tree='6cce1a9f85e5c3ae89323864adb7ca9723a3419e', clean=True)
        for source in (historical, {**selected, 'commit': historical['commit']},
                       {**selected, 'tree': historical['tree']}, {**selected, 'clean': False}):
            self.packet['source'] = source
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'selected product source/tree'):
                validate_packet(self.packet)


    def test_real_file_freeze_drift_and_binary_mutations(self):
        from scale_acceptance.guard import load_runner
        p = self.packet
        runner = load_runner()
        for key in ('product', 'harness', 'assets', 'evidence'):
            base = self.root / key
            base.mkdir()
            group = p[key]
            group['root'] = str(base)
            patterns = group['inputs']
            for pattern in patterns:
                if pattern == '*':
                    for name in ASSETS: (base / name).write_bytes(b'synthetic asset')
                elif pattern in ('crates', 'vendor', 'ui/src', 'ui/public', 'scripts', 'scripts/scale_acceptance') or 'node_modules/' in pattern:
                    folder = base / pattern
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / 'synthetic').write_text('synthetic')
                else:
                    path = base / pattern
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('synthetic')
            if key == 'product':
                for name in ('ui/src/app.ts', 'ui/src/browser/client.ts'):
                    path = base / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('synthetic seam')
            if key == 'harness':
                path = base / 'scripts/scale_acceptance/browser-page.mjs'; path.write_text('synthetic seam')
                (base / 'bridge.js').write_text('synthetic bridge')
                group['inputs'] += ['bridge.js', 'bridge.json']
                provenance = dict(hosted=True, esbuild_version='synthetic', bundle_sha256=sha256(base / 'bridge.js'), inputs={
                    'product': {name: p['product']['sha256'][name] for name in ('ui/src/app.ts', 'ui/src/browser/client.ts')},
                    'harness': {'scripts/scale_acceptance/browser-page.mjs': sha256(path)}})
                (base / 'bridge.json').write_text(json.dumps(provenance))
            actual = runner.identity(base, group['inputs'])
            group['sha256'] = {Path(name).as_posix(): item['sha256'] for name, item in actual.items() if not item.get('directory')}
        p['package']['sha256'] = p['evidence']['sha256']['package.zip']
        for key in ('browser', 'node', 'python', 'reservation'):
            path = Path(p[key]['path']); path.write_bytes(b'synthetic never executable')
            p[key]['sha256'] = sha256(path)
        runtime=self.root/'runtime';runtime.mkdir()
        git=runtime/'git.exe';git.write_bytes(b'selected Git')
        dll=runtime/'runtime.dll';dll.write_bytes(b'full runtime')
        p['git']=dict(path=str(git),sha256=sha256(git))
        external=[dict(path=str(path),sha256=sha256(path)) for path in (git,dll)]
        external += [p[key] for key in ('browser','node','python')]
        exec_path=runtime/'libexec'/'git-core';exec_path.mkdir(parents=True)
        git_helper=exec_path/'helper';git_helper.write_bytes(b'Git helper')
        bin_path=runtime/'bin';bin_path.mkdir();git_dll=bin_path/'git.dll';git_dll.write_bytes(b'Git DLL')
        external += [dict(path=str(path),sha256=sha256(path))for path in (git_helper,git_dll)]
        p['external_runtime']=dict(inputs=external,git_exec_path=str(exec_path),input_directories={
            str(runtime):[str(path)for path in (git,dll,git_helper,git_dll)],str(exec_path):[str(git_helper)],str(bin_path):[str(git_dll)]})
        omitted=copy.deepcopy(p);omitted['external_runtime']['input_directories'].pop(str(exec_path))
        with self.assertRaisesRegex(ValueError,'complete live Git'):validate_packet(omitted)
        packet = self.root / 'packet.json'
        def binding():
            packet.write_text(json.dumps(p))
            return dict(packet=str(packet), sha256=sha256(packet))
        def fake_git(self, *args, group='product'):
            return SOURCE if args == ('rev-parse', 'HEAD') else TREE if args == ('rev-parse', 'HEAD^{tree}') else ''
        # Only the git object identity is synthetic; real maps/hash/stamp checks run.
        with patch.object(ScaleIdentity, 'git', fake_git):
            identity = ScaleIdentity(binding()); identity.check()
            (runtime/'unexpected.dll').write_bytes(b'new')
            with self.assertRaisesRegex(OSError,'runtime membership'):identity.check()
            with self.assertRaisesRegex(ValueError,'runtime membership'):ScaleIdentity(binding())
            (runtime/'unexpected.dll').unlink()
            dll.write_bytes(b'changed runtime')
            with self.assertRaisesRegex(ValueError,'hash drift'):ScaleIdentity(binding())
            dll.write_bytes(b'full runtime');identity=ScaleIdentity(binding())
            p['parent_scheduled'] = False
            disabled = binding()
            packet_bytes = packet.read_bytes()
            with patch.object(Path, 'mkdir', side_effect=AssertionError('preparation created storage')), \
                 patch('time.time', side_effect=AssertionError('preparation started a clock')):
                prepared = ScaleIdentity(disabled, preparation=True)
                prepared.check()
            self.assertEqual(packet.read_bytes(), packet_bytes)
            self.assertIs(prepared.packet['parent_scheduled'], False)
            with self.assertRaisesRegex(ValueError, 'explicit default scale freeze'):
                ScaleIdentity(disabled)
            p['parent_scheduled'] = True
            with self.assertRaisesRegex(ValueError, 'actual Windows'):
                with patch('scale_acceptance.browser_scale_identity.os.name', 'posix'):
                    identity.require_windows()
            browser = Path(p['browser']['path']); browser.write_bytes(b'changed binary')
            with self.assertRaisesRegex(OSError, 'drift'): identity.check()
            with self.assertRaisesRegex(ValueError, 'hash drift'): ScaleIdentity(binding())
            browser.write_bytes(b'synthetic never executable')
            source = Path(p['product']['root']) / 'ui/src/app.ts'
            source.write_text('changed source')
            with self.assertRaisesRegex(ValueError, 'hash/map mismatch'): ScaleIdentity(binding())
            source.write_text('synthetic seam')
            identity = ScaleIdentity(binding())
            (Path(p['assets']['root']) / 'extra-test.wasm').write_bytes(b'bad')
            with self.assertRaisesRegex(OSError, 'drift'): identity.check()
            with self.assertRaisesRegex(ValueError, 'hash/map mismatch'): ScaleIdentity(binding())

    def test_approval_is_separate_exact_binding(self):
        paths = [self.root / n for n in ('plan.json', 'policy.json')]
        for path in paths:
            write_new(path, {})
        binding = dict(sha256='a' * 64)
        p = self.packet
        record = dict(version=1, decision='approved', contract='browser-scale-v1', plan_id=p['plan_id'],
                      shape='D', channel='chrome', plan_sha256=sha256(paths[0]), policy_sha256=sha256(paths[1]),
                      packet_sha256='a' * 64, reservation_sha256='a' * 64, approved_by='synthetic parent', approval_reference='unit control only')
        check = lambda value: approval_record(value, dict(plan_id=p['plan_id'], contract='browser-scale-v1'), *paths, binding, p)
        check(record)
        check_failures = [{}, *[{**record, key: None} for key in record]]
        for invalid in check_failures:
            with self.assertRaises(ValueError):
                check(invalid)
        paths[0].write_text('changed')
        with self.assertRaises(ValueError):
            check(record)

    def test_reservation_ceiling_and_one_shot(self):
        p = self.packet
        claims = self.root / 'claims'; claims.mkdir()
        attempt = self.root / 'attempt'
        now = time.time()
        r = dict(version=1, parent_scheduled=True, campaign='synthetic-control', claims_root=str(claims),
                 slots=[dict(plan_id=p['plan_id'], shape='D', channel='chrome', directory=str(attempt))],
                 channels=dict(chrome=dict(start_unix=now - 1, deadline_unix=now + 500)))
        path = Path(p['reservation']['path'])
        path.write_text(json.dumps(r)); schedule(p, attempt, now)
        for mutation in ('duplicate', 'over-budget', 'wrong-shape', 'expired', 'unscheduled'):
            value = copy.deepcopy(r)
            if mutation == 'duplicate': value['slots'] *= 5
            if mutation == 'over-budget': value['channels']['chrome']['deadline_unix'] = now + 21600
            if mutation == 'expired': value['channels']['chrome']['deadline_unix'] = now
            if mutation == 'wrong-shape': value['slots'][0]['shape'] = 'G'
            if mutation == 'unscheduled': value['parent_scheduled'] = False
            path.write_text(json.dumps(value))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): schedule(p, attempt, now)
        with claim_slot(claims, p['plan_id']):
            with self.assertRaises(FileExistsError):
                with claim_slot(claims, 'other'): pass
        with self.assertRaises(FileExistsError):
            with claim_slot(claims, p['plan_id']): pass
        self.assertTrue((claims / 'active.lock').exists())
        (claims / 'active.lock').unlink()  # synthetic parent retirement after controller stop
        self.assertTrue((claims / (p['plan_id'] + '.consumed')).exists())
        with self.assertRaisesRegex(RuntimeError, 'failed'):
            with claim_slot(claims, 'failure'): raise RuntimeError('failed')
        self.assertTrue((claims / 'failure.consumed').exists())

    def test_plan_is_single_shape_and_fixed(self):
        from scale_acceptance.plan import ROOT
        p = self.packet
        p['harness']['root'] = str(ROOT.resolve())
        directory = ROOT.resolve() / 'scratch/synthetic-scale-no-execution'
        p['profile'] = str(directory / 'work/profile')
        binding = dict(packet=str(ROOT / 'scratch/synthetic-packet.json'), sha256='a' * 64)
        for shape in ('D', 'G'):
            p['shape'] = shape
            plan, policy = documents(directory, binding, p)
            self.assertEqual([s['id'] for s in plan['steps']], ['generate', 'browser-scale', 'verify'])
            self.assertEqual([s['timeout_seconds'] for s in plan['steps']], [1800, 5400, 1800])
            self.assertEqual(plan['job']['limits']['bytes'], 10_000_000)
            self.assertEqual(plan['job']['resources']['temp_bytes'], 8 * GiB)
            self.assertEqual(plan['job']['resources']['memory_mb'], 64)
            self.assertEqual(plan['job']['resources']['workers'], 1)
            for key, value in LIMITS.items(): self.assertEqual(policy[key], value)
            self.assertNotIn('--rows', plan['steps'][0]['argv'])
            self.assertNotIn('browser_frozen', policy)



    def test_watchdog_covers_runner_hash_gaps_without_process_launch(self):
        from scale_acceptance.browser_scale_watchdog import Watchdog
        import threading
        killed = threading.Event()
        stalled = threading.Event()
        monitor = Watchdog(lambda: stalled.wait(1), self.root / 'stale.json',
                           terminate=killed.set, interval=.005, stale=.04).start()
        self.assertTrue(killed.wait(1))
        self.assertFalse(monitor.initial.is_set(), 'partial cold guard cannot acknowledge readiness')
        stalled.set()
        with self.assertRaisesRegex(OSError, 'sampling stale'): monitor.stop()
        self.assertTrue((self.root / 'stale.json').exists())
        killed.clear()
        def denied(): raise OSError('reservation conflict')
        monitor = Watchdog(denied, self.root / 'denied.json', terminate=killed.set, interval=.005, stale=.1).start()
        self.assertTrue(killed.wait(1))
        with self.assertRaisesRegex(OSError, 'reservation conflict'): monitor.stop()
        ticks = []
        monitor = Watchdog(lambda: ticks.append(1), self.root / 'not-failed.json',
                           terminate=killed.set, interval=.005, stale=.1).start()
        self.assertTrue(monitor.initial.wait(.1))
        time.sleep(.02)
        monitor.stop()
        self.assertGreaterEqual(len(ticks), 2)
        self.assertFalse((self.root / 'not-failed.json').exists())

    def test_wrapper_denials_retain_logs_without_launch(self):
        from scale_acceptance.browser_scale_guard import run_scale
        for case in ('no-approval', 'changed-plan', 'changed-policy', 'missing-identities', 'non-windows', 'tiny-no-preflight'):
            with self.subTest(case=case):
                root = self.root / case
                directory = root / 'scratch/attempt'
                directory.mkdir(parents=True)
                p = copy.deepcopy(self.packet)
                if case == 'tiny-no-preflight':
                    from scale_acceptance.browser_scale_identity import tiny_fixture
                    p.update(mode='qualify', fixture=tiny_fixture(p['shape']))
                p['harness']['root'] = str(root)
                p['profile'] = str(directory / 'work/profile')
                p['python']['path'] = str(Path(sys.executable).resolve())
                frozen = root / 'packet.json'; frozen.write_text('{}')
                binding = dict(packet=str(frozen), sha256=sha256(frozen))
                class Identity:
                    packet = p
                    def __init__(self, binding):
                        if case == 'missing-identities': raise ValueError('missing frozen identities')
                    def require_windows(self):
                        if case == 'non-windows': raise ValueError('actual Windows required')
                with patch('scale_acceptance.browser_scale_plan.ROOT', root):
                    manifest, policy = documents(directory, binding, p)
                    if case == 'changed-plan': manifest['steps'][1]['timeout_seconds'] += 1
                    if case == 'changed-policy': policy['owned_bytes'] += 1
                    write_new(directory / 'plan.json', manifest)
                    write_new(directory / 'policy.json', policy)
                    with patch('scale_acceptance.browser_scale_guard.ScaleIdentity', Identity), \
                         patch('scale_acceptance.browser_scale_guard.load_runner') as runner_factory:
                        from scale_acceptance.guard import load_runner
                        runner = load_runner()
                        runner_factory.return_value = runner
                        with patch.object(runner, 'run') as launch, patch.object(runner, 'contain_session') as contain:
                            with self.assertRaises((ValueError, FileNotFoundError)):
                                run_scale(directory / 'plan.json', directory / 'policy.json', root / 'absent-approval.json')
                            launch.assert_not_called(); contain.assert_not_called()
                    failure = json.loads((directory / 'batch/guard-failure.json').read_text())
                    self.assertEqual(failure['status'], 'failed')
                    self.assertEqual(failure['unrun_steps'], ['generate', 'browser-scale', 'verify'])
                    with self.assertRaises(FileExistsError):
                        run_scale(directory / 'plan.json', directory / 'policy.json', root / 'absent-approval.json')

    def test_scale_guard_quota_deadline_and_identity(self):
        class Identity:
            def check(self): pass
        policy = dict(version=1, **LIMITS, owned_roots=[str(self.root)], volumes=[str(self.root)],
                      progress_paths=[str(self.root / 'progress')])
        (self.root / 'work').mkdir()
        (self.root / 'batch').mkdir()
        # Capacity readings only are synthetic; no actual acceptance identity.
        with patch('scale_acceptance.guard.shutil.disk_usage', return_value=type('Disk', (), dict(free=100 * GiB))()):
            tick = [0]
            control = ScaleGuard(policy, self.root / 'batch/samples.jsonl', Identity(), time.time() + 1000, clock=lambda: tick[0])
            cold = json.loads((self.root / 'batch/full-guard-samples.jsonl').read_text().splitlines()[0])
            self.assertTrue(cold['initial']); self.assertIsNone(cold['error'])
            self.assertGreaterEqual(cold['seconds'], 0)
            quota = self.root / 'work/quota.jsonl'
            quota.write_text(json.dumps(dict(sampled_unix=time.time(), usable_bytes=16 * GiB))+'\n')
            control()
            for sample in (dict(sampled_unix=0, usable_bytes=16 * GiB),
                           dict(sampled_unix=time.time() + 50, usable_bytes=16 * GiB),
                           dict(sampled_unix=time.time(), usable_bytes=GiB)):
                with quota.open('a') as stream:stream.write(json.dumps(sample)+'\n')
                with self.assertRaises(ValueError): control()
            quota.unlink()
            with self.assertRaises(FileNotFoundError): control()
            # Host verification has no live origin; stale quota is no longer a
            # browser observation after the browser command has exited.
            control.fixture_pinned = True  # input admission covered separately
            from scale_acceptance.guard import load_runner
            runner=load_runner()
            control.observe(runner.StatusObservation((runner.AttemptObservation('verify',1,'running'),),False))
            # Rich mutable status is not an admission input, even if unreadable.
            (self.root/'batch/status.json').mkdir()
            quota.write_text(json.dumps(dict(sampled_unix=0, usable_bytes=0))+'\n')
            tick[0] = 1
            control()
            tick[0] = 601
            with self.assertRaisesRegex(OSError, 'no progress'): control()
            tick[0] = 21600
            with self.assertRaisesRegex(OSError, 'deadline'): control()

    def test_quota_journal_partial_complete_and_strict_metadata(self):
        path=self.root/'quota.jsonl'
        first=dict(sampled_unix=1,usable_bytes=16*GiB)
        path.write_text(json.dumps(first)+'\n')
        sample,state=read_quota_journal(path)
        self.assertEqual(sample,first)
        with path.open('ab') as stream:stream.write(b'{"sampled_unix":2,')
        self.assertEqual(read_quota_journal(path,state)[0],first)
        with path.open('ab') as stream:stream.write(b'"usable_bytes":9}\n')
        sample,state=read_quota_journal(path,state)
        self.assertEqual(sample['sampled_unix'],2)
        with path.open('ab') as stream:stream.write(b'{"x":1,"x":2}\n')
        with self.assertRaisesRegex(ValueError,'duplicate'):read_quota_journal(path,state)
        path.write_bytes(b'{}\n')
        with self.assertRaisesRegex(ValueError,'truncation'):read_quota_journal(path,state)

    def test_quota_journal_replacement_links_and_observation_drift(self):
        path=self.root/'quota.jsonl';path.write_bytes(b'{"sampled_unix":1}\n')
        _,state=read_quota_journal(path)
        # The retained old name already prevents inode reuse. An extra ordinary
        # reader would prohibit this fixture's rename on Windows.
        path.rename(self.root/'old.jsonl');path.write_bytes(b'{"sampled_unix":2}\n')
        with self.assertRaisesRegex(ValueError,'identity'):read_quota_journal(path,state)
        os.link(path,self.root/'alias.jsonl')
        with self.assertRaisesRegex(ValueError,'single-link'):read_quota_journal(path)
        (self.root/'alias.jsonl').unlink()
        from contextlib import contextmanager
        original=Path.open;mutated=[]
        @contextmanager
        def opened(value,mode='r',*args,**kwargs):
            with original(value,mode,*args,**kwargs) as stream:
                yield stream
            if value==path and mode=='rb':
                self.assertTrue(stream.closed)
                # Still inside the observation, before its final named-path
                # identity check, but after the ordinary reader really closes.
                path.rename(self.root/'during.jsonl');path.write_bytes(b'{"sampled_unix":3}\n')
                mutated.append(True)
        with patch.object(Path,'open',opened):
            with self.assertRaisesRegex(ValueError,'path identity'):read_quota_journal(path)
        self.assertEqual(mutated,[True])

    def test_quota_journal_empty_oversized_and_reparse_denied(self):
        path=self.root/'quota.jsonl'
        for raw in [b'',b'{"x":',b'x'*1024**2+b'\n']:
            path.write_bytes(raw)
            with self.assertRaises(ValueError):read_quota_journal(path)
        path.unlink();target=self.root/'target';target.write_bytes(b'{}\n')
        try:path.symlink_to(target)
        except OSError as error:
            if getattr(error,'winerror',None)==1314:self.skipTest('Windows symlink creation privilege unavailable')
            raise
        with self.assertRaises(ValueError):read_quota_journal(path)

    def test_append_progress_never_counts_an_unfinished_record(self):
        from scale_acceptance.guard import Guard
        path=self.root/'progress.jsonl';path.write_bytes(b'{"rows":1}\n')
        policy=dict(version=1,**LIMITS,owned_roots=[str(self.root)],volumes=[str(self.root)],
                    progress_paths=[str(path)])
        policy.update(sample_seconds=.01,no_progress_seconds=1)
        tick=[0]
        with patch('scale_acceptance.guard.shutil.disk_usage',return_value=type('Disk',(),dict(free=100*GiB))()):
            control=Guard(policy,self.root/'samples.jsonl',clock=lambda:tick[0])
            for value in [b'{"rows":2,"text":"'+b'x'*2000,b'x'*3000,b'x'*1000]:
                with path.open('ab') as stream:stream.write(value)
                tick[0]+=.1;control()
                self.assertEqual(control.last_progress,0)
            with path.open('ab') as stream:stream.write(b'"}\n')
            tick[0]=.5;control();self.assertEqual(control.last_progress,.5)
            with path.open('ab') as stream:stream.write(b'{"rows":2,"text":"'+b'x'*6000+b'"}\n')
            tick[0]=2
            with self.assertRaisesRegex(OSError,'no progress'):control()


class ProfileCopyControls(unittest.TestCase):
    def copy_case(self,mode):
        from scale_acceptance import browser_scale_guard as guard
        with tempfile.TemporaryDirectory(prefix='closed-profile-control-') as name:
            base=Path(name);source=base/'closed';source.mkdir();(source/'Cache').mkdir();(source/'empty').mkdir()
            (source/'Cache/index').write_bytes(b'closedprofilecache');(source/'Preferences').write_bytes(b'{}')
            files=sorted(str(p) for p in source.rglob('*') if p.is_file())
            expected=[dict(path=p,sha256=sha256(Path(p))) for p in files]
            if mode=='wronghash':expected[0]['sha256']='0'*64
            if mode=='hardlink':
                os.link(source/'Preferences',source/'alias');files.append(str(source/'alias'))
                expected.append(dict(path=str(source/'alias'),sha256=sha256(source/'alias')))
            observed=base/'observation.json'
            write_new(observed,dict(input_directories={str(source):files},inputs=expected))
            root=base/'fresh'
            r=dict(root=str(root),profile=str(root/'profile'),profile_copy_receipt=str(root/'profile-copy.json'),
                deadline_unix=time.time()+90,limits=dict(visits=2000000,read_bytes=16*GiB,
                    metadata_bytes=16*1024**2,profile_bytes=2*GiB,growth_bytes=4*GiB),
                closed_profile_observation=dict(path=str(observed),sha256=sha256(observed)))
            definition=base/'definition.json';write_new(definition,r)
            binding=dict(path=str(definition),sha256=sha256(definition))
            if mode=='existing':root.mkdir();(root/'profile').mkdir()
            packet=dict(profile=str(source),fixture=dict(bytes=12800));before={p:Path(p).read_bytes() for p in files}
            original=Path.lstat
            def metadata(path,*args,**kwargs):
                value=original(path,*args,**kwargs)
                if mode=='forecast' and path==source/'Preferences':
                    return SimpleNamespace(**{key:getattr(value,key) for key in dir(value)
                        if key.startswith('st_') and key!='st_size'},st_size=2*GiB+1)
                return value
            # Only the outer Windows/proof-role admission is mocked. Real copy,
            # audit, bytes, snapshots, closes and prewrite forecast run here.
            with patch.object(guard,'recovery_request',return_value=(r,packet,{})),patch.object(Path,'lstat',metadata):
                if mode=='pass':
                    budget=guard.module('acceptance-preflight').Budget(dict(seconds=1800,read_bytes=16*GiB,visits=2000000,
                        capture_bytes=65536,storage_bytes=4*GiB),root,mutation_roots=[root])
                    budget.install()
                    try:result=guard._copy_recovery_profile(binding,budget)
                    finally:budget.active=False
                    self.assertTrue(result['source_unchanged']);self.assertTrue((root/'profile/empty').is_dir())
                    self.assertGreaterEqual(result['usage']['charged_read_bytes'],sum(len(raw) for raw in before.values())*2)
                    for path,raw in before.items():self.assertEqual((root/'profile'/Path(path).relative_to(source)).read_bytes(),raw)
                else:
                    budget=guard.module('acceptance-preflight').Budget(dict(seconds=1800,read_bytes=16*GiB,visits=2000000,
                        capture_bytes=65536,storage_bytes=4*GiB),root,mutation_roots=[root]);budget.install()
                    try:
                        with self.assertRaises((AssertionError,ValueError)):guard._copy_recovery_profile(binding,budget)
                    finally:budget.active=False
                    self.assertFalse((root/'profile-copy.json').exists())
                    if mode in ('hardlink','forecast'):self.assertFalse((root/'profile').exists())
            for path,raw in before.items():self.assertEqual(Path(path).read_bytes(),raw)
    @unittest.skipIf(os.name=='nt','Linux entrypoint/import denial is separate from actual Windows recovery')
    def test_exact_emitted_copy_command_imports_parses_and_denies_before_io(self):
        import subprocess
        from pathlib import PureWindowsPath
        from scale_acceptance import browser_scale_guard as guard
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);definition=root/'definition.json'
            write_new(definition,dict(root=r'C:\hosted104-startup-recovery-r1',profile_copy_receipt=r'C:\hosted104-startup-recovery-r1\profile-copy.json',recovery_code=[],
                **{key:dict(path='C:/sealed/'+key+'.json',sha256='a'*64) for key in
                   ('frozen_packet','public_state','browser_receipt','independent','release','consumed_claim','closed_profile_observation')}))
            binding=dict(path=str(definition),sha256=sha256(definition))
            packet=dict(profile=r'C:\original-source\harness\scratch\scale\work\profile',shape='G',plan_id='original-G',channel='chrome',
                python=dict(path=r'C:\selected\python.exe'),node=dict(path=r'C:\selected\node.exe'),toolchains={},fixture={})
            plan,_=guard.recovery_documents(binding,packet,path_type=PureWindowsPath,scripts=r'C:\selected\scripts')
            argv=plan['steps'][0]['argv']
            self.assertEqual(argv[5],'browser-scale-copy-profile')
            mapped=[sys.executable,*argv[1:4],str(Path(__file__).with_name('scale-acceptance.py')),*argv[5:]]
            result=subprocess.run(mapped,cwd=root,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,1)
            self.assertIn('closed-profile copy requires actual Windows',result.stderr)
            self.assertNotIn('ImportError',result.stderr);self.assertNotIn('unrecognized arguments',result.stderr)
            self.assertEqual(sorted(p.name for p in root.iterdir()),['definition.json'])
    def test_real_closed_profile_copy_uses_audit_and_preserves_empty_directories(self):self.copy_case('pass')
    def test_wrong_body_pin_denies_and_retains_partial_copy(self):self.copy_case('wronghash')
    def test_hardlink_denies_before_copy(self):self.copy_case('hardlink')
    def test_metadata_forecast_denies_before_copy(self):self.copy_case('forecast')
    def test_existing_copy_target_denies_without_overwrite(self):self.copy_case('existing')


class RecoveryPacketControls(unittest.TestCase):
    """Actual failed-G record shapes through producer, declarations and CLI parser."""
    def setUp(self):
        import importlib.util
        from pathlib import PureWindowsPath
        from scale_acceptance import hosted_qualification as q
        self.q=q;self.PureWindowsPath=PureWindowsPath
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.paths={};self.serial=0
        docs=json.loads(Path(__file__).with_name('fixtures').joinpath('browser-scale-recovery-records.json').read_bytes())['documents']
        self.docs=docs
        def native(value):
            name=str(value)
            if PureWindowsPath(name).is_absolute():return str(PureWindowsPath(name))
            path=Path(value).resolve();key=str(PureWindowsPath('C:/source-control')/path.relative_to('/').as_posix())
            self.paths[key]=path;return key
        self.native=native
        def local_path(value):
            key=str(PureWindowsPath(value))
            if key in self.paths:return self.paths[key]
            # Owning producers emit real temporary paths on native Windows.
            path=Path(value)
            if path.is_absolute() and path.resolve().is_relative_to(self.root.resolve()):return path
            raise KeyError(key)
        self.local_path=local_path
        def local(binding):
            return q.bound_json(dict(path=str(local_path(binding['path'])),sha256=binding['sha256']))
        self.patch_native=patch.object(q,'native_path',side_effect=native);self.patch_native.start();self.addCleanup(self.patch_native.stop)
        self.patch_local=patch.object(q,'_local_binding',side_effect=local);self.patch_local.start();self.addCleanup(self.patch_local.stop)
        def save(value,native_path=None):
            self.serial+=1;path=self.root/(str(self.serial)+'.json');path.write_bytes(q._json_bytes(value))
            name=native_path or native(path);self.paths[str(PureWindowsPath(name))]=path
            return dict(path=str(PureWindowsPath(name)),sha256=sha256(path))
        self.save=save
        p=docs['frozen_packet'];old=docs['original_packet'];base=PureWindowsPath(p['profile']).parent.parent
        p['reservation']=save(docs['reservation'],p['reservation']['path'])
        frozen=save(p,old['paths']['config']);docs['original_preflight']['plan_sha256']=frozen['sha256']
        docs['browser_receipt']['packet_sha256']=frozen['sha256']
        browser=save(docs['browser_receipt'],str(base/'work/browser-receipt.json'))
        for attempt in docs['original_status']['attempts']:
            if attempt['id']=='browser-scale':
                for row in attempt['artifacts'].values():
                    if row is not None:row['sha256']=browser['sha256']
        release=save(docs['release'],str(base/'batch/reservation-released.json'))
        docs['independent']['source_receipts']=[release]
        now=docs['reservation']['channels'][p['channel']]['start_unix']+60;window=dict(schema='chopper-unattended-continuation-v1',non_time_allowances_renewed=False,
            launch_cutoff_utc='2099-01-01T00:00:00+00:00',deadline_utc='2099-01-02T00:00:00+00:00')
        claim=str(PureWindowsPath(docs['reservation']['claims_root'])/(p['plan_id']+'.consumed'))
        self.selection=dict(schema='chopper-hosted-packet-selection-v1',profile='browser-scale',operation=q.RECOVERY_OPERATION,
            original_packet=save(old),original_preflight=save(docs['original_preflight'],str(PureWindowsPath(old['paths']['preflight'])/'result.json')),
            original_status=save(docs['original_status'],str(base/'batch/status.json')),
            public_state=save(docs['public_state'],str(base/'work/public-state.json')),independent=save(docs['independent']),
            consumed_claim=save(docs['consumed_claim'],claim),host=save(docs['host']),history_ledger=save(docs['history_ledger']),
            window=save(window),start_unix=now+30,deadline_unix=now+5400,namespace='C:/hosted104-source-control-recovery-r1',
            approval_reference='source control only',dispatch=dict(checkout='C:/ci',commit='a'*40))
        spec=importlib.util.spec_from_file_location('recovery_actual_checker',Path(__file__).with_name('acceptance-preflight.py'))
        self.checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.checker)

    def generated(self):
        selected=self.root/'selection.json';selected.write_bytes(self.q._json_bytes(self.selection))
        # The operator is WSL even when this source control runs on native Windows.
        # Adapt only its emitted outer prefix, then run the real native consumer.
        actual=[sys.executable,'-B',str(Path(self.checker.__file__).resolve().parent.parent/'scripts/windows-native.py')]
        self.operator_prefix=actual if os.name!='nt' else ['/operator/python3','-B','/operator/source/scripts/windows-native.py']
        transport=self.q.recovery_transport
        def operator_binding(packet,checker):
            for row in packet['commands']:
                self.assertEqual(row['dispatch_argv'][:3],actual)
                row['dispatch_argv'][:3]=self.operator_prefix
            return transport(packet,checker,executable=self.docs['frozen_packet']['python']['path'])
        with patch.object(self.q.time,'time',return_value=self.selection['start_unix']-30), \
             patch.object(self.q,'recovery_transport',side_effect=operator_binding):
            result=self.q.prepare_packet(selected,self.root/'generated',self.checker)
        packet=json.loads(Path(result['path']).read_bytes())
        return packet,result

    def test_actual_record_producer_reaches_declarations_and_real_cli_parser(self):
        import importlib.util
        packet,result=self.generated()
        self.assertEqual(self.local_path(Path(result['path'])),Path(result['path']))
        with self.assertRaises(KeyError):self.local_path(str(self.root.parent/'unmapped.json'))
        with self.assertRaises(KeyError):self.local_path(r'C:\unmapped\outside.json')
        self.assertEqual(self.q.packet_declarations(packet,self.checker)['commands'],4)
        self.assertEqual(packet['forecast']['profile_files'],2)
        size=sum(self.docs['host']['input_sizes'].values())
        self.assertEqual(packet['forecast']['profile_bytes'],size)
        self.assertEqual(packet['forecast']['read_bytes'],3*size+2*self.docs['frozen_packet']['fixture']['bytes']+64*1024**2)
        self.assertEqual(packet['manifest']['steps'][0]['id'],'copy-profile')
        self.assertEqual([step['id'] for step in packet['manifest']['steps']],['copy-profile','extract-completed','verify'])
        self.assertEqual(packet['policy']['scale_frozen'],dict(packet=packet['definition']['frozen_packet']['path'],sha256=packet['definition']['frozen_packet']['sha256']))
        spec=importlib.util.spec_from_file_location('recovery_real_cli',Path(__file__).with_name('scale-acceptance.py'))
        cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
        argv=packet['commands'][2]['argv'];self.assertEqual(argv[5],'browser-scale-run')
        with patch.object(sys,'argv',[argv[4],*argv[5:]]),patch.object(cli,'run_scale',return_value=0) as execute:
            self.assertEqual(cli.main(),0)
        self.assertEqual(str(execute.call_args.args[0]),packet['paths']['plan'])
        for fault in ('Run','claim','argv','definition','code','overlap'):
            value=copy.deepcopy(packet)
            if fault=='Run':value['product_runs']=1
            if fault=='claim':value['new_claims']=1
            if fault=='argv':value['commands'][2]['argv'].append('--invented')
            if fault=='definition':value['definition']['profile']='C:/foreign'
            if fault=='code':value['recovery_code']=value['recovery_code'][:-1]
            if fault=='overlap':value['storage_priming']['covered_roots'].append(value['definition']['root'])
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.q.packet_declarations(value,self.checker)

    def test_generated_recovery_reaches_windows_consumer_without_reinterpreting_wsl_prefix(self):
        packet,_=self.generated()
        # The actual native checker has an UNC __file__, while its source pins
        # still refer to the exact bodies emitted by the WSL producer.
        native=SimpleNamespace(__file__=self.native(self.checker.__file__),checker_sources=self.checker.checker_sources)
        with patch.object(sys,'executable',self.docs['frozen_packet']['python']['path']):
            self.assertEqual(self.q.recovery_packet_declarations(packet,native)['commands'],4)
        self.q.recovery_transport(packet,self.checker)
        for fault in ('native-tail','script-path','checkout','commit','posix-executable'):
            value=copy.deepcopy(packet);outer=value['commands'][0]['dispatch_argv']
            if fault=='native-tail':outer[-1]='wrong-native-binding'
            elif fault=='script-path':outer[2]='/source/../windows-native.py'
            elif fault=='checkout':outer[outer.index('--checkout')+1]='C:/wrong-checkout'
            elif fault=='commit':outer[outer.index('--expect-commit')+1]='b'*40
            else:outer[0]='C:\\python.exe'
            with self.subTest(fault=fault),self.assertRaises(ValueError):
                self.q.recovery_transport(value,native,executable=self.docs['frozen_packet']['python']['path'])
        wrong=copy.deepcopy(packet);wrong['commands'][0]['dispatch_argv'][0]='/wrong/python3'
        from pathlib import PurePosixPath
        repository=PurePosixPath(self.operator_prefix[2]).parent.parent
        # Only POSIX repository resolution is unavailable in the native test OS.
        operator_path=SimpleNamespace(resolve=lambda:repository/'scripts/acceptance-preflight.py')
        with patch.object(self.q,'Path',return_value=operator_path), \
                self.assertRaisesRegex(ValueError,'exact WSL producer prefix'):
            self.q.recovery_transport(wrong,self.checker,executable=self.operator_prefix[0])

    def test_recovery_never_extends_original_channel_clock(self):
        self.selection['deadline_unix']=self.docs['reservation']['channels'][self.docs['frozen_packet']['channel']]['deadline_unix']+1
        self.selection['start_unix']=self.selection['deadline_unix']-1800
        with self.assertRaisesRegex(ValueError,'original channel deadline'):self.generated()

    def test_real_files_after_exit_accepts_failed_closed_and_requires_complete_oracle_for_success(self):
        from scale_acceptance import browser_scale_guard as guard
        packet,_=self.generated();definition,p,_=guard.recovery_request(packet['recovery'])
        local_root=self.root/'native-recovery';(local_root/'batch').mkdir(parents=True);(local_root/'preparation').mkdir()
        native_root=self.PureWindowsPath(definition['root']);original_Path=Path
        def mapped(value,*parts):
            win=self.PureWindowsPath(str(value))
            if win.is_absolute():
                if win.is_relative_to(native_root):return local_root/win.relative_to(native_root).as_posix()
                return self.local_path(value)
            return original_Path(value,*parts)
        storage=SimpleNamespace(roots=[],sample=lambda:packet['storage_priming']['ledger']['cumulative_owned_bytes']+4096)
        small=SimpleNamespace(windows=object(),module=lambda name:SimpleNamespace(host_lock_path=lambda:self.root/'Original'),
            primed_storage=lambda *args:storage,LIMITS={'stop_owned_bytes':56*GiB})
        release=copy.deepcopy(self.docs['release']);release.update(operation='completed-export extraction only',
            product_runs=0,new_claims=0,recovery=packet['recovery'])
        def independent(windows,facts,value,original,end,result,**kwargs):
            self.assertEqual(value['recovery'],packet['recovery']);self.assertTrue(facts)
            result.update(processes=[dict(pid=row['pid'],status='absent') for row in facts],original_lock_available=True)
        def run_case(passed,subdir):
            release['passed']=passed;(local_root/'batch/reservation-released.json').write_bytes(self.q._json_bytes(release))
            paths=dict(packet['paths'],after_exit=str(native_root/'preparation'/subdir));selected=dict(packet,paths=paths)
            # Packet setup already traversed the real producer/declaration above;
            # these substitutions cover only native path/WinAPI and storage sampling.
            with patch.object(self.q,'recovery_packet_declarations'),patch.object(guard,'recovery_request',return_value=(definition,p,{})),\
                 patch.object(self.q,'Path',side_effect=mapped),patch.object(self.checker,'load',return_value=small),\
                 patch.object(self.q,'independent_observation',side_effect=independent):
                return self.q.recovery_after_exit(selected,str(native_root/'preparation'/subdir),'a'*64,self.checker)
        result=run_case(False,'failed-closed')
        self.assertEqual(result['status'],'passed-after-exit');self.assertFalse(result['recovery_passed'])
        self.assertEqual(result['generated_input_bytes'],0);self.assertEqual(result['new_claims'],0)
        # A successful controller without the independent CSV oracle cannot pass.
        with self.assertRaises(FileNotFoundError):run_case(True,'missing-oracle')
        self.assertFalse(json.loads((local_root/'preparation/missing-oracle/result.json').read_bytes())['recovery_passed'])
        self.assertFalse((local_root/'active.lock').exists())

    def test_wrong_failed_run_link_denies_before_any_native_output(self):
        self.docs['browser_receipt']['status']='passed'
        base=self.PureWindowsPath(self.docs['frozen_packet']['profile']).parent.parent
        self.save(self.docs['browser_receipt'],str(base/'work/browser-receipt.json'))
        with self.assertRaises(ValueError):self.generated()
        self.assertFalse((self.root/'generated/packet.json').exists())


class EdgeTimeContinuationControls(unittest.TestCase):
    """Real owning producer/validators, with only Windows file mapping replaced."""
    def setUp(self):
        from pathlib import PureWindowsPath
        from scale_acceptance import hosted_qualification as q
        self.q=q;self.P=PureWindowsPath;self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.files={};self.values={}
        def pin(name,value):
            native=str(self.P('C:/control')/name);path=self.root/name;path.write_text(json.dumps(value));binding=dict(path=native,sha256=sha256(path));self.files[native]=path;self.values[native]=value;return binding
        self.pin=pin
        self.cells=[dict(plan_id=c+'-'+s,shape=s,channel=c,namespace='C:/'+c+'-'+s)for c in ('chrome','msedge')for s in ('D','G')]
        self.old=dict(version=1,parent_scheduled=True,campaign='same-family',slots=q.browser_scale_slots(self.cells),claims_root='C:\\owner\\campaign\\claims',
            qualifications=[dict(plan_id='old-tiny',shape='D',channel='chrome',directory='C:\\old-tiny-source\\harness\\scratch\\tiny')],
            channels={c:dict(start_unix=100000,deadline_unix=121600)for c in ('chrome','msedge')})
        self.original=pin('reservation.json',self.old)
        # The original reservation itself belongs to the already charged campaign root.
        oldkey=self.original['path'];newkey='C:\\owner\\campaign\\reservation.json';self.files[newkey]=self.files.pop(oldkey);self.values[newkey]=self.values.pop(oldkey);self.original['path']=newkey
        stamp=lambda n:__import__('datetime').datetime.fromtimestamp(n,__import__('datetime').timezone.utc).isoformat()
        self.authority=pin('authority.json',dict(old_reservation_sha256=self.original['sha256'],old_channel_stop=stamp(121600),overall_deadline=stamp(205000),overall_launch_cutoff=stamp(204000),non_time_allowances_renewed=False,publication_authorized=False))
        origin=pin('origin.json',dict(adopted_roots=['C:\\owner\\campaign'],metadata=dict(storage_priming=dict(ledger=dict(cumulative_owned_bytes=100)))))
        config=pin('config.json',dict(owned_root='C:\\owner\\old',history_roots=['C:\\owner\\retained'],retained_origin_manifest=origin['path'],inputs=[origin]))
        self.covered=['C:\\owner\\old','C:\\owner\\retained','C:\\owner\\campaign']
        ledger=pin('ledger.json',dict(method=q.STORAGE_LEDGER_METHOD,cumulative_owned_bytes=1000,covered_roots=self.covered));self.history=dict(configuration=config,origin=origin,ledger=ledger)
        self.claims=self.root/'claims';self.claims.mkdir();chrome={}
        for shape in ('D','G'):
            native=str(self.P(self.old['claims_root'])/('chrome-'+shape+'.consumed'));p=self.claims/('chrome-'+shape+'.consumed');p.write_text('100001');self.files[native]=p
            consumed=dict(path=native,sha256=sha256(p));audit=dict(status='passed-after-exit',profile='browser-scale',channel='chrome',shape=shape,original_byte0_available=True,probe_closed=True,timer_joined=True)
            if shape=='D':audit.update(scale_cell_passed=True,campaign_active_retirement=dict(consumed=consumed))
            else:
                audit.pop('profile');audit.update(operation=q.RECOVERY_OPERATION,recovery_passed=True,consumed_claim=consumed)
            chrome[shape]=dict(consumed=consumed,independent=pin('chrome-'+shape+'-audit.json',audit))
        self.body=dict(schema='chopper-browser-edge-time-continuation-v1',original_reservation=self.original,authority=self.authority,history=self.history,chrome=chrome,prior_edge_scale_seconds=0);self.binding=pin('continuation.json',self.body)
        def local(binding):
            if binding['path']not in self.files:return q.bound_json(binding)
            p=self.files[binding['path']];self.assertEqual(sha256(p),binding['sha256']);return json.loads(p.read_text())
        self.addCleanup(patch.stopall);patch.object(q,'_local_binding',side_effect=local).start()
        def convert(args,**kwargs):
            self.assertEqual(args[:2],['wslpath','-u']);n=args[2]
            if n==self.old['claims_root']:return str(self.claims)+'\n'
            if self.P(n).parent==self.P(self.old['claims_root']):return str(self.claims/self.P(n).name)+'\n'
            return str(self.root/str(self.P(n)).replace('\\','_').replace(':',''))+'\n'
        patch.object(q.subprocess,'check_output',side_effect=convert).start()
        # Synthetic C: fixtures use the WSL translation seam on either test OS;
        # this module-local adapter never changes the process-wide os.name.
        patch.object(q,'os',SimpleNamespace(name='posix',path=os.path)).start()
        self.packet=dict(paths=q.browser_scale_paths('C:/new-edge-tiny',mode='qualify'),host_receipt=dict(channel='msedge'),
            selection=dict(plan_id='new-edge-tiny',approval_reference='same-family'),time_continuation=self.binding,timing=dict(deadline=205000),
            origin=dict(metadata=dict(history=self.history,storage_priming=dict(covered_roots=self.covered,fresh_roots=[],ledger=dict(self.history['ledger'],cumulative_owned_bytes=1000)))))

    def emit(self):return self.q.browser_scale_make_reservation(self.packet,200000)

    def test_emitted_same_family_reaches_real_large_and_schedule_consumers(self):
        from scale_acceptance.browser_scale_guard import schedule_declaration
        emitted=json.loads(json.dumps(self.emit()));self.assertEqual(emitted['slots'],self.old['slots']);self.assertEqual(emitted['claims_root'],self.old['claims_root']);self.assertEqual(emitted['channels']['chrome'],self.old['channels']['chrome']);self.assertEqual(self.q._local_binding(self.original),self.old)
        self.q.browser_scale_time_reservation(self.binding,emitted)
        tiny=dict(mode='qualify',plan_id='new-edge-tiny',shape='D',channel='msedge')
        self.assertEqual(schedule_declaration(tiny,self.P(self.packet['paths']['owned_root']),emitted,200001,path_type=self.P),204880)
        for shape in ('D','G'):
            paths=self.q.browser_scale_paths('C:/msedge-'+shape,mode='scale');large=dict(paths=paths,shape=shape,selection=dict(plan_id='msedge-'+shape,approval_reference='same-family'),host_receipt=dict(channel='msedge'),
                time_continuation=self.binding,large_reservation=dict(path=self.packet['paths']['reservation'],sha256='a'*64),origin=copy.deepcopy(self.packet['origin']))
            large['origin']['metadata']['storage_priming']['fresh_roots']=[self.packet['paths']['source'],self.packet['paths']['metadata']]
            self.assertEqual(self.q.browser_scale_reservation(large,emitted,now=200001),204880)
        closure=self.q.browser_scale_time_inputs(self.binding);self.assertTrue(all(row in closure for row in [self.original,self.authority,*self.history.values()]))
        # D's subsequent permanent claim must not block G or erase Chrome.
        (self.claims/'msedge-D.consumed').write_text('200100');self.q.browser_scale_time_available(self.binding,plan_id='msedge-G')
        with self.assertRaisesRegex(ValueError,'unspent'):self.q.browser_scale_time_available(self.binding,plan_id='msedge-D')

    def test_emitted_tiny_then_D_then_G_accept_monotone_complete_ledger_epochs(self):
        emitted=self.emit();tiny_source=self.packet['paths']['source'];tiny_metadata=self.packet['paths']['metadata']
        def epoch(name,total,roots):
            history=copy.deepcopy(self.history);history['ledger']=self.pin(name,dict(method=self.q.STORAGE_LEDGER_METHOD,cumulative_owned_bytes=total,covered_roots=roots));return history
        tiny_history=epoch('after-tiny-ledger.json',1200,[*self.covered,tiny_source,tiny_metadata])
        dpaths=self.q.browser_scale_paths('C:/msedge-D',mode='scale');gpaths=self.q.browser_scale_paths('C:/msedge-G',mode='scale')
        def large(shape,history):
            ledger=self.q._local_binding(history['ledger']);paths=dpaths if shape=='D'else gpaths
            return dict(shape=shape,paths=paths,selection=dict(plan_id='msedge-'+shape,approval_reference='same-family'),host_receipt=dict(channel='msedge'),time_continuation=self.binding,large_reservation=dict(path=self.packet['paths']['reservation'],sha256='a'*64),origin=dict(metadata=dict(history=history,storage_priming=dict(covered_roots=ledger['covered_roots'],fresh_roots=[paths['source'],paths['metadata']],ledger=dict(history['ledger'],cumulative_owned_bytes=ledger['cumulative_owned_bytes'])))))
        D=large('D',tiny_history);self.q.browser_scale_time_context(self.binding,partition=D['origin']['metadata']['storage_priming'],history=tiny_history);self.q.browser_scale_reservation(D,emitted,now=200001)
        (self.claims/'msedge-D.consumed').write_text('200002')
        d_history=epoch('after-D-ledger.json',1500,[*self.covered,tiny_source,tiny_metadata,dpaths['source'],dpaths['metadata']]);G=large('G',d_history)
        self.q.browser_scale_time_context(self.binding,partition=G['origin']['metadata']['storage_priming'],history=d_history);self.q.browser_scale_reservation(G,emitted,now=200003)
        for fault in ('refund','missingBaselineRoot','missingCompletedTiny','missingCompletedD','unboundLatest'):
            bad=copy.deepcopy(G)
            if fault=='refund':
                h=epoch('refund.json',999,[*self.covered,tiny_source,tiny_metadata,dpaths['source'],dpaths['metadata']]);bad=large('G',h)
            elif fault in ('missingBaselineRoot','missingCompletedTiny','missingCompletedD'):
                removed={'missingBaselineRoot':self.covered[0],'missingCompletedTiny':tiny_source,'missingCompletedD':dpaths['source']}[fault]
                roots=[x for x in [*self.covered,tiny_source,tiny_metadata,dpaths['source'],dpaths['metadata']]if x!=removed]
                bad=large('G',epoch(fault+'.json',1500,roots))
            else:bad['origin']['metadata']['history']=self.history
            with self.subTest(fault=fault),self.assertRaises(ValueError):
                self.q.browser_scale_time_context(self.binding,partition=bad['origin']['metadata']['storage_priming'],history=bad['origin']['metadata']['history']);self.q.browser_scale_reservation(bad,emitted,now=200004)

    def test_consumed_active_wrong_debt_and_changed_original_deny_before_emission(self):
        for name in ['active.lock','msedge-D.consumed','msedge-G.consumed']:
            p=self.claims/name;p.write_text('1')
            with self.subTest(name=name),self.assertRaises(ValueError):self.emit()
            p.unlink()
        bad=copy.deepcopy(self.packet);bad['origin']['metadata']['storage_priming']['ledger']['cumulative_owned_bytes']=999
        with self.assertRaisesRegex(ValueError,'ledger/history'):self.q.browser_scale_make_reservation(bad,200000)
        p=self.files[self.original['path']];old=p.read_text();p.write_text(old+' ')
        with self.assertRaises(AssertionError):self.emit()
        p.write_text(old)

    def test_after_exit_mutation_target_never_trusts_self_hashed_current_reservation(self):
        current=self.root/'current-reservation.json';current.write_text(json.dumps(dict(claims_root='C:\\unrelated')))
        unrelated=self.root/'unrelated';unrelated.mkdir();marker=unrelated/'active.lock';marker.write_text('keep')
        packet=copy.deepcopy(self.packet);packet['paths'].update(after_exit=str(self.root/'audit'),metadata=str(self.root/'metadata'),reservation=str(current))
        captured=[]
        class AdmissionObserved(Exception):pass
        def budget(*args,**kwargs):captured.extend(kwargs['mutation_roots']);raise AdmissionObserved
        checker=SimpleNamespace(Budget=budget)
        with patch.object(self.q,'packet_declarations'),self.assertRaises(AdmissionObserved):
            self.q.browser_scale_after_exit(packet,packet['paths']['after_exit'],'a'*64,checker)
        self.assertIn(Path(self.old['claims_root'])/'active.lock',captured)
        self.assertNotIn(unrelated/'active.lock',captured)
        # The later real current-reservation consumer still denies a changed pinned body before unlink.
        current.write_text(json.dumps(dict(claims_root=str(unrelated))));binding=dict(path=str(current),sha256=sha256(current));current.write_text(current.read_text()+' ')
        with self.assertRaises(ValueError):self.q.retire_browser_scale_active(dict(reservation=binding),{},None)
        self.assertEqual(marker.read_text(),'keep')
        wrong=self.emit();wrong['claims_root']=str(unrelated);current.write_text(json.dumps(wrong));binding=dict(path=str(current),sha256=sha256(current))
        with self.assertRaises(ValueError):self.q.retire_browser_scale_active(dict(reservation=binding,time_continuation=self.binding),{},None)
        self.assertEqual(marker.read_text(),'keep')

    def test_continuation_proof_and_old_owner_mutations_deny(self):
        for fault in ('missingChrome','wrongClaimID','wrongOwner','missingDebtRoot','changedOldEdgeClock'):
            body=copy.deepcopy(self.body)
            if fault=='missingChrome':del body['chrome']['G']
            elif fault=='wrongClaimID':body['chrome']['D']['consumed']=self.pin('wrong-claim.json',100001)
            elif fault=='wrongOwner':
                body['original_reservation']=self.pin('different-owner.json',self.old)
            elif fault=='missingDebtRoot':
                ledger=dict(method=self.q.STORAGE_LEDGER_METHOD,cumulative_owned_bytes=1000,covered_roots=self.covered[:-1])
                body['history']['ledger']=self.pin('missing-owner-ledger.json',ledger)
            else:
                old=copy.deepcopy(self.old);old['channels']['msedge']['deadline_unix']+=1
                body['original_reservation']=self.pin('changed-old-clock.json',old)
            binding=self.pin('bad-'+fault+'.json',body)
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.q.browser_scale_time_context(binding)

    def test_emitted_reservation_mutations_never_reset_identity_clock_or_time_cap(self):
        original=self.emit()
        for fault in ('id','claims','old-clock','over6h','overall','chrome-clock','extra-slot','new-family'):
            bad=copy.deepcopy(original)
            if fault=='id':bad['slots'][2]['plan_id']='new-id'
            elif fault=='claims':bad['claims_root']='C:\\new-claims'
            elif fault=='old-clock':bad['channels']['chrome']['start_unix']+=1
            elif fault=='over6h':bad['channels']['msedge']['deadline_unix']=bad['channels']['msedge']['start_unix']+21601
            elif fault=='overall':bad['channels']['msedge']['deadline_unix']=205001
            elif fault=='chrome-clock':bad['channels']['chrome']['deadline_unix']+=1
            elif fault=='extra-slot':bad['slots'].append(copy.deepcopy(bad['slots'][0]))
            else:bad['campaign']='replacement'
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.q.browser_scale_time_reservation(self.binding,bad)
        bad=copy.deepcopy(self.body);bad['prior_edge_scale_seconds']=1;b=self.pin('not-unstarted.json',bad)
        with self.assertRaisesRegex(ValueError,'unstarted'):self.q.browser_scale_time_context(b)


if __name__ == '__main__':
    unittest.main(verbosity=2)
