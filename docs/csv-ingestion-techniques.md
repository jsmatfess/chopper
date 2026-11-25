# Bounded native CSV ingestion: techniques and experiment gates

Accessed 2026-11-05. Research only: no implementation, dependency selection,
measurements, policy changes or execution-graph work. Recommendations below are
inferences, explicitly distinguished from inspected behavior. [GitHub Issues](https://github.com/jsmatfess/chopper/issues) owns the
active backlog and specs.

## Finding

**Inference:** the plausible opportunities beyond the stronger strict serial
control are (1) amortizing structural searches without weakening the state
machine, and (2) bounded parallel parsing with useful initial computation in the
same worker pass. Rayon supplies scheduling, csveee supplies a fused speculative
processing model, and medialab supplies streaming search/record techniques. None
is an equivalent, resource-admitted replacement for Chopper as inspected.
There is no evidence here that any improves complete Chopper Runs.

Ordered export has little independent consumer computation to hide dispatch and
copying costs. Partition/probabilistic-allocation/uniform-shuffle ingestion offers
more possible key/record work, but global source IDs, ordered observations and
downstream memory headroom constrain fusion. These conclusions follow from the
current [direct loop][C-direct] and [operation ingestion loop][C-engine], rather
than upstream throughput comparisons.

## Inspected identities and evidence boundary

The published delivery locator below is a sanitized alias. The original locator
and inspected source remain privately retained; see the
[public source boundary](history/public-source-boundary.md). This editorial change
does not establish new runtime acceptance or change the recorded source identity.

| Source | Pinned identity and scope |
| --- | --- |
| Authoritative Chopper delivery | `a2ab151f341ec48691cc69c8bbc0d0bb994c5834`, clean Git status when inspected, at `/opt/chopper/source/inspected-delivery` (sanitized locator alias). Current facts below come from this tree, not the receiving checkout. |
| Rayon / rayon-core | Chopper lockfile: `rayon 1.12.0`, `rayon-core 1.13.0`. Inspected versioned official API docs and downloaded published sources; VCS identities `c9ced185ae3508246a9eb70c8407a1199bb1b77f` / `7af20d7692d5decbcb4adcaa079cd607e3e50814`. Archive SHA-256 values match Chopper's lockfile: `fb39b166781f92d482534ef4b4b1b2568f42613b53e5b6c160e24cfbfa30926d` / `22e18b0f0062d30d4230b2e85ff77fdfe4326feb054b9783a3460d8435c8ab91`. [Lockfile][C-lock] |
| ackxolotl/csveee | Behavioral audit uses published **0.2.1**, whose `.cargo_vcs_info.json` identifies `3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475`. Repository `main` resolved separately to `a79f1aa6c19a7fb2cf9132825c95ea689069925d`; do not silently substitute that head for the release. [Release source][E-release] |
| csveee paper | Ellmann/Neumann, *One Pass to Parse Them All: Fused Parallel CSV Processing*, PVLDB 19(11), DOI `10.14778/3836663.3836710`, §§3–4. Downloaded PDF SHA-256 `2b65fea8b62d5cffa19fe2a49bd608d9b5ce18e2d90a512dd68e75737e80ade2`. Paper and evolving crate are separate artifacts. [Author-hosted paper][paper] |
| medialab/simd-csv | `master` resolved to `df2cceb3bfe0427efc63fa213392f8c5b2713b47`; manifest version **0.14.0**. Source audit uses that commit, without asserting an identical crates.io release. This is **medialab/simd-csv**, not the unrelated `theo-lw/simd_csv`. [Manifest][M-manifest] |

Read the owning GitHub issue and parallel-execution research as conditional
context only. The current [specification][C-spec], [rewrite rules][C-rewrites]
and [direct-execution contract][C-contract] control eligibility. Graphify was
attempted first but reported “Graphify is not installed”; scoped source reads
supplied the findings. No installation followed.

The existing serial-span study is the stronger control: ordinary complete fields
ending at a buffered delimiter/LF can enter admitted reusable owned slots or
compact records without the scratch copy; other cases retain the strict path.
Its short ordered-export timing ranges overlap; the compact scan effect is
near-flat, and the pipeline pair is unreplicated. Component scans do not identify
CPU attribution or predict Run benefit, and modeled capacity requests increased.
This research neither reruns nor expands that terminal study. [Current parser][C-parser],
[recorded interpretation][C-performance]

## Technique comparison

| Technique | Documented/source behavior | Plausible Chopper use (inference) | Gate before a complete-Run challenger |
| --- | --- | --- | --- |
| Rayon indexed batches in the existing pool | `install` gives nested Rayon operations the selected pool; indexed iterators support positional splitting and reusable collection. `scope` joins children but allocates spawned tasks on the heap. `par_bridge` serializes individual `next()` pulls and does not preserve input order. [Pool][R-pool], [indexed API][R-indexed], [scope][R-scope], [bridge][R-bridge] | Schedule pre-admitted raw chunks or independent record/key work; use mutable indexed slots and ordered draining. A bridge around today's parser leaves parsing serial. | A byte/count-bounded producer, known valid record boundaries or a validated boundary algorithm, explicit ordered error/result handling, and admission for scheduler/result storage. Scheduling cannot establish CSV correctness. |
| csveee fused chunk processing | Chunk-local callbacks borrow mutable fields from parser storage; speculative callbacks can run repeatedly. Successful chunk states combine in file order after boundary reconciliation/reparse. `parse_stream` is sequential. [API/side effects][E-lib], [scheduler][E-scheduler], [merge][E-merge] | Parse and construct compact records or pure keys while bytes are hot; discard wrong speculative states. This has more theoretical opportunity than parse-then-revisit, but retaining all rows in chunk states defeats bounded streaming. | Strict dialect parity, bounded rolling results rather than whole-file chunk retention, Chopper admission callbacks, pool integration, stable global IDs and safe cancellation. No speculative callback may mutate authoritative observations or publish output. |
| csveee SIMD construction/UTF-8 techniques | The paper fuses parsing/processing and vectorizes structural indexing and record construction. Release 0.2.1's SIMD backend accepts fixed arity 1–63 and **only `QuoteHandling::Toggle`**; strict quoting and variadic mode route away from this backend. Text output validates UTF-8; byte output bypasses it. [Paper §§3–4][paper], [SIMD eligibility][E-simd], [output validation][E-output] | Study vectorized indexing or UTF-8 validation separately, keeping strict transitions. Do not assume choosing “Strict” retains the advertised SIMD pipeline. | Reconcile strict syntax with indexing, dynamic configured width, arbitrary supported column counts and historical working-limit/error behavior. Count any additional validation/index pass. |
| medialab hybrid search and record views | A state machine consumes SIMD search masks, reusing multiple structural hits for unquoted data; quoted data searches for the next quote. Zero-copy fields borrow the reader and can still contain quotes/escapes; copied records amortize allocations. [Design/source][M-lib], [record API][M-records], [reader][M-zero] | Try amortizing Chopper's repeated searches, or an admitted borrowed-span-to-owned/compact handoff. Most attractive where mask reuse removes work beyond current memchr spans. | Preserve strict states; account for refill/escape slow paths, UTF-8, unescaping and final retained record copies. Public reader replacement is blocked by documented semantic differences. |

Chopper already creates a job-local native Rayon pool, with resolved worker count
and 1-MiB thread stacks. `for_each_batch` executes admitted mutable slots without
collecting another result vector. Reusing this pool is
the relevant native seam. The optional profile implementation is only a precedent
for admitted ordered slots: it parses serially and parallelizes hashes in its own
profile pool, not Run ingestion. [Context/pool methods][C-storage],
[profile records][C-profile]

Calling csveee inside `install` does **not** redirect its workers: its scheduler
uses `std::thread::Builder::spawn_scoped`, not Rayon. It allocates a result slot
for every file chunk and waits for worker completion before ordered collection;
merge then allocates a vector of accepted states. Its I/O limit bounds ring
buffers, not all callback states, result metadata or mmap residency. These are
specific integration gaps, even with explicit concurrency. [Scheduler][E-scheduler],
[merge][E-merge], [resource API][E-builder]

## Semantic and API gates

The Chopper side of this table is current implementation, not merely a permissive
interpretation of RFC CSV. The parser and incremental decoder enforce quoting,
UTF-8 and working limits; ingestion/header code supplies expected width, source
IDs and observations. [Parser/decoder][C-parser], [header][C-header],
[ingestion][C-engine]

| Contract / concrete probe | Inspected upstream gap and required resolution |
| --- | --- |
| `ab"c,d\n` must reject a quote inside an unquoted field; `"a"x,b\n` must reject junk after closing quote. | csveee Strict DFA has error transitions for both; default Toggle is insufficient, and Strict disables its SIMD backend. medialab documents that mid-field/multiple quote pairs can misparse or lose content. Field-count checks cannot restore discarded text. [csveee transitions][E-table], [SIMD gate][E-simd], [medialab caveats][M-lib] |
| LF and CRLF accepted; bare CR outside quotes rejected; quoted CR/newlines preserved. | csveee CRLF configuration treats CR and LF as terminator bytes and skips runs; it does not impose Chopper's mandatory CR-followed-by-LF check. medialab documents leading-CR trimming. Probe `a,b\rc,d\n`, `\ra,b\n`, split CR/LF buffers, and quoted CR. Neither default provides parity. [csveee config][E-config], [skip logic][E-chunk], [medialab caveats][M-lib] |
| Bare blank records rejected unless configured to skip; `""\n` is a valid one-field record. | Both upstream paths skip bare empty lines. csveee's skip loop consumes configured terminator runs; medialab documents this policy. Once skipped, a callback cannot recover a missing validation error or its logical record number. [csveee skip][E-chunk], [medialab caveats][M-lib] |
| Multiline, doubled quotes, configured escape, final record without LF, UTF-8 split across buffers and invalid trailing sequences. | csveee has quote/escape state assumptions and text validation, but SIMD rejects an escape distinct from quote. medialab's zero-copy iterator exposes lexical bytes; unquoting alone is not unescaping or UTF-8 validation. Validate all bytes/fields, including unselected columns, and include copy/unescape costs. Exhaustive parity remains unproved. [csveee states][E-chunk], [SIMD gate][E-simd], [text validation][E-output], [record views][M-records] |
| Headers are validated records, not data IDs; duplicate names allowed but ambiguous selection rejected; headerless width inferred from first record; no type/null coercion. | csveee's header setting skips the header via boundary scanning; variadic mode accommodates runtime width but loses SIMD eligibility. medialab provides width/header handling, but a byte header is not validated text. Keep Chopper's header owner/name resolution and validate the complete first record. [csveee stream/header path][E-scheduler], [arity gate][E-simd], [medialab first-read/width][M-zero], [Chopper contract][C-spec] |
| `max_record_bytes` and error placement. | Chopper's parse counter includes consumed CSV syntax plus `32 * completed_fields`, checked incrementally; the LF consumed after CR has historical special accounting. It is neither decoded payload length nor raw physical-line length. Decoded-text packing has a separate payload-plus-field-overhead check. Upstream buffer caps are not equivalents. Preserve exact limit edges and logical record counting, including skipped blank records and headers; csveee errors expose byte offsets, not Chopper's record numbering. [Chopper checks][C-parser], [csveee errors][E-error] |

**Inference:** a serial prevalidator could guard a permissive fast parser, but must
validate the entire input, preserve error ordering and bind validation to the same
source bytes. The added read/scan and any retained snapshot belong in the complete
Run cost; “well-formed input” cannot silently become a new accepted-input contract.
A syntax-aware serial boundary scan is safer to reason about than splitting on
LF, but may consume the parsing work the experiment hopes to remove.

## Ordered effects and bounded ownership

Chopper hashes the ordered framed stream of field counts, byte lengths and exact
UTF-8 text. A hash of chunk hashes is a different digest. Ingestion also observes
summaries/preview before handing rows to initial operations; IDs start at zero
for data records. Probabilistic assignment depends on the original source ID and
parent/step domain; uniform shuffle additionally preserves its original domains
and collision refinement. [Digest][C-digest], [ingestion][C-engine],
[seed/resource specification][C-spec], [rewrite constraints][C-rewrites]

**Proposed ownership/order requirements (inference from these contracts):**

- Resolve the header and expected width first. Attach chunk byte ranges and local
  record/skip counts; establish checked global source ordinals from accepted
  prefix counts before ID-dependent computation. A speculative chunk's local row
  number is not a global source ID. Prefer deferring random-key work to accepted
  ordered batches over inventing an extra full-file counting pass.
- Keep digest, preview, summaries, stage observations, encounter-sensitive state
  and output-cap decisions in source order. Pure key construction may run in
  workers once identities/domains are fixed; this does not authorize changes to
  operation ordering, sorting, group allocation or execution dispatch.
- Bound raw buffers, boundary carry, active parser scratch, field/index metadata,
  reusable owned/compact storage, speculative alternatives, queued work and
  completed-but-undrained results together by bytes **and** counts. A stalled first
  chunk must stop later dispatch. File-size-proportional result arrays and
  all-file callback row vectors are unsuitable for larger-than-memory input.
- Admit capacity **before** allocation, including old/new growth overlap and
  retained wide-slot capacity; transfer grants with records and borrowed backing
  buffers through the last consumer. Neither upstream public builder exposes
  Chopper's per-growth reservation callback. A configured buffer size or worker
  count alone does not supply that ownership contract. [Chopper reserved APIs][C-parser],
  [csveee builder][E-builder], [medialab scratch growth][M-buffer]
- Poll cancellation during boundary scans, worker loops and ordered draining;
  stop and join workers before releasing buffers, grants or private output.
  Preserve the serial control's error precedence and logical placement rather
  than reporting whichever worker finishes first. Malformed
  input, cancellation and errors after direct consumption are terminal; they do
  not authorize reopening/replaying input. Preserve source checks and native
  atomic publication/cleanup. [Direct contract][C-contract], [direct Run][C-direct]

**Inference:** accounting must include enough headroom for existing sorting and
publication. Faster workers can reduce Run feasibility by retaining records that
shrink sort runs or force extra spills. Reservations remain working-allocation
accounting, not an RSS cap. Mmap does not resolve admission or mutable-source
identity problems. Compressed/transcoded sources and browser threading require
separate experiments; native file chunking supplies no such guarantee.
[Resource contract][C-spec], [current decoder][C-parser]

## Smallest useful experiment and falsifiers

This is a proposed decision procedure, not another backlog or an instruction to
run benchmarks in this research task. Follow the maintained [evidence rules][C-bench]
and retain the current plan, seed, features, resource settings and output mode.

1. **Qualify one ingestion seam before dependency choice.** Use plain native
   UTF-8 regular files and the current stronger strict serial implementation as
   control. A candidate must pass the table's byte-level probes at small refill
   sizes, chunk boundaries and limit edges; include late errors, narrow-then-wide
   records, many fields, admission denial, cancellation and cleanup. Test owned
   and compact targets separately. No timing result overrides a failed gate.
2. **Separate two hypotheses.** A small single-worker mask-reuse/search change
   tests whether remaining scans dominate beyond memchr and direct field spans.
   A bounded parallel candidate tests raw-chunk parsing into pre-admitted slots,
   with strict boundary validation and ordered commit. Initially avoid
   speculation; if boundary discovery costs erase benefit, that is a useful
   rejection, not permission to weaken validation. Add discardable speculation
   only if its strictness, ownership and identity gates can be demonstrated.
   A serial-parser/indexed-consumer batch is a distinct control when expensive
   pure key work is identified; it must not be labeled parallel parsing.
3. **Measure the two complete target Runs**, one ordered byte-capped export and
   one existing partition → probabilistic allocation → uniform-shuffle recipe,
   through usable native publication. Keep the seeded algorithm/version fixed.
   Compare one worker and one small existing multiworker setting, rather than a
   large matrix. Require exact output bytes/order, membership, names, lineage,
   digest and logical Analysis parity, plus independent field/ID/cap checks.
   Include header/BOM handling, decoding, boundary discovery/reparsing, copying,
   serialization, sync/publication and any extra sort/merge traffic in elapsed
   time. Component/profile timings are supporting diagnostics only.
4. **Falsify early.** Reject an unchanged candidate if any malformed input is
   accepted, error placement changes, order/seeded output differs, capacity grows
   with file length, cancellation leaves live workers/grants/output, or working
   headroom worsens completion. Reject its performance hypothesis if repeated
   matched complete Runs show no useful benefit beyond noise, including a
   representative quoted/Unicode or rare-wide case, or if extra passes/copies,
   serial commitment, storage contention or induced spills erase the gain.

**Remaining unknowns:** CPU attribution after PR72; strict parallel boundary cost
on Chopper's actual shapes; speculative retry frequency with text-only fixed-width
records; costs of admitted result storage and global-ID establishment; exact
malformed-header/BOM/error-precedence parity; and native Windows/Linux behavior
under shared pressure. No new upstream or Chopper execution was performed.
Private original benchmark logs were not hydrated, PR72 CI was not rechecked,
and no upstream headline speedup is transferred to Chopper.

[C-spec]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/docs/specification.md
[C-rewrites]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/docs/pipeline-rewrites.md
[C-contract]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/docs/direct-execution.md
[C-parser]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/crates/chopper-core/src/csv.rs
[C-engine]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/crates/chopper/src/engine.rs#L874
[C-direct]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/crates/chopper/src/engine/direct.rs
[C-header]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/crates/chopper/src/engine/header.rs
[C-storage]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/crates/chopper/src/storage.rs#L500
[C-profile]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/crates/chopper/src/profile/records.rs
[C-digest]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/crates/chopper/src/digest.rs
[C-lock]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/Cargo.lock#L693
[C-performance]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/docs/performance.md#strict-csv-serial-admitted-span-control-2026-11-05
[C-bench]: https://github.com/jsmatfess/chopper-private-archive/blob/a2ab151f341ec48691cc69c8bbc0d0bb994c5834/docs/benchmarks/README.md
[R-pool]: https://docs.rs/rayon/1.12.0/rayon/struct.ThreadPool.html#method.install
[R-indexed]: https://docs.rs/rayon/1.12.0/rayon/iter/trait.IndexedParallelIterator.html
[R-scope]: https://docs.rs/rayon/1.12.0/rayon/fn.scope.html
[R-bridge]: https://docs.rs/rayon/1.12.0/rayon/iter/trait.ParallelBridge.html
[paper]: https://db.in.tum.de/~ellmann/papers/csveee.pdf
[E-release]: https://docs.rs/crate/csveee/0.2.1/source/.cargo_vcs_info.json
[E-lib]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/lib.rs
[E-scheduler]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/scheduler/mod.rs
[E-merge]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/scheduler/merge.rs
[E-simd]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/parser/simd/mod.rs
[E-output]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/parser/output.rs
[E-table]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/parser/dfa/table.rs
[E-config]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/config.rs
[E-chunk]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/parser/chunk.rs
[E-error]: https://github.com/ackxolotl/csveee/blob/3f8a1acea17ea130fb8b4ac3de7cfa4e71cdd475/src/error.rs
[E-builder]: https://docs.rs/csveee/0.2.1/csveee/struct.ParserBuilder.html
[M-manifest]: https://github.com/medialab/simd-csv/blob/df2cceb3bfe0427efc63fa213392f8c5b2713b47/Cargo.toml
[M-lib]: https://github.com/medialab/simd-csv/blob/df2cceb3bfe0427efc63fa213392f8c5b2713b47/src/lib.rs
[M-records]: https://github.com/medialab/simd-csv/blob/df2cceb3bfe0427efc63fa213392f8c5b2713b47/src/records.rs
[M-zero]: https://github.com/medialab/simd-csv/blob/df2cceb3bfe0427efc63fa213392f8c5b2713b47/src/zero_copy_reader.rs
[M-buffer]: https://github.com/medialab/simd-csv/blob/df2cceb3bfe0427efc63fa213392f8c5b2713b47/src/buffer.rs
