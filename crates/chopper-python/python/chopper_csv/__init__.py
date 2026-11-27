"""Compose, load and execute file-to-file Chopper Jobs."""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import repeat
import json
from os import PathLike
from typing import Any

from . import functions
from ._formula import Expr, col, lit, parse
from ._native import (
    ChopperError,
    ExecutionControl as _NativeExecutionControl,
    NativeJob as _NativeJob,
    formula_functions,
)
from ._reports import (
    AnalyzeReport,
    DetectedDialect,
    InputReport,
    ManifestHeader,
    ManifestOutput,
    ManifestReader,
    Progress,
    RunReport,
    open_manifest,
)

__all__ = [
    "AnalyzeReport", "ChopperError", "DetectedDialect", "ExecutionControl", "Expr", "InputReport",
    "Job", "ManifestHeader", "ManifestOutput", "ManifestReader", "Pipeline", "Progress", "RunReport",
    "analyze", "assign", "assign_probabilistic", "balanced", "col", "detect_dialect",
    "formula_functions", "functions", "inspect", "interleaved", "iter_columns", "lit", "open_manifest",
    "parse", "partition", "preview", "run", "shuffle", "validate",
]

_Column = str | int


@dataclass(frozen=True, slots=True)
class _Operation:
    source: str


def _json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    # Keep UTF-8 Job sizes comparable to saved files. Escape lone surrogates
    # so the shared decoder, rather than Python's UTF-8 bridge, diagnoses them.
    return text.encode("utf-8", errors="backslashreplace").decode("utf-8")


def _operation(kind: str, **settings: Any) -> _Operation:
    return _Operation(_json({"type": kind, **settings}))


@dataclass(frozen=True, slots=True, init=False)
class Pipeline:
    """An ordered pipeline that can be reused as the prefix of several Jobs."""

    _operations: tuple[_Operation, ...]

    def __init__(self):
        object.__setattr__(self, "_operations", ())

    def then(self, step: "_Operation | Pipeline") -> "Pipeline":
        """Return a new pipeline with an operation or pipeline appended."""
        if isinstance(step, Pipeline):
            tail = step._operations
        elif isinstance(step, _Operation):
            tail = (step,)
        else:
            raise TypeError("then() expects an operation or Pipeline")
        result = Pipeline()
        object.__setattr__(result, "_operations", self._operations + tail)
        return result


def partition(columns: Sequence[_Column]) -> _Operation:
    """Partition by exact header names or zero-based column indices."""
    return _operation("partition", columns=columns)


def assign(groups: Sequence[dict[str, str]], *, strata: Sequence[_Column] = ()) -> _Operation:
    """Assign exact quotas from ordered name/percent records."""
    return _operation("assign", groups=groups, strata=strata)


def assign_probabilistic(
    groups: Sequence[dict[str, str]], *, strata: Sequence[_Column] = (),
) -> _Operation:
    """Assign by independent draws using ordered name/percent records."""
    return _operation("assign_probabilistic", groups=groups, strata=strata)


def shuffle(strategy: str = "uniform") -> _Operation:
    """Shuffle independently within each group."""
    return _operation("shuffle", strategy=strategy)


def balanced(files: int) -> _Operation:
    """Split each group into the requested number of consecutive balanced parts."""
    return _operation("balanced", files=files)


def interleaved(files: int) -> _Operation:
    """Split each group into the requested number of round-robin parts."""
    return _operation("interleaved", files=files)


class ExecutionControl:
    """Cancellation and progress for one Analyze or Run call."""

    __slots__ = ("_inner",)

    def __init__(self) -> None:
        self._inner = _NativeExecutionControl()

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self._inner.cancel()

    def progress(self) -> Progress:
        """Return a snapshot of the latest execution progress."""
        return Progress(self._inner.progress())


def _native_control(control: ExecutionControl | None) -> _NativeExecutionControl | None:
    if control is None:
        return None
    if not isinstance(control, ExecutionControl):
        raise TypeError("control must be an ExecutionControl or None")
    return control._inner


