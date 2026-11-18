//! Bounded sniff samples and candidate parsing with live capacity ownership.
//! Returned JSON has a separate Inspection owner. Configuration, inline decoder
//! buffers and codec/runtime memory are not
//! covered by these heap working-capacity reservations.
use super::*;

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

const SAMPLE: usize = 65536;
const NOTE: &str = "Suggestion from at most 64 KiB. Review delimiter and encoding; header, quote and escape settings were preserved. Non-BOM encodings are assumed UTF-8.";

struct ChargedBytes {
    bytes: Vec<u8>,
    charge: Reservation,
}

impl ChargedBytes {
    fn read(mut source: impl Read, charge: Reservation, maximum: usize) -> Result<Self> {
        let mut owner = Self {
            bytes: Vec::new(),
            charge,
        };
        let mut chunk = [0u8; 8192];
        loop {
            let read = match source.read(&mut chunk) {
                Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
                result => result?,
            };
            if read == 0 {
                return Ok(owner);
            }
            let needed = owner
                .bytes
                .len()
                .checked_add(read)
                .context("inspection sample length overflow")?;
            ensure!(needed <= maximum, "inspection sample exceeds decoded bound");
            if needed > owner.bytes.capacity() {
                let capacity = needed
                    .max(owner.bytes.capacity().saturating_mul(2))
                    .min(maximum);
                owner.charge.reserve_vec(&mut owner.bytes, capacity)?;
            }
            owner.bytes.extend_from_slice(&chunk[..read]);
        }
    }
}

fn sample_settings(bytes: &mut [u8], settings: &mut CsvSettings) -> usize {
    settings.encoding = if bytes.starts_with(&[0xff, 0xfe]) {
        "utf-16le"
    } else if bytes.starts_with(&[0xfe, 0xff]) {
        "utf-16be"
    } else {
        "utf-8"
    }
    .into();
    settings.bom = bytes.starts_with(&[0xef, 0xbb, 0xbf])
        || bytes.starts_with(&[0xff, 0xfe])
        || bytes.starts_with(&[0xfe, 0xff]);
    let mut length = bytes.len();
    // Match the existing policy: only a full sample may trim an incomplete tail.
    if length == SAMPLE {
        if settings.encoding == "utf-8" {
            if let Err(error) = std::str::from_utf8(bytes) {
                if error.error_len().is_none() {
                    length = error.valid_up_to();
                }
            }
        } else {
            length &= !1;
            if length >= 2 {
                let tail = [bytes[length - 2], bytes[length - 1]];
                let unit = if settings.encoding == "utf-16le" {
                    u16::from_le_bytes(tail)
                } else {
                    u16::from_be_bytes(tail)
                };
                if (0xd800..=0xdbff).contains(&unit) {
                    length -= 2;
                }
            }
        }
    }
    length
}

struct Candidate<'a> {
    parser: Parser<std::io::Cursor<&'a [u8]>>,
    row: Vec<String>,
    done: bool,
    charge: Reservation,
}

impl<'a> Candidate<'a> {
    fn new(text: &'a str, settings: CsvSettings, charge: Reservation) -> Self {
        Self {
            parser: Parser::new(std::io::Cursor::new(text.as_bytes()), settings, SAMPLE),
            row: Vec::new(),
            done: false,
            charge,
        }
    }
    fn next(&mut self) -> Result<bool> {
        if self.done {
            return Ok(false);
        }
        let result = self
            .parser
            .next_record_into_reserved(&mut self.row, &mut |bytes| self.charge.resize(bytes));
        if !matches!(result, Ok(true)) {
            self.done = true;
        }
        result
    }
}

fn candidate_score(
    text: &str,
    settings: CsvSettings,
    charge: Reservation,
) -> Result<Option<(usize, usize)>> {
    let mut owner = Candidate::new(text, settings, charge);
    let mut first = None;
    let mut total = 0;
    let mut consistent = 0;
    while total < 50 {
        match owner.next() {
            Ok(true) => {
                let width = owner.row.len();
                let first_width = *first.get_or_insert(width);
                consistent += usize::from(width == first_width);
                total += 1;
            }
            Ok(false) => break,
            Err(error) => {
                // Syntax/record-limit errors retain their optional-sniff behavior.
                // Admission failure must never become a successful different guess.
                if error
                    .downcast_ref::<crate::resources::MemoryAdmission>()
                    .is_some()
                {
                    return Err(error);
                }
                break;
            }
        }
    }
    Ok(first.map(|width| {
        (
            if width > 1 && consistent * 10 >= total * 9 {
                consistent
            } else {
                0
            },
            width,
        )
    }))
}

pub(super) fn sniff(source: impl Read, job: &Job, charge: Reservation) -> Result<Inspection> {
    let mut raw = ChargedBytes::read(source.take(SAMPLE as u64), charge.sibling(), SAMPLE)?;
    let mut settings = job.input_csv.clone();
    let length = sample_settings(&mut raw.bytes, &mut settings);
    raw.bytes.truncate(length);
    // UTF-8 and UTF-16 inputs have at most three UTF-8 output bytes per source
    // byte. Both actual vectors remain charged during decoding and growth.
    let decoded = ChargedBytes::read(
        DecodeReader::new(raw.bytes.as_slice(), &settings.encoding)?,
        charge.sibling(),
        3 * SAMPLE,
    )?;
    drop(raw);
    let text = std::str::from_utf8(&decoded.bytes)?;
    settings.line_ending = if text.contains("\r\n") { "crlf" } else { "lf" }.into();
    let mut best = (0, 0);
    for delimiter in [',', '\t', ';', '|'] {
        let mut candidate = settings.clone();
        candidate.delimiter = delimiter;
        if let Some(score) = candidate_score(text, candidate, charge.sibling())? {
            if score.0 > 0 && score > best {
                best = score;
                settings.delimiter = delimiter;
            }
        }
    }
    Inspection::build(
        charge,
        0,
        NOTE.len() + 64,
        || json!({"settings": settings, "note": NOTE}),
    )
}
