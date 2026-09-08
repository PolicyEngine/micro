"""Compatibility wrappers for the graph package's strict YAML parser."""

from __future__ import annotations

from os import PathLike
from pathlib import Path

from microcosm.graph.source_errors import GraphSourceParseError
from microcosm.graph.yaml12 import (
    JSONScalar,
    JSONValue,
)
from microcosm.graph.yaml12 import (
    load_json_strict as _load_json_strict,
)
from microcosm.graph.yaml12 import (
    load_yaml12 as _load_yaml12,
)

from .errors import SpecParseError


def _compat(error: GraphSourceParseError) -> SpecParseError:
    return SpecParseError(
        error.message,
        source=error.source,
        line=error.line,
        column=error.column,
    )


def load_yaml12(text: str, *, source: str = "<string>") -> JSONValue:
    try:
        return _load_yaml12(text, source=source)
    except GraphSourceParseError as error:
        raise _compat(error) from error


def load_yaml12_file(path: str | PathLike[str]) -> JSONValue:
    resource = Path(path)
    return load_yaml12(resource.read_text(encoding="utf-8"), source=str(resource))


def load_json_strict(text: str, *, source: str = "<string>") -> JSONValue:
    try:
        return _load_json_strict(text, source=source)
    except GraphSourceParseError as error:
        raise _compat(error) from error


__all__ = [
    "JSONScalar",
    "JSONValue",
    "load_json_strict",
    "load_yaml12",
    "load_yaml12_file",
]
