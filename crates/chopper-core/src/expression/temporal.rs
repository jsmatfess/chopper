use super::{admitted, row, EvalResult, Function, Node, Reserve, Value};
use std::{borrow::Cow, cmp::Ordering, fmt, fmt::Write};

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Date {
    year: u16,
    month: u8,
    day: u8,
}

impl Date {
    pub(super) fn canonical(text: &str) -> Result<Self, String> {
        let (year, rest) = digits(text, 4)?;
        let (month, rest) = digits(literal(rest, "-")?, 2)?;
        let (day, rest) = digits(literal(rest, "-")?, 2)?;
        if !rest.is_empty() {
            return Err("unexpected text after date".into());
        }
        Self::new(year, month, day)
    }

    fn new(year: u32, month: u32, day: u32) -> Result<Self, String> {
        if !(1..=9999).contains(&year)
            || !(1..=12).contains(&month)
            || !(1..=days_in_month(year as u16, month as u8) as u32).contains(&day)
        {
            return Err("invalid Gregorian date".into());
        }
        Ok(Self {
            year: year as u16,
            month: month as u8,
            day: day as u8,
        })
    }

    fn shift_day(mut self, forward: bool) -> Result<Self, String> {
        if forward {
            if self.day < days_in_month(self.year, self.month) {
                self.day += 1;
            } else {
                self.day = 1;
                if self.month < 12 {
                    self.month += 1;
                } else {
                    self.month = 1;
                    self.year += 1;
                }
            }
        } else if self.day > 1 {
            self.day -= 1;
        } else {
            if self.month > 1 {
                self.month -= 1;
            } else {
                self.month = 12;
                self.year -= 1;
            }
            self.day = days_in_month(self.year, self.month);
        }
        if !(1..=9999).contains(&self.year) {
            return Err("timestamp is outside years 0001 through 9999".into());
        }
        Ok(self)
    }
}

