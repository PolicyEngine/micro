"""Closed JSON Schema catalog for authored graph YAML."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource

from .source_errors import GraphSourceSchemaError, GraphSourceValidationError
from .yaml12 import ParsedYAML, SourceLocation

_SCHEMAS = ("graph-source-v1.schema.json", "graph-module-v1.schema.json")
_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def _refuse_retrieval(uri: str) -> Resource[Any]:
    raise NoSuchResource(ref=uri)


def _pointer(parts: object) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else "/"


def _location(parsed: ParsedYAML, pointer: str) -> SourceLocation | None:
    candidate = pointer
    while candidate not in parsed.locations and candidate not in {"", "/"}:
        candidate = candidate.rsplit("/", 1)[0] or "/"
    return parsed.locations.get(candidate) or parsed.locations.get("/")


@lru_cache(maxsize=1)
def schema_catalog() -> tuple[Mapping[str, Mapping[str, Any]], Registry[Any]]:
    root = resources.files("microcosm.graph").joinpath("schema")
    found = tuple(
        sorted(item.name for item in root.iterdir() if item.name.endswith(".json"))
    )
    if found != tuple(sorted(_SCHEMAS)):
        raise GraphSourceSchemaError(
            f"graph schema catalog must contain exactly {sorted(_SCHEMAS)!r}; "
            f"found {list(found)!r}"
        )
    schemas: dict[str, Mapping[str, Any]] = {}
    registry: Registry[Any] = Registry(retrieve=_refuse_retrieval)
    for filename in _SCHEMAS:
        try:
            value = json.loads(root.joinpath(filename).read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(value)
        except Exception as error:
            raise GraphSourceSchemaError(
                f"{filename}: invalid packaged Draft 2020-12 schema: {error}"
            ) from error
        if value.get("$schema") != _DRAFT or value.get("$id") != filename:
            raise GraphSourceSchemaError(
                f"{filename}: $schema and $id must identify the packaged schema"
            )
        schemas[filename] = value
        registry = registry.with_resource(filename, Resource.from_contents(value))
    return MappingProxyType(schemas), registry


def validate_graph_document(parsed: ParsedYAML, *, module: bool) -> None:
    """Validate one parsed document and report its first stable error."""
    schemas, registry = schema_catalog()
    schema_id = (
        "graph-module-v1.schema.json" if module else "graph-source-v1.schema.json"
    )
    validator = Draft202012Validator(schemas[schema_id], registry=registry)
    errors = sorted(
        validator.iter_errors(parsed.value),
        key=lambda error: (
            _pointer(error.absolute_path),
            _pointer(error.absolute_schema_path),
            error.message,
        ),
    )
    if not errors:
        return
    error = errors[0]
    pointer = _pointer(error.absolute_path)
    if error.validator == "additionalProperties":
        match = re.search(r"\('([^']+)' was unexpected\)", error.message)
        if match:
            pointer = (
                pointer.rstrip("/")
                + "/"
                + match.group(1).replace("~", "~0").replace("/", "~1")
            )
    location = _location(parsed, pointer)
    raise GraphSourceValidationError(
        error.message,
        source=None if location is None else location.source,
        pointer=pointer,
        line=None if location is None else location.line,
        column=None if location is None else location.column,
    )


__all__ = ["schema_catalog", "validate_graph_document"]
