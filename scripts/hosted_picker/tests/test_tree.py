import copy,unittest
from unittest.mock import patch
import diagnostics,model
from test_forest import Backend
from test_forest import identity
class API:
 def __init__(self):
  self.top=[1,9];self.rows={1:[30,0,'#32770',True],2:[30,1,'Edit',True],3:[30,1,'Button',False],9:[999,0,'SECRET',True]};self.child=[2,3];self.reads=[]
 def enumerate(self,visit):
  for h in self.top:visit(h)
 def children(self,root,visit):
  for h in self.child:visit(h)
 def owner(self,h):return self.rows[h][0]
 def visible(self,h):self.allowed(h);return self.rows[h][3]
 def enabled(self,h):self.allowed(h);return True
 def allowed(self,h):assert self.rows[h][0]==30,'foreign read';self.reads.append(h)
 def class_name(self,h):self.allowed(h);return self.rows[h][2]
 def parent(self,h):self.allowed(h);return self.rows[h][1]
 def control_id(self,h):self.allowed(h);return 1148 if h==2 else 1
 def text(self,h):raise AssertionError('No captions, Edit, filenames or titles')
class Tree(unittest.TestCase):
 def run_tree(self,a=None,b=None,clock=lambda:0):
  a=a or API();b=b or Backend();held=[]
  try:
   value=diagnostics.input_tree(b,7,b.ids[20],b.ids[10],1,lambda:None,a,model.observation,lambda f:held.append(f),clock,lambda t:None)
   self.assertTrue(held[-1].handles);self.assertFalse(b.closed)
   return value
  finally:
   if held and held[-1]:held[-1].close()
   self.assertCountEqual(b.opened,b.closed)
 def test_exact_child_tree(self):
  a=API();v=self.run_tree(a);self.assertEqual(v['identity']['pid'],30)
  self.assertEqual([p['pid'] for p in v['parentChain']],[30,20,10]);self.assertFalse(v['acceptance']);self.assertFalse(v['selectionEnabled'])
  self.assertEqual([n['caption'] for n in v['nodes']],[None,None]);self.assertNotIn(9,a.reads)
 def test_foreign_cyclic_unknown_parent_ambiguous_duplicate_node_and_class_bounds(self):
  for fault in ('foreign','cycle','parent','ambiguous','duplicate','class','node','empty','rootowner'):
   a=API()
   if fault=='foreign':a.rows[2][0]=999
   if fault=='cycle':a.rows[2][1]=2
   if fault=='parent':a.rows[2][1]=999
   if fault=='ambiguous':a.rows[4]=[30,0,'#32770',True];a.top.append(4)
   if fault=='duplicate':a.child.append(2)
   if fault=='class':a.rows[2][2]='x'*128
   if fault=='node':a.child=list(range(2,258));a.rows.update({h:[30,1,'Edit',True] for h in a.child})
   if fault=='empty':a.child=[]
   if fault=='rootowner':a.rows[1][0]=20
   with self.subTest(fault=fault),self.assertRaises((OSError,AssertionError)):self.run_tree(a)
 def test_race_replaced_timeout_enumeration_and_mutation(self):
  for fault in ('race','birth','enumeration','tree','deadline'):
   a=API();b=Backend();clock=lambda:0
   if fault=='enumeration':a.children=lambda *args:(_ for _ in ()).throw(OSError('enumeration'))
   if fault=='race':
    old=a.class_name
    def cls(h):
     value=old(h)
     if h==2:a.rows[2][0]=999
     return value
    a.class_name=cls
   if fault=='birth':
    old=a.class_name
    def cls(h):value=old(h);b.ids[30]['created']+=1;return value
    a.class_name=cls
   if fault=='tree':
    old=a.children;count=[0]
    def children(h,fn):
     count[0]+=1
     if count[0]==2:a.rows[2][1]=3
     old(h,fn)
    a.children=children
   if fault=='deadline':
    ticks=iter([0,6]);clock=lambda:next(ticks,6)
   with self.subTest(fault=fault),self.assertRaises((OSError,AssertionError)):self.run_tree(a,b,clock)
 def test_readiness_snapshots_close_before_fresh_and_visit_total(self):
  for count in (1,600):
   b=Backend();a=API();a.top=[9]*count;held=[];original=b.OpenProcess;previous=[0]
   def opened(*args):
    if args[-1]==10:
     self.assertEqual(len(b.closed),previous[0]);previous[0]+=4
    return original(*args)
   b.OpenProcess=opened
   try:
    with self.assertRaisesRegex(OSError,'exhausted|visit ceiling'):
     diagnostics.input_tree(b,7,b.ids[20],b.ids[10],1,lambda:None,a,model.observation,held.append,lambda:0,lambda t:None)
   finally:
    if held and held[-1]:held[-1].close()
   self.assertCountEqual(b.opened,b.closed);self.assertLessEqual(len(b.opened),32)
 def test_caption_utf16_and_byte_bounds(self):
  v=self.run_tree();v['nodes'][0]['caption']='x';
  with self.assertRaises(AssertionError):model.observation(v,v['identity'],[30],1)
  v=self.run_tree();v['nodes'][1].update(caption='x'*511,**{'class':'Button'})
  with self.assertRaises(AssertionError):model.observation(v,v['identity'],[30],1)
  with patch('json.dumps',return_value='x'*(1024**2+1)):
   with self.assertRaisesRegex(OSError,'byte ceiling'):self.run_tree()
if __name__=='__main__':unittest.main()

