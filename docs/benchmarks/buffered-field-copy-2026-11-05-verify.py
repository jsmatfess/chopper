import pathlib,json,sys
p=pathlib.Path(sys.argv[1]);d=json.loads((p/'records.json').read_text());a=d['complete_jobs'];assert len(a)==6 and [r['candidate'] for r in a]==[False,True,True,False,False,True]
for recipe,n in [('pipeline',1000000),('ordered',1000000)]:
 cell=[r for r in a if (r['recipe'],r['rows'])==(recipe,n)];assert len({r['exact_verified_sha256'] for r in cell})==1
assert all(d['verification'].values()) and all(r['cleanup'] and r['cpu']['ok'] and r['reported_analysis_diagnostics']['process_memory']['limit_bytes']==33554432 for r in a)
print(json.dumps(d['summaries'],indent=2));print('Six exact completed jobs and separate CPU measurements verified')
