use super::*;
use chopper_core::expression::{Expression, Value};
use std::borrow::Cow;

pub(crate) struct Program {
    expression: Expression,
    width: usize,
    _memory: Reservation,
}

pub(super) struct Unbound {
    expression: Expression,
    memory: Reservation,
}

impl Unbound {
    fn compile(source: &str, mut memory: Reservation) -> Result<Self> {
        memory.resize(Expression::preparation_bytes(source))?;
        let expression = Expression::parse(source).map_err(anyhow::Error::msg)?;
        Ok(Self { expression, memory })
    }

    pub(super) fn bind(
        mut self,
        name: &str,
        header: Option<&[String]>,
        width: usize,
        unnamed: usize,
    ) -> Result<(Program, Header)> {
        self.expression
            .bind(header, width, unnamed)
            .map_err(anyhow::Error::msg)?;
        let next = Header::appended(header, width, name, self.memory.sibling())?;
        self.memory.resize(
            (self.memory.bytes() as usize)
                .checked_add(self.expression.workspace_bytes())
                .context("formula allocation overflow")?,
        )?;
        Ok((
            Program {
                expression: self.expression,
                width,
                _memory: self.memory,
            },
            next,
        ))
    }
}

pub(super) fn compile_steps(job: &Job, ctx: &Context) -> Result<[Option<Unbound>; 64]> {
    let mut programs = [const { None }; 64];
    for (index, op) in job.operations.iter().enumerate() {
        if let Operation::Calculate { name, expression } = op {
            ctx.check()?;
            programs[index] = Some(
                Unbound::compile(expression, Reservation::new(ctx)).with_context(|| {
                    format!(
                        "preparing calculated column {name:?} at operation {}",
                        index + 1
                    )
                })?,
            );
        }
    }
    Ok(programs)
}

pub(crate) fn prepare(
    source: &str,
    name: &str,
    header: Option<&[String]>,
    width: usize,
    unnamed: usize,
    memory: Reservation,
) -> Result<(Program, Header)> {
    Unbound::compile(source, memory)?.bind(name, header, width, unnamed)
}

pub(crate) fn schema_after(
    header: Option<&[String]>,
    width: usize,
    name: &str,
    memory: Reservation,
) -> Result<Header> {
    Header::appended(header, width, name, memory)
}

impl Program {
    fn evaluate<'a>(
        &'a self,
        field: &(impl Fn(usize) -> Option<Value<'a>> + 'a),
        reserve: &mut chopper_core::expression::Reserve<'_>,
    ) -> Result<(char, Cow<'a, str>)> {
        let value = self.expression.evaluate(field, reserve)?;
        Ok((value.kind(), value.rendered(reserve)?))
    }

    pub(super) fn apply(
        &self,
        dataset: &Dataset,
        name: &str,
        prior_columns: usize,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<()> {
        output.physical_input(dataset.physical_source);
        let mut scratch = Reservation::new(ctx);
        let mut value = String::new();
        for parent in dataset.groups()? {
            ctx.check()?;
            let parent = parent?;
            let mut group =
                group_metadata::ClonedGroup::begin(&parent, output, Reservation::new(ctx))?;
            let mut rows = dataset.rows(&parent, ctx.max_record)?;
            let mut previous = None;
            while let Some(mut row) = rows.next_packed(previous.take())? {
                ctx.check()?;
                value.clear();
                let kind = {
                    let metadata = if prior_columns > 0 {
                        Some(
                            row.fields()
                                .nth(self.width)
                                .context("missing calculation metadata")?,
                        )
                    } else {
                        None
                    };
                    let first_calculated = self.width - prior_columns;
                    let field = |index| {
                        let text = row.fields().nth(index)?;
                        if index < first_calculated {
                            Some(Value::Text(Cow::Borrowed(text)))
                        } else {
                            Value::from_stored(
                                text,
                                metadata?.chars().nth(index - first_calculated)?,
                            )
                        }
                    };
                    let mut reserve = |bytes| reserve_scratch(&mut scratch, bytes, ctx);
                    let mut resource_failure = None;
                    let evaluation = self.evaluate(&field, &mut |n| {
                        reserve(n).map_err(|error| {
                            let message = error.to_string();
                            resource_failure = Some(error);
                            message
                        })
                    });
                    let (kind, result) = evaluation
                        .map_err(|error| resource_failure.unwrap_or(error))
                        .with_context(|| {
                            format!("input record {}, calculated column {name:?}", row.id + 1)
                        })?;
                    if value.capacity() < result.len() {
                        reserve(result.len())?;
                        value.try_reserve_exact(result.len())?;
                    }
                    value.push_str(&result);
                    kind
                };
                row.append_calculated(&value, kind, prior_columns > 0, ctx.max_record)
                    .with_context(|| {
                        format!("input record {}, calculated column {name:?}", row.id + 1)
                    })?;
                scratch.resize(value.capacity())?;
                output.packed_row_ref(&mut group.group, &row)?;
                previous = Some(row);
            }
            group.finish(output)?;
        }
        Ok(())
    }
}

fn reserve_scratch(scratch: &mut Reservation, bytes: usize, ctx: &Context) -> Result<()> {
    ctx.check()?;
    scratch.resize(
        (scratch.bytes() as usize)
            .checked_add(bytes)
            .context("formula scratch size overflow")?,
    )
}

#[derive(Deserialize)]
struct FormulaPreviewRequest {
    header: Option<Vec<String>>,
    columns: usize,
    rows: Vec<Vec<String>>,
    calculations: Vec<PreviewCalculation>,
}

