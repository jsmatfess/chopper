//! Build expressions for calculated columns with Chopper's formula functions.
//!
//! Expressions use the same formula text as saved Jobs. The engine binds
//! references and evaluates expressions when the Job analyzes or runs.
//!
//! ```
//! use chopper::formula::{col, functions as f};
//!
//! let column = (f::number(col(0)) * 2).alias("double_quantity");
//! assert_eq!(column.name, "double_quantity");
//! ```

use chopper_core::{expression::Expression, CalculatedColumn, Column};
use std::{
    borrow::Cow,
    fmt,
    ops::{Add, BitAnd, BitOr, Div, Mul, Not, Rem, Sub},
};

pub mod functions;

/// A composable formula for a calculated column.
///
/// `==` compares the formula text of two expressions. Use [`Expr::equal`]
/// or another comparison method to build a row condition.
#[derive(Clone, Debug)]
pub struct Expr {
    source: String,
    precedence: Precedence,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
enum Precedence {
    Unknown,
    Or,
    And,
    Not,
    Comparison,
    Additive,
    Multiplicative,
    Atom,
}

impl Expr {
    fn atom(source: impl Into<String>) -> Self {
        Self {
            source: source.into(),
            precedence: Precedence::Atom,
        }
    }

    /// Borrow the formula text used in saved Job JSON.
    pub fn as_str(&self) -> &str {
        &self.source
    }

    /// Name this expression as a calculated column in a Job.
    pub fn alias(self, name: impl Into<String>) -> CalculatedColumn {
        CalculatedColumn {
            name: name.into(),
            expression: self.source,
        }
    }

    /// Combine two formula expressions with AND, as with the `&` operator.
    pub fn and(self, rhs: impl Into<Self>) -> Self {
        self & rhs
    }

    /// Combine two formula expressions with OR, as with the `|` operator.
    pub fn or(self, rhs: impl Into<Self>) -> Self {
        self | rhs
    }

    /// Negate a formula expression with NOT, as with the `!` operator.
    #[allow(
        clippy::should_implement_trait,
        reason = "The inherent method delegates to the existing Not implementation"
    )]
    pub fn not(self) -> Self {
        !self
    }

    /// Build a row condition that tests whether the values are equal.
    pub fn equal(self, rhs: impl Into<Self>) -> Self {
        self.binary(rhs.into(), "=", Precedence::Comparison)
    }

    /// Build a row condition that tests whether the values differ.
    pub fn not_equal(self, rhs: impl Into<Self>) -> Self {
        self.binary(rhs.into(), "!=", Precedence::Comparison)
    }

    /// Build a row condition that tests whether the left value is less than the right.
    pub fn lt(self, rhs: impl Into<Self>) -> Self {
        self.binary(rhs.into(), "<", Precedence::Comparison)
    }

    /// Build a row condition that tests whether the left value is at most the right.
    pub fn le(self, rhs: impl Into<Self>) -> Self {
        self.binary(rhs.into(), "<=", Precedence::Comparison)
    }

    /// Build a row condition that tests whether the left value is greater than the right.
    pub fn gt(self, rhs: impl Into<Self>) -> Self {
        self.binary(rhs.into(), ">", Precedence::Comparison)
    }

    /// Build a row condition that tests whether the left value is at least the right.
    pub fn ge(self, rhs: impl Into<Self>) -> Self {
        self.binary(rhs.into(), ">=", Precedence::Comparison)
    }

    fn operand(&self, parent: Precedence, wrap_equal: bool) -> Cow<'_, str> {
        if self.precedence < parent || (wrap_equal && self.precedence == parent) {
            Cow::Owned(format!("({self})"))
        } else {
            Cow::Borrowed(self.as_str())
        }
    }

    fn binary(self, rhs: Self, operator: &str, precedence: Precedence) -> Self {
        let left = self.operand(precedence, false);
        // The parser is left-associative. Keep explicit right-side grouping.
        let right = rhs.operand(precedence, true);
        Self {
            source: format!("{left} {operator} {right}"),
            precedence,
        }
    }
}

impl PartialEq for Expr {
    fn eq(&self, other: &Self) -> bool {
        self.source == other.source
    }
}

