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

**Browser session**:
A browser processing context that can retain input profiling and exact prepared
outputs across requests, until completion, cancellation or failure.

**Workload**:
An input dataset paired with a complete pipeline configuration. Machine resources
and other execution conditions describe a run of that workload.
