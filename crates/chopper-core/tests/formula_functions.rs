use chopper_core::expression::{EvalError, Expression, Value};

fn check(cases: &[(&str, char, &str)]) {
    for &(source, kind, expected) in cases {
        let expression =
            Expression::parse(source).unwrap_or_else(|error| panic!("{source}: {error}"));
        let value = expression
            .evaluate(&|_| None, &mut |_| Ok(()))
            .unwrap_or_else(|error| panic!("{source}: {error}"));
        assert_eq!(value.kind(), kind, "{source}");
        assert_eq!(
            value.rendered(&mut |_| Ok(())).unwrap(),
            expected,
            "{source}"
        );
    }
}

#[test]
fn text_functions_keep_unicode_and_null_contracts() {
    check(&[
        (r#"LEFT("é🙂z", 2)"#, 't', "é🙂"),
        (r#"RIGHT("é🙂z", 2)"#, 't', "🙂z"),
        (r#"RIGHT("é🙂z", 0)"#, 't', ""),
        (r#"RIGHT("é🙂z", 4)"#, 't', "é🙂z"),
        (r#"LENGTH("é🙂z")"#, 'f', "3"),
        (r#"BYTE_LENGTH("é🙂z")"#, 'f', "7"),
        (r#"CONTAINS("Été", "té")"#, 'b', "true"),
        (r#"CONTAINS("Été", "été")"#, 'b', "false"),
        (r#"IS_BLANK(NULL) AND IS_BLANK("　 ")"#, 'b', "true"),
        (r#"LTRIM("　x　")"#, 't', "x　"),
        (r#"RTRIM("　x　")"#, 't', "　x"),
        (r#"REPEAT("é", 0)"#, 't', ""),
        (r#"REPEAT("", 4)"#, 't', ""),
        (r#"STRIP_PREFIX("éx", "é")"#, 't', "x"),
        (r#"STRIP_SUFFIX("éx", "x")"#, 't', "é"),
        (r#"STRIP_SUFFIX("éx", "z")"#, 't', "éx"),
        (r#"SPLIT_PART("é::::x", "::", 1)"#, 't', ""),
        (r#"SPLIT_PART("é::::x", "::", 2)"#, 't', "x"),
        (r#"SPLIT_PART("é::::x", "::", 3)"#, 'n', ""),
        (r#"TEXT_BEFORE(UPPER("é::x::z"), "::")"#, 't', "É"),
        (r#"TEXT_AFTER("é::x::z", "::")"#, 't', "x::z"),
        (r#"TEXT_AFTER("é", "::")"#, 'n', ""),
        (r#"SAFE.TEXT_AFTER("é", "")"#, 'n', ""),
        (r#"IS_ASCII("") AND NOT IS_ASCII("é")"#, 'b', "true"),
        (
            r#"IS_DIGITS("001") AND NOT IS_DIGITS("") AND NOT IS_DIGITS("１")"#,
            'b',
            "true",
        ),
        (r#"TRANSLATE("aé!a🙂", "aéa!", "ø猫X")"#, 't', "ø猫ø🙂"),
        (r#"LPAD("é", 4, "🙂x")"#, 't', "🙂x🙂é"),
        (r#"RPAD("é", 4, "🙂x")"#, 't', "é🙂x🙂"),
        (r#"LPAD("é🙂", 1)"#, 't', "é"),
        (r#"RPAD("x", 3)"#, 't', "x  "),
        (r#"SAFE.RPAD("x", 3, "")"#, 'n', ""),
        (r#"REPEAT("猫a", 3)"#, 't', "猫a猫a猫a"),
        (r#"CONCAT_WS("|", "a", NULL, "", "b")"#, 't', "a||b"),
        (r#"CONCAT_WS("|", NULL, NULL)"#, 't', ""),
        (r#"CONCAT_WS(NULL, "a")"#, 'n', ""),
    ]);
}

#[test]
fn ampersand_uses_concat_rules_and_operator_precedence() {
    check(&[
        (r#""Ada" & " " & "Lovelace" = "Ada Lovelace""#, 'b', "true"),
        (r#""A" & "B" IN ("AB", "BC")"#, 'b', "true"),
        (r#""é" & "" & "猫""#, 't', "é猫"),
        (r#""prefix" & NULL"#, 'n', ""),
        (r#"NULL & (1 / 0)"#, 'n', ""),
        (r#"SAFE("prefix" & 42)"#, 'n', ""),
    ]);
    let arithmetic = Expression::parse(r#""prefix" & 1 + 1 / 0"#).unwrap();
    assert_eq!(
        arithmetic
            .evaluate(&|_| None, &mut |_| Ok(()))
            .unwrap_err()
            .to_string(),
        "Cannot divide by zero. Use a nonzero divisor or wrap the operation in SAFE(...) to return NULL.",
    );
    let chain = vec![r#""x""#; 65].join(" & ");
    check(&[(&chain, 't', &"x".repeat(65))]);
}

#[test]
fn concat_ws_can_skip_nulls_and_empty_text_independently() {
    check(&[
        (r#"CONCAT_WS("|", "a", NULL, "", "b", FALSE)"#, 't', "a|||b"),
        (
            r#"CONCAT_WS("|", "a", NULL, "", "b", TRUE, TRUE)"#,
            't',
            "a|b",
        ),
        (
            r#"CONCAT_WS("|", "a", NULL, "", "b", FALSE, TRUE)"#,
            't',
            "a||b",
        ),
        (r#"CONCAT_WS("|", NULL, NULL, FALSE, TRUE)"#, 't', "|"),
        (r#"CONCAT_WS("|", "", "", TRUE, TRUE)"#, 't', ""),
        (r#"CONCAT_WS("|", " ", "b", TRUE, TRUE)"#, 't', " |b"),
        (r#"CONCAT_WS("|", "true")"#, 't', "true"),
        (r#"CONCAT_WS(NULL, "x", FALSE, TRUE)"#, 'n', ""),
        (r#"CONCAT("a", NULL, "b")"#, 'n', ""),
    ]);
    assert!(Expression::parse(r#"CONCAT_WS("|", TRUE, TRUE)"#).is_err());
    let values = ", \"x\"".repeat(63);
    let maximum = format!(r#"CONCAT_WS("|"{values}, TRUE, TRUE)"#);
    let expected = vec!["x"; 63].join("|");
    check(&[(&maximum, 't', &expected)]);
    assert!(Expression::parse(&format!(r#"CONCAT_WS("|"{values}, "x", TRUE)"#)).is_err());
}

#[test]
fn typed_predicates_and_numeric_functions() {
    check(&[
        (r#"NULLIF(TRIM("  "), "")"#, 'n', ""),
        (r#"NULLIF("x", NULL)"#, 't', "x"),
        (r#"SAFE.NULLIF("1", 1)"#, 'n', ""),
        (r#"FLOOR(-1.25)"#, 'f', "-2"),
        (r#"CEIL(-1.25)"#, 'f', "-1"),
        (r#"TRUNC(-1.25)"#, 'f', "-1"),
        ("10 - 2", 'f', "8"),
        ("9 * 2", 'f', "18"),
        ("7 / 2", 'f', "3.5"),
        ("8 % 3", 'f', "2"),
        ("1 + NULL", 'n', ""),
        ("3 > 2 AND 2 <> 3 AND NOT (2 > 2)", 'b', "true"),
        (
            r#"BETWEEN(1, 1, 2) AND BETWEEN("west", "east", "west")"#,
            'b',
            "true",
        ),
        (r#"SAFE.BETWEEN(1, 2, "3")"#, 'n', ""),
        (
            r#"IS_TEXT("01") AND IS_NUMBER(NUMBER("01")) AND IS_BOOLEAN(FALSE)"#,
            'b',
            "true",
        ),
        (
            r#"IS_TEXT(NULL) OR IS_NUMBER("1") OR IS_BOOLEAN(1)"#,
            'b',
            "false",
        ),
        (r#"SQRT(81) + POWER(2, 3)"#, 'f', "17"),
        (r#"LN(1) + LOG10(1000) + EXP(0)"#, 'f', "4"),
        (r#"SAFE.LOG10(0)"#, 'n', ""),
        (r#"SAFE.SQRT(-1)"#, 'n', ""),
        (r#"SAFE.POWER(1e300, 2)"#, 'n', ""),
        (r#"BUCKET(-1, 5)"#, 'f', "-5"),
        (r#"BUCKET(12, 5, 2)"#, 'f', "12"),
        (r#"SAFE.BUCKET(1, 0)"#, 'n', ""),
    ]);
}

#[test]
fn date_and_timestamp_arithmetic_handles_calendar_and_epoch_edges() {
    check(&[
        (r#"DATE_FROM_PARTS(2000, 2, 29)"#, 'd', "2000-02-29"),
        (r#"SAFE.DATE_FROM_PARTS(1900, 2, 29)"#, 'n', ""),
        (
            r#"DATE_ADD_DAYS(DATE_PARSE("0001-01-01"), 3652058)"#,
            'd',
            "9999-12-31",
        ),
        (
            r#"DATE_ADD_DAYS(DATE_PARSE("9999-12-31"), -3652058)"#,
            'd',
            "0001-01-01",
        ),
        (
            r#"SAFE.DATE_ADD_DAYS(DATE_PARSE("0001-01-01"), -1)"#,
            'n',
            "",
        ),
        (
            r#"DATE_DIFF_DAYS(DATE_PARSE("2000-03-01"), DATE_PARSE("2000-02-28"))"#,
            'f',
            "-2",
        ),
        (r#"DATE_WEEKDAY(DATE_PARSE("1970-01-01"))"#, 'f', "4"),
        (r#"DATE_IS_WEEKEND(DATE_PARSE("2026-01-04"))"#, 'b', "true"),
        (
            r#"DATE_END_OF_MONTH(DATE_PARSE("2024-02-01"))"#,
            'd',
            "2024-02-29",
        ),
        (
            r#"DATE_ADD_MONTHS(DATE_PARSE("2025-01-31"), -2)"#,
            'd',
            "2024-11-30",
        ),
        (
            r#"DATE_ADD_MONTHS(DATE_PARSE("2024-01-31"), 1)"#,
            'd',
            "2024-02-29",
        ),
        (r#"DATE_ISO_WEEK(DATE_PARSE("2021-01-01"))"#, 'f', "53"),
        (r#"DATE_ISO_WEEK(DATE_PARSE("2018-12-31"))"#, 'f', "1"),
        (
            r#"DATE_ISO_WEEK_YEAR(DATE_PARSE("2018-12-31"))"#,
            'f',
            "2019",
        ),
        (
            r#"DATE_ISO_WEEK_YEAR(DATE_PARSE("2021-01-01"))"#,
            'f',
            "2020",
        ),
        (
            r#"TEXT(TIMESTAMP_FROM_UNIX(-0.125))"#,
            't',
            "1969-12-31T23:59:59.875Z",
        ),
        (
            r#"TIMESTAMP_TO_UNIX(TIMESTAMP_FROM_UNIX(-0.125))"#,
            'f',
            "-0.125",
        ),
        (
            r#"TIMESTAMP_DIFF_SECONDS(TIMESTAMP_PARSE("9999-12-30T23:59:59.999999999Z"), TIMESTAMP_PARSE("9999-12-31T01:00:00+01:00"))"#,
            'f',
            "0.000000001",
        ),
        (
            r#"TEXT(TIMESTAMP_PARSE("2024-02-27T23:30:00-01:00"))"#,
            't',
            "2024-02-28T00:30:00Z",
        ),
        (
            r#"TEXT(TIMESTAMP_TRUNC(TIMESTAMP_PARSE("2024-02-29T12:59:59.9Z"), "minute"))"#,
            't',
            "2024-02-29T12:59:00Z",
        ),
        (
            r#"TIMESTAMP_PARSE("2024-02-29T00:30:00+01:00") = TIMESTAMP_PARSE("2024-02-28T23:30:00Z")"#,
            'b',
            "true",
        ),
        (
            r#"TIMESTAMP_FORMAT(TIMESTAMP_ADD_SECONDS(TIMESTAMP_PARSE("2024-12-31T23:59:59.75+02:00"), 0.5), "%Y-%m-%d %H:%M:%S %z", "local")"#,
            't',
            "2025-01-01 00:00:00 +02:00",
        ),
        (
            r#"SAFE.TIMESTAMP_ADD_SECONDS(TIMESTAMP_PARSE("9999-12-31T23:59:59+02:00"), 1)"#,
            'n',
            "",
        ),
        (r#"SAFE.TIMESTAMP_FROM_UNIX(1e30)"#, 'n', ""),
    ]);
}

#[test]
fn stored_timestamp_keeps_its_local_offset_in_dependent_formulas() {
    let source = Expression::parse(r#"TIMESTAMP_PARSE("2024-02-29T00:30:00+01:00")"#).unwrap();
    let value = source.evaluate(&|_| None, &mut |_| Ok(())).unwrap();
    let kind = value.kind();
    let utc = value.rendered(&mut |_| Ok(())).unwrap();
    assert_eq!(utc, "2024-02-28T23:30:00Z");
    assert!(Value::from_stored(&utc, 'x').is_none());

    let mut dependent =
        Expression::parse(r#"TIMESTAMP_FORMAT($0, "%Y-%m-%d %H:%M %z", "local")"#).unwrap();
    dependent.bind(None, 1, 0).unwrap();
    let value = dependent
        .evaluate(
            &|index| {
                assert_eq!(index, 0);
                Value::from_stored(&utc, kind)
            },
            &mut |_| Ok(()),
        )
        .unwrap();
    assert_eq!(
        value.rendered(&mut |_| Ok(())).unwrap(),
        "2024-02-29 00:30 +01:00"
    );
}

#[test]
fn stored_boolean_keeps_its_type_and_rejects_invalid_values() {
    assert!(matches!(
        Value::from_stored("false", 'b'),
        Some(Value::Bool(false))
    ));
    assert!(matches!(
        Value::from_stored("true", 'b'),
        Some(Value::Bool(true))
    ));
    assert!(Value::from_stored("truthy", 'b').is_none());
}

#[test]
fn formula_size_limit_counts_utf8_bytes() {
    let mut source = format!("\"{}\"", "é".repeat(8191));
    assert!(Expression::parse(&source).is_ok());
    source.push(' ');
    assert!(Expression::parse(&source)
        .unwrap_err()
        .contains("exceeds 16384 bytes"));
}

#[test]
fn compiled_patterns_contribute_to_the_admitted_formula_workspace() {
    let short = r#"REGEX_MATCH("abc", "a")"#;
    let long = r#"REGEX_MATCH("abc", "abc")"#;
    let short_bytes = Expression::parse(short).unwrap().workspace_bytes();
    let long_bytes = Expression::parse(long).unwrap().workspace_bytes();
    assert!(short_bytes > 0 && long_bytes > short_bytes);
    let combined = Expression::parse(&format!("SAFE({short} AND {long})")).unwrap();
    assert_eq!(combined.workspace_bytes(), short_bytes + long_bytes);
    let argument_list = Expression::parse(&format!("IF({short}, {long}, FALSE)")).unwrap();
    assert_eq!(argument_list.workspace_bytes(), short_bytes + long_bytes);
    let membership = Expression::parse(&format!("{short} IN ({long})")).unwrap();
    assert_eq!(membership.workspace_bytes(), short_bytes + long_bytes);
}

#[test]
fn regex_extract_reuses_capture_semantics_and_binds_group_expressions() {
    check(&[
        (r#"REGEX_MATCH("-", "[a-]")"#, 'b', "true"),
        (r#"REGEX_MATCH("z", "[a-]")"#, 'b', "false"),
        (r#"REGEX_MATCH("_", "^\w$")"#, 'b', "true"),
        (r#"REGEX_MATCH("-", "^\w$")"#, 'b', "false"),
        (
            r#"REGEX_EXTRACT("é ABC-123 DEF-456", "([A-Z]+)-([0-9]+)")"#,
            't',
            "ABC-123",
        ),
        (
            r#"REGEX_EXTRACT("é ABC-123 DEF-456", "([A-Z]+)-([0-9]+)", 1+1)"#,
            't',
            "123",
        ),
        (r#"REGEX_EXTRACT("b", "(a)?b", 1)"#, 'n', ""),
        (r#"REGEX_EXTRACT("b", "z")"#, 'n', ""),
        (r#"REGEX_EXTRACT("b", "^")"#, 't', ""),
        (r#"SAFE.REGEX_EXTRACT("b", "(b)", 2)"#, 'n', ""),
    ]);
    assert!(Expression::parse(r#"SAFE.REGEX_EXTRACT("b", [pattern])"#).is_err());

    let mut expression = Expression::parse(r#"REGEX_EXTRACT("ab", "(a)(b)", [capture])"#).unwrap();
    expression.bind(Some(&["capture".into()]), 1, 0).unwrap();
    let value = expression
        .evaluate(&|_| Some(Value::Number(2.0)), &mut |_| Ok(()))
        .unwrap();
    assert_eq!(value.rendered(&mut |_| Ok(())).unwrap(), "b");
}

#[test]
fn is_error_reports_row_errors_without_catching_system_errors() {
    check(&[
        (r#"IS_ERROR(NUMBER("unknown"))"#, 'b', "true"),
        (r#"IS_ERROR(NUMBER("42"))"#, 'b', "false"),
        ("IS_ERROR(1 / 0)", 'b', "true"),
        ("IS_ERROR(NULL)", 'b', "false"),
        ("IS_ERROR(SAFE(1 / 0))", 'b', "false"),
        ("IF(IS_ERROR(1 / 0), 7, 1 / 0)", 'f', "7"),
    ]);
    assert!(Expression::parse("IS_ERROR(unknown_function())").is_err());
    let expression = Expression::parse(r#"IS_ERROR(REPEAT("x", 32))"#).unwrap();
    let error = expression
        .evaluate(&|_| None, &mut |_| Err("memory denied".into()))
        .unwrap_err();
    assert!(matches!(error, EvalError::System(_)));
}

#[test]
fn string_growth_is_checked_before_allocation_and_safe_propagates_resource_errors() {
    let overflow = Expression::parse(r#"SAFE.REPEAT("é", 1e30)"#).unwrap();
    let error = overflow
        .evaluate(&|_| None, &mut |_| {
            panic!("overflow must precede reservation")
        })
        .unwrap_err();
    assert!(matches!(error, EvalError::System(_)));

    for source in [
        r#"SAFE.REPEAT("é", 1000000)"#,
        r#"SAFE.LPAD("x", 1000000)"#,
        r#"SAFE.RPAD("x", 1000000)"#,
    ] {
        let expression = Expression::parse(source).unwrap();
        let error = expression
            .evaluate(&|_| None, &mut |bytes| {
                assert!(bytes >= 1000000, "{source}: {bytes}");
                Err("memory denied".into())
            })
            .unwrap_err();
        assert!(matches!(error, EvalError::System(_)), "{source}");
    }
}

#[test]
fn every_reference_function_names_its_arguments_and_shows_working_examples() {
    use chopper_core::expression::FUNCTIONS;
    let reference = include_str!("../../../docs/formula-functions.md");
    for (name, signature) in FUNCTIONS {
        let prefix = format!("| `{signature}` | ");
        let line = reference
            .lines()
            .find_map(|line| line.strip_prefix(&prefix))
            .unwrap_or_else(|| panic!("missing reference for {signature}"));
        let (behavior, examples) = line.strip_suffix(" |").unwrap().split_once(" | ").unwrap();
        for argument in signature[name.len() + 1..signature.len() - 1].split(", ") {
            let argument = argument.trim_end_matches('?');
            if argument != "..." {
                assert!(
                    behavior.contains(&format!("`{argument}`")),
                    "{signature}: {argument}"
                );
            }
        }
        for example in examples.split("<br>") {
            let (source, output) = example.split_once("` → `").unwrap();
            let source = source.strip_prefix('`').unwrap();
            let output = output.strip_suffix('`').unwrap();
            let expression =
                Expression::parse(source).unwrap_or_else(|error| panic!("{source}: {error}"));
            let value = expression
                .evaluate(&|_| None, &mut |_| Ok(()))
                .unwrap_or_else(|error| panic!("{source}: {error}"));
            let rendered = match &value {
                Value::Null => "NULL".into(),
                Value::Text(text) => serde_json::to_string(text).unwrap(),
                Value::Bool(value) => value.to_string().to_uppercase(),
                Value::Date(_) => format!("DATE {}", value.rendered(&mut |_| Ok(())).unwrap()),
                Value::Timestamp(_) => {
                    format!("TIMESTAMP {}", value.rendered(&mut |_| Ok(())).unwrap())
                }
                Value::Number(_) => value.rendered(&mut |_| Ok(())).unwrap().into_owned(),
            };
            assert_eq!(rendered, output, "{source}");
        }
    }
}

#[test]
fn type_diagnostics_suggest_the_matching_conversion() {
    for (source, expected) in [
        (
            r#""1" < 1000000"#,
            "Cannot compare text with a number. Use NUMBER(",
        ),
        (
            r#""2024-01-01" = DATE_FROM_PARTS(2024, 1, 1)"#,
            "Use DATE_PARSE(",
        ),
        (
            r#""1970-01-01T00:00:00Z" IN (TIMESTAMP_FROM_UNIX(0))"#,
            "Use TIMESTAMP_PARSE(",
        ),
        (r#"IF(1, "yes", "no")"#, "compare it to 0 with <>"),
        (r#"IF("yes", 1, 0)"#, "Compare the text explicitly"),
    ] {
        let expression = Expression::parse(source).unwrap();
        let error = expression.evaluate(&|_| None, &mut |_| Ok(())).unwrap_err();
        assert!(
            matches!(error, EvalError::Row(ref message) if message.contains(expected)),
            "{source}: {error}"
        );
    }
}