impl Eq for Expr {}

impl fmt::Display for Expr {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
    }
}

impl std::str::FromStr for Expr {
    type Err = FormulaError;

    fn from_str(source: &str) -> Result<Self, FormulaError> {
        parse(source)
    }
}

/// A syntax error in formula text.
#[derive(Debug)]
pub struct FormulaError(String);

impl fmt::Display for FormulaError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for FormulaError {}

/// Parse existing Chopper formula text. The Job resolves column references
/// when it opens the input.
pub fn parse(source: impl Into<String>) -> Result<Expr, FormulaError> {
    let source = source.into();
    Expression::parse(&source).map_err(FormulaError)?;
    Ok(Expr {
        source,
        precedence: Precedence::Unknown,
    })
}

/// Refer to an exact header name or a zero-based input position.
pub fn col(column: impl Into<Column>) -> Expr {
    Expr::atom(match column.into() {
        Column::Name(name) => format!("[{}]", name.replace(']', "]]")),
        Column::Index(index) => format!("${index}"),
    })
}

/// Convert a text, boolean, or numeric value to a literal expression.
/// The formula parser rejects non-finite numbers at validation.
pub fn lit(value: impl Into<Expr>) -> Expr {
    value.into()
}

/// Build a NULL literal.
pub fn null() -> Expr {
    Expr::atom("NULL")
}

impl From<&Expr> for Expr {
    fn from(value: &Expr) -> Self {
        value.clone()
    }
}

impl From<&str> for Expr {
    fn from(value: &str) -> Self {
        Self::atom(format!("\"{}\"", value.replace('"', "\"\"")))
    }
}

impl From<String> for Expr {
    fn from(value: String) -> Self {
        value.as_str().into()
    }
}

impl From<bool> for Expr {
    fn from(value: bool) -> Self {
        Self::atom(if value { "TRUE" } else { "FALSE" })
    }
}

macro_rules! integer_literals {
    ($($kind:ty),+ $(,)?) => {
        $(impl From<$kind> for Expr {
            fn from(value: $kind) -> Self {
                Self::atom(value.to_string())
            }
        })+
    };
}

integer_literals!(i8, i16, i32, i64, i128, isize, u8, u16, u32, u64, u128, usize);

impl From<f64> for Expr {
    fn from(value: f64) -> Self {
        if !value.is_finite() {
            // This literal fails the shared finite-number check without looking like a header.
            return Self::atom("1e9999");
        }
        let decimal = value.to_string();
        let scientific = format!("{value:e}");
        Self::atom(if scientific.len() < decimal.len() {
            scientific
        } else {
            decimal
        })
    }
}

impl From<f32> for Expr {
    fn from(value: f32) -> Self {
        f64::from(value).into()
    }
}

macro_rules! binary_operator {
    ($trait:ident, $method:ident, $operator:literal, $precedence:ident) => {
        impl<Rhs: Into<Expr>> $trait<Rhs> for Expr {
            type Output = Self;

            fn $method(self, rhs: Rhs) -> Self {
                self.binary(rhs.into(), $operator, Precedence::$precedence)
            }
        }
    };
}

binary_operator!(Add, add, "+", Additive);
binary_operator!(Sub, sub, "-", Additive);
binary_operator!(Mul, mul, "*", Multiplicative);
binary_operator!(Div, div, "/", Multiplicative);
binary_operator!(Rem, rem, "%", Multiplicative);
binary_operator!(BitAnd, bitand, "AND", And);
binary_operator!(BitOr, bitor, "OR", Or);

impl Not for Expr {
    type Output = Self;

    fn not(self) -> Self {
        Self {
            source: format!("NOT {}", self.operand(Precedence::Not, false)),
            precedence: Precedence::Not,
        }
    }
}

fn function(name: &str, arguments: impl IntoIterator<Item = Expr>) -> Expr {
    let mut source = name.to_owned();
    source.push('(');
    let mut arguments = arguments.into_iter();
    if let Some(first) = arguments.next() {
        source.push_str(first.as_str());
        for expression in arguments {
            source.push_str(", ");
            source.push_str(expression.as_str());
        }
    }
    source.push(')');
    Expr::atom(source)
}