fn days_in_month(year: u16, month: u8) -> u8 {
    match month {
        2 if year.is_multiple_of(4) && (!year.is_multiple_of(100) || year.is_multiple_of(400)) => {
            29
        }
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

impl fmt::Display for Date {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
struct Civil {
    date: Date,
    second: u32,
    nanos: u32,
}

impl Civil {
    fn new(date: Date, hour: u32, minute: u32, second: u32, nanos: u32) -> Result<Self, String> {
        if hour > 23 || minute > 59 || second > 59 {
            return Err("invalid clock time".into());
        }
        Ok(Self {
            date,
            second: hour * 3600 + minute * 60 + second,
            nanos,
        })
    }

    fn shift(mut self, minutes: i16) -> Result<Self, String> {
        let second = self.second as i32 + i32::from(minutes) * 60;
        if !(0..86400).contains(&second) {
            self.date = self.date.shift_day(second >= 86400)?;
        }
        self.second = second.rem_euclid(86400) as u32;
        Ok(self)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Timestamp {
    utc: Civil,
    offset: i16,
}

impl Timestamp {
    pub(super) fn canonical(text: &str) -> Result<Self, String> {
        let (date, clock) = text
            .split_once('T')
            .or_else(|| text.split_once('t'))
            .ok_or("timestamp requires a date and time separated by T")?;
        let date = Date::canonical(date)?;
        let (hour, rest) = digits(clock, 2)?;
        let (minute, rest) = digits(literal(rest, ":")?, 2)?;
        let (second, rest) = digits(literal(rest, ":")?, 2)?;
        let (nanos, rest) = if let Some(rest) = rest.strip_prefix('.') {
            fraction(rest)?
        } else {
            (0, rest)
        };
        let (offset, rest) = offset(rest)?;
        if !rest.is_empty() {
            return Err("unexpected text after timestamp".into());
        }
        Self::new(Civil::new(date, hour, minute, second, nanos)?, offset)
    }

    fn new(local: Civil, offset: i16) -> Result<Self, String> {
        Ok(Self {
            utc: local.shift(-offset)?,
            offset,
        })
    }

    pub(super) fn with_offset(self, offset: i16) -> Self {
        Self { offset, ..self }
    }

    pub(super) fn offset(self) -> i16 {
        self.offset
    }

    pub(super) fn compare(self, other: Self) -> Ordering {
        self.utc.cmp(&other.utc)
    }
}

impl fmt::Display for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let ts = self.utc;
        write!(
            f,
            "{}T{:02}:{:02}:{:02}",
            ts.date,
            ts.second / 3600,
            ts.second / 60 % 60,
            ts.second % 60
        )?;
        if ts.nanos != 0 {
            let mut digits = 9;
            let mut nanos = ts.nanos;
            while nanos.is_multiple_of(10) {
                nanos /= 10;
                digits -= 1;
            }
            write!(f, ".{nanos:0digits$}")?;
        }
        f.write_char('Z')
    }
}

#[derive(Clone, Copy, Debug)]
enum Unit {
    Year,
    Quarter,
    Month,
    Day,
    Hour,
    Minute,
    Second,
}

impl Unit {
    fn parse(unit: &str, timestamp: bool) -> Result<Self, String> {
        match unit {
            "year" => Ok(Self::Year),
            "quarter" => Ok(Self::Quarter),
            "month" => Ok(Self::Month),
            "day" => Ok(Self::Day),
            "hour" if timestamp => Ok(Self::Hour),
            "minute" if timestamp => Ok(Self::Minute),
            "second" if timestamp => Ok(Self::Second),
            _ => Err(format!("unsupported date or timestamp unit {unit:?}")),
        }
    }

    fn extract(self, civil: Civil) -> f64 {
        let value = match self {
            Self::Year => civil.date.year as u32,
            Self::Quarter => (civil.date.month as u32 - 1) / 3 + 1,
            Self::Month => civil.date.month as u32,
            Self::Day => civil.date.day as u32,
            Self::Hour => civil.second / 3600,
            Self::Minute => civil.second / 60 % 60,
            Self::Second => civil.second % 60,
        };
        f64::from(value)
    }

    fn truncate(self, mut civil: Civil) -> Civil {
        let date = &mut civil.date;
        match self {
            Self::Year => {
                date.month = 1;
                date.day = 1;
            }
            Self::Quarter => {
                date.month = ((date.month - 1) / 3) * 3 + 1;
                date.day = 1;
            }
            Self::Month => date.day = 1,
            _ => {}
        }
        civil.second = match self {
            Self::Second => civil.second,
            Self::Minute => (civil.second / 60) * 60,
            Self::Hour => (civil.second / 3600) * 3600,
            _ => 0,
        };
        civil.nanos = 0;
        civil
    }
}

#[derive(Clone, Copy, Debug)]
enum Token {
    Year,
    Month,
    Day,
    Hour,
    Minute,
    Second,
    Fraction,
    Offset,
}
impl Token {
    fn parse(c: char, timestamp: bool) -> Result<Self, String> {
        match c {
            'Y' => Ok(Self::Year),
            'm' => Ok(Self::Month),
            'd' => Ok(Self::Day),
            'H' if timestamp => Ok(Self::Hour),
            'M' if timestamp => Ok(Self::Minute),
            'S' if timestamp => Ok(Self::Second),
            'f' if timestamp => Ok(Self::Fraction),
            'z' if timestamp => Ok(Self::Offset),
            _ => Err(format!("unsupported date or timestamp format token %{c}")),
        }
    }
    fn width(self) -> usize {
        match self {
            Self::Year => 4,
            Self::Fraction => 9,
            Self::Offset => 6,
            _ => 2,
        }
    }
}

#[derive(Debug)]
enum Part {
    Text(String),
    Token(Token),
}

#[derive(Debug)]
struct Format {
    parts: Vec<Part>,
    width: usize,
}

impl Format {
    fn new(format: &str, timestamp: bool, parsing: bool) -> Result<Self, String> {
        let mut parts = Vec::new();
        let mut width = 0;
        let mut seen = [false; 8];
        let mut begin = 0;
        let mut chars = format.char_indices();
        while let Some((index, c)) = chars.next() {
            if c != '%' {
                continue;
            }
            if index > begin {
                parts.push(Part::Text(format[begin..index].into()));
                width += index - begin;
            }
            let (end, c) = chars.next().ok_or("incomplete date format token")?;
            begin = end + c.len_utf8();
            if c == '%' {
                parts.push(Part::Text("%".into()));
                width += 1;
                continue;
            }
            let token = Token::parse(c, timestamp)?;
            if parsing && seen[token as usize] {
                return Err(format!("duplicate date format token %{c}"));
            }
            seen[token as usize] = true;
            width += token.width();
            parts.push(Part::Token(token));
        }
        if begin < format.len() {
            parts.push(Part::Text(format[begin..].into()));
            width += format.len() - begin;
        }
        if parsing && !seen[..3].iter().all(|&part| part) {
            return Err("parse format requires %Y, %m, and %d".into());
        }
        if parsing && timestamp && !(seen[3] && seen[4]) {
            return Err("timestamp parse format requires %H and %M".into());
        }
        Ok(Self { parts, width })
    }

    fn read(&self, mut text: &str) -> Result<(Civil, i16), String> {
        let mut parts = [0; 7];
        let mut zone = 0;
        for part in &self.parts {
            match part {
                Part::Text(expected) => text = literal(text, expected)?,
                Part::Token(Token::Offset) => (zone, text) = offset(text)?,
                Part::Token(token) => {
                    (parts[*token as usize], text) = if matches!(token, Token::Fraction) {
                        fraction(text)?
                    } else {
                        digits(text, token.width())?
                    };
                }
            }
        }
        if !text.is_empty() {
            return Err("unexpected text after date or timestamp".into());
        }
        let [year, month, day, hour, minute, second, nanos] = parts;
        let civil = Civil::new(Date::new(year, month, day)?, hour, minute, second, nanos)?;
        Ok((civil, zone))
    }

    fn write(&self, civil: Civil, zone: i16, reserve: &mut Reserve<'_>) -> EvalResult<String> {
        admitted(reserve, self.width)?;
        let mut output = String::with_capacity(self.width);
        for part in &self.parts {
            match part {
                Part::Text(text) => output.push_str(text),
                Part::Token(Token::Offset) => {
                    let sign = if zone < 0 { '-' } else { '+' };
                    let absolute = zone.unsigned_abs();
                    write!(output, "{sign}{:02}:{:02}", absolute / 60, absolute % 60).unwrap();
                }
                Part::Token(token) => {
                    let value = match token {
                        Token::Year => u32::from(civil.date.year),
                        Token::Month => u32::from(civil.date.month),
                        Token::Day => u32::from(civil.date.day),
                        Token::Hour => civil.second / 3600,
                        Token::Minute => civil.second / 60 % 60,
                        Token::Second => civil.second % 60,
                        Token::Fraction => civil.nanos,
                        Token::Offset => unreachable!(),
                    };
                    write!(output, "{value:0width$}", width = token.width()).unwrap();
                }
            }
        }
        Ok(output)
    }
}

#[derive(Debug)]
enum Operation {
    Parse(Option<Format>),
    Format(Format),
    Extract(Unit),
    Truncate(Unit),
}

#[derive(Debug)]
pub(super) struct Instruction {
    operation: Operation,
    timestamp: bool,
    local: bool,
}

pub(super) fn prepare(function: Function, args: &[Node]) -> Result<Option<Instruction>, String> {
    use Function::*;
    enum Kind {
        Parse,
        Format,
        Extract,
        Truncate,
    }
    let (timestamp, kind) = match function {
        DATE_PARSE => (false, Kind::Parse),
        DATE_FORMAT => (false, Kind::Format),
        DATE_EXTRACT => (false, Kind::Extract),
        DATE_TRUNC => (false, Kind::Truncate),
        TIMESTAMP_PARSE => (true, Kind::Parse),
        TIMESTAMP_FORMAT => (true, Kind::Format),
        TIMESTAMP_EXTRACT => (true, Kind::Extract),
        TIMESTAMP_TRUNC => (true, Kind::Truncate),
        _ => return Ok(None),
    };
    let option = |index| match args.get(index) {
        Some(Node::Literal(Value::Text(text))) => Ok(Some(text.as_ref())),
        None => Ok(None),
        _ => Err("date and timestamp options must be literal text"),
    };
    let parameter = option(1)?;
    let local = match option(2)? {
        None | Some("utc") => false,
        Some("local") => true,
        Some(_) => return Err("timestamp basis must be utc or local".into()),
    };
    let operation = match kind {
        Kind::Parse => Operation::Parse(
            parameter
                .map(|format| Format::new(format, timestamp, true))
                .transpose()?,
        ),
        Kind::Format => Operation::Format(Format::new(parameter.unwrap(), timestamp, false)?),
        Kind::Extract => Operation::Extract(Unit::parse(parameter.unwrap(), timestamp)?),
        Kind::Truncate => Operation::Truncate(Unit::parse(parameter.unwrap(), timestamp)?),
    };
    Ok(Some(Instruction {
        operation,
        timestamp,
        local,
    }))
}

impl Instruction {
    pub(super) fn evaluate<'a>(
        &self,
        value: Value<'a>,
        reserve: &mut Reserve<'_>,
    ) -> EvalResult<Value<'a>> {
        if matches!(value, Value::Null) {
            return Ok(Value::Null);
        }
        if let Operation::Parse(format) = &self.operation {
            let text = value.text()?;
            return if let Some(format) = format {
                let (civil, offset) = format.read(&text).map_err(row)?;
                if self.timestamp {
                    Timestamp::new(civil, offset)
                        .map(Value::Timestamp)
                        .map_err(row)
                } else {
                    Ok(Value::Date(civil.date))
                }
            } else if self.timestamp {
                Timestamp::canonical(&text)
                    .map(Value::Timestamp)
                    .map_err(row)
            } else {
                Date::canonical(&text).map(Value::Date).map_err(row)
            };
        }
        let (civil, zone, original_offset) = match value {
            Value::Timestamp(ts) if self.timestamp => {
                let zone = if self.local { ts.offset } else { 0 };
                (ts.utc.shift(zone).map_err(row)?, zone, ts.offset)
            }
            Value::Date(date) if !self.timestamp => (
                Civil {
                    date,
                    second: 0,
                    nanos: 0,
                },
                0,
                0,
            ),
            _ if self.timestamp => {
                return Err(row(
                    "expected a timestamp; use TIMESTAMP_PARSE to convert text",
                ))
            }
            _ => return Err(row("expected a date; use DATE_PARSE to convert text")),
        };
        match &self.operation {
            Operation::Format(format) => {
                Ok(Value::Text(Cow::Owned(format.write(civil, zone, reserve)?)))
            }
            Operation::Extract(unit) => Ok(Value::Number(unit.extract(civil))),
            Operation::Truncate(unit) => {
                let civil = unit.truncate(civil);
                if self.timestamp {
                    Timestamp::new(civil, zone)
                        .and_then(|ts| {
                            ts.utc.shift(original_offset)?;
                            Ok(Value::Timestamp(ts.with_offset(original_offset)))
                        })
                        .map_err(row)
                } else {
                    Ok(Value::Date(civil.date))
                }
            }
            Operation::Parse(_) => unreachable!(),
        }
    }
}

fn literal<'a>(text: &'a str, expected: &str) -> Result<&'a str, String> {
    text.strip_prefix(expected)
        .ok_or_else(|| format!("expected {expected:?}"))
}

