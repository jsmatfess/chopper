use super::{
    admitted, chars_equal_ignore_case, number, position, row, text_slice, EvalError, EvalResult,
    Field, Function, Node, Reserve, Value,
};
use std::borrow::Cow;
use std::ops::Range;

fn prefix_end_ignore_case(text: &str, pattern: &str) -> Option<usize> {
    let mut chars = text.chars();
    pattern
        .chars()
        .all(|part| {
            chars
                .next()
                .is_some_and(|ch| chars_equal_ignore_case(ch, part))
        })
        .then_some(text.len() - chars.as_str().len())
}

fn suffix_start_ignore_case(text: &str, pattern: &str) -> Option<usize> {
    let mut chars = text.chars();
    pattern
        .chars()
        .rev()
        .all(|part| {
            chars
                .next_back()
                .is_some_and(|ch| chars_equal_ignore_case(ch, part))
        })
        .then_some(chars.as_str().len())
}

fn find_ignore_case(text: &str, pattern: &str) -> Option<Range<usize>> {
    if pattern.is_empty() {
        return Some(0..0);
    }
    text.char_indices().find_map(|(start, _)| {
        prefix_end_ignore_case(&text[start..], pattern).map(|length| start..start + length)
    })
}

fn ignore_case(option: Option<Value<'_>>) -> EvalResult<bool> {
    match option {
        None => Ok(false),
        Some(Value::Bool(enabled)) => Ok(enabled),
        Some(other) => Err(row(format!(
            "ignore_case must be a Boolean. Received {}. Use TRUE or FALSE.",
            other.type_name()
        ))),
    }
}

fn output(reserve: &mut Reserve<'_>, size: Option<usize>) -> EvalResult<String> {
    let size = size
        .filter(|&n| n <= isize::MAX as usize)
        .ok_or_else(|| EvalError::System("text output length overflow".into()))?;
    admitted(reserve, size)?;
    let mut result = String::new();
    result
        .try_reserve_exact(size)
        .map_err(|error| EvalError::System(error.to_string()))?;
    Ok(result)
}

pub(super) fn concat_options(args: &[Node]) -> (&[Node], bool, bool) {
    use Node::Literal;
    use Value::Bool;
    match args {
        [values @ .., Literal(Bool(ignore_null)), Literal(Bool(ignore_empty))] => {
            (values, *ignore_null, *ignore_empty)
        }
        [values @ .., Literal(Bool(ignore_null))] => (values, *ignore_null, false),
        _ => (args, true, false),
    }
}

pub(super) fn concat<'a>(
    function: Function,
    first: Value<'a>,
    args: &'a [Node],
    field: &Field<'a>,
    reserve: &mut Reserve<'_>,
) -> EvalResult<Value<'a>> {
    let mut parts = [const { None }; 64];
    let first = first.text()?;
    let separated = matches!(function, Function::CONCAT_WS);
    let (args, ignore_null, ignore_empty) = if separated {
        concat_options(args)
    } else {
        (args, false, false)
    };
    let separator = if separated {
        first
    } else {
        parts[0] = Some(first);
        Cow::Borrowed("")
    };
    for (arg, part) in args.iter().zip(&mut parts[1..]) {
        let value = match arg.evaluate(field, reserve)? {
            Value::Null if !separated => return Ok(Value::Null),
            Value::Null if ignore_null => continue,
            Value::Null => Cow::Borrowed(""),
            value => {
                let text = value.text()?;
                if ignore_empty && text.is_empty() {
                    continue;
                }
                text
            }
        };
        *part = Some(value);
    }
    let mut values = parts.iter().flatten();
    let Some(first) = values.next() else {
        return Ok(Value::Text(Cow::Borrowed("")));
    };
    let size = values.clone().try_fold(first.len(), |size, part| {
        size.checked_add(separator.len())?.checked_add(part.len())
    });
    let mut result = output(reserve, size)?;
    result.push_str(first);
    for part in values {
        result.push_str(&separator);
        result.push_str(part);
    }
    Ok(Value::Text(Cow::Owned(result)))
}

