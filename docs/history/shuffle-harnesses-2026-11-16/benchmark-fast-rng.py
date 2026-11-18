"""Historical reproduction only: requires pinned pre-removal XOF builds.
Not a candidate harness for the current engine.
"""
"""Whole-job WSL source comparison: unchanged v1, pinned XOF caches and entropy setup.

Validate exact text/IDs/scopes/caps independently; require replay across cache
sizes for the pinned generator/plan and exact old/new v1 controls. Entropy jobs
record their effective seed and replay it once outside timing.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['before', 'after']:
        parser.add_argument('--' + name, type=Path, required=True)
        parser.add_argument('--' + name + '-allocator', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--workers', type=int, nargs='+', default=[1, 4])
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--variants', nargs='+')
    args = parser.parse_args()
    binaries = {name: getattr(args, name).resolve() for name in ['before', 'after']}
    allocators = {name: getattr(args, name + '_allocator') for name in ['before', 'after']}
    emit = lambda row: print(json.dumps(row), flush=True)
    emit({'type': 'environment', 'platform': platform.platform(), 'cache': 'warm uncontrolled', 'repeats': args.repeats, 'workers': args.workers, 'sha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k,p in binaries.items()}, 'allocator_sha256': {k: hashlib.sha256(p.read_bytes()).hexdigest() for k,p in allocators.items() if p}, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    # name, rows, payload width, extra columns, tuple count, strategy, memory
    cases = [('tiny_fisher', 16, 16, 0, 1, 'fisher_yates', 32),
             ('resident_fisher', 200000, 16, 0, 1, 'fisher_yates', 256),
             ('resident_keys', 200000, 16, 0, 1, 'uniform', 256),
             ('sparse_keys', 120000, 64, 0, 16, 'uniform', 32),
             ('many_fisher', 8192, 16, 0, 128, 'fisher_yates', 32),
             ('columns', 60000, 0, 32, 1, 'uniform', 32),
             ('external', 60000, 512, 0, 1, 'auto', 32),
             ('rare_wide', 10000, 16, 0, 1, 'uniform', 32)]
    variants = ['seeded_v1', 'before_v1', 'after_v1', 'xof64', 'xof256', 'xof1024', 'entropy_xof64']
    if args.variants: variants = [v for v in variants if v in args.variants]
    csv.field_size_limit(2097152)
    with tempfile.TemporaryDirectory(prefix='chopper-fast-rng-') as directory:
        root = Path(directory)
        for name, rows, width, columns, tuples, strategy, memory in cases:
            if args.cases and name not in args.cases: continue
            source, output, config = (root / n for n in ['input.csv','output','job.json'])
            def fields(i):
                payload = 'x' * (1800000 if name == 'rare_wide' and i == 0 else width)
                return [str(i), f'{i % tuples:03}', payload] + [str((i+c)%10) for c in range(columns)]
            header = ['id','key','payload'] + [f'c{c}' for c in range(columns)]
            with source.open('w', newline='') as stream:
                writer = csv.writer(stream,lineterminator='\n');writer.writerow(header);writer.writerows(fields(i) for i in range(rows))
            def verify(analysis, expect_execution=True):
                records = [json.loads(line) for line in (output/'manifest.jsonl').read_text().splitlines()]
                entries = [r for r in records if r['type']=='output']
                audit = next((r for r in records if r['type']=='execution_plan'),None)
                assert (audit is not None)==expect_execution
                if audit:
                    assert audit['effective_seed']==analysis['seed'] and audit['replay_guarantee']=='prepared_snapshot_only'
                    assert audit['source_logical_digest']==analysis['logical_digest']
                seen = bytearray(rows);digest = hashlib.sha256();last_key = None
                for entry in entries:
                    data=(output/entry['path']).read_bytes();assert len(data)==entry['csv_bytes']<=20000000
                    digest.update(data);digest.update(json.dumps({k:entry[k] for k in ['path','rows','csv_bytes','lineage']},sort_keys=True).encode())
                    key=entry['lineage'][-1]['values'][0] if tuples>1 else None
                    if key is not None: assert last_key is None or key>=last_key
                    last_key=key;count=0
                    with (output/entry['path']).open(newline='') as stream:
                        reader=csv.reader(stream);assert next(reader)==header
                        for row in reader:
                            i=int(row[0]);assert 0<=i<rows and not seen[i] and row==fields(i)
                            if key is not None:assert row[1]==key
                            seen[i]=1;count+=1
                    assert count==entry['rows']<=50000
                assert all(seen) and len(entries)==analysis['output_files']
                assert sum(e['csv_bytes'] for e in entries)==analysis['output_csv_bytes']
                choices=[r for r in records if r['type']=='execution_group']
                assert len(choices)==(tuples if expect_execution else 0) and all(r['uniform_full_permutation'] for r in choices)
                return (digest.hexdigest(),analysis['logical_digest'],analysis['stages']),choices
            for workers in args.workers:
                references,measures={},{}
                for repeat in range(args.repeats+int(any(allocators.values()))):
                    allocation=repeat==args.repeats
                    for variant in variants if repeat%2==0 else variants[::-1]:
                        build='before' if variant in ['before_v1','seeded_v1'] else 'after'
                        if allocation and not allocators[build]:continue
                        entropy=variant=='entropy_xof64';xof='xof' in variant
                        cache=64 if not xof or entropy else int(variant[3:])
                        operations=([{'type':'partition','columns':['key']}] if tuples>1 else [])+[{'type':'shuffle','strategy':strategy}]
                        job={'input':str(source),'output':str(output),'seed':None if entropy else 'fast-rng-measurement-v1','full_shuffle_policy':'flexible_v1','operations':operations,'resources':{'memory_mb':memory,'workers':workers,'max_record_bytes':2097152,'temp_dir':str(root)},'limits':{'rows':50000,'bytes':20000000}}
                        if variant=='seeded_v1':del job['full_shuffle_policy']
                        if xof:job['full_shuffle_rng']='blake3_xof_v1'
                        if cache!=64:job['resources']['shuffle_rng_buffer_bytes']=cache
                        config.write_text(json.dumps(job))
                        binary=allocators[build].resolve() if allocation else binaries[build]
                        command=[str(binary),str(config)] if allocation else [str(binary),'run','--config',str(config),'--yes']
                        stats=root/'time.txt';started=time.perf_counter()
                        process=subprocess.run(['/usr/bin/time','-f','%U %S %M','-o',str(stats),*command],capture_output=True,text=True,timeout=300)
                        if process.returncode:raise RuntimeError(f'{name}/{variant}: {process.stderr}')
                        elapsed=time.perf_counter()-started;result=json.loads(process.stdout);analysis=result['analysis'] if allocation else result
                        fingerprint,choices=verify(analysis,variant!='seeded_v1')
                        if not entropy:
                            key='xof' if xof else 'v1';assert references.setdefault(key,fingerprint)==fingerprint
                        if xof:
                            assert all(c['rng'].startswith('chopper-fast-rng-blake3-xof-1') and c['rng_cache_bytes']==cache for c in choices)
                        user,system,rss=map(float,stats.read_text().split())
                        record={'type':'allocation' if allocation else 'measurement','case':name,'workers':workers,'variant':variant,'repeat':repeat,'seconds':elapsed,'cpu_seconds':user+system,'peak_rss_kib':rss,'effective_seed':analysis['seed'],'diagnostics':analysis['diagnostics'],'peak_temp_bytes':analysis['peak_temp_bytes'],'algorithms':{a:sum(c['algorithm']==a for c in choices) for a in sorted({c['algorithm'] for c in choices})},'verified':True}
                        if allocation:record['allocation_profile']=result['allocation_profile']
                        else:measures.setdefault(variant,[]).append(elapsed)
                        emit(record);shutil.rmtree(output)
                        if entropy and repeat==0 and not allocation:
                            job['seed']=analysis['seed'];config.write_text(json.dumps(job))
                            replay=subprocess.run([str(binaries['after']),'run','--config',str(config),'--yes'],capture_output=True,text=True,check=True,timeout=300)
                            replay_fingerprint,_=verify(json.loads(replay.stdout));assert replay_fingerprint==fingerprint
                            emit({'type':'entropy_replay','case':name,'workers':workers,'seed':job['seed'],'verified':True});shutil.rmtree(output)
                if measures:emit({'type':'summary','case':name,'workers':workers,'median_seconds':{k:statistics.median(v) for k,v in measures.items()},'range_seconds':{k:[min(v),max(v)] for k,v in measures.items()}})


if __name__=='__main__':main()
