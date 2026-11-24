use super::*;
use chopper_core::expression::{Expression, Value};
use std::borrow::Cow;

pub(crate) struct Plan {
    programs: [Option<Program>; 64],
    order: [usize; 64],
    referenced_results: u64,
    width: usize,
    pub(crate) header: Header,
    pub(super) boundary: usize,
}

struct Program {
    expression: Expression,
    dependencies: u64,
    _memory: Reservation,
}

fn prepare(
    source: &str,
    schema: &Header,
    source_width: usize,
    unnamed: usize,
    mut memory: Reservation,
    source_reference: &mut impl FnMut(usize),
) -> Result<Program> {
    memory.resize(Expression::preparation_bytes(source))?;
    let mut expression = Expression::parse(source).map_err(anyhow::Error::msg)?;
    let mut dependencies = 0;
    expression
        .bind_references(Some(schema), schema.len(), unnamed, &mut |index| {
            if index >= source_width {
                dependencies |= 1 << (index - source_width);
            } else {
                source_reference(index);
            }
        })
        .map_err(anyhow::Error::msg)?;
    reserve_scratch_bytes(&mut memory, expression.workspace_bytes())?;
    Ok(Program {
        expression,
        dependencies,
        _memory: memory,
    })
}

fn ready(programs: &[Option<Program>], completed: u64) -> Option<usize> {
    programs.iter().enumerate().position(|(index, program)| {
        completed & (1 << index) == 0
            && program
                .as_ref()
                .is_none_or(|program| program.dependencies & !completed == 0)
    })
}

pub(crate) fn schema(
    job: &Job,
    header: Option<&[String]>,
    width: usize,
    memory: Reservation,
) -> Result<Header> {
    for column in &job.calculated_columns {
        ensure!(
            !header.is_some_and(|fields| fields.contains(&column.name)),
            "calculated column {:?} already exists",
            column.name
        );
    }
    Header::with_calculations(
        header,
        width,
        job.calculated_columns
            .iter()
            .map(|column| column.name.as_str()),
        memory,
    )
}

impl Plan {
    pub(crate) fn prepare(
        job: &Job,
        header: Option<&[String]>,
        width: usize,
        memory: Reservation,
    ) -> Result<Self> {
        let expanded = schema(job, header, width, memory.sibling())?;
        let mut programs = [const { None }; 64];
        let mut order = [0; 64];
        let count = job.calculated_columns.len();
        for (index, column) in job.calculated_columns.iter().enumerate() {
            programs[index] = Some(
                prepare(
                    &column.expression,
                    &expanded,
                    width,
                    if header.is_none() { width } else { 0 },
                    memory.sibling(),
                    &mut |_| {},
                )
                .with_context(|| format!("preparing calculated column {:?}", column.name))?,
            );
        }
        let referenced_results = programs[..count]
            .iter()
            .flatten()
            .fold(0, |mask, program| mask | program.dependencies);
        let mut completed = 0;
        for slot in &mut order[..count] {
            let index = ready(&programs[..count], completed).with_context(|| {
                let blocked = completed.trailing_ones() as usize;
                format!(
                    "cyclic calculated column dependency involving {:?}",
                    job.calculated_columns[blocked].name
                )
            })?;
            *slot = index;
            completed |= 1 << index;
        }
        let mut boundary = job.operations.len();
        for (index, operation) in job.operations.iter().enumerate() {
            let selectors = match operation {
                Operation::Partition { columns } => columns,
                Operation::Assign { strata, .. }
                | Operation::AssignProbabilistic { strata, .. } => strata,
                _ => continue,
            };
            for column in selectors {
                if resolve_column(column, Some(&expanded), expanded.len())? >= width {
                    boundary = boundary.min(index);
                }
            }
        }
        Ok(Self {
            programs,
            order,
            referenced_results,
            width,
            header: expanded,
            boundary,
        })
    }

