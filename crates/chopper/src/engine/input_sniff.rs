//! Bounded sniff samples and candidate parsing with live capacity ownership.
//! Returned JSON has a separate Inspection owner. Configuration, inline decoder
//! buffers and codec/runtime memory are not
//! covered by these heap working-capacity reservations.
use super::*;
use std::{cell::Cell, io::BufRead};

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) mod resource_contracts;

const SAMPLE: usize = 65536;
const NOTE: &str = "Suggestion from at most 64 KiB. Review delimiter and encoding. Without a byte-order mark, Sniff uses the selected encoding.";
const AMBIGUOUS: &str = "More than one delimiter fits this sample. The current delimiter was kept. Check the file and select its delimiter.";
const NO_MATCH: &str =
    "No delimiter produced a consistent multi-column sample. The current delimiter was kept.";

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

fn sample_settings(bytes: &[u8], settings: &mut CsvSettings) -> Result<()> {
    ensure!(
        !bytes.starts_with(&[0x00, 0x00, 0xfe, 0xff]),
        "sample has a UTF-32BE byte-order mark. Convert the input to a supported encoding"
    );
    if bytes.starts_with(&[0xff, 0xfe, 0x00, 0x00]) {
        ensure!(
            chopper_core::csv::encoding(&settings.encoding)?.name() == "UTF-16LE",
            "sample could be UTF-32LE or UTF-16LE starting with NUL. UTF-32 is unsupported. Select UTF-16LE explicitly if that is the input encoding"
        );
    }
    let bom_encoding = if bytes.starts_with(&[0xff, 0xfe]) {
        Some("utf-16le")
    } else if bytes.starts_with(&[0xfe, 0xff]) {
        Some("utf-16be")
    } else if bytes.starts_with(&[0xef, 0xbb, 0xbf]) {
        Some("utf-8")
    } else {
        None
    };
    settings.bom = bom_encoding.is_some();
    if let Some(encoding) = bom_encoding {
        settings.encoding = encoding.into();
    } else if chopper_core::csv::encoding(&settings.encoding)?.name() == "UTF-8"
        && bytes.contains(&0)
    {
        let mut zero = [0, 0];
        for pair in bytes.as_chunks::<2>().0 {
            zero[0] += usize::from(pair[0] == 0);
            zero[1] += usize::from(pair[1] == 0);
        }
        let minimum = (bytes.len() / 4).max(3);
        let encoding = match zero {
            [0, odd] if odd >= minimum => Some("UTF-16LE"),
            [even, 0] if even >= minimum => Some("UTF-16BE"),
            _ => None,
        };
        if let Some(encoding) = encoding {
            anyhow::bail!("sample looks like {encoding} without a byte-order mark; select the input encoding explicitly");
        }
    }
    Ok(())
}

struct Candidate<P> {
    parser: P,
    row: Vec<String>,
    done: bool,
    charge: Reservation,
}

impl<P: records::Records> Candidate<P> {
    fn new(parser: P, charge: Reservation) -> Self {
        Self {
            parser,
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

struct Sample<'a> {
    bytes: &'a [u8],
    remaining: Cell<&'a [u8]>,
    reached_end: Cell<bool>,
    capped: bool,
}

struct SampleReader<'a>(&'a Sample<'a>);

impl Read for SampleReader<'_> {
    fn read(&mut self, out: &mut [u8]) -> std::io::Result<usize> {
        let read = self.fill_buf()?.read(out)?;
        self.consume(read);
        Ok(read)
    }
}

impl BufRead for SampleReader<'_> {
    fn fill_buf(&mut self) -> std::io::Result<&[u8]> {
        let bytes = self.0.remaining.get();
        if bytes.is_empty() {
            self.0.reached_end.set(true);
        }
        Ok(bytes)
    }

    fn consume(&mut self, count: usize) {
        self.0.remaining.set(&self.0.remaining.get()[count..]);
    }
}

#[derive(Default)]
struct SampleScore {
    consistent: usize,
    line_ending: Option<&'static str>,
}

fn candidate_score(
    bytes: &[u8],
    capped: bool,
    settings: CsvSettings,
    dialect: &chopper_core::InputDialect,
    charge: Reservation,
) -> Result<SampleScore> {
    let sample = Sample {
        bytes,
        remaining: Cell::new(bytes),
        reached_end: Cell::new(false),
        capped,
    };
    let parser = Parser::new(SampleReader(&sample), settings, SAMPLE);
    if dialect.is_default() {
        score(Candidate::new(parser, charge), &sample, 0)
    } else {
        score(
            Candidate::new(
                chopper_core::csv::DialectParser::new(parser, dialect),
                charge,
            ),
            &sample,
            dialect.skip_columns,
        )
    }
}

