"""Tiny fixtures/subprocesses only; these tests are never benchmark evidence."""
import copy
import csv
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('workers', Path(__file__).with_name('benchmark-e5-workers.py'))
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class Controls(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def invoke(self, script, **kwargs):
        return w.attempt([sys.executable, '-c', script], self.root / 'attempt',
                         dict(os.environ), time.monotonic() + 5, **kwargs)

    def test_success_full_logs_and_exclusive_retention(self):
        result = self.invoke("import sys; print('full stdout'); print('full stderr', file=sys.stderr)")
        self.assertEqual(result['status'], 'completed')
        self.assertIn('full stdout', (self.root / 'attempt/stdout.log').read_text())
        self.assertIn('full stderr', (self.root / 'attempt/stderr.log').read_text())
        with self.assertRaises(FileExistsError):
            self.invoke('raise Exception()')

    def test_nonzero_no_retry_retains_partial_and_logs(self):
        script = "import sys; print('failure details',file=sys.stderr); sys.exit(7)"
        with self.assertRaisesRegex(ValueError, 'nonzero'):
            self.invoke(script)
        result = json.loads((self.root / 'attempt/outcome.json').read_text())
        self.assertEqual(result['exit_code'], 7)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('failure details', (self.root / 'attempt/stderr.log').read_text())

    def test_preflight_is_outside_spawn_through_exit_clock(self):
        clock = [10]
        def guard():
            clock[0] = 20
        with patch.object(w.time, 'perf_counter', side_effect=lambda: clock[0]):
            result = self.invoke('print(1)', guard=guard)
        self.assertEqual(result['seconds'], 0)

    def test_timeout_kills_reaps_retains_logs(self):
        with self.assertRaisesRegex(ValueError, 'timeout'):
            self.invoke("import time; print('started',flush=True); time.sleep(20)", timeout=.2)
        result = json.loads((self.root / 'attempt/outcome.json').read_text())
        self.assertIsNotNone(result['exit_code'])
        self.assertIn('started', (self.root / 'attempt/stdout.log').read_text())

    def test_launch_failure_retained(self):
        with self.assertRaises(OSError):
            w.attempt([str(self.root / 'missing')], self.root / 'attempt', dict(os.environ), time.monotonic() + 1)
        self.assertEqual(json.loads((self.root / 'attempt/outcome.json').read_text())['status'], 'failed')

    def test_running_guard_failure_retains_partial(self):
        partial = self.root / 'partial'
        def guard():
            if partial.exists():
                raise ValueError('disk ceiling')
        script = 'from pathlib import Path; import time; Path(' + repr(str(partial)) + ").write_text('partial'); time.sleep(20)"
        with self.assertRaisesRegex(ValueError, 'disk ceiling'):
            self.invoke(script, guard=guard)
        self.assertEqual(partial.read_text(), 'partial')
        self.assertIsNotNone(json.loads((self.root / 'attempt/outcome.json').read_text())['exit_code'])

    def test_identity_drift(self):
        with patch.object(w, 'identities', return_value={'a': 'changed'}):
            with self.assertRaisesRegex(ValueError, 'drift'):
                w.assert_identity({'a': 'frozen'})

    def test_deadline_disk_and_plan_blockers(self):
        with self.assertRaisesRegex(ValueError, 'deadline'):
            w.budget(self.root, time.monotonic() - 1)
        (self.root / 'data').write_bytes(b'123')
        with self.assertRaisesRegex(ValueError, 'disk ceiling'):
            w.budget(self.root, time.monotonic() + 5, limit=3)
        with self.assertRaisesRegex(ValueError, 'denial controls'):
            w.run({'status': 'blocked', 'blockers': w.BLOCKERS}, self.root / 'never-created')
        self.assertFalse((self.root / 'never-created').exists())

    def test_build_proof_rejects_source_and_feature_mismatch(self):
        proof = self.root / 'proof.json'
        identity = {'binary_sha256': 'exe', 'source_sha256': {'source': 'a'}}
        data = {'features': [], 'binary_sha256': 'exe', 'source_sha256': {'source': 'a'},
                'toolchains': ['pinned'], 'commands': [['cargo', 'build', '--release', '--locked', '-p', 'chopper']],
                'outcomes': [0], 'profile': 'release', 'build_logs': [{'path':str(proof), 'path_sha256':'unused'}]}
        with patch.object(w, 'identities', return_value=identity), patch.object(w, 'checked_file'):
            proof.write_text(json.dumps(data))
            frozen = w.freeze(self.root / 'exe', proof)
            self.assertIn(w.BLOCKERS[0], frozen['blockers'])
            data['source_sha256']['source'] = 'drift'
            proof.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'source inventory'):
                w.freeze(self.root / 'exe', proof)
            data['features'] = ['experimental']
            proof.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, 'features'):
                w.freeze(self.root / 'exe', proof)

    def test_frozen_panel_and_coverage(self):
        panel = w.schedule()
        self.assertEqual(len(panel), 24)
        self.assertEqual([v[3] for v in panel[:6]], [1, 0, 0, 1, 1, 0])
        for case, rows in w.CASES:
            self.assertEqual(sum(c == case for c, _, _, _ in panel), 6)
        a = {'diagnostics': {'sort_calls': 2, 'sort_rows': 8191, 'sort_runs': 2, 'merge_operations': 1}}
        w.coverage(a, 'external')
        a['diagnostics']['sort_rows'] = 8190
        with self.assertRaisesRegex(ValueError, '4096'):
            w.coverage(a, 'external')
        a['diagnostics'].update(sort_rows=9000, merge_operations=0)
        with self.assertRaisesRegex(ValueError, 'coverage'):
            w.coverage(a, 'external')


