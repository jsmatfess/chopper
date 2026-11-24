use super::{admitted, row, EvalError, EvalResult, Field, Function, Node, Reserve, Value};
use std::{borrow::Cow, cell::RefCell, ops::Range};

const MAX_PROGRAM: usize = 512;
pub(super) const PROGRAM_ALLOCATION_BOUND: usize = 2 * MAX_PROGRAM * std::mem::size_of::<Op>();
const MAX_CAPTURES: usize = 12;
const MISSING: usize = usize::MAX;

#[derive(Debug)]
pub(super) struct Instruction {
    regex: Regex,
    text: Node,
    replacement: Option<Node>,
    insensitive: bool,
    scratch: RefCell<Option<(States, States)>>,
}

impl Instruction {
    pub(super) fn prepare(function: Function, args: Vec<Node>) -> Result<Self, String> {
        let mut args = args.into_iter();
        let text = args.next().unwrap();
        let pattern = match args.next().unwrap() {
            Node::Literal(Value::Text(pattern)) => pattern,
            _ => return Err("pattern must be literal text".into()),
        };
        let like = matches!(function, Function::LIKE | Function::ILIKE);
        let insensitive = matches!(function, Function::ILIKE);
        let regex = if insensitive {
            Regex::compile(&pattern.to_lowercase(), like)?
        } else {
            Regex::compile(&pattern, like)?
        };
        Ok(Self {
            regex,
            text,
            replacement: args.next(),
            insensitive,
            scratch: RefCell::new(None),
        })
    }

    pub(super) fn workspace_bytes(&self) -> usize {
        2 * self.regex.instructions.len() * (std::mem::size_of::<Thread>() + 1)
            + self.text.workspace_bytes()
            + self.replacement.as_ref().map_or(0, Node::workspace_bytes)
    }

    pub(super) fn bind(
        &mut self,
        header: Option<&[String]>,
        width: usize,
        unnamed: usize,
    ) -> Result<(), String> {
        self.text.bind(header, width, unnamed)?;
        if let Some(replacement) = &mut self.replacement {
            replacement.bind(header, width, unnamed)?;
        }
        Ok(())
    }

    pub(super) fn evaluate<'a>(
        &'a self,
        field: &Field<'a>,
        reserve: &mut Reserve<'_>,
    ) -> EvalResult<Value<'a>> {
        let value = self.text.evaluate(field, reserve)?;
        if matches!(value, Value::Null) {
            return Ok(Value::Null);
        }
        let mut text = value.text()?;
        if self.insensitive {
            let output_bytes: usize = text
                .chars()
                .flat_map(char::to_lowercase)
                .map(char::len_utf8)
                .sum();
            admitted(reserve, output_bytes.saturating_mul(2).saturating_add(8))?;
            text = Cow::Owned(text.to_lowercase());
        }
        let length = self.regex.instructions.len();
        let mut scratch = self.scratch.borrow_mut();
        let (current, next) =
            scratch.get_or_insert_with(|| (States::new(length), States::new(length)));
        let mut matcher = Matcher {
            regex: &self.regex,
            current,
            next,
        };
        let Some(replacement) = &self.replacement else {
            return Ok(Value::Bool(matcher.find(&text, 0, reserve)?.is_some()));
        };
        let replacement = replacement.evaluate(field, reserve)?;
        if matches!(replacement, Value::Null) {
            return Ok(Value::Null);
        }
        let replacement = replacement.text()?;
        let mut output = String::new();
        let mut copied = 0;
        let mut search = 0;
        while let Some(found) = matcher.find(&text, search, reserve)? {
            append(&mut output, &text[copied..found.start], reserve)?;
            replace(
                &mut output,
                &replacement,
                &text,
                &found,
                self.regex.captures,
                reserve,
            )?;
            copied = found.end;
            search = if found.start != found.end {
                found.end
            } else if let Some(next) = text[found.end..].chars().next() {
                found.end + next.len_utf8()
            } else {
                break;
            };
        }
        if output.is_empty() && copied == 0 {
            // No matches, or only empty matches with an empty replacement.
            return Ok(Value::Text(text));
        }
        append(&mut output, &text[copied..], reserve)?;
        Ok(Value::Text(Cow::Owned(output)))
    }
}