    #[cfg(target_os = "linux")]
    pub(super) fn sorted_partition(
        &self,
        dataset: &Dataset,
        parent: &Group,
        columns: &[usize],
        job: &Job,
        ctx: &Context,
    ) -> Result<SortedRows> {
        let mut sorter = Sorter::new(ctx, SortOrder::Key);
        let mut evaluator = RowEvaluator::new(self, job, ctx);
        let mut rows = dataset.rows(parent, ctx.max_record)?;
        let mut previous = None;
        while let Some(mut row) = rows.next_packed(previous.take())? {
            evaluator.append(&mut row, ctx)?;
            let key =
                OperationKey::tuple(row.fields(), columns, 0, Reservation::new(ctx), &mut sorter)?;
            let capacity = key.install(&mut row, &mut sorter)?;
            previous = sorter.push_compact_reusing(row, capacity)?;
        }
        drop(rows);
        drop(evaluator);
        sorter.finish()
    }

    pub(super) fn apply(
        &self,
        dataset: &Dataset,
        job: &Job,
        ctx: &Context,
        output: &mut impl RowSink,
    ) -> Result<()> {
        use crate::observation::physical::Kind;
        let mut observation = ctx.physical_span(Kind::Calculation);
        output.physical_input(if observation.is_some() {
            ctx.physical_identity(Kind::Calculation)
        } else {
            dataset.physical_source
        });
        let mut calculated_rows = 0;
        let mut evaluator = RowEvaluator::new(self, job, ctx);
        for parent in dataset.groups()? {
            ctx.check()?;
            let parent = parent?;
            let mut group =
                group_metadata::ClonedGroup::begin(&parent, output, Reservation::new(ctx))?;
            let mut rows = dataset.rows(&parent, ctx.max_record)?;
            let mut previous = None;
            while let Some(mut row) = rows.next_packed(previous.take())? {
                evaluator.append(&mut row, ctx)?;
                calculated_rows += 1;
                if let Some(observation) = &mut observation {
                    observation.rows_processed(calculated_rows);
                }
                output.packed_row_ref(&mut group.group, &row)?;
                previous = Some(row);
            }
            group.finish(output)?;
        }
        if let Some(observation) = observation {
            observation.finish(calculated_rows);
        }
        Ok(())
    }
}

struct RowEvaluator<'a> {
    plan: &'a Plan,
    job: &'a Job,
    values: [(String, char); 64],
    scalars: [Option<Value<'static>>; 64],
    retained: Reservation,
}

impl<'a> RowEvaluator<'a> {
    fn new(plan: &'a Plan, job: &'a Job, ctx: &Context) -> Self {
        Self {
            plan,
            job,
            values: std::array::from_fn(|_| (String::new(), 'n')),
            scalars: [const { None }; 64],
            retained: Reservation::new(ctx),
        }
    }