class Gate(unittest.TestCase):
    setUp = Controls.setUp
    tearDown = Controls.tearDown
    invoke = Controls.invoke
    def ready(self):
        binary, test = self.root / 'production.exe', self.root / 'test.exe'
        binary.write_bytes(b'fake production; never engine evidence')
        test.write_bytes(b'fake test; separate artifact')
        identity = {'source_sha256': {'source': 'fixed'}, 'harness_sha256': {}, 'binary_sha256': w.sha(binary)}
        records = [dict(id=i, kind=k, requested_workers=q, resolved_workers=r, memory_mb=256, passed=True)
                   for i,k,q,r in [('D1','local',1,1),('D2','local',0,4),('D3','shared',1,1),('D4','shared',0,4)]]
        for record in records:
            record['scenarios'] = [dict(phase=phase,cancelled=cancelled,local_limit_bytes=128*1024**2,
                pool_limit_bytes=(64 if record['kind']=='shared' else 256)*1024**2,
                remaining_bytes=0,cleanup_verified=True,error='cancelled' if cancelled else record['kind'],
                grant_bytes=1024, rows=65536 if phase=='Serializing output' else 5000 if phase=='Finalizing output snapshot' else 0)
                for phase,cancelled in [('Reading and validating CSV',False),('Finalizing output snapshot',False),
                                       ('Serializing output',False),('Finalizing output snapshot',True)]]
        stdout, stderr = self.root / 'controls.log', self.root / 'controls.err'
        stdout.write_text(''.join(w.CONTROL_PREFIX + json.dumps(r) + '\n' for r in records)
                          + 'test result: ok. 1 passed; 0 failed; 0 ignored;\n')
        stderr.write_text('')
        control = dict(schema=1, source_sha256=identity['source_sha256'], test_binary=str(test),
            test_binary_sha256=w.sha(test), command=[str(test),w.CONTROL_FILTER+'complete_run_worker_denials','--exact','--nocapture'],
            stdout=str(stdout), stdout_sha256=w.sha(stdout), stderr=str(stderr), stderr_sha256=w.sha(stderr),
            exit_code=0, records=records)
        log = self.root / 'build.log'
        log.write_text('fake release build log, only test gate logic')
        control['test_build'] = dict(source_sha256=identity['source_sha256'],features=[],binary_sha256=w.sha(test),
            exit_code=0,toolchains=['synthetic'],command=['cargo','test','--locked','--lib','--no-run','-p','chopper'],
            logs=[dict(path=str(log),path_sha256=w.sha(log))])
        proof = dict(features=[], profile='release', binary_sha256=w.sha(binary),
            source_sha256=identity['source_sha256'],toolchains=['synthetic'],
            commands=[['cargo','build','--release','--locked','-p','chopper']],outcomes=[0],
            build_logs=[dict(path=str(log),path_sha256=w.sha(log))])
        attested = dict(os_build='fake Windows',cpu_available=4,volume_device='fake device',filesystem='NTFS',
                        storage='NVMe',free_space_bytes=w.DISK_BYTES,background_cache='synthetic',no_concurrent_work=True)
        paths = [self.root / name for name in ('build.json','controls.json','attestations.json')]
        for path,value in zip(paths,(proof,control,attested)):
            w.write_json(path,value)
        with patch.object(w,'identities',return_value=identity):
            plan = w.freeze(binary,*paths)
        return plan,identity

    def test_missing_failed_stale_and_forged_ready_controls_rejected(self):
        plan, identity = self.ready()
        self.assertEqual(plan['status'],'ready')
        report = plan['controls']
        with patch.object(w,'identities',return_value=identity):
            for mutation in ('missing','failed','stale','forged'):
                changed = copy.deepcopy(plan)
                if mutation == 'missing':
                    changed['controls'] = None
                elif mutation == 'failed':
                    changed['controls']['exit_code'] = 9
                elif mutation == 'stale':
                    changed['identity']['source_sha256'] = {'source':'new'}
                else:
                    changed['controls']['records'][0]['passed'] = False
                with self.assertRaises((ValueError,KeyError)):
                    w.run(changed,self.root / ('never-'+mutation))
                self.assertFalse((self.root / ('never-'+mutation)).exists())
        for key,value in [('exit_code',1),('source_sha256',{}),('records',[])]:
            changed = copy.deepcopy(report)
            changed[key]=value
            with self.assertRaises(ValueError):
                w.validate_controls(changed,identity,Path(plan['binary']))
        Path(report['stdout']).write_text('forged ready')
        with self.assertRaisesRegex(ValueError,'stale retained'):
            w.validate_controls(report,identity,Path(plan['binary']))

    def test_timeout_and_counter_failure_preserve_original_error(self):
        def broken(_):
            raise OSError('counter unavailable')
        with self.assertRaisesRegex(ValueError,'timeout'):
            self.invoke('import time;time.sleep(20)',timeout=.1,counter=broken)
        outcome=json.loads((self.root/'attempt/outcome.json').read_text())
        self.assertIn('timeout',outcome['error'])
        self.assertIn('counter unavailable',outcome['counter_error'])

    def test_counter_failure_invalidates_success(self):
        def broken(_):
            raise OSError('counter unavailable')
        with self.assertRaisesRegex(ValueError,'counter unavailable'):
            self.invoke('print(1)',counter=broken)
        self.assertEqual(json.loads((self.root/'attempt/outcome.json').read_text())['status'],'failed')

    def test_tiny_fake_end_to_end_loop_and_verification_stop_retention(self):
        # Use the real loop, subprocess attempt, CSV generator, verifier and
        # evidence gate. Only OS identities/command executable are synthetic.
        plan,identity=self.ready()
        fake=self.root/'fake.py'
        fake.write_text('''import csv,json,sys
from pathlib import Path
if sys.argv[1]=='controls':
 print(Path(sys.argv[2]).read_text());sys.exit(0)
j=json.loads(Path(sys.argv[1]).read_text());o=Path(j['output']);o.mkdir()
p=o/'part.csv';p.write_bytes(Path(j['input']).read_bytes());n=3
d={k:0 for k in ['temporary_path_reserved_bytes','directory_path_reserved_bytes','prepared_job_reserved_bytes','analysis_preview_reserved_bytes','analysis_warnings_reserved_bytes','analysis_timings_reserved_bytes','analysis_text_reserved_bytes','stage_stats_reserved_bytes','column_values_reserved_bytes','input_header_reserved_bytes','analysis_diagnostics_reserved_bytes','temporary_cleanup_failures','workspace_reserved_bytes','peak_workspace_reserved_bytes']}
d['process_memory']={'limit_bytes':64*1024**2,'peak_reserved_bytes':0}
a={'rows':n,'seed':j['seed'],'algorithm_version':'chopper-v1-blake3-1','workers':4 if j['resources']['workers']==0 else 1,'memory_budget_bytes':256*1024**2,'diagnostics':d,'logical_digest':'fake-not-engine-evidence','stages':[],'output_files':1,'output_csv_bytes':p.stat().st_size}
e=[{'type':'job','algorithm_version':a['algorithm_version'],'config':j,'analysis':a},{'type':'output','path':'part.csv','rows':n,'csv_bytes':p.stat().st_size,'stored_bytes':p.stat().st_size,'compressed_target_exceeded':False,'lineage':[]}]
(o/'manifest.jsonl').write_text(''.join(json.dumps(x)+'\\n' for x in e));print(json.dumps(a))
''')
        original=w.attempt
        def real_fake_attempt(command,*args,**kwargs):
            if command[0]==plan['controls']['test_binary']:
                command=[sys.executable,str(fake),'controls',plan['controls']['stdout']]
            else:
                command=[sys.executable,str(fake),command[command.index('--config')+1]]
            kwargs['counter']=lambda _: {'cpu_seconds':.001}
            return original(command,*args,**kwargs)
        with patch.object(w,'CASES',[('small',3)]),patch.object(w,'identities',return_value=identity),\
             patch.object(w.platform,'system',return_value='Windows'),patch.object(w,'attempt',side_effect=real_fake_attempt):
            # Re-freeze with the test-sized schedule. Production CLI exposes no
            # recipe override; the unchanged 24-attempt maximum still applies.
            plan['cases']=w.CASES;plan['schedule']=w.schedule()
            work=self.root/'tiny-success'
            w.run(plan,work)
            self.assertEqual(len(list(work.glob('*/verification.json'))),6)
            self.assertTrue((work/'summary.json').is_file())
            self.assertFalse((work/'STOP.json').exists())
            with patch.object(w,'verify',side_effect=ValueError('synthetic verification failure')):
                failed=self.root/'tiny-failure'
                with self.assertRaisesRegex(ValueError,'verification failure'):
                    w.run(plan,failed)
                self.assertTrue((failed/'STOP.json').is_file())
                self.assertTrue((failed/'01-small-1-W1-output/part.csv').is_file())
                self.assertTrue((failed/'01-small-1-W1/outcome.json').is_file())
                self.assertFalse((failed/'02-small-1-W0').exists())


