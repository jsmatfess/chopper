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
    fmt,
    ops::{Add, Div, Mul, Sub},
};

pub mod functions;

/// A composable formula for a calculated column.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Expr(String);

impl Expr {
    /// Borrow the formula text used in saved Job JSON.
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// Name this expression as a calculated column in a Job.
    pub fn alias(self, name: impl Into<String>) -> CalculatedColumn {
        CalculatedColumn {
            name: name.into(),
            expression: self.0,
        }
    }
}

impl fmt::Display for Expr {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.as_str())
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
    Ok(Expr(source))
}

/// Refer to an exact header name or a zero-based input position.
pub fn col(column: impl Into<Column>) -> Expr {
    Expr(match column.into() {
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
    Expr("NULL".into())
}

impl From<&Expr> for Expr {
    fn from(value: &Expr) -> Self {
        value.clone()
    }
}

impl From<&str> for Expr {
    fn from(value: &str) -> Self {
        Self(format!("\"{}\"", value.replace('"', "\"\"")))
    }
}

impl From<String> for Expr {
    fn from(value: String) -> Self {
        value.as_str().into()
    }
}

impl From<bool> for Expr {
    fn from(value: bool) -> Self {
        Self(if value { "TRUE" } else { "FALSE" }.into())
    }
}

macro_rules! integer_literals {
    ($($kind:ty),+ $(,)?) => {
        $(impl From<$kind> for Expr {
            fn from(value: $kind) -> Self {
                Self(value.to_string())
            }
        })+
    };
}

integer_literals!(i8, i16, i32, i64, i128, isize, u8, u16, u32, u64, u128, usize);

impl From<f64> for Expr {
    fn from(value: f64) -> Self {
        if value.is_finite() {
            Self(value.to_string())
        } else {
            // This literal fails the shared finite-number check without looking like a header.
            Self("1e9999".into())
        }
    }
}

impl From<f32> for Expr {
    fn from(value: f32) -> Self {
        f64::from(value).into()
    }
}

macro_rules! arithmetic {
    ($trait:ident, $method:ident, $operator:literal) => {
        impl<Rhs: Into<Expr>> $trait<Rhs> for Expr {
            type Output = Self;

            fn $method(self, rhs: Rhs) -> Self {
                Self(format!("({self}) {} ({})", $operator, rhs.into()))
            }
        }
    };
}

arithmetic!(Add, add, "+");
arithmetic!(Sub, sub, "-");
arithmetic!(Mul, mul, "*");
arithmetic!(Div, div, "/");

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
    Expr(source)
}
