"""Decision-gate regressions with independently known constant timing effects."""
import hashlib,itertools,json,pathlib,subprocess,sys,tempfile,unittest
SCRIPT=pathlib.Path(__file__).with_name('analyze-execution-graph.py')
class GateTests(unittest.TestCase):
 def run_case(self,regression=False,missing=False,identity_mismatch=False):
  with tempfile.TemporaryDirectory() as directory:
   root=pathlib.Path(directory);plan={'job_deadline_seconds':300,'workloads':[{'id':str(i)} for i in range(4)],'blocks':[]}
   for repetition,modes in enumerate(itertools.permutations(['disabled','collapsed','expanded'])):
    for workload in plan['workloads']:plan['blocks'].append({'id':workload['id']+'-'+str(repetition),'workload':workload['id'],'modes':list(modes)})
   path=root/'plan.json';path.write_text(json.dumps(plan));records=[{'kind':'context','plan_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'environment':{'browser_executable':'test-browser','browser_executable_sha256':'b'*64}}]
   for block in plan['blocks']:
    records.append({'kind':'browser_identity','block':block['id'],'executable':'test-browser','sha256':'c'*64 if identity_mismatch and block==plan['blocks'][-1] else 'b'*64,'version':'test-version'})
    for mode in block['modes']:
     common={'sample':block['id']+'-'+mode,'block':block['id'],'workload':block['workload'],'mode':mode,'browserVersion':'test-version'};job={'seed':'fixed-'+block['workload'],'output':block['id']};records.append({'kind':'attempt',**common,'job':job,'job_sha256':hashlib.sha256(json.dumps(job,separators=(',',':')).encode()).hexdigest()})
     seconds={'disabled':100,'collapsed':102,'expanded':110 if regression and block['workload']=='3' else 104}[mode]
     records.append({'kind':'measurement',**common,'status':'COMPLETE','elapsed_seconds':seconds});records.append({'kind':'verification',**common,'ordered_artifact_sha256':'a'*64})
   if missing:records.pop()
   records.append({'kind':'batch_complete'});raw=root/'raw.jsonl';raw.write_text(''.join(json.dumps(row)+'\n' for row in records));out=root/'summary.json';result=subprocess.run([sys.executable,str(SCRIPT),str(path),str(raw),str(out)],capture_output=True,text=True)
   return result,json.loads(out.read_text()) if out.exists() else None
 def test_known_two_and_four_percent_effects_pass_each_cell(self):
  result,summary=self.run_case();self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(summary['gate_pass']);self.assertEqual(summary['verified_jobs'],72)
  for cell in summary['cells']:
   expected=.02 if cell['mode']=='collapsed' else .04;self.assertAlmostEqual(cell['median_slowdown'],expected);self.assertAlmostEqual(cell['paired_bootstrap_upper95_slowdown'],expected)
 def test_one_ten_percent_workload_regression_cannot_be_hidden(self):
  result,summary=self.run_case(regression=True);self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(summary['gate_pass']);failed=[cell for cell in summary['cells'] if not cell['gate_pass']];self.assertEqual([(cell['workload'],cell['mode']) for cell in failed],[('3','expanded')])
 def test_changed_browser_executable_cannot_create_a_summary(self):
  result,summary=self.run_case(identity_mismatch=True);self.assertNotEqual(result.returncode,0);self.assertIsNone(summary)
 def test_missing_verification_cannot_create_a_summary(self):
  result,summary=self.run_case(missing=True);self.assertNotEqual(result.returncode,0);self.assertIsNone(summary)
if __name__=='__main__':unittest.main()
