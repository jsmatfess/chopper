import base64,json,unittest
from pathlib import Path
import diagnostics
HERE=Path(__file__).parent
class Fake:
 def __init__(self,rows):self.rows=rows;self.reads=[]
 def enumerate(self,visit):
  for h in self.rows:visit(h)
 def owner(self,h):return self.rows[h][0]
 def visible(self,h):
  assert self.owner(h)==22,'foreign visibility inspected'
  return self.rows[h][1]
 def class_name(self,h):
  assert self.owner(h)==22,'foreign class inspected'
  self.reads.append(h);return self.rows[h][2]
class Diagnostics(unittest.TestCase):
 def test_records_exact_visible_owner_and_never_foreign_or_hidden_class(self):
  api=Fake({1:(99,True,'SECRET'),2:(22,True,'Chrome_WidgetWin_1'),3:(22,False,'HIDDEN')});checks=[]
  value=diagnostics.owner_classes(api,22,lambda:checks.append(True))
  self.assertEqual(value['windows'],[dict(hwnd=2,owner=22,**{'class':'Chrome_WidgetWin_1'})])
  self.assertEqual(value['dialogCount'],0);self.assertFalse(value['acceptance']);self.assertFalse(value['selectionEnabled'])
  self.assertEqual(api.reads,[2]);self.assertGreaterEqual(len(checks),5)
 def test_ambiguous_dialogs_are_metadata_never_selected(self):
  value=diagnostics.owner_classes(Fake({1:(22,True,'#32770'),2:(22,True,'#32770')}),22,lambda:None)
  self.assertEqual(value['dialogCount'],2);self.assertFalse(value['selectionEnabled'])
 def test_changed_owner_and_held_identity_fail_closed(self):
  api=Fake({1:(22,True,'#32770')})
  def changed(h):api.rows[h]=(99,True,'foreign');return '#32770'
  api.class_name=changed
  with self.assertRaisesRegex(OSError,'changed'):diagnostics.owner_classes(api,22,lambda:None)
  def invalid():raise OSError('held birth changed')
  api=Fake({1:(22,True,'#32770')})
  with self.assertRaisesRegex(OSError,'held birth'):diagnostics.owner_classes(api,22,invalid)
  self.assertEqual(api.reads,[])
 def test_record_and_enumeration_bounds(self):
  with self.assertRaisesRegex(OSError,'ceiling'):diagnostics.owner_classes(Fake({h:(22,True,'C') for h in range(1,66)}),22,lambda:None)
  with self.assertRaisesRegex(OSError,'ceiling'):diagnostics.owner_classes(Fake({h:(99,True,'SECRET') for h in range(1,4098)}),22,lambda:None)
if __name__=='__main__':unittest.main()
