"""Portable source/lifecycle controls for the retained Native UI smoke adapter."""
import ast,contextlib,errno,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_smoke import control,suite,config

class NativeSmoke(unittest.TestCase):
    def test_actual_processing_cancel_terminal_stage_reset_is_not_a_global_row_regression(self):
        import copy
        case=dict(name='processing-cancel',job=dict(output='retained-native-output'))
        # R5 actual observation: reading rows65536 -> preparing operation2 rows0.
        value=dict(submitted=case['job'],runs=1,cancels=1,picks=0,headerReads=1,
            activeBeforeCancel=dict(status='running',output=case['job']['output'],progress=dict(rows=65536,phase='Reading and validating CSV')),
            activeOrder=1,cancelOrder=2,terminalOrder=3,cancelRequested=True,cancelHTTP=200,
            cancelClick=dict(trusted=True,unixMs=1794707257647,monotonicMs=2201.7,eventTimestamp=2201.3,status='RUNNING',phase='Reading and validating CSV'),
            captureInstalledUnixMs=1794707257613,preClickUnixMs=1794707257613,terminalUnixMs=1794707258590,
            state=dict(status='cancelled',error='job cancelled',progress=dict(rows=0,phase='Preparing operation 2 of 17',temp_bytes=4510054)))
        with patch.object(suite,'clean') as clean:
            suite.verify_case(case,value,Path('unused'),{});clean.assert_called_once()
            for rows in (None,-1,False,1.5):
                changed=copy.deepcopy(value);changed['state']['progress']['rows']=rows
                with self.subTest(rows=rows),self.assertRaises(AssertionError):suite.verify_case(case,changed,Path('unused'),{})
            changed=copy.deepcopy(value);changed['activeBeforeCancel']['progress']['rows']=0
            with self.assertRaises(AssertionError):suite.verify_case(case,changed,Path('unused'),{})
            changed=copy.deepcopy(value);changed['state']['progress']['phase']='Writing output'
            with self.assertRaises(AssertionError):suite.verify_case(case,changed,Path('unused'),{})
            changed=copy.deepcopy(value);changed['activeBeforeCancel']['progress']['phase']='Writing output';changed['state']['progress']['phase']='Writing output'
            with self.assertRaisesRegex(AssertionError,'completed-file'):suite.verify_case(dict(case,name='export-cancel'),changed,Path('unused'),{})
        script=r"""
const assert=require('node:assert/strict');const {qualifies}=require(process.argv[1]);
const value={status:'cancelled',error:'job cancelled',progress:{phase:'Preparing operation 2 of 17',rows:0}};
assert.equal(qualifies(value,true,200,'processing-cancel'),true);
assert.equal(qualifies(value,false,200,'processing-cancel'),false);
assert.equal(qualifies(value,true,500,'processing-cancel'),false);
for(const rows of [null,-1,false,1.5])assert.equal(qualifies({...value,progress:{...value.progress,rows}},true,200,'processing-cancel'),false);
assert.equal(qualifies({...value,progress:{phase:'Writing output',rows:0}},true,200,'export-cancel'),false);
assert.equal(qualifies({...value,progress:{phase:'Writing output',rows:100}},true,200,'export-cancel'),true);
assert.equal(qualifies({...value,status:'complete'},true,200,'processing-cancel'),false);
"""
        result=subprocess.run(['node','-e',script,str(Path(control.__file__).with_name('browser.cjs'))],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_bounded_failure_details_keep_empty_assertion_location_notes_and_api(self):
        try:raise AssertionError()
        except AssertionError as error:
            error.api='GetProcessTimes';error.pid=17;error.winerror=5
            error.add_note('observed case field')
            value=control.failure_details(error)
        self.assertEqual(value['type'],'AssertionError');self.assertEqual(value['message'],'')
        self.assertIn('test_bounded_failure_details',value['traceback'])
        self.assertEqual(value['notes'],['observed case field'])
        self.assertEqual((value['api'],value['pid'],value['winerror']),('GetProcessTimes',17,5))
        self.assertLessEqual(len(value['traceback']),16384)

    def test_picker_cold_inspector_uses_same_baseline_oracle_with_explicit_manifest_pin(self):
        from hosted_picker import config as picker,suite as helpers,control as picker_control
        plan=dict(python=dict(path=sys.executable),controller_root=str(Path(config.__file__).resolve().parents[2]),root='selected-root',documents={'package-binding.json':'package','custody.json':'custody'})
        with patch.object(picker,'os',SimpleNamespace(name='nt')),patch.object(picker,'validate',return_value={}),patch.object(picker,'read',side_effect=lambda name:{} if name=='package' else {'baselineCompletedManifestSha256':'accepted-manifest'}),patch.object(picker_control,'native_volume',return_value={}),patch.object(helpers,'baseline_completed',side_effect=AssertionError('cold picker baseline mismatch')) as baseline:
            probe=Mock()
            with self.assertRaisesRegex(AssertionError,'cold picker baseline mismatch'):picker.inspect(plan,None,probe=probe)
            baseline.assert_called_once_with(Path('selected-root'),expected_manifest='accepted-manifest');probe.assert_not_called()

    def test_actual_pre_original_baseline_failure_records_joined_no_start_and_audits_only_ownership(self):
        import copy
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'attempt1';identity=dict(pid=os.getpid(),created=123)
            windows=SimpleNamespace(query_job=Mock(return_value=dict(pids=[os.getpid()],kill_on_close=True)),process_identity=Mock(return_value=identity))
            reservation=SimpleNamespace(Reservation=Mock())
            runner=SimpleNamespace(contain_session=Mock(),_SESSION_JOB=1)
            helpers=SimpleNamespace(authorize_history=Mock(),baseline_completed=Mock(side_effect=AssertionError('baseline named/held mismatch')))
            modules={'suite':helpers,'browser-small-windows':windows,'validation-runner':runner,'reservation':reservation}
            accounting=dict(absolute_stop_utc='2100-01-01T00:00:00+00:00',expired_window_seconds_charged=17100,window_start_utc='2099-12-31T22:30:00Z',historical_absolute_stop_utc='2026-11-07T11:20:53Z',historical_window_seconds_charged=5400)
            plan=dict(case='processing-cancel',browser_version='selected',original_lock=dict(identity=[1,2]))
            with patch.multiple(control,ROOT=root,OUT=out,PLAN=plan,CONFIG_SHA='config',PREPARATION={'sha256':'pref'},os=SimpleNamespace(name='nt',getpid=os.getpid),sys=SimpleNamespace(flags=SimpleNamespace(isolated=True,dont_write_bytecode=True,optimize=0))),patch.object(control,'verify_sources'),patch.object(control,'document',side_effect=lambda name:accounting if name=='accounting.json' else {}),patch.object(control,'load',side_effect=modules.__getitem__),patch.object(config,'check'),patch.object(control.subprocess,'Popen') as launch:
                owner=[None]
                with self.assertRaisesRegex(AssertionError,'baseline named/held mismatch'):control.parent(owner)
                self.assertEqual(owner,[None]);reservation.Reservation.assert_not_called();launch.assert_not_called()
                value=json.loads((out/'receipt.json').read_text())
                self.assertFalse(value['originalAcquired']);self.assertFalse(value['originalReservationClosedAfterQuiescence'])
                self.assertTrue(value['setupCleanup']['preflight_timer_joined']);self.assertFalse(value['acceptance'])
                self.assertEqual(control.after_exit_release(value),[dict(pid=os.getpid(),created=[123])])
                for key in ('preflight_timer_joined','worker_launch_attempted','disk_started'):
                    changed=copy.deepcopy(value);changed['setupCleanup'][key]=not changed['setupCleanup'][key]
                    with self.subTest(key=key),self.assertRaises(AssertionError):control.after_exit_release(changed)

    def test_native_cold_inspector_runs_existing_baseline_oracle_before_runtime_probe(self):
        helpers=SimpleNamespace(baseline_completed=Mock(side_effect=AssertionError('cold baseline mismatch')))
        with patch.object(config.os,'name','nt'),patch.object(config,'validate',return_value={}),patch.object(control,'bindings_for_inspection'),patch.object(control,'load',return_value=helpers),patch.object(control,'native_volume') as volume:
            probe=Mock()
            with self.assertRaisesRegex(AssertionError,'cold baseline mismatch'):config.inspect({},None,probe=probe)
            helpers.baseline_completed.assert_called_once_with(control.ROOT);volume.assert_not_called();probe.assert_not_called()

    def test_retained_inventory_uses_windows_birthtime_and_keeps_change_time_stability(self):
        from hosted_picker import suite as helpers
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);file=root/'manifest.jsonl';file.write_bytes(b'committed')
            real_fstat=os.fstat
            fields=('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns','st_nlink','st_mode')
            def held(fd):
                value=real_fstat(fd);row={name:getattr(value,name) for name in fields}
                birth=getattr(value,'st_birthtime_ns',value.st_ctime_ns)
                row.update(st_birthtime_ns=birth,st_ctime_ns=birth+1000,st_file_attributes=getattr(value,'st_file_attributes',0))
                return SimpleNamespace(**row)
            with patch.object(helpers,'os',SimpleNamespace(name='nt',fstat=held)):
                result=helpers.inventory(root)
            self.assertEqual(result[file.name]['sha256'],hashlib.sha256(b'committed').hexdigest())
            calls=[]
            def changed(fd):
                value=held(fd);calls.append(fd)
                if len(calls)==2:value.st_ctime_ns+=1
                return value
            with patch.object(helpers,'os',SimpleNamespace(name='nt',fstat=changed)):
                with self.assertRaisesRegex(AssertionError,'held-before-to-after.*manifest|manifest.*held-before-to-after'):
                    helpers.inventory(root)
            def no_birth(fd):
                value=held(fd);del value.st_birthtime_ns;return value
            with patch.object(helpers,'os',SimpleNamespace(name='nt',fstat=no_birth)):
                with self.assertRaisesRegex(AssertionError,'named-to-held-open'):
                    helpers.inventory(root)

    def test_retained_inventory_denial_keeps_exact_path_boundary_and_raw_fields(self):
        from hosted_picker import suite as helpers
        before=SimpleNamespace(st_dev=1,st_ino=2,st_size=3,st_mtime_ns=4,st_ctime_ns=5,st_nlink=1,st_file_attributes=128)
        with patch.object(helpers,'os',SimpleNamespace(name='nt')):
            # Keep same-surface timestamp agreement valid; some Windows path
            # APIs already expose change-time, as the retained UNC probe does.
            helpers._inventory_match('exact/manifest.jsonl','named-to-held-open',before,before,held=True)
        after=SimpleNamespace(**vars(before));after.st_ctime_ns=6
        with self.assertRaises(AssertionError) as caught:
            helpers._inventory_match('exact/manifest.jsonl','named-before-to-after-close',before,after)
        text=str(caught.exception)
        self.assertIn('exact/manifest.jsonl',text);self.assertIn('named-before-to-after-close',text)
        self.assertIn('st_ctime_ns',text);self.assertIn('present',text)

    def test_unbound_windows_entry_denies_before_original_or_launch(self):
        with patch.object(control.os,'name','posix'),patch.object(control.subprocess,'Popen') as launch,patch.object(control,'load') as load:
            with self.assertRaises(AssertionError):control.parent([None])
            launch.assert_not_called();load.assert_not_called()

    def test_new_namespace_collision_denies_both_preparers_before_candidate_or_runtime_work(self):
        from hosted_picker import config as picker
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);definition=root/'definition.json';output=root/'candidate.json'
            definition.write_text(json.dumps(dict(new_namespace=True,root=str(root))))
            for owning in (config,picker):
                with self.subTest(preparer=owning.__name__),patch.object(owning,'validate') as validate:
                    with self.assertRaisesRegex(AssertionError,'fresh namespace required'):owning.prepare(definition,output)
                    validate.assert_not_called();self.assertFalse(output.exists())

    def test_actual_native_prepare_merges_real_selected_runtime_and_history_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);selected_root=root/'source';selected_root.mkdir();source=selected_root/'source.py';source.write_bytes(b'# frozen source\n')
            older=root/'old-receipt.json';older.write_bytes(b'{"failed":true}')
            accounting=root/'accounting.json';accounting.write_text(json.dumps(dict(prior_attempts=[dict(native_path=str(older),sha256=config.digest(older))])))
            selection=root/'selection.json';selection.write_text(json.dumps(dict(inputs=[dict(path=str(source),sha256=config.digest(source))],input_directories=[str(selected_root)])))
            tool=root/'tool';tool.write_bytes(b'fixed tool');binding=dict(path=str(tool),sha256=config.digest(tool))
            observed=root/'host.json';observed.write_text(json.dumps(dict(schema='chopper-hosted-host-v1',status='passed',host={'os':'Windows'},channel='chrome',workload_started=False,original_acquired=False,controller_started=False,tools={role:binding for role in ('python','node','browser')},inputs=[binding],preparation_code=[],input_directories={})))
            value=dict(root=str(root),channel='chrome',source_selection=dict(path=str(selection),sha256=config.digest(selection)),documents={'accounting.json':str(accounting)},inputs=[dict(path=str(accounting),sha256=config.digest(accounting))],input_directories=[],runtime_observation=dict(path=str(observed),sha256=None),**{role:binding for role in ('python','node','browser')})
            definition=root/'definition.json';definition.write_text(json.dumps(value));output=root/'candidate.json'
            # Only the platform/package validator is replaced; the real constructor reads,
            # conflict-checks, inventories, stamps and writes all of these actual files.
            with patch.object(config,'validate') as native_validation:
                result=config.prepare(definition,output,runtime_sha256=config.digest(observed))
                native_validation.assert_called_once()
            actual=json.loads(output.read_bytes());pins={row['path']:row for row in actual['inputs']}
            self.assertEqual(pins[str(source)]['sha256'],config.digest(source));self.assertEqual(pins[str(older)]['sha256'],config.digest(older))
            self.assertEqual(actual['input_directories'][str(selected_root)],[str(source)]);self.assertEqual(actual['channel'],'chrome')
            self.assertFalse(result['workload_started']);self.assertEqual(result['sha256'],config.digest(output))
            for row in actual['inputs']:self.assertEqual(row['stat'],config.stamp(row['path']))
            with patch.object(config,'read',side_effect=AssertionError('metadata check must not reread cold selection')):
                config.check(actual)
            value['inputs'].append(dict(path=str(source),sha256='0'*64));definition.write_text(json.dumps(value))
            with self.assertRaises(AssertionError):config.prepare(definition,root/'conflict.json',runtime_sha256=config.digest(observed))
            self.assertFalse((root/'conflict.json').exists())
            with self.assertRaisesRegex(AssertionError,'metadata changed'):config.check(actual)

    def test_explicit_source_config_digest_does_not_learn_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            selected=Path(directory)/'selection.json';selected.write_bytes(b'{}')
            before=config.digest(selected);selected.write_bytes(b'{"changed":true}')
            self.assertNotEqual(config.digest(selected),before)
            with self.assertRaisesRegex(AssertionError,'definition changed'):
                control.bind(selected,before,dict(path='unrun',sha256='a'*64))

    def test_native_atomic_output_oracle_never_accepts_a_committed_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'temp').mkdir();dest=root/'cancel-output'
            suite.clean(root,[dest]);dest.mkdir()
            with self.assertRaisesRegex(AssertionError,'output must remain absent'):suite.clean(root,[dest])
            self.assertTrue(dest.is_dir(),'failed oracle never removes committed/partial data')

    def test_native_jobs_select_actual_processing_or_export_without_fixture_creation(self):
        job=dict(input='',output='',operations=[],limits={},resources=dict(temp_dir='unrun',temp_bytes=2*1024**2,memory_mb=64,workers=1))
        for case in ('processing-cancel','export-cancel'):
            documents={'job.json':job,'decision.json':dict(case=case)}
            with patch.multiple(suite,document=lambda name:json.loads(json.dumps(documents[name])),PLAN=dict(case=case),create=True),patch.object(suite,'validate_job_namespace'):
                rows=suite.cases(Path('/unused'));value=rows[0]['job']
                self.assertEqual(rows[0]['name'],case);self.assertEqual(value['input'],suite.REUSED_INPUT)
                self.assertEqual(value['limits']['rows'],100 if case=='export-cancel' else None)
                self.assertEqual(value['resources']['max_files'],1200 if case=='export-cancel' else 4)
                self.assertEqual(value['resources']['memory_mb'],64);self.assertEqual(value['resources']['workers'],1)
                self.assertEqual(value['resources']['temp_bytes'],64*1024**2)
                if case=='export-cancel':self.assertEqual(value['operations'],[dict(type='shuffle',strategy='uniform')])
                else:
                    self.assertEqual([op['type'] for op in value['operations']],['shuffle','partition']*8+['shuffle'])
                    self.assertEqual([op['columns'] for op in value['operations'] if op['type']=='partition'],[['v']]*8)
                    self.assertTrue(all(op['strategy']=='uniform' for op in value['operations'] if op['type']=='shuffle'))

    def test_node_uses_real_operation_and_column_controls_for_exact_processing_recipe(self):
        script=r"""
const assert=require('node:assert/strict');
const {configureProcessing,configureExport,Counter}=require(process.argv[1]);
const operations=[];let selected,label='v';
const step=index=>({locator(selector){
  if(selector==='[data-field="strategy"]')return {async selectOption(value){assert.equal(operations[index].type,'shuffle');operations[index].strategy=value;}};
  if(selector==='[data-column-search]')return {async fill(value){assert.equal(value,'v');assert.equal(operations[index].type,'partition');}};
  if(selector==='[data-column-option="0"]')return {locator(name){assert.equal(name,'span');return {async textContent(){return label;}};},async click(){operations[index].columns=['v'];}};
  assert.equal(selector,'.column-chip span');return {async textContent(){assert.deepEqual(operations[index].columns,['v']);return 'v';}};
}});
const page={locator(selector){
  if(selector==='#new-operation')return {async selectOption(value){assert(['shuffle','partition'].includes(value));selected=value;}};
  if(selector==='#add-operation')return {async click(){operations.push({type:selected});}};
  assert.equal(selector,'#operations [data-step]');return {nth:step,async count(){return operations.length;}};
}};
(async()=>{
  await configureProcessing(page);
  assert.deepEqual(operations.map(op=>op.type),[...Array(8)].flatMap(()=>['shuffle','partition']).concat('shuffle'));
  assert.equal(operations.filter(op=>op.type==='partition'&&JSON.stringify(op.columns)==='["v"]').length,8);
  assert.equal(operations.filter(op=>op.strategy==='uniform').length,9);
  operations.length=0;await configureExport(page);
  assert.deepEqual(operations,[{type:'shuffle',strategy:'uniform'}]);
  const exportCounter=new Counter();exportCounter.expected={operations:[{type:'shuffle',strategy:'uniform'}]};
  exportCounter.request('/api/run-direct',{operations:[{type:'shuffle',strategy:'uniform'}]});
  assert.throws(()=>{const wrong=new Counter();wrong.expected=exportCounter.expected;wrong.request('/api/run-direct',{operations:[]});});
  operations.length=0;label='other';await assert.rejects(configureProcessing(page));
  const counter=new Counter();counter.expected={input:'retained',input_csv:{headers:true}};
  counter.request('/api/columns',counter.expected);assert.equal(counter.headerReads,1);assert.equal(counter.runs,0);
  assert.throws(()=>counter.request('/api/columns',{input:'wrong',input_csv:{headers:true}}));
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run(['node','-e',script,str(Path(control.__file__).with_name('browser.cjs'))],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_failed_export_diagnostics_are_bounded_and_do_not_reuse_baseline_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for index in range(1101):(root/('retained-%04d.part'%index)).write_bytes(b'')
            with patch.object(suite,'helpers',__import__('hosted_picker.suite',fromlist=['suite']),create=True):
                value=suite.diagnose_destination(root)
                self.assertEqual(len(value['entries']),8);self.assertTrue(value['moreEntriesPresent'])
                self.assertIn('not-verified-export',value['scope'])
                self.assertEqual(len(list(root.iterdir())),1101)
                self.assertFalse(any('sha256' in row for row in value['entries']))
            with patch.object(suite,'helpers',__import__('hosted_picker.suite',fromlist=['suite']),create=True):
                one=root/'single';one.mkdir();(one/'part').write_bytes(b'kept')
                self.assertFalse(suite.diagnose_destination(one)['moreEntriesPresent'])
                os.link(one/'part',one/'linked')
                with self.assertRaises(AssertionError):suite.diagnose_destination(one)

    def test_failed_export_diagnostics_query_full_windows_file_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);part=root/'part';part.write_bytes(b'')
            # Captured Python3.14 Windows DirEntry metadata has zero identities/link count.
            entry=SimpleNamespace(name=part.name,path=str(part),stat=Mock(return_value=SimpleNamespace(
                st_mode=33206,st_nlink=0,st_dev=0,st_ino=0,st_file_attributes=32)))
            with patch.object(suite,'helpers',__import__('hosted_picker.suite',fromlist=['suite']),create=True), \
                 patch.object(suite.os,'scandir',return_value=contextlib.nullcontext([entry])):
                value=suite.diagnose_destination(root)
            actual=part.lstat();row=value['entries'][0]
            self.assertEqual((row['dev'],row['ino']),(actual.st_dev,actual.st_ino))
            self.assertNotEqual(row['ino'],0);entry.stat.assert_not_called()

    def test_runtime_closure_requires_selected_trees_and_original_source_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);tools=root/'tools';browser=root/'browser';pw=root/'playwright'
            for folder in (tools,browser/'1.2.3.4',pw):folder.mkdir(parents=True)
            for file in (tools/'python',tools/'node',browser/'chrome',browser/'1.2.3.4'/'runtime.dll',pw/'index.js'):file.write_bytes(b'fixed')
            roots=[str(tools),str(browser/'1.2.3.4'),str(pw)]
            members={name:config.inventory(name) for name in roots}
            declared={name:dict(path=name,sha256=config.digest(name)) for names in members.values() for name in names}
            selected=root/'selection.json';selected.write_text(json.dumps(dict(source_commit=config.SOURCE,source_tree=config.TREE,inputs=list(declared.values()),input_directories=roots)))
            pin=dict(path=str(selected),sha256=config.digest(selected));declared[str(selected)]=pin
            value=dict(python=dict(path=str(tools/'python')),node=dict(path=str(tools/'node')),browser=dict(path=str(browser/'chrome')),browser_version='1.2.3.4',playwright_root=str(pw),runtime_roots=roots,input_directories=members,source_selection=pin)
            config.runtime_inventory(value,declared)
            with self.assertRaisesRegex(AssertionError,'complete selected runtime'):
                config.runtime_inventory(dict(value,runtime_roots=roots[:-1]),declared)
            omitted=dict(declared);del omitted[str(browser/'1.2.3.4'/'runtime.dll')]
            with self.assertRaisesRegex(AssertionError,'runtime membership incomplete'):config.runtime_inventory(value,omitted)
            shortened=dict(value,input_directories=dict(members,**{str(tools):[]}))
            with self.assertRaisesRegex(AssertionError,'runtime membership incomplete'):config.runtime_inventory(shortened,declared)

    def test_live_custody_binds_original_accounting_and_oldest_start_without_restamp(self):
        import copy
        custody=dict(reusedInput={'sha256':'fixed'},sampledOwnedBytes=123,retainedFixtureBytes=1048480,extraRetainedSourceFixtureBytes=0)
        baseline={'completed':'unchanged'};retained={'files':'unchanged'}
        proof=dict(schema='native-ui-live-custody-v1',configSha256='config',preflight={'sha256':'pref'},started_unix=100,finished_unix=105,input=custody['reusedInput'],accounting_baseline={k:custody[k] for k in ('sampledOwnedBytes','retainedFixtureBytes','extraRetainedSourceFixtureBytes')},baseline=baseline,originalCustodySha256='custody',retained_inputs=retained)
        fields=dict(CONFIG_SHA='config',PREPARATION={'sha256':'pref'},PLAN=dict(documents={'custody.json':'selected'},owned_roots=['root']))
        with patch.multiple(suite,**fields,create=True),patch.object(suite,'authorize_history',return_value=custody),patch.object(suite,'baseline_completed',return_value=baseline),patch.object(suite,'input_inventory',return_value=retained),patch.object(config,'digest',return_value='custody'):
            suite.authorize('root',159,observation=proof)
            for key,value in (('started_unix',98),('configSha256','other'),('originalCustodySha256','other'),('accounting_baseline',dict(proof['accounting_baseline'],sampledOwnedBytes=0)),('retained_inputs',{}),('baseline',{})):
                changed=copy.deepcopy(proof);changed[key]=value
                with self.subTest(key=key),self.assertRaises(AssertionError):suite.authorize('root',159,observation=changed)
            self.assertEqual(custody['sampledOwnedBytes'],123)

    def test_actual_cancel_phase_and_trusted_click_cannot_be_inferred_from_prior_poll(self):
        import copy
        case=dict(name='processing-cancel',job=dict(output='unused'))
        value=dict(submitted=case['job'],runs=1,cancels=1,picks=0,headerReads=1,activeBeforeCancel=dict(status='running',output='unused',progress=dict(rows=1,phase='Shuffling')),activeOrder=1,cancelOrder=2,terminalOrder=3,cancelRequested=True,cancelHTTP=200,cancelClick=dict(trusted=True,unixMs=102,monotonicMs=2,eventTimestamp=2),captureInstalledUnixMs=100,preClickUnixMs=101,terminalUnixMs=103,state=dict(status='cancelled',error='Job cancelled',progress=dict(rows=1,phase='Shuffling')))
        with patch.object(suite,'clean') as clean:
            suite.verify_case(case,value,Path('unused'),{})
            clean.assert_called_once()
            for mutation in ('phase','untrusted','late-click'):
                changed=copy.deepcopy(value)
                if mutation=='phase':changed['state']['progress']['phase']='Writing output'
                elif mutation=='untrusted':changed['cancelClick']['trusted']=False
                else:changed['cancelClick']['unixMs']=104
                clean.reset_mock()
                with self.subTest(mutation=mutation),self.assertRaises(AssertionError):suite.verify_case(case,changed,Path('unused'),{})
                clean.assert_not_called()
            exported=copy.deepcopy(value);exported['activeBeforeCancel']['progress']['phase']='Writing output';exported['state']['progress']['phase']='Writing output'
            suite.verify_case(dict(case,name='export-cancel'),exported,Path('unused'),{})

    def test_worker_accepts_only_matching_cold_preflight_then_complete_current_metadata(self):
        from scale_acceptance import hosted_qualification
        binding=dict(path='native-pref',sha256='a'*64)
        with patch.multiple(control,PLAN={'synthetic':True},CONFIG_PATH='exact-plan',PREPARATION=binding),patch.object(hosted_qualification,'preflight',return_value={'status':'passed'}) as proof,patch.object(config,'check') as metadata,patch.object(config,'validate') as cold:
            self.assertEqual(control.verify_sources(),{'status':'passed'})
            proof.assert_called_once_with(binding,'exact-plan','native-ui');metadata.assert_called_once_with(control.PLAN);cold.assert_not_called()
            proof.side_effect=ValueError('mismatched preflight');metadata.reset_mock()
            with self.assertRaisesRegex(ValueError,'mismatched preflight'):control.verify_sources()
            metadata.assert_not_called()

    def test_failed_case_audit_requires_positive_same_original_and_complete_cleanup(self):
        import copy
        value=dict(configSha256='config',preflight={'sha256':'pref'},acceptance=False,originalReservationClosedAfterQuiescence=True,released_after_supervision=True,original_lock_identity=[1,2],innerFinal={'pids':[]},outerFinal={'pids':[17]},reservation={'owner':{'pid':17}},diskSamplerJoined=True,watchdogJoined=True,parentPipeEOF={'stdout':True,'stderr':True},privateCleanup=dict(complete=True,owner=18,jobPids=[18],reaped=1,eof={'browser':{'stdout':True,'stderr':True}}),privateCaptureNames=['browser'],privateChildExitCodes=[1],process_identities=[dict(pid=17,created=100),dict(pid=18,created=101)],census_pids=[17,18,19])
        with patch.multiple(control,CONFIG_SHA='config',PREPARATION={'sha256':'pref'},PLAN=dict(original_lock={'identity':[1,2]})):
            self.assertEqual(control.after_exit_release(value),[dict(pid=17,created=[100]),dict(pid=18,created=[101]),dict(pid=19,created=None)])
            self.assertFalse(value['acceptance'],'ownership-only audit cannot relabel failed qualification')
            for field,bad in (('original_lock_identity',[1,3]),('innerFinal',{'pids':[19]}),('diskSamplerJoined',False),('released_after_supervision',False),('privateChildExitCodes',[])):
                changed=copy.deepcopy(value);changed[field]=bad
                with self.subTest(field=field),self.assertRaises(AssertionError):control.after_exit_release(changed)

    def test_native_setup_cleanup_audit_needs_no_nonexistent_private_worker(self):
        value=dict(configSha256='config',preflight={'sha256':'pref'},acceptance=False,originalReservationClosedAfterQuiescence=True,released_after_supervision=True,original_lock_identity=[1,2],innerFinal=None,outerFinal={'pids':[17]},reservation={'owner':{'pid':17}},diskSamplerJoined=True,watchdogJoined=True,process_identities=[dict(pid=17,created=100)],setupCleanup=dict(complete=True,worker_launch_attempted=False,capture_created=False,watchdog_joined=True,owned_job_pids=[17],acceptance=False))
        with patch.multiple(control,CONFIG_SHA='config',PREPARATION={'sha256':'pref'},PLAN=dict(original_lock={'identity':[1,2]})):
            self.assertEqual(control.after_exit_release(value),[dict(pid=17,created=[100])])
            value['setupCleanup']['worker_launch_attempted']=True
            with self.assertRaises(AssertionError):control.after_exit_release(value)

    def test_actual_cleanup_failure_always_stops_monitors_without_fd_release(self):
        source=Path(control.__file__).read_text();parent=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='parent')
        protected=next(n for n in parent.body if isinstance(n,ast.Try) and any(isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name) and call.func.value.id=='disk' and call.func.attr=='stop' for statement in n.finalbody for call in ast.walk(statement)))
        actual=compile(ast.Module(body=protected.finalbody,type_ignores=[]),'<retained Native cleanup>','exec')
        for fault in ('wait','census'):
            process=SimpleNamespace(pid=17,poll=lambda:None,kill=Mock(),wait=Mock(side_effect=OSError('primary wait failure')),stdin=SimpleNamespace(close=Mock())) if fault=='wait' else None
            windows=SimpleNamespace(query_job=Mock(side_effect=OSError('primary census failure')))
            disk=SimpleNamespace(stop=Mock());stopped=SimpleNamespace(set=Mock());watch=SimpleNamespace(join=Mock());close=Mock()
            scope=dict(record_job_census=lambda *args:None,windows=windows,outer=1,inner=None,p=process,report={'acceptance':False},capture=None,deadline=100,time=SimpleNamespace(monotonic=lambda:10),disk=disk,stopped=stopped,watch_started=True,watch=watch,os=SimpleNamespace(close=close))
            with self.subTest(fault=fault),self.assertRaisesRegex(OSError,'primary '+fault):exec(actual,scope)
            disk.stop.assert_called_once();stopped.set.assert_called_once();watch.join.assert_called_once();close.assert_not_called()

    def test_completed_failed_release_and_uncertain_fd_are_distinct(self):
        for still_open in (False,True):
            def parent(owner,**kwargs):owner[0]=SimpleNamespace(fd=123);return 1
            with patch.object(control,'parent',parent),patch.object(control.os,'fstat',return_value=SimpleNamespace()) as observed,patch.object(control,'retain_owner') as retained:
                if not still_open:observed.side_effect=OSError(errno.EBADF,'closed')
                self.assertEqual(control.execute_parent(),1)
                self.assertEqual(retained.call_count,int(still_open))

    def test_existing_disk_pending_fence_stops_future_observations(self):
        from scale_acceptance.guard import DiskObservation
        began=threading.Event();finish=threading.Event()
        def sample():began.set();finish.wait(2);return {'owned_bytes':7}
        disk=DiskObservation(sample).start()
        try:
            self.assertTrue(began.wait(1))
            with self.assertRaisesRegex(ValueError,'pending call'):disk.stop(timeout=.001)
            self.assertTrue(disk.pending)
        finally:finish.set();disk.stop(timeout=1)
        self.assertFalse(disk.pending)

if __name__=='__main__':unittest.main()
