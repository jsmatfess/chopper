"""Compose row formulas for calculated columns."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from math import isfinite
from sys import maxsize
from typing import Never

from ._native import _validate_formula


class _Precedence(IntEnum):
    UNKNOWN = 0
    OR = 1
    AND = 2
    NOT = 3
    COMPARISON = 4
    ADDITIVE = 5
    MULTIPLICATIVE = 6
    ATOM = 7


_BINARY_PRECEDENCE = {
    "OR": _Precedence.OR,
    "AND": _Precedence.AND,
    "=": _Precedence.COMPARISON,
    "!=": _Precedence.COMPARISON,
    "<": _Precedence.COMPARISON,
    "<=": _Precedence.COMPARISON,
    ">": _Precedence.COMPARISON,
    ">=": _Precedence.COMPARISON,
    "+": _Precedence.ADDITIVE,
    "-": _Precedence.ADDITIVE,
    "*": _Precedence.MULTIPLICATIVE,
    "/": _Precedence.MULTIPLICATIVE,
    "%": _Precedence.MULTIPLICATIVE,
}


@dataclass(frozen=True, slots=True, init=False)
class Expr:
    """An immutable Chopper formula expression.

    ``==`` compares formula text. Use ``equal`` or another comparison method
    to construct a condition on row values.
    """

    _source: str
    _precedence: _Precedence = field(compare=False, repr=False)

    def __init__(self, source: str):
        _validate_formula(source)
        object.__setattr__(self, "_source", source)
        object.__setattr__(self, "_precedence", _Precedence.UNKNOWN)

    @classmethod
    def _from_source(cls, source: str, precedence: _Precedence = _Precedence.ATOM) -> Expr:
        # Composition uses known grammar. Job validation checks the entire formula.
        expression = cls.__new__(cls)
        object.__setattr__(expression, "_source", source)
        object.__setattr__(expression, "_precedence", precedence)
        return expression

    def as_str(self) -> str:
        """Return the expression's formula text."""
        return self._source

    def equal(self, other: ExprLike) -> Expr:
        """Compare row values for equality."""
        return _binary(self, "=", other)

    def not_equal(self, other: ExprLike) -> Expr:
        """Compare row values for inequality."""
        return _binary(self, "!=", other)

    def lt(self, other: ExprLike) -> Expr:
        """Compare whether this row value is less than the other value."""
        return _binary(self, "<", other)

    def le(self, other: ExprLike) -> Expr:
        """Compare whether this row value is less than or equal to the other value."""
        return _binary(self, "<=", other)

    def gt(self, other: ExprLike) -> Expr:
        """Compare whether this row value is greater than the other value."""
        return _binary(self, ">", other)

    def ge(self, other: ExprLike) -> Expr:
        """Compare whether this row value is greater than or equal to the other value."""
        return _binary(self, ">=", other)

    def and_(self, other: ExprLike) -> Expr:
        """Combine two formula expressions with AND, as with the `&` operator."""
        return self & other

    def or_(self, other: ExprLike) -> Expr:
        """Combine two formula expressions with OR, as with the `|` operator."""
        return self | other

    def not_(self) -> Expr:
        """Negate a formula expression with NOT, as with the `~` operator."""
        return ~self

    def __str__(self) -> str:
        return self._source

    def __bool__(self) -> Never:
        raise TypeError("a formula has no Python truth value; compose it with &, |, or ~")

    def _operand(self, parent: _Precedence, *, wrap_equal: bool = False) -> str:
        if self._precedence < parent or (wrap_equal and self._precedence == parent):
            return f"({self})"
        return self._source

    def __and__(self, other: ExprLike) -> Expr:
        return _binary(self, "AND", other)

    def __rand__(self, other: ExprLike) -> Expr:
        return _binary(other, "AND", self)

    def __or__(self, other: ExprLike) -> Expr:
        return _binary(self, "OR", other)

    def __ror__(self, other: ExprLike) -> Expr:
        return _binary(other, "OR", self)

    def __invert__(self) -> Expr:
        operand = self._operand(_Precedence.NOT)
        return Expr._from_source(f"NOT {operand}", _Precedence.NOT)

    def __add__(self, other: ExprLike) -> Expr:
        return _binary(self, "+", other)

    def __radd__(self, other: ExprLike) -> Expr:
        return _binary(other, "+", self)

    def __sub__(self, other: ExprLike) -> Expr:
        return _binary(self, "-", other)

    def __rsub__(self, other: ExprLike) -> Expr:
        return _binary(other, "-", self)

    def __mul__(self, other: ExprLike) -> Expr:
        return _binary(self, "*", other)

    def __rmul__(self, other: ExprLike) -> Expr:
        return _binary(other, "*", self)

    def __truediv__(self, other: ExprLike) -> Expr:
        return _binary(self, "/", other)

    def __rtruediv__(self, other: ExprLike) -> Expr:
        return _binary(other, "/", self)

    def __mod__(self, other: ExprLike) -> Expr:
        return _binary(self, "%", other)

    def __rmod__(self, other: ExprLike) -> Expr:
        return _binary(other, "%", self)


ExprLike = Expr | str | bool | int | float | None


def col(column: str | int) -> Expr:
    """Reference a column by exact header name or zero-based index."""
    if isinstance(column, str):
        name = str.replace(column, "]", "]]")
        return Expr._from_source(f"[{name}]")
    if isinstance(column, bool) or not isinstance(column, int):
        raise TypeError("column must be a header name or an integer index")
    index = int(column)
    if not 0 <= index <= 2 * maxsize + 1:
        raise ValueError("column index is outside the supported range")
    return Expr._from_source(f"${index}")


def lit(value: ExprLike) -> Expr:
    """Make a text, numeric, Boolean or null literal, or return an existing expression."""
    if isinstance(value, Expr):
        return value
    if isinstance(value, str):
        text = str.replace(value, '"', '""')
        return Expr._from_source(f'"{text}"')
    if value is None:
        return Expr._from_source("NULL")
    if isinstance(value, bool):
        return Expr._from_source("TRUE" if value else "FALSE")
    if isinstance(value, (int, float)):
        number = int(value) if isinstance(value, int) else float(value)
        try:
            finite = isfinite(number)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("formula number must be finite")
        return Expr._from_source(str(number))
    raise TypeError("formula literals must be strings, numbers, Booleans or None")


def parse(source: str) -> Expr:
    """Check formula text and preserve its spelling for composition or reuse."""
    return Expr(source)


def _binary(left: ExprLike, operator: str, right: ExprLike) -> Expr:
    precedence = _BINARY_PRECEDENCE[operator]
    left_source = lit(left)._operand(precedence)
    # Equal-precedence operators are left-associative.
    right_source = lit(right)._operand(precedence, wrap_equal=True)
    return Expr._from_source(f"{left_source} {operator} {right_source}", precedence)


class _Omitted:
    __slots__ = ()

    def __repr__(self) -> str:
        return "<omitted>"


_OMITTED = _Omitted()


def _function(name: str, *args: ExprLike | _Omitted) -> Expr:
    end = len(args)
    while end and isinstance(args[end - 1], _Omitted):
        end -= 1
    expressions = []
    for arg in args[:end]:
        if isinstance(arg, _Omitted):
            raise TypeError("supply earlier optional arguments before later ones")
        expressions.append(lit(arg).as_str())
    return Expr._from_source(f"{name}({', '.join(expressions)})")
