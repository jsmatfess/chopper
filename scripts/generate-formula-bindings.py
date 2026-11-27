#!/usr/bin/env python3
"""Generate SDK builders and reference syntax from the core formula catalog."""

import argparse
from dataclasses import dataclass
import json
import keyword
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "crates/chopper-core/src/expression.rs"
RUST = ROOT / "crates/chopper/src/formula/functions.rs"
PYTHON = ROOT / "crates/chopper-python/python/chopper_csv/functions.py"
REFERENCE = ROOT / "docs/formula-functions.md"
REFERENCE_SYNTAX = ROOT / "docs/formula-reference-syntax.json"
COMMAND = "python scripts/generate-formula-bindings.py"

ROW = re.compile(r'([A-Z][A-Z0-9_]*),\s*"([^"]+)",\s*([0-9]+),\s*([0-9]+);')
PARAMETER = re.compile(r"[a-z][a-z0-9_]*\??")
VARIADIC = {
    "CONCAT": ("CONCAT(text, ...)", 1, 64),
    "COALESCE": ("COALESCE(value, ...)", 1, 64),
    "CONCAT_WS": ("CONCAT_WS(separator, text, ..., ignore_null?, ignore_empty?)", 2, 66),
    "IFS": ("IFS(condition, value, ..., fallback)", 3, 63),
}


@dataclass(frozen=True)
class Binding:
    name: str
    signature: str
    required: tuple[str, ...]
    optional: str | None = None

    @property
    def sdk_name(self) -> str:
        return "if_else" if self.name == "IF" else self.name.lower()


def parameter_name(name: str) -> str:
    return f"{name}_" if name in {"from", "match"} or keyword.iskeyword(name) else name


def parse_catalog(source: str) -> list[Binding]:
    blocks = re.findall(r"^functions! \{\n(.*?)^\}", source, re.MULTILINE | re.DOTALL)
    if len(blocks) != 1:
        raise ValueError("expected one functions! definition in expression.rs")

    bindings = []
    used_names = set()
    for line in blocks[0].splitlines():
        if not line.strip():
            continue
        row = ROW.fullmatch(line.strip())
        if row is None:
            raise ValueError(f"unrecognized formula catalog row {line.strip()!r}")
        name, signature, minimum, maximum = row.groups()
        minimum, maximum = int(minimum), int(maximum)
        if name in VARIADIC:
            if (signature, minimum, maximum) != VARIADIC[name]:
                raise ValueError(f"unrecognized variadic signature {signature!r}")
            binding = Binding(name, signature, ())
        else:
            if not signature.startswith(f"{name}(") or not signature.endswith(")"):
                raise ValueError(f"signature {signature!r} does not match {name}")
            args = signature[len(name) + 1:-1].split(", ")
            if (
                not all(PARAMETER.fullmatch(arg) for arg in args)
                or len(args) != maximum
                or minimum < 1
                or (maximum - minimum) not in (0, 1)
                or any(arg.endswith("?") != (index >= minimum) for index, arg in enumerate(args))
            ):
                raise ValueError(f"unrecognized formula signature {signature!r}")
            names = [parameter_name(arg.removesuffix("?")) for arg in args]
            if len(set(names)) != len(names):
                raise ValueError(f"duplicate SDK parameter in {signature!r}")
            optional = names[minimum] if minimum < maximum else None
            binding = Binding(name, signature, tuple(names[:minimum]), optional)
        if binding.sdk_name in used_names:
            raise ValueError(f"duplicate SDK function {binding.sdk_name!r}")
        used_names.add(binding.sdk_name)
        bindings.append(binding)
    if not bindings:
        raise ValueError("the core formula catalog is empty")
    return bindings


def rust_special(binding: Binding) -> tuple[list[str], list[str], str]:
    match binding.name:
        case "CONCAT" | "COALESCE":
            return ["values: impl IntoIterator<Item = Expr>"], [
                f'function("{binding.name}", values)',
            ], "Pass the expressions in formula argument order."
        case "CONCAT_WS":
            return ["separator: impl Into<Expr>", "values: impl IntoIterator<Item = Expr>"], [
                "let arguments = std::iter::once(separator.into()).chain(values);",
                'function("CONCAT_WS", arguments)',
            ], "Append optional literal Boolean flags for `ignore_null` and `ignore_empty` in that order."
        case "IFS":
            return ["cases: impl IntoIterator<Item = (Expr, Expr)>", "fallback: impl Into<Expr>"], [
                "let arguments = cases",
                "    .into_iter()",
                "    .flat_map(|(condition, value)| [condition, value]);",
                'function("IFS", arguments.chain(std::iter::once(fallback.into())))',
            ], "Pass ordered condition and value pairs followed by a fallback expression."
    raise ValueError(f"missing Rust generation for {binding.name}")


