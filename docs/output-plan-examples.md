# Output plan examples

Reviewed 43 representative scenarios and generated 9,372 plans: all 781 step combinations through four steps, across four output formats and three limit configurations. The UI tests check ordering, row preservation, fixed counts, and compression across this matrix. Regenerate with `cd ui && npm run simulate:plan`. These descriptions use configuration only; they do not predict data-dependent file counts.

## One plain CSV

Pipeline: no steps. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Write the input to one CSV, keeping rows in their original order.

## Row chunks

Pipeline: no steps. Limits: rows=100000, bytes=none, compressed=none. Compression: none.

Split the input into CSV files, keeping rows in their original order.

Each CSV contains at most 100,000 data rows.

## Byte chunks in one ZIP

Pipeline: no steps. Limits: rows=none, bytes=64MiB, compressed=none. Compression: zip.

Split the input into CSV files, keeping rows in their original order.

Each CSV contains at most 64 MiB of uncompressed CSV data. The byte limit includes any header and byte-order mark. Package all CSVs and the manifest together in one ZIP archive.

## Full shuffle

Pipeline: shuffle (auto). Limits: rows=none, bytes=none, compressed=none. Compression: none.

Shuffle the input rows into a random order, then write them to one CSV.

## Fisher-Yates shuffle into chunks

Pipeline: shuffle (fisher_yates). Limits: rows=1000, bytes=none, compressed=none. Compression: none.

Shuffle the input rows into a random order, then split them into CSV files.

Fisher–Yates v1 keeps uniform randomness but changes the seeded order from the default shuffle. Each group must fit in memory or the job fails.

Each CSV contains at most 1,000 data rows.

## One partition column

Pipeline: partition. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for each distinct value of “country”.

Rows keep their original order within each output.

## Two partition columns

Pipeline: partition. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for each unique combination of “country” and “segment”.

Rows keep their original order within each output.

## Three partition columns

Pipeline: partition. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for each unique combination of “country”, “segment”, and “channel”.

Rows keep their original order within each output.

## Numeric column references

Pipeline: partition. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for each unique combination of column #0 and column #2.

Rows keep their original order within each output. Column numbers start at 0.

## Treatment and control

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for “treatment” with 80% of the rows and a CSV for “control” with 20%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Three allocations

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for “A” with 50% of the rows, a CSV for “B” with 30%, and a CSV for “C” with 20%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Allocation names with punctuation

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for “control, holdout=1” with 80% of the rows and a CSV for “test <new>” with 20%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Single allocation

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for “all” containing all rows.

Rows keep their original order within each output.

## Zero-percent allocation

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for “all” containing all rows and an empty CSV for “empty”.

Rows keep their original order within each output.

## Empty allocation listed first

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create an empty CSV for “empty”, a CSV for “treatment” with 80% of the rows, and a CSV for “control” with 20%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Country strata pooled into allocation files

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Create a CSV for “treatment” with 80% of the rows and a CSV for “control” with 20%, choosing rows randomly. Apply those percentages separately for each distinct value of “country”, pooling the results into the corresponding “treatment” and “control” outputs.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Partition then allocation

Pipeline: partition → assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

For each unique combination of “country” and “segment”, create a CSV for “treatment” with 80% of the matching rows and a CSV for “control” with 20%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Allocation then partition

Pipeline: assign → partition. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Randomly assign 80% of the rows to “treatment” and 20% to “control”. Create a CSV for each unique combination of “country” and “segment” within each allocation.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Redundant strata

Pipeline: partition → assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

For each unique combination of “country” and “segment”, create a CSV for “treatment” with 80% of the matching rows and a CSV for “control” with 20%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Additional strata

Pipeline: partition → assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

For each distinct value of “country”, create a CSV for “treatment” with 80% of the matching rows and a CSV for “control” with 20%, choosing rows randomly. Apply those percentages separately for each distinct value of “segment”, pooling the results into the corresponding “treatment” and “control” outputs.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Partition, allocation, shuffle, balanced parts

Pipeline: partition → assign → shuffle (auto) → balanced. Limits: rows=none, bytes=none, compressed=none. Compression: none.

For each unique combination of “country” and “segment”, randomly assign 80% of the rows to “treatment” and 20% to “control”. Shuffle the rows in each allocation into a random order, then split each allocation as evenly as possible into 3 CSVs.

Allocations are rounded to whole rows. Each split produces nonempty parts whose row counts differ by at most one.

## Stratified allocation, shuffle, limits and ZIP

Pipeline: assign → shuffle (auto). Limits: rows=100000, bytes=64MiB, compressed=10MB. Compression: zip.

Create a set of CSV files for “treatment” with 80% of the rows and a set of CSV files for “control” with 20%, choosing rows randomly. Apply those percentages separately for each unique combination of “country” and “segment”, pooling the results into the corresponding “treatment” and “control” outputs. Shuffle the rows in each allocation into a random order before writing.

Allocations are rounded to whole rows.

Each CSV contains at most 100,000 data rows and 64 MiB of uncompressed CSV data. The byte limit includes any header and byte-order mark. Aim for 10 MB per compressed CSV inside the ZIP; this is an approximate target and may be exceeded. Package all CSVs and the manifest together in one ZIP archive.

## Shuffle before balanced splitting

Pipeline: shuffle (auto) → balanced. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Shuffle the input rows into a random order, then split them as evenly as possible into 3 CSVs.

Each split produces nonempty parts whose row counts differ by at most one.

## Shuffle after balanced splitting

Pipeline: balanced → shuffle (auto). Limits: rows=none, bytes=none, compressed=none. Compression: none.

