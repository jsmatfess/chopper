# Pipeline rewrite eligibility

Current contract (2026-11-15): seeded-output policy is removed. Rewrites must
preserve requested pipeline semantics, exact allocation/group membership, full
shuffle distributions and strict serialized caps; they need not preserve a
particular seeded realization. Public seed input is removed; execution generates
internal entropy and internal snapshot execution preserves retained output bytes.

Calculated columns are bound to the validated source schema. The retained
snapshot plan evaluates them before the first consuming operation, or during
final output preparation when only export uses them. Rewrites must preserve
that boundary and any row-level evaluation failures. Spills preserve types
and timestamp offsets. Partition keys compare the rendered text.

A hosted Run or an unobserved Linux Run can feed calculated rows directly
into a single Partition that uses a calculated field. Eligibility requires
plain output, one root group, and a source file of at least 128 MiB. Auto grouping
keeps its existing choice between routing and sorting. Builds with experimental
constant Partition use their staged route.

The fused pass supplies the existing sorter with the same rendered tuple,
ordinal, and packed fields. Its final writer constructs the same capped output
snapshot. Hosted Run admits that writer before evaluating the rows and reports
calculation as the grouping or sort input when observations are enabled. A
failed attempt drops its private output and spills before replaying the staged
route from the retained input. Replay preserves error order when a resource or
Partition failure occurs before a later formula error. Cancellation and failed
cleanup stop before replay. The calculation traversal timer includes collecting
and finishing the sort when this route succeeds.

Ordinary builds now fuse adjacent `auto/uniform -> partition(columns)` into one
sort on partition tuples and random keys, avoiding the global shuffle
materialization. Explicit Fisher–Yates remains excluded from this physical sort.
The blanket partition-first/independent-child-shuffle candidate was evaluated and
withheld because skewed and single-group cases regressed. A resident Auto
selector was also withheld after fitting/external complete-job regressions.

The table below retains the construction properties and historical experiment
labels. “Exact v1 output” describes those algorithms, not a current user policy.
The shuffle/partition implementation is enabled by default. The alternate runner and its allocation-range feature remain removed; ordinary execution now also supports the adjacent exact-range construction below. Other experiment gates are unchanged. Limits-only Run retains direct private publication;
errors after input consumption never trigger raw-input replay.

