//! Shared, row-local calculation language.
use std::{borrow::Cow, cmp::Ordering, fmt, fmt::Write as _};
mod pattern;
mod temporal;
mod text;

pub const MAX_SOURCE_BYTES: usize = 16 * 1024;
const MAX_DEPTH: usize = 64;

#[derive(Debug)]
pub struct Expression(Node);

#[derive(Debug)]
enum Node {
    Name(String),
    Index(usize),
    Literal(Value<'static>),
    Call(Function, Vec<Node>),
    Unary(Unary, Box<Node>),
    Binary(Binary, Box<Node>, Box<Node>),
    In(Box<Node>, Vec<Node>),
    Safe(Box<Node>),
    Temporal(temporal::Instruction, Box<Node>),
    Pattern(Box<pattern::Instruction>),
}

#[derive(Debug)]
pub enum Value<'a> {
    Null,
    Text(Cow<'a, str>),
    Number(f64),
    Bool(bool),
    Date(temporal::Date),
    Timestamp(temporal::Timestamp),
}

impl<'a> Value<'a> {
    pub fn from_stored(text: &'a str, kind: char) -> Option<Self> {
        match kind {
            't' => Some(Self::Text(Cow::Borrowed(text))),
            'n' => Some(Self::Null),
            'f' => text.parse().ok().map(Self::Number),
            'b' => text.parse().ok().map(Self::Bool),
            'd' => temporal::Date::canonical(text).ok().map(Self::Date),
            offset if (0x10000..0x10000 + 2880).contains(&(offset as u32)) => {
                temporal::Timestamp::canonical(text).ok().map(|ts| {
                    Self::Timestamp(ts.with_offset((offset as u32 - 0x10000) as i16 - 1440))
                })
            }
            _ => None,
        }
    }

    pub fn kind(&self) -> char {
        match self {
            Self::Null => 'n',
            Self::Text(_) => 't',
            Self::Number(_) => 'f',
            Self::Bool(_) => 'b',
            Self::Date(_) => 'd',
            Self::Timestamp(ts) => char::from_u32(0x10000 + (ts.offset() + 1440) as u32).unwrap(),
        }
    }

    pub fn rendered(self, reserve: &mut Reserve<'_>) -> EvalResult<Cow<'a, str>> {
        match self {
            Self::Null => Ok(Cow::Borrowed("")),
            Self::Text(text) => Ok(text),
            Self::Bool(true) => Ok(Cow::Borrowed("true")),
            Self::Bool(false) => Ok(Cow::Borrowed("false")),
            Self::Date(date) => {
                admitted(reserve, 10)?;
                let mut text = String::with_capacity(10);
                write!(text, "{date}").unwrap();
                Ok(Cow::Owned(text))
            }
            Self::Timestamp(ts) => {
                admitted(reserve, 30)?;
                let mut text = String::with_capacity(30);
                write!(text, "{ts}").unwrap();
                Ok(Cow::Owned(text))
            }
            Self::Number(value) => {
                // Decimal Rust display of any finite binary64 fits in this bound.
                // A counting pass avoids reserving hundreds of bytes for
                // ordinary small numeric values or hidden formatter growth.
                let mut size = TextLength::default();
                write!(size, "{value}").unwrap();
                admitted(reserve, size.0)?;
                let mut result = String::with_capacity(size.0);
                write!(result, "{value}").unwrap();
                Ok(Cow::Owned(result))
            }
        }
    }

    fn type_name(&self) -> &'static str {
        match self {
            Self::Null => "NULL",
            Self::Text(_) => "text",
            Self::Number(_) => "a number",
            Self::Bool(_) => "a Boolean",
            Self::Date(_) => "a date",
            Self::Timestamp(_) => "a timestamp",
        }
    }

    fn number(self) -> EvalResult<f64> {
        match self {
            Self::Number(n) => Ok(n),
            Self::Text(_) => Err(row(
                "expected a number, received text. Use NUMBER(...) to convert the text.",
            )),
            other => Err(row(format!(
                "expected a number, received {}. Pass a numeric value.",
                other.type_name()
            ))),
        }
    }

    fn boolean(self) -> EvalResult<Option<bool>> {
        match self {
            Self::Null => Ok(None),
            Self::Bool(b) => Ok(Some(b)),
            other => {
                let hint = match &other {
                    Self::Text(_) => "Compare the text explicitly, for example status = \"yes\".",
                    Self::Number(_) => "To test for a nonzero number, compare it to 0 with <>.",
                    _ => "Use a comparison or a predicate such as IS_NULL(...).",
                };
                Err(row(format!(
                    "expected a boolean condition, received {}. {hint}",
                    other.type_name()
                )))
            }
        }
    }

    fn text(self) -> EvalResult<Cow<'a, str>> {
        match self {
            Self::Text(s) => Ok(s),
            other => Err(row(format!(
                "expected text, received {}. Use TEXT(...) to convert the value.",
                other.type_name()
            ))),
        }
    }

