"""Compose, load and execute file-to-file Chopper Jobs."""

from collections.abc import Sequence
from dataclasses import dataclass
import json
from os import PathLike
from typing import Any

from ._native import ChopperError, ExecutionControl, NativeJob as _NativeJob

__all__ = [
    "ChopperError", "ExecutionControl", "Job", "Pipeline", "analyze", "assign",
    "assign_probabilistic", "balanced", "interleaved", "partition", "run", "shuffle",
    "validate",
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


class Job:
    """A reusable Job backed by the same settings and engine as the CLI."""

    __slots__ = ("_native",)

    def __init__(self, settings: dict[str, Any], *, pipeline: Pipeline | None = None):
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

    def analyze(self, control: ExecutionControl | None = None) -> dict[str, Any]:
        """Return bounded statistics and advisory estimates."""
        return self._native.analyze(control)

    def run(self, control: ExecutionControl | None = None) -> dict[str, Any]:
        """Run the Job and return aggregate counts and the manifest path."""
        return self._native.run(control)


def validate(settings: dict[str, Any]) -> None:
    """Validate a dictionary Job."""
    Job(settings).validate()


def analyze(settings: dict[str, Any], control: ExecutionControl | None = None) -> dict[str, Any]:
    """Analyze a dictionary Job."""
    return Job(settings).analyze(control)


def run(settings: dict[str, Any], control: ExecutionControl | None = None) -> dict[str, Any]:
    """Run a dictionary Job."""
    return Job(settings).run(control)
