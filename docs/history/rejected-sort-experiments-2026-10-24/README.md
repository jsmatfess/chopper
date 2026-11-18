# Rejected sort experiment source snapshots

These are byte-for-byte snapshots of the working-tree implementations immediately
before the 2026-10-24 removal, including pre-existing uncommitted ownership edits.
They are historical text, outside every build and harness. They do not identify
the source of older measurements; those artifacts retain their own recorded
source/build identities. No historical binary is relabeled as this snapshot.

- `radix.rs.txt`: SHA-256 `86a1ffb72dcd621658376f53ea0d8f768b7afe37e09b5b3330c78725dda32b46`.
- `distribution.rs.txt`: SHA-256 `e77e32b07bb9b138086493d3d5df8c77ddcd3c5453b9e5f9560abc6b9f8ed4bd`.

Comparison sorting, collision refinement, routing and external merge remain in
live storage modules. See [removal validation](../../validation.md#radix-and-prefix-distribution-removal-2026-10-24)
and the [pre-removal review](../../strategy-review.md).
