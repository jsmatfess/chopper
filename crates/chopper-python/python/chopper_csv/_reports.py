"""Typed views of the native Job and manifest report dictionaries."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from os import PathLike
from pathlib import Path
from typing import Any, Literal

from ._native import ManifestReader as _NativeManifestReader
from ._native import open_manifest as _open_manifest


_DEFAULT_MANIFEST_RECORD_BYTES = 16 * 1024 * 1024


class _Report(Mapping[str, Any]):
    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def to_dict(self) -> dict[str, Any]:
        """Copy the JSON-ready report, including its nested values."""
        return deepcopy(self._data)


class AnalyzeReport(_Report):
    """Bounded input statistics and advisory estimates from Analyze."""

    __slots__ = ()

    @property
    def rows(self) -> int:
        return self["rows"]

    @property
    def columns(self) -> int:
        return self["columns"]

    @property
    def header(self) -> list[str] | None:
        return self["header"]

    @property
    def preview(self) -> list[list[str]]:
        return self["preview"]

    @property
    def column_values(self) -> list[dict[str, Any]]:
        return self["column_values"]

    @property
    def stages(self) -> list[dict[str, Any]]:
        return self["stages"]

    @property
    def writer_estimate(self) -> dict[str, Any] | None:
        return self.get("writer_estimate")

    @property
    def auto_observations(self) -> dict[str, Any] | None:
        return self.get("auto_observations")

    @property
    def suggested_run_memory_mb(self) -> int | None:
        return self.get("suggested_run_memory_mb")

    @property
    def cache_hit(self) -> bool:
        return self["cache_hit"]

    @property
    def seconds(self) -> float:
        return self["seconds"]

    @property
    def accuracy(self) -> str:
        return self["accuracy"]


class RunReport(_Report):
    """Aggregate counts and the manifest path for a published Run."""

    __slots__ = ()

    @property
    def rows(self) -> int:
        return self["rows"]

    @property
    def columns(self) -> int:
        return self["columns"]

    @property
    def groups(self) -> int:
        return self["groups"]

    @property
    def output_files(self) -> int:
        return self["output_files"]

    @property
    def output_csv_bytes(self) -> int:
        return self["output_csv_bytes"]

    @property
    def manifest_path(self) -> Path:
        return Path(self["manifest_path"])

    def outputs(self, *, max_record_bytes: int = _DEFAULT_MANIFEST_RECORD_BYTES) -> ManifestReader:
        """Open this Run's manifest to stream its output metadata."""
        return open_manifest(self.manifest_path, max_record_bytes=max_record_bytes)


class InputReport(_Report):
    """Input columns and optional preview rows from the configured parser."""

    __slots__ = ()

    @property
    def columns(self) -> int:
        return self["columns"]

    @property
    def header(self) -> list[str] | None:
        return self["header"]

    @property
    def input_is_zip(self) -> bool:
        return self["input_is_zip"]

    @property
    def preview(self) -> list[list[str]]:
        """Retained rows, empty for a column-only inspection."""
        return self.get("preview", [])

    @property
    def preview_row_numbers(self) -> list[int]:
        """One-based data-record numbers for the retained preview."""
        return self.get("preview_row_numbers", [])


class DetectedDialect(_Report):
    """Suggested CSV settings from a bounded input sample."""

    __slots__ = ()

    @property
    def settings(self) -> dict[str, Any]:
        return self["settings"]

    @property
    def delimiter_status(self) -> Literal["detected", "ambiguous", "not_detected"]:
        return self["delimiter_status"]

    @property
    def sample_bytes(self) -> int:
        return self["sample_bytes"]

    @property
    def note(self) -> str:
        return self["note"]


class ManifestHeader(_Report):
    """Metadata from the first record of a published result manifest."""

    __slots__ = ()

    @property
    def schema_version(self) -> int:
        return self["schema_version"]

    @property
    def application_version(self) -> str:
        return self["application_version"]

    @property
    def algorithm_version(self) -> str:
        return self["algorithm_version"]

    @property
    def compression(self) -> Literal["none", "gzip", "zip"]:
        return self["compression"]

    @property
    def rows(self) -> int:
        return self["rows"]

    @property
    def output_files(self) -> int:
        return self["output_files"]

    @property
    def output_csv_bytes(self) -> int:
        return self["output_csv_bytes"]

    @property
    def input_header(self) -> list[str] | None:
        return self["input_header"]


class ManifestOutput(_Report):
    """Metadata for one output file or ZIP member."""

    __slots__ = ()

    @property
    def path(self) -> str:
        """Relative output filename or exact ZIP member name."""
        return self["path"]

    @property
    def rows(self) -> int:
        return self["rows"]

    @property
    def csv_bytes(self) -> int:
        return self["csv_bytes"]

    @property
    def stored_bytes(self) -> int:
        return self["stored_bytes"]

    @property
    def compressed_target_exceeded(self) -> bool:
        return self["compressed_target_exceeded"]

    @property
    def lineage(self) -> list[dict[str, Any]]:
        return self["lineage"]


class Progress(_Report):
    """The most recent execution phase and its row and temporary-byte counts."""

    __slots__ = ()

    @property
    def phase(self) -> str:
        return self["phase"]

    @property
    def rows(self) -> int:
        return self["rows"]

    @property
    def temp_bytes(self) -> int:
        return self["temp_bytes"]


class ManifestReader(Iterator[ManifestOutput]):
    """Stream output metadata from a published manifest."""

    __slots__ = ("_inner",)

    def __init__(self, inner: _NativeManifestReader) -> None:
        self._inner = inner

    @property
    def header(self) -> ManifestHeader:
        return ManifestHeader(self._inner.header)

    def __next__(self) -> ManifestOutput:
        return ManifestOutput(next(self._inner))

    def close(self) -> None:
        """Close the file early. The header remains available."""
        self._inner.close()

    def __enter__(self) -> ManifestReader:
        return self

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()


def open_manifest(
    path: str | PathLike[str], *, max_record_bytes: int = _DEFAULT_MANIFEST_RECORD_BYTES,
) -> ManifestReader:
    """Open a manifest with a byte limit on each JSON Lines record."""
    return ManifestReader(_open_manifest(path, max_record_bytes=max_record_bytes))