fn append(output: &mut String, part: &str, reserve: &mut Reserve<'_>) -> EvalResult<()> {
    let size = output
        .len()
        .checked_add(part.len())
        .ok_or_else(|| EvalError::System("replacement size overflow".into()))?;
    if size > output.capacity() {
        let capacity = size.max(output.capacity().saturating_mul(2)).max(64);
        admitted(reserve, capacity)?;
        output
            .try_reserve_exact(capacity - output.len())
            .map_err(|e| EvalError::System(e.to_string()))?;
    }
    output.push_str(part);
    Ok(())
}

fn replace(
    output: &mut String,
    mut replacement: &str,
    input: &str,
    found: &Match,
    groups: usize,
    reserve: &mut Reserve<'_>,
) -> EvalResult<()> {
    while let Some(at) = replacement.find(['$', '\\']) {
        append(output, &replacement[..at], reserve)?;
        let tail = &replacement[at + 1..];
        if replacement.as_bytes()[at] == b'\\' {
            let next = tail
                .chars()
                .next()
                .ok_or_else(|| row("trailing replacement escape"))?;
            append(output, &tail[..next.len_utf8()], reserve)?;
            replacement = &tail[next.len_utf8()..];
        } else {
            let len = tail.bytes().take_while(u8::is_ascii_digit).count();
            if len == 0 {
                append(output, "$", reserve)?;
                replacement = tail;
                continue;
            }
            let group = tail[..len]
                .parse::<usize>()
                .map_err(|_| row("invalid replacement capture number"))?;
            if group > groups {
                return Err(row(format!(
                    "replacement references missing capture {group}"
                )));
            }
            if group == 0 {
                append(output, &input[found.start..found.end], reserve)?;
            } else {
                let [start, end] = found.captures[group - 1];
                if start != MISSING && end != MISSING {
                    append(output, &input[start..end], reserve)?;
                }
            }
            replacement = &tail[len..];
        }
    }
    append(output, replacement, reserve)
}

#[derive(Clone, Copy, Debug)]
enum Predicate {
    Any,
    Literal(char),
    Class(usize),
    Digit,
    Word,
    Space,
}

#[derive(Debug)]
struct Class {
    ranges: Vec<Range<char>>,
    predicates: Vec<Predicate>,
    negated: bool,
}

impl Class {
    fn matches(&self, character: char) -> bool {
        let inside = self
            .ranges
            .iter()
            .any(|range| range.start <= character && character <= range.end)
            || self
                .predicates
                .iter()
                .any(|test| test.matches(character, &[]));
        inside != self.negated
    }
}

impl Predicate {
    fn matches(self, character: char, classes: &[Class]) -> bool {
        match self {
            Self::Any => true,
            Self::Literal(value) => character == value,
            Self::Class(index) => classes[index].matches(character),
            Self::Digit => character.is_ascii_digit(),
            Self::Word => character.is_alphanumeric() || character == '_',
            Self::Space => character.is_whitespace(),
        }
    }
}

#[derive(Debug)]
enum Ast {
    Test(Predicate),
    Start,
    End,
    Capture(usize, Box<Ast>),
    Sequence(Vec<Ast>),
    Alternation(Vec<Ast>),
    Repeat(Box<Ast>, usize, Option<usize>),
}

#[derive(Clone, Copy, Debug)]
enum Op {
    Test(Predicate, usize),
    Start(usize),
    End(usize),
    Save(usize, usize, usize),
    Split(usize, usize),
    Accept,
}

#[derive(Debug)]
struct Regex {
    instructions: Vec<Op>,
    classes: Vec<Class>,
    start: usize,
    captures: usize,
    whole: bool,
}