| Requested sequence / proposed physical plan | Equivalence | Status and required constraints |
| --- | --- | --- |
| `uniform -> uniform`: retain only the last random-key sort | Exact v1 output | Implemented. Keys depend on stable source row IDs and the last shuffle's original operation index/parent domain. Retain both logical stages; no intervening operation may change parents or membership. |
| `auto/uniform -> fisher_yates`: retain the final resident shuffle | Equivalent full-permutation law under independent ideal randomness | Implemented for leading prefixes and visible retained pairs. Keep the final original index/domain and resident-only failure; never elide an earlier explicit Fisher–Yates. Upstream grouping/shuffle fusion retains its existing priority. |
| `partition -> uniform`: sort tuple plus child random key/domain | Exact v1 output | Implemented, including ingestion. Derive each child domain from its original partition lineage and shuffle index; preserve collision refinement. |
| `uniform -> balanced`: sort once, emit exact contiguous ranges | Exact v1 output | Implemented. Preserve remainder rounding, original parent lineage and insufficient-row failure. This fuses traversal; it does not exchange the operations. |
| `fisher_yates -> balanced`: traverse the realized resident permutation once | Exact realized output | Implemented for root and retained parents. Preserve resident-only failure, parent quotas/remainders, original indices, lineage and downstream order. Avoid the intermediate Dataset; never move Balanced across the shuffle. |
| `partition -> balanced`: count each key, then emit exact per-key ranges | Exact membership, lineage and encounter order | Opt-in native `experimental-counted-partition-balanced` for unobserved Auto Run with plain UTF-8 input, plain output and a finite writer ceiling. Two validated passes and the existing counted-source proof precede publication. |
| `partition -> uniform -> balanced`: sort once and emit each tuple's exact child ranges | Exact v1 output | Opt-in `experimental-partition-balanced`. A charged bounded tuple counter supplies parent sizes; preserve original last-uniform index, collision domain and per-tuple remainder rounding. High fanout/counter denial uses original materialization; typed admission failures discard tentative output and retry. [Evidence](performance.md#partition-shuffle-balanced-fusion-2026-10-18). |
| Count-independent membership `-> partition ->` count-independent membership | Exact v1 output | Opt-in `experimental-streaming-chain`. Either endpoint may be probabilistic allocation or interleaving. Retain original scope/operation domains, source IDs, independent per-tuple encounter counters, named empty allocations and all logical stages. Bounded catalog/composite-key denial replays the original graph; exact quotas and intervening operations are excluded. [Evidence](performance.md#streaming-membership-partition-chains-2026-10-18). |
| `uniform -> partition`: sort tuple plus original parent random key/domain | Exact v1 output | Enabled by default; the former feature retains additional audit instrumentation. Keep the original shuffle domain, source IDs and collision refinement; append partition lineage at its original index. Preserve canonical tuple order and the shuffled subsequence inside each tuple. |
| `full shuffle -> partition`: partition first, derive fresh independent child shuffles | Equivalent distribution under the ideal independent-permutation model; different seeded output | Removed prototype (`experimental-flexible-partition`, invalid Cargo feature). The historical distribution argument is retained below; the new blanket rewrite was measured and withheld. |
| `full shuffle -> unstratified exact allocation`: cut one parent permutation at largest-remainder quotas | Equivalent joint membership/within-allocation order under ideal independent randomness; different seeded output | Implemented in ordinary execution for leading and visible retained pairs, using the requested shuffle producer. Preserve configured order/named zeros, original indices/stages, lineage, caps and parent isolation. Decline strata and an immediately following auto/uniform suffix to preserve existing assignment/shuffle fusion. [Historical proof](allocation-ranges-experiment.md); its removed policy/feature descriptions are not current options. |
| `Fisher-Yates -> partition`: replace with tuple/random-key sorting | Different pinned algorithm and seeded output | Excluded from the exact-v1 prototype. A separately recorded flexible-policy plan requires the appropriate distribution argument and acceptance checks. |
| Move a row-count, balanced, interleaved or byte-cap split across a shuffle | Generally changes membership/chunk boundaries | Prohibited by the current rules. Shuffling children cannot repair membership selected before the shuffle. Exact-output fusion must still apply the original split to the same realized order. |
| Move shuffle across exact/probabilistic or stratified assignment | Requires a separate joint-distribution/encounter-order proof | Excluded from the reverse-partition prototype. Existing assignment-then-shuffle fusion retains original assignment membership, quotas, draw sequence and child domains; it is not an exchange of the operations. |
| One-chunk final writers: flush all before synchronizing original Files | Identical bytes and native commit requirements | Opt-in Linux `experimental-batched-final-sync`, unobserved plain typed catalogs only. Admit root handle queue before transfer; sync every original handle before Analysis/manifest/commit, preserve original stage/witness and terminal cleanup. No reopen, fewer-sync shortcut or other-platform/codec/multichunk eligibility. |
| Bounded final writer with one proved chunk: retain typed metadata until canonical merge | Identical output and original publication witness | Opt-in native `experimental-single-final-catalog`; exact Group or absence of every chunk cap proves one record. Preserve serialized metadata byte limits; materialize the canonical root catalog in its original stage. Other constructors and multi-chunk groups retain disk catalogs. No writer ceiling change or Analyze dependency. |
| Singleton retained stratified exact assignment: count strata, then interleave original quota streams into bounded final writers | Exact internal-entropy membership and output | Opt-in native `experimental-retained-exact-writers`, plain UTF-8 output and Auto grouping with configured allocation count within the writer ceiling. Preserve each stratum's original parent/step/domain, largest-remainder quotas and encounter subsequence; configured names/zeros, global output order and caps remain exact. Preparation denial retries the same immutable parent through the original writer; cancellation/cleanup faults and every emission error are terminal. No CSV retry or observed/WASI/composed eligibility. Experimental qualification is separate from this eligibility contract. |
| `balanced(r) -> balanced(s)`: scan original nested ranges together | Exact output | Default for an eligible two-operation hosted Run. The guarded path decodes the retained rows once and emits the original nested ranges into a snapshot. The `experimental-nested-balanced` feature also covers deeper and intermediate chains. Each parent uses its original remainder rounding, lineage and stage counts. Flattening to `balanced(r*s)` can change boundaries. [Eligibility](execution-decisions.md#hosted-consecutive-balanced) · [Prototype evidence](performance.md#nested-balanced-range-fusion-2026-10-17) |
| Redundant value partitions: group only on newly varying columns | Exact output | Opt-in `experimental-constant-partition`. Earlier requested value partitions prove constants through subsequent selection/reordering. Share intermediate files or copy terminal rows when all keys are constant; otherwise sort varying keys with full tuple lineage/domains. [Evidence](performance.md#proven-constant-partition-keys-2026-10-17). |
| Consecutive value partitions on different columns: group once by nested tuples | Exact output | Opt-in `experimental-consecutive-partitions`. Retain selected-column order/duplicates and every logical lineage/stage; preserve encounter order and original downstream domains. Typed admission denial discards tentative output before CSV/dataset replay. Native cases improve, but large browser merging regresses. [Evidence](performance.md#consecutive-value-partition-fusion-2026-10-17). |

The distribution statement is a mathematical model, not a new generator-quality
or finite-seed-space guarantee. Its derivation and restrictions are in
[randomization/planning research](maintainer/research/randomization-planning-research.md). Flexible
rewrites require their own eligibility and evidence; the ordinary exact-range and mixed-elision rules above are enabled without a policy selector. Buffered XOF and independent random
buckets have been removed; historical experiment records do not enable them.

## Current executable eligibility

`engine::shuffle_partition::Plan::at` recognizes only an adjacent random-key
`uniform`/`auto` shuffle followed by value partitioning. It does not search across
another operation or substitute Fisher-Yates strategies. After existing
consecutive-uniform elimination, the selector retains the last shuffle's original
index. The physical implementation uses the existing `GroupRandom` comparator:
partition tuple, the original 16-byte random key and its 32-byte collision domain.
The domain comes from the original parent, rather than a newly partitioned child.

The leading ingestion path and later dataset path use the same selector/domain
choice. The retained-dataset path uses `engine::exact_plan::Proposal` to separate
original plan/parent identity, admitted column ownership and tentative sorting
from output emission. The same seam now serves retained streaming-chain parents:
preparation owns tentative resources, and cancellation or failed cleanup overrides
a retryable denial after those owners drop. Typed memory
admission denial before emission drops tentative owners and retries that parent
through the original shuffle and partition stages; previously emitted parents
are retained once. Diagnostics count `shuffle_partition_retries`. Cancellation,
other preparation errors and every emission error remain terminal. Raw ingestion
keeps its existing behavior because it has no retained replay boundary. This is
not a calibrated cost selector; the fused path is enabled by default.

Retained streaming chains retry only the denied, un-emitted parent through its
original three stages. Earlier emitted parents remain once, and logical statistics
commit once. Bounded counter denial is typed separately from local/shared memory
denial. Every error after the emission call begins, including final sorting,
metadata construction and sink finalization, is terminal. Writer-setup denial
before any parent attempt retains the existing original-stage fallback. Raw CSV
ingestion retains its separate existing retry behavior; it does not use this
retained-parent seam. See [shared-seam acceptance](validation.md#shared-exact-plan-retained-parent-seam-2026-10-28).
Temporary-file unlink failures now retain orphan charges and a reported path;
shared execution checks prevent a cleanup failure from becoming a successful
original-stage retry. Shared Windows/Linux/WASI contracts now cover actual
pathname unlink failure at this retry boundary; browser destination export and
OPFS deletion faults remain separate acceptance gaps. See the
[retained-parent contract evidence](performance.md#wasi-retained-parent-retry-acceptance-2026-10-21).
Resolved-column arrays and operation keys reserve capacity before
allocation. Sort/spill/merge reservations and bounded fallbacks retain their
existing limits; the prototype does not introduce flexible resource-dependent
algorithm selection. Physical row ordinals may be normalized monotonically
inside a resulting parent. Current consumers use their relative order; random
streams use source IDs and logical lineage. Tests compare downstream exact and
probabilistic assignment, partitioning, balanced/interleaved splits and shuffling
against the original two-stage execution.

Behind the same experiment gate, a lazy charged audit retains at most the first
16 completed retained-parent attempts, with partial shape observations, typed
denial phase and commit/terminal outcome. Omitted records and collection denial
are explicit; successful collection consumes working headroom. This observes the
existing gate rather than selecting a calibrated plan. The
[audit evidence](performance.md#bounded-retained-parent-decision-audit-2026-10-21)
defines coverage and counter limits.

The selector tests cover adjacency, explicit strategies, positional/assignment
barriers and original indices after repeated uniform shuffles. Execution tests
force equal primary keys through resident and hierarchical external sorts,
compare multiple parents and downstream operations, preserve empty-input stage
summaries, and check reservation rollback, cancellation, malformed input and
disk-denial cleanup. This audits the exact rules; the flexible baseline now has
resolved-plan/admission/replay tests below. Distribution-rewrite selection and
acceptance remain open.

## Adjacent exact ranges and mixed-method elision

`engine::shuffle_assignment::Plan::at` selects only an immediately adjacent full
shuffle and exact assignment with empty strata. It accepts auto, uniform and
explicit Fisher–Yates while preserving the latter's resident-only failure.
Existing upstream grouping/shuffle fusions keep their priority; a following
auto/uniform after assignment declines this pair. No grouping, positional split,
allocation or cap crosses the selected span.

For quotas q_i on N distinguishable IDs, let M=N!/product(q_i!). Ordinary
independent quota membership and a uniform parent permutation give any tuple of
ordered named-child lists probability M/(N!*M)=1/N!. Cutting one uniform
permutation bijects its N! outcomes to the same tuples, each with probability
1/N!. This is the joint output law, not conditional independence from an exposed
physical intermediate order or a finite-seed-space certificate. Zero quotas
remain named children; stratified quotas need a different proof.

The existing producer supplies that parent's complete permutation, then the range
sink retains admitted AssignmentScratch and one ClonedGroup at a time. Retained
parents admit scratch before permutation construction; ingestion learns N at EOF
and admits scratch while the result remains owned. Lineage, decoding and output
serialization still require their own overlapping grants. Every new error is
terminal; this path adds no retry, and never replays consumed raw input.
Original shuffle and assignment statistics commit once. Producer observations map
both original operations; ExactMembership records actual range traversal and
counts without inventing assignment RNG draws or a second sort.

`engine::shuffle_elision` keeps the random-key capability predicate unchanged.
Only earlier auto/uniform operations may be elided before an adjacent supported
shuffle, including a final Fisher–Yates. An independent ideal final uniform
permutation maps every fixed prior ordering to each result with probability
1/N!, so eliminating that earlier ordering preserves the full law. Earlier
explicit resident requests still execute and can fail. Leading mixed prefixes
retain actual parser-row capacity instead of shrinking without a replacement
grant; the parser/source and final resident owner overlap. This can change fit
relative to the old materialized path, without changing the configured budget.
Elided facts have zero row work and no data source; final work keeps its original
index, actual algorithm and Read/Dataset source. Grouping/assignment suffix
fusions are deliberately unchanged.

The ingestion-adaptive and random-quota balanced pilot implementations are not
retained. Their measured decisions and limitations belong to the
[swarm investigation](performance/investigations/shuffle-swarm-decisions-2026-11-15.md).
No new size threshold, resident Auto selector or alternate runner is enabled.

### Prepared-spill probabilistic shuffle

Auto recognizes plain Partition → probabilistic assignment → Uniform or Auto
shuffle under the [runtime gates](execution-decisions.md#3-current-auto-planning).
The Linux build opt-in can also request the same fusion directly. It replaces the intermediate
allocation Dataset and individual child sorts with a grouped sort per retained
partition parent. The key contains the configured allocation index and the
original child's Uniform key and collision domain. Membership uses the original
assignment index and stratification. The sink receives named children in the
original order, including empty allocations.

Preparation owns a real buffered spill file before accumulation. Typed memory
denial drops its tentative owners before the retained-parent proposal tries the
original allocation and shuffle. Cancellation and cleanup failure win at that
boundary. After entering emission, every error is terminal. Original stage
statistics commit once and physical facts map the operations that actually ran.
[Linux complete-job and pressure evidence](performance/investigations/probabilistic-shuffle-fusion-at-2-gib-2026-11-21.md)

## Retained result ownership

The [retained-execution module](../crates/chopper/src/engine/retained_execution.rs)
shares output ownership for the existing consecutive-partition, streaming-chain
and partition/shuffle/balanced paths. It chooses the intermediate DatasetWriter
or terminal PlanWriter, preserves owned/packed RowSink adapters and finalizes
exactly one result. Successful commitment appends the existing bounded statistics,
replaces the appropriate result and advances the original operation cursor once.
Declined or failed attempts drop tentative writers/results without committing.
There is no new common statistics allocation or feature/default change.

Setup and execution/finalization failures remain distinguishable. Streaming's
outer fallback still accepts only writer-setup denial; its per-parent retry stays
in exact_plan::Proposal. Consecutive partitions retain their existing whole-attempt
typed-memory fallback, and partition/balanced retains both bounded-count decline
and typed-admission fallback. These are separate policies, not one retry rule.
Raw ingestion, direct publication, ordinary operation dispatch and nested-balanced
shared ranges keep their existing paths. The separate native/WASI test reactor
checks writer lifetime, failure phases and commitment when these optional paths
are enabled; test entry points remain absent from production engines.

## Removed alternate policy runner

`experimental-flexible` and `experimental-flexible-allocation`, their alternate
runner, execution-plan stream and public Job policy selector are removed. There
is one production execution path. Earlier measurements of those builds are
historical evidence, not currently available execution options.

## Adjacent flexible partition-first prototype

Historical description of the removed prototype, preserved to interpret dated
evidence. Its feature, selector, domain and dedicated tests no longer exist.
Current flexible `auto -> partition` executes ordinary ordered stages; no public
runtime partition-first selector existed. Exact shuffle/partition fusion is a
separate surviving seeded-v1 implementation.

The historical `experimental-flexible-partition` feature enabled only an adjacent
`auto full shuffle -> partition(columns)` pair under the historical `flexible_v1` policy. Explicit
uniform/Fisher–Yates requests, intervening operations, positional splits
and assignments are excluded from this selector. Existing parents remain
independent. The requested operations remain in their original order in the job
and logical analysis; the execution audit records physical partitioning before
child shuffles, original indices, logical parent lineage, physical child lineage
and the versioned domain recipe. Complete-job WSL/native and browser OPFS measurements are recorded; mixed
results retain opt-in status. Broader statistical/algorithm acceptance remains
open. See [measurements](performance.md#flexible-partition-first-shuffle-experiment-2026-10-18).

For one existing parent with N distinct source IDs and tuple counts n1…nk, there
are N! equally likely ideal input permutations. Fix one order within every tuple.
Exactly N!/(n1!…nk!) interleavings induce those orders after stable partitioning.
Consequently each tuple-order combination has probability 1/(n1!…nk!), equal to
independent uniform child permutations. Canonical tuple output order removes the
irrelevant global interleaving. Apply the same argument independently within each
existing parent. The finite test enumerates all 120 permutations of five IDs in
three tuples and checks the four child-order combinations each occur 30 times;
independent child enumeration gives those same four combinations. This is a
combinatorial identity under ideal independent randomness, not a PRNG quality
certificate or seeded-output equivalence.

The prototype first executes ordinary bounded value grouping at the partition's
original logical index. It derives each full-shuffle domain from the original
shuffle index and full partition-child lineage, then applies the separate BLAKE3
derivation context `chopper.flexible.partition-first.v1`. This creates a distinct
versioned family of per-child streams. The existing actual-capacity admission and
external random-key fallback remain available for each physical child. Audit
records label `independent-partition-child-v1` and distinguish the original
logical parent from the physical child. The planner version is 2 when this
experimental planner is compiled; the baseline flexible planner remains version
1. No new distribution identity is assumed for exact allocations, stratification,
row-count/byte-cap splits or interleaving.

## Historical unstratified allocation ranges

The former allocation-range experiment has been removed with the alternate
runner. Its distribution proof remains in [the experiment record](allocation-ranges-experiment.md);
it is not promoted by the seeded-policy removal. Reintroducing it requires a new
bounded implementation and complete-job comparison against the current baseline.
