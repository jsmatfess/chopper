use chopper_core::{
    csv::{CompactRecord, Parser},
    CsvSettings,
};
use std::io::BufReader;

#[test]
fn admitted_spans_match_scalar_fields_across_every_small_refill_and_working_edge(
) -> anyhow::Result<()> {
    let cases: &[&[u8]] = &[
        b"alpha,beta\nnext,last\n",
        b"alpha,beta",
        b"alpha,,\n,tail,\n",
        "α,界\n\"quoted,comma\",\"a\"\"b\nline\"\n".as_bytes(),
        b"alpha,beta\r\n\r\n\"\",tail\r\n",
        b"a;\"b\\\"c\";d\n",
        b"a\"b,c\n",
        b"a,\"b\"junk\n",
        b"a,\"b",
        b"alpha,\xff\n",
        b"alpha,beta\rgamma",
        b"\n",
        b"\"\"\n",
        b"a\0b,c\n",
    ];
    for input in cases {
        for capacity in 1..=80 {
            for maximum in [0, 1, 5, 31, 32, 37, 38, 63, 64, 65, 128, 4096] {
                for custom in [false, true] {
                    let settings = CsvSettings {
                        delimiter: if custom { ';' } else { ',' },
                        escape: custom.then_some('\\'),
                        skip_empty_lines: custom,
                        ..Default::default()
                    };
                    let mut scalar = Parser::new(
                        BufReader::with_capacity(capacity, *input),
                        settings.clone(),
                        maximum,
                    );
                    let mut compact = Parser::new(
                        BufReader::with_capacity(capacity, *input),
                        settings.clone(),
                        maximum,
                    );
                    let mut owned = Parser::new(
                        BufReader::with_capacity(capacity, *input),
                        settings,
                        maximum,
                    );
                    let mut record = CompactRecord::default();
                    let mut fields = Vec::new();
                    loop {
                        let a = scalar.next_record();
                        let b = compact.next_compact_record_into(&mut record);
                        let c = owned.next_record_into_reserved(&mut fields, &mut |_| Ok(()));
                        assert_eq!(scalar.record, compact.record);
                        assert_eq!(scalar.record, owned.record);
                        match (a,b,c) {
                            (Ok(Some(expected)),Ok(true),Ok(true)) => { assert_eq!(record.fields().collect::<Vec<_>>(), expected); assert_eq!(fields,expected); },
                            (Ok(None),Ok(false),Ok(false)) => { assert!(record.is_empty()); assert!(fields.is_empty()); break; },
                            (Err(a),Err(b),Err(c)) => { assert_eq!(format!("{a:#}"),format!("{b:#}")); assert_eq!(format!("{a:#}"),format!("{c:#}")); assert!(record.is_empty()); break; },
                            (a,b,c) => panic!("parser mismatch capacity={capacity}, maximum={maximum}, input={input:?}: {a:?}/{b:?}/{c:?}"),
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

#[test]
fn admitted_span_denial_keeps_every_retained_capacity_charged() {
    let input = "first,second,界\nthird,\"quoted\nfield\",last\n";
    for capacity in [1, 7, 17, 65536] {
        for budget in 0..=320 {
            let mut parser = Parser::new(
                BufReader::with_capacity(capacity, input.as_bytes()),
                CsvSettings::default(),
                4096,
            );
            let mut record = CompactRecord::default();
            let mut granted = 0;
            loop {
                let result = parser.next_compact_record_into_reserved(&mut record, &mut |bytes| {
                    anyhow::ensure!(bytes <= budget, "synthetic admission denial");
                    granted = bytes;
                    Ok(())
                });
                assert!(granted >= record.capacity() + parser.scratch_capacity());
                if !matches!(result, Ok(true)) {
                    break;
                }
            }
            let mut parser = Parser::new(
                BufReader::with_capacity(capacity, input.as_bytes()),
                CsvSettings::default(),
                4096,
            );
            let mut fields = Vec::new();
            let mut granted = 0;
            loop {
                let result = parser.next_record_into_reserved(&mut fields, &mut |bytes| {
                    anyhow::ensure!(bytes <= budget, "synthetic admission denial");
                    granted = bytes;
                    Ok(())
                });
                assert!(
                    granted
                        >= fields.capacity() * std::mem::size_of::<String>()
                            + fields.iter().map(String::capacity).sum::<usize>()
                            + parser.scratch_capacity()
                );
                if !matches!(result, Ok(true)) {
                    break;
                }
            }
        }
    }
}
