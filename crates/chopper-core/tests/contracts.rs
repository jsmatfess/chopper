use chopper_core::{
    csv::{self, DecodeReader, Parser},
    random, *,
};
use std::io::{BufReader, Cursor, Read};

#[test]
fn decoded_text_packing_preserves_literal_fields_and_matches_csv_framing() -> anyhow::Result<()> {
    let values = [
        "",
        "0007",
        "null",
        "NA",
        "2026-10-19",
        "界\0\n\"\\",
        " ",
        "",
    ];
    let maximum = values.iter().map(|v| v.len()).sum::<usize>() + values.len() * 32;
    let mut packed = csv::CompactRecord::default();
    let mut held = 0;
    packed.set_text_fields_reserved(values.into_iter(), maximum, &mut |n| {
        held = n;
        Ok(())
    })?;
    assert_eq!(held, packed.capacity());
    assert_eq!(packed.fields().collect::<Vec<_>>(), values);
    let bytes = csv::serialize(&values.map(str::to_owned), &Default::default())?;
    let mut parser = Parser::new(Cursor::new(bytes), Default::default(), 8192);
    let mut reference = csv::CompactRecord::default();
    assert!(parser.next_compact_record_into(&mut reference)?);
    assert_eq!(packed.encoded_fields(), reference.encoded_fields());
    let mut owned = Vec::new();
    csv::copy_text_fields_into_reserved(values.into_iter(), &mut owned, maximum, &mut |n| {
        held = n;
        Ok(())
    })?;
    assert_eq!(owned, values);
    assert_eq!(
        held,
        owned.capacity() * std::mem::size_of::<String>()
            + owned.iter().map(String::capacity).sum::<usize>()
    );
    assert!(packed
        .set_text_fields_reserved(values.into_iter(), maximum - 1, &mut |_| Ok(()))
        .is_err());
    assert!(packed.is_empty());
    assert!(packed
        .set_text_fields_reserved([].into_iter(), maximum, &mut |_| Ok(()))
        .is_err());
    Ok(())
}

#[test]
fn decoded_text_growth_denial_retains_owned_capacity_and_wide_columns_do_not_accumulate(
) -> anyhow::Result<()> {
    let wide = "x".repeat(4096);
    let mut packed = csv::CompactRecord::default();
    packed.set_text_fields_reserved(["a", "b"].into_iter(), 8192, &mut |_| Ok(()))?;
    let old = packed.capacity();
    let limit = old + 8 + 16 + wide.len() + 1 - 1;
    let mut held = 0;
    let result =
        packed.set_text_fields_reserved([wide.as_str(), "x"].into_iter(), 8192, &mut |n| {
            anyhow::ensure!(n <= limit, "denied");
            held = n;
            Ok(())
        });
    assert!(result.is_err());
    assert!(packed.is_empty());
    assert_eq!(packed.capacity(), old);
    assert_eq!(held, old);
    let mut owned = vec!["a".to_owned(), "b".to_owned()];
    let old = owned.capacity() * std::mem::size_of::<String>()
        + owned.iter().map(String::capacity).sum::<usize>();
    let limit = old + wide.len() - 1;
    let result = csv::copy_text_fields_into_reserved(
        [wide.as_str(), "x"].into_iter(),
        &mut owned,
        8192,
        &mut |n| {
            anyhow::ensure!(n <= limit, "denied");
            held = n;
            Ok(())
        },
    );
    assert!(result.is_err());
    assert_eq!(owned, ["a", "b"]);
    assert_eq!(held, old);
    for i in 0..32 {
        let values = if i % 2 == 0 {
            [wide.as_str(), "x"]
        } else {
            ["x", wide.as_str()]
        };
        csv::copy_text_fields_into_reserved(values.into_iter(), &mut owned, 8192, &mut |n| {
            held = n;
            Ok(())
        })?;
        assert_eq!(owned, values);
        let payload = owned.iter().map(String::capacity).sum::<usize>();
        assert!(payload <= wide.len() + 128);
        assert_eq!(
            held,
            owned.capacity() * std::mem::size_of::<String>() + payload
        );
    }
    Ok(())
}