def rust_function(binding: Binding) -> str:
    docs = [f"/// Build the `{binding.signature}` expression."]
    if binding.name in VARIADIC:
        parameters, body, usage = rust_special(binding)
        docs.append(f"/// {usage}")
    else:
        parameters = [f"{name}: impl Into<Expr>" for name in binding.required]
        arguments = f"[{', '.join(f'{name}.into()' for name in binding.required)}]"
        if binding.optional is None:
            body = [
                f"let arguments = {arguments};",
                f'function("{binding.name}", arguments)',
            ]
        else:
            parameters.append(f"{binding.optional}: Option<Expr>")
            docs.append(f"/// Pass `None` to omit `{binding.optional}`.")
            body = [
                f"let arguments = {arguments};",
                f'function("{binding.name}", arguments.into_iter().chain({binding.optional}))',
            ]

    declaration = f"pub fn {binding.sdk_name}({', '.join(parameters)}) -> Expr {{"
    if len(declaration) > 100:
        arguments = "".join(f"    {parameter},\n" for parameter in parameters)
        declaration = f"pub fn {binding.sdk_name}(\n{arguments}) -> Expr {{"
    return "\n".join([*docs, declaration, *(f"    {line}" for line in body), "}"])


def python_special(binding: Binding) -> tuple[list[str], list[str], str]:
    match binding.name:
        case "CONCAT":
            return ["text: ExprLike", "*additional_text: ExprLike"], [
                'return _function("CONCAT", text, *additional_text)',
            ], ""
        case "COALESCE":
            return ["value: ExprLike", "*additional_values: ExprLike"], [
                'return _function("COALESCE", value, *additional_values)',
            ], ""
        case "CONCAT_WS":
            return ["separator: ExprLike", "text: ExprLike", "*additional_text_and_flags: ExprLike"], [
                'return _function("CONCAT_WS", separator, text, *additional_text_and_flags)',
            ], "Append optional literal Boolean flags for ignore_null and ignore_empty in that order."
        case "IFS":
            return ["*cases: tuple[ExprLike, ExprLike]", "fallback: ExprLike"], [
                "arguments = [",
                "    argument for condition, value in cases for argument in (condition, value)",
                "]",
                'return _function("IFS", *arguments, fallback)',
            ], "Pass ordered (condition, value) pairs and a keyword fallback."
    raise ValueError(f"missing Python generation for {binding.name}")


def python_function(binding: Binding) -> str:
    docs = f'"""Build a Chopper `{binding.signature}` expression.'
    if binding.name in VARIADIC:
        parameters, body, usage = python_special(binding)
    else:
        parameters = [f"{name}: ExprLike" for name in binding.required]
        arguments = ", ".join(binding.required)
        usage = ""
        if binding.optional is not None:
            parameters.append(f"{binding.optional}: ExprLike | _Omitted = _OMITTED")
            arguments += f", {binding.optional}"
            usage = f"Omit {binding.optional} to use the engine default. None emits NULL."
        body = [f'return _function("{binding.name}", {arguments})']
    if usage:
        docs += f'\n\n    {usage}\n    """'
    else:
        docs += '"""'

    declaration = f"def {binding.sdk_name}({', '.join(parameters)}) -> Expr:"
    if len(declaration) > 88:
        arguments = "".join(f"    {parameter},\n" for parameter in parameters)
        declaration = f"def {binding.sdk_name}(\n{arguments}) -> Expr:"
    return "\n".join([declaration, f"    {docs}", *(f"    {line}" for line in body)])


@dataclass(frozen=True)
class Snippet:
    rust: str
    python: str
    rust_literal: bool = False

    def rust_expr(self) -> str:
        return f"lit({self.rust})" if self.rust_literal else self.rust


INLINE_CODE = re.compile(r"`([^`]+)`")
EXAMPLE = re.compile(r"`([^`]+)`\s*→")
TEXT_LITERAL = re.compile(r'"(?:[^"]|"")*"')
COLUMN_NAME = re.compile(r"\[(?:[^\]]|\]\])*\]")
NUMBER_LITERAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
FORMULA_CALL = re.compile(r"(SAFE\.)?([A-Z][A-Z0-9_]*)\((.*)\)")
ARGUMENT_TOKEN = re.compile(rf'{TEXT_LITERAL.pattern}|{COLUMN_NAME.pattern}|[(),"\[]')


