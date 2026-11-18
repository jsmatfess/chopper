//! The same configuration decoding reference runs on native and WASI.
use super::*;
#[derive(serde::Deserialize, serde::Serialize)]
#[serde(
    untagged,
    expecting = "data did not match any variant of untagged enum Column"
)]
enum LegacyColumn {
    Index(usize),
    Name(String),
}

pub(super) fn run() -> Result<serde_json::Value> {
    let mut cases: Vec<Vec<u8>> = [
        "0",
        "1",
        "4294967295",
        "4294967296",
        "18446744073709551615",
        "18446744073709551616",
        "-1",
        "-0",
        "0.0",
        "1e0",
        "null",
        "true",
        "false",
        "\"\"",
        "\"0\"",
        "\"01\"",
        "\"界é\\n\\u0000\"",
        "[]",
        "{}",
        "[1,2]",
        "{\"a\":1}",
        "[\"\\ud800\"]",
        "{\"a\":\"\\udc00\"}",
        "[tru]",
        "[1,]",
        "{\"a\":1,}",
        "[",
        "{",
        "\"\\ud800\"",
        "\"unterminated",
        "",
        "1 2",
    ]
    .into_iter()
    .map(|s| s.as_bytes().to_vec())
    .collect();
    cases.extend([
        vec![0xff],
        b"[\"\xff\"]".to_vec(),
        [vec![b'['; 127], b"0".to_vec(), vec![b']'; 127]].concat(),
        [vec![b'['; 128], b"0".to_vec(), vec![b']'; 128]].concat(),
    ]);
    let count = cases.len();
    let mut accepted = 0;
    for source in cases {
        match (
            serde_json::from_slice::<LegacyColumn>(&source),
            serde_json::from_slice::<chopper_core::Column>(&source),
        ) {
            (Ok(expected), Ok(actual)) => {
                ensure!(
                    serde_json::to_value(expected)? == serde_json::to_value(actual)?,
                    "column serialized value changed"
                );
                accepted += 1;
            }
            (Err(expected), Err(actual)) => ensure!(
                actual.to_string() == expected.to_string(),
                "column syntax/type error changed"
            ),
            _ => anyhow::bail!("column result changed"),
        }
    }
    let mut name = String::with_capacity(32768);
    name.push_str(&"\u{1}".repeat(16384));
    let pointer = name.as_ptr();
    let column: chopper_core::Column = serde_json::from_value(serde_json::Value::String(name))?;
    let chopper_core::Column::Name(name) = column else {
        anyhow::bail!("column name changed kind")
    };
    ensure!(
        name.as_ptr() == pointer && name.capacity() == 32768 && name.len() == 16384,
        "owned column name copied or resized"
    );
    Ok(
        serde_json::json!({"reference_json_cases":count,"accepted_cases":accepted,"usize_bits":usize::BITS,"legacy_values_and_errors_preserved":true,"owned_control_string_moved_without_copy":true,"numeric_string_remains_name":true}),
    )
}