#[test]
fn compact_parser_matches_owned_fields_errors_and_working_limits() -> anyhow::Result<()> {
    let inputs: &[&[u8]] = &[
        b"",
        b"\n\n",
        b"a,b\r\n\"hello\r\nworld\",\"a\"\"b\"\n\"\",end",
        b"a,b,\n\"\",\"\",\"\"\n",
        b"\"unterminated",
        b"\"closed\"x\n",
        b"bare\rX",
        b"quo\"te,x\n",
        b"a,\xff\n",
        b"\"a\\\"b\";c\n",
        "界,é\0\n".as_bytes(),
    ];
    for input in inputs {
        for capacity in [1, 2, 7, 65536] {
            for maximum in [0, 1, 2, 31, 32, 33, 63, 64, 65, 128, 4096] {
                for custom in [false, true] {
                    let settings = CsvSettings {
                        delimiter: if custom { ';' } else { ',' },
                        escape: custom.then_some('\\'),
                        skip_empty_lines: custom,
                        ..Default::default()
                    };
                    let mut owned = Parser::new(
                        BufReader::with_capacity(capacity, *input),
                        settings.clone(),
                        maximum,
                    );
                    let mut compact = Parser::new(
                        BufReader::with_capacity(capacity, *input),
                        settings,
                        maximum,
                    );
                    let mut record = csv::CompactRecord::default();
                    loop {
                        let a = owned.next_record();
                        let b = compact.next_compact_record_into(&mut record);
                        assert_eq!(owned.record, compact.record);
                        match (a, b) {
                            (Ok(Some(fields)), Ok(true)) => {
                                assert_eq!(record.fields().collect::<Vec<_>>(), fields);
                                assert_eq!(record.len(), fields.len());
                                assert_eq!(
                                    record.payload_bytes(),
                                    fields.iter().map(String::len).sum::<usize>()
                                );
                                let mut encoded = (fields.len() as u64).to_le_bytes().to_vec();
                                for field in fields {
                                    encoded.extend_from_slice(&(field.len() as u64).to_le_bytes());
                                    encoded.extend_from_slice(field.as_bytes());
                                }
                                assert_eq!(record.encoded_fields(), encoded);
                            }
                            (Ok(None), Ok(false)) => {
                                assert!(record.is_empty());
                                break;
                            }
                            (Err(a), Err(b)) => {
                                assert_eq!(format!("{a:#}"), format!("{b:#}"));
                                assert!(record.is_empty());
                                break;
                            }
                            (a, b) => panic!(
                                "parser mismatch {input:?}/{capacity}/{maximum}: {a:?} / {b:?}"
                            ),
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

#[test]
fn compact_parser_reuses_storage_through_wide_columns_and_transcoding() -> anyhow::Result<()> {
    for encoding in ["utf-8", "utf-16le", "shift_jis"] {
        let settings = CsvSettings {
            encoding: encoding.into(),
            ..Default::default()
        };
        let rows = [
            vec!["界".repeat(20000), "small".into()],
            vec!["a".into(), "界".repeat(20000)],
        ];
        let input = rows
            .iter()
            .map(|row| csv::serialize(row, &settings))
            .collect::<anyhow::Result<Vec<_>>>()?
            .concat();
        let decoder = DecodeReader::new(Cursor::new(input), encoding)?;
        let mut parser = Parser::new(BufReader::with_capacity(7, decoder), settings, 256 * 1024);
        let mut record = csv::CompactRecord::default();
        let mut capacity_pointer = None;
        for row in &rows {
            assert!(parser.next_compact_record_into(&mut record)?);
            assert_eq!(record.fields().collect::<Vec<_>>(), *row);
            if let Some(pointer) = capacity_pointer {
                assert_eq!(record.encoded_fields().as_ptr(), pointer);
            }
            capacity_pointer = Some(record.encoded_fields().as_ptr());
            record = csv::CompactRecord::with_storage(record.into_encoded_fields());
            assert!(record.is_empty());
        }
        assert!(!parser.next_compact_record_into(&mut record)?);
    }
    Ok(())
}

#[test]
fn compact_parser_reserves_capacity_and_growth_overlap_at_exact_edges() -> anyhow::Result<()> {
    // Moving wide fields exercises both scratch and framed-record growth;
    // escaped quotes exercise scalar pushes as well as chunk copies.
    let input = format!(
        "\"{}\"\"界\",tail\nshort,{}\n",
        "x".repeat(300),
        "y".repeat(1000)
    );
    for chunk in [1, 7, 65536] {
        let run = |limit: usize| -> anyhow::Result<(bool, usize)> {
            let mut parser = Parser::new(
                BufReader::with_capacity(chunk, input.as_bytes()),
                CsvSettings::default(),
                4096,
            );
            let mut record = csv::CompactRecord::default();
            let mut charged = 0;
            let mut peak = 0;
            loop {
                let result = parser.next_compact_record_into_reserved(&mut record, &mut |bytes| {
                    anyhow::ensure!(bytes <= limit, "shared budget denied");
                    charged = bytes;
                    peak = peak.max(bytes);
                    Ok(())
                });
                assert_eq!(charged, parser.scratch_capacity() + record.capacity());
                match result {
                    Ok(true) => {}
                    Ok(false) => return Ok((true, peak)),
                    Err(error) => {
                        assert!(format!("{error:#}").contains("shared budget denied"));
                        assert!(record.is_empty());
                        return Ok((false, peak));
                    }
                }
            }
        };
        let (_, peak) = run(usize::MAX)?;
        assert!(!run(peak - 1)?.0);
        assert!(run(peak)?.0);
        assert!(run(peak + 1)?.0);
    }
    Ok(())
}

fn parse(data: &[u8], settings: CsvSettings) -> anyhow::Result<Vec<Vec<String>>> {
    let decoder = DecodeReader::new(Cursor::new(data), &settings.encoding)?;
    let mut parser = Parser::new(BufReader::with_capacity(1, decoder), settings, 4096);
    let mut rows = vec![];
    while let Some(row) = parser.next_record()? {
        rows.push(row);
    }
    Ok(rows)
}
#[test]
fn strict_csv_handles_multiline_quotes_empty_and_crlf() {
    let rows = parse(
        b"a,b\r\n\"hello\r\nworld\",\"a\"\"b\"\r\n\"\",end",
        CsvSettings::default(),
    )
    .unwrap();
    assert_eq!(
        rows,
        vec![
            vec!["a", "b"],
            vec!["hello\r\nworld", "a\"b"],
            vec!["", "end"]
        ]
    );
    for input in [
        b"\"unterminated".as_slice(),
        b"a\"b,c",
        b"\"a\"junk,b",
        b"a,b\rc,d",
        b"\n",
    ] {
        assert!(parse(input, CsvSettings::default()).is_err(), "{:?}", input);
    }
}
#[test]
fn encoding_and_serialization_roundtrip_strictly() {
    let fields = vec!["café".into(), "a,\"b\"\nline".into(), "".into()];
    for (enc, signature) in [
        ("utf-8", &[0xef, 0xbb, 0xbf][..]),
        ("utf-16le", &[0xff, 0xfe][..]),
        ("utf-16be", &[0xfe, 0xff][..]),
        ("windows-1252", &[][..]),
    ] {
        let s = CsvSettings {
            encoding: enc.into(),
            bom: !signature.is_empty(),
            ..CsvSettings::default()
        };
        let mut data = csv::bom(&s).unwrap();
        assert_eq!(data, signature, "{enc}");
        data.extend(csv::serialize(&fields, &s).unwrap());
        assert_eq!(parse(&data, s).unwrap(), vec![fields.clone()]);
    }
    assert!(csv::bom(&CsvSettings {
        encoding: "windows-1252".into(),
        bom: true,
        ..Default::default()
    })
    .is_err());
    assert!(csv::encode("漢字", "windows-1252").is_err());
    assert!(parse(&[0xff, 0xff], CsvSettings::default()).is_err());
}
#[test]
fn decoder_preserves_characters_across_input_blocks() {
    for enc in ["utf-8", "utf-16le", "utf-16be", "Shift_JIS"] {
        let text = format!("{}漢字", "a".repeat(8191));
        let data = csv::encode(&text, enc).unwrap();
        let mut decoder = DecodeReader::new(Cursor::new(data), enc).unwrap();
        let mut actual = String::new();
        decoder.read_to_string(&mut actual).unwrap();
        assert_eq!(text, actual);
    }
}

#[test]
fn decoder_delivers_the_valid_prefix_before_reporting_malformed_input() -> anyhow::Result<()> {
    for capacity in [1, 64 * 1024] {
        let mut decoder = DecodeReader::new(b"valid\n\xfftail".as_slice(), "utf-8")?;
        let mut buffer = vec![0; capacity];
        let mut prefix = Vec::new();
        let error = loop {
            match decoder.read(&mut buffer) {
                Ok(0) => panic!("reader discarded a malformed byte"),
                Ok(read) => prefix.extend_from_slice(&buffer[..read]),
                Err(error) => break error,
            }
        };
        assert_eq!(prefix, b"valid\n");
        assert_eq!(error.kind(), std::io::ErrorKind::InvalidData);
        let mut tail = String::new();
        decoder.read_to_string(&mut tail)?;
        assert_eq!(tail, "tail");
    }
    Ok(())
}

#[test]
fn custom_escape_and_delimiter() {
    let s = CsvSettings {
        delimiter: ';',
        escape: Some('\\'),
        ..CsvSettings::default()
    };
    let row = vec!["a;\"b\\c".into()];
    let data = csv::serialize(&row, &s).unwrap();
    assert_eq!(parse(&data, s).unwrap(), vec![row]);
}
#[test]
fn largest_remainder_and_decimal_validation() {
    let groups = vec![
        Allocation {
            name: "a".into(),
            percent: "33.333333".into(),
        },
        Allocation {
            name: "b".into(),
            percent: "33.333333".into(),
        },
        Allocation {
            name: "c".into(),
            percent: "33.333334".into(),
        },
    ];
    let w = weights(&groups).unwrap();
    assert_eq!(quotas(2, &w), vec![1, 0, 1]);
    for n in [0, 1, 10, 1_000_000_000, u64::MAX] {
        assert_eq!(quotas(n, &w).iter().sum::<u64>(), n);
    }
    assert!(weights(&[Allocation {
        name: "a".into(),
        percent: "99.999999".into()
    }])
    .is_err());
    assert_eq!(quotas(3, &[50_000_000, 50_000_000]), vec![2, 1]);
}
#[test]
fn tuple_keys_preserve_field_boundaries_and_lexical_order() {
    let tuples = vec![
        vec!["a".into(), "bc".into()],
        vec!["ab".into(), "c".into()],
        vec!["a\0".into(), "".into()],
        vec!["a".into(), "b".into()],
    ];
    let mut expected = tuples.clone();
    expected.sort();
    let mut actual = tuples;
    actual.sort_by_key(|v| random::tuple_key(v, &[0, 1]));
    assert_eq!(actual, expected);
}
#[test]
fn parser_enforces_record_working_budget() {
    let mut parser = Parser::new(Cursor::new(b"abcdef\n"), CsvSettings::default(), 4);
    assert!(parser
        .next_record()
        .unwrap_err()
        .to_string()
        .contains("CSV record"));
}

#[test]
fn reused_records_preserve_boundaries_blank_lines_and_working_limits() {
    for capacity in [1, 2, 3, 7, 64, 65536] {
        let settings = CsvSettings {
            skip_empty_lines: true,
            ..Default::default()
        };
        let input = "\r\nα,\"a\"\"b\r\n界\",\"\"\r\n\nlast\n";
        let mut parser = Parser::new(
            BufReader::with_capacity(capacity, input.as_bytes()),
            settings,
            4096,
        );
        let mut fields = vec!["stale".repeat(100); 8];
        assert!(parser.next_record_into(&mut fields).unwrap());
        assert_eq!(fields, ["α", "a\"b\r\n界", ""]);
        assert_eq!(parser.record, 2);
        assert!(parser.next_record_into(&mut fields).unwrap());
        assert_eq!(fields, ["last"]);
        assert_eq!(parser.record, 4);
        assert!(!parser.next_record_into(&mut fields).unwrap());
        assert!(fields.is_empty());

        // Preserve v1 working-byte accounting, including CRLF counting as one
        // structural byte and the 32-byte charge for each completed field.
        for input in [b"abc,d\n".as_slice(), b"abc,d\r\n"] {
            for maximum in [37, 38] {
                let mut parser = Parser::new(
                    BufReader::with_capacity(capacity, input),
                    CsvSettings::default(),
                    maximum,
                );
                assert_eq!(parser.next_record_into(&mut fields).is_ok(), maximum == 38);
            }
        }
    }
}

#[test]
fn reused_record_capacity_is_bounded_when_wide_fields_move() {
    let mut data = String::new();
    for wide in 0..32 {
        let fields: Vec<_> = (0..32)
            .map(|i| {
                if i == wide {
                    "x".repeat(4096)
                } else {
                    "x".into()
                }
            })
            .collect();
        data.push_str(&fields.join(","));
        data.push('\n');
    }
    let mut parser = Parser::new(Cursor::new(data), CsvSettings::default(), 8192);
    let mut fields = Vec::new();
    for wide in 0..32 {
        assert!(parser.next_record_into(&mut fields).unwrap());
        assert_eq!(fields[wide].len(), 4096);
        assert!(fields.iter().map(String::capacity).sum::<usize>() <= 16384);
    }
}

#[test]
fn reusable_serializer_clears_previous_record_and_preserves_encoding() {
    for enc in ["utf-8", "utf-16le", "utf-16be", "windows-1252", "Shift_JIS"] {
        for escape in [None, Some('\\')] {
            let settings = CsvSettings {
                encoding: enc.into(),
                escape,
                line_ending: "crlf".into(),
                ..Default::default()
            };
            let mut serializer = csv::Serializer::new(&settings).unwrap();
            for row in [
                vec!["x".repeat(1000), "a,\"b\\c\r\n".into(), String::new()],
                vec!["short".into()],
            ] {
                let bytes = serializer.serialize(&row).unwrap().to_vec();
                assert_eq!(serializer.bytes(), bytes);
                assert_eq!(parse(&bytes, settings.clone()).unwrap(), vec![row]);
            }
        }
    }
}
#[test]
fn byte_units_preserve_decimal_and_binary_scales_and_reject_overflow() -> anyhow::Result<()> {
    for (input, expected) in [
        ("42", 42),
        ("2 B", 2),
        ("2 kB", 2_000),
        ("100 MB", 100_000_000),
        ("2Gb", 2_000_000_000),
        ("2 TB", 2_000_000_000_000),
        ("2 KiB", 2 * 1024),
        ("64MiB", 64 * 1024_u64.pow(2)),
        ("2 GiB", 2 * 1024_u64.pow(3)),
        ("2TiB", 2 * 1024_u64.pow(4)),
    ] {
        assert_eq!(parse_bytes(input)?, expected, "{input}");
    }
    for input in ["2PB", "1.5GiB", "99999999999999999TiB"] {
        assert!(parse_bytes(input).is_err(), "{input}");
    }
    assert_eq!(parse_bytes("18446744073709551615 B")?, u64::MAX);
    Ok(())
}

#[test]
fn column_selection_preserves_exact_names_and_requested_order() -> anyhow::Result<()> {
    let header = ["First", "Key", "Key", "Last"].map(String::from);
    let selected = [
        Column::Name("Last".into()),
        Column::Index(2),
        Column::Name("First".into()),
        Column::Index(2),
    ];
    assert_eq!(
        resolve_columns(&selected, Some(&header), header.len())?,
        [3, 2, 0, 2]
    );
    assert_eq!(resolve_column(&Column::Index(3), None, header.len())?, 3);
    assert!(resolve_column(&Column::Index(4), Some(&header), header.len()).is_err());
    assert!(resolve_column(&Column::Name("Last".into()), None, header.len()).is_err());
    for name in ["first", "Key"] {
        let error =
            resolve_column(&Column::Name(name.into()), Some(&header), header.len()).unwrap_err();
        assert!(
            error.to_string().contains("missing or ambiguous"),
            "{error:#}"
        );
    }
    Ok(())
}

#[test]
fn invalid_job_config_reports_the_exact_json_field() {
    for (fields, pointer) in [
        (
            serde_json::json!({"resources": {"temp_bytes": 0}}),
            "/resources/temp_bytes",
        ),
        (
            serde_json::json!({"output_csv": {"encoding": "not-an-encoding"}}),
            "/output_csv/encoding",
        ),
        (
            serde_json::json!({"calculated_columns": [
                {"name": "ok", "expression": "1"},
                {"name": "bad", "expression": "("}
            ]}),
            "/calculated_columns/1/expression",
        ),
    ] {
        let mut job: Job = serde_json::from_value(fields).unwrap();
        job.input = "in.csv".into();
        let error = job.validate().unwrap_err();
        let cause = error.downcast_ref::<JobValidationError>().unwrap();
        assert_eq!(cause.path(), pointer);
        assert!(!cause.to_string().is_empty());
    }
}

#[test]
fn input_only_configuration_requires_a_destination_for_publication() -> anyhow::Result<()> {
    let mut job = Job {
        input: "in.csv".into(),
        ..Default::default()
    };
    job.validate()?;
    let error = job.validate_output().unwrap_err();
    assert_eq!(
        error.downcast_ref::<JobValidationError>().unwrap().path(),
        "/output"
    );
    job.output = "out".into();
    job.validate_output()
}

#[test]
fn owned_reserved_parser_matches_owned_and_charges_exact_growth_edges() -> anyhow::Result<()> {
    let mut input = String::from("\r\n");
    for wide in 0..12 {
        let fields: Vec<_> = (0..12)
            .map(|i| {
                if i == wide {
                    format!("\"{}\"\"界\r\n\"", "x".repeat(4000))
                } else {
                    "tail".into()
                }
            })
            .collect();
        input.push_str(&fields.join(","));
        input.push_str("\r\n");
    }
    input.push_str("last\n");
    for chunk in [1, 7, 65536] {
        let run = |limit: usize| -> anyhow::Result<(bool, usize)> {
            let settings = CsvSettings {
                skip_empty_lines: true,
                ..Default::default()
            };
            let mut expected = Parser::new(
                BufReader::with_capacity(chunk, input.as_bytes()),
                settings.clone(),
                8192,
            );
            let mut parser = Parser::new(
                BufReader::with_capacity(chunk, input.as_bytes()),
                settings,
                8192,
            );
            let mut fields = Vec::new();
            let mut charged = 0;
            let mut peak = 0;
            loop {
                let result = parser.next_record_into_reserved(&mut fields, &mut |bytes| {
                    anyhow::ensure!(bytes <= limit, "shared budget denied");
                    charged = bytes;
                    peak = peak.max(bytes);
                    Ok(())
                });
                assert_eq!(
                    charged,
                    parser.scratch_capacity()
                        + fields.capacity() * std::mem::size_of::<String>()
                        + fields.iter().map(String::capacity).sum::<usize>()
                );
                match result {
                    Ok(true) => {
                        assert_eq!(Some(&fields), expected.next_record()?.as_ref());
                        assert_eq!(parser.record, expected.record);
                        assert!(fields.iter().map(String::capacity).sum::<usize>() <= 16384);
                    }
                    Ok(false) => {
                        assert!(expected.next_record()?.is_none());
                        return Ok((true, peak));
                    }
                    Err(error) => {
                        assert!(format!("{error:#}").contains("shared budget denied"));
                        return Ok((false, peak));
                    }
                }
            }
        };
        let (_, peak) = run(usize::MAX)?;
        assert!(!run(peak - 1)?.0);
        assert!(run(peak)?.0);
        assert!(run(peak + 1)?.0);
    }
    Ok(())
}

#[test]
fn owned_reserved_parser_retains_charges_on_invalid_input() -> anyhow::Result<()> {
    for input in [
        b"abc,\"unterminated".as_slice(),
        b"abc,\xff\n",
        b"abc,def\r",
        b"\n",
    ] {
        let mut parser = Parser::new(
            BufReader::with_capacity(1, input),
            CsvSettings::default(),
            4096,
        );
        let mut fields = Vec::new();
        let mut charged = 0;
        assert!(parser
            .next_record_into_reserved(&mut fields, &mut |bytes| {
                charged = bytes;
                Ok(())
            })
            .is_err());
        assert_eq!(
            charged,
            parser.scratch_capacity()
                + fields.capacity() * std::mem::size_of::<String>()
                + fields.iter().map(String::capacity).sum::<usize>()
        );
    }
    Ok(())
}

#[test]
fn reserved_serializer_matches_text_and_all_supported_encodings() -> anyhow::Result<()> {
    for encoding in [
        "utf-8",
        "utf-16le",
        "utf-16be",
        "windows-1250",
        "windows-1251",
        "windows-1252",
        "windows-1253",
        "windows-1254",
        "windows-1255",
        "windows-1256",
        "windows-1257",
        "windows-1258",
        "Shift_JIS",
        "GBK",
        "Big5",
        "EUC-KR",
        "ISO-8859-2",
    ] {
        for escape in [None, Some('\\')] {
            let settings = CsvSettings {
                encoding: encoding.into(),
                escape,
                line_ending: "crlf".into(),
                ..Default::default()
            };
            let mut serializer = csv::Serializer::new(&settings)?;
            let mut charged = 0;
            for fields in [
                vec!["a,\"b\\c\r\n".to_string(), "".into(), "tail".into()],
                vec!["x".repeat(10000)],
                vec!["short".into()],
            ] {
                let expected = csv::serialize(&fields, &settings)?;
                let actual = serializer.serialize_fields_reserved(
                    fields.iter().map(String::as_str),
                    &mut |bytes| {
                        charged = bytes;
                        Ok(())
                    },
                )?;
                assert_eq!(actual, expected, "{encoding}/{escape:?}");
                assert_eq!(charged, serializer.capacity());
            }
        }
    }
    for (encoding, value) in [
        ("utf-8", "界😀\"\n"),
        ("utf-16le", "界😀\"\n"),
        ("utf-16be", "界😀\"\n"),
        ("Shift_JIS", "日本語"),
        ("GBK", "中文"),
        ("Big5", "中文"),
        ("EUC-KR", "한국어"),
        ("windows-1251", "Русский"),
    ] {
        let settings = CsvSettings {
            encoding: encoding.into(),
            ..Default::default()
        };
        let fields = vec![value.to_string(), "".into()];
        let mut serializer = csv::Serializer::new(&settings)?;
        assert_eq!(
            serializer
                .serialize_fields_reserved(fields.iter().map(String::as_str), &mut |_| Ok(()))?,
            csv::serialize(&fields, &settings)?
        );
    }
    Ok(())
}

#[test]
fn reserved_serializer_growth_edges_shared_pressure_and_retry() -> anyhow::Result<()> {
    let edge = 8 + 1001; // prior minimum capacity plus replacement text capacity
    for limit in [edge - 1, edge, edge + 1] {
        let mut serializer = csv::Serializer::new(&CsvSettings::default())?;
        let mut used = 0;
        let mut peak = 0;
        let mut other = 0;
        let mut reserve = |bytes| -> anyhow::Result<()> {
            anyhow::ensure!(bytes + other <= limit, "shared budget");
            used = bytes;
            peak = peak.max(bytes + other);
            Ok(())
        };
        serializer.serialize_fields_reserved(["x"], &mut reserve)?;
        let wide = "y".repeat(1000);
        let result = serializer.serialize_fields_reserved([wide.as_str()], &mut reserve);
        assert_eq!(result.is_ok(), limit >= edge);
        drop(reserve);
        assert_eq!(used, serializer.capacity());
        if limit >= edge {
            assert_eq!(peak, edge);
        }
        // Every retained byte competes with unrelated work, including on reuse.
        other = limit;
        assert!(serializer
            .serialize_fields_reserved(["x"], &mut |bytes| {
                anyhow::ensure!(bytes + other <= limit, "shared budget");
                Ok(())
            })
            .is_err());
        other = 0;
        serializer.serialize_fields_reserved(["x"], &mut |bytes| {
            anyhow::ensure!(bytes + other <= limit, "shared budget");
            used = bytes;
            Ok(())
        })?;
        assert_eq!(used, serializer.capacity());
        assert_eq!(serializer.bytes(), b"x\n");
    }
    Ok(())
}

#[test]
fn reserved_serializer_encoding_failure_keeps_buffers_charged_and_retryable() -> anyhow::Result<()>
{
    let settings = CsvSettings {
        encoding: "windows-1252".into(),
        ..Default::default()
    };
    let mut serializer = csv::Serializer::new(&settings)?;
    let mut used = 0;
    assert!(serializer
        .serialize_fields_reserved(["before😀after"], &mut |bytes| {
            used = bytes;
            Ok(())
        })
        .is_err());
    assert_eq!(used, serializer.capacity());
    let expected = csv::serialize(&["valid".into()], &settings)?;
    assert_eq!(
        serializer.serialize_fields_reserved(["valid"], &mut |bytes| {
            used = bytes;
            Ok(())
        })?,
        expected
    );
    assert_eq!(used, serializer.capacity());
    // Permit text but deny the encoded destination, then retry without pressure.
    let mut utf16 = csv::Serializer::new(&CsvSettings {
        encoding: "utf-16le".into(),
        ..Default::default()
    })?;
    let wide = "x".repeat(1000);
    assert!(utf16
        .serialize_fields_reserved([wide.as_str()], &mut |bytes| {
            anyhow::ensure!(bytes <= 1001, "encoding destination denied");
            used = bytes;
            Ok(())
        })
        .is_err());
    assert_eq!(used, utf16.capacity());
    utf16.serialize_fields_reserved([wide.as_str()], &mut |bytes| {
        used = bytes;
        Ok(())
    })?;
    assert_eq!(used, utf16.capacity());
    assert_eq!(utf16.bytes().len(), 2002);
    Ok(())
}

#[test]
fn obsolete_shuffle_policies_are_rejected() {
    let job = serde_json::to_value(chopper_core::Job::default()).unwrap();
    assert!(job.get("full_shuffle_policy").is_none());
    for policy in ["seeded_v1", "flexible_v1"] {
        let mut request = job.clone();
        request["full_shuffle_policy"] = serde_json::json!(policy);
        assert!(serde_json::from_value::<chopper_core::Job>(request)
            .unwrap_err()
            .to_string()
            .contains("unknown field `full_shuffle_policy`"));
    }
}

#[test]
fn removed_shuffle_experiments_are_strict_errors_and_counter_defaults_survive() -> anyhow::Result<()>
{
    let job = Job {
        input: "fixture.csv".into(),
        ..Default::default()
    };
    let default = serde_json::to_value(&job)?;
    assert!(default.get("full_shuffle_rng").is_none());
    assert!(default.get("full_shuffle_algorithm").is_none());
    assert!(default["resources"]
        .get("shuffle_rng_buffer_bytes")
        .is_none());
    for _ in [0] {
        for (field, value, expected) in [
            (
                "full_shuffle_algorithm",
                serde_json::json!("independent_buckets_v1"),
                "unknown variant `independent_buckets_v1`",
            ),
            (
                "full_shuffle_rng",
                serde_json::json!("blake3_xof_v1"),
                "unknown variant `blake3_xof_v1`",
            ),
            (
                "resources",
                serde_json::json!({"shuffle_rng_buffer_bytes":64}),
                "unknown field `shuffle_rng_buffer_bytes`",
            ),
        ] {
            let mut request = default.clone();
            request[field] = value;
            let error = serde_json::from_value::<Job>(request)
                .unwrap_err()
                .to_string();
            assert!(error.contains(expected), "{error}");
        }
        let mut request = default.clone();
        request["full_shuffle_rng"] = serde_json::json!("blake3_counter_v1");
        request["full_shuffle_algorithm"] = serde_json::json!("adaptive_v1");
        let decoded: Job = serde_json::from_value(request)?;
        decoded.validate()?;
        assert_eq!(decoded.full_shuffle_rng, FullShuffleRng::Blake3CounterV1);
        assert_eq!(
            serde_json::to_value(decoded)?["resources"],
            default["resources"]
        );
    }
    Ok(())
}