pub(super) fn evaluate<'a>(
    function: Function,
    text: Cow<'a, str>,
    second: Option<Value<'a>>,
    third: Option<Value<'a>>,
    reserve: &mut Reserve<'_>,
) -> EvalResult<Value<'a>> {
    use Function::*;
    match function {
        LENGTH => number(text.chars().count() as f64),
        BYTE_LENGTH => number(text.len() as f64),
        IS_ASCII => Ok(Value::Bool(text.is_ascii())),
        IS_DIGITS => Ok(Value::Bool(
            !text.is_empty() && text.bytes().all(|b| b.is_ascii_digit()),
        )),
        LTRIM => text_slice(text, |s| s.len() - s.trim_start().len()..s.len()),
        RTRIM => text_slice(text, |s| 0..s.trim_end().len()),
        LEFT | RIGHT => {
            let count = position(second.unwrap(), "count")?;
            text_slice(text, |s| match function {
                LEFT => 0..s.char_indices().nth(count).map_or(s.len(), |(at, _)| at),
                _ => {
                    s.char_indices()
                        .rev()
                        .nth(count)
                        .map_or(0, |(at, ch)| at + ch.len_utf8())..s.len()
                }
            })
        }
        STARTSWITH | STRIP_PREFIX => {
            let part = second.unwrap().text()?;
            let end = if ignore_case(third)? {
                prefix_end_ignore_case(&text, &part)
            } else {
                text.strip_prefix(part.as_ref())
                    .map(|rest| text.len() - rest.len())
            };
            if matches!(function, STARTSWITH) {
                Ok(Value::Bool(end.is_some()))
            } else {
                text_slice(text, |s| end.unwrap_or(0)..s.len())
            }
        }
        ENDSWITH | STRIP_SUFFIX => {
            let part = second.unwrap().text()?;
            let start = if ignore_case(third)? {
                suffix_start_ignore_case(&text, &part)
            } else {
                text.strip_suffix(part.as_ref()).map(str::len)
            };
            if matches!(function, ENDSWITH) {
                Ok(Value::Bool(start.is_some()))
            } else {
                text_slice(text, |s| 0..start.unwrap_or(s.len()))
            }
        }
        CONTAINS => {
            let part = second.unwrap().text()?;
            Ok(Value::Bool(if ignore_case(third)? {
                find_ignore_case(&text, &part).is_some()
            } else {
                text.contains(part.as_ref())
            }))
        }
        SPLIT_PART | TEXT_BEFORE | TEXT_AFTER => {
            let delimiter = second.unwrap().text()?;
            if delimiter.is_empty() {
                return Err(row("delimiter must not be empty. Use a character or a nonempty text string as the delimiter."));
            }
            let range = if matches!(function, SPLIT_PART) {
                let index = position(third.unwrap(), "index")?;
                text.split(delimiter.as_ref()).nth(index).map(|part| {
                    let start = part.as_ptr().addr() - text.as_ptr().addr();
                    start..start + part.len()
                })
            } else {
                let matched = if ignore_case(third)? {
                    find_ignore_case(&text, &delimiter)
                } else {
                    text.find(delimiter.as_ref())
                        .map(|start| start..start + delimiter.len())
                };
                matched.map(|range| {
                    if matches!(function, TEXT_BEFORE) {
                        0..range.start
                    } else {
                        range.end..text.len()
                    }
                })
            };
            match range {
                Some(range) => text_slice(text, |_| range),
                None => Ok(Value::Null),
            }
        }
        REPEAT => {
            let count = position(second.unwrap(), "count")?;
            if text.is_empty() || count == 0 {
                return Ok(Value::Text(Cow::Borrowed("")));
            }
            if count == 1 {
                return Ok(Value::Text(text));
            }
            let size = text
                .len()
                .checked_mul(count)
                .filter(|&n| n <= isize::MAX as usize)
                .ok_or_else(|| EvalError::System("text output length overflow".into()))?;
            admitted(reserve, size)?;
            Ok(Value::Text(Cow::Owned(text.repeat(count))))
        }
        LPAD | RPAD => {
            let width = position(second.unwrap(), "width")?;
            let pad = third
                .map(Value::text)
                .transpose()?
                .unwrap_or(Cow::Borrowed(" "));
            pad_text(text, width, &pad, matches!(function, LPAD), reserve)
        }
        TRANSLATE => translate(
            &text,
            &second.unwrap().text()?,
            &third.unwrap().text()?,
            reserve,
        ),
        _ => unreachable!(),
    }
}

fn pad_text<'a>(
    text: Cow<'a, str>,
    width: usize,
    pad: &str,
    left: bool,
    reserve: &mut Reserve<'_>,
) -> EvalResult<Value<'a>> {
    if pad.is_empty() {
        return Err(row(
            "padding text must not be empty. Supply a nonempty pad or omit it to use a space.",
        ));
    }
    let length = text.chars().count();
    if width <= length {
        return text_slice(text, |s| {
            0..s.char_indices().nth(width).map_or(s.len(), |(at, _)| at)
        });
    }
    let padding = width - length;
    let chars = pad.chars().count();
    let cycles = padding / chars;
    let tail = &pad[..pad.char_indices().nth(padding % chars).unwrap().0];
    let size = cycles
        .checked_mul(pad.len())
        .and_then(|bytes| bytes.checked_add(tail.len()))
        .and_then(|bytes| bytes.checked_add(text.len()));
    let mut result = output(reserve, size)?;
    if !left {
        result.push_str(&text);
    }
    for _ in 0..cycles {
        result.push_str(pad);
    }
    result.push_str(tail);
    if left {
        result.push_str(&text);
    }
    Ok(Value::Text(Cow::Owned(result)))
}

fn translate<'a>(
    text: &str,
    from: &str,
    to: &str,
    reserve: &mut Reserve<'_>,
) -> EvalResult<Value<'a>> {
    let count = from.chars().count();
    let mut pairs: Vec<(char, usize, Option<char>)> = Vec::new();
    admitted(
        reserve,
        count
            .checked_mul(std::mem::size_of::<(char, usize, Option<char>)>())
            .ok_or_else(|| EvalError::System("translation table size overflow".into()))?,
    )?;
    pairs
        .try_reserve_exact(count)
        .map_err(|error| EvalError::System(error.to_string()))?;
    let mut replacement = to.chars();
    pairs.extend(
        from.chars()
            .enumerate()
            .map(|(index, ch)| (ch, index, replacement.next())),
    );
    pairs.sort_unstable_by_key(|&(ch, index, _)| (ch, index));
    pairs.dedup_by_key(|pair| pair.0);
    let translated = || {
        text.chars()
            .filter_map(|ch| match pairs.binary_search_by_key(&ch, |pair| pair.0) {
                Ok(index) => pairs[index].2,
                Err(_) => Some(ch),
            })
    };
    let size = translated().try_fold(0usize, |size, ch| size.checked_add(ch.len_utf8()));
    let mut result = output(reserve, size)?;
    result.extend(translated());
    Ok(Value::Text(Cow::Owned(result)))
}