class Job:
    """A reusable Job backed by the same settings and engine as the CLI."""

    __slots__ = ("_native",)

    def __init__(
        self,
        settings: dict[str, Any],
        *,
        pipeline: Pipeline | None = None,
        calculated_columns: Mapping[str, Expr | str] | None = None,
    ):
        if not isinstance(settings, dict):
            raise TypeError("Job settings must be a dictionary")
        if pipeline is not None:
            if not isinstance(pipeline, Pipeline):
                raise TypeError("pipeline must be a Pipeline")
            if "operations" in settings:
                raise TypeError("supply either operations or a pipeline")
            settings = {
                **settings,
                "operations": [json.loads(step.source) for step in pipeline._operations],
            }
        if calculated_columns is not None:
            if not isinstance(calculated_columns, Mapping):
                raise TypeError("calculated_columns must be a mapping")
            if "calculated_columns" in settings:
                raise TypeError("supply calculated_columns in settings or as a keyword")
            definitions = []
            for name, expression in calculated_columns.items():
                if not isinstance(name, str):
                    raise TypeError("calculated column names must be strings")
                if isinstance(expression, Expr):
                    expression = expression.as_str()
                elif not isinstance(expression, str):
                    raise TypeError("calculated column expressions must be Expr or str")
                definitions.append({"name": name, "expression": expression})
            settings = {**settings, "calculated_columns": definitions}
        self._native = _NativeJob.from_json(_json(settings))

    @classmethod
    def load(cls, path: str | PathLike[str]) -> "Job":
        """Read saved Job JSON. Relative paths resolve from the working directory."""
        job = cls.__new__(cls)
        job._native = _NativeJob.load(path)
        return job

    @classmethod
    def from_json(cls, source: str) -> "Job":
        """Decode a Job from a versioned JSON string."""
        job = cls.__new__(cls)
        job._native = _NativeJob.from_json(source)
        return job

    def to_dict(self) -> dict[str, Any]:
        """Return the Job settings as an independent dictionary."""
        return self._native.to_dict()

    def save(self, path: str | PathLike[str]) -> None:
        """Save this Job in the CLI's versioned JSON format."""
        self._native.save(path)

    def validate(self) -> None:
        """Check configuration and raise ChopperError on failure."""
        self._native.validate()

    def inspect(self) -> InputReport:
        """Discover input columns from the first parsed record."""
        return InputReport(self._native.inspect())

    def preview(self) -> InputReport:
        """Discover input columns and sample up to eight data records."""
        return InputReport(self._native.preview())

    def detect_dialect(self) -> DetectedDialect:
        """Suggest CSV settings from a bounded sample of the input."""
        return DetectedDialect(self._native.detect_dialect())

    def analyze(self, control: ExecutionControl | None = None) -> AnalyzeReport:
        """Return bounded statistics and advisory estimates."""
        return AnalyzeReport(self._native.analyze(_native_control(control)))

    def run(self, control: ExecutionControl | None = None) -> RunReport:
        """Run the Job and return aggregate counts and the manifest path."""
        return RunReport(self._native.run(_native_control(control)))


def validate(settings: dict[str, Any]) -> None:
    """Validate a dictionary Job."""
    Job(settings).validate()


def inspect(settings: dict[str, Any]) -> InputReport:
    """Discover input columns for a dictionary Job."""
    return Job(settings).inspect()


def preview(settings: dict[str, Any]) -> InputReport:
    """Preview the input for a dictionary Job."""
    return Job(settings).preview()


def detect_dialect(settings: dict[str, Any]) -> DetectedDialect:
    """Suggest CSV settings for a dictionary Job."""
    return Job(settings).detect_dialect()


def iter_columns(report: Mapping[str, Any]) -> Iterator[tuple[int, str | None]]:
    """Yield zero-based column indices and optional names from an input report."""
    header = report.get("header")
    names = header if header is not None else repeat(None, report["columns"])
    return enumerate(names)


def analyze(settings: dict[str, Any], control: ExecutionControl | None = None) -> AnalyzeReport:
    """Analyze a dictionary Job."""
    return Job(settings).analyze(control)


def run(settings: dict[str, Any], control: ExecutionControl | None = None) -> RunReport:
    """Run a dictionary Job."""
    return Job(settings).run(control)