fn score(
    mut owner: Candidate<impl records::Records>,
    sample: &Sample<'_>,
    skipped_columns: usize,
) -> Result<SampleScore> {
    let mut first = None;
    let mut total = 0;
    let mut consistent = 0;
    let (mut lf, mut crlf) = (false, false);
    while total < 50 {
        match owner.next() {
            // A byte-capped tail can look like a valid unterminated final
            // record even when only a prefix of that record was sampled.
            Ok(true) if sample.capped && sample.reached_end.get() => break,
            Ok(true) => {
                let consumed = sample.bytes.len() - sample.remaining.get().len();
                match &sample.bytes[..consumed] {
                    [.., b'\r', b'\n'] => crlf = true,
                    [.., b'\n'] => lf = true,
                    _ => {}
                }
                let width = owner.row.len() + skipped_columns;
                let first_width = *first.get_or_insert(width);
                consistent += usize::from(width == first_width);
                total += 1;
            }
            Ok(false) => break,
            Err(error) => {
                if error
                    .downcast_ref::<crate::resources::MemoryAdmission>()
                    .is_some()
                {
                    return Err(error);
                }
                // An open field or split CRLF at the byte cap is expected.
                if sample.capped && sample.reached_end.get() {
                    break;
                }
                return Ok(SampleScore::default());
            }
        }
    }
    Ok(SampleScore {
        consistent: if first.unwrap_or(0) > 1 && consistent >= 2 && consistent * 10 >= total * 9 {
            consistent
        } else {
            0
        },
        line_ending: match (lf, crlf) {
            (true, false) => Some("lf"),
            (false, true) => Some("crlf"),
            _ => None,
        },
    })
}

pub(super) fn sniff(source: impl Read, job: &Job, charge: Reservation) -> Result<Inspection> {
    let raw = ChargedBytes::read(source.take(SAMPLE as u64), charge.sibling(), SAMPLE)?;
    let sample_bytes = raw.bytes.len();
    let capped = sample_bytes == SAMPLE;
    let mut settings = job.input_csv.clone();
    sample_settings(&raw.bytes, &mut settings)?;
    // The supported encodings expand to at most three UTF-8 bytes per source
    // byte. Keep both vectors charged while the decoder produces the sample.
    let decoder = DecodeReader::new(raw.bytes.as_slice(), &settings.encoding)?;
    let decoded = if capped {
        ChargedBytes::read(decoder.sample(), charge.sibling(), 3 * SAMPLE)?
    } else {
        ChargedBytes::read(decoder, charge.sibling(), 3 * SAMPLE)?
    };
    drop(raw);
    let configured = settings.delimiter;
    let mut best = 0;
    let mut suggested = configured;
    let mut configured_ending = None;
    let mut suggested_ending = None;
    let mut ambiguous = false;
    for delimiter in std::iter::once(configured).chain(
        [',', '\t', ';', '|']
            .into_iter()
            .filter(|&value| value != configured),
    ) {
        if delimiter == settings.quote || settings.escape == Some(delimiter) {
            continue;
        }
        let mut candidate = settings.clone();
        candidate.delimiter = delimiter;
        let score = candidate_score(
            &decoded.bytes,
            capped,
            candidate,
            &job.input_dialect,
            charge.sibling(),
        )?;
        if delimiter == configured {
            configured_ending = score.line_ending;
        }
        if score.consistent > best {
            best = score.consistent;
            suggested = delimiter;
            suggested_ending = score.line_ending;
            ambiguous = false;
        } else if score.consistent > 0 && score.consistent == best {
            ambiguous = true;
        }
    }
    let ending = if ambiguous || best == 0 {
        configured_ending
    } else {
        suggested_ending
    };
    if let Some(ending) = ending {
        settings.line_ending = ending.into();
    }
    let (delimiter_status, note) = if ambiguous {
        ("ambiguous", AMBIGUOUS)
    } else if best == 0 {
        ("not_detected", NO_MATCH)
    } else {
        settings.delimiter = suggested;
        ("detected", NOTE)
    };
    // Charge all owned text, including up to three encoded CSV setting characters.
    let text_bytes = settings
        .encoding
        .len()
        .checked_add(settings.line_ending.len())
        .and_then(|bytes| bytes.checked_add(note.len() + delimiter_status.len() + 12))
        .context("dialect suggestion text length overflow")?;
    Inspection::build(charge, 0, text_bytes, || {
        json!({
            "settings": settings,
            "note": note,
            "delimiter_status": delimiter_status,
            "sample_bytes": sample_bytes,
        })
    })
}