#[derive(Deserialize)]
struct PreviewCalculation {
    operation: usize,
    name: String,
    expression: String,
}

#[derive(Serialize)]
pub struct FormulaPreview {
    functions: &'static [(&'static str, &'static str)],
    steps: Vec<PreviewStep>,
    #[serde(skip)]
    _memory: Reservation,
}

#[derive(Serialize)]
struct PreviewStep {
    operation: usize,
    error: Option<String>,
    rows: Vec<PreviewCell>,
}

#[derive(Serialize)]
struct PreviewCell {
    value: Option<String>,
    error: Option<String>,
    is_null: bool,
    #[serde(skip)]
    kind: char,
    #[serde(skip)]
    stored: Option<String>,
}

pub fn formula_preview_json(reader: impl Read, wire_bytes: u64) -> Result<FormulaPreview> {
    ensure!(
        wire_bytes <= 2 * 1024 * 1024,
        "formula preview request exceeds 2 MiB"
    );
    let mut wire_memory = input_inspection_reservation(&Job::default())?;
    // Bound JSON container descriptor growth, overlapping vector allocation,
    // and decoded strings before deserializing the request.
    wire_memory.resize(wire_bytes as usize * 32)?;
    let request = serde_json::from_reader(reader.take(wire_bytes))?;
    formula_preview(request)
}

fn formula_preview(request: FormulaPreviewRequest) -> Result<FormulaPreview> {
    let FormulaPreviewRequest {
        header,
        columns,
        rows,
        calculations,
    } = request;
    ensure!(
        rows.len() <= 8 && calculations.len() <= 64,
        "formula preview exceeds its row or step limit"
    );
    ensure!(
        header.as_ref().is_none_or(|h| h.len() == columns)
            && rows.iter().all(|r| r.len() == columns),
        "invalid formula preview schema"
    );
    let mut memory = input_inspection_reservation(&Job::default())?;
    let mut steps: Vec<PreviewStep> = Vec::new();
    memory.reserve_vec(&mut steps, calculations.len())?;
    let mut derived_header = None;
    let mut display_bytes = 0;
    for (index, calculation) in calculations.into_iter().enumerate() {
        let mut step = PreviewStep {
            operation: calculation.operation,
            error: None,
            rows: Vec::new(),
        };
        let source_header = derived_header.as_deref().or(header.as_deref());
        let program = if calculation.name.is_empty() {
            Err(anyhow::anyhow!("enter a calculated column name"))
        } else {
            prepare(
                &calculation.expression,
                &calculation.name,
                source_header,
                columns + index,
                if header.is_none() { columns } else { 0 },
                memory.sibling(),
            )
        };
        let (program, next_header) = match program {
            Ok(prepared) => prepared,
            Err(error) => {
                step.error = Some(copy_preview_error(&mut memory, &error)?);
                steps.push(step);
                derived_header = Some(Header::append_for_preview(
                    source_header,
                    columns + index,
                    &calculation.name,
                    memory.sibling(),
                )?);
                continue;
            }
        };
        memory.reserve_vec(&mut step.rows, rows.len())?;
        let mut scratch = memory.sibling();
        for (row_index, row) in rows.iter().enumerate() {
            let dependency_failed = std::cell::Cell::new(false);
            let field = |index: usize| {
                if let Some(text) = row.get(index) {
                    return Some(Value::Text(Cow::Borrowed(text)));
                }
                let previous = steps
                    .get(index.checked_sub(columns)?)
                    .and_then(|step| step.rows.get(row_index));
                let value = previous.and_then(|cell| {
                    Value::from_stored(cell.value.as_deref().or(cell.stored.as_deref())?, cell.kind)
                });
                if value.is_none() {
                    dependency_failed.set(true);
                }
                value
            };
            let result = program.evaluate(&field, &mut |bytes| {
                scratch
                    .resize(
                        (scratch.bytes() as usize)
                            .checked_add(bytes)
                            .ok_or("formula preview size overflow")?,
                    )
                    .map_err(|error| error.to_string())
            });
            let cell = match result {
                Ok((kind, value)) if value.len() <= 32768 - display_bytes => {
                    display_bytes += value.len();
                    PreviewCell {
                        value: Some(memory.copy_string(&value)?),
                        error: None,
                        is_null: kind == 'n',
                        kind,
                        stored: None,
                    }
                }
                Ok((kind, value)) => PreviewCell {
                    value: None,
                    error: Some(memory.copy_string("Value exceeds the preview size limit")?),
                    is_null: false,
                    kind,
                    stored: Some(memory.copy_string(&value)?),
                },
                Err(error) => PreviewCell {
                    value: None,
                    error: Some(if dependency_failed.get() {
                        memory
                            .copy_string("An earlier calculated column has no value for this row")?
                    } else {
                        copy_preview_error(&mut memory, &error)?
                    }),
                    is_null: false,
                    kind: 't',
                    stored: None,
                },
            };
            scratch.resize(0)?;
            step.rows.push(cell);
        }
        steps.push(step);
        derived_header = Some(next_header);
    }
    Ok(FormulaPreview {
        functions: chopper_core::expression::FUNCTIONS,
        steps,
        _memory: memory,
    })
}

fn copy_preview_error(memory: &mut Reservation, error: &anyhow::Error) -> Result<String> {
    let message = error.to_string();
    let end = message
        .char_indices()
        .nth(256)
        .map_or(message.len(), |(i, _)| i);
    memory.copy_string(&message[..end])
}