Split the input as evenly as possible into 3 CSVs. Shuffle the rows in each CSV into a random order before writing.

Each split produces nonempty parts whose row counts differ by at most one.

## Partition then balanced splitting

Pipeline: partition → balanced. Limits: rows=none, bytes=none, compressed=none. Compression: none.

For each unique combination of “country” and “segment”, split the matching rows as evenly as possible into 3 CSVs.

Rows keep their original order within each output. Each split produces nonempty parts whose row counts differ by at most one.

## Balanced splitting then partition

Pipeline: balanced → partition. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Split the input as evenly as possible into 3 parts. Create a CSV for each unique combination of “country” and “segment” within each part.

Rows keep their original order within each output. Each split produces nonempty parts whose row counts differ by at most one.

## Balanced splitting then allocation

Pipeline: balanced → assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Split the input as evenly as possible into 3 parts. Within each part, create a CSV for “treatment” with 80% of the rows and a CSV for “control” with 20%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows. Each split produces nonempty parts whose row counts differ by at most one.

## Allocation then balanced splitting

Pipeline: assign → balanced. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Randomly assign 80% of the rows to “treatment” and 20% to “control”. Split each allocation as evenly as possible into 3 CSVs.

Rows keep their original order within each output. Allocations are rounded to whole rows. Each split produces nonempty parts whose row counts differ by at most one.

## Fixed balanced files with hard limits

Pipeline: balanced → shuffle (auto). Limits: rows=10000, bytes=64MiB, compressed=none. Compression: none.

Split the input as evenly as possible into 3 CSVs. Shuffle the rows in each CSV into a random order before writing.

Each split produces nonempty parts whose row counts differ by at most one.

Each CSV contains at most 10,000 data rows and 64 MiB of uncompressed CSV data. The byte limit includes any header and byte-order mark. The file count stays fixed; analysis will reject the plan if a part cannot fit within those limits.

## Balanced splitting followed by subdividable partitions

Pipeline: balanced → partition. Limits: rows=1000, bytes=none, compressed=none. Compression: none.

Split the input as evenly as possible into 3 parts. Create CSV files for each unique combination of “country” and “segment” within each part.

Rows keep their original order within each output. Each split produces nonempty parts whose row counts differ by at most one.

Each CSV contains at most 1,000 data rows.

## Balanced splitting followed by subdividable allocations

Pipeline: balanced → assign. Limits: rows=1000, bytes=none, compressed=none. Compression: none.

Split the input as evenly as possible into 3 parts. Within each part, create a set of CSV files for “treatment” with 80% of the rows and a set of CSV files for “control” with 20%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows. Each split produces nonempty parts whose row counts differ by at most one.

Each CSV contains at most 1,000 data rows.

## Repeated partitions

Pipeline: partition → partition. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Group the input rows by “country” and “segment”. Create a CSV for each distinct value of “channel” within each group.

Rows keep their original order within each output.

## Repeated allocations

Pipeline: assign → assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Randomly assign 80% of the rows to “treatment” and 20% to “control”. Within each allocation, create a CSV for “A” with 50% of the rows and a CSV for “B” with 50%, choosing rows randomly.

Rows keep their original order within each output. Allocations are rounded to whole rows.

## Repeated balanced splits

Pipeline: balanced → balanced. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Split the input as evenly as possible into 3 parts. Split each part as evenly as possible into 2 CSVs.

Rows keep their original order within each output. Each split produces nonempty parts whose row counts differ by at most one.

## Repeated shuffles

Pipeline: shuffle (auto) → shuffle (auto) → shuffle (auto) → balanced. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Shuffle the input rows into a random order. Shuffle them again into a random order. Shuffle them again into a random order, then split them as evenly as possible into 3 CSVs.

Each split produces nonempty parts whose row counts differ by at most one.

## One balanced file

Pipeline: balanced. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Keep the input together in one CSV.

Rows keep their original order within each output. Each split produces nonempty parts whose row counts differ by at most one.

## Compressed target without hard limits

Pipeline: partition. Limits: rows=none, bytes=none, compressed=10MB. Compression: gzip.

Create CSV files for each unique combination of “country” and “segment”.

Rows keep their original order within each output.

Aim for 10 MB per compressed file; this is an approximate target and may be exceeded. Compress each CSV separately with gzip.

## Balanced files with compressed target

Pipeline: balanced. Limits: rows=none, bytes=none, compressed=10MB. Compression: zstd.

Split the input as evenly as possible into 3 CSVs.

Rows keep their original order within each output. Each split produces nonempty parts whose row counts differ by at most one.

Aim for 10 MB per compressed file; this is an approximate target and may be exceeded. Keep the chosen file count even if the compressed files are larger than the target. Compress each CSV separately with Zstandard.

## Compressed target without compression

Pipeline: no steps. Limits: rows=none, bytes=none, compressed=10MB. Compression: none.

Write the input to one CSV, keeping rows in their original order.

Choose an output compression format to use the compressed size target.

## Unfinished partition

Pipeline: partition. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Choose the columns that should have separate CSV files.

Rows keep their original order within each output.

## Unfinished allocation

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Choose unique allocation names and percentages totaling 100%.

Rows keep their original order within each output.

## Invalid allocation total

Pipeline: assign. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Choose unique allocation names and percentages totaling 100%.

Rows keep their original order within each output.

## Unfinished balanced split

Pipeline: balanced. Limits: rows=none, bytes=none, compressed=none. Compression: none.

Choose a positive whole number of CSV files for the input.

Rows keep their original order within each output.