impl Regex {
    fn compile(pattern: &str, whole: bool) -> Result<Self, String> {
        if pattern.len() > 4096 {
            return Err("pattern exceeds 4096 bytes".into());
        }
        let mut parser = Parser {
            input: pattern,
            classes: Vec::new(),
            captures: 0,
        };
        let tree = if whole {
            parser.like()?
        } else {
            parser.alternation(0)?
        };
        if !parser.input.is_empty() {
            return Err("unexpected closing parenthesis in pattern".into());
        }
        let mut regex = Self {
            instructions: vec![Op::Accept],
            classes: parser.classes,
            start: 0,
            captures: parser.captures,
            whole,
        };
        let end = if whole { regex.emit(Op::End(0))? } else { 0 };
        regex.start = regex.compile_ast(&tree, end, &mut (4 * MAX_PROGRAM))?;
        Ok(regex)
    }

    fn emit(&mut self, instruction: Op) -> Result<usize, String> {
        if self.instructions.len() >= MAX_PROGRAM {
            return Err("compiled pattern exceeds 512 instructions".into());
        }
        let index = self.instructions.len();
        self.instructions.push(instruction);
        Ok(index)
    }

    fn compile_ast(
        &mut self,
        ast: &Ast,
        mut next: usize,
        remaining: &mut usize,
    ) -> Result<usize, String> {
        *remaining = remaining
            .checked_sub(1)
            .ok_or("pattern exceeds compilation work limit")?;
        match ast {
            Ast::Test(test) => self.emit(Op::Test(*test, next)),
            Ast::Start => self.emit(Op::Start(next)),
            Ast::End => self.emit(Op::End(next)),
            Ast::Capture(group, item) => {
                let after = self.emit(Op::Save(*group, 1, next))?;
                let inner = self.compile_ast(item, after, remaining)?;
                self.emit(Op::Save(*group, 0, inner))
            }
            Ast::Sequence(items) => {
                for item in items.iter().rev() {
                    next = self.compile_ast(item, next, remaining)?;
                }
                Ok(next)
            }
            Ast::Alternation(alternatives) => {
                let (last, earlier_items) = alternatives.split_last().unwrap();
                let mut start = self.compile_ast(last, next, remaining)?;
                for item in earlier_items.iter().rev() {
                    let earlier = self.compile_ast(item, next, remaining)?;
                    start = self.emit(Op::Split(earlier, start))?;
                }
                Ok(start)
            }
            Ast::Repeat(item, min, maximum) => {
                if let Some(max) = maximum {
                    for _ in *min..*max {
                        let repeat = self.compile_ast(item, next, remaining)?;
                        next = self.emit(Op::Split(repeat, next))?;
                    }
                } else {
                    let loop_start = self.emit(Op::Accept)?;
                    let repeat = self.compile_ast(item, loop_start, remaining)?;
                    self.instructions[loop_start] = Op::Split(repeat, next);
                    next = loop_start;
                }
                for _ in 0..*min {
                    next = self.compile_ast(item, next, remaining)?;
                }
                Ok(next)
            }
        }
    }
}

struct Parser<'a> {
    input: &'a str,
    classes: Vec<Class>,
    captures: usize,
}