def sdk_call(name: str, rust: list[str], python: list[str]) -> Snippet:
    return Snippet(f"f::{name}({', '.join(rust)})", f"f.{name}({', '.join(python)})")


def sdk_signature(binding: Binding) -> Snippet:
    if binding.name in VARIADIC:
        rust = [parameter.split(":", 1)[0] for parameter in rust_special(binding)[0]]
        python = [parameter.split(":", 1)[0] for parameter in python_special(binding)[0]]
        if binding.name == "IFS":
            python[-1] = "fallback=fallback"
    else:
        rust = list(binding.required)
        python = list(binding.required)
        if binding.optional is not None:
            rust.append(binding.optional)
            python.append(f"{binding.optional}={binding.optional}")
    return sdk_call(binding.sdk_name, rust, python)


def sdk_string(source: str) -> Snippet:
    rust = source.replace("\\", "\\\\").replace('"', '\\"')
    rust = re.sub(r"[\x00-\x1f]", lambda char: f"\\u{{{ord(char[0]):x}}}", rust)
    return Snippet(f'"{rust}"', json.dumps(source, ensure_ascii=False), rust_literal=True)


def parsed_snippet(source: str) -> Snippet:
    text = sdk_string(source)
    return Snippet(f"parse({text.rust})?", f"parse({text.python})")


def split_arguments(source: str) -> list[str] | None:
    # Find commas outside quoted text and nested calls. The SDK's parse handles
    # formula syntax beyond the examples we can express with named builders.
    arguments = []
    start = depth = 0
    for token in ARGUMENT_TOKEN.finditer(source):
        match token[0]:
            case "(":
                depth += 1
            case ")":
                depth -= 1
                if depth < 0:
                    return None
            case "," if depth == 0:
                arguments.append(source[start:token.start()].strip())
                start = token.end()
            case '"' | "[":
                return None
    arguments.append(source[start:].strip())
    return arguments if depth == 0 and all(arguments) else None


def sdk_example_call(binding: Binding, arguments: list[Snippet]) -> Snippet:
    rust = [argument.rust for argument in arguments]
    python = [argument.python for argument in arguments]
    match binding.name:
        case "CONCAT" | "COALESCE" | "CONCAT_WS":
            start = int(binding.name == "CONCAT_WS")
            values = ", ".join(argument.rust_expr() for argument in arguments[start:])
            rust = [*rust[:start], f"[{values}]"]
        case "IFS":
            pairs = list(zip(arguments[:-1:2], arguments[1:-1:2], strict=True))
            rust_cases = ", ".join(f"({a.rust_expr()}, {b.rust_expr()})" for a, b in pairs)
            python_cases = [f"({a.python}, {b.python})" for a, b in pairs]
            rust = [f"[{rust_cases}]", rust[-1]]
            python = [*python_cases, f"fallback={python[-1]}"]
        case _ if binding.optional is not None:
            if len(arguments) == len(binding.required):
                rust.append("None")
            else:
                rust[-1] = f"Some({arguments[-1].rust_expr()})"
                python[-1] = f"{binding.optional}={python[-1]}"
    return sdk_call(binding.sdk_name, rust, python)


def sdk_example(source: str, bindings: dict[str, Binding]) -> Snippet:
    if TEXT_LITERAL.fullmatch(source):
        return sdk_string(source[1:-1].replace('""', '"'))
    if COLUMN_NAME.fullmatch(source):
        name = sdk_string(source[1:-1].replace("]]", "]"))
        return Snippet(f"col({name.rust})", f"col({name.python})")
    if re.fullmatch(r"\$(?:0|[1-9][0-9]*)", source):
        return Snippet(f"col({source[1:]})", f"col({source[1:]})")
    if NUMBER_LITERAL.fullmatch(source):
        return Snippet(source, source, rust_literal=True)
    match source:
        case "NULL":
            return Snippet("null()", "None")
        case "TRUE" | "FALSE":
            return Snippet(source.lower(), source.title(), rust_literal=True)
    call = FORMULA_CALL.fullmatch(source)
    if call is None or call[2] not in bindings:
        return parsed_snippet(source)
    arguments = split_arguments(call[3])
    if arguments is None:
        return parsed_snippet(source)
    binding = bindings[call[2]]
    minimum = len(binding.required)
    maximum = minimum + int(binding.optional is not None)
    if binding.name in VARIADIC:
        _, minimum, maximum = VARIADIC[binding.name]
    if not minimum <= len(arguments) <= maximum:
        raise ValueError(f"invalid argument count in formula reference example {source!r}")
    snippet = sdk_example_call(binding, [sdk_example(argument, bindings) for argument in arguments])
    if call[1] is not None:
        return sdk_call("safe", [snippet.rust], [snippet.python])
    return snippet


