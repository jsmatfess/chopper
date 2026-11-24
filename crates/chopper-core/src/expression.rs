//! Shared, row-local calculation language.
use std::{borrow::Cow, cmp::Ordering, fmt, fmt::Write as _};
mod pattern;
mod temporal;

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

    fn number(self) -> EvalResult<f64> {
        match self {
            Self::Number(n) => Ok(n),
            _ => Err(row("expected a number; use NUMBER to convert text")),
        }
    }

    fn boolean(self) -> EvalResult<Option<bool>> {
        match self {
            Self::Null => Ok(None),
            Self::Bool(b) => Ok(Some(b)),
            _ => Err(row("expected a boolean condition")),
        }
    }

    fn text(self) -> EvalResult<Cow<'a, str>> {
        match self {
            Self::Text(s) => Ok(s),
            _ => Err(row("expected text; use TEXT to convert a value")),
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
        Err(row("number is not finite"))
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
                Err(format!("unknown function {name:?}"))
            }

            fn check(self, count: usize) -> Result<(), String> {
                let (min, max, signature) = match self {
                    $(Self::$name => ($min, $max, $signature),)+
                };
                if (min..=max).contains(&count) && (!matches!(self, Self::IFS) || count % 2 == 1) {
                    Ok(())
                } else {
                    Err(format!("expected {signature}"))
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
    STARTSWITH, "STARTSWITH(text, prefix)", 2, 2;
    ENDSWITH, "ENDSWITH(text, suffix)", 2, 2;
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
            return Err(format!("formula exceeds {MAX_SOURCE_BYTES} bytes"));
        }
        let mut parser = Parser { source, nodes: 0 };
        let node = parser.expression(0, 1)?;
        if !parser.source.trim_start().is_empty() {
            return Err("unexpected text after expression".into());
        }
        Ok(Self(node))
    }

    /// Resolve references against the schema immediately before this step.
    pub fn bind(
        &mut self,
        header: Option<&[String]>,
        width: usize,
        unnamed: usize,
    ) -> Result<(), String> {
        self.0.bind(header, width, unnamed)
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
            Self::Pattern(pattern) => pattern.workspace_bytes(),
            _ => 0,
        }
    }

    fn bind(
        &mut self,
        header: Option<&[String]>,
        width: usize,
        unnamed: usize,
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
                    (Some((index, _)), None) => *self = Self::Index(index),
                    _ => {
                        return Err(format!(
                            "column {name:?} is missing or ambiguous; use a zero-based index"
                        ))
                    }
                }
            }
            Self::Index(index) if *index >= width => {
                return Err(format!("column index {index} exceeds record width {width}"));
            }
            Self::Call(_, args) => {
                for arg in args {
                    arg.bind(header, width, unnamed)?;
                }
            }
            Self::Safe(node) | Self::Unary(_, node) | Self::Temporal(_, node) => {
                node.bind(header, width, unnamed)?
            }
            Self::Pattern(instruction) => instruction.bind(header, width, unnamed)?,
            Self::Binary(_, left, right) => {
                left.bind(header, width, unnamed)?;
                right.bind(header, width, unnamed)?;
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
        let first = args[0].evaluate(field, reserve)?;
        if matches!(self, Self::IS_NULL) {
            return Ok(Value::Bool(matches!(first, Value::Null)));
        }
        if matches!(first, Value::Null) {
            return Ok(Value::Null);
        }
        if matches!(self, Self::CONCAT) {
            let mut parts = [const { None }; 64];
            parts[0] = Some(first.text()?);
            for (arg, part) in args[1..].iter().zip(parts[1..].iter_mut()) {
                let value = arg.evaluate(field, reserve)?;
                if matches!(value, Value::Null) {
                    return Ok(Value::Null);
                }
                *part = Some(value.text()?);
            }
            let bytes = parts
                .iter()
                .flatten()
                .try_fold(0usize, |size, part| size.checked_add(part.len()))
                .ok_or_else(|| EvalError::System("text length overflow".into()))?;
            admitted(reserve, bytes)?;
            let mut result = String::with_capacity(bytes);
            for part in parts.into_iter().flatten() {
                result.push_str(&part);
            }
            return Ok(Value::Text(Cow::Owned(result)));
        }
        let second = if let Some(arg) = args.get(1) {
            let value = arg.evaluate(field, reserve)?;
            if matches!(value, Value::Null) {
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
                    number(text.parse().map_err(|_| row("invalid number"))?)
                }
            }
            Self::TEXT => Ok(Value::Text(first.rendered(reserve)?)),
            Self::ABS => number(first.number()?.abs()),
            Self::ROUND => {
                let places = second.map(Value::number).transpose()?.unwrap_or(0.0);
                if places.fract() != 0.0 || !(-308.0..=308.0).contains(&places) {
                    return Err(row(
                        "rounding places must be an integer from -308 through 308",
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
            Self::STARTSWITH | Self::ENDSWITH => {
                let text = first.text()?;
                let part = second.unwrap().text()?;
                Ok(Value::Bool(if matches!(self, Self::STARTSWITH) {
                    text.starts_with(part.as_ref())
                } else {
                    text.ends_with(part.as_ref())
                }))
            }
            Self::SUBSTRING => {
                let start = position(second.unwrap())?;
                let length = third.map(position).transpose()?.unwrap_or(usize::MAX);
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
            | Self::COALESCE
            | Self::CONCAT
            | Self::SAFE
            | Self::LIKE
            | Self::ILIKE
            | Self::REGEX_MATCH
            | Self::REGEX_REPLACE => {
                unreachable!()
            }
        }
    }
}

fn position(value: Value<'_>) -> EvalResult<usize> {
    let n = value.number()?;
    if n < 0.0 || n.fract() != 0.0 {
        return Err(row("substring positions must be nonnegative integers"));
    }
    Ok(n as usize)
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
    Equal,
    Different,
    Less,
    LessEqual,
    Greater,
    GreaterEqual,
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
                let ordering = match (left, right) {
                    (Value::Text(a), Value::Text(b)) => a.cmp(&b),
                    (Value::Bool(a), Value::Bool(b)) => a.cmp(&b),
                    (Value::Date(a), Value::Date(b)) => a.cmp(&b),
                    (Value::Timestamp(a), Value::Timestamp(b)) => a.compare(b),
                    (Value::Number(a), Value::Number(b)) => a
                        .partial_cmp(&b)
                        .ok_or_else(|| row("number is not finite"))?,
                    _ => return Err(row("comparison requires matching types")),
                };
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
            _ => {
                let a = left.number()?;
                let b = right.number()?;
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
            Err("formula is too deeply nested or has too many terms".into())
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
            let right = self.expression(depth + 1, precedence + 1)?;
            left = Node::Binary(op, Box::new(left), Box::new(right));
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
                    .map_err(|_| "expected a zero-based column index after $".into())
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
                    let mut args = Vec::new();
                    if !self.source.trim_start().starts_with(')') {
                        loop {
                            args.push(self.expression(depth + 1, 1)?);
                            match self.source.trim_start().strip_prefix(',') {
                                Some(rest) => self.source = rest,
                                None => break,
                            }
                        }
                    }
                    self.expect(')')?;
                    function.check(args.len())?;
                    if matches!(function, Function::SAFE) {
                        return Ok(Node::Safe(Box::new(args.pop().unwrap())));
                    }
                    let call = if matches!(
                        function,
                        Function::LIKE
                            | Function::ILIKE
                            | Function::REGEX_MATCH
                            | Function::REGEX_REPLACE
                    ) {
                        Node::Pattern(Box::new(pattern::Instruction::prepare(function, args)?))
                    } else if let Some(instruction) = temporal::prepare(function, &args)? {
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
                    return Err("expected a function call after SAFE".into());
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
            _ => Err("expected a column reference, literal, or function call".into()),
        }
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
        let value: f64 = literal.parse().map_err(|_| "invalid numeric literal")?;
        Ok(Node::Literal(
            number(value).map_err(|error| error.to_string())?,
        ))
    }

    fn quoted(&mut self, end: char) -> Result<String, String> {
        self.source = &self.source[1..];
        let mut result = String::new();
        loop {
            let (text, rest) = self.source.split_once(end).ok_or("unclosed quoted value")?;
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
        ("<=", LessEqual, 3),
        (">=", GreaterEqual, 3),
        ("<>", Different, 3),
        ("!=", Different, 3),
        ("=", Equal, 3),
        ("<", Less, 3),
        (">", Greater, 3),
        ("+", Add, 4),
        ("-", Subtract, 4),
        ("*", Multiply, 5),
        ("/", Divide, 5),
        ("%", Remainder, 5),
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