impl Parser<'_> {
    fn take(&mut self) -> Option<char> {
        let first = self.input.chars().next()?;
        self.input = &self.input[first.len_utf8()..];
        Some(first)
    }

    fn consume(&mut self, value: char) -> bool {
        if let Some(rest) = self.input.strip_prefix(value) {
            self.input = rest;
            true
        } else {
            false
        }
    }

    fn like(&mut self) -> Result<Ast, String> {
        let mut items = Vec::new();
        while let Some(character) = self.take() {
            items.push(match character {
                '\\' => Ast::Test(Predicate::Literal(
                    self.take().ok_or("trailing wildcard escape")?,
                )),
                '.' if self.consume('*') => {
                    Ast::Repeat(Box::new(Ast::Test(Predicate::Any)), 0, None)
                }
                '.' => Ast::Test(Predicate::Any),
                _ => Ast::Test(Predicate::Literal(character)),
            });
        }
        Ok(Ast::Sequence(items))
    }

    fn alternation(&mut self, depth: usize) -> Result<Ast, String> {
        if depth >= 32 {
            return Err("pattern is nested too deeply".into());
        }
        let mut branches = vec![self.sequence(depth)?];
        while self.consume('|') {
            branches.push(self.sequence(depth)?);
        }
        if branches.len() == 1 {
            Ok(branches.pop().unwrap())
        } else {
            Ok(Ast::Alternation(branches))
        }
    }

    fn sequence(&mut self, depth: usize) -> Result<Ast, String> {
        let mut items = Vec::new();
        while let Some(character) = self.input.chars().next() {
            if matches!(character, '|' | ')') {
                break;
            }
            self.take();
            let item = match character {
                '(' => {
                    let capturing = !self.consume('?');
                    if !capturing && !(self.consume(':')) {
                        return Err("unsupported group assertion or option".into());
                    }
                    let group = self.captures;
                    if capturing {
                        if self.captures >= MAX_CAPTURES {
                            return Err("pattern exceeds 12 numbered capture groups".into());
                        }
                        self.captures += 1;
                    }
                    let inner = self.alternation(depth + 1)?;
                    if !self.consume(')') {
                        return Err("unclosed pattern group".into());
                    }
                    if capturing {
                        Ast::Capture(group, Box::new(inner))
                    } else {
                        inner
                    }
                }
                '[' => Ast::Test(self.class()?),
                '.' => Ast::Test(Predicate::Any),
                '^' => Ast::Start,
                '$' => Ast::End,
                '\\' => Ast::Test(self.escape()?),
                '*' | '+' | '?' | '{' => {
                    return Err("repetition requires a preceding pattern".into())
                }
                _ => Ast::Test(Predicate::Literal(character)),
            };
            let bounds = if self.consume('*') {
                Some((0, None))
            } else if self.consume('+') {
                Some((1, None))
            } else if self.consume('?') {
                Some((0, Some(1)))
            } else if self.consume('{') {
                Some(self.repetition()?)
            } else {
                None
            };
            items.push(if let Some((min, max)) = bounds {
                Ast::Repeat(Box::new(item), min, max)
            } else {
                item
            });
        }
        Ok(Ast::Sequence(items))
    }

    fn repetition(&mut self) -> Result<(usize, Option<usize>), String> {
        let min = self.quantity()?;
        let max = if self.consume(',') {
            if self.input.starts_with('}') {
                None
            } else {
                Some(self.quantity()?)
            }
        } else {
            Some(min)
        };
        if !self.consume('}') || max.is_some_and(|max| max < min) {
            return Err("invalid repetition bounds".into());
        }
        Ok((min, max))
    }

    fn quantity(&mut self) -> Result<usize, String> {
        let count = self.input.bytes().take_while(u8::is_ascii_digit).count();
        let value = self.input[..count]
            .parse::<usize>()
            .ok()
            .filter(|&n| n <= MAX_PROGRAM)
            .ok_or("invalid or oversized repetition count")?;
        self.input = &self.input[count..];
        Ok(value)
    }

    fn escape(&mut self) -> Result<Predicate, String> {
        Ok(match self.take().ok_or("trailing regex escape")? {
            'd' => Predicate::Digit,
            'w' => Predicate::Word,
            's' => Predicate::Space,
            'n' => Predicate::Literal('\n'),
            'r' => Predicate::Literal('\r'),
            't' => Predicate::Literal('\t'),
            c if c.is_ascii_alphanumeric() => {
                return Err(format!("unsupported regex escape \\{c}"))
            }
            c => Predicate::Literal(c),
        })
    }

    fn class(&mut self) -> Result<Predicate, String> {
        let mut class = Class {
            ranges: Vec::new(),
            predicates: Vec::new(),
            negated: self.consume('^'),
        };
        loop {
            if self.consume(']') {
                break;
            }
            let atom = self.class_atom()?;
            if let Predicate::Literal(start) = atom {
                if self.input.starts_with('-') && !self.input.starts_with("-]") {
                    self.take();
                    let Predicate::Literal(end) = self.class_atom()? else {
                        return Err("character class ranges require literal endpoints".into());
                    };
                    if end < start {
                        return Err("character class range is reversed".into());
                    }
                    class.ranges.push(start..end);
                    continue;
                }
            }
            class.predicates.push(atom);
        }
        if class.ranges.is_empty() && class.predicates.is_empty() {
            return Err("empty character class".into());
        }
        let index = self.classes.len();
        self.classes.push(class);
        Ok(Predicate::Class(index))
    }

    fn class_atom(&mut self) -> Result<Predicate, String> {
        match self.take().ok_or("unclosed character class")? {
            '\\' => self.escape(),
            c => Ok(Predicate::Literal(c)),
        }
    }
}

