## Memory proportional writers and publication scheduling (2026-11-21)

Bounded concurrent writers and streaming publication reduced complete-job time on several inputs larger than the engine's working allocation. The changes remain local and experimental. The [comparison projection](../../benchmarks/memory-proportional-writers-summary-2026-11-21.json) records individual samples, spreads, build and source identities, and original record locations. Raw logs, inputs and binaries remain in local scratch. The projection replaces workstation path prefixes with labels.

Each timing cell has three alternating pairs through completed publication, with a separate excluded warmup. Linux runs used WSL2/ext4, one worker and a 1 GiB cgroup with swap disabled. Engine memory settings varied by cell. The harness requested input cache eviction. Host backing caches were uncontrolled. The cells use different pinned control and candidate pairs.

| Linux workload | Control median | Candidate median | Elapsed reduction |
| --- | ---: | ---: | ---: |
| Partition, 2 GiB and 8 keys | 16.304 s | 10.138 s | 37.8% |
| Stratified exact assignment, 2 GiB and 8 strata/outputs | 35.348 s | 16.854 s | 52.3% |
| Gzip Balanced, 2 GiB repeated payload | 17.807 s | 13.296 s | 25.3% |
| Gzip Balanced, 2 GiB varied payload | 70.485 s | 63.668 s | 9.7% |
| Zstandard Balanced, 2 GiB repeated payload | 13.297 s | 6.580 s | 50.5% |
| Wider writer ceiling, 8 GiB and 16,384 outputs | 266.971 s | 168.579 s | 36.9% |
| Batched final sync, 2 GiB and 8,192 outputs | 81.317 s | 40.962 s | 49.6% |

### Writer admission and publication

The experiments increase the limit from a fixed count to four writers per nominal MiB, then eight with 16 KiB CSV buffers. A single-record catalog allows sixteen per MiB up to 16,384 writers for eligible uncapped output, subject to Unix descriptor limits and ordinary memory admission. Replacing each writer's metadata file with a typed record removes a descriptor when the output shape guarantees one chunk. In the 8 GiB test the increased ceiling avoids the fallback and cuts managed temporary writes by 99.97%, at the cost of 44.52% higher working reservations and 28.73% higher CLI RSS. That is a whole-plan comparison. The fallback uses a different active writer and catalog path.

At 4,096 concurrent writers, smaller CSV buffers save 60.65% of working reservations and 64.55% of RSS. Smaller metadata buffers save 24.11% of working reservations while increasing median elapsed by 4.19%. The typed catalog saves 26.23% of working reservations and 16.81% of RSS at 8,192 writers. The smaller CSV buffers and typed catalog each have an adverse time pair. All three changes meet their recorded resource rules. A separate 1.5 GiB wide UTF-16 test saves 46.98% of working reservations and 16.04% elapsed by releasing header encoder scratch once encoded prefixes are retained.

Analyze estimates writer demand from existing key sketches and configured fanout. The estimate preserves exact or approximate status and reports unknown for unsupported correlated compositions. Run independently validates the input and applies hard file, descriptor and admission limits.

A diagnostic measured 41.835 seconds inside 8,193 successful sync calls over a 68.476-second Linux job. The candidate flushes each CSV, keeps its original file handle, and drains admitted pending syncs before returning Analysis or publishing. It preserves cancellation and error cleanup. The control ranged from 63.920 to 90.845 seconds and the candidate from 32.094 to 58.759. Every pair improved. CLI CPU dropped 15.71%, working reservations rose 0.18%, and managed writes were unchanged. A separate control confirmed 8,193 actual sync calls in the candidate. An interrupted pair had verified candidate output without an outer-clock endpoint. The projection excludes that pair and selects its separately completed replacement.

### Pipeline behavior and transfer

Bounded Partition streams into an admitted exact tuple map and preserves canonical group order and within-group encounter order. In the Linux cell it cuts managed temporary writes from about 2.71 GB to 3,184 bytes and CLI RSS by roughly 92%. Retained exact assignment counts strata over one retained parent and advances each stratum's unchanged quota and random stream in encounter order. It cuts managed temporary writes from 10.73 GB to 2.65 GB. Internal fixed-entropy controls test exact membership and output bytes.

