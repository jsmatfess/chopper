# CSV compatibility fixtures

The manifest for each source specifies the input bytes, CSV settings and
expected headers and rows or error. Strings are UTF-8 and integer arrays are
literal bytes. The tests also generate a long header that crosses the parser
refill boundary and a separate forced-spill workload. See
[csv_compatibility.rs](../../csv_compatibility.rs).

Run the suite from the repository root with the checked-in fixtures.

```sh
cargo test --locked -p chopper --test csv_compatibility
```

## Chopper

The local cases exercise RFC 4180-style quoting, literal field content, line
endings, headers, inferred record width, encodings, record limits and optional
input settings. In width rejection cases, `parsed` gives the expected records
before CLI intake validates width. See [local.json](local.json).

## W3C CSV on the Web

The CSVW cases use the original input bytes under the W3C 3-clause BSD License.
Each `input.file` maps to the same filename in the upstream `tests/` directory.
The names identify CSVW tests 001–003, 019, 022–025, 050–052, 054–055 and 262.
See [the CSVW test suite at b3f461d](https://github.com/w3c/csvw/tree/b3f461db0e86a68c019bc1f912e86f3555907e34/tests)
and [the license](W3C-LICENSE).

The expectations project the CSVW test parameters onto explicit Chopper input
settings and compare raw string cells. For example, 022 applies `trim: both`
to cells, 051 skips the first two lines and uses `#` comments, and 050 and 262
retain the date strings from the CSV. See [csvw.json](csvw.json).

## Go standard library

Copyright 2011 The Go Authors. All rights reserved.

The Go cases adapt named examples and strip the diagnostic position markers
as Go's test runner does. See
[encoding/csv/reader_test.go at 880f3ba](https://github.com/golang/go/blob/880f3ba4028fbe81523ce4935c29c225972fff02/src/encoding/csv/reader_test.go)
and [the Go license](GO-LICENSE).

The manifest records three deliberate differences from the upstream
expectations. Chopper preserves CRLF inside quoted cells, requires quotation
around field text containing a lone CR, and requires ASCII delimiters. The
separate Unicode comment case exercises the supported comment setting. See
[go.json](go.json).