    fn compare(&self, other: &Self) -> EvalResult<Ordering> {
        match (self, other) {
            (Self::Text(a), Self::Text(b)) => Ok(a.cmp(b)),
            (Self::Bool(a), Self::Bool(b)) => Ok(a.cmp(b)),
            (Self::Date(a), Self::Date(b)) => Ok(a.cmp(b)),
            (Self::Timestamp(a), Self::Timestamp(b)) => Ok(a.compare(*b)),
            (Self::Number(a), Self::Number(b)) => {
                a.partial_cmp(b).ok_or_else(|| row("number is not finite"))
            }
            _ => {
                let hint = match (self, other) {
                    (Self::Text(_), Self::Number(_)) | (Self::Number(_), Self::Text(_)) =>
                        "Use NUMBER(...) on the text for a numeric comparison.",
                    (Self::Text(_), Self::Date(_)) | (Self::Date(_), Self::Text(_)) =>
                        "Use DATE_PARSE(...) on the text for a date comparison.",
                    (Self::Text(_), Self::Timestamp(_)) | (Self::Timestamp(_), Self::Text(_)) =>
                        "Use TIMESTAMP_PARSE(...) on the text for a timestamp comparison.",
                    _ => "Compare two values of the same type, or convert both to text with TEXT(...).",
                };
                Err(row(format!(
                    "Cannot compare {} with {}. {hint}",
                    self.type_name(),
                    other.type_name()
                )))
            }
        }
    }
}

#[derive(Default)]
struct TextLength(usize);

impl fmt::Write for TextLength {
    fn write_str(&mut self, text: &str) -> fmt::Result {
        self.0 += text.len();
        Ok(())
    }
}

#[derive(Debug)]
pub enum EvalError {
    Row(String),
    System(String),
}

impl fmt::Display for EvalError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Row(message) | Self::System(message) => f.write_str(message),
        }
    }
}

impl std::error::Error for EvalError {}

type EvalResult<T> = Result<T, EvalError>;
pub type Reserve<'a> = dyn FnMut(usize) -> Result<(), String> + 'a;

fn row(message: impl Into<String>) -> EvalError {
    EvalError::Row(message.into())
}

fn admitted(reserve: &mut Reserve<'_>, bytes: usize) -> EvalResult<()> {
    reserve(bytes).map_err(EvalError::System)
}

fn number(value: f64) -> EvalResult<Value<'static>> {
    if value.is_finite() {
        Ok(Value::Number(value))
    } else {
        Err(row("number is not finite. Check the inputs and use a smaller magnitude or a valid numeric range."))
    }
}

macro_rules! functions {
    ($($name:ident, $signature:literal, $min:literal, $max:literal;)+) => {
        #[allow(clippy::upper_case_acronyms, non_camel_case_types)]
        #[derive(Clone, Copy, Debug)]
        enum Function { $($name),+ }

        pub const FUNCTIONS: &[(&str, &str)] = &[$((stringify!($name), $signature)),+];

        impl Function {
            fn parse(name: &str) -> Result<Self, String> {
                $(if name.eq_ignore_ascii_case(stringify!($name)) { return Ok(Self::$name); })+
                Err(format!("unknown function {name:?}. Check the spelling in the formula function reference."))
            }

            fn check(self, args: &[Node]) -> Result<(), String> {
                let count = args.len();
                let (min, max, signature) = match self {
                    $(Self::$name => ($min, $max, $signature),)+
                };
                if (min..=max).contains(&count)
                    && (!matches!(self, Self::IFS) || count % 2 == 1)
                    && (!matches!(self, Self::CONCAT_WS)
                        || (1..=63).contains(&text::concat_options(&args[1..]).0.len()))
                {
                    Ok(())
                } else {
                    Err(format!("expected {signature}, received {count} arguments. Check the required arguments and their order."))
                }
            }
        }
    }
}