def render_reference(bindings: list[Binding], source: str) -> str:
    by_name = {binding.name: binding for binding in bindings}
    signatures = {binding.signature: sdk_signature(binding) for binding in bindings}
    operators = {
        **{op: Snippet(f"left {op} right", f"left {op} right") for op in ("+", "-", "*", "/")},
        **{op: parsed_snippet(f"5 {op} 2") for op in ("%", "=", "!=", "<>", "<", "<=", ">", ">=")},
        "&": Snippet("f::concat([left, right])", "f.concat(left, right)"),
        "AND": Snippet("left.and(right)", "left.and_(right)"),
        "OR": Snippet("left.or(right)", "left.or_(right)"),
        "NOT": Snippet("expr.not()", "expr.not_()"),
    }
    code = {}
    table = ""
    for line in source.splitlines():
        if not line.startswith("|"):
            table = ""
            continue
        if line == "| Function | Behavior | Examples |":
            table = "functions"
            continue
        if line == "| Operator | Behavior |":
            table = "operators"
            continue
        if not table or line.startswith("| ---"):
            continue
        cells = [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        names = INLINE_CODE.findall(cells[0])
        if table == "operators":
            for name in names:
                if name not in operators:
                    raise ValueError(f"unknown operator in the formula reference {name!r}")
                code[name] = operators[name]
            continue
        if len(cells) != 3 or len(names) != 1 or names[0] not in signatures:
            raise ValueError(f"unrecognized function row in the formula reference {line!r}")
        code[names[0]] = signatures[names[0]]
        for item in re.split(r"<br\s*/?>", cells[2]):
            example = EXAMPLE.match(item.strip())
            if example is None:
                raise ValueError(f"unrecognized example in the formula reference {item!r}")
            code[example[1]] = sdk_example(example[1], by_name)

    missing = (signatures.keys() | operators.keys()) - code.keys()
    if missing:
        raise ValueError(f"missing rows in the formula reference: {', '.join(sorted(missing))}")
    payload = {
        "schema_version": 1,
        "code": {key: {"rust": item.rust, "python": item.python} for key, item in code.items()},
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render(bindings: list[Binding]) -> dict[Path, str]:
    rust_header = (
        f"// Generated by `{COMMAND}`.\n"
        "//! Named builders for the engine's calculated-column functions.\n"
        "//! The engine checks argument types and literal requirements when a Job uses the expression.\n"
        "\nuse super::{function, Expr};"
    )
    python_header = (
        '"""Named builders for the engine\'s calculated-column functions."""\n'
        f"\n# Generated by `{COMMAND}`.\n"
        "from ._formula import Expr, ExprLike, _Omitted, _OMITTED, _function\n"
        "\n__all__ = [\n"
        + "".join(f'    "{binding.sdk_name}",\n' for binding in bindings)
        + "]"
    )
    return {
        RUST: "\n\n".join([rust_header, *(rust_function(binding) for binding in bindings)]) + "\n",
        PYTHON: "\n\n\n".join([python_header, *(python_function(binding) for binding in bindings)]) + "\n",
        REFERENCE_SYNTAX: render_reference(bindings, REFERENCE.read_text(encoding="utf-8")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if a generated file is stale")
    args = parser.parse_args()
    try:
        outputs = render(parse_catalog(CATALOG.read_text(encoding="utf-8")))
        if args.check:
            stale = [
                str(path.relative_to(ROOT))
                for path, expected in outputs.items()
                if not path.is_file() or path.read_text(encoding="utf-8") != expected
            ]
            if stale:
                print(f"Stale formula bindings: {', '.join(stale)}. Run {COMMAND}.", file=sys.stderr)
                return 1
        else:
            for path, expected in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8", newline="\n")
    except (OSError, ValueError) as error:
        print(f"Cannot generate formula bindings: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
