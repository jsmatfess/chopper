#![cfg(not(target_os = "wasi"))]

use chopper::{
    formula::{col, functions as f, lit, null, parse, Expr},
    job::{Job, JobSettings},
};
use std::fs;

#[test]
fn expressions_preserve_literals_references_and_existing_formula_text() -> anyhow::Result<()> {
    assert_eq!(col(0).as_str(), "$0");
    assert_eq!(col("0").as_str(), "[0]");
    assert_eq!(col("a]b").as_str(), "[a]]b]");
    assert_eq!(lit("a\"b").as_str(), "\"a\"\"b\"");
    assert_eq!(null().as_str(), "NULL");
    assert_eq!(f::round(lit(2.25), Some(lit(1))).as_str(), "ROUND(2.25, 1)");
    assert_eq!(f::round(2.25, None).as_str(), "ROUND(2.25)");
    assert!(parse("1 +").is_err());
    assert!(parse(lit(f64::INFINITY).as_str()).is_err());
    assert_eq!(parse("upper([country])")?.as_str(), "upper([country])");
    assert_eq!(
        "upper([country])".parse::<Expr>()?,
        parse("upper([country])")?
    );
    Ok(())
}

#[test]
fn composed_arithmetic_preserves_grouping_without_extra_depth() -> anyhow::Result<()> {
    let sum = (0..64)
        .map(|index| f::number(col(index)))
        .reduce(|left, right| left + right)
        .unwrap();
    parse(sum.as_str())?;
    assert_eq!((lit(1) - (lit(2) - 3)).as_str(), "1 - (2 - 3)");
    assert_eq!((lit(1) + lit(2) * 3).as_str(), "1 + 2 * 3");
    assert_eq!((parse("1 + 2")? * 3).as_str(), "(1 + 2) * 3");
    let condition = !(lit(false) | true) & true;
    assert_eq!(condition.as_str(), "NOT (FALSE OR TRUE) AND TRUE");
    assert_eq!(lit(false).or(true).not().and(true), condition);
    Ok(())
}

#[test]
fn numeric_literals_keep_extreme_finite_values_compact() -> anyhow::Result<()> {
    let expression = f::coalesce(std::iter::repeat_with(|| lit(f64::MIN_POSITIVE)).take(64));
    parse(expression.as_str())?;
    assert_eq!(lit(2.25).as_str(), "2.25");
    Ok(())
}

#[test]
fn remainder_and_comparisons_preserve_grouping_and_expression_equality() -> anyhow::Result<()> {
    let amount = f::number(col(0));
    let condition = (amount.clone() % 3).equal(1).and(amount.ge(0));
    assert_eq!(condition.as_str(), "NUMBER($0) % 3 = 1 AND NUMBER($0) >= 0");
    assert_eq!(lit(11).not_equal(lit(5) % 3).as_str(), "11 != 5 % 3");
    assert_eq!((lit(11) % (lit(5) % 3)).as_str(), "11 % (5 % 3)");
    assert_eq!(lit(true).equal(lit(10).gt(5)).as_str(), "TRUE = (10 > 5)");
    assert_eq!(lit(10).lt(5).not().as_str(), "NOT 10 < 5");
    assert_eq!(lit(false).not().le(true).as_str(), "(NOT FALSE) <= TRUE");
    assert!(lit(1).eq(&parse("1")?));
    assert!(lit(1).ne(&lit(2)));
    Ok(())
}

#[test]
fn composed_formulas_bind_numeric_selectors_in_headered_and_headerless_jobs() -> anyhow::Result<()>
{
    let root = tempfile::tempdir()?;
    for (name, input, headers, reference, expected) in [
        (
            "headerless",
            "3,us\n7,gb\n1,\n",
            false,
            col(0),
            "3,us,9,US,10,true\n7,gb,21,GB,22,true\n1,\"\",3,missing,4,false\n",
        ),
        (
            "named-zero",
            "id,0\n3,7\n",
            true,
            col("0"),
            "3,7,21,7,22,true\n",
        ),
    ] {
        let source = root.path().join(format!("{name}.csv"));
        let destination = root.path().join(name);
        fs::write(&source, input)?;
        let mut settings =
            JobSettings::for_files(source.to_str().unwrap(), destination.to_str().unwrap());
        settings.input_csv.headers = headers;
        settings.output_csv.headers = false;
        let value = f::number(reference);
        settings.calculated_columns = vec![
            (parse("1 + 2")? * &value).alias("triple"),
            f::if_else(
                !(f::is_blank(col(1)) | f::is_null(col(1))) & f::is_text(col(1)),
                f::upper(f::trim(col(1))),
                "missing",
            )
            .alias("label"),
            (col("triple") + 1).alias("next"),
            (value.clone() % 2)
                .equal(1)
                .and(value.ge(3))
                .alias("qualifies"),
        ];
        let job = Job::new(settings);
        job.validate()?;
        let saved = root.path().join(format!("{name}.json"));
        job.save(&saved)?;
        let report = Job::load(&saved)?.run()?;
        let outputs = report.outputs()?.collect::<Result<Vec<_>, _>>()?;
        assert_eq!(outputs.len(), 1);
        let output = fs::read_to_string(destination.join(&outputs[0].path))?;
        assert_eq!(output.replace("\r\n", "\n"), expected);
    }
    Ok(())
}
