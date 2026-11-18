"""Read-only FFI and observer fakes; no native entry points."""
import unittest
import diagnostics, model, test_ffi
from test_forest import Backend
from test_tree import API

class Census(unittest.TestCase):
 def setUp(self):
  self.ffi=test_ffi.CachedFFI();self.ffi.setUp();self.w=self.ffi.w
 def tearDown(self):self.ffi.tearDown()
 def backend(self, sequence):
  b=Backend();self.calls=[];original=b.query_job
  def query(job,max_pids=64):
   self.calls.append(1)
   value=sequence[min(len(self.calls)-1,len(sequence)-1)]
   if isinstance(value,BaseException):raise value
   return original(job,max_pids)
  b.query_job=query;b.IncompleteJobCensus=self.w.IncompleteJobCensus
  return b
 def test_shared_query_strict_and_classifies_only_valid_in_capacity_incomplete(self):
  for assigned,count,pids,kind in ((4,3,[10,20,30],self.w.IncompleteJobCensus),(65,3,[10,20,30],OSError),(3,65,[],OSError),(2,3,[10,20,30],OSError),(4,3,[10,10,30],OSError),(4,3,[0,20,30],OSError)):
   def query(h,which,out,size,ret):
    if which==9:out._obj.basic.flags=0x2000
    else:
     out._obj.assigned=assigned;out._obj.count=count
     for i,pid in enumerate(pids):out._obj.pids[i]=pid
    return True
   self.ffi.functions['QueryInformationJobObject'].fn=query
   before=self.ffi.functions['QueryInformationJobObject'].calls
   with self.subTest(assigned=assigned,count=count,pids=pids),self.assertRaises(kind) as caught:self.w.query_job(7,64)
   self.assertEqual(self.ffi.functions['QueryInformationJobObject'].calls-before,2)
   if kind is self.w.IncompleteJobCensus:self.assertEqual((caught.exception.assigned,caught.exception.count),(4,3))
   else:self.assertNotIsInstance(caught.exception,self.w.IncompleteJobCensus)
 def test_real_fake_ffi_incomplete_then_complete_accepted_without_partial_metadata(self):
  b=Backend();calls=[];original=self.ffi.functions['QueryInformationJobObject'].fn
  def query(h,kind,out,size,ret):
   if kind==9:return original(h,kind,out,size,ret)
   calls.append(1);out._obj.assigned=4;out._obj.count=3 if len(calls)==1 else 4
   for i,pid in enumerate((10,20,30,40)):out._obj.pids[i]=pid
   if len(calls)==1:self.assertEqual(b.opened,[])
   return True
  self.ffi.functions['QueryInformationJobObject'].fn=query
  b.query_job=lambda job,max_pids=64:self.w.query_job(job,max_pids,self.ffi.k)
  b.IncompleteJobCensus=self.w.IncompleteJobCensus;held=[]
  try:
   v=diagnostics.input_tree(b,7,b.ids[20],b.ids[10],1,lambda:None,API(),model.observation,held.append,lambda:0,lambda t:None)
   self.assertEqual(v['snapshots'],1);self.assertFalse(v['selectionEnabled']);self.assertGreater(len(calls),2)
  finally:
   if held and held[-1]:held[-1].close()
  self.assertCountEqual(b.opened,b.closed)
 def test_persistent_incomplete_exactly_three_queries_no_metadata(self):
  b=self.backend([self.w.IncompleteJobCensus(4,3)]);a=API();held=[]
  with self.assertRaises(self.w.IncompleteJobCensus):diagnostics.input_tree(b,7,b.ids[20],b.ids[10],1,lambda:None,a,model.observation,held.append,lambda:0,lambda t:None)
  self.assertEqual(len(self.calls),3);self.assertEqual(b.opened,[]);self.assertEqual(a.reads,[]);self.assertEqual(held,[])
 def test_api_overflow_corrupt_errors_terminal(self):
  for message in ('Windows API failed','Job census oversized','Invalid Job census'):
   b=self.backend([OSError(message),None])
   with self.assertRaisesRegex(OSError,message):diagnostics.complete_census(b,7,lambda:None)
   self.assertEqual(len(self.calls),1);self.assertEqual(b.opened,[])
 def test_deadline_checked_between_acquisitions(self):
  b=self.backend([self.w.IncompleteJobCensus(4,3)]);ticks=[]
  def bounded():
   ticks.append(1)
   if len(ticks)==2:raise OSError('deadline')
  with self.assertRaisesRegex(OSError,'deadline'):diagnostics.complete_census(b,7,bounded)
  self.assertEqual(len(self.calls),1)
 def test_complete_foreign_unknown_and_changed_target_still_denied_after_incomplete(self):
  for fault in ('foreign','unknown','target'):
   b=self.backend([self.w.IncompleteJobCensus(4,3),None]);held=[];a=API();root=b.ids[20].copy();node=b.ids[10].copy()
   if fault=='foreign':b.member=False
   elif fault=='unknown':b.ids[30]['image']=''
   else:b.ids[20]['created']+=1
   try:
    with self.subTest(fault=fault),self.assertRaises(OSError):diagnostics.input_tree(b,7,root,node,1,lambda:None,a,model.observation,held.append,lambda:0,lambda t:None)
    self.assertEqual(a.reads,[])
   finally:
    if held and held[-1]:held[-1].close()
   self.assertCountEqual(b.opened,b.closed)
 def test_extra_dialog_still_denied_after_incomplete(self):
  b=self.backend([self.w.IncompleteJobCensus(4,3),None]);a=API();a.top.append(50);a.rows[50]=[30,0,'#32770',True];held=[]
  try:
   with self.assertRaisesRegex(OSError,'ambiguous'):diagnostics.input_tree(b,7,b.ids[20],b.ids[10],1,lambda:None,a,model.observation,held.append,lambda:0,lambda t:None)
  finally:
   if held and held[-1]:held[-1].close()
  self.assertCountEqual(b.opened,b.closed)
