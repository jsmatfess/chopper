#!/usr/bin/env python3
"""Generate named Rust and Python builders from the core formula catalog."""

import argparse
from dataclasses import dataclass
import keyword
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "crates/chopper-core/src/expression.rs"
RUST = ROOT / "crates/chopper/src/formula/functions.rs"
PYTHON = ROOT / "crates/chopper-python/python/chopper_csv/functions.py"
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
