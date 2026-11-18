## Reproduction and correctness

A fixture captured from the pre-optimization executable covers 16 composed pipelines, including stratification, repeated grouping, adjacent shuffles, buffer shuffles, embedded newlines, Unicode, and NUL-containing partition keys. Regression tests compare every output's contents, path, metadata, and every stage statistic. Other tests cover shared balanced data, forced multi-level merge collisions, worker-count compression parity, cancellation, source replacement, exact encoded byte caps, and publication races.

Final verification on 2026-10-11 passed all 38 native tests and all 12 browser contracts, including external shuffling, compression roundtrips, and cancellation cleanup. Clippy with warnings denied, Rust formatting, native/WASI release builds, and TypeScript checking passed. An additional 120 randomized pipeline comparisons matched the previous executable: 94 successful jobs had identical stage statistics and outputs, and 26 invalid jobs were rejected by both builds. The browser parity test now orders files by their numeric output suffix; its original native-generated digest remains unchanged.

The benchmark script alternates old/new builds, reports median job times, and verifies logical output digests across builds and repetitions. Fixture generation and output verification are outside the timed interval. It cleans up its own input, spill, and output files.

```sh
source .tools/linux/cargo/env
cargo build --release --locked -p chopper --example generate --bin chopper
python3 scripts/benchmark-pipelines.py \
  --before /path/to/previous/chopper \
  --after .tools/linux/target/release/chopper \
  --generator .tools/linux/target/release/examples/generate \
  --rows 1000000 --repeats 3
```

Use `--work-dir` to select the filesystem for source, temporary data, and output. Keep a copy of the previous executable before rebuilding it.
