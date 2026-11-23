# Native scripted Job decoding ownership

[#151](history/prior-issues.md#issue-151), child of #86, covers only
native scripted `analyze` and `run` decode-origin payloads. The
[facade](../crates/chopper/src/cli_job.rs) preserves metadata lookup, the exact
`configuration exceeds 1 MiB` metadata rejection, File open, and direct typed
`serde_json::from_reader::<_, Job>` with `read job JSON` context. Metadata is not
an actual-read cap or immutable snapshot. There is no input buffer, Value tree,
preflight, seek, replay, regular-file requirement or identity check.

After open, the existing process ledger admits defaults before serde starts.
Imported local resources and CLI overrides are unknown at this point; neither
is resolved early. No pressure refresh or discovery/fallback/Auto formula changes.
The reader forwards one-byte reads, including unchanged source errors and
Interrupted behavior. Before returning a byte, it grows a checked monotone
allowance for all covered allocations that byte enables. A denied byte is
consumed from the source but withheld from serde. Inline sticky denial returns
`ErrorKind::Other` without a boxed carrier and prevents any further source reads.
The sticky state distinguishes shared denial from genuine injected I/O Other.
After serde unwinds, the explicit shared error gets the original JSON context.
Genuine admission failure may preempt later parse errors. EOF changes no counters
and invents no next-byte grant. Arithmetic overflow is terminal accounting failure.

The native [Validate command](validate-cli.md) uses the same owner and reader
with optional field-path tracking. Its decoder wraps the same serde_json
stream deserializer in pinned serde_path_to_error 0.1.20 and still requires
end of stream on success. Analyze and Run use the direct typed decoder.

Validate adds an allowance of `2Q` (twice the consumed byte count on fallback)
before delivering each byte. JSON map keys and enum tags reach `CaptureKey` as
strings. It copies the decoded text, and `TrackedSeed` can clone the current
chain node before visiting the value. Each active key or tag therefore needs
at most two copies bounded by its raw string interior. The finite parent links
and sequence indices are inline. The pinned adapter materializes a path vector
and clones its keys only on error. Those diagnostics are error carriers outside
the payload envelope. For successful decodes, the allocation census also
checks the tracked decoder's construction and release ordering.

## Construction envelope

All terms count requested allocation layouts, including old plus new during
reallocation. All arithmetic is checked. C is the versioned private serde Content
size, L is Column size, and U is max(Operation, Allocation, Column) size. These are
computed from actual types; compilation requires C, 2C, L and U in 2..=1024.

For n enabled slots of size s:

```text
G(0,s) = 0
G(n>0,s) = s * max(4,3*n)
P(H>0) = max(8, next_power_of_two(H))
S(0) = 0; S(H>0) = P(H) + P(H)/2
V(k,c) = max(min(k*U,1_048_576), G(k,L), G(c,U))
E = 28 + Q + S(H) + sum_arrays(G(k,C)+V(k,c)) + sum_objects G(k,2*C)
```

Q counts cumulative raw string interiors, including keys, escape backslashes and
hex bytes, excluding unescaped boundary quotes. H is the largest complete or
partial raw string interior. Arrays/objects start with k=1 at their opener and
increment at each direct comma; this includes a pending element/pair before its
decode or push. Array c counts direct container element openers before delivery.
Closed container charges remain in the cumulative sums. Accounting never uses
field names, tags, decoded lengths, validation limits or semantic validity.

The 28 bytes cover Job's two CsvSettings defaults and two independently supplied
CsvSettings defaults, each allocating exactly `utf-8` (5) and `lf` (2). Other
defaults are empty/None/inline. Q covers unique owned text origins: IoRead scratch
copies once into Content or directly typed strings; owning Content then moves
strings into typed fields and scalar Columns. Scratch is charged separately.

IoRead scratch starts at eight bytes and doubles; Unicode reserve(4) follows at
least six raw escape bytes, so its required capacity is already bounded by H.
The largest capacity is at most P(H), and old/new overlap at most S(H).

For Vec growth at push t, old capacity <=t-1 and new capacity is
max(2*old,t,4). G covers old/new overlap, arbitrary non-power-of-two cautious
initial hints, retained storage and minimum four-slot allocations. Content's
in-progress key/value/child heaps have separate text/container origins, so need
no duplicate descriptor charge. One physical array has at most one Content Vec
and one typed Vec. Owning Content IntoIter retains its source allocation while
the destination grows. Column can push scalar elements, bounded by G(k,L).
Operation/Allocation can push only container elements, bounded by G(c,U), but
their eager cautious hint may allocate before rejecting even the first scalar:
min(k*U,1 MiB) remains necessary. These are alternative typed-vector phases,
hence max. Struct and internally tagged sequence representations are covered.
Closing punctuation can enable all conversion/default completion without another
read; cumulative counts and initial defaults already cover it.

Accounting uses 128 inline frames. Overflow or mismatched closure switches
permanently to a conservative structural fallback, preserving the previous maximum.
Let p be all raw bytes and A, M, K count every raw `[`, `{`, `,`, including those
inside strings:

```text
E_fallback = 28 + p + S(p)
           + (C+U)*(4*A+3*K) + (2*C)*(4*M+3*K)
```

Each real container has max(4,3*k) <=4+3*(k-1); all real direct commas/openers
are included in the raw totals. Q and H are <=p. This proves fallback dominance
without trusting lexical state. Malformed Unicode can confuse quote state only
during invalid hex consumption immediately before serde's own error; it cannot
enable a later covered allocation. The accountant emits no lexical errors.

## Audit gates and limits

The proof depends on serde/core/derive **1.0.229**, serde_json **1.0.151**, JSON
std with **arbitrary_precision and float_roundtrip disabled**, default recursion
limits, the exhaustive current Job schema and audited std growth/copy behavior.
Dependency or feature changes require re-audit; Cargo.lock alone is insufficient.
For each delivery build, inspect effective target features (use the actual target,
avoiding resolution of unfetched unrelated platform dependencies):

```sh
cargo tree --locked --offline --target x86_64-unknown-linux-gnu -p chopper -e features -i serde_json
```

The versioned private Content reference deliberately breaks on a serde update.
The focused tests print actual Content/Column/Operation/Allocation sizes and
observe System requested layouts and growth against the already-held grant.
The audit read the pinned IoRead/escape/Content/derive/size_hint paths and Rust
1.99.1 (`58cf8f9c35b355199727627d07ae34a4e2846d67`) raw_vec, Vec, String,
slice copies, I/O Bytes and ErrorKind sources. Parent-retained proof source pins
cover 42 files; all matched before implementation. Native Windows layouts,
sysroot behavior and actual qualification require separate parent validation.
These are build/workload-scoped claims, not acceptance of arbitrary toolchains.

The focused Linux build on that compiler observed C=32, L=24, Operation=56,
Allocation=48 and U=56 bytes. Its effective JSON features were `default,std`.
Requested-layout probes check each successful covered allocation/reallocation
against the already-held grant, exact retained capacity, and zero live covered
bytes before grant release. Separate controls exercise actual Content/typed
overlap, defaults, pending values, scratch and non-power-of-two Vec growth,
cautious hints at the 1 MiB ceiling, and engine-owned entropy construction after configuration admission.
Removing the corresponding allowance in these isolated controls underbounds the
observed requests. Error fixtures compare legacy values/errors/positions and
source read traces; they do not claim that error objects fit the payload grant.
Denial probes stop recording new allocations at the withheld byte and continue
tracking prior payloads through unwinding and source-grant release, excluding
later error carriers explicitly. The tracked controls check the lexical and
fallback allowance boundaries at the reader, then check partial payload teardown
with the tracked decoder on the lexical path. The independent event oracle recomputes prefix
allowances from generated lexical events rather than scanning with a second copy
of the production lexer. Decline is modeled by dropping the prompt-owned source;
terminal interaction and actual native Windows qualification remain separate.

The refined bound is intentionally conservative. It does not promise that every
metadata-sized Job fits an otherwise unused 128 MiB fallback. Invalid scalar
groups still pay eager typed hint allocation. Sequence forms and discarded
objects/defaults are overcharged. Allocation peaks, ledger reservations and RSS
are different quantities; no performance, scale or RSS claim follows.

## Retention and later calls

After from_reader destroys scratch/Content, the existing exhaustive Job capacity
walker must fit E; only then shrink to actual retained String/Vec capacity.
DecodedJob declares Job before its grant. Immutable borrowing, scalar resource
overrides and consuming Run/Analyze methods retain source capacity through
prompts, profiling and the whole engine call. PreparedJob independently admits its
configuration; intentional overlap can deny work or reduce Auto's observed free
headroom. No early release, bare extraction, Clone, general mutation or generic
reservation export exists. Ordinary engine/core APIs remain unchanged.

CLI decoding does not construct or retain a user seed. The Job schema rejects
`seed`; the engine's retained-configuration owner admits internal entropy before
execution. The existing 64-byte generated-entropy construction remains covered
by the prepared-configuration resource contracts.

Error objects, validation/formatting internals, allocator bookkeeping/usable size,
RSS, stacks, source File/OS paths/handles, ledger/bootstrap control owners,
prompts/framing and unrelated caller construction remain outside this envelope.
Guide/split/flag-built Run caller-owned construction, HTTP and WASI retain their existing accounting boundaries. #86,
#81/#94, frozen release and platform acceptance remain separate.
