## Terminal Uniform short tail (2026-11-21)

A bounded pending run catalog and a shorter interim merge changed
8 GiB complete-job elapsed by -17.24% and process
CPU by -1.26%. Managed temporary writes fell by
37.01%. The measurements met the predeclared retention rule for this opt-in path.
[Matched complete-job samples and retention criteria](../../benchmarks/terminal-uniform-short-tail-summary-2026-11-21.json)

| Median [observed range] | Original merge scheduling | Short-tail scheduling |
| --- | ---: | ---: |
 | Complete elapsed | 123.427 [113.156–124.531] s | 102.146 [99.170–104.880] s |
 | Process CPU | 63.73 [63.02–63.85] s | 62.93 [60.83–63.04] s |
 | Peak working reservations | 25241255 [25241255–25241255] bytes | 25333633 [25333633–25333633] bytes |
 | Peak process RSS | 30900 [30832–30996] KiB | 35464 [34544–35700] KiB |
 | Cgroup file-cache refaults | 10420996 [9530748–10856881] | 16761085 [12019504–16797443] |
 | Managed temporary writes | 22280144360 [22280144360–22280144360] bytes | 14033880552 [14033880552–14033880552] bytes |
 | Managed temporary reads | 22280142848 [22280142848–22280142848] bytes | 14033879040 [14033879040–14033879040] bytes |

Both builds formed 512 original runs. The control processed two
full 256-way intermediate merges followed by its last merge. The
candidate admitted up to 512 active readers within the existing
quarter-memory planning formula. The 96 MiB engine setting allows
roughly 380 readers. It consolidates only enough inputs to reach that
final limit, so only two total merges ran. The native candidate also
keeps a bounded catalog of pending open run owners. A low descriptor
limit, tighter reader or catalog admission, temporary-space pressure,
or the pending limit selects the original hierarchy. Those paths
move owned temporary files through the original sorter. The input
is consumed once.

The 8 GiB WSL2/ext4 jobs ran with one worker inside a hard 1 GiB
cgroup without swap. Each produced eight exact parts and observed the
1200 MiB serialized cap. An independent oracle checked every field,
unique source IDs, quotas, caps, shuffle nonidentity, manifest and
cleanup outside the stopwatch. One small and one full-size warmup
pair are excluded. Three alternating complete pairs contribute to
the table. Paired elapsed changes were -7.31%, -17.24%, -20.37%, and CPU changes were
-3.48%, -1.08%, -1.44%. Working reservations and process RSS describe different memory
scopes. Cache refaults describe the whole command scope.

Median working reservations rose by 92,378 bytes and process RSS by
4,564 KiB. The candidate's GNU time filesystem input counter rose
52.00% and cgroup file-cache refaults rose 60.84%. The filesystem
output counter fell 26.66%. The candidate showed greater cache
pressure alongside lower complete elapsed, CPU and managed reads
and writes on this fixture.

Focused native tests exercise exact output ordering and cleanup
of the pending catalog, the 1024-run transition to the old hierarchy,
the temporary-space guard and the lower descriptor limit. Native
storage tests and a compact-spill compile also passed. Higher active
fan-in and short-tail materialization are bundled in this trial.
The measured comparison does not isolate their separate time costs.
The source algorithm takes only the required excess through an
intermediate merge. [GNU Coreutils short-tail merge implementation](https://github.com/coreutils/coreutils/blob/v9.8/src/sort.c#L3682-L3740)