fn digits(text: &str, count: usize) -> Result<(u32, &str), String> {
    let prefix = text
        .as_bytes()
        .get(..count)
        .ok_or("incomplete date or time")?;
    if !prefix.iter().all(u8::is_ascii_digit) {
        return Err("expected numeric date or time field".into());
    }
    let value = prefix
        .iter()
        .fold(0, |value, &digit| value * 10 + u32::from(digit - b'0'));
    Ok((value, &text[count..]))
}

fn fraction(text: &str) -> Result<(u32, &str), String> {
    let count = text.bytes().take_while(u8::is_ascii_digit).count();
    if !(1..=9).contains(&count) {
        return Err("expected one through nine fractional-second digits".into());
    }
    let (value, rest) = digits(text, count)?;
    Ok((value * 10_u32.pow((9 - count) as u32), rest))
}

fn offset(text: &str) -> Result<(i16, &str), String> {
    if let Some(rest) = text.strip_prefix(['Z', 'z']) {
        return Ok((0, rest));
    }
    let (sign, rest) = if let Some(rest) = text.strip_prefix('+') {
        (1, rest)
    } else if let Some(rest) = text.strip_prefix('-') {
        (-1, rest)
    } else {
        return Err("timestamp requires Z or a numeric offset".into());
    };
    let (hour, rest) = digits(rest, 2)?;
    let (minute, rest) = digits(literal(rest, ":")?, 2)?;
    if hour > 23 || minute > 59 {
        return Err("invalid timestamp offset".into());
    }
    Ok((sign * (hour * 60 + minute) as i16, rest))
}