functions! {
    TRIM, "TRIM(text)", 1, 1;
    UPPER, "UPPER(text)", 1, 1;
    LOWER, "LOWER(text)", 1, 1;
    CONCAT, "CONCAT(text, ...)", 1, 64;
    REPLACE, "REPLACE(text, search, replacement)", 3, 3;
    STARTSWITH, "STARTSWITH(text, prefix, ignore_case?)", 2, 3;
    ENDSWITH, "ENDSWITH(text, suffix, ignore_case?)", 2, 3;
    SUBSTRING, "SUBSTRING(text, start, length?)", 2, 3;
    NUMBER, "NUMBER(text)", 1, 1;
    TEXT, "TEXT(value)", 1, 1;
    ABS, "ABS(number)", 1, 1;
    ROUND, "ROUND(number, places?)", 1, 2;
    IF, "IF(condition, when_true, when_false)", 3, 3;
    IFS, "IFS(condition, value, ..., fallback)", 3, 63;
    IS_NULL, "IS_NULL(value)", 1, 1;
    COALESCE, "COALESCE(value, ...)", 1, 64;
    SAFE, "SAFE(expression)", 1, 1;
    IS_ERROR, "IS_ERROR(expression)", 1, 1;
    DATE_PARSE, "DATE_PARSE(text, format?)", 1, 2;
    DATE_FORMAT, "DATE_FORMAT(date, format)", 2, 2;
    DATE_EXTRACT, "DATE_EXTRACT(date, part)", 2, 2;
    DATE_TRUNC, "DATE_TRUNC(date, unit)", 2, 2;
    TIMESTAMP_PARSE, "TIMESTAMP_PARSE(text, format?)", 1, 2;
    TIMESTAMP_FORMAT, "TIMESTAMP_FORMAT(timestamp, format, basis?)", 2, 3;
    TIMESTAMP_EXTRACT, "TIMESTAMP_EXTRACT(timestamp, part, basis?)", 2, 3;
    TIMESTAMP_TRUNC, "TIMESTAMP_TRUNC(timestamp, unit, basis?)", 2, 3;
    LIKE, "LIKE(text, pattern)", 2, 2;
    ILIKE, "ILIKE(text, pattern)", 2, 2;
    REGEX_MATCH, "REGEX_MATCH(text, pattern)", 2, 2;
    REGEX_REPLACE, "REGEX_REPLACE(text, pattern, replacement)", 3, 3;
    LEFT, "LEFT(text, count)", 2, 2;
    RIGHT, "RIGHT(text, count)", 2, 2;
    LENGTH, "LENGTH(text)", 1, 1;
    CONTAINS, "CONTAINS(text, search, ignore_case?)", 2, 3;
    NULLIF, "NULLIF(value, match)", 2, 2;
    IS_BLANK, "IS_BLANK(text)", 1, 1;
    SPLIT_PART, "SPLIT_PART(text, delimiter, index)", 3, 3;
    LTRIM, "LTRIM(text)", 1, 1;
    RTRIM, "RTRIM(text)", 1, 1;
    FLOOR, "FLOOR(number)", 1, 1;
    CEIL, "CEIL(number)", 1, 1;
    STRIP_PREFIX, "STRIP_PREFIX(text, prefix, ignore_case?)", 2, 3;
    STRIP_SUFFIX, "STRIP_SUFFIX(text, suffix, ignore_case?)", 2, 3;
    TEXT_BEFORE, "TEXT_BEFORE(text, delimiter, ignore_case?)", 2, 3;
    TEXT_AFTER, "TEXT_AFTER(text, delimiter, ignore_case?)", 2, 3;
    IS_ASCII, "IS_ASCII(text)", 1, 1;
    IS_DIGITS, "IS_DIGITS(text)", 1, 1;
    BYTE_LENGTH, "BYTE_LENGTH(text)", 1, 1;
    TRANSLATE, "TRANSLATE(text, from, to)", 3, 3;
    LPAD, "LPAD(text, width, pad?)", 2, 3;
    RPAD, "RPAD(text, width, pad?)", 2, 3;
    REPEAT, "REPEAT(text, count)", 2, 2;
    CONCAT_WS, "CONCAT_WS(separator, text, ..., ignore_null?, ignore_empty?)", 2, 66;
    BETWEEN, "BETWEEN(value, lower, upper)", 3, 3;
    IS_TEXT, "IS_TEXT(value)", 1, 1;
    IS_NUMBER, "IS_NUMBER(value)", 1, 1;
    IS_BOOLEAN, "IS_BOOLEAN(value)", 1, 1;
    TRUNC, "TRUNC(number)", 1, 1;
    SQRT, "SQRT(number)", 1, 1;
    POWER, "POWER(base, exponent)", 2, 2;
    LN, "LN(number)", 1, 1;
    LOG10, "LOG10(number)", 1, 1;
    EXP, "EXP(number)", 1, 1;
    BUCKET, "BUCKET(number, width, origin?)", 2, 3;
    DATE_FROM_PARTS, "DATE_FROM_PARTS(year, month, day)", 3, 3;
    DATE_ADD_DAYS, "DATE_ADD_DAYS(date, count)", 2, 2;
    DATE_DIFF_DAYS, "DATE_DIFF_DAYS(start, end)", 2, 2;
    DATE_WEEKDAY, "DATE_WEEKDAY(date)", 1, 1;
    DATE_IS_WEEKEND, "DATE_IS_WEEKEND(date)", 1, 1;
    DATE_END_OF_MONTH, "DATE_END_OF_MONTH(date)", 1, 1;
    DATE_ADD_MONTHS, "DATE_ADD_MONTHS(date, count)", 2, 2;
    DATE_ISO_WEEK, "DATE_ISO_WEEK(date)", 1, 1;
    DATE_ISO_WEEK_YEAR, "DATE_ISO_WEEK_YEAR(date)", 1, 1;
    TIMESTAMP_ADD_SECONDS, "TIMESTAMP_ADD_SECONDS(timestamp, count)", 2, 2;
    TIMESTAMP_DIFF_SECONDS, "TIMESTAMP_DIFF_SECONDS(start, end)", 2, 2;
    TIMESTAMP_FROM_UNIX, "TIMESTAMP_FROM_UNIX(seconds)", 1, 1;
    TIMESTAMP_TO_UNIX, "TIMESTAMP_TO_UNIX(timestamp)", 1, 1;
    REGEX_EXTRACT, "REGEX_EXTRACT(text, pattern, group?)", 2, 3;
}

type Field<'a> = dyn Fn(usize) -> Option<Value<'a>> + 'a;

impl Expression {
    pub fn preparation_bytes(source: &str) -> usize {
        let bytes = &source.as_bytes()[..source.len().min(MAX_SOURCE_BYTES)];
        let mut cursor = 0;
        let mut pattern_words = 0;
        while let Some(&byte) = bytes.get(cursor) {
            if matches!(byte, b'"' | b'[') {
                let end = if byte == b'[' { b']' } else { b'"' };
                cursor += 1;
                while let Some(offset) = bytes[cursor..].iter().position(|&value| value == end) {
                    cursor += offset + 1;
                    if bytes.get(cursor) != Some(&end) {
                        break;
                    }
                    cursor += 1;
                }
            } else if byte.is_ascii_alphabetic() || byte == b'_' {
                let start = cursor;
                cursor += 1;
                while bytes
                    .get(cursor)
                    .is_some_and(|b| b.is_ascii_alphanumeric() || *b == b'_')
                {
                    cursor += 1;
                }
                if [
                    b"LIKE".as_slice(),
                    b"ILIKE",
                    b"REGEX_MATCH",
                    b"REGEX_REPLACE",
                    b"REGEX_EXTRACT",
                ]
                .iter()
                .any(|name| bytes[start..cursor].eq_ignore_ascii_case(name))
                {
                    pattern_words += 1;
                }
            } else {
                cursor += 1;
            }
        }
        // Source spelling bounds the tree and literal data. Counted repeats
        // can expand the pattern program independently of its source length.
        bytes.len() * 128 + pattern_words * pattern::PROGRAM_ALLOCATION_BOUND
    }

