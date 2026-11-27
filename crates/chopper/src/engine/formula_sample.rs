//! Bounded formula samples from an open CSV reader, independent of job execution.
use super::*;
use crate::csv_intake::Intake;

const ROWS_PER_BATCH: usize = 512;
const BYTES_PER_BATCH: usize = 1024 * 1024;

#[derive(Serialize)]
pub struct FormulaSample {
    rows: Vec<(u64, Vec<String>)>,
    done: bool,
    #[serde(skip)]
    _memory: Reservation,
}

/// Keep the decoder open across batches, including compressed inputs. The
/// caller controls when another batch is read and can stop after each report.
pub fn sample_formula_rows(
    job: &Job,
    mut report: impl FnMut(&FormulaSample) -> Result<()>,
    mut more: impl FnMut() -> Result<bool>,
) -> Result<()> {
    validate_input_inspection(job)?;
    let memory = input_inspection_reservation(job)?;
    with_input(job, memory.sibling(), |source| {
        let input = Intake::inspection(
            source,
            &job.input_csv,
            job.resources.max_record_bytes,
            memory,
        )?;
        records::with_dialect!(input, &job.input_dialect, |input| sample(
            input,
            &mut report,
            &mut more,
        ))
    })
}

fn sample(
    mut input: Intake<impl records::Records>,
    report: &mut impl FnMut(&FormulaSample) -> Result<()>,
    more: &mut impl FnMut() -> Result<bool>,
) -> Result<()> {
    drop(input.header()?);
    let mut number = 0_u64;
    let mut pending = false;
    loop {
        let mut batch = FormulaSample {
            rows: Vec::new(),
            done: false,
            _memory: input.reservation(),
        };
        let mut bytes = 0;
        let mut read_error = None;
        for _ in 0..ROWS_PER_BATCH {
            if !pending {
                match input.next_owned(|| Ok(())) {
                    Ok(true) => number += 1,
                    Ok(false) => {
                        batch.done = true;
                        break;
                    }
                    Err(error) => {
                        read_error = Some(error);
                        break;
                    }
                }
            }
            let row = input.owned();
            // Include field boundaries so wide, mostly empty rows are bounded too.
            let size = row.iter().map(|field| field.len() + 1).sum::<usize>();
            pending = size <= BYTES_PER_BATCH && size > BYTES_PER_BATCH - bytes;
            if pending {
                break;
            }
            if size > BYTES_PER_BATCH {
                // Skip the oversized record and pause. Do not keep reading
                // large records after the batch has used its byte budget.
                break;
            }
            batch._memory.reserve_vec(&mut batch.rows, ROWS_PER_BATCH)?;
            let mut fields = Vec::new();
            batch._memory.reserve_vec(&mut fields, row.len())?;
            for field in row {
                fields.push(batch._memory.copy_string(field)?);
            }
            batch.rows.push((number, fields));
            bytes += size;
            if bytes == BYTES_PER_BATCH {
                break;
            }
        }
        report(&batch)?;
        if let Some(error) = read_error {
            return Err(error);
        }
        let done = batch.done;
        drop(batch);
        if done || !more()? {
            return Ok(());
        }
    }
}
