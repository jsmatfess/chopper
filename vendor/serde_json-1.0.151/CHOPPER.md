# Chopper's Serde JSON package

Upstream `serde_json` 1.0.151 has package checksum
`c841b55ecdae098c80dcae9cf767f6f8a0c2cdb3416bbef72181df4d0fe73f14`.
The original source and the MIT and Apache-2.0 license notices are included.

The package identity `chopper-serde-json` preserves the default upstream
implementation in Cargo consumers. The manifest exposes only `std`. Another
dependency can select upstream `arbitrary_precision`, `float_roundtrip` or
`preserve_order` and keep Chopper's allocation and serialization behavior.
The fork uses the same Serde trait types as the public Job and report types.

The Job decoder's [working-allocation audit](../../docs/cli-job-decoding.md)
covers the audited streaming JSON scratch and typed configuration. Resource
ownership elsewhere also depends on the inline representation of numbers and
the order and allocation behavior of the default `BTreeMap` representation of
JSON objects. Revisit these audits and the downstream package checks when
updating the code or the dependency graph.