    pub fn parse(source: &str) -> Result<Self, String> {
        if source.len() > MAX_SOURCE_BYTES {
            return Err(format!("formula exceeds {MAX_SOURCE_BYTES} bytes. Split it into smaller calculated columns."));
        }
        let mut parser = Parser { source, nodes: 0 };
        let node = parser.expression(0, 1)?;
        if !parser.source.trim_start().is_empty() {
            return Err("unexpected text after expression. Check for a missing operator or an extra closing parenthesis.".into());
        }
        Ok(Self(node))
    }

    /// Resolve references against the source and calculated-column schema.
    pub fn bind(
        &mut self,
        header: Option<&[String]>,
        width: usize,
        unnamed: usize,
    ) -> Result<(), String> {
        self.bind_references(header, width, unnamed, &mut |_| {})
    }

    pub fn bind_references(
        &mut self,
        header: Option<&[String]>,
        width: usize,
        unnamed: usize,
        reference: &mut impl FnMut(usize),
    ) -> Result<(), String> {
        self.0.bind(header, width, unnamed, reference)
    }

    pub fn workspace_bytes(&self) -> usize {
        self.0.workspace_bytes()
    }

    pub fn evaluate<'a>(
        &'a self,
        field: &Field<'a>,
        reserve: &mut Reserve<'_>,
    ) -> EvalResult<Value<'a>> {
        self.0.evaluate(field, reserve)
    }
}

impl Node {
    fn workspace_bytes(&self) -> usize {
        match self {
            Self::Call(_, args) => args.iter().map(Self::workspace_bytes).sum(),
            Self::Unary(_, arg) | Self::Safe(arg) | Self::Temporal(_, arg) => arg.workspace_bytes(),
            Self::Binary(_, left, right) => left.workspace_bytes() + right.workspace_bytes(),
            Self::In(value, items) => {
                value.workspace_bytes() + items.iter().map(Self::workspace_bytes).sum::<usize>()
            }
            Self::Pattern(pattern) => pattern.workspace_bytes(),
            _ => 0,
        }
    }

    fn bind(
        &mut self,
        header: Option<&[String]>,
        width: usize,
        unnamed: usize,
        reference: &mut impl FnMut(usize),
    ) -> Result<(), String> {
        match self {
            Self::Name(name) => {
                let mut matches = header
                    .unwrap_or_default()
                    .iter()
                    .enumerate()
                    .skip(unnamed)
                    .filter(|(_, candidate)| *candidate == name);
                match (matches.next(), matches.next()) {
                    (Some((index, _)), None) => {
                        reference(index);
                        *self = Self::Index(index);
                    }
                    _ => {
                        return Err(format!(
                            "column {name:?} is missing or ambiguous. Check the exact header or use a zero-based index such as $0"
                        ))
                    }
                }
            }
            Self::Index(index) if *index >= width => {
                return Err(format!("column index ${index} is outside the {width}-column formula schema. Indexes start at $0."));
            }
            Self::Index(index) => reference(*index),
            Self::Call(_, args) => {
                for arg in args {
                    arg.bind(header, width, unnamed, reference)?;
                }
            }
            Self::Safe(node) | Self::Unary(_, node) | Self::Temporal(_, node) => {
                node.bind(header, width, unnamed, reference)?
            }
            Self::Pattern(instruction) => instruction.bind(header, width, unnamed, reference)?,
            Self::Binary(_, left, right) => {
                left.bind(header, width, unnamed, reference)?;
                right.bind(header, width, unnamed, reference)?;
            }
            Self::In(value, items) => {
                value.bind(header, width, unnamed, reference)?;
                for item in items {
                    item.bind(header, width, unnamed, reference)?;
                }
            }
            _ => {}
        }
        Ok(())
    }

    fn evaluate<'a>(
        &'a self,
        field: &Field<'a>,
        reserve: &mut Reserve<'_>,
    ) -> EvalResult<Value<'a>> {
        match self {
            Self::Name(name) => Err(EvalError::System(format!("unbound column {name:?}"))),
            Self::Index(index) => field(*index)
                .ok_or_else(|| EvalError::System(format!("missing column at index {index}"))),
            Self::Literal(value) => Ok(match value {
                Value::Text(text) => Value::Text(Cow::Borrowed(text)),
                Value::Null => Value::Null,
                Value::Number(n) => Value::Number(*n),
                Value::Bool(b) => Value::Bool(*b),
                Value::Date(date) => Value::Date(*date),
                Value::Timestamp(ts) => Value::Timestamp(*ts),
            }),
            Self::Temporal(instruction, node) => {
                instruction.evaluate(node.evaluate(field, reserve)?, reserve)
            }
            Self::Pattern(instruction) => instruction.evaluate(field, reserve),
            Self::Safe(node) => match node.evaluate(field, reserve) {
                Err(EvalError::Row(_)) => Ok(Value::Null),
                result => result,
            },
            Self::Call(function, args) => function.evaluate(args, field, reserve),
            Self::Unary(operator, arg) => {
                let value = arg.evaluate(field, reserve)?;
                if matches!(value, Value::Null) {
                    return Ok(Value::Null);
                }
                match operator {
                    Unary::Plus => Ok(Value::Number(value.number()?)),
                    Unary::Minus => number(-value.number()?),
                    Unary::Not => Ok(Value::Bool(!value.boolean()?.unwrap())),
                }
            }
            Self::Binary(op, left, right) => {
                let left = left.evaluate(field, reserve)?;
                op.evaluate(left, || right.evaluate(field, reserve))
            }
            Self::In(value, items) => {
                let value = value.evaluate(field, reserve)?;
                if matches!(value, Value::Null) {
                    return Ok(Value::Null);
                }
                let mut saw_null = false;
                for item in items {
                    let item = item.evaluate(field, reserve)?;
                    if matches!(item, Value::Null) {
                        saw_null = true;
                    } else if value.compare(&item)? == Ordering::Equal {
                        return Ok(Value::Bool(true));
                    }
                }
                Ok(if saw_null {
                    Value::Null
                } else {
                    Value::Bool(false)
                })
            }
        }
    }
}

