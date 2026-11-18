# Architecture, research, and implementation plan

Historical design/research: buffer-shuffle descriptions and negative controls below
refer to pre-removal builds. The current engine rejects that strategy and its
configuration fields; see [current specification](specification.md#shuffling-and-seeds).

Status: historical architecture/research plan, retained for rationale. Native CLI/local UI and the hosted WASI browser engine are now implemented, along with later profiling and performance work. Future-tense recommendations below reflect the original plan. Use [GitHub Issues](https://github.com/jsmatfess/chopper/issues) for current delivery status, [validation](validation.md) for evidence, [performance](performance.md) for implementation follow-ups, and [adaptive execution](adaptive-execution.md) for the remaining resource-planning design.

## Stack and boundaries

Recommend Rust for the processing engine and native executable, with a lightweight TypeScript browser UI served by the executable. Ship platform binaries with embedded UI assets so end users do not install language runtimes. Select and pin individual libraries during implementation after correctness and platform checks.

Separate a portable core (configuration, validation semantics, plan, allocation, keys, serialization rules) from native storage, scheduling, compression adapters, and the local HTTP host. Storage interfaces expose bounded read/write/spill primitives. Do not expose OS paths or native threads throughout the core.

Rust supports a browser WebAssembly target, but ordinary filesystem and thread APIs do not work there. A later worker-based browser adapter must provide those capabilities explicitly; this is not simply a native binary recompile. See the [Rust target documentation](https://doc.rust-lang.org/rustc/platform-support/wasm32-unknown-unknown.html).

Browser temporary storage can use OPFS, whose synchronous file access is available in workers and whose capacity is subject to origin storage quotas. Large-file browser support must be capability- and capacity-checked; the native billion-row target is not an unconditional browser promise. See [MDN's OPFS documentation](https://developer.mozilla.org/en-US/docs/Web/API/File_System_API/Origin_private_file_system).

Candidate modules: chopper-core, chopper-native, chopper-cli, chopper-server, and ui. Keep archive/codec dependencies behind adapters to allow different native and browser implementations. Add an early WASM build smoke check for the portable core, without pulling hosted delivery into v1.

## Physical planning

The logical plan defines results. The physical plan chooses in-memory processing, streaming passes, spools, sorting, or bucketed processing. Resource decisions must not alter the agreed semantics or uniform seeded results.

| Operation | Initial algorithm | External-memory concern |
| --- | --- | --- |
| Row/strict byte chunks | Serialize and count, close before overflow | Keep record serialization bounded; account for encoding and headers |
| Balanced split | Count then sequentially route at exact boundaries | Replay input or canonical spool |
| Low-cardinality partition | Bounded routing buffers with spill | Cap handles and total per-group memory |
| High-cardinality partition | External sort by tuple and current ordinal | Stable group order without random payload reads |
| Exact treatment allocation | Count each scope, then weighted remaining-quota draws | External aggregation/processing of high-cardinality strata |
| Uniform shuffle | Sort by deterministic random keys with collision refinement | Sequential sorted runs and bounded merge fan-in |
| Approximate shuffle | Deterministic bounded-buffer replacement and drain | Buffer capacity is an explicit semantic parameter |

Retain original identity separately from current sequence ordinals after shuffle. Sorting by current sequence restores the order entering an operation, not necessarily original input order. A stratified assignment can group records temporarily for counting/allocation, then restore current order before output.

Pipeline fusion is allowed only with equivalence evidence: partitioning, assignment, balanced splitting, and shuffle generally cannot be arbitrarily reordered. Analysis may need to execute expensive intermediate steps to know exact downstream counts; clearly expose that cost and reuse prepared spools where safe.

## Exact assignment without shuffling payloads

Given exact group quotas q[j] and R remaining rows in a scope, draw an unbiased integer in [0, R), select a group proportional to its remaining quota, decrement that quota, and advance. This design yields exactly the requested counts and uniform assignment among fixed-count allocations under ideal random draws. Each group's writes remain in encounter order.

Use integer rejection sampling, not floating-point probabilities or modulo-biased random draws. Namespace deterministic random streams by operation and scope. Persist or externally group per-stratum counters when they cannot fit RAM. At small sizes, enumerate possible draws to validate the allocation law, not just observed frequencies.

This avoids an unnecessary full payload shuffle when only random membership is required. It still requires exact scope counts; HLL cannot substitute for them.

## Uniform external-memory shuffle

Research establishes that external-memory random permutations can exploit distribution and sequential I/O. Sanders' [Random permutations on distributed, external and hierarchical memory](https://www.sciencedirect.com/science/article/abs/pii/S0020019098001276) studies this problem. Its theoretical and historical performance results are background, not a Chopper speed claim.

Proposed baseline: give each row a deterministic pseudorandom key derived from effective seed, shuffle operation/scope identity, original row identity, and key-block index. Sort lexicographically by those keys. Use the same key order in RAM and external merge sorting, so changing memory or run boundaries cannot change results.

Do not resolve equal finite keys by input ordinal: that introduces bias. Conceptually each key is an extendable random bit string. Start with a wide block (proposed 128 bits); equal prefixes acquire additional independently derived blocks until resolved. Inject collisions in tests so this path is actually exercised. Specify the keyed generator, domain encoding, key-block byte order, and version before implementation; use a stable established primitive, not platform hashing or library-default RNG behavior.

The ordering is uniform in the ideal independent-random-string model. Finite deterministic seeds and pseudorandom expansion give a reproducible computational implementation, not literal access to all N! permutations. State this distinction in technical documentation.

Sorted runs carry framed records or sequential payload blocks with their metadata. Sorting only offsets then randomly fetching KB-sized payloads is an alternative to benchmark, not the default: it can trade memory savings for poor disk access patterns.

Optional later optimization: recursively distribute by prefixes of the same random keys, process buckets in key order, and refine oversized buckets. Preserving the exact key ordering makes this equivalent to the baseline. Independent Fisher-Yates shuffles inside physical buckets would make results depend on bucket layout and are therefore unsuitable as a transparent substitution.

Classic in-memory Fisher-Yates is useful as a reference and benchmark, but is not an automatic fallback for the canonical key-sort shuffle because its seeded permutation would differ. Reservoir sampling selects a sample; it does not supply a complete shuffle.

For D bytes of intermediate representation, run generation writes roughly D, and each materialized merge level reads and writes roughly D. The final merge can stream to output. Actual peak disk includes live old/new runs, retained sources/spools, metadata, and staged outputs; estimate the schedule rather than promise a universal multiplier. Bound merge fan-in by both memory and file descriptors. Wide records and slow external disks make I/O, not row count alone, central to planning.

## Approximate shuffle

Proposed behavior: fill K record slots, then for each incoming record choose a uniform slot, emit that slot's record and replace it; at EOF randomly drain remaining slots. Reproduce exactly for fixed K, seed, algorithm version, and input order. This has limited mixing and is visibly labeled approximate.

K is a user-visible semantic configuration. Enforce a separate byte budget: variable-width records must spill slot payloads or fail with a resource error; never silently change K in response to available RAM. Analysis can recommend K, but the resolved value is recorded before execution. External slot payload access may be slow, which preview should expose when this strategy is selected.

## Analysis at large scale

Use bounded exact sets for small cardinalities; promote to HLL for preview estimates, hashing length-framed field tuples. Maintain sketches only for requested column combinations, not all possible subsets. The [original HyperLogLog paper](https://cermics.enpc.fr/~meuniefr/FlFuGaMe07.pdf) describes single-pass estimation with standard error approximately 1.04/sqrt(m). For 16,384 registers this is roughly 0.81%, not a worst-case bound. The paper was indexed during research, although direct PDF retrieval failed; confirm the reference before relying on further details.

Full-stream sketches still read all rows. Sampling saves I/O only for an explicitly incomplete preview; compressed input and multiline CSV limit arbitrary seeking. Exact cardinalities and per-scope counts require external aggregation when distinct keys exceed the memory budget.

Analyze and validate in the same pass where possible. Keep parsed-record spools when they save repeated decompression or expensive stages, subject to peak storage. Do not require spooling for simple replayable operations where another sequential pass is cheaper. Input digests allow detection of changed sources before publication.

## Parsing and codecs: early correctness risks

The popular Rust csv reader deliberately favors finding a parse over rejecting malformed quoting. It enforces equal widths by default, but that does not fulfill Chopper's strict grammar contract. See [its error-handling documentation](https://docs.rs/csv/latest/csv/struct.Reader.html). Evaluate a strict incremental validator paired with a fast parser, or a strict parser implementation. Validate byte-boundary splits, encoding decoder state, embedded newlines, and quote/escape transitions. Do not assume a library's strict/flexible flag covers malformed syntax.

CSV byte caps apply after encoding and serialization, not to input lengths or decoded character counts. A counting serializer must match the writing serializer. Stateful encodings and BOM/header costs need explicit tests; unsupported combinations must fail rather than silently miscount.

ZIP is an archive with independent entries and a central directory; large entry sizes/counts require ZIP64 support. Stream or spool its metadata instead of retaining a directory proportional to output count in RAM. Follow the [PKWARE ZIP specification](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT). One archive contains all output CSVs, so member-level splitting does not constrain total archive size.

For compressed-target estimates, sample serialized output with the chosen codec/settings using bounded effort, add a documented safety margin, and round conservatively. Include header/small-file overhead and report actual sizes afterward. Heterogeneous data may defeat the estimate; strict uncompressed caps remain available. Compression estimates must not change logical results with hardware or incidental scheduling: freeze the deterministic estimator's result in the resolved plan.

## Delivery sequence and evidence

1. Contract and primitive spikes: versioned config/plan model; deterministic identities and RNG protocol; strict CSV/encoding feasibility; streaming ZIP64 metadata feasibility; portable-core WASM build. Resolve encoding support and resource defaults here.
2. Native foundation: budgeting, cancellable I/O, framed spool format, source consistency, manifest streaming, safe staging/publication, parser and codecs. Add analysis and basic CLI.
3. Deterministic splitting: balanced counts, exact row/byte caps, bounded/external partition routing. Verify CLI --yes and configuration conflict diagnostics.
4. Random operations: exact allocation/stratification, canonical in-memory/external uniform shuffle, bounded-buffer mode, combined pipelines. These remain requirements for v1, not optional follow-ups.
5. Local web UI: shared plan/config schema, ordered pipeline editor, file/member selection, dialect preview, analysis confirmation, progress/cancellation, results. Embed production assets in releases.
6. Resource and release validation: Windows/macOS/Linux packaging and end-to-end correctness, disk-full/cancel/corrupt-input paths, and benchmark-driven planner tuning. Publish measured limits and resource assumptions.

Meaningful tests cover record conservation including duplicates, relative ordering, exact quota sums and rounding ties, high cardinality/skew, tiny groups, actual encoded byte boundaries, multiline fields, malformed syntax, archive checksum failures, injected random-key collisions, and identical seeded results across memory/worker settings and OSes. Use golden algorithm vectors and a deliberately simple small-data reference implementation for composed pipelines.

Exercise resource exhaustion and cancellation during every materialized phase and ZIP finalization; verify no successful destination appears and cleanup never touches unrelated files. Measure memory with large cardinality and oversized records, not only average-width friendly input. Strict allocation budgets include library overhead; RSS includes runtime/OS effects and must be measured separately.

Benchmarks span typical 10K/1M-row cases and external-memory cases larger than assigned RAM, with short and KB-wide records, skewed/high-cardinality keys, compressible/incompressible text, and different storage speeds. Report end-to-end time including analysis, throughput by phase, peak RSS, temporary/output bytes, and effective settings. Large synthetic generators must themselves stream.

A one-billion-row run on sufficiently provisioned storage is a scale acceptance target, not something small tests certify. Record hardware, free space, row width, seed/config, and conservation digests; do not claim it is verified until that run exists. Evaluate GPUs only after profiling shows a compute-bound phase that outweighs transfers and additional platform complexity.
