import base64,copy,ctypes,io,json,queue,tempfile,time,types,unittest
from pathlib import Path
from unittest.mock import patch
import assets,diagnostics,model,suite,selection,config,control as m
HERE=Path(__file__).parent
from fake_inputs import layout as fake_layout, job as fake_job

class Worker(unittest.TestCase):
 def run_worker(self,fault=None,channel='chrome',case='success'):
  image=model.IMAGES[channel]
  order=[];events_ref={};children=[];sent=[];identities={}
  tree=dict(kind='owned-hosted-dialog-observation',mode='observe-input',channel='chrome',session=1,
   identity=dict(pid=22,parent=20,created=99,image=image),hwnd=1,rootClass='#32770',rootReady=True,
   nodes=[dict(hwnd=2,parent=1,owner=22,id=1148,ready=True,**{'class':'Edit'},caption=None)],selectionEnabled=False,acceptance=False)
  if fault=='ownership':tree['identity']={**tree['identity'],'parent':999}
  if fault=='path':tree['nodes'][0]['parent']=999
  class Input:
   closed=False
   def __init__(self,name):self.name=name
   def write(self,raw):
    value=json.loads(raw);sent.append(value);q=events_ref['q']
    if value.get('failed') is True:
     order.append('failure stop to Node');q.put(('browser',json.dumps(dict(kind='browser-closed'))));children[0].returncode=1
    elif 'phase' in value:q.put(('browser',json.dumps(dict(kind='browser-launched',version='156.0.8078.80'))))
    elif 'ownedBrowserBound' in value:
     q.put(('browser',json.dumps(dict(kind='capabilities',origin='http://127.0.0.1:54321',**{k:True for k in ('secure','isolated','shared','open','directory','locks','storage')}))))
     q.put(('browser',json.dumps(dict(kind='browse-start',mode='input',unixMs=1))))
     if fault=='pre-click':q.put(('browser',json.dumps(dict(kind='browser-closed'))))
     elif fault=='clicked-first':
      q.queue.clear();q.put(('browser',json.dumps(dict(kind='browse-clicked',mode='input',unixMs=2))))
     else:q.put(('browser',json.dumps(dict(kind='browse-clicked',mode='input',unixMs=2))))
    elif any(value.get(k) is True for k in ('inputObserved','outputObserved','permissionObserved')):
     q.put(('browser',json.dumps(dict(kind='picker-observation-complete',case=case,runs=0,acceptance=False))))
     q.put(('browser',json.dumps(dict(kind='browser-closed'))));children[0].returncode=0
    elif value.get('selected')=='input':
     stage=events_ref.get('stage')
     if stage:q.put(('browser',json.dumps(dict(kind='repeat-input-selected',stage=stage,filename='malformed.csv' if stage=='malformed' else 'tiny.csv',output='output',acceptance=False,byteConsumptionProven=False))))
     else:q.put(('browser',json.dumps(dict(kind='input-selected',filename='cancel.csv' if case in ('processing-cancel','export-cancel') else 'tiny.csv',output='',acceptance=False,byteConsumptionProven=False))))
    elif value.get('postClickObserved') is True:
     if fault=='run-event':q.put(('browser',json.dumps(dict(kind='run-clicked',runs=1))))
     else:q.put(('browser',json.dumps(dict(kind='post-click-dom',dom=dict(kind='FAKE DOM',output=''),acceptance=False,runs=0,outputConfirmationRequired=False))))
    elif 'inputVerified' in value and events_ref.get('stage'):
     stage=events_ref['stage'];q.put(('browser',json.dumps(dict(kind='repeat-ready-to-run',stage=stage,runs=1 if stage=='malformed' else 2,output='output'))))
    elif value.get('baselineVerified') is True or value.get('malformedVerified') is True:
     stage='malformed' if value.get('baselineVerified') else 'retry';events_ref['stage']=stage;events_ref['mode']='input'
     q.put(('browser',json.dumps(dict(kind='repeat-browse-start',stage=stage,mode='input'))))
     q.put(('browser',json.dumps(dict(kind='repeat-browse-clicked',stage=stage,mode='input'))))
    elif 'inputVerified' in value:
     events_ref['mode']='output'
     q.put(('browser',json.dumps(dict(kind='browse-start',mode='output'))))
     q.put(('browser',json.dumps(dict(kind='browse-clicked',mode='output'))))
    elif value.get('permissionInvoked') is True:
     order.append('postclick complete to Node')
     q.put(('browser',json.dumps(dict(kind='ready-to-run',runs=0,output='output',permissionConfirmed=True))))
    elif value.get('runApproved') is True and events_ref.get('stage'):
     stage=events_ref['stage'];q.put(('browser',json.dumps(dict(kind='repeat-run-clicked',stage=stage,runs=2 if stage=='malformed' else 3))))
     if stage=='malformed':q.put(('browser',json.dumps(dict(kind='malformed-failure-complete',runs=2,status='FAILED',error='CSV record 4 has 2 fields, expected 3',cleanup=dict(workspaces=[],locks=[])))))
     else:
      q.put(('browser',json.dumps(dict(kind='retry-export-complete',acceptance=False,runs=3,status='COMPLETE',output='output/chopper-results-00000000-0000-4000-8000-000000000001'))))
      q.put(('browser',json.dumps(dict(kind='browser-closed'))));children[0].returncode=0
    elif value.get('runApproved') is True:
     q.put(('browser',json.dumps(dict(kind='run-clicked',runs=1))))
     if case=='malformed-retry':
      q.put(('browser',json.dumps(dict(kind='baseline-export-complete',acceptance=False,runs=1,status='COMPLETE',output='output/chopper-results-00000000-0000-4000-8000-000000000000'))));return
     elif case in ('processing-cancel','export-cancel'):
      active=dict(status='RUNNING',phase='Reading CSV' if case=='processing-cancel' else 'Saving results (1/1101)',rows=65536 if case=='processing-cancel' else 0,monotonicMs=1)
      capture=dict(installed=dict(monotonicMs=2),events=[dict(active,monotonicMs=4,trusted=True,type='click')],taken=dict(monotonicMs=5))
      fields=dict(case=case,active=active,beforeClick=dict(active,monotonicMs=3),capture=capture)
      q.put(('browser',json.dumps(dict(kind='cancel-active-observed',case=case,active=active))))
      q.put(('browser',json.dumps(dict(kind='cancel-click-observed',**fields))))
      q.put(('browser',json.dumps(dict(kind='cancellation-complete',**fields,terminal=dict(status='CANCELLED',monotonicMs=6),cancelClicked=True,runs=1,status='CANCELLED',cleanup=dict(workspaces=[],locks=[])))))
     elif case=='success':q.put(('browser',json.dumps(dict(kind='tiny-export-complete',acceptance=False,runs=1,status='COMPLETE',output='output/chopper-results-00000000-0000-4000-8000-000000000000'))))
     else:q.put(('browser',json.dumps(dict(kind='controlled-failure-complete',acceptance=False,runs=1,status='FAILED',error='header/BOM exceeds output byte limit',cleanup=dict(workspaces=[],locks=[])))))
     q.put(('browser',json.dumps(dict(kind='browser-closed'))));children[0].returncode=0
   def flush(self):pass
   def close(self):self.closed=True
  class Process:
   def __init__(self,argv,**kwargs):
    order.append('spawn '+('browser' if not children else 'uia'))
    self.pid=20 if not children else 21;self.returncode=None if self.pid==20 else (1 if fault=='observer' else 0)
    self.stdin=Input('browser' if self.pid==20 else 'observe-input');children.append(self)
    identities[self.pid]=dict(pid=self.pid,parent=m.os.getpid(),created=1,image='node' if self.pid==20 else 'ps')
   def poll(self):return self.returncode
   def wait(self,timeout):
    order.append('wait '+str(self.pid));self.returncode=0 if self.returncode is None else self.returncode;return self.returncode
  class Capture:
   def __init__(self,p,name,q,f):
    self.name=name;self.eof={'stdout':True,'stderr':True};events_ref['q']=q
    if name=='observe-input':q.put((name,json.dumps(tree)))
   def finish(self,deadline):
    order.append('EOF '+self.name)
    if fault=='eof':raise OSError('fake missing EOF')
    return dict(stdout=True,stderr=True)
  class Kernel:
   def OpenProcess(self,*args):order.append('hold Chrome');return args[-1]
   def GetProcessTimes(self,handle,*stamps):stamps[0]._obj.dwLowDateTime=99;return True
   def IsProcessInJob(self,h,j,out):out._obj.value=fault!='held-job';return True
   def WaitForSingleObject(self,*args):return 258
  kernel=Kernel()
  # ctypes function attributes are needed on the fake callable too.
  def times(handle,*stamps):stamps[0]._obj.dwLowDateTime=98 if fault=='held-birth' else 99;return True
  kernel.GetProcessTimes=times
  class Windows:
   def process_identity(self,pid):
    if pid==23:return {**tree_identity,'pid':23}
    return tree_identity if pid==22 else (dict(pid=24,parent=22,created=100,image=image) if pid==24 else identities.get(pid,dict(pid=pid,parent=1,created=1,image='python')))
   def query_job(self,job,max_pids=256):return dict(kill_on_close=True,pids=[m.os.getpid(),20,24]+([] if fault=='chrome-not-in-job' else [22])+([23] if fault=='duplicate-root' else []))
   def held_identity(self,h,pid):return {**self.process_identity(pid),'session':1}
   def kernel(self):return kernel
   def checked(self,value):assert value;return value
   def close(self,h):
    order.append('close Chrome')
    if fault=='handle-close':raise OSError('fake close failure')
   def stop_descendants(self,*args):
    order.append('stop descendants')
    for c in children:
     if c.returncode is None:c.returncode=91
    return [m.os.getpid()]
  tree_identity=dict(pid=22,parent=999 if fault=='node-parent' else 20,created=99,image=image)
  class Server:
   failure=None;url='http://127.0.0.1:54321'
   def __init__(self,*args):pass
   def start(self):order.append('server start');return dict(url=self.url,owner=m.os.getpid())
   def stop(self):
    order.append('server stop/join')
    if fault=='server-stop':raise OSError('fake stop failure')
    return True
  def stop_live_disk():
   order.append('live disk joined')
   if fault=='live-disk-stop':raise OSError('live disk pending call')
  layouts={mode:fake_layout(mode) for mode in ('input','output')}
  class Send:
   def __init__(self):self.text={}
   def __call__(self,h,msg,capacity,pointer,flags,timeout,out):
    order.append('native message '+str(msg))
    if msg==12:self.text[h]=ctypes.wstring_at(pointer);out._obj.value=1
    elif msg==13:
     text=self.text[h];assert len(text)<capacity
     ctypes.memmove(pointer,ctypes.create_unicode_buffer(text),ctypes.sizeof(ctypes.c_wchar)*(len(text)+1))
     out._obj.value=len(text)
    else:out._obj.value=1
    return 1
  class ClassAPI:
   user=types.SimpleNamespace(SendMessageTimeoutW=Send())
   def enumerate(self,visit):visit(100);visit(999)
   def children(self,h,visit):
    for i in range(len(layouts[events_ref.get('mode','input')]['nodes'])):visit(101+i)
   def row(self,h):return layouts[events_ref.get('mode','input')]['nodes'][h-101]
   def parent(self,h):
    if fault=='path':return 999
    ix=self.row(h)['parentIndex'];return 100 if ix==-1 else ix+101
   def control_id(self,h):return self.row(h)['id']
   def enabled(self,h):return True
   def owner(self,h):return 999 if h==999 or fault=='ownership' and h==101 else 24
   def visible(self,h):return True
   def class_name(self,h):
    if fault=='observer':raise OSError('fake enumeration')
    return '#32770' if h==100 else self.row(h)['class']
  def postobserve(*args,**kwargs):
   order.append('postclick readonly observer');args[5]()
   if fault=='postclick-ownership':raise OSError('fake postclick changed owner')
   return dict(kind='exact-owned-post-output-click-windows',acceptance=False,runs=0,additionalClicks=0)
  def authorize(*args,**kwargs):
   order.append('fresh custody before browser')
   if fault=='expired-custody':raise OSError('fresh custody required')
  def input_tree(*args,**kwargs):
   order.append('membership rebind '+str(kwargs['rebind_membership']))
   return diagnostics.input_tree(*args,**kwargs)
  modules={'uia':types.SimpleNamespace(run=lambda *a,**kw:(order.append('uia exact permission') or dict(kind='owned-uia-permission-invoked',acceptance=False,actions=0 if case=='observe-permission' else 1,helperLaunched=True)),retain_cache=lambda *a,**kw:dict(complete=True,retained=True)), 'postclick':types.SimpleNamespace(observe=postobserve),'selection':types.SimpleNamespace(choose=selection.choose,choose_output=selection.choose_output,NativeMessages=selection.NativeMessages),'suite':types.SimpleNamespace(authorize=authorize,preflight=authorize,baseline_completed=lambda *a:{},verify_malformed_input=lambda *a:order.append('verify malformed'),committed_snapshot=lambda *a:dict(name='baseline'),verify_preserved_export=lambda *a,**kw:True,cancellation_click=suite.cancellation_click,cancellation_job=suite.cancellation_job,verify_cancelled_output=lambda *a,**kw:dict(complete=False,markerAbsent=True),verify_export=lambda *a,**kw:dict(complete=True),verify_output=lambda *a,**kw:None,REUSED_INPUT='fake-input',verify_reused_input=lambda *a:order.append('verify baseline'),PROFILE='fake-profile',verify_profile=lambda *a:None,node_exit_gate=suite.node_exit_gate,cleanup_helper=lambda *a,**kw:dict(complete=True)), 'diagnostics':types.SimpleNamespace(NativeWindows=ClassAPI,HeldForest=diagnostics.HeldForest,forest_classes=diagnostics.forest_classes,input_tree=input_tree),'browser-small-windows':Windows(),'validation-runner':types.SimpleNamespace(contain_session=lambda:None,_SESSION_JOB=9),
   'model':model,
   'assets':types.SimpleNamespace(read_package=lambda *a:(order.append('package bytes checked') or {'/index.html':b'FAKE'}),handler=assets.handler),
   'integration':types.SimpleNamespace(OwnedServer=Server,retained_ports=lambda roots:(order.append('retained origin audit') or set()))}
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);out=root/'attempt1';out.mkdir()
   docs={'package-binding.json':{},'job.json':fake_job(),'input-layout.json':layouts['input'],'output-layout.json':layouts['output'],'uia-binding.json':{},'permission-layout.json':{}}
   (out/'output-birth.json').write_text('{}');(out/'helper-temp-birth.json').write_text('{}');(root/'pins.json').write_text(json.dumps({'observe.ps1':'a'*64}))
   with patch.object(selection,'OUTPUT',str(out/'output')),patch.object(m,'disk_observer',return_value=types.SimpleNamespace(start=lambda:order.append('live disk started'),stop=stop_live_disk,pending=fault=='live-disk-stop')),patch.object(m,'live_custody',return_value=({}, {},0)),patch.object(config,'check',side_effect=lambda plan:order.append('complete metadata before browser')),patch.multiple(m,ROOT=root,OUT=out,PLAN=dict(malformed_input=dict(path='malformed.csv'),input=dict(path='cancel.csv' if case in ('processing-cancel','export-cancel') else 'tiny.csv'),inputs=[dict(path=str(m.HERE/'uia.ps1'),sha256='synthetic')],toolchains=dict(node_version='synthetic'),channel=channel,case=case,browser=dict(path=image),playwright_root='fake-deps',browser_version='156.0.8078.80',profile=dict(reuse=True)),document=lambda name:docs[name],load=lambda n:modules[n],verify_custody=lambda:dict(selectedZIP=dict(path='FAKE'),retainedProfile={},reusedInput={}),owned_roots=lambda *args:[root],
                       Capture=Capture,native_session=lambda p:1),patch.object(m.subprocess,'Popen',Process),patch.object(m.subprocess,'CREATE_NO_WINDOW',0,create=True),patch.object(m.sys,'stdin',io.StringIO('go\n')):
    error=None
    try:rc=m.worker(time.monotonic()+60)
    except BaseException as e:error=e;rc=None
    report=json.loads((out/'worker-result.json').read_text())
  return rc,error,report,order,sent
 def test_fresh_complete_metadata_and_custody_gate_browser_launch(self):
  rc,error,report,order,sent=self.run_worker()
  self.assertIsNone(error)
  self.assertLess(order.index('retained origin audit'),order.index('spawn browser'))
  self.assertLess(order.index('package bytes checked'),order.index('spawn browser'))
  self.assertLess(order.index('complete metadata before browser'),order.index('spawn browser'))
  self.assertLess(order.index('fresh custody before browser'),order.index('spawn browser'))
  self.assertLess(order.index('live disk joined'),order.index('fresh custody before browser'))
  self.assertTrue(report['liveCustodyDiskStopped'])
 def test_membership_rebind_is_only_before_first_native_selection(self):
  rc,error,report,order,sent=self.run_worker()
  self.assertIsNone(error)
  self.assertEqual([v for v in order if v.startswith('membership rebind ')],
   ['membership rebind True','membership rebind False'])
 def test_failed_readonly_capture_publishes_current_census_before_cleanup(self):
  rc,error,report,order,sent=self.run_worker('observer')
  self.assertIsNotNone(error)
  self.assertEqual(report['runs'],0)
  self.assertEqual(report['selections'],0)
  self.assertTrue(report['diagnosticForests'])
  facts=report['diagnosticForests'][0]
  self.assertIn(24,facts['captured']['pids'])
  self.assertIn(24,facts['last']['pids'])
  self.assertIn(24,[v['pid'] for v in facts['identities']])
  self.assertTrue(report['privateCleanup']['complete'])
  rc,error,report,order,sent=self.run_worker(fault='expired-custody')
  self.assertIsNotNone(error)
  self.assertNotIn('spawn browser',order)
  self.assertFalse(report.get('observationComplete'))

 def test_pending_live_custody_disk_prevents_browser_and_cleanup_credit(self):
  rc,error,report,order,sent=self.run_worker(fault='live-disk-stop')
  self.assertIsNotNone(error);self.assertNotIn('spawn browser',order)
  self.assertFalse(report.get('liveCustodyDiskStopped'))
  self.assertIn('server stop/join',order);self.assertIn('stop descendants',order)
  self.assertTrue(report['serverStopped']);self.assertTrue(report['privateCleanup']['complete'])
  with self.assertRaisesRegex(AssertionError,'live custody disk stop failed'):m.require_private_cleanup(report)
  with self.assertRaisesRegex(AssertionError,'live custody disk not joined'):
   m.require_private_cleanup(dict(liveCustodyDiskStarted=True,liveCustodyDiskStopped=False))
  with self.assertRaisesRegex(AssertionError,'live custody disk stop failed'):
   m.require_private_cleanup(dict(liveCustodyDiskStarted=True,liveCustodyDiskStopped=True,liveCustodyDiskStopError='second stop failed'))

 def test_layout_observations_cannot_run_or_qualify(self):
  for channel in ('chrome','msedge'):
   for case in ('observe-input','observe-output','observe-permission'):
    with self.subTest(channel=channel,case=case):
     rc,error,report,order,sent=self.run_worker(channel=channel,case=case)
     self.assertIsNone(error,str(error));self.assertEqual(rc,0)
     self.assertTrue(report['diagnosticComplete']);self.assertEqual(report['runs'],0)
     self.assertEqual(report['postClickObservationComplete'],case=='observe-permission')
     self.assertFalse(any(v.get('runApproved') for v in sent))
     self.assertEqual(report['inputObservation']['channel'],channel)
     m.require_private_cleanup(report)

 def test_channels_and_controlled_failure_use_the_same_worker(self):
  for channel in ('chrome','msedge'):
   for case in ('success','failure'):
    with self.subTest(channel=channel,case=case):
     rc,error,report,order,sent=self.run_worker(channel=channel,case=case)
     self.assertIsNone(error,str(error));self.assertEqual(rc,0)
     self.assertTrue(report.get('tinyExportComplete' if case=='success' else 'controlledFailureComplete'))
     self.assertLess(order.index('server stop/join'),order.index('EOF browser'))
     m.require_private_cleanup(report)

 def test_complete_event_protocol_and_cleanup(self):
  rc,error,report,order,sent=self.run_worker();self.assertIsNone(error,str(error));self.assertEqual(rc,0)
  self.assertTrue(report['observationComplete']);self.assertFalse(report['acceptance']);self.assertEqual(report['runs'],1);self.assertTrue(report['postClickObservationComplete'])
  self.assertEqual(sent[-1],dict(runApproved=True))
  self.assertLess(order.index('postclick complete to Node'),order.index('server stop/join'))
  self.assertLess(order.index('server stop/join'),order.index('stop descendants'))
  self.assertLess(order.index('stop descendants'),order.index('EOF browser'))
  self.assertLess(order.index('EOF browser'),order.index('close Chrome'))
  self.assertEqual([x for x in order if x.startswith('native message ')],['native message 12','native message 13','native message 245']*2)
  self.assertEqual(report['selections'],1);self.assertTrue(report['outputSelectedPublicUI']);self.assertTrue(report['inputSelectedPublicUI']);self.assertIn('postOutputClickObservation',report)
  self.assertEqual(report['outputObservation']['mode'],'observe-output')
  self.assertEqual(report['captureNames'],['browser']);self.assertEqual(report['inputObservation']['identity']['pid'],24)
  m.require_private_cleanup(report)
 def test_unknown_handle_cleanup_is_reported_and_blocks_release(self):
  rc,error,report,order,sent=self.run_worker('handle-close')
  self.assertIsNotNone(error);self.assertIn('diagnosticHandleCleanupError',report)
  self.assertFalse(report['observationComplete']);self.assertFalse(report['acceptance'])
 def test_browse_start_cannot_bind_or_acknowledge_tree(self):
  for fault in ('pre-click','clicked-first'):
   rc,error,report,order,sent=self.run_worker(fault)
   self.assertIsNotNone(error);self.assertNotIn('observation',report)
   self.assertFalse(any('observed' in value for value in sent))
 def test_negative_ownership_ancestry_observer_eof_server_stop(self):
  for fault in ('handle-close','pre-click','clicked-first','ownership','path','observer','eof','server-stop','duplicate-root','chrome-not-in-job','held-birth','held-job','node-parent','postclick-ownership','run-event'):
   with self.subTest(fault=fault):
    rc,error,report,order,sent=self.run_worker(fault);self.assertIsNotNone(error);self.assertIsNone(rc)
    self.assertIn('stop descendants',order);self.assertIn('server stop/join',order)
    self.assertFalse(report['acceptance'])
    if fault not in ('handle-close','eof','server-stop'):self.assertTrue(report['failureBrowserClosed'])
    self.assertLess(order.index('server stop/join'),order.index('EOF browser'))
    if fault not in ('handle-close','eof','server-stop'):self.assertFalse(any('observed' in x for x in sent))



 def test_cancellation_cases_keep_actual_picker_and_private_cleanup_protocol(self):
  for case in ('processing-cancel','export-cancel'):
   rc,error,report,order,sent=self.run_worker(case=case)
   self.assertIsNone(error)
   self.assertEqual(rc,0)
   self.assertTrue(report['cancellationComplete'])
   self.assertTrue(report['cancelledOutput']['markerAbsent'])
   self.assertEqual(report['runs'],1)
   self.assertTrue(report['privateCleanup']['complete'])
   self.assertFalse(report.get('tinyExportComplete',False))


 def test_same_context_malformed_retry_requires_three_ordered_runs_and_three_input_selections(self):
  rc,error,report,order,sent=self.run_worker(case='malformed-retry')
  self.assertIsNone(error,str(error))
  self.assertEqual(rc,0)
  self.assertTrue(report['malformedRetryComplete'])
  self.assertEqual(report['runs'],3)
  self.assertEqual(report['selections'],3)
  self.assertTrue(report['retry'])
  self.assertFalse(report['automaticRetry'])
  self.assertIn('CSV record 4',report['malformedFailure']['error'])
  self.assertEqual(sum(v.get('baselineVerified') is True for v in sent),1)
  self.assertEqual(sum(v.get('malformedVerified') is True for v in sent),1)
  self.assertEqual(sum(v.get('permissionInvoked') is True for v in sent),1)
  messages=[i for i,v in enumerate(order) if v.startswith('native message ')]
  self.assertEqual(len(messages),12)
  # Each stage's immutable-input callback runs again before every real message.
  for i in messages[6:9]:self.assertIn('verify malformed',order[messages[messages.index(i)-1]+1:i])
  for i in messages[9:12]:self.assertIn('verify baseline',order[messages[messages.index(i)-1]+1:i])

 def test_native_messages_rejects_unbound_and_wrong_stage_paths_before_ffi(self):
  def send(*args):self.fail('unbound path reached Windows message')
  user=types.SimpleNamespace(SendMessageTimeoutW=send)
  for messages,path in ((selection.NativeMessages(user),'malformed.csv'),
                        (selection.NativeMessages(user,path='malformed.csv'),selection.PATH),
                        (selection.NativeMessages(user,path='malformed.csv'),selection.OUTPUT)):
   with self.subTest(path=path),self.assertRaisesRegex(AssertionError,'unbound native picker path'):
    messages.message(1,12,path)


if __name__=='__main__':unittest.main()
