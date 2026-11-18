import unittest
from types import SimpleNamespace
import diagnostics
class Readiness(unittest.TestCase):
 def run_settle(self,sequence,kill=True):
  calls=[];now=[0.0]
  def query(job,max_pids):
   calls.append(1);return dict(kill_on_close=kill,pids=sequence[min(len(calls)-1,len(sequence)-1)])
  def guard():
   if now[0]>=5:raise OSError('deadline')
  backend=SimpleNamespace(query_job=query)
  def pause(n):now[0]+=n
  diagnostics.settle_job(backend,9,guard,lambda:now[0],pause,5)
  return len(calls),now[0]
 def test_four_equal_samples_before_binding(self):
  n,elapsed=self.run_settle([[1,2]])
  self.assertEqual(n,4);self.assertAlmostEqual(elapsed,.6)
 def test_startup_change_restarts_only_readiness_streak(self):
  n,elapsed=self.run_settle([[1],[1,2],[1,2]])
  self.assertEqual(n,5);self.assertAlmostEqual(elapsed,.8)
 def test_never_settled_has_eight_read_limit(self):
  with self.assertRaisesRegex(OSError,'did not settle'):self.run_settle([[i+1] for i in range(8)])
 def test_unknown_empty_or_noncontained_job_never_binds(self):
  for sequence,kill in [([[]],True),([[1]],False)]:
   with self.assertRaisesRegex(OSError,'Job unknown'):self.run_settle(sequence,kill)
if __name__=='__main__':unittest.main()
