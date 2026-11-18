"""Verify matched jobs, then summarize each workload/mode without pooling."""
import argparse,collections,hashlib,itertools,json,math,pathlib,statistics
p=argparse.ArgumentParser();p.add_argument('plan');p.add_argument('raw');p.add_argument('output');p.add_argument('--control',action='store_true');a=p.parse_args()
plan=json.loads(pathlib.Path(a.plan).read_text());raw=pathlib.Path(a.raw);records=[json.loads(line) for line in raw.read_text().splitlines() if line.strip()]
assert not any(row['kind']=='failure' for row in records),'Failed attempts are retained, never summarized as passes'
assert any(row['kind']=='batch_complete' for row in records),'Incomplete batch'
context=[row for row in records if row['kind']=='context'];assert len(context)==1
assert context[0]['plan_sha256']==hashlib.sha256(pathlib.Path(a.plan).read_bytes()).hexdigest(),'Plan identity mismatch'
measurements=[row for row in records if row['kind']=='measurement'];verified=[row for row in records if row['kind']=='verification'];ordered_expected=[b['id']+'-'+mode for b in plan['blocks'] for mode in b['modes']];expected=set(ordered_expected)
assert [row['sample'] for row in measurements]==ordered_expected,'Measurement order differs from declared blocks'
attempts=[row for row in records if row['kind']=='attempt'];assert [row['sample'] for row in attempts]==ordered_expected,'Missing or duplicate admitted attempts'
identities=[row for row in records if row['kind']=='browser_identity'];assert [row['block'] for row in identities]==[block['id'] for block in plan['blocks']],'Missing browser process identities'
assert len({(row['executable'],row['sha256'],row['version']) for row in identities})==1,'Browser executable changed between blocks'
identity=identities[0];assert context[0]['environment']['browser_executable']==identity['executable'] and context[0]['environment']['browser_executable_sha256']==identity['sha256'],'Browser context/process identity mismatch'
for row in attempts:assert row['browserVersion']==identity['version'],'Browser version mismatch'
for row in attempts:assert row['job_sha256']==hashlib.sha256(json.dumps(row['job'],separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'Job identity mismatch'
assert collections.Counter(row['sample'] for row in measurements)==collections.Counter(expected)
assert collections.Counter(row['sample'] for row in verified)==collections.Counter(expected)
for row in measurements:assert row['status']=='COMPLETE' and 0<row['elapsed_seconds']<=plan['job_deadline_seconds']
for w in plan['workloads']:
 rows=[r for r in verified if r['workload']==w['id']];digests={r['ordered_artifact_sha256'] for r in rows};assert len(digests)==1,('Seeded ordered CSV/lineage/digest mismatch',w['id'],digests)
 jobs=[{k:v for k,v in row['job'].items() if k!='output'} for row in attempts if row['workload']==w['id']];assert all(job==jobs[0] for job in jobs),'Unmatched configuration (only fresh output destination identity may differ)'
summary={'raw_sha256':hashlib.sha256(raw.read_bytes()).hexdigest(),'plan_sha256':hashlib.sha256(pathlib.Path(a.plan).read_bytes()).hexdigest(),'scope':'same-build matched complete hosted Runs through authoritative destination export/marker reply; public cleanup/UI completion checked separately; verification outside timer','uncertainty':None if a.control else 'exact paired-block bootstrap resampling distribution, conditional on these six blocks; one-sided 95th percentile, no population/tail claim','control':a.control,'cells':[]}
for w in plan['workloads']:
 blocks=[block for block in plan['blocks'] if block['workload']==w['id']];data={mode:[next(r['elapsed_seconds'] for r in measurements if r['sample']==block['id']+'-'+mode) for block in blocks] for mode in ['disabled','collapsed','expanded'] if all(mode in b['modes'] for b in blocks)}
 if a.control:continue
 assert set(data)=={'disabled','collapsed','expanded'} and len(blocks)==6,'Six complete balanced matched blocks required'
 assert {tuple(block['modes']) for block in blocks}==set(itertools.permutations(['disabled','collapsed','expanded'])),'All six mode permutations required'
 baseline=data['disabled'];base_median=statistics.median(baseline)
 for mode in ['collapsed','expanded']:
  values=data[mode];med=statistics.median(values);slowdown=med/base_median-1
  ratios=sorted(statistics.median(values[i] for i in indices)/statistics.median(baseline[i] for i in indices)-1 for indices in itertools.product(range(6),repeat=6))
  upper=ratios[math.ceil(.95*len(ratios))-1];mad=statistics.median(abs(value-med) for value in values)
  summary['cells'].append({'workload':w['id'],'mode':mode,'n':6,'disabled_seconds':baseline,'enabled_seconds':values,'disabled_median_seconds':base_median,'enabled_median_seconds':med,'disabled_range_seconds':[min(baseline),max(baseline)],'disabled_mad_seconds':statistics.median(abs(value-base_median) for value in baseline),'enabled_range_seconds':[min(values),max(values)],'enabled_mad_seconds':mad,'paired_slowdowns':[value/base-1 for value,base in zip(values,baseline)],'median_slowdown':slowdown,'paired_bootstrap_upper95_slowdown':upper,'gate_pass':slowdown<=.05 and upper<=.05})
summary['verified_jobs']=len(verified);summary['gate_pass']=not a.control and len(summary['cells'])==8 and all(cell['gate_pass'] for cell in summary['cells'])
pathlib.Path(a.output).write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps({'verified_jobs':summary['verified_jobs'],'gate_pass':summary['gate_pass'],'cells':[{k:cell[k] for k in ['workload','mode','median_slowdown','paired_bootstrap_upper95_slowdown','gate_pass']} for cell in summary['cells']]}))