impl Function {
    fn evaluate<'a>(
        self,
        args: &'a [Node],
        field: &Field<'a>,
        reserve: &mut Reserve<'_>,
    ) -> EvalResult<Value<'a>> {
        if matches!(self, Self::IFS | Self::IF) {
            let (fallback, cases) = args.split_last().unwrap();
            for case in cases.as_chunks::<2>().0 {
                if case[0].evaluate(field, reserve)?.boolean()? == Some(true) {
                    return case[1].evaluate(field, reserve);
                }
            }
            return fallback.evaluate(field, reserve);
        }
        if matches!(self, Self::COALESCE) {
            for arg in args {
                let value = arg.evaluate(field, reserve)?;
                if !matches!(value, Value::Null) {
                    return Ok(value);
                }
            }
            return Ok(Value::Null);
        }
        if matches!(self, Self::IS_ERROR) {
            return match args[0].evaluate(field, reserve) {
                Err(EvalError::Row(_)) => Ok(Value::Bool(true)),
                result => result.map(|_| Value::Bool(false)),
            };
        }
        let first = args[0].evaluate(field, reserve)?;
        let predicate = match self {
            Self::IS_NULL => Some(matches!(first, Value::Null)),
            Self::IS_TEXT => Some(matches!(first, Value::Text(_))),
            Self::IS_NUMBER => Some(matches!(first, Value::Number(_))),
            Self::IS_BOOLEAN => Some(matches!(first, Value::Bool(_))),
            Self::IS_BLANK => {
                return Ok(Value::Bool(match first {
                    Value::Null => true,
                    _ => first.text()?.trim().is_empty(),
                }))
            }
            _ => None,
        };
        if let Some(value) = predicate {
            return Ok(Value::Bool(value));
        }
        if matches!(first, Value::Null) {
            return Ok(Value::Null);
        }
        if matches!(self, Self::CONCAT | Self::CONCAT_WS) {
            return text::concat(self, first, &args[1..], field, reserve);
        }
        let second = if let Some(arg) = args.get(1) {
            let value = arg.evaluate(field, reserve)?;
            if matches!(value, Value::Null) && !matches!(self, Self::NULLIF) {
                return Ok(Value::Null);
            }
            Some(value)
        } else {
            None
        };
        let third = if let Some(arg) = args.get(2) {
            let value = arg.evaluate(field, reserve)?;
            if matches!(value, Value::Null) {
                return Ok(Value::Null);
            }
            Some(value)
        } else {
            None
        };
        match self {
            Self::TRIM => text_slice(first.text()?, |text| {
                let start = text.len() - text.trim_start().len();
                start..text.trim_end().len().max(start)
            }),
            Self::UPPER | Self::LOWER => {
                let text = first.text()?;
                // Bound the output before invoking Rust's Unicode case conversion.
                let bytes = if matches!(self, Self::UPPER) {
                    text.chars()
                        .flat_map(char::to_uppercase)
                        .map(char::len_utf8)
                        .sum()
                } else {
                    text.chars()
                        .flat_map(char::to_lowercase)
                        .map(char::len_utf8)
                        .sum()
                };
                admitted(reserve, bytes)?;
                // Rust lowercasing includes the context-dependent final sigma.
                let mut result = String::with_capacity(bytes);
                if matches!(self, Self::UPPER) {
                    result.extend(text.chars().flat_map(char::to_uppercase));
                } else if text.is_ascii() {
                    result.extend(text.bytes().map(|b| char::from(b.to_ascii_lowercase())));
                } else {
                    // str::to_lowercase can reserve extra capacity as it grows.
                    admitted(reserve, bytes.saturating_mul(2).saturating_add(8))?;
                    result = text.to_lowercase();
                }
                Ok(Value::Text(Cow::Owned(result)))
            }
            Self::NUMBER => {
                let text = first.text()?;
                if text.is_empty() {
                    Ok(Value::Null)
                } else {
                    number(text.parse().map_err(|_| row("invalid number. Give NUMBER text such as \"42\". Use TRIM(...) first to remove surrounding whitespace."))?)
                }
            }
            Self::TEXT => Ok(Value::Text(first.rendered(reserve)?)),
            Self::ABS => number(first.number()?.abs()),
            Self::FLOOR => number(first.number()?.floor()),
            Self::CEIL => number(first.number()?.ceil()),
            Self::TRUNC => number(first.number()?.trunc()),
            Self::SQRT => number(first.number()?.sqrt()),
            Self::POWER => number(first.number()?.powf(second.unwrap().number()?)),
            Self::LN => number(first.number()?.ln()),
            Self::LOG10 => number(first.number()?.log10()),
            Self::EXP => number(first.number()?.exp()),
            Self::BUCKET => {
                let width = second.unwrap().number()?;
                if width <= 0.0 {
                    return Err(row(
                        "BUCKET width must be positive. Pass a number greater than zero for width.",
                    ));
                }
                let origin = third.map(Value::number).transpose()?.unwrap_or(0.0);
                let offset = first.number()? - origin;
                let quotient = offset / width;
                // Division may underflow to zero even though the value is below the origin.
                let bucket = if quotient == 0.0 && offset < 0.0 {
                    -1.0
                } else {
                    quotient.floor()
                };
                number(bucket * width + origin)
            }
            Self::BETWEEN => {
                let lower = first.compare(&second.unwrap())?;
                let upper = first.compare(&third.unwrap())?;
                Ok(Value::Bool(
                    lower != Ordering::Less && upper != Ordering::Greater,
                ))
            }
            Self::NULLIF => {
                let other = second.unwrap();
                if !matches!(other, Value::Null) && first.compare(&other)? == Ordering::Equal {
                    Ok(Value::Null)
                } else {
                    Ok(first)
                }
            }
            Self::ROUND => {
                let places = second.map(Value::number).transpose()?.unwrap_or(0.0);
                if places.fract() != 0.0 || !(-308.0..=308.0).contains(&places) {
                    return Err(row(
                        "ROUND places must be an integer from -308 through 308. Omit places to round to a whole number.",
                    ));
                }
                let factor = 10_f64.powi(places as i32);
                let value = first.number()?;
                let scaled = value * factor;
                number(if places > 0.0 && !scaled.is_finite() {
                    value
                } else {
                    scaled.round() / factor
                })
            }
            Self::SUBSTRING => {
                let start = position(second.unwrap(), "start")?;
                let length = third
                    .map(|value| position(value, "length"))
                    .transpose()?
                    .unwrap_or(usize::MAX);
                text_slice(first.text()?, |text| {
                    let mut chars = text.char_indices();
                    let Some((start, _)) = chars.nth(start) else {
                        return text.len()..text.len();
                    };
                    let end = if length == 0 {
                        start
                    } else {
                        chars.nth(length - 1).map_or(text.len(), |(end, _)| end)
                    };
                    start..end
                })
            }
            Self::REPLACE => {
                let text = first.text()?;
                let needle = second.unwrap().text()?;
                let replacement = third.unwrap().text()?;
                let matches = text.match_indices(needle.as_ref()).count();
                let bytes = replacement
                    .len()
                    .checked_mul(matches)
                    .and_then(|added| (text.len() - needle.len() * matches).checked_add(added))
                    .ok_or_else(|| EvalError::System("replacement length overflow".into()))?;
                admitted(reserve, bytes)?;
                let mut result = String::with_capacity(bytes);
                let mut start = 0;
                for (index, matched) in text.match_indices(needle.as_ref()) {
                    result.push_str(&text[start..index]);
                    result.push_str(&replacement);
                    start = index + matched.len();
                }
                result.push_str(&text[start..]);
                Ok(Value::Text(Cow::Owned(result)))
            }
            Self::LEFT
            | Self::RIGHT
            | Self::LENGTH
            | Self::BYTE_LENGTH
            | Self::LTRIM
            | Self::RTRIM
            | Self::STARTSWITH
            | Self::ENDSWITH
            | Self::CONTAINS
            | Self::STRIP_PREFIX
            | Self::STRIP_SUFFIX
            | Self::SPLIT_PART
            | Self::TEXT_BEFORE
            | Self::TEXT_AFTER
            | Self::IS_ASCII
            | Self::IS_DIGITS
            | Self::TRANSLATE
            | Self::LPAD
            | Self::RPAD
            | Self::REPEAT => text::evaluate(self, first.text()?, second, third, reserve),
            Self::DATE_FROM_PARTS
            | Self::DATE_ADD_DAYS
            | Self::DATE_DIFF_DAYS
            | Self::DATE_WEEKDAY
            | Self::DATE_IS_WEEKEND
            | Self::DATE_END_OF_MONTH
            | Self::DATE_ADD_MONTHS
            | Self::DATE_ISO_WEEK
            | Self::DATE_ISO_WEEK_YEAR
            | Self::TIMESTAMP_ADD_SECONDS
            | Self::TIMESTAMP_DIFF_SECONDS
            | Self::TIMESTAMP_FROM_UNIX
            | Self::TIMESTAMP_TO_UNIX => temporal::arithmetic(self, first, second, third),
            Self::DATE_PARSE
            | Self::DATE_FORMAT
            | Self::DATE_EXTRACT
            | Self::DATE_TRUNC
            | Self::TIMESTAMP_PARSE
            | Self::TIMESTAMP_FORMAT
            | Self::TIMESTAMP_EXTRACT
            | Self::TIMESTAMP_TRUNC
            | Self::IF
            | Self::IFS
            | Self::IS_NULL
            | Self::IS_ERROR
            | Self::IS_TEXT
            | Self::IS_NUMBER
            | Self::IS_BOOLEAN
            | Self::IS_BLANK
            | Self::COALESCE
            | Self::CONCAT
            | Self::CONCAT_WS
            | Self::SAFE
            | Self::LIKE
            | Self::ILIKE
            | Self::REGEX_MATCH
            | Self::REGEX_REPLACE
            | Self::REGEX_EXTRACT => {
                unreachable!()
            }
        }
    }
}

