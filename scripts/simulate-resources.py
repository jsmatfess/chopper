# Historical reproduction only: targets pinned pre-removal builds, not the current engine.
# Buffer-shuffle requests below are retained to interpret the recorded evidence.
"""Explore resource sensitivity. Estimates are hypotheses, not calibrated runtime guarantees.

All sizes describe DECOMPRESSED CSV. Override throughput using measured benchmark results.
This model excludes compression, browser RPC latency, skew, and pipeline fusion.
"""
import argparse
import itertools
import json
import math


def estimate(rows, width, memory_mb, disk_mib_s, cpu_rows_s, approximate):
    size = rows * width
    memory = memory_mb * 1024**2
    # Field allocations and sort keys often dominate narrow-row memory.
    row_memory = width + 160
    run_rows = max(1, int(memory * 0.4 / row_memory))
    runs = max(1, math.ceil(rows / run_rows))
    fan_in = max(2, min(64, int(memory / 4 / (row_memory + 65536))))
    passes = 0 if runs == 1 else math.ceil(math.log(runs, fan_in))
    spool = rows * (width + 64)
    uniform_io = 3 * size + (2 * passes * spool if runs > 1 else 0)
    # Buffer currently loses uniform's ingestion fusion: include its extra spool pass.
    buffer_io = 3 * size + 2 * spool
    uniform_cpu = rows / cpu_rows_s * (1 + math.log2(max(2, min(rows, run_rows))) / 20)
    buffer_cpu = rows / cpu_rows_s * 1.3
    uniform_seconds = uniform_cpu + uniform_io / (disk_mib_s * 1024**2)
    buffer_seconds = buffer_cpu + buffer_io / (disk_mib_s * 1024**2)
    strategy = 'buffer' if approximate and buffer_seconds < uniform_seconds * 0.8 else 'uniform'
    return dict(rows=rows,mean_row_bytes=width,memory_mb=memory_mb,disk_mib_s=disk_mib_s,
                cpu_rows_s=cpu_rows_s,estimated_runs=runs,estimated_merge_passes=passes,
                estimated_uniform_seconds=round(uniform_seconds,2),estimated_buffer_seconds=round(buffer_seconds,2),
                estimated_temp_bytes=max(size, 2*spool),recommended_strategy=strategy,
                suggested_buffer_rows=max(1,min(100000,int(memory/8/row_memory))),
                caveat='Mean-row estimate cannot guarantee memory bounds; validate against largest records. Buffer mixing is approximate.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rows',type=int,nargs='+',default=[1000000,1000000000])
    p.add_argument('--row-bytes',type=int,nargs='+',default=[16,140,1024])
    p.add_argument('--memory-mb',type=int,nargs='+',default=[32,128,256,512])
    p.add_argument('--disk-mib-s',type=float,nargs='+',default=[50,500,2000])
    p.add_argument('--cpu-rows-s',type=float,nargs='+',default=[250000,1000000])
    p.add_argument('--allow-approximate',action='store_true')
    args=p.parse_args()
    dimensions=[args.rows,args.row_bytes,args.memory_mb,args.disk_mib_s,args.cpu_rows_s]
    if any(not math.isfinite(n) or n<=0 for values in dimensions for n in values):
        p.error('All model inputs must be positive and finite')
    if math.prod(map(len,dimensions))>10000:p.error('At most 10000 scenarios')
    scenarios=[estimate(*values,args.allow_approximate) for values in itertools.product(*dimensions)]
    for scenario in scenarios: print(json.dumps({'type':'scenario',**scenario}))
    for rows,width,disk,cpu in itertools.product(args.rows,args.row_bytes,args.disk_mib_s,args.cpu_rows_s):
        candidates=[s for s in scenarios if (s['rows'],s['mean_row_bytes'],s['disk_mib_s'],s['cpu_rows_s'])==(rows,width,disk,cpu)]
        cost=lambda s:s['estimated_'+s['recommended_strategy']+'_seconds']
        best=min(map(cost,candidates))
        chosen=min((s for s in candidates if cost(s)<=best*1.1),key=lambda s:s['memory_mb'])
        print(json.dumps({'type':'recommendation','rule':'Smallest tested budget within 10% of modeled best runtime',**chosen}))


if __name__=='__main__':main()
