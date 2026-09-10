"""Bounded, value-only inspection of a compiled graph and its visible fields.

This is declaration metadata, not execution evidence or source authority. A
population's schema includes its ordinary derived fields as well as its carried
fields; it is not a snapshot of a Frame halfway through execution.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import fields
from types import MappingProxyType

from .decl import (
    ROWS_ALL,
    ArtifactInput,
    ArtifactOutput,
    ArtifactType,
    CompiledGraph,
    Graph,
    GraphError,
    Node,
    Owned,
    Ownership,
    Slice,
    SourceRef,
    StructuralDelta,
    WeightTransition,
    compile_graph,
)
from .serialize import graph_from_json, graph_to_json

__all__ = ["graph_schema"]

PROTOCOL = "microcosm.graph.schema.v1"
# Inspector development limits; none describe microdata size or release scope.
MAX_NODES = 256
MAX_SOURCES = 256
MAX_DEPTH = 64
MAX_DECLARED_FIELDS = 20_000
MAX_ROWS = 100_000
MAX_DECLARATION_BYTES = 8 * 1024 * 1024
MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_ITEMS = 200_000
MAX_STRING_CHARS = 16_384
_DECLARATIONS = frozenset(
    {
        Graph,
        Node,
        SourceRef,
        Slice,
        Owned,
        WeightTransition,
        ArtifactInput,
        ArtifactOutput,
        ArtifactType,
    }
)


def _require(condition: bool, detail: str) -> None:
    if not condition:
        raise GraphError(f"Graph schema: {detail}.")


def _preflight(value: object) -> None:
    """Bound existing declaration objects before serializer/decoder allocation.

    The conservative byte charge allows six JSON bytes per string character.
    This bounds metadata construction, not total Python process memory.
    """
    remaining, items = MAX_DECLARATION_BYTES, 0

    def walk(child: object, depth: int) -> None:
        nonlocal remaining, items
        items += 1
        _require(items <= MAX_ITEMS and depth <= MAX_DEPTH, "declaration complexity")
        kind = type(child)
        cost = 16
        if kind is str:
            _require(len(child) <= MAX_STRING_CHARS, "string length")
            cost = 6 * len(child) + 2
        elif child is None or kind is bool:
            pass
        elif kind is int:
            _require(child.bit_length() <= 1024, "integer size")
            cost = child.bit_length() + 2
        elif kind is float:
            _require(math.isfinite(child), "finite number required")
            cost = 32
        elif kind in {Ownership, StructuralDelta}:
            walk(child.value, depth + 1)
        elif kind in _DECLARATIONS:
            for field in fields(child):
                walk(field.name, depth + 1)
                walk(getattr(child, field.name), depth + 1)
        elif kind in {tuple, list}:
            _require(len(child) <= MAX_ITEMS - items, "container size")
            for part in child:
                walk(part, depth + 1)
        elif kind in {dict, MappingProxyType}:
            _require(len(child) <= (MAX_ITEMS - items) // 2, "mapping size")
            for key, part in child.items():
                walk(key, depth + 1)
                walk(part, depth + 1)
        else:
            raise GraphError(f"Graph schema: unsupported declaration {kind.__name__}.")
        remaining -= cost
        _require(remaining >= 0, "prospective declaration size")

    walk(value, 0)


def _structure(compiled: CompiledGraph) -> dict[str, object]:
    return {
        "order": list(compiled.order),
        "versions": dict(sorted(compiled.versions.items())),
        "predecessors": {
            key: list(value) for key, value in sorted(compiled.predecessors.items())
        },
        "owners": [
            list(key) + [owner] for key, owner in sorted(compiled.owners.items())
        ],
    }


def graph_schema(compiled: CompiledGraph) -> dict[str, object]:
    """Export the actual declaration, checked compilation and visible fields.

    ``producer`` is the local declared owner, otherwise the structural carrier
    of the requested population. ``declared_in`` traces the nearest actual
    Owned declaration; its rows/ownership/rewrite describe that declaration,
    not a claim about the current row membership or scientific availability.

    ``input_bindings`` covers explicit slices, named slice/output masks and
    implicit rewrite incumbents. It does not enumerate runtime-injected IDs,
    memberships, resolved weights/strata or parameter-driven EXPAND cells.
    Typed artifact dependencies remain in graph and compiled predecessors.
    """
    _require(type(compiled) is CompiledGraph, "actual CompiledGraph required")
    _require(type(compiled.graph) is Graph, "actual Graph required")
    graph = compiled.graph
    _require(len(graph.nodes) <= MAX_NODES, "node limit")
    _require(len(graph.sources) <= MAX_SOURCES, "source limit")
    _require(
        sum(len(node.outputs) for node in graph.nodes) <= MAX_DECLARED_FIELDS,
        "declared field limit",
    )
    _preflight(graph)
    _preflight(
        (compiled.order, compiled.versions, compiled.predecessors, compiled.owners)
    )
    raw = graph_to_json(graph).encode("utf-8")
    _require(len(raw) <= MAX_DECLARATION_BYTES, "declaration size")
    # Reuse the real declaration parser/compiler. A caller-constructed or stale
    # CompiledGraph must not supply fictitious owners or edges to the inspector.
    detached = graph_from_json(raw.decode("utf-8"))
    try:
        checked = compile_graph(detached)
    except RecursionError:
        raise GraphError("Graph schema: compilation depth.") from None
    structure = _structure(checked)
    _require(_structure(compiled) == structure, "compiled structure mismatch")
    by_id = {node.id: node for node in detached.nodes}
    declarations = {
        (node.id, output.entity, output.column): output
        for node in detached.nodes
        for output in node.outputs
    }
    depth: dict[str, int] = {}
    for node_id in checked.order:
        depth[node_id] = 1 + max(
            (depth[parent] for parent in checked.predecessors[node_id]), default=0
        )
        _require(depth[node_id] <= MAX_DEPTH, "graph depth")

    # Each map holds the nearest actual declaration, including derived fields
    # anywhere in that version. Structural descendants carry the completed map.
    visible: dict[str, dict[tuple[str, str], tuple[str, Owned]]] = {}
    rows: list[dict[str, object]] = []
    bindings: list[dict[str, object]] = []
    used = len(raw)
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )

    def append(target: list[dict[str, object]], row: dict[str, object]) -> None:
        nonlocal used
        _require(len(rows) + len(bindings) < MAX_ROWS, "expanded row limit")
        size = sum(len(part.encode("utf-8")) for part in encoder.iterencode(row))
        _require(size <= MAX_EXPORT_BYTES - used, "prospective export size")
        used += size
        target.append(row)

    for version in checked.order:
        holder = by_id[version]
        if holder.structural is StructuralDelta.NONE:
            continue
        current = {} if holder.base is None else dict(visible[holder.base])
        local = {
            (entity, column): owner
            for (population, entity, column), owner in checked.owners.items()
            if population == version
        }
        # Count before copying an expanded version into exported row objects.
        _require(
            len(rows) + len(current.keys() | local.keys()) <= MAX_ROWS,
            "expanded schema limit",
        )
        for coordinate, owner in local.items():
            declaration = declarations[owner, *coordinate]
            current[coordinate] = (owner, declaration)
        visible[version] = current
        for (entity, column), (declared_in, declaration) in sorted(current.items()):
            append(
                rows,
                {
                    "population": version,
                    "entity": entity,
                    "column": column,
                    "dtype": declaration.dtype,
                    "producer": local.get((entity, column), version),
                    "declared_in": declared_in,
                    "rows": declaration.rows,
                    "ownership": declaration.ownership.value,
                    "rewrite": declaration.rewrite,
                },
            )

    def binding(
        node: Node, version: str, entity: str, column: str, row_mask: str, kind: str
    ) -> None:
        coordinate = (entity, column)
        owner = checked.owners.get((version, entity, column))
        declaration_version = version
        if owner == node.id:
            # Rewrites receive the current structural carrier's incumbent,
            # potentially materialized by EXPAND, not the output being written.
            declaration_version = by_id[version].base
            _require(declaration_version is not None, "rewrite base required")
            owner = None
        _require(coordinate in visible[declaration_version], "input field missing")
        declared_in, _declaration = visible[declaration_version][coordinate]
        append(
            bindings,
            {
                "node": node.id,
                "population": version,
                "entity": entity,
                "column": column,
                "rows": row_mask,
                "producer": version if owner is None else owner,
                "declared_in": declared_in,
                "kind": kind,
            },
        )

    for node_id in checked.order:
        node = by_id[node_id]
        if node.structural is StructuralDelta.CREATE:
            continue
        version = (
            checked.versions[node_id]
            if node.structural is StructuralDelta.NONE
            else node.base
        )
        for slice_ in node.inputs:
            for column in slice_.columns:
                binding(node, version, slice_.entity, column, slice_.rows, "slice")
            if slice_.rows != ROWS_ALL:
                binding(
                    node, version, slice_.entity, slice_.rows, ROWS_ALL, "slice_mask"
                )
        for output in node.outputs:
            if output.rewrite:
                binding(
                    node,
                    version,
                    output.entity,
                    output.column,
                    output.rows,
                    "rewrite_incumbent",
                )
            if output.rows != ROWS_ALL:
                binding(
                    node, version, output.entity, output.rows, ROWS_ALL, "output_mask"
                )
    bindings.sort(
        key=lambda row: tuple(
            str(row[key]) for key in ("node", "kind", "entity", "column", "rows")
        )
    )
    result = {
        "protocol": PROTOCOL,
        "country": detached.country,
        "graph_sha256": hashlib.sha256(raw).hexdigest(),
        "graph": json.loads(raw),
        "compiled": structure,
        "schema": rows,
        "input_bindings": bindings,
    }
    # Stream the final size accounting; do not build another unbounded JSON
    # string. All variable-sized graph/row construction was bounded above.
    total = 0
    for part in encoder.iterencode(result):
        total += len(part.encode("utf-8"))
        _require(total <= MAX_EXPORT_BYTES, "export size")
    _preflight(compiled.graph)
    _require(
        graph_to_json(compiled.graph).encode("utf-8") == raw
        and _structure(compiled) == structure,
        "input changed during export",
    )
    return result