fn position(value: Value<'_>, argument: &str) -> EvalResult<usize> {
    let n = value.number()?;
    if n < 0.0 || n.fract() != 0.0 {
        return Err(row(format!(
            "{argument} must be a nonnegative whole number. Use 0 or a positive integer."
        )));
    }
    Ok(n as usize)
}

fn chars_equal_ignore_case(left: char, right: char) -> bool {
    left.eq_ignore_ascii_case(&right)
        || (!(left.is_ascii() && right.is_ascii())
            && (left.to_lowercase().eq(right.to_lowercase())
                || left.to_uppercase().eq(right.to_uppercase())))
}

fn text_slice(
    value: Cow<'_, str>,
    range: impl FnOnce(&str) -> std::ops::Range<usize>,
) -> EvalResult<Value<'_>> {
    let range = range(&value);
    match value {
        Cow::Borrowed(text) => Ok(Value::Text(Cow::Borrowed(&text[range]))),
        Cow::Owned(mut text) => {
            text.truncate(range.end);
            text.drain(..range.start);
            Ok(Value::Text(Cow::Owned(text)))
        }
    }
}

#[derive(Debug)]
enum Unary {
    Plus,
    Minus,
    Not,
}

#[derive(Clone, Copy, Debug)]
enum Binary {
    Or,
    And,
    In,
    Equal,
    Different,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
    Concat,
    Add,
    Subtract,
    Multiply,
    Divide,
    Remainder,
}