    #[inline(always)]
    fn append(&mut self, row: &mut PackedRow, ctx: &Context) -> Result<()> {
        let Self {
            plan,
            job,
            values,
            scalars,
            retained,
        } = self;
        let count = job.calculated_columns.len();
        ctx.check()?;
        let (fields, payload) = row.field_sizes();
        ensure!(
            fields + count <= ctx.max_record / 24,
            "input record {}, calculated row exceeds maximum record size",
            row.id + 1
        );
        let mut remaining = ctx.max_record.saturating_sub(payload);
        let mut scratch = retained.sibling();
        for &index in &plan.order[..count] {
            let (before, rest) = values.split_at_mut(index);
            let ((value, kind), after) = rest.split_first_mut().unwrap();
            let field = |column: usize| {
                if column < plan.width {
                    return row
                        .fields()
                        .nth(column)
                        .map(|text| Value::Text(Cow::Borrowed(text)));
                }
                let relative = column - plan.width;
                if let Some(value) = scalars.get(relative).and_then(Option::as_ref) {
                    return scalar_value(value);
                }
                let (text, kind) = if relative < index {
                    before.get(relative)?
                } else {
                    after.get(relative.checked_sub(index + 1)?)?
                };
                Value::from_stored(text, *kind)
            };
            let mut resource_failure = None;
            let result = plan.programs[index]
                .as_ref()
                .unwrap()
                .evaluate_retaining_scalar(
                    &field,
                    plan.referenced_results & (1 << index) != 0,
                    &mut |bytes| {
                        ctx.check()
                            .and_then(|()| reserve_scratch_bytes(&mut scratch, bytes))
                            .map_err(|error| {
                                let message = error.to_string();
                                resource_failure = Some(error);
                                message
                            })
                    },
                );
            let (scalar, result_kind, rendered) = result
                .map_err(|error| resource_failure.unwrap_or(error))
                .with_context(|| {
                    format!(
                        "input record {}, calculated column {:?}",
                        row.id + 1,
                        job.calculated_columns[index].name
                    )
                })?;
            remaining = remaining
                .checked_sub(result_kind.len_utf8())
                .and_then(|bytes| bytes.checked_sub(rendered.len()))
                .with_context(|| {
                    format!(
                        "input record {}, calculated column {:?} exceeds maximum record size",
                        row.id + 1,
                        job.calculated_columns[index].name
                    )
                })?;
            value.clear();
            let previous_capacity = value.capacity();
            if previous_capacity < rendered.len() {
                let other_capacity = retained.bytes() as usize - previous_capacity;
                reserve_scratch_bytes(retained, rendered.len())?;
                value.try_reserve_exact(rendered.len())?;
                retained.resize(other_capacity + value.capacity())?;
            }
            value.push_str(&rendered);
            *kind = result_kind;
            drop(rendered);
            scalars[index] = scalar;
            scratch.resize(0)?;
        }
        row.append_calculated(&values[..count], ctx.max_record)
            .with_context(|| {
                format!("input record {}, appending calculated columns", row.id + 1)
            })?;
        Ok(())
    }
}

fn scalar_value(value: &Value<'_>) -> Option<Value<'static>> {
    match value {
        Value::Text(_) => None,
        Value::Null => Some(Value::Null),
        Value::Number(number) => Some(Value::Number(*number)),
        Value::Bool(boolean) => Some(Value::Bool(*boolean)),
        Value::Date(date) => Some(Value::Date(*date)),
        Value::Timestamp(timestamp) => Some(Value::Timestamp(*timestamp)),
    }
}

impl Program {
    fn evaluate_retaining_scalar<'a>(
        &'a self,
        field: &(impl Fn(usize) -> Option<Value<'a>> + 'a),
        retain_scalar: bool,
        reserve: &mut chopper_core::expression::Reserve<'_>,
    ) -> Result<(Option<Value<'static>>, char, Cow<'a, str>)> {
        let value = self.expression.evaluate(field, reserve)?;
        let scalar = if retain_scalar {
            scalar_value(&value)
        } else {
            None
        };
        Ok((scalar, value.kind(), value.rendered(reserve)?))
    }

    fn evaluate<'a>(
        &'a self,
        field: &(impl Fn(usize) -> Option<Value<'a>> + 'a),
        reserve: &mut chopper_core::expression::Reserve<'_>,
    ) -> Result<(char, Cow<'a, str>)> {
        let value = self.expression.evaluate(field, reserve)?;
        Ok((value.kind(), value.rendered(reserve)?))
    }
}

