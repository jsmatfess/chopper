use chopper_core::expression::{EvalError, Expression, Value, FUNCTIONS, MAX_SOURCE_BYTES};
use std::collections::BTreeMap;

type Cases<'a> = BTreeMap<&'a str, Vec<(String, String, String)>>;

fn check(source: &str, kind: &str, expected: &str) -> Result<(), String> {
    let expression = match Expression::parse(source) {
        Ok(_) if kind == "parse" => return Err(format!("accepted invalid formula {source}")),
        Ok(expression) => expression,
        Err(error) if kind == "parse" && error.contains(expected) => return Ok(()),
        Err(error) => {
            return Err(format!(
                "{source}: unexpected parse error {error:?}, wanted {kind} {expected:?}"
            ))
        }
    };
    let value = match expression.evaluate(&|_| None, &mut |_| Ok(())) {
        Ok(value) => value,
        Err(EvalError::Row(error)) if kind == "row" && error.contains(expected) => {
            let safe = Expression::parse(&format!("SAFE({source})"))?;
            if matches!(safe.evaluate(&|_| None, &mut |_| Ok(())), Ok(Value::Null)) {
                return Ok(());
            }
            return Err(format!(
                "{source}: SAFE did not produce null for a row error"
            ));
        }
        Err(error) => {
            return Err(format!(
                "{source}: unexpected {error:?}, wanted {kind} {expected:?}"
            ))
        }
    };
    let actual_kind = if matches!(value, Value::Timestamp(_)) {
        "timestamp".to_owned()
    } else {
        value.kind().to_string()
    };
    let rendered = value
        .rendered(&mut |_| Ok(()))
        .map_err(|error| error.to_string())?;
    if (actual_kind.as_str(), rendered.as_ref()) != (kind, expected) {
        return Err(format!(
            "{source}: got {actual_kind} {rendered:?}, wanted {kind} {expected:?}"
        ));
    }
    Ok(())
}

#[test]
fn every_catalog_function_has_adversarial_cases() {
    let cases: Cases<'_> =
        serde_json::from_str(include_str!("fixtures/formula-adversarial.json")).unwrap();
    let mut names: Vec<_> = FUNCTIONS.iter().map(|(name, _)| *name).collect();
    names.sort_unstable();
    assert_eq!(cases.keys().copied().collect::<Vec<_>>(), names);
    let mut failures = Vec::new();
    for (name, examples) in cases {
        assert!(examples.len() >= 4, "{name}");
        assert!(Expression::parse(&format!("{name}()")).is_err(), "{name}");
        for (arguments, kind, expected) in examples {
            let source = format!("{name}({arguments})");
            if let Err(error) = check(&source, &kind, &expected) {
                failures.push(error);
            }
        }
    }
    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

#[test]
fn extreme_formulas_reject_input_cleanly() {
    let oversize = format!("TEXT(\"{}\")", "x".repeat(MAX_SOURCE_BYTES));
    assert!(Expression::parse(&oversize).unwrap_err().contains("bytes"));
    let deeply_nested = format!("{}42{}", "ABS(".repeat(128), ")".repeat(128));
    assert!(Expression::parse(&deeply_nested)
        .unwrap_err()
        .contains("deeply nested"));
    let pattern = format!(
        "REGEX_MATCH(\"x\", \"{}x{}\")",
        "(?:".repeat(40),
        ")".repeat(40)
    );
    assert!(Expression::parse(&pattern)
        .unwrap_err()
        .contains("nested too deeply"));
    let captures = format!("REGEX_MATCH(\"x\", \"{}\")", "(x)".repeat(13));
    assert!(Expression::parse(&captures)
        .unwrap_err()
        .contains("12 numbered capture groups"));
    let expression = Expression::parse(r#"SAFE(REGEX_MATCH($0, "^(?:a|aa)+b$"))"#).unwrap();
    let mut expression = expression;
    expression.bind(None, 1, 1).unwrap();
    let input = "a".repeat(64 * 1024);
    let result = expression
        .evaluate(&|_| Some(Value::Text(input.as_str().into())), &mut |_| {
            Ok(())
        })
        .unwrap();
    assert!(matches!(result, Value::Bool(false)));
    let mut checks = 0;
    let error = expression
        .evaluate(&|_| Some(Value::Text(input.as_str().into())), &mut |_| {
            checks += 1;
            if checks == 2 {
                Err("stopped".into())
            } else {
                Ok(())
            }
        })
        .unwrap_err();
    assert!(matches!(error, EvalError::System(message) if message == "stopped"));
}