class ReadinessLifecycle(unittest.TestCase):
 def test_later_ready_snapshot_closes_previous_and_retains_found(self):
  b=Backend();a=API();held=[];enumerations=[0];original=a.enumerate
  def enumerate(visit):
   enumerations[0]+=1
   if enumerations[0]==1:visit(9)
   else:original(visit)
  a.enumerate=enumerate
  try:
   v=diagnostics.input_tree(b,7,b.ids[20],b.ids[10],1,lambda:None,a,model.observation,held.append,lambda:0,lambda t:None)
   self.assertEqual(v['snapshots'],2);self.assertEqual(len(b.closed),4)
   self.assertEqual(list(held[-1].handles),[10,20,30,40])
  finally:
   if held and held[-1]:held[-1].close()
  self.assertEqual(len(b.closed),9)
 def test_partial_capture_is_published_for_cleanup(self):
  b=Backend();b.fail_open=30;held=[]
  try:
   with self.assertRaisesRegex(OSError,'open race'):
    diagnostics.input_tree(b,7,b.ids[20],b.ids[10],1,lambda:None,API(),model.observation,held.append,lambda:0,lambda t:None)
   self.assertEqual(list(held[-1].handles),[10,20])
  finally:
   if held and held[-1]:held[-1].close()
  self.assertCountEqual(b.closed,b.opened)


class MembershipReadiness(unittest.TestCase):
 def run_capture(self,a,b,held,**kwargs):
  return diagnostics.input_tree(b,7,dict(b.ids[20]),dict(b.ids[10]),1,lambda:None,a,
   model.observation,held.append,kwargs.pop('clock',lambda:0),kwargs.pop('pause',lambda t:None),**kwargs)
 def close(self,b,held):
  for f in held:
   if f:f.close()
  self.assertCountEqual(b.opened,b.closed)
 def test_growth_and_shrink_discard_then_completely_rebind(self):
  for growth in (True,False):
   b=Backend();a=API();held=[];original=a.visible;changed=[False]
   def visible(h):
    result=original(h)
    if not changed[0]:
     changed[0]=True
     if growth:b.ids[50]=identity(50,20);b.pids.append(50)
     else:b.pids.remove(40)
    return result
   a.visible=visible
   try:
    value=self.run_capture(a,b,held,rebind_membership=True)
    self.assertEqual(value['snapshots'],2)
    first=held[0].evidence();self.assertFalse(held[0].handles)
    self.assertEqual(first['captured']['pids'],[10,20,30,40])
    self.assertEqual(first['membershipChange']['actual']['pids'],sorted(b.pids))
    self.assertEqual(sorted(v['pid'] for v in value['processes']),sorted(b.pids))
   finally:self.close(b,held)
 def test_default_strict_and_identity_flags_count_errors_do_not_rebind(self):
  for fault in ('strict','birth','root','node','reuse-with-growth','unknown','session','flags','count','incomplete'):
   b=Backend();a=API();held=[];original=a.visible;changed=[False]
   def visible(h):
    result=original(h)
    if not changed[0]:
     changed[0]=True
     if fault=='birth':b.ids[30]['created']+=1
     elif fault=='flags':b.query_job=lambda *args,**kwargs:dict(kill_on_close=False,pids=b.pids[:])
     elif fault=='count':b.pids=list(range(1,66))
     elif fault=='incomplete':
      class Incomplete(OSError):pass
      b.IncompleteJobCensus=Incomplete
      def query(*args,**kwargs):raise Incomplete('incomplete')
      b.query_job=query
     else:
      b.ids[50]=identity(50,20);b.pids.append(50)
      if fault in ('root','node'):b.ids[20 if fault=='root' else 10]['created']+=1
      elif fault=='reuse-with-growth':b.ids[40]['created']+=1
      elif fault=='unknown':b.ids[50]['image']=''
      elif fault=='session':b.ids[50]['session']=2
    return result
   a.visible=visible
   try:
    with self.subTest(fault=fault),self.assertRaises(OSError):
     self.run_capture(a,b,held,rebind_membership=fault!='strict')
   finally:self.close(b,held)
 def test_discard_close_failure_is_terminal(self):
  b=Backend();a=API();held=[];original=a.visible;close=b.close
  def visible(h):
   result=original(h)
   if 50 not in b.ids:b.ids[50]=identity(50,20);b.pids.append(50)
   return result
  def failing(h):
   if h==10:raise OSError('close failed')
   close(h)
  a.visible=visible;b.close=failing
  try:
   with self.assertRaisesRegex(OSError,'cleanup unknown'):
    self.run_capture(a,b,held,rebind_membership=True)
   self.assertEqual(len(held),1);self.assertTrue(held[0].cleanup_failed)
  finally:b.close=close;self.close(b,held)
 def test_membership_readiness_keeps_original_deadline_and_snapshot_bound(self):
  for deadline in (False,True,'visits'):
   b=Backend();a=API();held=[];original=a.visible;counter=[50];tick=[0]
   if deadline=='visits':a.top=[9]*600+[1]
   def visible(h):
    result=original(h);pid=counter[0];counter[0]+=1;b.ids[pid]=identity(pid,20);b.pids.append(pid)
    return result
   a.visible=visible
   def pause(seconds):
    if deadline is True and counter[0]>50:tick[0]=6
   try:
    with self.assertRaisesRegex(OSError,'deadline|snapshots exhausted|visit ceiling'):
     self.run_capture(a,b,held,rebind_membership=True,clock=lambda:tick[0],pause=pause)
    self.assertLessEqual(len([f for f in held if f]),8)
   finally:self.close(b,held)
