"""Load versioned graph YAML and compose it into one declaration."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType

from .artifact_edges import numeric_scope, require_compatible_scope
from .decl import (
    ArtifactInput,
    ArtifactOutput,
    ArtifactType,
    CompiledGraph,
    Graph,
    GraphError,
    Node,
    Owned,
    Ownership,
    Param,
    Slice,
    SourceRef,
    StructuralDelta,
    WeightTransition,
    compile_graph,
)
from .graph_schema import validate_graph_document
from .kernel import KernelRegistry
from .source_errors import (
    GraphParameterBindingError,
    GraphSourceCompositionError,
    GraphSourceValidationError,
)
from .yaml12 import ParsedYAML, parse_yaml12

GRAPH_SOURCE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GraphSourceReceipt:
    """Identity of one authored YAML document used in composition."""

    path: str
    sha256: str


@dataclass(frozen=True)
class LoadedGraphSource:
    """A Graph plus authored-input evidence retained for run manifests."""

    graph: Graph
    schema_version: int
    parameters: Mapping[str, Param]
    receipts: tuple[GraphSourceReceipt, ...]
    products: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True)
class _Document:
    path: Path
    relative: str
    raw: bytes
    parsed: ParsedYAML


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GraphSourceValidationError(f"{label} must be a mapping")
    return value


def _safe_module_path(root: Path, raw: object, *, source: Path) -> Path:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise GraphSourceCompositionError(
            f"module path must be a non-empty relative POSIX path: {raw!r}",
            source=str(source),
        )
    relative = PurePosixPath(raw)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise GraphSourceCompositionError(
            f"unsafe module path {raw!r}", source=str(source)
        )
    candidate = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise GraphSourceCompositionError(
                f"module path may not contain a symbolic link: {raw!r}",
                source=str(source),
            )
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise GraphSourceCompositionError(
            f"module path escapes graph root: {raw!r}", source=str(source)
        ) from error
    if not candidate.is_file():
        raise GraphSourceCompositionError(
            f"declared module does not exist: {raw!r}", source=str(source)
        )
    return candidate


def _read_document(path: Path, root: Path, *, module: bool) -> _Document:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise GraphSourceValidationError(
            "graph YAML must be UTF-8", source=str(path)
        ) from error
    parsed = parse_yaml12(text, source=str(path))
    value = _mapping(parsed.value, "graph document")
    version = value.get("schema_version")
    if version != GRAPH_SOURCE_SCHEMA_VERSION:
        raise GraphSourceValidationError(
            f"unsupported graph schema version {version!r}",
            source=str(path),
            pointer="/schema_version",
        )
    validate_graph_document(parsed, module=module)
    return _Document(path, path.relative_to(root).as_posix(), raw, parsed)


def _freeze_json(value: object) -> Param:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GraphSourceValidationError("parameters must be finite")
        return value
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    raise GraphSourceValidationError(
        f"node parameter has unsupported type {type(value).__name__}"
    )


def _parameter_value(
    name: str, declaration: Mapping[str, object], supplied: object
) -> Param:
    kind = declaration["type"]
    valid = {
        "boolean": lambda value: isinstance(value, bool),
        "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
        "number": lambda value: (
            isinstance(value, int | float) and not isinstance(value, bool)
        ),
        "string": lambda value: isinstance(value, str),
    }[kind]
    if not valid(supplied):
        raise GraphParameterBindingError(
            f"parameter {name!r} requires type {kind}, got {type(supplied).__name__}"
        )
    if isinstance(supplied, float) and not math.isfinite(supplied):
        raise GraphParameterBindingError(f"parameter {name!r} must be finite")
    if "allowed" in declaration and supplied not in declaration["allowed"]:
        raise GraphParameterBindingError(
            f"parameter {name!r} is not one of its allowed values"
        )
    if "minimum" in declaration and supplied < declaration["minimum"]:  # type: ignore[operator]
        raise GraphParameterBindingError(f"parameter {name!r} is below its minimum")
    if "maximum" in declaration and supplied > declaration["maximum"]:  # type: ignore[operator]
        raise GraphParameterBindingError(f"parameter {name!r} is above its maximum")
    return _freeze_json(supplied)


def _bind_parameters(
    declarations: Mapping[str, Mapping[str, object]], supplied: Mapping[str, object]
) -> Mapping[str, Param]:
    unknown = sorted(set(supplied) - set(declarations))
    if unknown:
        raise GraphParameterBindingError(
            f"undeclared run parameter override(s): {', '.join(unknown)}"
        )
    result: dict[str, Param] = {}
    for name in sorted(declarations):
        declaration = declarations[name]
        required = declaration["required"]
        has_default = "default" in declaration
        if required and has_default:
            raise GraphParameterBindingError(
                f"required parameter {name!r} may not declare a default"
            )
        if not required and not has_default:
            raise GraphParameterBindingError(
                f"optional parameter {name!r} must declare a default"
            )
        if name in supplied:
            raw = supplied[name]
        elif has_default:
            raw = declaration["default"]
        else:
            raise GraphParameterBindingError(
                f"required run parameter {name!r} was not supplied"
            )
        result[name] = _parameter_value(name, declaration, raw)
    return MappingProxyType(result)


def _artifact_type(value: object) -> ArtifactType:
    item = _mapping(value, "artifact type")
    return ArtifactType(str(item["name"]), int(item["schema_version"]))


def _lower_node(raw: Mapping[str, object], bindings: Mapping[str, Param]) -> Node:
    params = {
        str(name): _freeze_json(value)
        for name, value in _mapping(raw.get("params", {}), "node params").items()
    }
    for local, global_name in _mapping(
        raw.get("param_bindings", {}), "parameter bindings"
    ).items():
        if local in params:
            raise GraphParameterBindingError(
                f"node {raw['id']!r} parameter {local!r} is both literal and bound"
            )
        if global_name not in bindings:
            raise GraphParameterBindingError(
                f"node {raw['id']!r} binds undefined parameter {global_name!r}"
            )
        params[str(local)] = bindings[str(global_name)]
    inputs = tuple(
        Slice(
            str(item["entity"]),
            tuple(str(value) for value in item["columns"]),
            str(item.get("rows", "all")),
        )
        for item in (_mapping(value, "slice") for value in raw.get("inputs", []))
    )
    outputs = tuple(
        Owned(
            str(item["entity"]),
            str(item["column"]),
            str(item["dtype"]),
            str(item.get("rows", "all")),
            Ownership(str(item.get("ownership", "produced"))),
            bool(item.get("rewrite", False)),
        )
        for item in (
            _mapping(value, "owned coordinate") for value in raw.get("outputs", [])
        )
    )
    weight_raw = raw.get("weights")
    weights = None
    if weight_raw is not None:
        item = _mapping(weight_raw, "weight transition")
        weights = WeightTransition(
            str(item["entity"]), str(item["to_kind"]), str(item.get("mass", "conserve"))
        )
    artifact_inputs = tuple(
        ArtifactInput(
            str(item["name"]),
            str(item["producer"]),
            str(item["artifact"]),
            _artifact_type(item["type"]),
        )
        for item in (
            _mapping(value, "artifact input")
            for value in raw.get("artifact_inputs", [])
        )
    )
    artifact_outputs = tuple(
        ArtifactOutput(str(item["name"]), _artifact_type(item["type"]))
        for item in (
            _mapping(value, "artifact output")
            for value in raw.get("artifact_outputs", [])
        )
    )
    return Node(
        id=str(raw["id"]),
        kernel=str(raw["kernel"]),
        inputs=inputs,
        outputs=outputs,
        params=params,
        population=None if "population" not in raw else str(raw["population"]),
        structural=StructuralDelta(str(raw.get("structural", "none"))),
        base=None if "base" not in raw else str(raw["base"]),
        sources=tuple(str(value) for value in raw.get("sources", [])),
        weights=weights,
        mass=str(raw.get("mass", "conserve")),
        description=str(raw.get("description", "")),
        citation=str(raw.get("citation", "")),
        entrants=bool(raw.get("entrants", False)),
        artifact_inputs=artifact_inputs,
        artifact_outputs=artifact_outputs,
    )


def _freeze_product(value: Mapping[str, object]) -> Mapping[str, object]:
    def freeze(item: object) -> object:
        if isinstance(item, Mapping):
            return MappingProxyType(
                {str(key): freeze(child) for key, child in item.items()}
            )
        if isinstance(item, list):
            return tuple(freeze(child) for child in item)
        return item

    frozen = freeze(value)
    assert isinstance(frozen, Mapping)
    return frozen


def load_graph_source(
    path: str | Path, *, parameters: Mapping[str, object] | None = None
) -> LoadedGraphSource:
    """Load a root and its exact modules without executing runtime code."""
    root_path = Path(path)
    if root_path.is_symlink():
        raise GraphSourceCompositionError(
            "root graph path may not be a symbolic link", source=str(root_path)
        )
    root_path = root_path.resolve()
    root_dir = root_path.parent
    documents: list[_Document] = []
    active: list[Path] = []
    seen: set[Path] = set()

    def visit(candidate: Path, *, is_module: bool) -> None:
        if candidate in active:
            chain = " -> ".join(
                item.relative_to(root_dir).as_posix() for item in (*active, candidate)
            )
            raise GraphSourceCompositionError(
                f"module cycle: {chain}", source=str(candidate)
            )
        if candidate in seen:
            raise GraphSourceCompositionError(
                f"module is declared more than once: {candidate.relative_to(root_dir).as_posix()}",
                source=str(candidate),
            )
        active.append(candidate)
        document = _read_document(candidate, root_dir, module=is_module)
        payload = _mapping(document.parsed.value, "graph document")
        for module_path in sorted(payload.get("modules", [])):
            visit(
                _safe_module_path(root_dir, module_path, source=candidate),
                is_module=True,
            )
        active.pop()
        seen.add(candidate)
        documents.append(document)

    visit(root_path, is_module=False)
    root = _mapping(
        next(item.parsed.value for item in documents if item.path == root_path), "root"
    )
    collected: dict[str, list[tuple[Path, object]]] = {
        "sources": [],
        "nodes": [],
        "parameters": [],
        "products": [],
    }
    for document in documents:
        payload = _mapping(document.parsed.value, "graph document")
        for name in collected:
            raw = payload.get(name, {} if name == "parameters" else [])
            entries = (
                raw.items()
                if name == "parameters"
                else (
                    (
                        str(
                            _mapping(item, name[:-1])[
                                "name" if name != "nodes" else "id"
                            ]
                        ),
                        item,
                    )
                    for item in raw
                )
            )
            for key, value in entries:
                collected[name].append((document.path, (str(key), value)))

    unique: dict[str, dict[str, object]] = {name: {} for name in collected}
    origins: dict[str, dict[str, Path]] = {name: {} for name in collected}
    for category, entries in collected.items():
        for source, pair in entries:
            key, value = pair
            if key in unique[category]:
                raise GraphSourceCompositionError(
                    f"duplicate {category[:-1]} {key!r}; first declared in {origins[category][key]}",
                    source=str(source),
                )
            unique[category][key] = value
            origins[category][key] = source

    parameter_declarations = {
        name: _mapping(value, f"parameter {name}")
        for name, value in unique["parameters"].items()
    }
    bound = _bind_parameters(parameter_declarations, parameters or {})
    sources = tuple(
        SourceRef(
            str(item["name"]),
            str(item["codec"]),
            str(item.get("description", "")),
        )
        for item in (
            _mapping(unique["sources"][name], "source")
            for name in sorted(unique["sources"])
        )
    )
    nodes = tuple(
        _lower_node(_mapping(unique["nodes"][name], "node"), bound)
        for name in sorted(unique["nodes"])
    )
    mass_partition = root.get("mass_partition")
    try:
        graph = Graph(
            str(root["country"]),
            sources,
            nodes,
            None
            if mass_partition is None
            else tuple(str(value) for value in mass_partition),  # type: ignore[arg-type]
        )
    except (GraphError, TypeError, ValueError) as error:
        raise GraphSourceValidationError(
            f"graph declaration is invalid: {error}", source=str(root_path)
        ) from error
    products = tuple(
        _freeze_product(_mapping(unique["products"][name], "product"))
        for name in sorted(unique["products"])
    )
    receipts = tuple(
        GraphSourceReceipt(
            document.relative,
            hashlib.sha256(document.raw).hexdigest(),
        )
        for document in sorted(documents, key=lambda item: item.relative)
    )
    return LoadedGraphSource(
        graph,
        GRAPH_SOURCE_SCHEMA_VERSION,
        bound,
        receipts,
        products,
    )


def graph_from_yaml_file(
    path: str | Path, *, parameters: Mapping[str, object] | None = None
) -> Graph:
    return load_graph_source(path, parameters=parameters).graph


def compiled_graph_from_yaml_file(
    path: str | Path,
    *,
    kernels: KernelRegistry,
    parameters: Mapping[str, object] | None = None,
) -> CompiledGraph:
    compiled = compile_graph(graph_from_yaml_file(path, parameters=parameters))
    validate_kernel_registry(compiled, kernels)
    return compiled


def validate_kernel_registry(compiled: CompiledGraph, kernels: KernelRegistry) -> None:
    """Verify executable contracts for every node before a run starts."""

    for node_id in compiled.order:
        node = compiled.graph.node(node_id)
        try:
            kernel = kernels.get(node.kernel)
        except KeyError as error:
            raise GraphSourceValidationError(
                f"node {node.id!r} references unregistered kernel {node.kernel!r}"
            ) from error
        if kernel.capabilities.structural is not node.structural:
            raise GraphSourceValidationError(
                f"node {node.id!r} declares structural operation "
                f"{node.structural.value!r}, but {node.kernel!r} declares "
                f"{kernel.capabilities.structural.value!r}"
            )
        for binding in node.artifact_inputs:
            producer = compiled.graph.node(binding.producer)
            producer_scope = numeric_scope(kernels.get(producer.kernel).capabilities)
            try:
                require_compatible_scope(producer_scope, kernel.capabilities)
            except ValueError as error:
                raise GraphSourceValidationError(
                    f"node {node.id!r} cannot consume typed artifact "
                    f"{binding.name!r}: {error}"
                ) from error


__all__ = [
    "GRAPH_SOURCE_SCHEMA_VERSION",
    "GraphSourceReceipt",
    "LoadedGraphSource",
    "compiled_graph_from_yaml_file",
    "graph_from_yaml_file",
    "load_graph_source",
    "validate_kernel_registry",
]
