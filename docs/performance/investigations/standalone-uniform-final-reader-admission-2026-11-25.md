## Standalone Uniform final reader admission (2026-11-25)

Smaller reader buffers help the 164-run workload from the
[standalone shuffle screen](standalone-uniform-direct-publication-2026-11-25.md).
The 128-run holdout shows why a fixed smaller buffer still needs an
admission guard. [Issue #20](https://github.com/jsmatfess/chopper/issues/20) ·
[Control results](../../benchmarks/standalone-uniform-narrow-final-reader-check-2026-11-25.json) ·
[Scratch patch](../../benchmarks/standalone-uniform-narrow-final-reader-2026-11-25.patch)

### Matched writer and peer control

Feature-free Linux storage creates a known number of tiny raw runs at
256 MiB with a 512 MiB shared ledger. The prototype uses 12 KiB per reader
only for the wider final traversal. Ordinary readers use 64 KiB. The real
snapshot and direct encoders consume the sorted rows. The peer grant is
obtained after the final cursor opens and held through encoding.

| Initial runs | Ordinary live cursor bytes | Wider live cursor bytes | Result with shared peer |
| ---: | ---: | ---: | --- |
| 96 | 2,174,594 | 1,214,108 | Both encode 96 rows at a 530,512,996-byte peer |
| 164 | 2,504,064 | 2,074,036 | Both encode 164 rows at a 530,512,996-byte peer |
| 128 | 131,880 | 1,618,780 | Ordinary encodes all rows at a 535,219,364-byte peer. Wider returns typed shared denial. |

Both modes also encode all 128 rows at the original 530,512,996-byte
request. The stronger 128-run peer was selected once from the measured
wider live ownership, leaving 32 KiB to the writer, and reused unchanged
in both arms. Successful and denied cases verify tracked reservations,
temporary-directory and staging cleanup. This is a component result for
reader and writer coexistence with synthetic spill frames. The stopwatch
and usable-publication checks belong to the separate complete-job
screens.

### Decision and replay

Keep the current standalone route. At a constant 64-run ordinary fan-in,
128 raw runs become two final readers. The wider traversal opens 128.
At 164 runs the ordinary final cursor still opens 38 readers. A
conditional path needs conservative accounting based on the measured run
catalog, reader buffers and metadata, and the live writer. Prove that
pending run owners and the fallback stay within admission during intake,
and that the ordinary hierarchy can consume those same runs before row
emission. The 128-run holdout belongs in that check.

Start from `61c488d04a41dff4696e3bf0bc02dc4371f541d8`, copy the linked
patch into an isolated checkout, apply it with `git apply` and run the
focused control under the ordinary Linux descriptor limit.

```sh
cargo test --locked -p chopper --lib standalone_uniform_narrow_final_reader_bound -- --nocapture --test-threads=1
```

The first prototype added its method to the optional spill-block file
type. The feature-free build aliases that type to DiskFile, so the
attempt stopped at compile time. The replay places the capacity change
on DiskFile and passes with the same scope and fixed resource cases.
