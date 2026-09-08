"""Canonical JSON serialization for frozen graph declarations."""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import MappingProxyType

from .canonical import canonical_json
from .decl import (
    ArtifactInput,
    ArtifactOutput,
    ArtifactType,
    Graph,
    Node,
    Owned,
    Ownership,
    Param,
    Product,
    ProductKind,
    Slice,
    SourceRef,
    StructuralDelta,
    WeightTransition,
)

__all__ = [
    "GRAPH_DOCUMENT_SERIALIZATION_VERSION",
    "graph_document_from_json",
    "graph_document_to_json",
    "graph_from_json",
    "graph_to_json",
]

GRAPH_DOCUMENT_SERIALIZATION_VERSION = 1


def graph_to_json(graph: Graph) -> str:
    """Serialize ``graph`` losslessly as canonical declaration JSON."""

    if not isinstance(graph, Graph):
        raise TypeError(f"graph_to_json expects Graph, got {type(graph).__name__}")
    payload = {
        "country": graph.country,
        "sources": [
            {
                "name": source.name,
                "codec": source.codec,
                "description": source.description,
            }
            for source in graph.sources
        ],
        "nodes": [_node_payload(node) for node in graph.nodes],
        # Amendment 12: present only when declared, so a declaration written
        # before the amendment serializes byte for byte as it did.
        **(
            {}
            if graph.mass_partition is None
            else {"mass_partition": list(graph.mass_partition)}
        ),
        **(
            {}
            if not graph.products
            else {"products": [_product_payload(product) for product in graph.products]}
        ),
    }
    return canonical_json(payload).decode("utf-8")


def graph_from_json(text: str) -> Graph:
    """Restore a :class:`Graph` from :func:`graph_to_json` output."""

    if not isinstance(text, str):
        raise TypeError(f"graph_from_json expects str, got {type(text).__name__}")
    try:
        raw = json.loads(text, parse_constant=_reject_json_constant)
    except json.JSONDecodeError as error:
        raise ValueError("graph JSON is not valid JSON") from error
    root = _mapping(raw, "graph")
    fields = {"country", "sources", "nodes"}
    if "mass_partition" in root:
        fields.add("mass_partition")
    if "products" in root:
        fields.add("products")
    _exact_fields(root, fields, "graph")
    sources_raw = _array(root["sources"], "graph.sources")
    nodes_raw = _array(root["nodes"], "graph.nodes")
    return Graph(
        country=_string(root["country"], "graph.country"),
        sources=tuple(
            _source_from_payload(value, index)
            for index, value in enumerate(sources_raw)
        ),
        nodes=tuple(
            _node_from_payload(value, index) for index, value in enumerate(nodes_raw)
        ),
        mass_partition=_partition_from_payload(
            root.get("mass_partition"), "graph.mass_partition"
        ),
        products=tuple(
            _product_from_payload(value, index)
            for index, value in enumerate(
                _array(root.get("products", []), "graph.products")
            )
        ),
    )


