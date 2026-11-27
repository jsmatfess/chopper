use anyhow::{ensure, Context, Result};
use chopper::core::{
    csv::{CompactRecord, DecodeReader, DialectParser, Parser},
    Column, CsvSettings, Grouping, InputDialect, Job, Operation, Resources,
};
use serde::Deserialize;
use serde_json::Value;
use std::{
    fs::{self, File},
    io::{BufReader, BufWriter, Read, Write},
    path::{Path, PathBuf},
    process::Command,
};

type Rows = Vec<Vec<String>>;
const FIXTURES: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/tests/fixtures/csv-compatibility"
);
const CORPORA: [(&str, &str); 3] = [
    (
        "Local",
        include_str!("fixtures/csv-compatibility/local.json"),
    ),
    ("CSVW", include_str!("fixtures/csv-compatibility/csvw.json")),
    ("Go", include_str!("fixtures/csv-compatibility/go.json")),
];

#[derive(Deserialize)]
#[serde(untagged)]
enum Input {
    Text(String),
    Bytes(Vec<u8>),
    Fixture { file: PathBuf },
}

impl Input {
    fn bytes(&self) -> Result<Vec<u8>> {
        match self {
            Self::Text(text) => Ok(text.as_bytes().to_vec()),
            Self::Bytes(bytes) => Ok(bytes.clone()),
            Self::Fixture { file } => {
                let path = Path::new(FIXTURES).join(file);
                fs::read(&path).with_context(|| format!("read fixture {}", path.display()))
            }
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Case {
    name: String,
    input: Input,
    input_csv: CsvSettings,
    #[serde(default)]
    input_dialect: InputDialect,
    #[serde(default = "record_limit")]
    max_record_bytes: usize,
    expected: Expected,
    #[serde(default)]
    upstream_difference: Option<String>,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Expected {
    Rows {
        header: Option<Vec<String>>,
        rows: Rows,
    },
    Rejected {
        error: String,
        parsed: Option<Rows>,
    },
    Unsupported {
        error: String,
    },
}

fn record_limit() -> usize {
    1024 * 1024
}

// Limit source reads before decoding as well as parser refills after decoding.
struct Fragmented<'a> {
    bytes: &'a [u8],
    limit: usize,
}

impl Read for Fragmented<'_> {
    fn read(&mut self, output: &mut [u8]) -> std::io::Result<usize> {
        let size = output.len().min(self.limit);
        self.bytes.read(&mut output[..size])
    }
}

fn parse(
    raw: &[u8],
    settings: &CsvSettings,
    dialect: &InputDialect,
    maximum: usize,
    (source_read, parser_read): (usize, usize),
    compact: bool,
) -> Result<Rows> {
    let source = Fragmented {
        bytes: raw,
        limit: source_read,
    };
    let decoded = DecodeReader::new(source, &settings.encoding)?;
    let parser = Parser::new(
        BufReader::with_capacity(parser_read, decoded),
        settings.clone(),
        maximum,
    );
    macro_rules! collect {
        ($parser:expr) => {{
            let mut parser = $parser;
            let mut rows = Vec::new();
            if compact {
                let mut record = CompactRecord::default();
                while parser.next_compact_record_into_reserved(&mut record, &mut |_| Ok(()))? {
                    rows.push(record.fields().map(str::to_owned).collect());
                }
            } else {
                let mut fields = Vec::new();
                while parser.next_record_into_reserved(&mut fields, &mut |_| Ok(()))? {
                    rows.push(fields.clone());
                }
            }
            Ok(rows)
        }};
    }
    if dialect.is_default() {
        collect!(parser)
    } else {
        collect!(DialectParser::new(parser, dialect))
    }
}

fn check_core(case: &Case, raw: &[u8]) -> Result<()> {
    let mut expected_header_and_rows = Vec::new();
    let (want_rows, want_error) = match &case.expected {
        Expected::Rows { header, rows } => {
            expected_header_and_rows.extend(header.iter().cloned());
            expected_header_and_rows.extend(rows.iter().cloned());
            (Some(&expected_header_and_rows), None)
        }
        // Width belongs to engine intake. The core test checks all lexical fields.
        Expected::Rejected {
            parsed: Some(rows), ..
        } => (Some(rows), None),
        Expected::Rejected {
            error,
            parsed: None,
        } => (None, Some(error.as_str())),
        // Run validates unsupported settings before invoking the parser.
        Expected::Unsupported { .. } => return Ok(()),
    };
    let full = (8192, 65536);
    let read_sizes: &[(usize, usize)] = if raw.len() < 1024 {
        &[full, (1, full.1), (full.0, 1), (1, 1)]
    } else {
        &[full]
    };
    for &sizes in read_sizes {
        for compact in [false, true] {
            let actual = parse(
                raw,
                &case.input_csv,
                &case.input_dialect,
                case.max_record_bytes,
                sizes,
                compact,
            );
            if let Some(rows) = want_rows {
                let actual = actual
                    .with_context(|| format!("core parse, reads {sizes:?}, compact={compact}"))?;
                ensure!(
                    actual == *rows,
                    "core fields or row count differ, reads {sizes:?}, compact={compact}"
                );
            } else {
                let wanted = want_error.unwrap();
                let error = actual
                    .err()
                    .context("core accepted input expected to fail")?;
                ensure!(
                    format!("{error:#}").contains(wanted),
                    "expected core error {wanted:?}, got {error:#}"
                );
            }
        }
    }
    Ok(())
}

fn make_job(dir: &Path, input_csv: CsvSettings) -> Result<Job> {
    let temp_dir = dir.join("temp");
    fs::create_dir(&temp_dir)?;
    Ok(Job {
        input: dir.join("input.csv").to_string_lossy().into_owned(),
        output: dir.join("out").to_string_lossy().into_owned(),
        output_csv: CsvSettings {
            headers: input_csv.headers,
            ..CsvSettings::default()
        },
        input_csv,
        resources: Resources {
            memory_mb: 32.into(),
            workers: 1,
            max_record_bytes: record_limit(),
            temp_dir: Some(temp_dir.to_string_lossy().into_owned()),
            ..Resources::default()
        },
        ..Job::default()
    })
}

fn run_cli(job: &Job, dir: &Path) -> Result<std::process::Output> {
    let path = dir.join("job.json");
    fs::write(&path, serde_json::to_vec(job)?)?;
    let result = Command::new(env!("CARGO_BIN_EXE_chopper"))
        .args(["run", "--config"])
        .arg(path)
        .args(["--yes", "--summary"])
        .output()?;
    ensure!(
        dir.join("temp").read_dir()?.next().is_none(),
        "Run retained temporary files"
    );
    Ok(result)
}

fn read_export(
    job: &Job,
    header: Option<&[String]>,
    partition_column: Option<usize>,
) -> Result<(Rows, Value)> {
    let output = Path::new(&job.output);
    let manifest = fs::read_to_string(output.join("manifest.jsonl"))?;
    let mut entries = manifest.lines().map(serde_json::from_str::<Value>);
    let first = entries.next().context("empty manifest")??;
    ensure!(first["type"] == "job", "expected manifest Job record");
    let analysis = &first["analysis"];
    ensure!(
        analysis["header"] == serde_json::to_value(header)?,
        "manifest header differs"
    );
    let mut rows = Vec::new();
    let mut files = 0;
    let mut bytes = 0;
    for entry in entries {
        let entry = entry?;
        ensure!(entry["type"] == "output", "expected manifest output record");
        let path = entry["path"]
            .as_str()
            .context("missing manifest output path")?;
        let data = fs::read(output.join(path))?;
        let mut fields = parse(
            &data,
            &job.output_csv,
            &InputDialect::default(),
            usize::MAX,
            (8192, 65536),
            false,
        )?;
        if let Some(header) = header {
            ensure!(
                fields.first().map(Vec::as_slice) == Some(header),
                "chunk header differs for {path}"
            );
            fields.remove(0);
        }
        ensure!(
            entry["rows"].as_u64() == Some(fields.len() as u64),
            "chunk row count differs for {path}"
        );
        ensure!(
            entry["csv_bytes"].as_u64() == Some(data.len() as u64),
            "chunk byte count differs for {path}"
        );
        ensure!(
            job.limits.rows.is_none_or(|cap| fields.len() as u64 <= cap),
            "chunk exceeds row cap"
        );
        if let Some(column) = partition_column {
            let key = entry["lineage"][0]["values"][0]
                .as_str()
                .with_context(|| format!("missing partition key for {path}"))?;
            ensure!(
                fields
                    .iter()
                    .all(|row| row.get(column).map(String::as_str) == Some(key)),
                "{path} contains a row outside its partition {key:?}"
            );
        }
        files += 1;
        bytes += data.len();
        rows.extend(fields);
    }
    ensure!(
        analysis["rows"].as_u64() == Some(rows.len() as u64),
        "manifest total rows differs"
    );
    ensure!(
        analysis["output_files"].as_u64() == Some(files),
        "manifest file count differs"
    );
    ensure!(
        analysis["output_csv_bytes"].as_u64() == Some(bytes as u64),
        "manifest byte count differs"
    );
    ensure!(
        output.read_dir()?.count() == files as usize + 1,
        "unlisted output files"
    );
    Ok((rows, analysis.clone()))
}

fn check_case(case: &Case) -> Result<()> {
    let raw = case.input.bytes()?;
    check_core(case, &raw)?;
    let dir = tempfile::tempdir()?;
    let mut job = make_job(dir.path(), case.input_csv.clone())?;
    job.input_dialect = case.input_dialect.clone();
    job.resources.max_record_bytes = case.max_record_bytes;
    job.limits.rows = Some(2);
    fs::write(&job.input, raw)?;
    let result = run_cli(&job, dir.path())?;
    let stderr = String::from_utf8_lossy(&result.stderr);
    match &case.expected {
        Expected::Rows { header, rows } => {
            ensure!(result.status.success(), "Run failed: {stderr}");
            let (actual, _) = read_export(&job, header.as_deref(), None)?;
            ensure!(actual == *rows, "exported fields or row count differ");
        }
        Expected::Rejected { error, .. } | Expected::Unsupported { error } => {
            ensure!(
                !result.status.success() && stderr.contains(error),
                "expected Run error {error:?}, got {stderr}"
            );
            ensure!(
                !Path::new(&job.output).exists(),
                "rejected input published output"
            );
        }
    }
    Ok(())
}

fn long_sample() -> Case {
    let name = "x".repeat(65536);
    Case {
        name: "delimiter-beyond-sniff-sample".into(),
        input: Input::Text(format!("{name};note\n1;a\n")),
        input_csv: CsvSettings {
            delimiter: ';',
            ..CsvSettings::default()
        },
        input_dialect: InputDialect::default(),
        max_record_bytes: record_limit(),
        expected: Expected::Rows {
            header: Some(vec![name, "note".into()]),
            rows: vec![vec!["1".into(), "a".into()]],
        },
        upstream_difference: None,
    }
}

#[test]
fn csv_compatibility() -> Result<()> {
    let mut report = String::from("\nCSV compatibility (explicit settings)\n");
    let mut failures = Vec::new();
    for (corpus, json) in CORPORA {
        let mut cases: Vec<Case> = serde_json::from_str(json)?;
        if corpus == "Local" {
            cases.push(long_sample());
        }
        let (mut matched, mut rejected, mut unsupported, mut differences, mut unexpected) =
            (0, 0, 0, 0, 0);
        for case in &cases {
            if let Err(error) = check_case(case) {
                unexpected += 1;
                failures.push(format!("{corpus}/{}: {error:#}", case.name));
                continue;
            }
            match &case.expected {
                Expected::Rows { .. } => matched += 1,
                Expected::Rejected { .. } => rejected += 1,
                Expected::Unsupported { .. } => unsupported += 1,
            }
            differences += usize::from(case.upstream_difference.is_some());
        }
        use std::fmt::Write as _;
        writeln!(
            report,
            "{corpus}: {matched} exact matches, {rejected} expected rejections, {unsupported} unsupported, {unexpected} unexpected ({differences} documented upstream differences)"
        )?;
        for case in &cases {
            if let Some(difference) = &case.upstream_difference {
                writeln!(report, "  {}: {difference}", case.name)?;
            }
        }
    }
    // Write directly to keep the summary visible in the ordinary gate logs.
    std::io::stdout().lock().write_all(report.as_bytes())?;
    ensure!(
        failures.is_empty(),
        "CSV compatibility failures:\n{}",
        failures.join("\n")
    );
    Ok(())
}

#[test]
fn csv_compatibility_forced_spill() -> Result<()> {
    let dir = tempfile::tempdir()?;
    let mut job = make_job(
        dir.path(),
        CsvSettings {
            delimiter: ';',
            ..CsvSettings::default()
        },
    )?;
    job.resources.grouping = Grouping::Sort;
    job.operations = vec![Operation::Partition {
        columns: vec![Column::Name("key".into())],
    }];
    job.input_dialect.comment_prefix = Some("#".into());
    job.limits.rows = Some(10000);
    let mut input = BufWriter::new(File::create(&job.input)?);
    writeln!(input, "# generated test input\nid;key;payload")?;
    let payload = "界".repeat(126);
    let mut expected = Vec::with_capacity(40000);
    for n in 0..40000 {
        let id = n / 2;
        let key = id % 3;
        let digit = id % 2;
        writeln!(input, "{id};{key};\"café \"\"{digit}\"\"\r\n{payload}\"")?;
        expected.push(vec![
            id.to_string(),
            key.to_string(),
            format!("café \"{digit}\"\r\n{payload}"),
        ]);
    }
    input.flush()?;
    drop(input);
    let result = run_cli(&job, dir.path())?;
    ensure!(
        result.status.success(),
        "forced-spill Run failed: {}",
        String::from_utf8_lossy(&result.stderr)
    );
    let header = ["id".into(), "key".into(), "payload".into()];
    let (mut rows, analysis) = read_export(&job, Some(&header), Some(1))?;
    let spills = analysis["diagnostics"]["sort_runs"]
        .as_u64()
        .context("missing sort diagnostics")?;
    ensure!(spills > 0, "fixture did not spill");
    rows.sort_unstable();
    expected.sort_unstable();
    ensure!(
        rows == expected,
        "forced spill changed fields or row multiplicities"
    );
    writeln!(
        std::io::stdout().lock(),
        "CSV compatibility spill: {} rows, {spills} sort runs, exact multiset",
        rows.len()
    )?;
    Ok(())
}