impl Binary {
    fn evaluate<'a>(
        self,
        left: Value<'a>,
        right: impl FnOnce() -> EvalResult<Value<'a>>,
    ) -> EvalResult<Value<'a>> {
        if matches!(self, Self::And | Self::Or) {
            let terminal = matches!(self, Self::Or);
            let left = left.boolean()?;
            if left == Some(terminal) {
                return Ok(Value::Bool(terminal));
            }
            let right = right()?.boolean()?;
            return Ok(match (left, right) {
                (_, Some(value)) if value == terminal => Value::Bool(terminal),
                (Some(_), Some(value)) => Value::Bool(value),
                _ => Value::Null,
            });
        }
        let right = right()?;
        if matches!(left, Value::Null) || matches!(right, Value::Null) {
            return Ok(Value::Null);
        }
        match self {
            Self::Equal
            | Self::Different
            | Self::Less
            | Self::LessEqual
            | Self::Greater
            | Self::GreaterEqual => {
                let ordering = left.compare(&right)?;
                Ok(Value::Bool(match self {
                    Self::Equal => ordering == Ordering::Equal,
                    Self::Different => ordering != Ordering::Equal,
                    Self::Less => ordering == Ordering::Less,
                    Self::LessEqual => ordering != Ordering::Greater,
                    Self::Greater => ordering == Ordering::Greater,
                    Self::GreaterEqual => ordering != Ordering::Less,
                    _ => unreachable!(),
                }))
            }
            Self::In | Self::Concat => unreachable!("operator is lowered during parsing"),
            _ => {
                let a = left.number()?;
                let b = right.number()?;
                if b == 0.0 && matches!(self, Self::Divide | Self::Remainder) {
                    return Err(row("Cannot divide by zero. Use a nonzero divisor or wrap the operation in SAFE(...) to return NULL."));
                }
                number(match self {
                    Self::Add => a + b,
                    Self::Subtract => a - b,
                    Self::Multiply => a * b,
                    Self::Divide => a / b,
                    Self::Remainder => a % b,
                    _ => unreachable!(),
                })
            }
        }
    }
}

struct Parser<'a> {
    source: &'a str,
    nodes: usize,
}

impl<'a> Parser<'a> {
    fn count(&mut self, depth: usize) -> Result<(), String> {
        self.nodes += 1;
        if depth >= MAX_DEPTH || self.nodes > 256 {
            Err("formula is too deeply nested or has too many terms. Split it into smaller calculated columns.".into())
        } else {
            Ok(())
        }
    }

    fn expression(&mut self, depth: usize, minimum: u8) -> Result<Node, String> {
        let mut left = self.atom(depth)?;
        while let Some((op, precedence, rest)) = operator(self.source.trim_start()) {
            if precedence < minimum {
                break;
            }
            self.count(depth)?;
            self.source = rest;
            left = if matches!(op, Binary::In) {
                self.expect('(')?;
                let items = self.arguments(depth + 1)?;
                if items.is_empty() {
                    return Err("IN requires at least one item. Write a nonempty list such as country IN (\"US\").".into());
                }
                Node::In(Box::new(left), items)
            } else {
                let right = self.expression(depth + 1, precedence + 1)?;
                match (op, left) {
                    (Binary::Concat, Node::Call(Function::CONCAT, mut parts))
                        if parts.len() < 64 =>
                    {
                        parts.push(right);
                        Node::Call(Function::CONCAT, parts)
                    }
                    (Binary::Concat, left) => Node::Call(Function::CONCAT, vec![left, right]),
                    (op, left) => Node::Binary(op, Box::new(left), Box::new(right)),
                }
            };
        }
        Ok(left)
    }

