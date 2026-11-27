//! Ownership of the column picker's source buffer and first decoded record.
//! Returned JSON has a separate Inspection owner. Configuration clones,
//! DecodeReader's inline buffers and codec
//! internals are outside this working-allocation boundary.
use super::*;

use crate::csv_intake::Intake;

pub(super) fn columns(
    source: impl Read,
    job: &Job,
    record: Reservation,
    input_is_zip: bool,
) -> Result<Inspection> {
    let owner = Intake::inspection(
        source,
        &job.input_csv,
        job.resources.max_record_bytes,
        record,
    )?;
    records::with_dialect!(owner, &job.input_dialect, |owner| columns_from(
        owner,
        job.input_csv.headers,
        input_is_zip,
    ))
}

fn columns_from(
    mut owner: Intake<impl records::Records>,
    headers: bool,
    input_is_zip: bool,
) -> Result<Inspection> {
    owner.next_owned(|| Ok(()))?;
    let (items, text) = if headers {
        let bytes = owner.owned().iter().try_fold(0usize, |total, field| {
            total
                .checked_add(field.len())
                .context("inspection header length overflow")
        })?;
        (owner.owned().len(), bytes)
    } else {
        (0, 0)
    };
    Inspection::build(owner.reservation(), items, text, || {
        json!({
            "columns": owner.owned().len(),
            "header": if headers { Some(owner.owned()) } else { None },
            "input_is_zip": input_is_zip,
        })
    })
}

// Retain admitted header/sample owners until the separately admitted JSON tree exists.
pub(super) fn preview(
    source: impl Read,
    job: &Job,
    record: Reservation,
    input_is_zip: bool,
) -> Result<Inspection> {
    let owner = Intake::inspection(
        source,
        &job.input_csv,
        job.resources.max_record_bytes,
        record,
    )?;
    records::with_dialect!(owner, &job.input_dialect, |owner| preview_from(
        owner,
        input_is_zip
    ))
}

fn preview_from(
    mut owner: Intake<impl records::Records>,
    input_is_zip: bool,
) -> Result<Inspection> {
    let header = owner.header()?;
    let header = header.map(|header| header.into_parts());
    let mut sample = preview::Builder::new(owner.reservation());
    let mut row_numbers = [0; 8];
    let mut retained = 0;
    for number in 1..=8 {
        if !owner.next_owned(|| Ok(()))? {
            break;
        }
        let bytes = owner.owned().iter().map(String::len).sum();
        if sample.consider(FieldViews::owned(owner.owned()), bytes)? {
            row_numbers[retained] = number;
            retained += 1;
        }
    }
    let sample = sample.finish()?;
    let header_fields = header.as_ref().map(|(fields, _)| fields);
    let mut items = header_fields.map_or(0, |fields| fields.len());
    let mut text = header_fields.map_or(0, |fields| fields.iter().map(String::len).sum::<usize>());
    items = items
        .checked_add(sample.len() + retained)
        .context("preview array length overflow")?;
    for row in sample.iter() {
        items = items
            .checked_add(row.len())
            .context("preview field count overflow")?;
        for field in row {
            text = text
                .checked_add(field.len())
                .context("preview text length overflow")?;
        }
    }
    Inspection::build(owner.reservation(), items, text, || {
        json!({
            "columns": owner.columns(), "header": header_fields, "input_is_zip": input_is_zip,
            "preview": sample,
            "preview_row_numbers": &row_numbers[..retained],
        })
    })
}

#[cfg(any(test, feature = "resource-contract-tests"))]
pub(super) fn resource_contracts() -> Result<serde_json::Value> {
    contracts::run()
}

// Keep independent controls in separate frames: DecodeReader has sizeable
// inline buffers, and debug builds retain stack slots for moved temporaries.
#[cfg(any(test, feature = "resource-contract-tests"))]
mod contracts {
    use super::*;
    use crate::csv_intake::SOURCE_BUFFER;
    use crate::resources::{MemoryAdmission, MemoryPool};
    const SOURCE: &[u8] = b"\"country, region\",segment,segment\n";

    fn probe(job: &Job) -> Result<(u64, u64, u64)> {
        let source = SOURCE;
        let probe = Arc::new(Workspace::new(1024 * 1024));
        let mut parser = Intake::inspection(
            source,
            &job.input_csv,
            job.resources.max_record_bytes,
            Reservation::for_workspace(probe.clone()),
        )?;
        ensure!(parser.next_owned(|| Ok(()))?, "missing inspection record");
        let peak = probe.peak();
        let retained = probe.used();
        ensure!(
            retained > SOURCE_BUFFER as u64,
            "missing decoded record charge"
        );
        ensure!(!parser.next_owned(|| Ok(()))?, "inspection EOF changed");
        let eof_retained = probe.used();
        ensure!(
            eof_retained >= SOURCE_BUFFER as u64,
            "EOF released source owner"
        );
        ensure!(!parser.next_owned(|| Ok(()))?, "terminal EOF resumed");
        ensure!(
            probe.used() == eof_retained,
            "terminal EOF changed capacity"
        );
        drop(parser);
        ensure!(probe.used() == 0, "inspection probe leaked");

        Ok((peak, retained, eof_retained))
    }

