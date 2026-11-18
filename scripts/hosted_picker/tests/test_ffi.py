"""Fake FFI only: reuse definitions, never process state."""
import ctypes, importlib.util, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import diagnostics
from test_forest import Backend

class Call:
 def __init__(self,fn):self.fn=fn;self.calls=0;self.configured=0
 def __setattr__(self,key,value):
  if key in ('argtypes','restype'):self.configured+=1
  object.__setattr__(self,key,value)
 def __call__(self,*args):self.calls+=1;return self.fn(*args)

class CachedFFI(unittest.TestCase):
 def setUp(self):
  spec=importlib.util.spec_from_file_location('fake_ffi',Path(__file__).resolve().parents[2] / 'browser-small-windows.py')
  self.w=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.w)
  self.state=dict(pid=30,parent=20,created=30,session=1,status=258,exit_code=259,member=True)
  self.functions={}
  def function(name,fn):self.functions[name]=Call(fn);return self.functions[name]
  def image(h,flags,out,size):out.value='chrome';return True
  def info(h,kind,out,size,ret):out._obj.pid=self.state['pid'];out._obj.parent=self.state['parent'];return 0
  def times(h,birth,*rest):birth._obj.dwLowDateTime=self.state['created'];return True
  def session(pid,out):out._obj.value=self.state['session'];return True
  def exit_code(handle,out):out._obj.value=self.state['exit_code'];return True
  def member(h,j,out):out._obj.value=self.state['member'];return True
  def census(h,kind,out,size,ret):
   if kind==9:out._obj.basic.flags=0x2000
   else:out._obj.assigned=out._obj.count=1;out._obj.pids[0]=30
   return True
  self.k=SimpleNamespace()
  for name in ('OpenProcess','GetCurrentProcess','DuplicateHandle','CloseHandle','TerminateProcess','TerminateJobObject'):
   setattr(self.k,name,function(name,lambda *a:1))
  for name,fn in dict(GetProcessId=lambda handle:self.state['pid'],GetExitCodeProcess=exit_code,QueryInformationJobObject=census,WaitForSingleObject=lambda *a:self.state['status'],QueryFullProcessImageNameW=image,GetProcessTimes=times,ProcessIdToSessionId=session,IsProcessInJob=member).items():setattr(self.k,name,function(name,fn))
  self.n=SimpleNamespace(NtQueryInformationProcess=function('NtQueryInformationProcess',info))
  self.loads=[]
  def load(name,**kw):self.loads.append((name,kw));return self.k if name=='kernel32' else self.n
  self.patches=[patch.object(self.w,'os',SimpleNamespace(name='nt')),patch.object(ctypes,'WinDLL',load,create=True)]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
 def test_complete_kernel_declarations_keep_handle_outputs_live(self):
  kernel=self.w.kernel()
  configured={name:call.configured for name,call in vars(self.k).items()}
  self.assertTrue(all(count==2 for count in configured.values()),configured)
  self.assertEqual(kernel.GetProcessId.argtypes,[self.w.W.HANDLE])
  self.assertEqual(kernel.GetExitCodeProcess.argtypes,[self.w.W.HANDLE,ctypes.POINTER(self.w.W.DWORD)])
  code=self.w.W.DWORD()
  for pid,exit_code in ((30,259),(31,0)):
   self.state.update(pid=pid,exit_code=exit_code)
   self.assertEqual(kernel.GetProcessId(30),pid)
   self.assertTrue(kernel.GetExitCodeProcess(30,ctypes.byref(code)))
   self.assertEqual(code.value,exit_code)
  self.assertIs(self.w.kernel(),kernel)
  self.assertEqual(configured,{name:call.configured for name,call in vars(self.k).items()})
  self.assertEqual([name for name,kwargs in self.loads],['kernel32'])
 def test_bindings_and_structure_reused_but_every_identity_api_live(self):
  structure=self.w.PBI
  first=self.w.held_identity(30,30)
  configured={n:f.configured for n,f in self.functions.items()}
  self.assertIs(self.w.kernel(),self.k);self.assertIs(self.w.ntdll(),self.n)
  self.state.update(created=31,session=2,parent=21)
  second=self.w.held_identity(30,30)
  self.assertNotEqual(first,second);self.assertEqual(second['created'],31);self.assertEqual(second['session'],2)
  self.assertIs(self.w.PBI,structure)
  self.assertEqual([n for n,k in self.loads],['kernel32','ntdll'])
  self.assertEqual(configured,{n:f.configured for n,f in self.functions.items()})
  for n in ('QueryFullProcessImageNameW','NtQueryInformationProcess','GetProcessTimes','ProcessIdToSessionId'):self.assertEqual(self.functions[n].calls,2)
  self.assertEqual(self.functions['WaitForSingleObject'].calls,4)
  self.w.process_identity(30);self.w.process_identity(30)
  self.assertEqual(len(self.loads),2);self.assertEqual(self.functions['GetProcessTimes'].calls,4)
 def test_cached_bindings_deny_birth_session_member_and_handle_drift(self):
  for fault in ('created','session','member','status','pid','last-wait'):
   with self.subTest(fault=fault):
    self.state.update(pid=30,parent=20,created=30,session=1,status=258,member=True)
    b=Backend();b.kernel=self.w.kernel;b.held_identity=self.w.held_identity
    f=diagnostics.HeldForest(b,7,{}, {},1,lambda:None)
    f.handles={30:30};f.identities={30:self.w.held_identity(30,30)}
    f.check_members([30])
    before={n:fn.calls for n,fn in self.functions.items()}
    if fault=='last-wait':
     waits=iter((258,0));self.functions['WaitForSingleObject'].fn=lambda *a:next(waits)
    else:self.state[fault]={'created':31,'session':2,'member':False,'status':0,'pid':31}[fault]
    with self.assertRaises(OSError):f.check_members([30])
    self.assertGreater(self.functions['IsProcessInJob'].calls,before['IsProcessInJob'])
    if fault not in ('member','status'):self.assertGreater(self.functions['GetProcessTimes'].calls,before['GetProcessTimes'])
    self.functions['WaitForSingleObject'].fn=lambda *a:self.state['status']
  self.assertEqual([n for n,k in self.loads],['kernel32','ntdll'])
 def test_job_census_is_live_with_cached_kernel(self):
  self.assertEqual(self.w.query_job(7)['pids'],[30])
  self.assertEqual(self.w.query_job(7)['pids'],[30])
  self.assertEqual(self.functions['QueryInformationJobObject'].calls,4)
  self.assertEqual(len(self.loads),1)

if __name__=='__main__':unittest.main()
