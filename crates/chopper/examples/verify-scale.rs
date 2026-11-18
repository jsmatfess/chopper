//! Exact conservation checker for `generate OUTPUT ROWS 0` plain CSV outputs.
//! Retains one bit per source ID, never a set of strings or the output payload.
use anyhow::{ensure, Context, Result};
use chopper::core::{
    csv::{CompactRecord, Parser},
    CsvSettings,
};
use std::{
    fs::File,
    io::{BufRead, BufReader, Read},
    path::Path,
};

struct Hashed<R> {
    inner: R,
    hash: blake3::Hasher,
}
impl<R: Read> Read for Hashed<R> {
    fn read(&mut self, bytes: &mut [u8]) -> std::io::Result<usize> {
        let count = self.inner.read(bytes)?;
        self.hash.update(&bytes[..count]);
        Ok(count)
    }
}
fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(args.len() == 3, "usage: verify-scale OUTPUT_DIRECTORY ROWS");
    let directory = Path::new(&args[1]);
    let expected: u64 = args[2].parse()?;
    let bytes = usize::try_from(expected.checked_add(7).context("ID range overflow")? / 8)?;
    let mut seen = Vec::new();
    seen.try_reserve_exact(bytes)?;
    seen.resize(bytes, 0u8);
    let mut total = 0u64;
    let mut files = Vec::new();
    for line in BufReader::new(File::open(directory.join("manifest.jsonl"))?).lines() {
        let entry: serde_json::Value = serde_json::from_str(&line?)?;
        if entry["type"] != "output" {
            continue;
        }
        let name = entry["path"].as_str().context("missing output path")?;
        ensure!(
            Path::new(name).components().count() == 1 && name.ends_with(".csv"),
            "expected plain CSV leaf"
        );
        let mut input = Hashed {
            inner: File::open(directory.join(name))?,
            hash: blake3::Hasher::new(),
        };
        let mut parser = Parser::new(
            BufReader::with_capacity(65536, &mut input),
            CsvSettings::default(),
            1048576,
        );
        let header = parser.next_record()?.context("missing header")?;
        ensure!(
            header == ["id", "country", "segment", "payload"],
            "unexpected header"
        );
        let mut record = CompactRecord::default();
        let mut rows = 0u64;
        while parser.next_compact_record_into(&mut record)? {
            let mut fields = record.fields();
            let id_text = fields.next().context("missing ID")?;
            ensure!(
                !id_text.is_empty()
                    && id_text.bytes().all(|b| b.is_ascii_digit())
                    && (id_text.len() == 1 || !id_text.starts_with('0')),
                "noncanonical ID text"
            );
            let id: u64 = id_text.parse()?;
            ensure!(id < expected, "out-of-range ID {id}");
            let index = usize::try_from(id / 8)?;
            let mask = 1u8 << (id % 8);
            ensure!(seen[index] & mask == 0, "duplicate ID {id}");
            seen[index] |= mask;
            ensure!(
                fields.next()
                    == Some(["US", "GB", "DE", "CA", "FR", "JP", "AU"][(id % 7) as usize]),
                "wrong country for ID {id}"
            );
            let segment = fields.next().context("missing segment")?;
            ensure!(
                segment.as_bytes() == [b'0' + (id % 3) as u8],
                "wrong segment for ID {id}"
            );
            ensure!(
                fields.next() == Some("") && fields.next().is_none(),
                "unexpected payload/width for ID {id}"
            );
            rows += 1;
        }
        drop(parser);
        ensure!(
            entry["rows"].as_u64() == Some(rows),
            "manifest row mismatch"
        );
        let size = std::fs::metadata(directory.join(name))?.len();
        ensure!(
            entry["csv_bytes"].as_u64() == Some(size),
            "manifest byte mismatch"
        );
        total = total.checked_add(rows).context("row total overflow")?;
        files.push(serde_json::json!({"path":name,"rows":rows,"bytes":size,"lineage":entry["lineage"],"blake3":input.hash.finalize().to_hex().to_string()}));
    }
    ensure!(
        total == expected,
        "missing IDs: expected {expected}, found {total}"
    );
    // Range + no duplicates + exact count establishes every ID occurs once.
    println!(
        "{}",
        serde_json::json!({"rows":total,"id_bitset_bytes":seen.len(),"files":files,"verified":true})
    );
    Ok(())
}
