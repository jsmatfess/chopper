# Chopper

Chopper divides CSV data into outputs according to an ordered pipeline.

## Language

**Job**:
A request to process an input using an ordered pipeline, CSV settings, an output
destination and resource limits. It can be analyzed, prepared or run.

**Prepared job**:
A job with an immutable snapshot of its exact CSV outputs, retained for later
confirmation and publication.

**CSV intake**:
The reading of decoded CSV records and discovery of their header and column
count for profiling, input inspection or a job's pipeline.

**Calculated column**:
A column introduced at a position in the ordered pipeline, with each value
defined by a deterministic expression over that row. The expression can
reference input columns and calculated columns available at that position.

**NULL**:
An absent expression value, distinct from empty text within a formula. `NULL`
is represented as an empty field in CSV output and groups with empty text when
partitioning by a calculated column.

**Timestamp**:
An expression value that identifies an instant in UTC and retains the input
offset for calculations in the value's local time.

**Browser session**:
A browser processing context that can retain input profiling and exact prepared
outputs across requests, until completion, cancellation or failure.

**Workload**:
An input dataset paired with a complete pipeline configuration. Machine resources
and other execution conditions describe a run of that workload.