#[derive(Clone, Copy, Debug)]
struct Thread {
    pc: usize,
    start: usize,
    captures: [[usize; 2]; MAX_CAPTURES],
}

struct Match {
    start: usize,
    end: usize,
    captures: [[usize; 2]; MAX_CAPTURES],
}

#[derive(Debug)]
struct States {
    seen: Vec<bool>,
    threads: Vec<Thread>,
}

impl States {
    fn new(length: usize) -> Self {
        Self {
            seen: vec![false; length],
            threads: Vec::with_capacity(length),
        }
    }

    fn clear(&mut self) {
        self.seen.fill(false);
        self.threads.clear();
    }

    fn add(&mut self, regex: &Regex, mut thread: Thread, at: usize, end: usize) {
        loop {
            if std::mem::replace(&mut self.seen[thread.pc], true) {
                return;
            }
            thread.pc = match regex.instructions[thread.pc] {
                Op::Test(_, _) | Op::Accept => {
                    self.threads.push(thread);
                    return;
                }
                Op::Start(next) if at == 0 => next,
                Op::End(next) if at == end => next,
                Op::Start(_) | Op::End(_) => return,
                Op::Save(group, endpoint, next) => {
                    thread.captures[group][endpoint] = at;
                    next
                }
                Op::Split(first, second) => {
                    self.add(
                        regex,
                        Thread {
                            pc: first,
                            ..thread
                        },
                        at,
                        end,
                    );
                    second
                }
            };
        }
    }
}

struct Matcher<'a> {
    regex: &'a Regex,
    current: &'a mut States,
    next: &'a mut States,
}

impl Matcher<'_> {
    fn find(
        &mut self,
        input: &str,
        start: usize,
        reserve: &mut Reserve<'_>,
    ) -> EvalResult<Option<Match>> {
        let mut best = None;
        self.current.clear();
        self.next.clear();
        // Keep the earliest path at each instruction. Captures cannot affect
        // future transitions, so discarding duplicate paths prevents backtracking.
        for (iteration, (offset, character)) in input[start..]
            .char_indices()
            .map(|(offset, character)| (start + offset, Some(character)))
            .chain(std::iter::once((input.len(), None)))
            .enumerate()
        {
            if iteration.is_multiple_of(1024) {
                admitted(reserve, 0)?;
            }
            if best.is_none() && (!self.regex.whole || offset == 0) {
                self.current.add(
                    self.regex,
                    Thread {
                        pc: self.regex.start,
                        start: offset,
                        captures: [[MISSING; 2]; MAX_CAPTURES],
                    },
                    offset,
                    input.len(),
                );
            }
            for &thread in &self.current.threads {
                match self.regex.instructions[thread.pc] {
                    Op::Accept => {
                        best = Some(Match {
                            start: thread.start,
                            end: offset,
                            captures: thread.captures,
                        });
                        break;
                    }
                    Op::Test(predicate, pc) => {
                        if let Some(character) =
                            character.filter(|&c| predicate.matches(c, &self.regex.classes))
                        {
                            self.next.add(
                                self.regex,
                                Thread { pc, ..thread },
                                offset + character.len_utf8(),
                                input.len(),
                            );
                        }
                    }
                    _ => unreachable!(),
                }
            }
            if self.next.threads.is_empty() && (best.is_some() || self.regex.whole) {
                break;
            }
            std::mem::swap(&mut self.current, &mut self.next);
            self.next.clear();
        }
        Ok(best)
    }
}
