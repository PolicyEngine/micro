"""Parse the deterministic JSON-compatible YAML 1.2 subset."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from types import MappingProxyType

import yaml
from yaml.composer import ComposerError
from yaml.error import Mark, YAMLError
from yaml.loader import SafeLoader
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import DirectiveToken, TagToken

from .source_errors import GraphSourceParseError

type JSONScalar = None | bool | int | float | str
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]

_BOOL_TAG = "tag:yaml.org,2002:bool"
_FLOAT_TAG = "tag:yaml.org,2002:float"
_INT_TAG = "tag:yaml.org,2002:int"
_MERGE_TAG = "tag:yaml.org,2002:merge"
_NULL_TAG = "tag:yaml.org,2002:null"
_STR_TAG = "tag:yaml.org,2002:str"
_TIMESTAMP_TAG = "tag:yaml.org,2002:timestamp"
_JSON_SCALAR_TAGS = frozenset({_BOOL_TAG, _FLOAT_TAG, _INT_TAG, _NULL_TAG, _STR_TAG})


@dataclass(frozen=True)
class SourceLocation:
    source: str
    line: int
    column: int


@dataclass(frozen=True)
class ParsedYAML:
    value: JSONValue
    locations: Mapping[str, SourceLocation]


class _StrictYAML12Loader(SafeLoader):
    """SafeLoader with YAML 1.2 core boolean and numeric resolution."""


_StrictYAML12Loader.yaml_implicit_resolvers = {
    first: list(resolvers)
    for first, resolvers in SafeLoader.yaml_implicit_resolvers.items()
}
for _first, _resolvers in tuple(_StrictYAML12Loader.yaml_implicit_resolvers.items()):
    _StrictYAML12Loader.yaml_implicit_resolvers[_first] = [
        (tag, regexp)
        for tag, regexp in _resolvers
        if tag not in {_BOOL_TAG, _FLOAT_TAG, _INT_TAG}
    ]
_StrictYAML12Loader.add_implicit_resolver(
    _BOOL_TAG,
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)
_StrictYAML12Loader.add_implicit_resolver(
    _INT_TAG,
    re.compile(
        r"^(?:[-+]?0b[0-1_]+|[-+]?0o[0-7_]+|"
        r"[-+]?0x[0-9a-fA-F_]+|[-+]?[0-9][0-9_]*)$"
    ),
    list("-+0123456789"),
)
_StrictYAML12Loader.add_implicit_resolver(
    _FLOAT_TAG,
    re.compile(
        r"^(?:[-+]?(?:[0-9][0-9_]*\.[0-9_]*|\.[0-9_]+)"
        r"(?:[eE][-+]?[0-9]+)?|[-+]?[0-9][0-9_]*(?:[eE][-+]?[0-9]+)|"
        r"[-+]?\.(?:inf|Inf|INF)|[-+]?\.(?:nan|NaN|NAN))$"
    ),
    list("-+0123456789."),
)


def _construct_yaml12_int(loader: SafeLoader, node: ScalarNode) -> int:
    value = loader.construct_scalar(node).replace("_", "")
    sign = -1 if value.startswith("-") else 1
    unsigned = value[1:] if value[:1] in {"+", "-"} else value
    for prefix, base in (("0b", 2), ("0o", 8), ("0x", 16)):
        if unsigned.startswith(prefix):
            return sign * int(unsigned[2:], base)
    return sign * int(unsigned, 10)


_StrictYAML12Loader.add_constructor(_INT_TAG, _construct_yaml12_int)


def _error(
    message: str, *, source: str, mark: Mark | None = None, pointer: str | None = None
) -> GraphSourceParseError:
    return GraphSourceParseError(
        message,
        source=source,
        pointer=pointer,
        line=None if mark is None else mark.line + 1,
        column=None if mark is None else mark.column + 1,
    )


def _marked_yaml_error(exc: YAMLError, *, source: str) -> GraphSourceParseError:
    mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
    if isinstance(exc, ComposerError) and "single document" in str(exc):
        message = "multiple YAML documents are not allowed"
    else:
        problem = getattr(exc, "problem", None)
        message = f"invalid YAML: {problem}" if problem else "invalid YAML"
    return _error(message, source=source, mark=mark)


def _tokens(text: str, *, source: str) -> Iterator[object]:
    try:
        yield from yaml.scan(text, Loader=_StrictYAML12Loader)
    except YAMLError as exc:
        raise _marked_yaml_error(exc, source=source) from exc


def _reject_syntax_extensions(text: str, *, source: str) -> None:
    for token in _tokens(text, source=source):
        if isinstance(token, TagToken):
            raise _error(
                "explicit YAML tags are not allowed",
                source=source,
                mark=token.start_mark,
            )
        if isinstance(token, DirectiveToken):
            if token.name == "TAG":
                raise _error(
                    "YAML tag directives are not allowed",
                    source=source,
                    mark=token.start_mark,
                )
            if token.name == "YAML" and token.value != (1, 2):
                raise _error(
                    "only the YAML 1.2 directive is allowed",
                    source=source,
                    mark=token.start_mark,
                )
            if token.name not in {"TAG", "YAML"}:
                raise _error(
                    "YAML directives other than %YAML 1.2 are not allowed",
                    source=source,
                    mark=token.start_mark,
                )


def _pointer(parent: str, token: object) -> str:
    escaped = str(token).replace("~", "~0").replace("/", "~1")
    return f"{parent}/{escaped}" if parent else f"/{escaped}"


def _validate_node(
    node: Node,
    *,
    source: str,
    active: set[int],
    validated: set[int],
) -> None:
    identity = id(node)
    if identity in active:
        raise _error(
            "cyclic YAML aliases are not allowed", source=source, mark=node.start_mark
        )
    if identity in validated:
        return
    active.add(identity)
    try:
        if isinstance(node, ScalarNode):
            if node.tag == _TIMESTAMP_TAG:
                raise _error(
                    "timestamps and dates are not allowed",
                    source=source,
                    mark=node.start_mark,
                )
            if node.tag not in _JSON_SCALAR_TAGS:
                raise _error(
                    "only JSON-compatible scalar values are allowed",
                    source=source,
                    mark=node.start_mark,
                )
            if node.tag == _FLOAT_TAG:
                normalized = node.value.replace("_", "").lower()
                try:
                    finite = normalized.lstrip("+-") not in {
                        ".inf",
                        ".nan",
                    } and math.isfinite(float(normalized))
                except ValueError:
                    raise _error(
                        "invalid YAML 1.2 number", source=source, mark=node.start_mark
                    ) from None
                if not finite:
                    raise _error(
                        "non-finite numbers are not allowed",
                        source=source,
                        mark=node.start_mark,
                    )
            if node.tag == _INT_TAG:
                normalized = node.value.replace("_", "").lstrip("+-")
                if normalized.startswith(("0b", "0o", "0x")):
                    normalized = normalized[2:]
                if not normalized:
                    raise _error(
                        "invalid YAML 1.2 number",
                        source=source,
                        mark=node.start_mark,
                    )
            return
        if isinstance(node, SequenceNode):
            for item in node.value:
                _validate_node(item, source=source, active=active, validated=validated)
            return
        if isinstance(node, MappingNode):
            keys: set[str] = set()
            for key_node, value_node in node.value:
                if key_node.tag == _MERGE_TAG:
                    raise _error(
                        "YAML merge keys are not allowed",
                        source=source,
                        mark=key_node.start_mark,
                    )
                if not isinstance(key_node, ScalarNode) or key_node.tag != _STR_TAG:
                    raise _error(
                        "mapping keys must be strings",
                        source=source,
                        mark=key_node.start_mark,
                    )
                if key_node.value in keys:
                    raise _error(
                        f"duplicate mapping key {key_node.value!r}",
                        source=source,
                        mark=key_node.start_mark,
                    )
                keys.add(key_node.value)
                _validate_node(
                    value_node, source=source, active=active, validated=validated
                )
            return
        raise _error(
            "only JSON-compatible YAML nodes are allowed",
            source=source,
            mark=node.start_mark,
        )
    finally:
        active.remove(identity)
        validated.add(identity)


def _source_map(
    node: Node, *, source: str, pointer: str, result: dict[str, SourceLocation]
) -> None:
    result.setdefault(
        pointer or "/",
        SourceLocation(source, node.start_mark.line + 1, node.start_mark.column + 1),
    )
    if isinstance(node, SequenceNode):
        for index, child in enumerate(node.value):
            _source_map(
                child, source=source, pointer=_pointer(pointer, index), result=result
            )
    elif isinstance(node, MappingNode):
        for key, child in node.value:
            child_pointer = _pointer(pointer, key.value)
            result[child_pointer] = SourceLocation(
                source, key.start_mark.line + 1, key.start_mark.column + 1
            )
            _source_map(child, source=source, pointer=child_pointer, result=result)


def _ensure_json_value(value: object, *, source: str) -> JSONValue:
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _error("non-finite numbers are not allowed", source=source)
        return value
    if isinstance(value, list):
        return [_ensure_json_value(item, source=source) for item in value]
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise _error("mapping keys must be strings", source=source)
        return {
            key: _ensure_json_value(item, source=source) for key, item in value.items()
        }
    raise _error("only JSON-compatible values are allowed", source=source)


def parse_yaml12(text: str, *, source: str = "<string>") -> ParsedYAML:
    """Load one YAML document and retain stable locations for its values."""
    if not isinstance(text, str):
        raise TypeError("YAML input must be text")
    _reject_syntax_extensions(text, source=source)
    loader = _StrictYAML12Loader(text)
    try:
        node = loader.get_single_node()
        if node is None:
            return ParsedYAML(None, MappingProxyType({}))
        _validate_node(node, source=source, active=set(), validated=set())
        locations: dict[str, SourceLocation] = {}
        _source_map(node, source=source, pointer="", result=locations)
        value = _ensure_json_value(loader.construct_document(node), source=source)
        return ParsedYAML(value, MappingProxyType(locations))
    except GraphSourceParseError:
        raise
    except YAMLError as exc:
        raise _marked_yaml_error(exc, source=source) from exc
    finally:
        loader.dispose()


def load_yaml12(text: str, *, source: str = "<string>") -> JSONValue:
    return parse_yaml12(text, source=source).value


def load_yaml12_file(path: str | PathLike[str]) -> JSONValue:
    resource = Path(path)
    return load_yaml12(resource.read_text(encoding="utf-8"), source=str(resource))


def load_json_strict(text: str, *, source: str = "<string>") -> JSONValue:
    if not isinstance(text, str):
        raise TypeError("JSON input must be text")

    def refuse_duplicates(pairs: list[tuple[str, JSONValue]]) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {}
        for key, value in pairs:
            if key in result:
                raise _error(f"duplicate mapping key {key!r}", source=source)
            result[key] = value
        return result

    def refuse_constant(_constant: str) -> JSONValue:
        raise _error("non-finite numbers are not allowed", source=source)

    try:
        return json.loads(
            text, object_pairs_hook=refuse_duplicates, parse_constant=refuse_constant
        )
    except GraphSourceParseError:
        raise
    except json.JSONDecodeError as exc:
        raise GraphSourceParseError(
            f"invalid JSON: {exc.msg}",
            source=source,
            line=exc.lineno,
            column=exc.colno,
        ) from exc


__all__ = [
    "JSONScalar",
    "JSONValue",
    "ParsedYAML",
    "SourceLocation",
    "load_json_strict",
    "load_yaml12",
    "load_yaml12_file",
    "parse_yaml12",
]
