## Pending standalone Uniform spill admission (2026-11-25)

Deferred merging holds enough extra file and catalog capacity to deny a
subsequent spill before the final reader exists. A proposed fallback that
immediately drains the pending files through the ordinary hierarchy also
fails at this boundary. [Issue #20](https://github.com/jsmatfess/chopper/issues/20) ·
[Control summary](../../benchmarks/standalone-uniform-next-spill-peer-2026-11-25.json)

The feature-free Linux test fills 96 independently sorted tiny spill runs
and leaves one packed row waiting to spill. The ordinary sorter holds 33
runs after its eager 64-way merge. The wider sorter holds all 96. On the
same 512 MiB shared ledger, the test obtains a fixed 536,788,041-byte
competing grant immediately before the next spill. It leaves 65,535 bytes
alongside the wider sorter, one byte below the existing writer buffer.

| Sorter | Held runs | Working reservations, bytes | Result under the same peer |
| --- | ---: | ---: | --- |
| Ordinary | 33 | 7,737 | Next spill succeeds |
| Wider | 96 | 17,336 | Typed shared denial before writer |
| Wider with immediate ordinary drain | 96 | 17,336 | Typed shared denial during drain |

The successful ordinary case releases the early peer after the spill and
verifies all 97 IDs and fields in order. The unpressured wider control
also verifies all rows. Both denied paths release their managed files
and shared grants. The test isolates sorter intake and the attempted
fallback. Full CSV parsing, final writing under a late competing grant
and complete-job elapsed time have separate receipts. [Final reader and writer control](standalone-uniform-final-reader-admission-2026-11-25.md)

Keep the ordinary standalone merge hierarchy. A wider candidate needs
ownership that allows the old spill to succeed before the next temporary
writer or catalog is admitted, as well as the existing final writer
requirement. The early and late competing requests test different
simultaneous owners.

For replay, apply the [scratch patch](../../benchmarks/standalone-uniform-next-spill-peer-2026-11-25.patch)
to a disposable checkout of `e0fe0320a2a2da03c67be890ed35988f111e81ef`.
Use the default native Linux features and an ordinary soft descriptor
limit of at least 4096. The control derives one peer request from the
unpressured wider ownership, then applies it unchanged. Temporary path
length can affect the calibrated absolute bytes.

```sh
cargo test --locked -p chopper --lib standalone_uniform_pending_runs_spill_peer -- --nocapture --test-threads=1
```