Counted Balanced reuses the existing codec owners. Gzip's elapsed gains come with 14.26% higher CLI CPU on repeated data and 2.42% higher CPU on varied data. Zstandard saves 13.56% CPU on repeated data. Reported working snapshots cover different codec publication phases. The accounting measures working reservations and managed temporary traffic. CLI RSS, final CSV writes, and physical I/O have separate scopes.

Native Windows MSVC/NTFS runs used 2 GiB inputs, one worker and a 256 MiB engine setting. Partition improved from 9.516 to 5.905 seconds and stratified exact assignment from 22.561 to 12.785 seconds. Every pair improved. Process peak working set fell 90.88% and 90.73% respectively. Windows used uncontrolled caches and had no OS memory or swap cap. The Linux sync scheduling feature is inactive on Windows. The Partition control disables both the bounded Partition flag and the exact-assignment flag that enables it transitively. The latter has no work in that shape. The exact-assignment control differs by only its own flag. Full field, ID, encounter order, exact quota, manifest, cap and cleanup checks passed.

### Cross-tool comparison and requirement costs

The separate three-tool, 2 GiB, eight-key ordered Partition cohort measured Chopper at 10.540 seconds, qsv 29 at 4.676 seconds and the DuckDB 2.0 materialized adapter at 21.318 seconds. CLI or core process RSS was 5.6, 39.4 and 361.8 MiB respectively. All three completed under a 1 GiB cgroup. The adapter clocks include private output sync and rename. Chopper also implements its manifest, serialized caps and destination-race handling. The DuckDB extension identity comes from an earlier matching receipt and subsequent file metadata and hash. The original per-run list omits the extension, and the Python wrapper package lacks a separate pin.

qsv's partitioner uses a single pass with a key-to-writer map in its unlimited mode. Chopper applies that idea with bounded writer and exact-key admission. qsv's random sort is resident and its external sort has no random mode. Its split uses a ceiling-based chunk size, and the count prepass can use mmap and Polars. [qsv partition source](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/partition.rs) · [qsv sort source](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/sort.rs) · [qsv split source](https://github.com/dathere/qsv/blob/313132b8e25cbc2f1da0f72a805da86b7c84f179/src/cmd/split.rs)

DuckDB's partitioned COPY can reorder rows. An order-preserving streaming adapter failed DuckDB's 256 MiB admission after targeted controls. The successful adapter materialized all text fields, discovered keys and ran eight filtered COPY queries ordered by row ID. The measured result applies to that adapter. [DuckDB COPY source](https://github.com/duckdb/duckdb/blob/d54cbbe3df17e8e5ce68312f483b4155836112aa/src/execution/operator/persistent/physical_copy_to_file.cpp)

Chopper's logical digest accounts for roughly 1.1 user CPU seconds in one 2 GiB Partition profile. Standalone UTF-8 validation accounts for about 0.10 user CPU seconds. qsv accepted invalid UTF-8 and malformed quoting in controls where Chopper rejected the input. Chopper's empty-field quoting adds 16 MiB in this fixture. A separate eight-file sync probe measured 0.60 seconds inside sync calls. These estimates measure time spent or bytes added. They leave the causal elapsed cost of each requirement and the rest of qsv's lead unresolved.

### Rejections and validation

Compact rows regressed Interleaved by 33.95%. Plain input buffering and adaptive writer buffers missed their predeclared paired-time or resource rules. A bounded hash index improved only 1.94% at 512 keys with mixed pair directions and little resource change. A CSV-body spool plus offset index saved 18.89% CPU but increased Balanced elapsed by 11.84% and added about 2.23 GB of managed writes. The live prototypes were removed and their raw evidence preserved.

Linux default and all-feature native checks, native Windows lint and workspace tests, and 31 WASI/browser and restoration steps passed in the recorded source epochs. The first Windows gate exposed a one-ULP expected-versus-wire JSON timing mismatch. The test now parses both values through the same wire representation. The Windows performance attempts preserve a preflight invalidated by a status-file write race and a warmup that assumed a sort fallback where Windows correctly routed. The final hosted and native artifacts were rebuilt with default features. The first browser manifest omitted the static CSS and distribution notices. The separate final packaging receipt pins both. [Validation projection](../../benchmarks/memory-proportional-writers-checks-2026-11-21.json)

Explicit grouping Sort, remaining shuffle strategies, and broader codec and composed pipeline workloads still need decision-grade performance coverage. The results support retaining the scoped opt-in paths and resource tradeoffs.
