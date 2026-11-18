"""Exercise r11 production observer branches with fake handles/windows only."""
import unittest
import diagnostics, model
from test_tree import API
from test_forest import Backend, identity

class ScopedTree(unittest.TestCase):
 def observe(self, mutate):
  b=Backend();a=API();held=[];fired=[];original=a.class_name
  def cls(h):
   value=original(h)
   if h==2 and not fired:
    fired.append(True);mutate(b,a)
   return value
  a.class_name=cls
  try:
   result=diagnostics.input_tree(b,7,b.ids[20].copy(),b.ids[10].copy(),1,lambda:None,a,model.observation,held.append,lambda:0,lambda t:None)
   self.assertTrue(fired)
   self.assertEqual([p['pid'] for p in result['parentChain']],[30,20,10])
   self.assertFalse(set(b.closed)&{10,20,30},'target handles must remain held')
   return result,b,a
  finally:
   if held and held[-1]:held[-1].close()
   self.assertCountEqual(b.opened,b.closed)
 def test_unrelated_chrome_birth_is_bound_in_final_census(self):
  def birth(b,a):
   b.ids[50]=identity(50,20);b.pids.append(50)
   a.top.append(50);a.rows[50]=[50,0,'Chrome_WidgetWin_1',True]
   # API fixture permits only PID30 reads by default; explicitly admit the new bound Chrome.
   old=a.allowed
   def allowed(h):
    if h==50:a.reads.append(h)
    else:old(h)
   a.allowed=allowed
  result,b,a=self.observe(birth)
  self.assertIn(50,[i['pid'] for i in result['processes']]);self.assertIn(50,b.opened);self.assertIn(50,a.reads)
 def test_unrelated_exit_and_pid_replacement_allowed_after_rebinding(self):
  for fault in ('exit','birth'):
   def mutate(b,a):
    if fault=='exit':b.pids.remove(40);b.dead.add(40)
    else:b.ids[40]['created']+=1
   result,b,a=self.observe(mutate)
   self.assertEqual(40 in [i['pid'] for i in result['processes']],fault=='birth')
 def test_each_target_chain_member_birth_image_session_parent_membership_exit_liveness_denied(self):
  for pid in (30,20,10):
   for fault in ('birth','image','session','parent','membership','census','dead'):
    def mutate(b,a):
     if fault=='birth':b.ids[pid]['created']+=1
     elif fault=='image':b.ids[pid]['image']='replacement'
     elif fault=='session':b.ids[pid]['session']=2
     elif fault=='parent':b.ids[pid]['parent']=999
     elif fault=='membership':b.nonmembers.add(pid)
     elif fault=='census':b.pids.remove(pid)
     else:b.dead.add(pid)
    with self.subTest(pid=pid,fault=fault),self.assertRaises(OSError):self.observe(mutate)
 def test_new_extra_or_replaced_candidate_denied(self):
  for fault in ('extra','replacement'):
   def mutate(b,a):
    b.ids[50]=identity(50,20);b.pids.append(50)
    a.rows[50]=[50,0,'#32770',True];a.top.append(50)
    old=a.allowed
    def allowed(h):
     if h==50:a.reads.append(h)
     else:old(h)
    a.allowed=allowed
    if fault=='replacement':a.top.remove(1)
   with self.subTest(fault=fault),self.assertRaisesRegex(OSError,'candidate'):self.observe(mutate)
 def test_new_unknown_job_ancestry_membership_and_partial_refresh_cleanup(self):
  for fault in ('parent','membership','open','session','image','cycle'):
   def mutate(b,a):
    b.ids[50]=identity(50,20);b.pids.append(50)
    if fault=='parent':b.ids[50]['parent']=999
    elif fault=='membership':b.nonmembers.add(50)
    elif fault=='open':b.fail_open=50
    elif fault=='session':b.ids[50]['session']=2
    elif fault=='image':b.ids[50]['image']=''
    elif fault=='cycle':b.ids[50]['parent']=50
   with self.subTest(fault=fault),self.assertRaises(OSError):self.observe(mutate)
 def test_foreign_new_process_window_has_no_class_or_visibility_read(self):
  def mutate(b,a):
   a.rows[50]=[50,0,'SECRET',True];a.top.append(50)
  result,b,a=self.observe(mutate);self.assertNotIn(50,a.reads)

if __name__=='__main__':unittest.main()