def graph_document_to_json(graph: Graph) -> str:
    """Return a versioned generated document without changing legacy bytes."""

    payload = {
        "derived": True,
        "document_type": "microcosm.graph",
        "graph": json.loads(graph_to_json(graph)),
        "serialization_version": GRAPH_DOCUMENT_SERIALIZATION_VERSION,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def graph_document_from_json(text: str) -> Graph:
    """Read the closed envelope emitted by :func:`graph_document_to_json`."""

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field {key!r}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            text, object_pairs_hook=unique, parse_constant=_reject_json_constant
        )
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid generated Graph JSON: {error.msg}.") from error
    mapping = _mapping(payload, "generated graph document")
    _exact_fields(
        mapping,
        {"derived", "document_type", "graph", "serialization_version"},
        "generated graph document",
    )
    if mapping["serialization_version"] != GRAPH_DOCUMENT_SERIALIZATION_VERSION:
        raise ValueError(
            "Unsupported generated Graph JSON serialization version "
            f"{mapping['serialization_version']!r}."
        )
    if mapping["derived"] is not True or mapping["document_type"] != "microcosm.graph":
        raise ValueError(
            "Generated Graph JSON is not a derived microcosm.graph document."
        )
    return graph_from_json(
        json.dumps(
            mapping["graph"], sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    )


def _partition_from_payload(value: object, label: str) -> tuple[str, str] | None:
    if value is None:
        return None
    parts = _array(value, label)
    if len(parts) != 2:
        raise TypeError(f"{label} must be an [entity, column] pair")
    return (_string(parts[0], f"{label}[0]"), _string(parts[1], f"{label}[1]"))


def _node_payload(node: Node) -> dict[str, object]:
    return {
        **(
            {
                "artifact_inputs": [
                    {
                        "name": item.name,
                        "producer": item.producer,
                        "artifact": item.artifact,
                        "type": {
                            "name": item.type.name,
                            "schema_version": item.type.schema_version,
                        },
                    }
                    for item in node.artifact_inputs
                ]
            }
            if node.artifact_inputs
            else {}
        ),
        **(
            {
                "artifact_outputs": [
                    {
                        "name": item.name,
                        "type": {
                            "name": item.type.name,
                            "schema_version": item.type.schema_version,
                        },
                    }
                    for item in node.artifact_outputs
                ]
            }
            if node.artifact_outputs
            else {}
        ),
        "id": node.id,
        "kernel": node.kernel,
        "inputs": [
            {
                "entity": slice_.entity,
                "columns": list(slice_.columns),
                "rows": slice_.rows,
            }
            for slice_ in node.inputs
        ],
        "outputs": [
            {
                "entity": owned.entity,
                "column": owned.column,
                "dtype": owned.dtype,
                "rows": owned.rows,
                "ownership": owned.ownership.value,
                **({"rewrite": True} if owned.rewrite else {}),
            }
            for owned in node.outputs
        ],
        "params": dict(node.params),
        "population": node.population,
        "structural": node.structural.value,
        "base": node.base,
        **({"bases": list(node.bases)} if node.bases else {}),
        "sources": list(node.sources),
        "weights": (
            None
            if node.weights is None
            else {
                "entity": node.weights.entity,
                "to_kind": node.weights.to_kind,
                "mass": node.weights.mass,
                **(
                    {"anchor": node.weights.anchor}
                    if node.weights.anchor is not None
                    else {}
                ),
            }
        ),
        "mass": node.mass,
        **({"entrants": True} if node.entrants else {}),
        "description": node.description,
        "citation": node.citation,
    }


def _source_from_payload(value: object, index: int) -> SourceRef:
    label = f"graph.sources[{index}]"
    payload = _mapping(value, label)
    _exact_fields(payload, {"name", "codec", "description"}, label)
    return SourceRef(
        name=_string(payload["name"], f"{label}.name"),
        codec=_string(payload["codec"], f"{label}.codec"),
        description=_string(payload["description"], f"{label}.description"),
    )


def _node_from_payload(value: object, index: int) -> Node:
    label = f"graph.nodes[{index}]"
    payload = _mapping(value, label)
    fields = {
        "id",
        "kernel",
        "inputs",
        "outputs",
        "params",
        "population",
        "structural",
        "base",
        "sources",
        "weights",
        "mass",
        "description",
        "citation",
    }
    fields.update(
        name for name in ("artifact_inputs", "artifact_outputs") if name in payload
    )
    if "entrants" in payload:
        fields.add("entrants")
    if "bases" in payload:
        fields.add("bases")
    _exact_fields(payload, fields, label)
    entrants = payload.get("entrants", False)
    if not isinstance(entrants, bool):
        raise TypeError(f"{label}.entrants must be a boolean")
    inputs = _array(payload["inputs"], f"{label}.inputs")
    outputs = _array(payload["outputs"], f"{label}.outputs")
    sources = _array(payload["sources"], f"{label}.sources")
    params = _mapping(payload["params"], f"{label}.params")
    population = _optional_string(payload["population"], f"{label}.population")
    base = _optional_string(payload["base"], f"{label}.base")
    bases = _array(payload.get("bases", []), f"{label}.bases")
    return Node(
        artifact_inputs=tuple(
            _artifact_from_payload(value, input_=True)
            for value in _array(
                payload.get("artifact_inputs", []), f"{label}.artifact_inputs"
            )
        ),
        artifact_outputs=tuple(
            _artifact_from_payload(value, input_=False)
            for value in _array(
                payload.get("artifact_outputs", []), f"{label}.artifact_outputs"
            )
        ),
        id=_string(payload["id"], f"{label}.id"),
        kernel=_string(payload["kernel"], f"{label}.kernel"),
        inputs=tuple(
            _slice_from_payload(child, f"{label}.inputs[{child_index}]")
            for child_index, child in enumerate(inputs)
        ),
        outputs=tuple(
            _owned_from_payload(child, f"{label}.outputs[{child_index}]")
            for child_index, child in enumerate(outputs)
        ),
        params={
            _string(name, f"{label}.params key"): _param_from_json(
                child, f"{label}.params[{name!r}]"
            )
            for name, child in params.items()
        },
        population=population,
        structural=StructuralDelta(
            _string(payload["structural"], f"{label}.structural")
        ),
        base=base,
        bases=tuple(
            _string(name, f"{label}.bases[{base_index}]")
            for base_index, name in enumerate(bases)
        ),
        sources=tuple(
            _string(name, f"{label}.sources[{source_index}]")
            for source_index, name in enumerate(sources)
        ),
        weights=_weights_from_payload(payload["weights"], f"{label}.weights"),
        mass=_string(payload["mass"], f"{label}.mass"),
        entrants=entrants,
        description=_string(payload["description"], f"{label}.description"),
        citation=_string(payload["citation"], f"{label}.citation"),
    )


def _slice_from_payload(value: object, label: str) -> Slice:
    payload = _mapping(value, label)
    _exact_fields(payload, {"entity", "columns", "rows"}, label)
    columns = _array(payload["columns"], f"{label}.columns")
    return Slice(
        entity=_string(payload["entity"], f"{label}.entity"),
        columns=tuple(
            _string(column, f"{label}.columns[{index}]")
            for index, column in enumerate(columns)
        ),
        rows=_string(payload["rows"], f"{label}.rows"),
    )


def _owned_from_payload(value: object, label: str) -> Owned:
    payload = _mapping(value, label)
    fields = {"entity", "column", "dtype", "rows", "ownership"}
    if "rewrite" in payload:
        fields.add("rewrite")
    _exact_fields(payload, fields, label)
    rewrite = payload.get("rewrite", False)
    if not isinstance(rewrite, bool):
        raise TypeError(f"{label}.rewrite must be a boolean")
    return Owned(
        entity=_string(payload["entity"], f"{label}.entity"),
        column=_string(payload["column"], f"{label}.column"),
        dtype=_string(payload["dtype"], f"{label}.dtype"),
        rows=_string(payload["rows"], f"{label}.rows"),
        ownership=Ownership(_string(payload["ownership"], f"{label}.ownership")),
        rewrite=rewrite,
    )


def _weights_from_payload(value: object, label: str) -> WeightTransition | None:
    if value is None:
        return None
    payload = _mapping(value, label)
    fields = {"entity", "to_kind", "mass"}
    if "anchor" in payload:
        fields.add("anchor")
    _exact_fields(payload, fields, label)
    return WeightTransition(
        entity=_string(payload["entity"], f"{label}.entity"),
        to_kind=_string(payload["to_kind"], f"{label}.to_kind"),
        mass=_string(payload["mass"], f"{label}.mass"),
        anchor=_optional_string(payload.get("anchor"), f"{label}.anchor"),
    )


def _param_from_json(value: object, label: str) -> Param:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, list):
        return tuple(
            _param_from_json(child, f"{label}[{index}]")
            for index, child in enumerate(value)
        )
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _string(key, f"{label} key"): _param_from_json(
                    child, f"{label}[{key!r}]"
                )
                for key, child in value.items()
            }
        )
    raise TypeError(f"{label} is not a legal graph parameter")


