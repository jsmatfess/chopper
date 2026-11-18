use anyhow::{Context, Result};
use chopper_core::{
    csv::{CompactRecord, DecodeReader, Parser},
    CsvSettings,
};
use std::{fs::File, io::BufReader, time::Instant};
fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    let mode = args.get(1).context("mode")?;
    let path = args.get(2).context("input")?;
    let started = Instant::now();
    let reader = DecodeReader::new(File::open(path)?, "utf-8")?;
    let mut parser = Parser::new(
        BufReader::with_capacity(65536, reader),
        CsvSettings::default(),
        1048576,
    );
    let mut peak = 0;
    let mut reserve = |n| {
        peak = peak.max(n);
        Ok(())
    };
    let (mut rows, mut count, mut payload, mut checksum) = (0u64, 0u64, 0u64, 0u64);
    match mode.as_str() {
        "owned" => {
            let mut fields = Vec::new();
            while parser.next_record_into_reserved(&mut fields, &mut reserve)? {
                rows += 1;
                for field in &fields {
                    count += 1;
                    payload += field.len() as u64;
                    checksum = checksum.wrapping_add(
                        field.len() as u64
                            + u64::from(field.as_bytes().first().copied().unwrap_or(0)),
                    );
                }
            }
        }
        "compact" => {
            let mut record = CompactRecord::default();
            while parser.next_compact_record_into_reserved(&mut record, &mut reserve)? {
                rows += 1;
                for field in record.fields() {
                    count += 1;
                    payload += field.len() as u64;
                    checksum = checksum.wrapping_add(
                        field.len() as u64
                            + u64::from(field.as_bytes().first().copied().unwrap_or(0)),
                    );
                }
            }
        }
        _ => anyhow::bail!("unsupported mode"),
    }
    println!(
        "{}",
        serde_json::json!({"mode":mode,"rows_including_header":rows,"fields":count,"payload_bytes":payload,"checksum":checksum,"modeled_parser_capacity_peak":peak,"seconds":started.elapsed().as_secs_f64(),"scope":"File open/decode/admitted parse/field length+firstbyte counters through EOF; excludes process startup. Capacity callback always accepts; modeled parser grants only, not RSS or engine peak."})
    );
    Ok(())
}