class NativeCounters(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Win32 counters')
    def test_real_tiny_subprocess_counters(self):
        with tempfile.TemporaryDirectory() as directory:
            result = w.attempt([sys.executable, '-c', 'print(1)'], Path(directory)/'counter',
                dict(os.environ),time.monotonic()+5,counter=w.load('benchmark-windows').counters)
            self.assertGreater(result['peak_working_set_bytes'], 0)
            self.assertGreaterEqual(result['cpu_seconds'], 0)
            self.assertIn('read_transfer_bytes',result['process_io'])


class Verification(unittest.TestCase):
    setUp = Controls.setUp
    tearDown = Controls.tearDown
    def fixture(self, case='small', workers=1, reverse=False):
        output, temp = self.root / 'output', self.root / 'temp'
        output.mkdir()
        temp.mkdir()
        rows = 3
        path = output / 'part.csv'
        with path.open('w', newline='', encoding='utf-8') as stream:
            writer = csv.writer(stream)
            writer.writerow(['id', 'key', 'payload'])
            writer.writerows(w.fields(case, i, rows) for i in (reversed(range(rows)) if reverse else range(rows)))
        size = path.stat().st_size
        d = {k: 0 for k in ('temporary_path_reserved_bytes', 'directory_path_reserved_bytes',
            'prepared_job_reserved_bytes', 'analysis_preview_reserved_bytes', 'analysis_warnings_reserved_bytes',
            'analysis_timings_reserved_bytes', 'analysis_text_reserved_bytes', 'stage_stats_reserved_bytes',
            'column_values_reserved_bytes', 'input_header_reserved_bytes', 'analysis_diagnostics_reserved_bytes',
            'temporary_cleanup_failures', 'workspace_reserved_bytes', 'peak_workspace_reserved_bytes')}
        d['process_memory'] = {'limit_bytes': 64 * 1024**2, 'peak_reserved_bytes': 0}
        analysis = {'rows': rows, 'seed': w.SEED, 'algorithm_version': w.ALGORITHM,
                    'workers': 4 if workers == 0 else 1, 'memory_budget_bytes': 256 * 1024**2,
                    'diagnostics': d, 'logical_digest': 'synthetic-not-engine-evidence', 'stages': [],
                    'output_files': 1, 'output_csv_bytes': size}
        job = w.job_for(case, self.root / 'input.csv', output, temp, workers)
        entries = [{'type': 'job', 'algorithm_version': w.ALGORITHM, 'config': job, 'analysis': analysis},
                   {'type': 'output', 'path': 'part.csv', 'rows': rows, 'csv_bytes': size,
                    'stored_bytes': size, 'compressed_target_exceeded': False, 'lineage': []}]
        self.save(output, entries)
        return output, temp, analysis, entries

    def save(self, output, entries):
        (output / 'manifest.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in entries), encoding='utf-8')

    def test_real_verification_logic_success_and_exact_order_fingerprint(self):
        output, temp, a, entries = self.fixture('external', 0)
        first = w.verify(output, temp, a, 'external', 3, 0)
        text = (output / 'part.csv').read_text().splitlines()
        (output / 'part.csv').write_text('\n'.join([text[0]] + text[:0:-1]) + '\n')
        # newline byte metadata must be updated; altered ordering changes fingerprint.
        size = (output / 'part.csv').stat().st_size
        entries[1].update(csv_bytes=size, stored_bytes=size)
        a['output_csv_bytes'] = size
        self.save(output, entries)
        self.assertNotEqual(first, w.verify(output, temp, a, 'external', 3, 0))

    def test_wrong_manifest_analysis_and_input_rejected(self):
        output,temp,a,entries=self.fixture()
        entries[0]['analysis']=copy.deepcopy(a)
        entries[0]['analysis']['stages']=[{'forged':True}]
        self.save(output,entries)
        with self.assertRaisesRegex(ValueError,'manifest analysis'):
            w.verify(output,temp,a,'small',3,1)
        entries[0]['analysis']=a
        self.save(output,entries)
        with self.assertRaisesRegex(ValueError,'manifest config input'):
            w.verify(output,temp,a,'small',3,1,self.root/'different.csv')

    def test_direct_order_rejected(self):
        output, temp, a, _ = self.fixture(reverse=True)
        with self.assertRaisesRegex(ValueError, 'direct order'):
            w.verify(output, temp, a, 'small', 3, 1)

    def test_duplicate_missing_or_modified_fields_rejected(self):
        output, temp, a, entries = self.fixture()
        path = output / 'part.csv'
        data = path.read_bytes()
        path.write_bytes(data.replace(b'1,', b'0,'))
        with self.assertRaisesRegex(ValueError, 'conservation'):
            w.verify(output, temp, a, 'small', 3, 1)

    def test_manifest_caps_cleanup_workers_seed_and_membership(self):
        output, temp, a, entries = self.fixture('skew')
        with self.assertRaisesRegex(ValueError, 'partition lineage'):
            w.verify(output, temp, a, 'skew', 3, 1)
        entries[1]['lineage'] = [{'operation': 1, 'values': ['heavy']}]
        self.save(output, entries)
        # Last row belongs to key 2, so this is wrong group membership.
        with self.assertRaisesRegex(ValueError, 'membership'):
            w.verify(output, temp, a, 'skew', 3, 1)
        for key, value, error in [('workers', 2, 'worker'), ('seed', 'wrong', 'seed')]:
            changed = copy.deepcopy(a)
            changed[key] = value
            with self.assertRaisesRegex(ValueError, error):
                w.verify(output, temp, changed, 'skew', 3, 1)
        (temp / 'leaked').write_text('x')
        with self.assertRaisesRegex(ValueError, 'not empty'):
            w.verify(output, temp, a, 'skew', 3, 1)

    def test_encoded_cap_and_unlisted_file(self):
        output, temp, a, entries = self.fixture()
        (output / 'extra').write_text('x')
        with self.assertRaisesRegex(ValueError, 'unlisted'):
            w.verify(output, temp, a, 'small', 3, 1)
        entries[1]['csv_bytes'] = 262145
        self.save(output, entries)
        with self.assertRaisesRegex(ValueError, 'cap'):
            w.verify(output, temp, a, 'small', 3, 1)


if __name__ == '__main__':
    unittest.main()
