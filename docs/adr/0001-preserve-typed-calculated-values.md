# Preserve typed calculated values through the pipeline

Calculated columns in the planned expression language can reference earlier
calculated columns, so their values retain their types across pipeline steps,
including when rows spill to disk. Partition keys and CSV output use the
values' text representation, preserving Chopper's text-based partition rules.
Keeping the typed value alongside that boundary lets later formulas distinguish
`NULL` from empty text and read a timestamp's original offset even though its
default text representation uses UTC.