def _product_payload(product: Product) -> dict[str, object]:
    return {
        "name": product.name,
        "kind": product.kind.value,
        **({"node": product.node} if product.node is not None else {}),
        **({"entity": product.entity} if product.entity is not None else {}),
        **({"column": product.column} if product.column is not None else {}),
        **({"artifact": product.artifact} if product.artifact is not None else {}),
        **({"source": product.source} if product.source is not None else {}),
        **({"codec": product.codec} if product.codec is not None else {}),
        **(
            {"codec_version": product.codec_version}
            if product.codec_version is not None
            else {}
        ),
    }


def _product_from_payload(value: object, index: int) -> Product:
    label = f"graph.products[{index}]"
    payload = _mapping(value, label)
    fields = {"name", "kind"} | (
        set(payload)
        & {
            "node",
            "entity",
            "column",
            "artifact",
            "source",
            "codec",
            "codec_version",
        }
    )
    _exact_fields(payload, fields, label)
    version = payload.get("codec_version")
    if version is not None and (type(version) is not int or version < 1):
        raise TypeError(f"{label}.codec_version must be a positive integer")
    return Product(
        name=_string(payload["name"], f"{label}.name"),
        kind=ProductKind(_string(payload["kind"], f"{label}.kind")),
        node=_optional_string(payload.get("node"), f"{label}.node"),
        entity=_optional_string(payload.get("entity"), f"{label}.entity"),
        column=_optional_string(payload.get("column"), f"{label}.column"),
        artifact=_optional_string(payload.get("artifact"), f"{label}.artifact"),
        source=_optional_string(payload.get("source"), f"{label}.source"),
        codec=_optional_string(payload.get("codec"), f"{label}.codec"),
        codec_version=version,
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(name, str) for name in value
    ):
        raise TypeError(f"{label} must be a JSON object with string keys")
    return value


def _array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be a JSON array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _exact_fields(
    payload: Mapping[str, object], expected: set[str], label: str
) -> None:
    if set(payload) != expected:
        raise ValueError(
            f"{label} fields are {sorted(payload)!r}, expected {sorted(expected)!r}"
        )


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"graph JSON contains non-finite constant {value}")


def _artifact_from_payload(
    value: object, *, input_: bool
) -> ArtifactInput | ArtifactOutput:
    raw = _mapping(value, "artifact declaration")
    fields = {"name", "type"} | ({"producer", "artifact"} if input_ else set())
    _exact_fields(raw, fields, "artifact declaration")
    type_raw = _mapping(raw["type"], "artifact type")
    _exact_fields(type_raw, {"name", "schema_version"}, "artifact type")
    type_ = ArtifactType(
        _string(type_raw["name"], "artifact type.name"), type_raw["schema_version"]
    )
    name = _string(raw["name"], "artifact name")
    if input_:
        return ArtifactInput(
            name,
            _string(raw["producer"], "artifact producer"),
            _string(raw["artifact"], "artifact output"),
            type_,
        )
    return ArtifactOutput(name, type_)
