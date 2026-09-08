"""Stable errors raised while loading an authored graph source."""

from __future__ import annotations


class GraphSourceError(ValueError):
    """Base error with an editor-ready source location and JSON Pointer."""

    def __init__(
        self,
        message: str,
        *,
        source: str | None = None,
        pointer: str | None = None,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.message = message
        self.source = source
        self.pointer = pointer
        self.line = line
        self.column = column
        location = source
        if location is not None and line is not None:
            location += f":{line}"
            if column is not None:
                location += f":{column}"
        if pointer:
            location = f"{location or ''} {pointer}".strip()
        super().__init__(f"{location}: {message}" if location else message)


class GraphSourceParseError(GraphSourceError):
    """Authored input is outside the accepted YAML/JSON subset."""


class GraphSourceSchemaError(GraphSourceError):
    """The packaged graph-source schema catalog is invalid."""


class GraphSourceValidationError(GraphSourceError):
    """A parsed graph source does not satisfy its closed schema."""


class GraphSourceCompositionError(GraphSourceError):
    """Declared graph modules cannot be composed safely."""


class GraphParameterBindingError(GraphSourceError):
    """Run parameter declarations and supplied bindings disagree."""


__all__ = [
    "GraphParameterBindingError",
    "GraphSourceCompositionError",
    "GraphSourceError",
    "GraphSourceParseError",
    "GraphSourceSchemaError",
    "GraphSourceValidationError",
]
