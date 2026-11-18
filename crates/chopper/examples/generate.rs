//! Streaming fixture generator: cargo run --release --example generate -- output.csv rows payload_bytes
use anyhow::{ensure, Context, Result};
use std::io::{BufWriter, Write};
fn main() -> Result<()> {
    let args: Vec<_> = std::env::args().collect();
    ensure!(
        matches!(args.len(), 4 | 5),
        "usage: generate OUTPUT ROWS PAYLOAD_BYTES [EXTRA_COLUMNS]"
    );
    let rows: u64 = args[2].parse()?;
    let width: usize = args[3].parse()?;
    let columns: usize = args
        .get(4)
        .map(|value| value.parse())
        .transpose()?
        .unwrap_or(0);
    ensure!(columns <= 128, "extra columns must be at most 128");
    ensure!(
        width <= 16 * 1024 * 1024,
        "payload width exceeds generator budget"
    );
    let file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&args[1])
        .context("create new output")?;
    let mut writer = BufWriter::with_capacity(1024 * 1024, file);
    write!(writer, "id,country,segment,payload")?;
    for column in 0..columns {
        write!(writer, ",c{column}")?;
    }
    writeln!(writer)?;
    let mut payload = vec![b'x'; width];
    for row in 0..rows {
        let hash = blake3::hash(&row.to_le_bytes());
        for (index, byte) in payload.iter_mut().enumerate() {
            *byte = b'a' + hash.as_bytes()[index % 32] % 26;
        }
        write!(
            writer,
            "{row},{},{},",
            ["US", "GB", "DE", "CA", "FR", "JP", "AU"][row as usize % 7],
            row % 3
        )?;
        writer.write_all(&payload)?;
        for column in 0..columns {
            write!(writer, ",{}", (row % 10 + column as u64 % 10) % 10)?;
        }
        writer.write_all(b"\n")?;
    }
    writer.flush()?;
    Ok(())
}
