"""Admission and independent filesystem controls; tiny task-owned scratch only."""
import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scale_acceptance import hosted_qualification as q
import suite
import uia
from fake_inputs import job


class Admission(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.selected = self.root / 'config.json'
        self.selected.write_text('{"selection":"synthetic"}')
        self.checker = self.root / 'checker.py'
        self.checker.write_text('# synthetic checker')
        self.value = dict(schema='chopper-acceptance-preflight-v1',status='passed',profile='small',
            host=q.host(),plan_sha256=self.sha(self.selected),workload_started=False,
            acceptance_window_started=False,scale_slot_consumed=False,
            checker=dict(files={str(self.checker):self.sha(self.checker)}),bindings=dict(inputs=['synthetic']))

    def sha(self,path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def receipt(self,value=None):
        value = copy.deepcopy(value or self.value)
        worker = self.root / 'worker-result.json'
        worker.write_text(json.dumps(value))
        value['worker_receipt_sha256'] = self.sha(worker)
        result = self.root / 'result.json'
        result.write_text(json.dumps(value))
        return dict(path=str(result),sha256=self.sha(result))

    def test_exact_preparation_and_parent_worker_custody(self):
        binding = self.receipt()
        self.assertEqual(q.preflight(binding,self.selected,'small')['status'],'passed')
        for name in ('checker.py','config.json','worker-result.json'):
            p = self.root / name
            original = p.read_bytes()
            p.write_bytes(original + b' ')
            with self.subTest(name=name), self.assertRaises(ValueError):
                q.preflight(binding,self.selected,'small')
            p.write_bytes(original)

    def test_recovery_preflight_binding_must_match_actual_worker(self):
        binding=self.receipt()
        path=Path(binding['path']);value=json.loads(path.read_bytes())
        value['recovery']=dict(path=str(self.root/'unvalidated.json'),sha256='a'*64)
        path.write_bytes(q._json_bytes(value));binding['sha256']=self.sha(path)
        with self.assertRaisesRegex(ValueError,'parent/worker recovery mismatch'):
            q.preflight(binding,self.selected,'small')

    def test_failed_wrong_host_path_channel_scope_and_attempt_receipts_deny(self):
        for changes in (dict(status='failed'),dict(status='blocked'),dict(profile='browser-scale'),
                        dict(host={**q.host(),'node':'different'}),dict(workload_started=True),
                        dict(scale_slot_consumed=True),dict(acceptance_window_started=True)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                q.preflight(self.receipt({**self.value,**changes}),self.selected,'small')
        r=q.receipt('small','chrome',{},passed=True,details={})
        self.assertFalse(r['scale_acceptance']);self.assertFalse(r['qualifies_other_profiles'])
        self.assertFalse(r['qualifies_other_channels'])

    def test_picker_independent_adapter_uses_current_facts_and_positive_no_worker_cleanup(self):
        plan=dict(original_lock={'identity':[1,2]})
        cleanup=dict(complete=True,owner=18,jobPids=[18],reaped=1,eof={'browser':dict(stdout=True,stderr=True)})
        private=dict(privateCleanup=cleanup,captureNames=['browser'],childExitCodes=[0],serverStopped=True,helperTempCleanup={'complete':True},browserIdentity=dict(pid=23,created=230),diagnosticForests=[dict(identities=[dict(pid=24,created=240)],retiredIdentities=[dict(pid=25,created=250)],captured={'pids':[24,99]},last={'pids':[26]},membershipChange={'expected':{'pids':[27]},'actual':{'pids':[28]}})])
        report=dict(originalReservationClosedAfterQuiescence=True,reservation=dict(identity=[1,2],owner=dict(pid=17,created=170)),outerFinal={'pids':[17]},innerFinal={'pids':[]},diskSamplerJoined=True,watchdogJoined=True,workerBirth=dict(pid=18,created=180),privateCleanup=cleanup,parentPipeEOF=dict(stdout=True,stderr=True),issueAccounting={'pid':999},observationComplete=False,smokeCaseQualified=False)
        release,facts=q.picker_release_facts(plan,report,private,[dict(pid=22,created=220)])
        self.assertEqual(release,dict(released_after_supervision=True,original_lock_identity=[1,2]))
        actual={row['pid']:row['created'] for row in facts}
        self.assertEqual(set(actual),{17,18,22,23,24,25,26,27,28,99});self.assertIsNone(actual[99]);self.assertEqual(actual[25],[250]);self.assertNotIn(999,actual)
        self.assertFalse(report['smokeCaseQualified'])
        drift=copy.deepcopy(plan);drift['original_lock']['identity']=[1,3]
        with self.assertRaises(ValueError):q.picker_release_facts(drift,report,private,[])
        no_worker={k:v for k,v in report.items() if k not in ('workerBirth','privateCleanup','parentPipeEOF')}
        no_worker.update(noWorkerLaunched=True,innerFinal=None)
        self.assertEqual(q.picker_release_facts(plan,no_worker,None,[])[1],[dict(pid=17,created=[170])])
        for mutation in ('uncertain-launch','monitor','qualification','open-original'):
            bad=copy.deepcopy(no_worker)
            if mutation=='uncertain-launch':bad['workerBirth']=dict(pid=18,created=180)
            elif mutation=='monitor':bad['diskSamplerJoined']=False
            elif mutation=='qualification':bad['smokeCaseQualified']=True
            else:bad['originalReservationClosedAfterQuiescence']=False
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):q.picker_release_facts(plan,bad,None,[])

    def test_picker_membership_producer_record_preserves_unknown_newcomer(self):
        from hosted_picker import diagnostics
        fixture=json.loads((Path(__file__).resolve().parents[2]/'fixtures/picker-membership-change.json').read_bytes())
        row=fixture['forest']
        class Windows:
            def query_job(self,job,max_pids):return row['last']
        forest=diagnostics.HeldForest(Windows(),object(),{'pid':101},{'pid':102},1,lambda:None)
        forest.pids=row['captured']['pids'];forest.handles={pid:pid for pid in forest.pids}
        forest.identities={item['pid']:item for item in row['identities']}
        forest.check_members=lambda handles:None
        with self.assertRaises(diagnostics.JobMembershipChanged):forest.check()
        emitted=json.loads(json.dumps(forest.evidence()))
        self.assertEqual(emitted['membershipChange'],row['membershipChange'])
        cleanup=dict(complete=True,owner=18,jobPids=[18],reaped=1,eof={'browser':dict(stdout=True,stderr=True)})
        private=dict(privateCleanup=cleanup,captureNames=['browser'],childExitCodes=[0],serverStopped=True,
            helperTempCleanup={'complete':True},browserIdentity={'pid':101,'created':1010},diagnosticForests=[emitted])
        report=dict(originalReservationClosedAfterQuiescence=True,reservation=dict(identity=[1,2],owner=dict(pid=17,created=170)),
            outerFinal={'pids':[17]},innerFinal={'pids':[]},diskSamplerJoined=True,watchdogJoined=True,
            workerBirth=dict(pid=18,created=180),privateCleanup=cleanup,parentPipeEOF=dict(stdout=True,stderr=True))
        _,facts=q.picker_release_facts(dict(original_lock={'identity':[1,2]}),report,private,[dict(pid=19,created=190)])
        actual={item['pid']:item['created'] for item in facts}
        self.assertEqual(set(actual),{17,18,19,*fixture['expected_facts']['known_pids'],112})
        self.assertIsNone(actual[112])
        for pid in fixture['expected_facts']['known_pids']:self.assertEqual(actual[pid],[pid*10])
        for name in ('expected','actual'):
            bad=copy.deepcopy(private);bad['diagnosticForests'][0]['membershipChange'][name]=[112]
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'census requires its PID list'):
                q.picker_release_facts(dict(original_lock={'identity':[1,2]}),report,bad,[])

    def test_picker_after_exit_real_files_bind_configuration_preflight_and_both_report_shapes(self):
        import importlib.util
        checker_path=Path(__file__).resolve().parents[2]/'acceptance-preflight.py'
        spec=importlib.util.spec_from_file_location('picker_after_checker',checker_path);checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
        original=self.root/'original';original.write_bytes(b'0');stamp=original.stat()
        lock=dict(path=str(original),identity=[stamp.st_dev,stamp.st_ino])
        for no_worker in (True,False):
            root=self.root/('no-worker' if no_worker else 'worker');root.mkdir();attempt=root/'attempt1';attempt.mkdir()
            candidate=root/'candidate.json';plan=dict(schema='chopper-hosted-picker-qualification-v1',root=str(root),controller_root=str(self.root/'controller'),input_directories={},channel='chrome',case='processing-cancel',original_lock=lock)
            candidate.write_text(json.dumps(plan));self.selected=candidate
            self.value.update(profile='actual-picker',plan_sha256=self.sha(candidate));pref=self.receipt()
            report=dict(profile='actual-picker',channel='chrome',case='processing-cancel',configSha256=self.sha(candidate),preflight=pref,originalReservationClosedAfterQuiescence=True,reservation=dict(identity=lock['identity'],owner=dict(pid=17,created=170)),outerFinal={'pids':[17]},innerFinal=None,diskSamplerJoined=True,watchdogJoined=True,observationComplete=False,smokeCaseQualified=False,noWorkerLaunched=no_worker)
            if not no_worker:
                cleanup=dict(complete=True,owner=18,jobPids=[18],reaped=1,eof={'browser':dict(stdout=True,stderr=True)})
                private=dict(privateCleanup=cleanup,captureNames=['browser'],childExitCodes=[1],serverStopped=True,helperTempCleanup={'complete':True},diagnosticForests=[])
                (attempt/'worker-result.json').write_text(json.dumps(private));(attempt/'browser.birth.json').write_text(json.dumps(dict(pid=19,created=190)))
                report.update(workerBirth=dict(pid=18,created=180),privateCleanup=cleanup,innerFinal={'pids':[]},parentPipeEOF=dict(stdout=True,stderr=True))
            receipt=attempt/'receipt.json';destination=root/'after-exit'
            request=dict(schema='chopper-picker-after-exit-v1',profile='actual-picker',root=str(root),configuration=str(candidate),receipt=str(receipt),preflight=pref['path'],original_lock=lock,output=str(destination))
            small=SimpleNamespace(runner=SimpleNamespace(contain_session=lambda:None),windows=object())
            timer=SimpleNamespace(cancel=lambda:None,join=lambda:None,is_alive=lambda:False)
            def observe(windows,facts,release,original_path,deadline,result,**kw):
                self.assertEqual(release['original_lock_identity'],lock['identity']);self.assertEqual(original_path,str(original));self.assertIn(dict(pid=17,created=[170]),facts)
                result.update(processes=[],original_byte0_available=True,probe_closed=True)
            with patch.object(checker,'load',return_value=small),patch.object(checker.Budget,'install'),patch.object(q,'independent_observation',side_effect=observe) as independent:
                if no_worker:
                    bad=dict(report,configSha256='0'*64);receipt.write_text(json.dumps(bad))
                    with self.assertRaisesRegex(ValueError,'hash drift'):q.picker_after_exit(request,destination,'a'*64,checker,self.sha(receipt),timer=timer)
                    self.assertFalse(destination.exists());independent.assert_not_called()
                    bad=dict(report,preflight=dict(pref,path=str(root/'wrong-pref.json')));receipt.write_text(json.dumps(bad))
                    with self.assertRaisesRegex(ValueError,'exact current picker preflight'):q.picker_after_exit(request,destination,'a'*64,checker,self.sha(receipt),timer=timer)
                    self.assertFalse(destination.exists());independent.assert_not_called()
                receipt.write_text(json.dumps(report));result=q.picker_after_exit(request,destination,'a'*64,checker,self.sha(receipt),timer=timer)
                independent.assert_called_once();self.assertEqual(result['status'],'passed-after-exit');self.assertFalse(result['qualification']);self.assertFalse(result['smoke_case_qualification_passed'])
                self.assertTrue(json.loads((destination/'result.json').read_text())['timer_joined'])

    def test_compact_picker_receipt_still_binds_every_configuration_byte(self):
        self.value.update(profile='actual-picker', bindings=dict(channel='chrome', case='success'))
        self.selected.write_text(json.dumps(dict(inputs=[dict(path='synthetic', sha256='a'*64)])))
        self.value['plan_sha256'] = self.sha(self.selected)
        binding = self.receipt()
        self.assertEqual(q.preflight(binding, self.selected, 'actual-picker')['status'], 'passed')
        changed = json.loads(self.selected.read_text())
        changed['inputs'][0]['sha256'] = 'b'*64
        self.selected.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, 'hash drift'):
            q.preflight(binding, self.selected, 'actual-picker')

    def test_native_ui_matches_only_preparation_and_cannot_become_hosted_qualification(self):
        self.value['profile']='native-ui'
        binding=self.receipt()
        self.assertEqual(q.preflight(binding,self.selected,'native-ui')['status'],'passed')
        self.assertNotIn('native-ui',q.PROFILES)
        with self.assertRaisesRegex(ValueError,'installed hosted profile'):
            q.receipt('native-ui','chrome',binding,passed=True,details={})
        self.selected.write_bytes(self.selected.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'hash drift'):
            q.preflight(binding,self.selected,'native-ui')

    def test_parent_cannot_substitute_worker_bindings(self):
        binding=self.receipt()
        result=self.root/'result.json';value=json.loads(result.read_text())
        value['bindings']={'inputs':['changed']};result.write_text(json.dumps(value))
        binding['sha256']=self.sha(result)
        with self.assertRaisesRegex(ValueError,'parent/worker mismatch'):
            q.preflight(binding,self.selected,'small')