    fn atom(&mut self, depth: usize) -> Result<Node, String> {
        self.count(depth)?;
        self.source = self.source.trim_start();
        match self.source.chars().next() {
            Some('"') => Ok(Node::Literal(Value::Text(Cow::Owned(self.quoted('"')?)))),
            Some('[') => self.quoted(']').map(Node::Name),
            Some('$') => {
                self.source = &self.source[1..];
                self.take(|c| c.is_ascii_digit())
                    .parse()
                    .map(Node::Index)
                    .map_err(|_| "expected a zero-based column index after $. Use a reference such as $0.".into())
            }
            Some('(') => {
                self.source = &self.source[1..];
                let node = self.expression(depth + 1, 1)?;
                self.expect(')')?;
                Ok(node)
            }
            Some('+' | '-') => {
                let op = if self.source.starts_with('+') {
                    Unary::Plus
                } else {
                    Unary::Minus
                };
                self.source = &self.source[1..];
                Ok(Node::Unary(op, Box::new(self.atom(depth + 1)?)))
            }
            Some(c) if c.is_ascii_digit() || c == '.' => self.numeric(),
            Some(c) if c.is_alphabetic() || c == '_' => {
                let name = self.take(word_char);
                if name.eq_ignore_ascii_case("NOT") {
                    return Ok(Node::Unary(
                        Unary::Not,
                        Box::new(self.expression(depth + 1, 3)?),
                    ));
                }
                self.source = self.source.trim_start();
                let mut safe = false;
                let name = if name.eq_ignore_ascii_case("SAFE") {
                    if let Some(rest) = self.source.strip_prefix('.') {
                        self.source = rest;
                        safe = true;
                        self.take(word_char)
                    } else {
                        name
                    }
                } else {
                    name
                };
                if let Some(rest) = self.source.strip_prefix('(') {
                    self.source = rest;
                    let function = Function::parse(name)?;
                    let mut args = self.arguments(depth + 1).map_err(|error| format!("{function:?}: {error}"))?;
                    function.check(&args)?;
                    if matches!(function, Function::SAFE) {
                        return Ok(Node::Safe(Box::new(args.pop().unwrap())));
                    }
                    let call = if matches!(
                        function,
                        Function::LIKE
                            | Function::ILIKE
                            | Function::REGEX_MATCH
                            | Function::REGEX_REPLACE
                            | Function::REGEX_EXTRACT
                    ) {
                        Node::Pattern(Box::new(pattern::Instruction::prepare(function, args).map_err(|error| format!("{function:?}: {error}"))?))
                    } else if let Some(instruction) = temporal::prepare(function, &args).map_err(|error| format!("{function:?}: {error}"))? {
                        Node::Temporal(instruction, Box::new(args.remove(0)))
                    } else {
                        Node::Call(function, args)
                    };
                    return Ok(if safe {
                        Node::Safe(Box::new(call))
                    } else {
                        call
                    });
                }
                if safe {
                    return Err("expected a function call after SAFE. Use SAFE(expression) or SAFE.NUMBER(text).".into());
                }
                if name.eq_ignore_ascii_case("NULL") {
                    Ok(Node::Literal(Value::Null))
                } else if name.eq_ignore_ascii_case("TRUE") {
                    Ok(Node::Literal(Value::Bool(true)))
                } else if name.eq_ignore_ascii_case("FALSE") {
                    Ok(Node::Literal(Value::Bool(false)))
                } else {
                    Ok(Node::Name(name.into()))
                }
            }
            _ => Err("expected a column reference, literal, or function call. Check for a missing argument or an incomplete expression.".into()),
        }
    }

    fn arguments(&mut self, depth: usize) -> Result<Vec<Node>, String> {
        let mut args = Vec::new();
        if !self.source.trim_start().starts_with(')') {
            loop {
                args.push(self.expression(depth, 1)?);
                match self.source.trim_start().strip_prefix(',') {
                    Some(rest) => self.source = rest,
                    None => break,
                }
            }
        }
        self.expect(')')?;
        Ok(args)
    }

    fn numeric(&mut self) -> Result<Node, String> {
        let start = self.source;
        self.take(|c| c.is_ascii_digit());
        if let Some(rest) = self.source.strip_prefix('.') {
            self.source = rest;
            self.take(|c| c.is_ascii_digit());
        }
        if let Some(rest) = self.source.strip_prefix(['e', 'E']) {
            self.source = rest.strip_prefix(['+', '-']).unwrap_or(rest);
            self.take(|c| c.is_ascii_digit());
        }
        let literal = &start[..start.len() - self.source.len()];
        let value: f64 = literal
            .parse()
            .map_err(|_| "invalid numeric literal. Use a number such as 42, 3.5, or 1e6.")?;
        Ok(Node::Literal(
            number(value).map_err(|error| error.to_string())?,
        ))
    }

    fn quoted(&mut self, end: char) -> Result<String, String> {
        self.source = &self.source[1..];
        let mut result = String::new();
        loop {
            let (text, rest) = self.source.split_once(end).ok_or({
                if end == ']' {
                    "unclosed column reference. Close it with ] and double any ] within the name."
                } else {
                    "unclosed quoted value. Close the text with a double quote and double any embedded quotes."
                }
            })?;
            result.push_str(text);
            if let Some(rest) = rest.strip_prefix(end) {
                self.source = rest;
                result.push(end);
            } else {
                self.source = rest;
                return Ok(result);
            }
        }
    }

    fn expect(&mut self, token: char) -> Result<(), String> {
        self.source = self
            .source
            .trim_start()
            .strip_prefix(token)
            .ok_or_else(|| format!("expected {token}"))?;
        Ok(())
    }

    fn take(&mut self, accepts: impl Fn(char) -> bool) -> &'a str {
        let end = self
            .source
            .find(|c| !accepts(c))
            .unwrap_or(self.source.len());
        let (value, rest) = self.source.split_at(end);
        self.source = rest;
        value
    }
}

fn word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

fn operator(source: &str) -> Option<(Binary, u8, &str)> {
    use Binary::*;
    for (token, op, precedence) in [
        ("OR", Or, 1),
        ("AND", And, 2),
        ("IN", In, 3),
        ("<=", LessEqual, 3),
        (">=", GreaterEqual, 3),
        ("<>", Different, 3),
        ("!=", Different, 3),
        ("=", Equal, 3),
        ("<", Less, 3),
        (">", Greater, 3),
        ("&", Concat, 4),
        ("+", Add, 5),
        ("-", Subtract, 5),
        ("*", Multiply, 6),
        ("/", Divide, 6),
        ("%", Remainder, 6),
    ] {
        let Some(prefix) = source.get(..token.len()) else {
            continue;
        };
        let rest = &source[token.len()..];
        if prefix.eq_ignore_ascii_case(token)
            && (!token.as_bytes()[0].is_ascii_alphabetic() || !rest.starts_with(word_char))
        {
            return Some((op, precedence, rest));
        }
    }
    None
}