    fn local_denial(job: &Job, peak: u64) -> Result<()> {
        let source = SOURCE;
        // A local denial occurs before allocating the fixed source buffer.
        let local = Arc::new(Workspace::new(SOURCE_BUFFER - 1));
        let error = Intake::inspection(
            source,
            &job.input_csv,
            job.resources.max_record_bytes,
            Reservation::for_workspace(local.clone()),
        )
        .err()
        .context("local source admission should fail")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Local)
            ),
            "source denial lost local type"
        );
        ensure!(local.used() == 0, "local source denial leaked");

        let local = Arc::new(Workspace::new(peak as usize - 1));
        let mut owner = Intake::inspection(
            source,
            &job.input_csv,
            job.resources.max_record_bytes,
            Reservation::for_workspace(local.clone()),
        )?;
        let error = owner
            .next_owned(|| Ok(()))
            .err()
            .context("local parser growth should fail")?;
        ensure!(
            matches!(
                error.downcast_ref::<MemoryAdmission>(),
                Some(MemoryAdmission::Local)
            ),
            "parser denial lost local type"
        );
        let retained_error = local.used();
        ensure!(
            retained_error >= SOURCE_BUFFER as u64 && !owner.next_owned(|| Ok(()))?,
            "local denial released owner or resumed parser"
        );
        ensure!(
            local.used() == retained_error,
            "terminal local error changed capacity"
        );
        drop(owner);
        ensure!(local.used() == 0, "local parser denial leaked");

        Ok(())
    }

    fn shared_denial(job: &Job, peak: u64, expected: serde_json::Value) -> Result<()> {
        let source = SOURCE;
        // Independently test source-buffer and parser-growth shared boundaries.
        for (demand, parse) in [(SOURCE_BUFFER as u64, false), (peak, true)] {
            let pool = Arc::new(MemoryPool::new(demand + 7));
            let workspace = Arc::new(Workspace::shared(1024 * 1024, pool.clone()));
            let mut held = Reservation::for_workspace(Arc::new(Workspace::shared(8, pool.clone())));
            held.resize(8)?;
            let result = Intake::inspection(
                source,
                &job.input_csv,
                job.resources.max_record_bytes,
                Reservation::for_workspace(workspace.clone()),
            );
            if parse {
                let mut owner = result?;
                let error = owner
                    .next_owned(|| Ok(()))
                    .err()
                    .context("shared parser growth should fail")?;
                ensure!(
                    matches!(
                        error.downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Shared { .. })
                    ),
                    "parser denial lost shared type"
                );
                let after_error = workspace.used();
                ensure!(
                    after_error >= SOURCE_BUFFER as u64,
                    "error released live source"
                );
                ensure!(!owner.next_owned(|| Ok(()))?, "failed parser resumed");
                ensure!(
                    workspace.used() == after_error,
                    "terminal error changed capacity"
                );
                drop(owner);
            } else {
                let error = result.err().context("shared source buffer should fail")?;
                ensure!(
                    matches!(
                        error.downcast_ref::<MemoryAdmission>(),
                        Some(MemoryAdmission::Shared { .. })
                    ),
                    "source denial lost shared type"
                );
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 8,
                "denial changed held owner"
            );
            drop(held);
            if parse {
                // This pool isolates the parser edge, excluding result-tree
                // capacity. Test the fresh parser here; the result owner has
                // its own construction/overlap admission controls.
                let mut owner = Intake::inspection(
                    source,
                    &job.input_csv,
                    job.resources.max_record_bytes,
                    Reservation::for_workspace(workspace.clone()),
                )?;
                ensure!(
                    owner.next_owned(|| Ok(()))?,
                    "fresh parser retry lost record"
                );
                ensure!(
                    serde_json::to_value(owner.owned())? == expected["header"],
                    "fresh retry changed header"
                );
                drop(owner);
            } else {
                // Construct/destroy only: this grant deliberately excludes records.
                drop(Intake::inspection(
                    source,
                    &job.input_csv,
                    job.resources.max_record_bytes,
                    Reservation::for_workspace(workspace.clone()),
                )?);
            }
            ensure!(
                workspace.used() == 0 && pool.usage().reserved_bytes == 0,
                "fresh retry leaked"
            );
        }

        Ok(())
    }

    fn invalid_input(job: &Job) -> Result<usize> {
        let mut error_cases = 0;
        for bytes in [b"\"unterminated".as_slice(), b"\xff".as_slice()] {
            let workspace = Arc::new(Workspace::new(1024 * 1024));
            let mut owner = Intake::inspection(
                bytes,
                &job.input_csv,
                job.resources.max_record_bytes,
                Reservation::for_workspace(workspace.clone()),
            )?;
            ensure!(
                owner.next_owned(|| Ok(())).is_err(),
                "invalid inspection accepted"
            );
            let retained = workspace.used();
            ensure!(
                retained >= SOURCE_BUFFER as u64,
                "error dropped live owner charge"
            );
            ensure!(!owner.next_owned(|| Ok(()))?, "invalid parser resumed");
            ensure!(
                workspace.used() == retained,
                "terminal invalid parser changed capacity"
            );
            drop(owner);
            ensure!(workspace.used() == 0, "invalid inspection leaked");
            error_cases += 1;
        }
        Ok(error_cases)
    }

    fn read_error(job: &Job) -> Result<()> {
        struct Cancelled;
        impl Read for Cancelled {
            fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> {
                Err(std::io::Error::other("cancelled"))
            }
        }
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let mut owner = Intake::inspection(
            Cancelled,
            &job.input_csv,
            job.resources.max_record_bytes,
            Reservation::for_workspace(workspace.clone()),
        )?;
        let error = owner
            .next_owned(|| Ok(()))
            .err()
            .context("read error accepted")?;
        ensure!(
            format!("{error:#}").contains("cancelled"),
            "read error changed"
        );
        ensure!(!owner.next_owned(|| Ok(()))?, "read-error parser resumed");
        drop(owner);
        ensure!(workspace.used() == 0, "read error leaked");

        Ok(())
    }

    fn json_parity(job: &Job, expected: serde_json::Value) -> Result<()> {
        let source = SOURCE;
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let mut trailing = source.to_vec();
        trailing.extend_from_slice(b"\"unterminated");
        ensure!(
            columns(
                trailing.as_slice(),
                job,
                Reservation::for_workspace(workspace.clone()),
                false
            )? == expected,
            "column picker parsed beyond the first record"
        );
        let mut no_header = job.clone();
        no_header.input_csv.headers = false;
        ensure!(
            columns(
                source,
                &no_header,
                Reservation::for_workspace(workspace.clone()),
                true
            )? == json!({"columns": 3, "header": null, "input_is_zip": true}),
            "header-disabled JSON changed"
        );
        ensure!(
            columns(
                b"".as_slice(),
                job,
                Reservation::for_workspace(workspace.clone()),
                false
            )? == json!({"columns": 0, "header": [], "input_is_zip": false}),
            "empty JSON changed"
        );
        ensure!(workspace.used() == 0, "JSON inspection leaked");
        Ok(())
    }

    pub(super) fn run() -> Result<serde_json::Value> {
        let job = Job::default();
        let expected = json!({"columns": 3, "header": ["country, region", "segment", "segment"], "input_is_zip": false});
        let (peak, retained, eof_retained) = probe(&job)?;
        local_denial(&job, peak)?;
        shared_denial(&job, peak, expected.clone())?;
        let error_cases = invalid_input(&job)?;
        read_error(&job)?;
        json_parity(&job, expected)?;
        Ok(json!({
            "contract": "inspection-columns-resource-contracts-v1",
            "source_buffer_bytes": SOURCE_BUFFER,
            "first_record_peak_bytes": peak, "first_record_retained_bytes": retained,
            "eof_retained_bytes": eof_retained,
            "typed_local_denials": 2, "typed_shared_denials": 2,
            "fresh_owner_release_retries": 2, "terminal_after_error": true,
            "eof_owner_retained": true, "invalid_input_cleanup_cases": error_cases,
            "read_error_cleanup": true, "json_parity": true, "final_reserved_bytes": 0,
        }))
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn columns_production_path_ordinary_stack() -> anyhow::Result<()> {
        use super::*;
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let result = columns(
            b"alpha,beta\n".as_slice(),
            &Job::default(),
            Reservation::for_workspace(workspace.clone()),
            false,
        )?;
        assert_eq!(
            result,
            json!({"columns": 2, "header": ["alpha", "beta"], "input_is_zip": false})
        );
        assert!(workspace.used() > 0);
        drop(result);
        assert_eq!(workspace.used(), 0);
        Ok(())
    }

    #[test]
    fn columns_parser_shared_capacity_contract() -> anyhow::Result<()> {
        super::resource_contracts()?;
        Ok(())
    }
}

#[cfg(test)]
mod preview_tests {
    use super::*;

    #[test]
    fn result_keeps_its_admission_and_failure_releases_builders() -> Result<()> {
        let workspace = Arc::new(Workspace::new(1024 * 1024));
        let result = preview(
            b"id,note\n1,hello\n".as_slice(),
            &Job::default(),
            Reservation::for_workspace(workspace.clone()),
            false,
        )?;
        assert!(workspace.used() > 0);
        assert_eq!(result["preview"], json!([["1", "hello"]]));
        drop(result);
        assert_eq!(workspace.used(), 0);
        assert!(preview(
            b"id,note\n1,hello\n2\n".as_slice(),
            &Job::default(),
            Reservation::for_workspace(workspace.clone()),
            false,
        )
        .is_err());
        assert_eq!(workspace.used(), 0);
        let denied = Arc::new(Workspace::new(crate::csv_intake::SOURCE_BUFFER));
        assert!(preview(
            b"id,note\n1,hello\n".as_slice(),
            &Job::default(),
            Reservation::for_workspace(denied.clone()),
            false,
        )
        .is_err());
        assert_eq!(denied.used(), 0);
        Ok(())
    }
}