class FilesystemOracle(unittest.TestCase):
    def fixture(self,base):
        output=base/'attempt1/output';output.mkdir(parents=True)
        name='chopper-results-00000000-0000-4000-8000-000000000000'
        dest=output/name;dest.mkdir()
        values=[b'id,text,tag\r\n3,"say ""hi""",\xe6\xbc\xa2\r\n',b'id,text,tag\r\n4,"line\nfeed",\xf0\x9f\x99\x82\r\n']
        for n,b in enumerate(values,1):(dest/f'part-{n:08d}.csv').write_bytes(b)
        metadata=dict(type='job',schema_version=1,config=job(),analysis=dict(rows=2,output_files=2,
            output_csv_bytes=66,header=['id','text','tag'],logical_digest='bf97e5d6a4e6d5f0c11ce01927bd9af53b05ccfc05a66481a95704f374abe3ad'))
        rows=[metadata]+[dict(type='output',path=f'part-{n:08d}.csv',rows=1,csv_bytes=33,
            stored_bytes=33,compressed_target_exceeded=False) for n in (1,2)]
        (dest/'manifest.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
        (dest/'CHOPPER-COMPLETE.json').write_bytes(b'{"complete":true,"files":3,"engine":"chopper-browser","version":1}\n')
        return output,dest,'output/'+name,suite.dir_identity(output)

    def test_exact_bytes_decoded_fields_order_caps_manifest_and_marker(self):
        with tempfile.TemporaryDirectory() as d,patch.object(suite,'NATIVE_ROOT',d),patch.object(suite,'document',lambda name:job(),create=True):
            output,dest,public,birth=self.fixture(Path(d))
            self.assertTrue(suite.verify_export(output,birth,public)['complete'])
            import csv
            fields=[]
            for p in sorted(dest.glob('*.csv')):
                with p.open(newline='',encoding='utf-8') as f:
                    reader=csv.reader(f);self.assertEqual(next(reader),['id','text','tag']);fields.extend(reader)
                self.assertLessEqual(p.stat().st_size,40)
            self.assertEqual(fields,[['3','say "hi"','漢'],['4','line\nfeed','🙂']])

    def test_incomplete_wrong_csv_manifest_extra_files_and_directory_replacement_deny(self):
        for fault in ('marker-missing','marker-empty','marker-false','marker-count','marker-type',
                      'csv-oversized','csv-order','extra-file','manifest-wrong','path','birth'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d,patch.object(suite,'NATIVE_ROOT',d),patch.object(suite,'document',lambda name:job(),create=True):
                out,dest,public,birth=self.fixture(Path(d));marker=dest/'CHOPPER-COMPLETE.json'
                if fault=='marker-missing':marker.unlink()
                elif fault=='marker-empty':marker.write_text('')
                elif fault.startswith('marker-'):
                    m=json.loads(marker.read_text());m.update({'complete':False} if fault=='marker-false' else {'files':2} if fault=='marker-count' else {'version':True});marker.write_text(json.dumps(m))
                elif fault=='csv-oversized':(dest/'part-00000001.csv').write_bytes(b'x'*41)
                elif fault=='csv-order':(dest/'part-00000001.csv').write_bytes((dest/'part-00000002.csv').read_bytes())
                elif fault=='extra-file':(dest/'extra').write_bytes(b'')
                elif fault=='manifest-wrong':(dest/'manifest.jsonl').write_text('{}\n')
                elif fault=='path':public='cancelled'
                elif fault=='birth':birth={'dev':0,'ino':0}
                with self.assertRaises((AssertionError,KeyError,ValueError)):
                    suite.verify_export(out,birth,public)

    def test_original_release_requires_eof_reap_job_and_watchdog_quiescence(self):
        owner=123;report=dict(captureNames=['browser','uia'],childExitCodes=[0,0],
            privateCleanup=dict(complete=True,eof={n:dict(stdout=True,stderr=True) for n in ('browser','uia')},reaped=2,owner=owner,jobPids=[owner]))
        import os
        check=lambda value=report,eof=dict(stdout=True,stderr=True),inner=[],outer=[os.getpid()],watch=False:suite.private_release_gate(value,eof,inner,outer,owner,watch)
        check()
        for change in ('eof','reaped','owner','job','capture'):
            value=copy.deepcopy(report)
            if change=='eof':value['privateCleanup']['eof']['uia']['stderr']=False
            elif change=='reaped':value['privateCleanup']['reaped']=1
            elif change=='owner':value['privateCleanup']['owner']=999
            elif change=='job':value['privateCleanup']['jobPids'].append(99)
            else:value['captureNames'].append('unreaped')
            with self.subTest(change=change),self.assertRaises(AssertionError):check(value)
        for args in (dict(inner=[99]),dict(outer=[os.getpid(),99]),dict(watch=True),dict(eof=dict(stdout=True,stderr=False))):
            with self.assertRaises(AssertionError):check(**args)

    def test_real_committed_baseline_survives_failure_and_second_export_then_drift_denies(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(suite,'NATIVE_ROOT',directory),patch.object(suite,'document',lambda name:job(),create=True):
            output,dest,public,birth=self.fixture(Path(directory))
            preserved=suite.committed_snapshot(output,birth,public)
            self.assertTrue(suite.verify_preserved_export(output,birth,preserved))
            second=output/'chopper-results-00000000-0000-4000-8000-000000000001';second.mkdir()
            with self.assertRaisesRegex(AssertionError,'unexpected output'):suite.verify_preserved_export(output,birth,preserved)
            for source in dest.iterdir():(second/source.name).write_bytes(source.read_bytes())
            self.assertTrue(suite.verify_export(output,birth,'output/'+second.name,preserved=preserved)['complete'])
            first=dest/'part-00000001.csv';before=first.stat();os.utime(first,ns=(before.st_atime_ns,before.st_mtime_ns+1000000000))
            with self.assertRaisesRegex(AssertionError,'committed hosted export changed'):
                suite.verify_export(output,birth,'output/'+second.name,preserved=preserved)


class HelperCache(unittest.TestCase):
    LOG=b'{"logTime": "1113/075004", "correlationVector":"CAC7108CC85D4CBDB5B740F21B4676CD","action":"FETCH_UX_CONFIG", "result":""}\n'

    def fixture(self, root):
        helper=root/'attempt1/helper-temp';helper.mkdir(parents=True)
        empty=helper/'empty';empty.mkdir()
        log=helper/'cv_debug.log';log.write_bytes(self.LOG)
        owner=os.getpid()
        node=dict(pid=1001,parent=owner,image='selected-node.exe',created=100)
        (helper.parent/'browser.birth.json').write_text(json.dumps(node))
        report=dict(captureNames=['browser'],childExitCodes=[0],browserClosed=True,
            serverStopped=True,nodeExit=0,heldBrowserBirth=200,
            browserIdentity=dict(pid=1002,parent=1001,image='selected-edge.exe',created=200),
            privateCleanup=dict(complete=True,eof=dict(browser=dict(stdout=True,stderr=True)),
                reaped=1,owner=owner,jobPids=[owner]))
        plan=dict(channel='msedge',node=dict(path='selected-node.exe'),browser=dict(path='selected-edge.exe'))
        return helper,log,empty,report,plan

    def invoke(self, root, helper, report, plan, primitive=uia.retain_cache):
        with patch.multiple(suite,NATIVE_ROOT=str(root),PLAN=plan,create=True):
            return suite.cleanup_helper(helper,report,suite.dir_identity(helper),retain_cache=primitive)

    def test_known_edge_log_is_retained_with_no_deletion_or_empty_credit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);helper,log,empty,report,plan=self.fixture(root)
            result=self.invoke(root,helper,report,plan)
            self.assertTrue(result['complete']);self.assertTrue(result['retained'])
            self.assertFalse(result['empty']);self.assertEqual(result['deletedFiles'],0)
            self.assertEqual(result['bytes'],len(self.LOG))
            self.assertEqual(result['knownBrowserLogs'][0]['sha256'],hashlib.sha256(self.LOG).hexdigest())
            self.assertEqual(log.read_bytes(),self.LOG);self.assertTrue(empty.is_dir())

    def test_unknown_files_and_channels_deny_before_any_directory_removal(self):
        for fault in ('unknown-file','chrome','unknown-channel','wrong-content','wrong-birth','not-closed'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
                root=Path(d);helper,log,empty,report,plan=self.fixture(root)
                if fault=='unknown-file':(helper/'other.log').write_bytes(b'untouched')
                elif fault in ('chrome','unknown-channel'):plan['channel']=fault
                elif fault=='wrong-content':log.write_bytes(self.LOG.replace(b'FETCH_UX_CONFIG',b'OTHER_OPERATION'))
                elif fault=='wrong-birth':report['heldBrowserBirth']=201
                elif fault=='not-closed':report['browserClosed']=False
                primitive=unittest.mock.Mock(wraps=uia.retain_cache)
                with self.assertRaises(AssertionError):self.invoke(root,helper,report,plan,primitive)
                primitive.assert_not_called();self.assertTrue(log.exists());self.assertTrue(empty.is_dir())

    def test_reparse_and_hardlinked_log_deny_without_deletion(self):
        for fault in ('reparse','hardlink'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
                root=Path(d);helper,log,empty,report,plan=self.fixture(root)
                primitive=unittest.mock.Mock(wraps=uia.retain_cache)
                if fault=='hardlink':
                    os.link(log,root/'second-link')
                    with self.assertRaises(AssertionError):self.invoke(root,helper,report,plan,primitive)
                else:
                    actual_lstat=Path.lstat
                    def lstat(p,*args,**kwargs):
                        value=actual_lstat(p,*args,**kwargs)
                        if p!=log:return value
                        fields={name:getattr(value,name) for name in ('st_mode','st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink')}
                        return SimpleNamespace(**fields,st_file_attributes=0x400)
                    with patch.object(Path,'lstat',lstat),self.assertRaises(AssertionError):
                        self.invoke(root,helper,report,plan,primitive)
                primitive.assert_not_called();self.assertTrue(log.exists());self.assertTrue(empty.is_dir())

    def test_mutation_during_retention_denies_and_preserves_every_file(self):
        for fault in ('content','membership'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d:
                root=Path(d);helper,log,empty,report,plan=self.fixture(root)
                def primitive(*args):
                    result=uia.retain_cache(*args)
                    if fault=='content':log.write_bytes(self.LOG+b' ')
                    else:(helper/'unexpected').write_bytes(b'untouched')
                    return result
                with self.assertRaises(AssertionError):self.invoke(root,helper,report,plan,primitive)
                self.assertTrue(log.exists());self.assertTrue(empty.is_dir())

    def test_empty_tree_keeps_original_empty_directory_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);helper,log,empty,report,plan=self.fixture(root);log.unlink()
            primitive=unittest.mock.Mock(wraps=uia.retain_cache)
            result=self.invoke(root,helper,report,plan,primitive)
            self.assertTrue(result['complete']);self.assertTrue(result['emptyOnly'])
            self.assertEqual(list(helper.iterdir()),[]);primitive.assert_not_called()


class HistoricalCharges(unittest.TestCase):
    def test_original_receipts_elapsed_and_expired_windows_cannot_be_refunded(self):
        from datetime import datetime,timezone
        now=1700000000  # exact fake clock; datetime microseconds must not round into the future
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);anchor_path=root/'anchor.json'
            old=dict(native_path=str(root/'old.json'),sha256='a'*64,elapsed=1)
            window=dict(charged_seconds=3,reason='synthetic expired window')
            anchor=dict(elapsed=2,issueAccounting=dict(prior_attempts=[old],expired_windows=[window],expired_window_seconds_charged=3))
            anchor_path.write_text(json.dumps(anchor));sha=hashlib.sha256(anchor_path.read_bytes()).hexdigest()
            anchor_row=dict(native_path=str(anchor_path),sha256=sha,elapsed=2)
            accounting=dict(window_start_utc=datetime.fromtimestamp(now-1,timezone.utc).isoformat(),
                absolute_stop_utc=datetime.fromtimestamp(now+200,timezone.utc).isoformat(),prior_attempts=[old,anchor_row],
                prior_elapsed_seconds=3,expired_windows=[window],expired_window_seconds_charged=3)
            custody=dict(parentHostSchedulingApproved=True,freshNativeCustodyReviewed=True,packageOSBrowserHashesReviewed=True,
                retainedFixtureBytes=1008260,extraRetainedSourceFixtureBytes=1444,
                baselineCompletedManifestSha256='b'*64,sampleUtc=datetime.fromtimestamp(now,timezone.utc).isoformat())
            plan=dict(parent_reviewed=True,historical_anchor=dict(path=str(anchor_path),sha256=sha),
                      inputs=[dict(path=r['native_path'],sha256=r['sha256']) for r in accounting['prior_attempts']])
            # A later failed receipt is applicable even when absent from the
            # original anchor. Complete declaration validation is not just the
            # minimum historical anchor check or the live 60-second gate.
            later=dict(native_path=str(root/'later-failed.json'),sha256='c'*64,elapsed=4)
            with_later=copy.deepcopy(accounting)
            with_later['prior_attempts'].append(later);with_later['prior_elapsed_seconds']+=4
            with self.assertRaisesRegex(AssertionError,'history cannot be omitted'):
                suite.validate_history(plan,with_later)
            complete=copy.deepcopy(plan);complete['inputs'].append(dict(path=later['native_path'],sha256=later['sha256']))
            suite.validate_history(complete,with_later)  # No clock/custody/owner is needed here.
            with patch.object(suite,'PLAN',plan,create=True):
                for fault in (None,'missing-receipt','changed-elapsed','expired-refund'):
                    value=copy.deepcopy(accounting)
                    if fault=='missing-receipt':value['prior_attempts']=[anchor_row];value['prior_elapsed_seconds']=2
                    elif fault=='changed-elapsed':value['prior_attempts'][0]['elapsed']=0;value['prior_elapsed_seconds']=2
                    elif fault=='expired-refund':value['expired_windows']=[];value['expired_window_seconds_charged']=0
                    with patch.object(suite,'document',lambda name:value if name=='accounting.json' else custody,create=True):
                        if fault is None:suite.authorize(root,now)
                        else:
                            with self.subTest(fault=fault),self.assertRaises(AssertionError):suite.authorize(root,now)

class LiveCustody(unittest.TestCase):
    def fixture(self,stack,directory):
        import control,config,time
        root=Path(directory);out=root/'attempt1';out.mkdir()
        tiny=root/'tiny.csv';tiny.write_bytes(b'id,text,tag\r\n3,"say ""hi""",\xe6\xbc\xa2\r\n4,"line\nfeed",\xf0\x9f\x99\x82\r\n')
        s=tiny.stat();input_binding=dict(path=str(tiny),bytes=53,sha256=suite.INPUT_SHA256,nativeStat=dict(dev=s.st_dev,ino=s.st_ino,bytes=s.st_size,mtime_ns=s.st_mtime_ns))
        lock=root/'original.lock';lock.write_bytes(b'lock');ls=lock.stat()
        custody=dict(sampleUtc='1970-01-01T00:00:00+00:00',sampledOwnedBytes=1000,retainedFixtureBytes=53,extraRetainedSourceFixtureBytes=1820,reusedInput=input_binding,retainedInputPaths=[str(tiny)],inputInventoryComplete=True,selectedZIP={'path':'selected.zip'},capacityObservation={'volume':dict(root='C:\\',filesystem='NTFS',serial=7)},baselineCompletedManifestSha256='a'*64)
        cp=root/'custody.json';cp.write_text(json.dumps(custody));selected=root/'candidate.json';selected.write_text('{}')
        plan=dict(inputs=[dict(path=str(tiny),sha256=suite.INPUT_SHA256,stat=config.stamp(tiny))],input_directories={},documents={'custody.json':str(cp)},input={'path':str(tiny)},growth_bytes=4*1024**3,owned_cap_bytes=32*1024**3,original_lock=dict(path=str(lock),identity=[ls.st_dev,ls.st_ino]))
        for name in ('python','node','browser'):
            path=root/(name+'.exe');path.write_bytes(name.encode());plan[name]=dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            plan['inputs'].append(dict(**plan[name],stat=config.stamp(path)))
        plan['inputs'].append(dict(path=str(cp),sha256=hashlib.sha256(cp.read_bytes()).hexdigest(),stat=config.stamp(cp)))
        runtime=dict(powershell=dict(path='known.ps',sha256='b'*64),assemblies={},nativeImages={},windowsVersion=[1,2,3,4,5])
        baseline={f'part-{i:08d}.csv':dict(bytes=33,sha256=hashlib.sha256(value).hexdigest(),dev=1,ino=i,mtime_ns=1) for i,value in enumerate([b'id,text,tag\r\n3,"say ""hi""",\xe6\xbc\xa2\r\n',b'id,text,tag\r\n4,"line\nfeed",\xf0\x9f\x99\x82\r\n'],1)}
        baseline['manifest.jsonl']=dict(bytes=1,sha256='a'*64,dev=1,ino=3,mtime_ns=1)
        config_binding=dict(path=str(selected),sha256=hashlib.sha256(selected.read_bytes()).hexdigest());pref=dict(path='exact-pref.json',sha256='c'*64)
        docs={'custody.json':custody,'uia-binding.json':runtime}
        observer=dict(pid=os.getpid(),parent=1,image=plan['python']['path'],created=123)
        windows=SimpleNamespace(process_identity=lambda pid:dict(observer))
        modules={'suite':suite,'browser-small-windows':windows}
        stack.enter_context(patch.multiple(control,ROOT=root,OUT=out,PLAN=plan,CONFIG_PATH=str(selected),CONFIG_SHA=config_binding['sha256'],PREPARATION=pref,load=lambda name:modules[name],document=lambda name:docs[name],owned_roots=lambda *args:[root],verify_custody=lambda:custody,native_volume=lambda:custody['capacityObservation']['volume'],sys=SimpleNamespace(getwindowsversion=lambda:runtime['windowsVersion'])))
        stack.enter_context(patch.multiple(suite,PLAN=plan,REUSED_INPUT=str(tiny),CONFIG_BINDING=config_binding,PREFLIGHT_BINDING=pref,document=lambda name:docs[name],create=True))
        stack.enter_context(patch.object(suite,'authorize_history',return_value=custody))
        stack.enter_context(patch.object(suite,'baseline_completed',return_value=baseline))
        stack.enter_context(patch.object(config,'physical_capacity',return_value=200*1024**3))
        def after(marker):
            end=time.monotonic()
            return dict(started=marker,finished=end,value=dict(owned=1100,free=200*1024**3))
        disk=SimpleNamespace(after=after)
        return SimpleNamespace(root=root,tiny=tiny,plan=plan,custody=custody,baseline=baseline,disk=disk,context=config_binding)

    def test_real_reobservation_admits_old_accounting_without_reset(self):
        import contextlib,control,time
        with tempfile.TemporaryDirectory() as d,contextlib.ExitStack() as stack:
            f=self.fixture(stack,d);before=copy.deepcopy(f.custody)
            binding,context,current=control.live_custody('worker',f.baseline,f.disk)
            suite.authorize(f.root,time.time(),observation=binding,context=context)
            self.assertEqual(current,1100);self.assertEqual(f.custody,before)
            live=json.loads(Path(binding['path']).read_text())
            self.assertEqual(live['accounting_baseline']['sampledOwnedBytes'],1000)
            self.assertEqual(live['accounting_baseline']['extraRetainedSourceFixtureBytes'],1820)
            self.assertGreater(live['started_unix'],0)

    def test_missing_mismatched_expired_or_tampered_live_receipt_denies(self):
        import contextlib,control,time
        with tempfile.TemporaryDirectory() as d,contextlib.ExitStack() as stack:
            f=self.fixture(stack,d);binding,context,current=control.live_custody('parent',f.baseline,f.disk);target=Path(binding['path']);original=target.read_bytes();live=json.loads(original)
            with self.assertRaises(AssertionError):suite.authorize(f.root,time.time(),context=context)
            with self.assertRaises(AssertionError):suite.authorize(f.root,live['started_unix']+60.001,observation=binding,context=context)
            for field in ('context','input','selectedZIP','executables','uia','volume','original_lock','accounting_baseline','retained_inputs','baseline_completed','disk'):
                bad=copy.deepcopy(live)
                if field=='context':bad[field]['config']['sha256']='d'*64
                elif field=='disk':bad[field]['started_unix']=live['started_unix']-1
                else:bad[field]=[] if isinstance(bad[field],list) else {}
                target.write_text(json.dumps(bad));repinned=dict(path=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest())
                with self.subTest(field=field),self.assertRaises((AssertionError,KeyError)):
                    suite.authorize(f.root,time.time(),observation=repinned,context=context)
            target.write_bytes(original+b' ')
            with self.assertRaisesRegex(AssertionError,'expected hash drift'):suite.authorize(f.root,time.time(),observation=binding,context=context)

    def test_actual_input_executable_and_baseline_drift_deny_before_receipt(self):
        import contextlib,control
        for fault in ('input','input-body','node','baseline','disk'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d,contextlib.ExitStack() as stack:
                f=self.fixture(stack,d)
                if fault=='input':f.tiny.write_bytes(b'changed')
                elif fault=='input-body':
                    old=f.tiny.stat();f.tiny.write_bytes(b'x'*53);os.utime(f.tiny,ns=(old.st_atime_ns,old.st_mtime_ns))
                elif fault=='node':Path(f.plan['node']['path']).write_bytes(b'changed')
                elif fault=='baseline':stack.enter_context(patch.object(suite,'baseline_completed',return_value={}))
                else:f.disk.after=lambda marker:(_ for _ in ()).throw(OSError('pending disk observation'))
                with self.assertRaises((AssertionError,OSError)):control.live_custody('worker',f.baseline,f.disk)
                self.assertFalse((f.root/'attempt1/worker-live-custody.json').exists())

    def test_candidate_original_custody_and_owned_receipt_alias_drift_deny(self):
        import contextlib,control,time
        for fault in ('candidate','original-custody','receipt-hardlink','binding'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d,contextlib.ExitStack() as stack:
                f=self.fixture(stack,d);binding,context,current=control.live_custody('worker',f.baseline,f.disk)
                if fault=='candidate':Path(context['config']['path']).write_text('{"changed":true}')
                elif fault=='original-custody':Path(context['original_custody']['path']).write_text('{"changed":true}')
                elif fault=='receipt-hardlink':os.link(binding['path'],f.root/'unwanted-alias')
                else:
                    context=copy.deepcopy(context);context['config']['sha256']='d'*64
                    value=json.loads(Path(binding['path']).read_text());value['context']=context
                    Path(binding['path']).write_text(json.dumps(value));binding['sha256']=hashlib.sha256(Path(binding['path']).read_bytes()).hexdigest()
                with self.assertRaises(AssertionError):suite.authorize(f.root,time.time(),observation=binding,context=context)

    def test_drift_during_real_observation_denies_before_receipt(self):
        import contextlib,control
        for fault in ('node','input','membership'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as d,contextlib.ExitStack() as stack:
                f=self.fixture(stack,d);original_after=f.disk.after
                directory=f.root/'immutable';directory.mkdir();f.plan['input_directories'][str(directory)]=[]
                def drift(marker):
                    if fault=='node':Path(f.plan['node']['path']).write_bytes(b'changed during observation')
                    elif fault=='input':f.tiny.write_bytes(b'changed during observation')
                    else:(directory/'unknown.py').write_text('new source member')
                    return original_after(marker)
                f.disk.after=drift
                with self.assertRaisesRegex(AssertionError,'input metadata changed|input inventory changed'):
                    control.live_custody('worker',f.baseline,f.disk)
                self.assertFalse((f.root/'attempt1/worker-live-custody.json').exists())

class CancellationFiles(unittest.TestCase):
    def test_case_jobs_reuse_original_job_without_mutation_or_new_fixture(self):
        original=job();before=copy.deepcopy(original)
        processing=suite.cancellation_job(original,'processing-cancel')
        exporting=suite.cancellation_job(original,'export-cancel')
        self.assertEqual(original,before)
        self.assertEqual(len(processing['operations']),17)
        self.assertEqual(processing['operations'][-1],dict(type='shuffle',strategy='uniform'))
        for index,operation in enumerate(processing['operations']):
            self.assertEqual(operation,dict(type='shuffle',strategy='uniform') if index%2==0 else dict(type='partition',columns=['v']))
        self.assertEqual(processing['resources']['temp_bytes'],64*1024**2)
        self.assertEqual(processing['resources']['max_files'],4)
        self.assertEqual(processing['resources']['max_record_bytes'],1024)
        self.assertEqual(exporting['resources']['max_record_bytes'],64)
        self.assertEqual(exporting['operations'],[])
        self.assertEqual(exporting['limits']['rows'],100)
        self.assertEqual(exporting['resources']['max_files'],1200)
        for value in (processing,exporting):
            self.assertEqual(value['input'],original['input'])
            self.assertEqual(value['resources']['memory_mb'],64)
        with self.assertRaises(AssertionError):suite.cancellation_job(original,'success')

    def test_actual_representative_lineage_fits_record_metadata_budget(self):
        processing=suite.cancellation_job(job(),'processing-cancel');lineage=[];sizes=[];steps=[]
        for index,operation in enumerate(processing['operations'],1):
            if operation['type']=='partition':
                self.assertEqual(operation['columns'],['v'])
                # Selected child_metadata::Entry::Values serializes the full parent array.
                lineage.append(dict(operation=index,values=['v']))
                sizes.append(len(json.dumps(lineage,separators=(',',':')).encode('utf-8')));steps.append(index)
        self.assertEqual(sizes,[32,63,94,125,157,189,221,253])
        self.assertEqual(next(step for step,size in zip(steps,sizes) if size>64),6)
        self.assertLessEqual(max(sizes),processing['resources']['max_record_bytes'])

    def test_processing_stage_semantics_match_live_browser_predicate_and_parent(self):
        states=[(dict(status='RUNNING',phase='Reading and validating CSV',rows=65536),True),
            (dict(status='RUNNING',phase='Serializing output',rows=65536),True),
            (dict(status='RUNNING',phase='Preparing operation 6 of 17',rows=0),True)]
        states += [(dict(status='RUNNING',phase='Preparing operation %s of 17'%index,rows=0),True) for index in range(2,18)]
        states += [(dict(status='RUNNING',phase=phase,rows=0),False) for phase in ('Reading CSV','Writing output','Saving results (1/1101)','Preparing operation 1 of 17','Preparing operation 0 of 17','Preparing operation 18 of 17','Preparing operation 06 of 17','Preparing operation 6 of 18','Preparing operation -1 of 17','Preparing operation 6 of 17 trailing')]
        states += [(dict(status=status,phase='Preparing operation 6 of 17',rows=0),False) for status in ('COMPLETE','FAILED','CANCELLED','IDLE')]
        states += [(dict(status='RUNNING',phase=phase,rows=1),False) for phase in ('','unexpected','Writing output','Saving results (1/2)','Preparing operation 0 of 17','Preparing operation 18 of 17','Complete')]
        states += [(dict(status='RUNNING',phase='Preparing operation 6 of 17',rows=rows),False) for rows in (-1,False,None,0.5,'0',2**53)]
        for observed,wanted in states:
            with self.subTest(observed=observed):
                self.assertEqual(suite.processing_observation(observed),wanted)
                def event(stamp,**extra):return dict(observed,monotonicMs=stamp,**extra)
                value=dict(case='processing-cancel',active=event(1),beforeClick=event(3),capture=dict(installed=dict(monotonicMs=2),events=[event(4,trusted=True,type='click')],taken=dict(monotonicMs=5)),terminal=dict(status='CANCELLED',monotonicMs=6))
                if wanted:suite.cancellation_click(value,'processing-cancel')
                else:
                    with self.assertRaises(AssertionError):suite.cancellation_click(value,'processing-cancel')
        # Execute the actual function passed to Playwright, not a copied predicate.
        script=r"""
const assert=require('node:assert/strict'),vm=require('node:vm');
const {cancelCurrent,cancellationObservation}=require(process.argv[1]);const states=JSON.parse(process.argv[2]);
const cases=states.map(([state,wanted])=>['processing-cancel',state,wanted]);
for(const [phase,wanted] of [['Saving results (0/1101)',false],['Saving results (1/1101)',true],['Saving results (1101/1101)',true],['Saving results (1102/1101)',false],['Saving results (1/0)',false],['Saving results (0/0)',false]])cases.push(['export-cancel',{status:'RUNNING',phase,rows:0},wanted]);
(async()=>{for(const [which,state,wanted] of cases){
 let accepted=true;try{cancellationObservation(state,which);}catch{accepted=false;}assert.equal(accepted,wanted,JSON.stringify(state));
 let called=false;
 const page={waitForFunction:async(fn,which)=>{called=true;
  const nodes={status:{textContent:state.status},phase:{textContent:state.phase},'progress-detail':{textContent:String(state.rows)+' rows'}};
  let value=false;try{value=vm.runInNewContext('('+fn.toString()+')(which)',{which,document:{querySelector:name=>nodes[name.slice(1)]}});}catch(error){assert.match(error.message,/terminal before cancellation phase/);}
  // DOM text cannot retain the original numeric type; test invalid numeric values in the typed observation above.
  if(Number.isSafeInteger(state.rows)&&state.rows>=0)assert.equal(value,wanted,JSON.stringify(state));
  throw Error('stop before any click');
 }};
 await assert.rejects(cancelCurrent(page,which,()=>{throw Error('must not emit');}),/stop before any click/);assert(called);
}})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run(['node','-e',script,str(Path(suite.__file__).with_name('hosted.cjs')),json.dumps(states)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_real_cancelled_output_has_no_marker_and_processing_has_no_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);output=root/'attempt1/output';output.mkdir(parents=True)
            with patch.object(suite,'NATIVE_ROOT',str(root)):
                birth=suite.dir_identity(output)
                self.assertTrue(suite.verify_cancelled_output(output,birth,'processing-cancel')['markerAbsent'])
                folder=output/'chopper-results-00000000-0000-4000-8000-000000000000';folder.mkdir()
                (folder/'part-00000001.csv').write_bytes(b'v\nx\n')
                self.assertFalse(suite.verify_cancelled_output(output,birth,'export-cancel')['complete'])
                with self.assertRaises(AssertionError):suite.verify_cancelled_output(output,birth,'processing-cancel')
                (folder/'CHOPPER-COMPLETE.json').write_bytes(b'{"complete":')
                self.assertEqual(suite.verify_cancelled_output(output,birth,'export-cancel')['marker']['status'],'invalid')
                (folder/'CHOPPER-COMPLETE.json').write_bytes(b'{"complete":true,"files":2,"engine":"chopper-browser","version":1}\n')
                with self.assertRaisesRegex(AssertionError,'valid committed marker'):suite.verify_cancelled_output(output,birth,'export-cancel')
                self.assertTrue((folder/'CHOPPER-COMPLETE.json').exists(),'oracle never deletes a committed export')

    def test_actual_click_state_and_order_are_authoritative(self):
        active=dict(status='RUNNING',phase='Reading CSV',rows=65536,monotonicMs=1)
        click=dict(active,monotonicMs=4,trusted=True,type='click')
        value=dict(case='processing-cancel',active=active,beforeClick=dict(active,monotonicMs=3),capture=dict(installed=dict(monotonicMs=2),events=[click],taken=dict(monotonicMs=5)),terminal=dict(status='CANCELLED',monotonicMs=6))
        self.assertEqual(suite.cancellation_click(value,'processing-cancel'),click)
        for fault in ('phase','terminal','untrusted','order'):
            changed=copy.deepcopy(value)
            if fault=='phase':changed['capture']['events'][0]['phase']='Saving results (1/2)'
            elif fault=='terminal':changed['capture']['events'][0]['status']='COMPLETE'
            elif fault=='untrusted':changed['capture']['events'][0]['trusted']=False
            else:changed['capture']['events'][0]['monotonicMs']=0
            with self.subTest(fault=fault),self.assertRaises(AssertionError):suite.cancellation_click(changed,'processing-cancel')


class BrowserLargeAdmission(unittest.TestCase):
    def test_large_planning_forecast_does_not_renew_absolute_window_or_phase_limits(self):
        import datetime
        iso=lambda tick:datetime.datetime.fromtimestamp(tick,datetime.timezone.utc).isoformat()
        window=dict(schema='chopper-unattended-continuation-v1',non_time_allowances_renewed=False,
            launch_cutoff_utc=iso(9500),deadline_utc=iso(10000))
        for shape,seconds in (('D',600),('G',480)):
            forecast=q.BROWSER_SCALE_FORECAST[shape]
            self.assertEqual(forecast['seconds'],seconds)
            self.assertEqual(forecast['cleanup_margin_seconds'],120)
            total=seconds+120
            self.assertEqual(q._window(window,now=10000-total-1,seconds=total)['deadline'],10000)
            for now in (10000-total,9500):
                with self.subTest(shape=shape,now=now),self.assertRaises(ValueError):
                    q._window(window,now=now,seconds=total)

    def reservation(self):
        slots=[dict(plan_id=channel+'-'+shape,channel=channel,shape=shape,
            directory=q.browser_scale_paths('C:/large-'+channel+'-'+shape,mode='scale')['owned_root'])
            for channel in ('chrome','msedge') for shape in ('D','G')]
        reservation=dict(version=1,parent_scheduled=True,campaign='selected104',slots=slots,
            claims_root='C:/shared104/claims',channels={channel:dict(start_unix=100,deadline_unix=21700)
                for channel in ('chrome','msedge')})
        packet=dict(selection=dict(plan_id='chrome-D',approval_reference='selected104'),shape='D',
            host_receipt=dict(channel='chrome'),paths=q.browser_scale_paths('C:/large-chrome-D',mode='scale'),
            large_reservation=dict(path='C:/shared104/reservation.json'),
            origin=dict(metadata=dict(storage_priming=dict(covered_roots=['C:/shared104'],fresh_roots=[]))))
        return packet,reservation

    def test_one_shared_four_cell_reservation_and_disjoint_outputs(self):
        packet,reservation=self.reservation()
        self.assertEqual(q.browser_scale_reservation(packet,reservation,now=101),21700)
        for fault in ('missing-cell','duplicate-id','duplicate-directory','nested-directory','wrong-current-root','claims-in-cell','unaccounted-owner','wrong-campaign','expired'):
            p,r=copy.deepcopy(packet),copy.deepcopy(reservation)
            now=101
            if fault=='missing-cell':r['slots'].pop()
            elif fault=='duplicate-id':r['slots'][1]['plan_id']=r['slots'][0]['plan_id']
            elif fault=='duplicate-directory':r['slots'][1]['directory']=r['slots'][0]['directory']
            elif fault=='nested-directory':r['slots'][1]['directory']=p['paths']['source']+'/nested-source/harness/scratch/scale'
            elif fault=='wrong-current-root':r['slots'][0]['directory']='C:/other'
            elif fault=='claims-in-cell':r['claims_root']=p['paths']['metadata']+'/claims';p['origin']['metadata']['storage_priming']['covered_roots']=['C:/']
            elif fault=='unaccounted-owner':p['origin']['metadata']['storage_priming']['covered_roots']=[]
            elif fault=='wrong-campaign':r['campaign']='unselected'
            else:now=21700
            with self.subTest(fault=fault),self.assertRaises((ValueError,AssertionError)):
                q.browser_scale_reservation(p,r,now=now)

    def evidence(self,shape='G'):
        from scale_acceptance.browser_scale_identity import scale_fixture
        fixture=scale_fixture(shape)
        candidate=dict(shape=shape,channel='chrome',browser_version='selected-version')
        verified=dict(source_sha256=fixture['sha256'],rows=fixture['rows'],shape=shape,
            limits=dict(bytes=10000000,rows=1000000,compressed_bytes=None))
        facts=[dict(id='spill',kind='spill',status='completed'),dict(id='merge',kind='merge_traversal',status='completed')]
        for row in facts:
            row['outcomes']={name:dict(rows=100 if name=='completed' else 0,
                runs=2 if name=='completed' and row['kind']=='spill' else 0,
                attempts=1 if name=='completed' else 0) for name in ('completed','interrupted','failed','handed_off')}
        state=dict(status='complete',error=None,graph=dict(unavailable=False,eventsOmitted=42,
            steps=[dict(copy.deepcopy(row),source_omitted=True) for row in facts]))
        browser=dict(status='extracted; independent verification still required',failures=[],channel='chrome',
            shape=shape,actual_browser_version='selected-version',spill_coverage=dict(facts=facts))
        return candidate,fixture,verified,browser,state

    def test_failed_large_controller_can_prove_ownership_without_scale_promotion(self):
        import importlib.util
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);metadata=root/'metadata';metadata.mkdir()
            owned=root/'scale';batch=owned/'batch';batch.mkdir(parents=True)
            pref=root/'preflight';pref.mkdir()
            claims=root/'claims';claims.mkdir();(claims/'active.lock').write_text('17')
            (claims/'cell-D.consumed').write_text(str(time.time()))
            reservation=root/'reservation.json';reservation.write_text(json.dumps(dict(claims_root=str(claims))))
            reservation_pin=dict(path=str(reservation),sha256=hashlib.sha256(reservation.read_bytes()).hexdigest())
            data=owned/'D';data.mkdir();(data/'input.csv').write_bytes(b'partial')
            config=root/'config.json';candidate=dict(channel='chrome',shape='D',mode='scale',plan_id='cell-D',
                reservation=reservation_pin);config.write_text(json.dumps(candidate))
            (pref/'result.json').write_text(json.dumps(dict(plan_sha256=hashlib.sha256(config.read_bytes()).hexdigest())))
            release=dict(passed=False,released_after_supervision=True,pid=17,created=170,
                cleanup=dict(original_release_safe=True,processes=[]))
            (batch/'reservation-released.json').write_text(json.dumps(release))
            destination=metadata/'after-exit'
            packet=dict(mode='scale',shape='D',large_reservation=reservation_pin,fixture=dict(bytes=1000000000,sha256='a'*64),host_receipt=dict(channel='chrome'),
                paths=dict(after_exit=str(destination),owned_root=str(owned),metadata=str(metadata),config=str(config),
                    preflight=str(pref),source=str(root/'source')),
                origin=dict(metadata=dict(storage_priming=dict(covered_roots=[]))))
            checker_path=Path(__file__).resolve().parents[2]/'acceptance-preflight.py'
            spec=importlib.util.spec_from_file_location('failed_large_checker',checker_path)
            checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
            storage=SimpleNamespace(roots=[],sample=lambda:123)
            local=SimpleNamespace(host_lock_path=lambda:root/'original')
            small=SimpleNamespace(windows=object(),module=lambda _:local,primed_storage=lambda *_:storage,
                LIMITS=dict(stop_owned_bytes=64*1024**3))
            timer=SimpleNamespace(cancel=lambda:None,join=lambda:None,is_alive=lambda:False)
            def observe(*args,**kwargs):
                result=args[5];result.update(processes=[dict(pid=17,status='absent')],original_byte0_available=True,probe_closed=True)
            with patch.object(q,'packet_declarations'),patch.object(checker.Budget,'install'), \
                 patch.object(checker,'load',return_value=small),patch.object(q,'preflight'), \
                 patch.object(q,'batch_admission',return_value={'matching':'frozen'}), \
                 patch.object(q,'retained_packet_roots',return_value=[]), \
                 patch.object(q,'independent_observation',side_effect=observe), \
                 patch.object(q,'browser_scale_evidence') as acceptance:
                denied=metadata/'failed-retirement';packet['paths']['after_exit']=str(denied)
                with patch.object(q,'retire_browser_scale_active',side_effect=ValueError('uncertain active owner')):
                    with self.assertRaisesRegex(ValueError,'uncertain active owner'):
                        q.browser_scale_after_exit(packet,denied,'b'*64,checker,timer=timer)
                failed=json.loads((denied/'result.json').read_text())
                self.assertEqual(failed['status'],'failed');self.assertFalse(failed['scale_cell_passed'])
                self.assertTrue((claims/'active.lock').exists())
                packet['paths']['after_exit']=str(destination)
                result=q.browser_scale_after_exit(packet,destination,'b'*64,checker,timer=timer)
            self.assertEqual(result['status'],'passed-after-exit');self.assertFalse(result['scale_cell_passed'])
            self.assertFalse(result['qualification']);self.assertEqual(result['generated_input_bytes'],7)
            self.assertFalse(result['retained_incomplete_input']['fixture_verified'])
            self.assertTrue(result['campaign_active_retirement']['active_retired'])
            self.assertFalse((claims/'active.lock').exists());self.assertTrue((claims/'cell-D.consumed').is_file())
            self.assertTrue(result['original_byte0_available']);self.assertTrue(result['probe_closed']);self.assertTrue(result['timer_joined'])
            self.assertNotIn('qualification_receipt',result);acceptance.assert_not_called()
            self.assertTrue((metadata/'storage-ledger.json').is_file())
            self.assertFalse((destination/'tiny-receipt.json').exists())

    def test_campaign_slot_derivation_and_wrong_active_owner_denial(self):
        cells=[dict(namespace='C:/future-'+channel+'-'+shape,plan_id=channel+'-'+shape,channel=channel,shape=shape)
            for channel in ('chrome','msedge') for shape in ('D','G')]
        slots=q.browser_scale_slots(cells)
        self.assertEqual(len(slots),4);self.assertEqual(len({row['directory'] for row in slots}),4)
        bad=copy.deepcopy(cells);bad[1]['namespace']=bad[0]['namespace']
        with self.assertRaises(ValueError):q.browser_scale_slots(bad)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);active=root/'active.lock';active.write_text('999')
            reservation=root/'reservation.json';reservation.write_text(json.dumps(dict(claims_root=str(root))))
            candidate=dict(mode='scale',plan_id='cell',reservation=dict(path=str(reservation),sha256=hashlib.sha256(reservation.read_bytes()).hexdigest()))
            class Budget:
                active=False;read_bytes=0;visits=0
                def check(self):pass
            with self.assertRaisesRegex(ValueError,'active owner'):
                q.retire_browser_scale_active(candidate,dict(pid=17),Budget())
            self.assertTrue(active.exists())

    def test_large_actual_oracle_graph_and_positive_spill_required(self):
        for shape in ('D','G'):q.browser_scale_evidence(*self.evidence(shape))
        for fault in ('wrong-input','wrong-rows','wrong-cap','wrong-browser','failed','missing-graph','negative-omission','incomplete-step','zero-spill','invalid-metric','different-public-facts'):
            c,f,v,b,s=self.evidence()
            if fault=='wrong-input':v['source_sha256']='0'*64
            elif fault=='wrong-rows':v['rows']-=1
            elif fault=='wrong-cap':v['limits']['bytes']+=1
            elif fault=='wrong-browser':b['actual_browser_version']='other'
            elif fault=='failed':b['failures']=['failure']
            elif fault=='missing-graph':s['graph']['unavailable']=True
            elif fault=='negative-omission':s['graph']['eventsOmitted']=-1
            elif fault=='incomplete-step':s['graph']['steps'][0]['status']='running'
            elif fault=='zero-spill':
                b['spill_coverage']['facts'][0]['outcomes']['completed']['runs']=0;s['graph']['steps'][0]['outcomes']['completed']['runs']=0
            elif fault=='invalid-metric':
                b['spill_coverage']['facts'][1]['outcomes']['completed']['runs']=True;s['graph']['steps'][1]['outcomes']['completed']['runs']=True
            else:b['spill_coverage']['facts'][0]['outcomes']['completed']['rows']+=1
            with self.subTest(fault=fault),self.assertRaises((ValueError,AssertionError)):
                q.browser_scale_evidence(c,f,v,b,s)

    def test_actual_node_spill_producer_is_consumed_by_independent_python_check(self):
        node=shutil.which('node')
        if node is None:self.skipTest('Node is required for the composed producer/consumer check')
        root=Path(q.__file__).resolve().parents[2]
        fixture_path=root/'scripts/fixtures/browser-scale-quota-traversal.json'
        state=json.loads(fixture_path.read_text())
        candidate,fixture,verified,browser,_=self.evidence()
        script="import {readFileSync} from 'node:fs'; const {observedSpill}=await import(process.argv[1]); const state=JSON.parse(readFileSync(process.argv[2],'utf8')); process.stdout.write(JSON.stringify(observedSpill(state,Number(process.argv[3]))));"
        browser['spill_coverage']=json.loads(subprocess.check_output([node,'--input-type=module','-e',script,
            (root/'scripts/scale_acceptance/browser-scale-driver.mjs').as_uri(),str(fixture_path),str(fixture['rows'])],text=True))
        q.browser_scale_evidence(candidate,fixture,verified,browser,state)
        recovered=copy.deepcopy(browser);recovered['status']='extracted; independent streaming verification pending'
        q.browser_scale_evidence(candidate,fixture,verified,recovered,state,recovery=True)
        with self.assertRaises(ValueError):q.browser_scale_evidence(candidate,fixture,verified,recovered,state)
        self.assertEqual(browser['spill_coverage']['facts'][1]['status'],'interrupted')
        mixed_browser,mixed_state=copy.deepcopy(browser),copy.deepcopy(state)
        for row in (mixed_state['graph']['steps'][1],mixed_browser['spill_coverage']['facts'][1]):
            row['status']='completed'
            row['outcomes']['completed'].update(rows=1,attempts=1)
            row['outcomes']['interrupted']['rows']-=1
        q.browser_scale_evidence(candidate,fixture,verified,mixed_browser,mixed_state)
        for row in (mixed_state['graph']['steps'][1],mixed_browser['spill_coverage']['facts'][1]):
            row['outcomes']['interrupted']['rows']-=1
        with self.assertRaises(ValueError):q.browser_scale_evidence(candidate,fixture,verified,mixed_browser,mixed_state)
        for fault in ('partial','failed','fact-drift','running','error'):
            b,s=copy.deepcopy(browser),copy.deepcopy(state)
            traversal=s['graph']['steps'][1]
            if fault=='partial':
                traversal['outcomes']['interrupted']['rows']-=1
                b['spill_coverage']['facts'][1]['outcomes']['interrupted']['rows']-=1
            elif fault=='failed':
                traversal['outcomes']['failed']['attempts']=1
                b['spill_coverage']['facts'][1]['outcomes']['failed']['attempts']=1
            elif fault=='fact-drift':b['spill_coverage']['facts'][1]['outcomes']['interrupted']['rows']-=1
            elif fault=='running':s['status']='running'
            else:s['error']='engine failure'
            with self.subTest(fault=fault),self.assertRaises(ValueError):
                q.browser_scale_evidence(candidate,fixture,verified,b,s)