fn reserve_scratch_bytes(scratch: &mut Reservation, bytes: usize) -> Result<()> {
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
    #[serde(default)]
    include_references: bool,
    target: Option<usize>,
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
    #[serde(skip_serializing_if = "Vec::is_empty")]
    references: Vec<usize>,
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
        include_references,
        target,
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
    let expanded = Header::with_calculations(
        header.as_deref(),
        columns,
        calculations.iter().map(|column| column.name.as_str()),
        memory.sibling(),
    )?;
    let mut programs = [const { None }; 64];
    let mut direct_references: [Vec<usize>; 64] = std::array::from_fn(|_| Vec::new());
    let mut display_bytes = 0;
    for (index, calculation) in calculations.iter().enumerate() {
        let mut reference_error = None;
        let direct = &mut direct_references[index];
        let program = if calculation.name.is_empty() {
            Err(anyhow::anyhow!(
                "enter a calculated column name. Use a unique name for the formula result"
            ))
        } else if expanded
            .iter()
            .filter(|name| **name == calculation.name)
            .count()
            > 1
        {
            Err(anyhow::anyhow!("calculated column name already exists. Choose a name that differs from all input and calculated columns"))
        } else {
            prepare(
                &calculation.expression,
                &expanded,
                columns,
                if header.is_none() { columns } else { 0 },
                memory.sibling(),
                &mut |field| {
                    if include_references && reference_error.is_none() {
                        reference_error = add_preview_reference(&mut memory, direct, field).err();
                    }
                },
            )
        };
        if let Some(error) = reference_error {
            return Err(error);
        }
        let error = match program {
            Ok(program) => {
                programs[index] = Some(program);
                None
            }
            Err(error) => Some(copy_preview_error(&mut memory, &error)?),
        };
        steps.push(PreviewStep {
            operation: calculation.operation,
            error,
            rows: Vec::new(),
            references: Vec::new(),
        });
    }
    let dependency_closure = |mut mask: u64| {
        let mut pending = mask;
        while pending != 0 {
            let index = pending.trailing_zeros() as usize;
            pending &= pending - 1;
            if let Some(program) = &programs[index] {
                pending |= program.dependencies & !mask;
                mask |= program.dependencies;
            }
        }
        mask
    };
    let needed = if let Some(operation) = target {
        let index = steps
            .iter()
            .position(|step| step.operation == operation)
            .context("unknown formula preview target")?;
        dependency_closure(1 << index)
    } else {
        u64::MAX
    };
    let mut completed = 0;
    while let Some(index) = ready(&programs[..steps.len()], completed) {
        completed |= 1 << index;
        let Some(program) = programs[index].as_ref() else {
            continue;
        };
        if needed & (1 << index) == 0 {
            continue;
        }
        let mut references = Vec::new();
        if include_references {
            let mut dependencies = dependency_closure(1 << index);
            while dependencies != 0 {
                let dependency = dependencies.trailing_zeros() as usize;
                dependencies &= dependencies - 1;
                for &field in &direct_references[dependency] {
                    add_preview_reference(&mut memory, &mut references, field)?;
                }
            }
            references.sort_unstable();
        }
        let mut step = PreviewStep {
            operation: steps[index].operation,
            error: None,
            rows: Vec::new(),
            references,
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
                        memory.copy_string(
                            "A referenced calculated column has no value for this row. Check the referenced formula for an error",
                        )?
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
        steps[index] = step;
    }
    for (index, step) in steps.iter_mut().enumerate() {
        if completed & (1 << index) == 0 {
            step.error = Some(memory.copy_string("Cyclic calculated column dependency. Edit a formula to remove its reference back to this column")?);
        }
    }
    Ok(FormulaPreview {
        functions: chopper_core::expression::FUNCTIONS,
        steps,
        _memory: memory,
    })
}

fn add_preview_reference(
    memory: &mut Reservation,
    fields: &mut Vec<usize>,
    field: usize,
) -> Result<()> {
    if !fields.contains(&field) {
        if fields.len() == fields.capacity() {
            memory.reserve_vec(fields, fields.capacity().max(2) * 2)?;
        }
        fields.push(field);
    }
    Ok(())
}

fn copy_preview_error(memory: &mut Reservation, error: &anyhow::Error) -> Result<String> {
    let message = error.to_string();
    let end = message
        .char_indices()
        .nth(256)
        .map_or(message.len(), |(i, _)| i);
    memory.copy_string(&message[..end])
}
