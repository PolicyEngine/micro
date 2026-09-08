"""Graph execution: immutable projection, validation, patching, and reuse."""

from __future__ import annotations

import hashlib
import json
import socket
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd

from microcosm.frame import Frame, WeightKind, Weights

from . import keys as graph_keys
from .artifact_edges import scope_payload, typed_contracts, value_from_descriptor
from .canonical import canonical_json, sha256_domain
from .codecs import SOURCE_CODECS, BoundSource, SourceCodecRegistry
from .decl import (
    GATE_OUTCOMES,
    ROWS_ALL,
    CompiledGraph,
    Node,
    Owned,
    Ownership,
    ProductKind,
    StructuralDelta,
)
from .errors import NodeRejectedError
from .graph_source import validate_kernel_registry
from .kernel import (
    ArtifactValue,
    Capabilities,
    KernelContext,
    KernelRegistry,
    KernelResult,
    KernelRole,
    Numeric,
    NumericScope,
    Tolerance,
    source_hash,
)
from .keys import (
    _capabilities_projection,
    artifact_key,
    frame_key,
    graph_key,
    node_key,
    seed,
    source_binding_key,
    source_content_identity,
    source_content_key,
    union_lineage_key,
    validation_outcome_key,
    weights_key,
)
from .manifest import Decision, NodeReceipt, RunManifest
from .population import (
    Population,
    _expand_cells,
    entrant_strata_receipt,
    expand_lineage_receipt,
    expand_writes_receipt,
    mass_record_receipt,
    patch,
    restore_cached_expand,
    union_populations,
    weight_cap_receipt,
)
from .serialize import graph_document_from_json
from .store import (
    ContentStore,
    ResumePolicy,
    StoreCorrupt,
    StoreMiss,
    StoreUnavailable,
)

__all__ = ["NodeRejected", "NodeRejectedError", "run_graph"]

# Compatibility spelling from the initial interface.  Every rejection is an
# instance of the amended shared runtime exception.
NodeRejected = NodeRejectedError

_CERTIFYING_GATE_OUTCOMES = frozenset({"pass", "not_applicable"})
_EXPAND_WRITE_CLASSES = ("entrant", "copied-rewrite", "new-column")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _cache_record_key(key: str) -> str:
    return sha256_domain("node-receipt", canonical_json((key,)))


def _opaque_artifact_key(key: str, name: str) -> str:
    return sha256_domain("node-artifact", canonical_json((key, name)))


def _normal_json_mapping(value: Mapping[str, object], label: str) -> dict[str, object]:
    """Validate and detach a descriptive mapping through canonical JSON."""

    try:
        restored = json.loads(canonical_json(value))
    except (TypeError, ValueError) as error:
        raise NodeRejected(
            f"{label} must contain canonical JSON values: {error}"
        ) from error
    if not isinstance(restored, dict):  # pragma: no cover - Mapping encodes as object
        raise NodeRejected(f"{label} must encode as an object.")
    return restored


def _failed_gate_result(
    node: Node,
    population: Population | None,
    error: Exception,
) -> KernelResult:
    """Turn a gate evaluation exception into an owned, evidenced failure."""

    if node.structural is not StructuralDelta.NONE or population is None:
        raise NodeRejected(
            f"Gate node {node.id!r} cannot recover an exception without an "
            "ordinary population-bound verdict column."
        ) from error
    columns: dict[tuple[str, str], pd.Series] = {}
    for owned in node.outputs:
        if owned.dtype != "string":
            raise NodeRejected(
                f"Gate node {node.id!r} output {owned.entity}.{owned.column} "
                "must declare dtype 'string' to record a failed verdict."
            ) from error
        ids = _owned_ids(population.frame, owned, node_id=node.id)
        columns[(owned.entity, owned.column)] = pd.Series(
            "fail",
            index=ids,
            name=owned.column,
            dtype="string",
        )
    return KernelResult(
        columns=MappingProxyType(columns),
        receipt={
            "outcome": "fail",
            "evidence": {
                "exception_type": type(error).__name__,
                "message": str(error),
            },
        },
    )


def _transitive_ancestors(compiled: CompiledGraph, node_id: str) -> tuple[str, ...]:
    """Return every predecessor of ``node_id`` in canonical node order."""

    pending = list(compiled.predecessors[node_id])
    ancestors: set[str] = set()
    while pending:
        predecessor = pending.pop()
        if predecessor in ancestors:
            continue
        ancestors.add(predecessor)
        pending.extend(compiled.predecessors[predecessor])
    return tuple(candidate for candidate in compiled.order if candidate in ancestors)


def _release_tier(
    compiled: CompiledGraph,
    node_id: str,
    receipts: Mapping[str, NodeReceipt],
) -> tuple[str, tuple[str, ...]]:
    """Derive a release tier solely from gate receipts in its ancestry."""

    gate_ids = tuple(
        ancestor
        for ancestor in _transitive_ancestors(compiled, node_id)
        if receipts[ancestor].capabilities.role is KernelRole.GATE
    )
    certified = all(
        receipts[gate_id].receipt.get("outcome") in _CERTIFYING_GATE_OUTCOMES
        for gate_id in gate_ids
    )
    return ("certified" if certified else "evidence"), gate_ids


def _validate_release_tier(node: Node, result: KernelResult, derived: str) -> None:
    """Require a release kernel's owned tier answer to equal the derivation."""

    tier_outputs = [owned for owned in node.outputs if owned.column == "tier"]
    if len(tier_outputs) != 1 or tier_outputs[0].dtype != "string":
        raise NodeRejected(
            f"Release node {node.id!r} must own exactly one string tier column."
        )
    owned = tier_outputs[0]
    series = result.columns[(owned.entity, owned.column)]
    answers = set(series.dropna().astype(str))
    if series.isna().any() or answers != {derived}:
        raise NodeRejected(
            f"Release node {node.id!r} returned tier {sorted(answers)!r}, "
            f"but gate ancestry derives {derived!r}."
        )


def _decision_names(decisions: tuple[Decision, ...]) -> frozenset[str]:
    names: set[str] = set()
    for decision in decisions:
        payload = dict(decision)
        names.add(payload.get("name", decision.kind))
    return frozenset(names)


def _required_decision_names(node: Node) -> tuple[str, ...]:
    """Validate and return a release node's normative decision requirements."""

    required = node.params.get("requires_decisions", ())
    if not isinstance(required, tuple) or any(
        not isinstance(name, str) or not name for name in required
    ):
        raise NodeRejected(
            f"Release node {node.id!r} params['requires_decisions'] must be a "
            "tuple of non-empty decision names."
        )
    if len(set(required)) != len(required):
        raise NodeRejected(
            f"Release node {node.id!r} repeats a required decision name."
        )
    return required


def _release_outcome(node: Node, tier: str, decisions: tuple[Decision, ...]) -> str:
    required = _required_decision_names(node)
    if not set(required) <= _decision_names(decisions):
        return "unreached"
    return "pass" if tier == "certified" else "fail"


def _dtype_matches(series: pd.Series, token: str) -> bool:
    dtype = series.dtype
    if token == "boolean":
        return isinstance(dtype, pd.BooleanDtype)
    if token == "Int64":
        return isinstance(dtype, pd.Int64Dtype)
    if token == "string":
        return isinstance(dtype, pd.StringDtype)
    expected = {
        "bool": np.dtype(np.bool_),
        "int32": np.dtype(np.int32),
        "int64": np.dtype(np.int64),
        "float32": np.dtype(np.float32),
        "float64": np.dtype(np.float64),
    }[token]
    return dtype == expected


def _dtype_token(series: pd.Series) -> str:
    dtype = series.dtype
    if isinstance(dtype, pd.BooleanDtype):
        return "boolean"
    if isinstance(dtype, pd.Int64Dtype):
        return "Int64"
    if isinstance(dtype, pd.StringDtype):
        return "string"
    numpy_dtype = np.dtype(dtype)
    by_dtype = {
        np.dtype(np.bool_): "bool",
        np.dtype(np.int32): "int32",
        np.dtype(np.int64): "int64",
        np.dtype(np.float32): "float32",
        np.dtype(np.float64): "float64",
    }
    try:
        return by_dtype[numpy_dtype]
    except KeyError as error:
        raise NodeRejected(
            f"Frame column has unsupported dtype {dtype!s}; graph columns use "
            "the frozen DTYPES tokens."
        ) from error


def _mask_values(table: pd.DataFrame, column: str, *, node_id: str) -> np.ndarray:
    series = table[column]
    if not (
        pd.api.types.is_bool_dtype(series.dtype)
        or isinstance(series.dtype, pd.BooleanDtype)
    ):
        raise NodeRejected(
            f"Node {node_id!r} row mask {column!r} has dtype {series.dtype!s}, "
            "not bool/boolean."
        )
    if series.isna().any():
        raise NodeRejected(f"Node {node_id!r} row mask {column!r} contains nulls.")
    return series.to_numpy(dtype=np.bool_, copy=True)


def _owned_ids(frame: Frame, owned: Owned, *, node_id: str) -> pd.Index:
    table = frame.table(owned.entity)
    id_column = frame.schema.entity_id_column(owned.entity)
    if owned.rows == ROWS_ALL:
        selected = table
    else:
        selected = table.loc[_mask_values(table, owned.rows, node_id=node_id)]
    return pd.Index(selected[id_column].to_numpy(copy=True), name=id_column)


def _set_read_only(array: object) -> None:
    if isinstance(array, np.ndarray):
        try:
            array.setflags(write=False)
        except ValueError:
            pass


def _freeze_series(series: pd.Series) -> None:
    """Make every discoverable backing buffer read-only in place."""

    extension = series.array
    for attribute in ("_data", "_mask", "_ndarray"):
        _set_read_only(getattr(extension, attribute, None))
    try:
        _set_read_only(series.to_numpy(copy=False))
    except (TypeError, ValueError):
        pass


def _freeze_frame(table: pd.DataFrame) -> pd.DataFrame:
    frozen = table.copy(deep=True)
    for column in frozen.columns:
        _freeze_series(frozen[column])
    _set_read_only(frozen.index.to_numpy(copy=False))
    return frozen


def _update_scalar(digest: hashlib._Hash, value: object) -> None:
    if value is pd.NA:
        payload = b"pd.NA"
    elif value is pd.NaT:
        payload = b"pd.NaT"
    elif value is None:
        payload = b"None"
    elif isinstance(value, (float, np.floating)):
        payload = b"f" + np.asarray([value], dtype=np.float64).tobytes()
    elif isinstance(value, (bool, np.bool_)):
        payload = b"b1" if bool(value) else b"b0"
    elif isinstance(value, (int, np.integer)):
        payload = b"i" + str(int(value)).encode("ascii")
    elif isinstance(value, str):
        payload = b"s" + value.encode("utf-8")
    elif isinstance(value, (bytes, np.bytes_)):
        payload = b"y" + bytes(value)
    else:
        payload = b"r" + repr(value).encode("utf-8")
    digest.update(len(payload).to_bytes(8, "little"))
    digest.update(payload)


def _update_array(digest: hashlib._Hash, values: object) -> None:
    array = np.asarray(values)
    digest.update(str(array.dtype).encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(array.shape).encode("ascii"))
    digest.update(b"\0")
    if array.dtype.hasobject:
        for value in array.ravel(order="C"):
            _update_scalar(digest, value)
    else:
        digest.update(np.ascontiguousarray(array).tobytes())


def _update_series(digest: hashlib._Hash, series: pd.Series) -> None:
    digest.update(str(series.dtype).encode("utf-8"))
    digest.update(b"\0")
    extension = series.array
    data = getattr(extension, "_data", None)
    mask = getattr(extension, "_mask", None)
    if isinstance(data, np.ndarray) and isinstance(mask, np.ndarray):
        _update_array(digest, data)
        _update_array(digest, mask)
    else:
        _update_array(digest, series.to_numpy(dtype=object, copy=False))
    _update_array(digest, series.index.to_numpy(copy=False))


def _context_digest(context: KernelContext) -> bytes:
    digest = hashlib.sha256(b"microcosm-graph/kernel-context/1\0")
    for entity in sorted(context.tables):
        table = context.tables[entity]
        digest.update(entity.encode("utf-8") + b"\0")
        for column in table.columns:
            digest.update(str(column).encode("utf-8") + b"\0")
            _update_series(digest, table[column])
    for entity in sorted(context.weights):
        weights = context.weights[entity]
        digest.update(entity.encode("utf-8") + b"\0")
        digest.update(weights.kind.value.encode("ascii") + b"\0")
        _update_array(digest, weights.values)
    for name in sorted(context.weight_anchors):
        weights = context.weight_anchors[name]
        digest.update(name.encode("utf-8") + b"\0")
        digest.update(weights.kind.value.encode("ascii") + b"\0")
        _update_array(digest, weights.values)
    _update_series(digest, context.strata)
    for name, value in sorted(context.artifacts.items()):
        digest.update(
            canonical_json(
                (
                    name,
                    value.key,
                    value.producer_key,
                    value.type.name,
                    value.type.schema_version,
                    scope_payload(value.numerics),
                )
            )
        )
        digest.update(len(value.payload).to_bytes(8, "little"))
        digest.update(value.payload)
    return digest.digest()


def _structural_columns(frame: Frame, entity: str) -> list[str]:
    columns = [frame.schema.entity_id_column(entity)]
    if entity == frame.schema.person_entity:
        columns.extend(
            frame.schema.membership_column(group)
            for group in frame.schema.group_entities
        )
    return columns


def _materialized_expand_coordinates(node: Node) -> frozenset[tuple[str, str]]:
    """Return and validate the carried EXPAND cells an ordinary node claims."""

    raw_materialized = node.params.get("materialized_expand_outputs", ())
    if not isinstance(raw_materialized, tuple) or any(
        not isinstance(value, str) or "." not in value for value in raw_materialized
    ):
        raise NodeRejected(
            f"Node {node.id!r} params['materialized_expand_outputs'] must be a "
            "tuple of 'entity.column' strings."
        )
    materialized: set[tuple[str, str]] = set()
    owned_by_coordinate = {
        (output.entity, output.column): output for output in node.outputs
    }
    for value in raw_materialized:
        entity, column = value.split(".", 1)
        coordinate = (entity, column)
        output = owned_by_coordinate.get(coordinate)
        if output is None or output.rewrite:
            raise NodeRejected(
                f"Node {node.id!r} materialized EXPAND output {value!r} must be "
                "one of its non-rewrite owned cells."
            )
        materialized.add(coordinate)
    if len(materialized) != len(raw_materialized):
        raise NodeRejected(f"Node {node.id!r} repeats a materialized EXPAND output.")
    return frozenset(materialized)


def _expand_rewrite_coordinates(
    compiled: CompiledGraph, node: Node
) -> frozenset[tuple[str, str]]:
    """Return overlays an EXPAND's full-cell same-version claimant rewrites."""

    if node.structural is not StructuralDelta.EXPAND:
        return frozenset()
    overlay_coordinates = _expand_writer_coordinates(node)
    rewrites: set[tuple[str, str]] = set()
    for (version, entity, column), owner_id in compiled.owners.items():
        coordinate = (entity, column)
        if version != node.id or coordinate not in overlay_coordinates:
            continue
        owner = compiled.graph.node(owner_id)
        output = next(
            candidate
            for candidate in owner.outputs
            if (candidate.entity, candidate.column) == coordinate
        )
        if output.rewrite and output.rows == ROWS_ALL:
            rewrites.add(coordinate)
    return frozenset(rewrites)


def _project_context(
    node: Node,
    population: Population | None,
    *,
    key: str,
    sources: Mapping[str, BoundSource],
    tolerances: Mapping[tuple[str, str], Tolerance | None],
    numerics: Mapping[tuple[str, str], NumericScope],
    artifacts: Mapping[str, ArtifactValue] | None = None,
    weight_anchors: Mapping[str, Weights] | None = None,
) -> KernelContext:
    if population is None:
        return KernelContext(
            node=node,
            tables=MappingProxyType({}),
            weights=MappingProxyType({}),
            strata=pd.Series([], dtype=object, name="stratum"),
            params=node.params,
            rng=np.random.default_rng(seed(key)),
            sources=MappingProxyType({name: sources[name] for name in node.sources}),
            tolerances=tolerances,
            numerics=numerics,
            artifacts={} if artifacts is None else artifacts,
            weight_anchors={} if weight_anchors is None else weight_anchors,
        )

    frame = population.frame
    slices: dict[str, list[object]] = {}
    for slice_ in node.inputs:
        slices.setdefault(slice_.entity, []).append(slice_)

    materialized = _materialized_expand_coordinates(node)
    for entity, column in materialized:
        coordinate = (entity, column)
        if population.owners.get(coordinate) != population.version:
            raise NodeRejected(
                f"Node {node.id!r} materialized EXPAND output "
                f"{entity}.{column!s} was not "
                f"installed by population version {population.version!r}."
            )

    tables: dict[str, pd.DataFrame] = {}
    entity_masks: dict[str, np.ndarray] = {}
    projected_entities = set(slices)
    projected_entities.update(owned.entity for owned in node.outputs)
    for entity in sorted(projected_entities):
        table = frame.table(entity)
        entity_slices = slices.get(entity, [])
        row_specs = {slice_.rows for slice_ in entity_slices}
        if len(row_specs) > 1:
            raise NodeRejected(
                f"Node {node.id!r} declares incompatible row masks for entity "
                f"{entity!r}; KernelContext has one table per entity."
            )
        columns = _structural_columns(frame, entity)
        for slice_ in entity_slices:
            columns.extend(slice_.columns)
        for owned in node.outputs:
            if owned.entity != entity or not owned.rewrite:
                continue
            if owned.column not in table:
                raise NodeRejected(
                    f"Node {node.id!r} rewrite incumbent "
                    f"{owned.entity}.{owned.column} is absent."
                )
            columns.append(owned.column)
        for materialized_entity, materialized_column in sorted(materialized):
            if materialized_entity != entity:
                continue
            if materialized_column not in table:
                raise NodeRejected(
                    f"Node {node.id!r} materialized EXPAND output "
                    f"{materialized_entity}.{materialized_column} is absent."
                )
            columns.append(materialized_column)
        columns = list(dict.fromkeys(columns))
        if row_specs and next(iter(row_specs)) != ROWS_ALL:
            row_column = str(next(iter(row_specs)))
            mask = _mask_values(table, row_column, node_id=node.id)
        else:
            mask = np.ones(len(table), dtype=np.bool_)
        entity_masks[entity] = mask
        tables[entity] = _freeze_frame(table.loc[mask, columns])

    weights: dict[str, Weights] = {}
    for entity in sorted(projected_entities):
        try:
            effective = frame.resolve_weights(entity)
        except ValueError:
            if entity in frame.weighted_entities:
                raise
            # Some coarser groups contain members whose inherited person
            # weights differ, so Frame deliberately refuses to invent one
            # group weight.  The frozen context has no "needs weights" bit;
            # omit that ambiguous inherited entry while retaining its table.
            continue
        values = effective.values[entity_masks[entity]]
        weights[entity] = Weights(values=values, kind=effective.kind)

    person_mask = entity_masks.get(
        frame.schema.person_entity,
        np.ones(frame.n(frame.schema.person_entity), dtype=np.bool_),
    )
    strata = frame.strata.loc[person_mask].copy()
    _freeze_series(strata)
    return KernelContext(
        node=node,
        tables=MappingProxyType(tables),
        weights=MappingProxyType(weights),
        strata=strata,
        params=node.params,
        rng=np.random.default_rng(seed(key)),
        sources=MappingProxyType({name: sources[name] for name in node.sources}),
        tolerances=tolerances,
        numerics=numerics,
        artifacts={} if artifacts is None else artifacts,
        weight_anchors={} if weight_anchors is None else weight_anchors,
    )


_NUMERIC_RANK = {
    Numeric.BITWISE: 0,
    Numeric.PLATFORM_BITWISE: 1,
    Numeric.TOLERANCE_BOUND: 2,
}


def _input_numerics(
    compiled: CompiledGraph,
    node_id: str,
    kernels: KernelRegistry,
    *,
    writers: Mapping[tuple[str, str], tuple[str, ...]] | None = None,
) -> Mapping[tuple[str, str], NumericScope]:
    """Resolve each read coordinate to its loosest writer numeric scope."""

    writer_map = _input_writers(compiled, node_id) if writers is None else writers
    resolved: dict[tuple[str, str], NumericScope] = {}
    for coordinate, writer_ids in writer_map.items():
        capabilities = tuple(
            kernels.get(compiled.graph.node(writer_id).kernel).capabilities
            for writer_id in writer_ids
        )
        numeric = max(
            (capability.numeric for capability in capabilities),
            key=_NUMERIC_RANK.__getitem__,
            default=Numeric.BITWISE,
        )
        bounds = tuple(
            capability.tolerance
            for capability in capabilities
            if capability.numeric is Numeric.TOLERANCE_BOUND
        )
        tolerance = (
            None
            if not bounds
            else Tolerance(
                rtol=max(bound.rtol for bound in bounds if bound is not None),
                atol=max(bound.atol for bound in bounds if bound is not None),
                ulps=max(bound.ulps for bound in bounds if bound is not None),
            )
        )
        platform = (
            graph_keys.platform_fingerprint()
            if any(
                capability.numeric is Numeric.PLATFORM_BITWISE
                for capability in capabilities
            )
            else None
        )
        resolved[coordinate] = NumericScope(
            numeric=numeric,
            tolerance=tolerance,
            platform=platform,
        )
    return MappingProxyType(resolved)


def _input_tolerances(
    compiled: CompiledGraph,
    node_id: str,
    kernels: KernelRegistry,
    *,
    writers: Mapping[tuple[str, str], tuple[str, ...]] | None = None,
    numerics: Mapping[tuple[str, str], NumericScope] | None = None,
) -> Mapping[tuple[str, str], Tolerance | None]:
    """Project each input numeric scope to its legacy tolerance value."""

    scopes = (
        _input_numerics(compiled, node_id, kernels, writers=writers)
        if numerics is None
        else numerics
    )
    return MappingProxyType(
        {coordinate: scope.tolerance for coordinate, scope in scopes.items()}
    )


def _input_writers(
    compiled: CompiledGraph,
    node_id: str,
    *,
    receipts: Mapping[str, NodeReceipt] | None = None,
) -> Mapping[tuple[str, str], tuple[str, ...]]:
    """Return causal writer lists for explicit, rewrite, and claim reads."""

    node = compiled.graph.node(node_id)
    if node.structural in {StructuralDelta.CREATE, StructuralDelta.UNION}:
        return MappingProxyType({})
    input_version = (
        compiled.versions[node_id]
        if node.structural is StructuralDelta.NONE
        else node.base
    )
    assert input_version is not None
    coordinates = {
        (owned.entity, owned.column) for owned in node.outputs if owned.rewrite
    }
    coordinates.update(_materialized_expand_coordinates(node))
    coordinates.update(
        (slice_.entity, column) for slice_ in node.inputs for column in slice_.columns
    )
    writers: dict[tuple[str, str], tuple[str, ...]] = {}
    for coordinate in sorted(coordinates):
        entity, column = coordinate
        writers[coordinate] = _writers_of(
            compiled,
            input_version,
            entity,
            column,
            exclude_node=node.id,
            receipts=receipts,
        )
    return MappingProxyType(writers)


def _expand_writer_coordinates(node: Node) -> frozenset[tuple[str, str]]:
    """Coordinates an EXPAND declares it may materialize."""

    if node.structural is not StructuralDelta.EXPAND:
        return frozenset()
    return frozenset((entity, column) for entity, column, _dtype in _expand_cells(node))


def _expand_declared_payload(node: Node) -> list[str]:
    """Canonical receipt spellings of every declared EXPAND coordinate."""

    return [
        f"{entity}.{column}"
        for entity, column in sorted(_expand_writer_coordinates(node))
    ]


def _parse_expand_declared(node: Node, raw: object) -> frozenset[tuple[str, str]]:
    """Validate the executor-authored EXPAND declaration attestation."""

    expected = tuple(_expand_declared_payload(node))
    if not isinstance(raw, list | tuple) or tuple(raw) != expected:
        raise ValueError(
            f"EXPAND node {node.id!r} expand_declared must exactly equal its "
            f"canonical declaration {expected!r}."
        )
    return _expand_writer_coordinates(node)


def _parse_expand_writes(
    node: Node, raw: object
) -> Mapping[tuple[str, str], tuple[str, ...]]:
    """Validate an executor-authored EXPAND coordinate/row-class record."""

    if not isinstance(raw, Mapping):
        raise ValueError(f"EXPAND node {node.id!r} expand_writes must be a mapping.")
    declared = _expand_writer_coordinates(node)
    parsed: dict[tuple[str, str], tuple[str, ...]] = {}
    for spelling, raw_classes in raw.items():
        if not isinstance(spelling, str) or spelling.count(".") != 1:
            raise ValueError(
                f"EXPAND node {node.id!r} expand_writes coordinate {spelling!r} "
                "must be an 'entity.column' string."
            )
        entity, column = spelling.split(".")
        coordinate = (entity, column)
        if coordinate not in declared:
            raise ValueError(
                f"EXPAND node {node.id!r} expand_writes names undeclared "
                f"coordinate {spelling!r}."
            )
        if not isinstance(raw_classes, list | tuple) or not raw_classes:
            raise ValueError(
                f"EXPAND node {node.id!r} expand_writes {spelling!r} must name "
                "at least one row class."
            )
        classes = tuple(raw_classes)
        if any(not isinstance(value, str) for value in classes):
            raise ValueError(
                f"EXPAND node {node.id!r} expand_writes {spelling!r} row classes "
                "must be strings."
            )
        canonical = tuple(value for value in _EXPAND_WRITE_CLASSES if value in classes)
        if classes != canonical:
            raise ValueError(
                f"EXPAND node {node.id!r} expand_writes {spelling!r} row classes "
                f"must be unique and ordered as {_EXPAND_WRITE_CLASSES!r}."
            )
        parsed[coordinate] = classes
    return MappingProxyType(parsed)


def _validate_materialized_expand_outputs(
    compiled: CompiledGraph,
    node: Node,
    population: Population | None,
    receipts: Mapping[str, NodeReceipt],
) -> None:
    """Bind the no-Slice materialization bridge to its immediate EXPAND."""

    if "materialized_expand_outputs" not in node.params:
        return
    materialized = _materialized_expand_coordinates(node)
    if population is None:
        raise NodeRejected(
            f"Node {node.id!r} uses materialized_expand_outputs without an "
            "incumbent population; an immediate EXPAND population is required."
        )
    holder = compiled.graph.node(population.version)
    if holder.structural is not StructuralDelta.EXPAND:
        raise NodeRejected(
            f"Node {node.id!r} uses materialized_expand_outputs on population "
            f"version {population.version!r}, whose holder is {holder.structural.name}; "
            "an immediate EXPAND population is required."
        )
    holder_receipt = receipts.get(holder.id)
    if holder_receipt is None:  # compiled population ancestry should prevent this
        raise NodeRejected(
            f"Node {node.id!r} cannot validate materialized_expand_outputs: "
            f"EXPAND population version {holder.id!r} has no runtime receipt."
        )
    try:
        expand_declared = _parse_expand_declared(
            holder, holder_receipt.receipt.get("expand_declared")
        )
    except ValueError as error:  # executor-authored receipts cannot be malformed
        raise NodeRejected(
            f"Node {node.id!r} cannot validate materialized_expand_outputs for "
            f"EXPAND population version {holder.id!r}: {error}"
        ) from error
    for entity, column in sorted(materialized):
        if (entity, column) not in expand_declared:
            raise NodeRejected(
                f"Node {node.id!r} names materialized EXPAND output "
                f"{entity}.{column}, but EXPAND population version {holder.id!r} "
                "did not declare that coordinate."
            )


def _writers_of(
    compiled: CompiledGraph,
    version: str,
    entity: str,
    column: str,
    *,
    exclude_node: str | None = None,
    receipts: Mapping[str, NodeReceipt] | None = None,
) -> tuple[str, ...]:
    """All nodes that wrote rows of ``entity.column`` as seen from ``version``.

    The result is in causal order: the originating producer, EXPAND
    materializers, rewrites, and materialization claimants. Structural nodes
    that only carry the coordinate do not appear.
    """

    coordinate = (entity, column)
    newest_first: list[str] = []

    def add(writer_id: str) -> None:
        if writer_id != exclude_node and writer_id not in newest_first:
            newest_first.append(writer_id)

    while True:
        holder = compiled.graph.node(version)
        owner_id = compiled.owners.get((version, entity, column))
        if owner_id is not None:
            owner = compiled.graph.node(owner_id)
            output = next(
                owned
                for owned in owner.outputs
                if (owned.entity, owned.column) == coordinate
            )
            inherited = (
                output.rewrite
                or output.rows != ROWS_ALL
                or coordinate in _materialized_expand_coordinates(owner)
            )
            add(owner_id)
            if not inherited:
                break

        if _expand_wrote_rows(holder, coordinate, receipts):
            add(holder.id)
        if holder.structural is StructuralDelta.UNION:
            for base in holder.bases:
                for writer in reversed(
                    _writers_of(
                        compiled,
                        base,
                        entity,
                        column,
                        exclude_node=exclude_node,
                        receipts=receipts,
                    )
                ):
                    add(writer)
            break
        if holder.structural is StructuralDelta.CREATE or holder.base is None:
            break
        version = holder.base
    return tuple(reversed(newest_first))


def _expand_wrote_rows(
    node: Node,
    coordinate: tuple[str, str],
    receipts: Mapping[str, NodeReceipt] | None,
) -> bool:
    """Whether this EXPAND actually wrote any row of a coordinate."""

    if coordinate not in _expand_writer_coordinates(node):
        return False
    if receipts is None:
        # Static preflight has no runtime receipt with which to refine the
        # declaration. Exact writer ids are checked during execution.
        return True
    node_receipt = receipts.get(node.id)
    if node_receipt is None:
        return False
    try:
        writes = _parse_expand_writes(node, node_receipt.receipt.get("expand_writes"))
    except ValueError as error:  # executor-authored receipts cannot be malformed
        raise NodeRejected(str(error)) from error
    return coordinate in writes


def _validate_series(
    node: Node,
    owned: Owned,
    series: pd.Series,
    population: Population,
) -> None:
    if not isinstance(series, pd.Series):
        raise NodeRejected(
            f"Node {node.id!r} output {owned.entity}.{owned.column} is "
            f"{type(series).__name__}, not a pandas Series."
        )
    if series.index.has_duplicates:
        raise NodeRejected(
            f"Node {node.id!r} output {owned.entity}.{owned.column} repeats ids."
        )
    expected = _owned_ids(population.frame, owned, node_id=node.id)
    actual = pd.Index(series.index)
    if len(actual) != len(expected) or set(actual.tolist()) != set(expected.tolist()):
        missing = expected.difference(actual).tolist()[:5]
        extra = actual.difference(expected).tolist()[:5]
        raise NodeRejected(
            f"Node {node.id!r} output {owned.entity}.{owned.column} ids do not "
            f"equal its owned ids; missing={missing}, extra={extra}."
        )
    if not _dtype_matches(series, owned.dtype):
        raise NodeRejected(
            f"Node {node.id!r} output {owned.entity}.{owned.column} has dtype "
            f"{series.dtype!s}, not declared {owned.dtype!r}."
        )
    if owned.ownership is Ownership.ABSENT and not series.isna().all():
        raise NodeRejected(
            f"Node {node.id!r} wrote a value into ABSENT-owned "
            f"{owned.entity}.{owned.column}."
        )


def _validate_filter_mask(node: Node, series: object, population: Population) -> None:
    if not isinstance(series, pd.Series):
        raise NodeRejected(f"FILTER node {node.id!r} mask is not a pandas Series.")
    if series.index.has_duplicates:
        raise NodeRejected(f"FILTER node {node.id!r} mask repeats person ids.")
    frame = population.frame
    person_entity = frame.schema.person_entity
    id_column = frame.schema.entity_id_column(person_entity)
    expected = pd.Index(
        frame.table(person_entity)[id_column].to_numpy(copy=True), name=id_column
    )
    actual = pd.Index(series.index)
    if len(actual) != len(expected) or set(actual.tolist()) != set(expected.tolist()):
        raise NodeRejected(
            f"FILTER node {node.id!r} mask ids do not equal the base person ids."
        )
    if not (
        series.dtype == np.dtype(np.bool_) or isinstance(series.dtype, pd.BooleanDtype)
    ):
        raise NodeRejected(
            f"FILTER node {node.id!r} mask has dtype {series.dtype!s}, not bool."
        )
    if series.isna().any():
        raise NodeRejected(f"FILTER node {node.id!r} mask contains nulls.")


def _validate_create(node: Node, frame: Frame) -> None:
    try:
        frame.revalidate()
    except (TypeError, ValueError) as error:
        raise NodeRejected(
            f"Node {node.id!r} returned an invalid Frame: {error}"
        ) from error
    # Amendment 15: every name the graph will spell as entity.column is dot-free.
    dotted_names = sorted(
        name
        for entity in frame.entities
        for name in (entity, *map(str, frame.table(entity).columns))
        if "." in name
    )
    if dotted_names:
        raise NodeRejected(
            f"CREATE node {node.id!r} returned a Frame with dotted names "
            f"{dotted_names[:5]}; entity and column names may not contain '.'."
        )
    expected_columns = {(owned.entity, owned.column) for owned in node.outputs}
    actual_columns = {
        (entity, str(column))
        for entity in frame.entities
        for column in frame.table(entity).columns
        if column not in _structural_columns(frame, entity)
    }
    if actual_columns != expected_columns:
        missing = sorted(expected_columns - actual_columns)
        extra = sorted(actual_columns - expected_columns)
        raise NodeRejected(
            f"CREATE node {node.id!r} data columns do not exactly equal its "
            f"declaration; missing={missing}, extra={extra}."
        )
    for owned in node.outputs:
        table = frame.table(owned.entity)
        if owned.column not in table:
            raise NodeRejected(
                f"CREATE node {node.id!r} did not load declared column "
                f"{owned.entity}.{owned.column}."
            )
        series = table[owned.column]
        if not _dtype_matches(series, owned.dtype):
            raise NodeRejected(
                f"CREATE node {node.id!r} loaded {owned.entity}.{owned.column} "
                f"as {series.dtype!s}, not {owned.dtype!r}."
            )
        if owned.ownership is Ownership.ABSENT and not series.isna().all():
            raise NodeRejected(
                f"CREATE node {node.id!r} loaded a value into ABSENT-owned "
                f"{owned.entity}.{owned.column}."
            )


def _validate_result(
    node: Node,
    kernel_capabilities: Capabilities,
    result: KernelResult,
    population: Population | None,
    *,
    cache_hit: bool = False,
) -> tuple[dict[str, object], dict[str, bytes]]:
    if not isinstance(result, KernelResult):
        raise NodeRejected(
            f"Node {node.id!r} kernel returned {type(result).__name__}, not KernelResult."
        )
    if not isinstance(result.columns, Mapping):
        raise NodeRejected(f"Node {node.id!r} result.columns is not a mapping.")
    if result.expand is not None and not isinstance(result.expand, Mapping):
        raise NodeRejected(f"Node {node.id!r} result.expand is not a mapping.")
    if not isinstance(result.artifacts, Mapping):
        raise NodeRejected(f"Node {node.id!r} result.artifacts is not a mapping.")
    if not isinstance(result.receipt, Mapping):
        raise NodeRejected(f"Node {node.id!r} result.receipt is not a mapping.")
    if result.strata is not None and not isinstance(result.strata, pd.Series):
        raise NodeRejected(f"Node {node.id!r} result.strata is not a Series.")
    if result.strata is not None and (
        cache_hit or node.structural is not StructuralDelta.EXPAND or not node.entrants
    ):
        raise NodeRejected(
            f"Node {node.id!r} returned entrant strata outside a fresh "
            "entrants=True EXPAND."
        )
    if kernel_capabilities.structural is not node.structural:
        raise NodeRejected(
            f"Node {node.id!r} declares structural={node.structural.value!r}, but "
            f"kernel capabilities declare {kernel_capabilities.structural.value!r}."
        )

    expected = {(owned.entity, owned.column): owned for owned in node.outputs}
    try:
        got = set(result.columns)
    except (TypeError, ValueError) as error:
        raise NodeRejected(
            f"Node {node.id!r} result.columns has malformed coordinates."
        ) from error
    if any(
        not isinstance(coordinate, tuple)
        or len(coordinate) != 2
        or any(not isinstance(part, str) for part in coordinate)
        for coordinate in got
    ):
        raise NodeRejected(
            f"Node {node.id!r} result.columns keys must be (entity, column) strings."
        )
    if node.structural in {StructuralDelta.NONE, StructuralDelta.REVISION}:
        if got != set(expected):
            raise NodeRejected(
                f"Node {node.id!r} returned output keys {sorted(got)!r}, not exactly "
                f"its owned keys {sorted(expected)!r}."
            )
    elif node.structural is not StructuralDelta.EXPAND and got:
        raise NodeRejected(
            f"Structural node {node.id!r} returned column outputs; structural "
            "results use frame, keep, or weights."
        )

    if node.structural is StructuralDelta.FILTER:
        if population is None:  # pragma: no cover - compiler gives FILTER a base
            raise NodeRejected(f"FILTER node {node.id!r} has no base population.")
        _validate_filter_mask(node, result.keep, population)
    elif result.keep is not None:
        raise NodeRejected(f"Non-FILTER node {node.id!r} returned a keep mask.")

    frame_operations = {StructuralDelta.CREATE, StructuralDelta.EXPAND}
    if cache_hit:
        frame_operations.add(StructuralDelta.UNION)
    if node.structural not in frame_operations and result.frame is not None:
        raise NodeRejected(f"Node {node.id!r} returned a Frame outside CREATE/EXPAND.")
    if node.structural is StructuralDelta.UNION:
        if cache_hit and result.frame is None:
            raise NodeRejected(
                f"Cached UNION node {node.id!r} has no executor frame artifact."
            )
        if not cache_hit and result.frame is not None:
            raise NodeRejected(
                f"UNION node {node.id!r} returned a Frame; the executor owns union."
            )
    if node.structural is StructuralDelta.CREATE and result.frame is None:
        raise NodeRejected(f"CREATE node {node.id!r} did not return a Frame.")
    if node.structural is StructuralDelta.EXPAND:
        if cache_hit and result.frame is None:
            raise NodeRejected(
                f"Cached EXPAND node {node.id!r} has no executor frame artifact."
            )
        if not cache_hit and result.frame is not None:
            raise NodeRejected(
                f"EXPAND node {node.id!r} returned a Frame; kernels return "
                "source lineage, cells, and weights, and the executor expands."
            )
        if not cache_hit and result.expand is None:
            raise NodeRejected(
                f"EXPAND node {node.id!r} returned no per-entity lineage."
            )
        if cache_hit and result.expand is not None:
            raise NodeRejected(
                f"Cached EXPAND node {node.id!r} returned kernel lineage instead "
                "of its executor frame artifact."
            )
    elif result.expand is not None:
        raise NodeRejected(f"Non-EXPAND node {node.id!r} returned expansion lineage.")
    if result.frame is not None and not isinstance(result.frame, Frame):
        raise NodeRejected(f"Node {node.id!r} result.frame is not a Frame.")
    if node.structural is StructuralDelta.CREATE:
        assert result.frame is not None
        _validate_create(node, result.frame)

    lineage_expand = node.structural is StructuralDelta.EXPAND
    if lineage_expand:
        weight_entity = node.params.get("expand_weight_entity")
        weight_kind = node.params.get("expand_weight_kind")
        if not isinstance(weight_entity, str) or not weight_entity:
            raise NodeRejected(
                f"EXPAND node {node.id!r} has no normative weight entity."
            )
        if not isinstance(weight_kind, str) or not weight_kind:
            raise NodeRejected(f"EXPAND node {node.id!r} has no normative weight kind.")
        if result.weights is None:
            raise NodeRejected(f"EXPAND node {node.id!r} returned no weights.")
    elif (node.weights is None) != (result.weights is None):
        state = "returned" if result.weights is not None else "did not return"
        raise NodeRejected(
            f"Node {node.id!r} {state} weights inconsistently with its declaration."
        )
    if result.weights is not None and not isinstance(result.weights, Weights):
        raise NodeRejected(f"Node {node.id!r} result.weights is not Weights.")

    if population is not None:
        for coordinate, owned in expected.items():
            _validate_series(node, owned, result.columns[coordinate], population)

    artifacts: dict[str, bytes] = {}
    for name, payload in result.artifacts.items():
        if not isinstance(name, str) or not name:
            raise NodeRejected(
                f"Node {node.id!r} artifact names must be non-empty strings."
            )
        if not isinstance(payload, bytes):
            raise NodeRejected(f"Node {node.id!r} artifact {name!r} is not bytes.")
        artifacts[name] = payload
    for output in node.artifact_outputs:
        if output.name not in artifacts:
            error = StoreMiss if cache_hit else NodeRejected
            raise error(
                f"Node {node.id!r} is missing declared artifact {output.name!r}."
            )
    receipt = _normal_json_mapping(result.receipt, f"Node {node.id!r} receipt")
    if node.structural is StructuralDelta.EXPAND:
        if cache_hit:
            if not isinstance(receipt.get("expand"), dict):
                raise NodeRejected(
                    f"Cached EXPAND node {node.id!r} has no lineage receipt."
                )
        else:
            assert result.expand is not None
            try:
                receipt["expand"] = expand_lineage_receipt(result.expand)
                assert population is not None
                strata_receipt = entrant_strata_receipt(
                    population.frame, node, result.expand, result.strata
                )
            except (TypeError, ValueError) as error:
                raise NodeRejected(
                    f"EXPAND node {node.id!r} returned malformed lineage or "
                    f"entrant strata: {error}"
                ) from error
            receipt.pop("entrant_strata", None)
            if strata_receipt is not None:
                receipt["entrant_strata"] = strata_receipt
    if kernel_capabilities.role is KernelRole.GATE:
        outcome = receipt.get("outcome")
        if outcome not in GATE_OUTCOMES:
            raise NodeRejected(
                f"Gate node {node.id!r} returned outcome {outcome!r}; expected "
                f"one of {GATE_OUTCOMES!r}."
            )
    return receipt, artifacts


def _validate_entrant_materialization_contract(
    compiled: CompiledGraph,
    node: Node,
    population: Population | None,
    receipt: Mapping[str, object],
) -> None:
    """Require every entrant's carried data cells to have downstream claims."""

    if not node.entrants or population is None:
        return
    raw_expand = receipt.get("expand")
    if not isinstance(raw_expand, Mapping):
        return  # the ordinary EXPAND validation reports the malformed receipt
    entrant_entities: set[str] = set()
    for entity, entries in raw_expand.items():
        if not isinstance(entity, str) or not isinstance(entries, list):
            continue
        if any(
            isinstance(entry, list) and len(entry) == 2 and entry[1] is None
            for entry in entries
        ):
            entrant_entities.add(entity)

    frame = population.frame
    for entity in sorted(entrant_entities):
        if entity not in frame.entities:
            continue  # lineage validation supplies the node-naming rejection
        structural = set(_structural_columns(frame, entity))
        if (
            compiled.graph.mass_partition is not None
            and compiled.graph.mass_partition[0] == entity
        ):
            structural.add(compiled.graph.mass_partition[1])
        for column in frame.table(entity).columns:
            column = str(column)
            if column in structural:
                continue
            coordinate = (entity, column)
            claimant_id = compiled.owners.get((node.id, entity, column))
            if claimant_id is None:
                raise NodeRejected(
                    f"EXPAND node {node.id!r} entrant cell {entity}.{column} "
                    "has no materialized_expand_outputs ownership claim."
                )
            claimant = compiled.graph.node(claimant_id)
            claimed = claimant.params.get("materialized_expand_outputs", ())
            spelling = f"{entity}.{column}"
            output = next(
                (
                    owned
                    for owned in claimant.outputs
                    if (owned.entity, owned.column) == coordinate
                ),
                None,
            )
            if (
                not isinstance(claimed, tuple)
                or spelling not in claimed
                or output is None
                or output.rewrite
            ):
                raise NodeRejected(
                    f"EXPAND node {node.id!r} entrant cell {spelling} is not "
                    f"declared through node {claimant_id!r}'s "
                    "materialized_expand_outputs."
                )
            if output.rows != ROWS_ALL:
                raise NodeRejected(
                    f"EXPAND node {node.id!r} entrant cell {spelling} is claimed "
                    f"through masked rows {output.rows!r}; materialization bridge "
                    "claims must use rows='all'."
                )
            carried_dtype = _dtype_token(frame.table(entity)[column])
            if output.dtype != carried_dtype:
                raise NodeRejected(
                    f"EXPAND node {node.id!r} entrant cell {spelling} is claimed "
                    f"as {output.dtype!r}; its carried dtype is {carried_dtype!r}."
                )


def _create_population(node: Node, frame: Frame) -> Population:
    # Entity ids and membership columns are structural Frame columns rather
    # than declaration-owned data cells, but Population ownership is total
    # over the physical carrier.  The CREATE version supplies all of them.
    return Population.from_frame(frame, node.id)


def _validate_population_declaration(node: Node, population: Population | None) -> None:
    """Reject declarations that cross implicit population boundaries."""

    if node.weights is not None and node.structural is StructuralDelta.NONE:
        raise NodeRejected(
            f"Node {node.id!r} declares a weight transition without creating a "
            "structural population version."
        )
    if population is None or node.structural is not StructuralDelta.NONE:
        return
    schema = population.frame.schema
    structural = {
        (entity, schema.entity_id_column(entity)) for entity in schema.entities
    }
    structural.update(
        (schema.person_entity, schema.membership_column(group))
        for group in schema.group_entities
    )
    for owned in node.outputs:
        if (owned.entity, owned.column) in structural:
            raise NodeRejected(
                f"Node {node.id!r} cannot own structural column "
                f"{owned.entity}.{owned.column}; use a structural node."
            )


def _apply_result(
    node: Node,
    result: KernelResult,
    population: Population | None,
    *,
    cache_hit: bool = False,
    mass_partition: tuple[str, str] | None = None,
    rewrite_coordinates: frozenset[tuple[str, str]] = frozenset(),
    weight_anchor: Weights | None = None,
) -> Population:
    if (
        mass_partition is not None
        and node.structural in {StructuralDelta.NONE, StructuralDelta.REVISION}
        and any(
            (owned.entity, owned.column) == mass_partition for owned in node.outputs
        )
    ):
        entity, column = mass_partition
        raise NodeRejected(
            f"Node {node.id!r} cannot own mass partition {entity}.{column}; "
            "partition values are fixed by the structural population."
        )
    if node.structural is StructuralDelta.CREATE:
        assert result.frame is not None
        return _create_population(node, result.frame)
    assert population is not None
    if node.structural is StructuralDelta.UNION:
        if cache_hit and result.frame is not None:
            for entity in population.frame.entities:
                if not result.frame.table(entity).equals(
                    population.frame.table(entity)
                ):
                    raise NodeRejected(
                        f"Cached UNION node {node.id!r} frame disagrees with its bases."
                    )
            for entity in population.frame.weighted_entities:
                expected = population.frame.weights_for(entity)
                actual = result.frame.weights_for(entity)
                if actual.kind is not expected.kind or not np.array_equal(
                    actual.values, expected.values
                ):
                    raise NodeRejected(
                        f"Cached UNION node {node.id!r} weights disagree with its bases."
                    )
        return population
    if (
        cache_hit
        and node.structural is StructuralDelta.EXPAND
        and result.frame is not None
    ):
        try:
            return restore_cached_expand(
                population,
                node,
                result,
                mass_partition=mass_partition,
                rewrite_coordinates=rewrite_coordinates,
            )
        except (TypeError, ValueError) as error:
            raise NodeRejected(
                f"Node {node.id!r} cached EXPAND rejected: {error}"
            ) from error
    if node.structural is StructuralDelta.FILTER:
        person_entity = population.frame.schema.person_entity
        id_column = population.frame.schema.entity_id_column(person_entity)
        ids = pd.Index(
            population.frame.table(person_entity)[id_column].to_numpy(copy=True),
            name=id_column,
        )
        mask = (
            result.keep.reindex(ids).to_numpy(dtype=np.bool_, copy=True)  # type: ignore[union-attr]
        )
        result = KernelResult(
            frame=population.frame.select(mask),
            weights=result.weights,
            artifacts=result.artifacts,
            receipt=result.receipt,
        )
    # The frozen context has no base-Frame field.  A pure REWEIGHT kernel can
    # therefore return only its typed replacement weights; the executor binds
    # those weights to the incumbent structural frame here.
    if node.structural is StructuralDelta.REWEIGHT and result.frame is None:
        result = KernelResult(
            columns=result.columns,
            frame=population.frame,
            weights=result.weights,
            artifacts=result.artifacts,
            receipt=result.receipt,
        )
    try:
        return patch(
            population,
            node,
            result,
            mass_partition=mass_partition,
            rewrite_coordinates=rewrite_coordinates,
            weight_anchor=weight_anchor,
        )
    except NodeRejected:
        raise
    except (TypeError, ValueError) as error:
        raise NodeRejected(f"Node {node.id!r} patch rejected: {error}") from error


def _series_for_column(frame: Frame, entity: str, column: str) -> pd.Series:
    table = frame.table(entity)
    id_column = frame.schema.entity_id_column(entity)
    return pd.Series(
        table[column].array.copy(),
        index=pd.Index(table[id_column].to_numpy(copy=True), name=id_column),
        name=column,
        dtype=table[column].dtype,
    )


def _write_node(
    store: ContentStore,
    node: Node,
    *,
    key: str,
    kernel_impl_hash: str,
    capabilities: Capabilities,
    result: KernelResult,
    population: Population,
    receipt: Mapping[str, object],
    opaque_artifacts: Mapping[str, bytes],
    verify_existing: bool,
    typed_artifacts: Mapping[str, object] | None = None,
) -> tuple[dict[tuple[str, str], str], dict[str, object]]:
    columns: dict[tuple[str, str], tuple[pd.Series, str]] = {}
    if node.structural in {StructuralDelta.NONE, StructuralDelta.REVISION}:
        declared = {(owned.entity, owned.column): owned for owned in node.outputs}
        for coordinate, series in result.columns.items():
            columns[coordinate] = (series, declared[coordinate].dtype)
    else:
        for entity in population.frame.entities:
            for column in population.frame.table(entity).columns:
                series = _series_for_column(population.frame, entity, column)
                columns[(entity, column)] = (series, _dtype_token(series))

    column_entries: list[dict[str, str]] = []
    manifest_artifacts: dict[tuple[str, str], str] = {}
    for (entity, column), (series, token) in sorted(columns.items()):
        output_key = artifact_key(key, entity, column)
        store.put_column(
            output_key,
            series,
            declared_dtype=token,
            entity_ids=series.index,
            node_key=key,
            verify_existing=verify_existing,
        )
        column_entries.append({"entity": entity, "column": column, "key": output_key})
        manifest_artifacts[(entity, column)] = output_key

    stored_frame_key: str | None = None
    if node.structural not in {StructuralDelta.NONE, StructuralDelta.REVISION}:
        stored_frame_key = frame_key(key)
        store.put_frame(
            stored_frame_key,
            population.frame,
            node_key=key,
            verify_existing=verify_existing,
        )

    weight_entry: dict[str, str] | None = None
    if result.weights is not None:
        if node.weights is not None:
            entity = node.weights.entity
        elif node.structural is StructuralDelta.EXPAND and isinstance(
            node.params.get("expand_weight_entity"), str
        ):
            entity = str(node.params["expand_weight_entity"])
        else:  # defended by result validation
            raise NodeRejected(
                f"Node {node.id!r} returned weights without an entity contract."
            )
        id_column = population.frame.schema.entity_id_column(entity)
        ids = population.frame.table(entity)[id_column]
        weights_series = pd.Series(
            result.weights.values,
            index=pd.Index(ids.to_numpy(copy=True), name=id_column),
            dtype="float64",
            name="weights",
        )
        stored_weights_key = weights_key(key, entity)
        store.put_column(
            stored_weights_key,
            weights_series,
            declared_dtype="float64",
            entity_ids=weights_series.index,
            node_key=key,
            verify_existing=verify_existing,
        )
        weight_entry = {
            "entity": entity,
            "kind": result.weights.kind.value,
            "key": stored_weights_key,
        }

    opaque_entries: list[dict[str, str]] = []
    for name, payload in sorted(opaque_artifacts.items()):
        output_key = _opaque_artifact_key(key, name)
        store.put_bytes(
            output_key,
            payload,
            node_key=key,
            verify_existing=verify_existing,
        )
        opaque_entries.append({"name": name, "key": output_key})

    outcome_entry: str | None = None
    if capabilities.role is KernelRole.GATE:
        outcome_entry = validation_outcome_key(key)
        store.put_json(
            outcome_entry,
            {
                "schema_version": 1,
                "node_id": node.id,
                "node_key": key,
                "outcome": receipt["outcome"],
                **({"evidence": receipt["evidence"]} if "evidence" in receipt else {}),
            },
            kind="validation-outcome",
            node_key=key,
            verify_existing=verify_existing,
        )

    record: dict[str, object] = {
        "schema_version": 2 if typed_artifacts else 1,
        **({"typed_artifacts": dict(typed_artifacts)} if typed_artifacts else {}),
        "node_id": node.id,
        "node_key": key,
        "kernel_ref": node.kernel,
        "kernel_impl_hash": kernel_impl_hash,
        "capabilities": _capabilities_projection(capabilities),
        "receipt": dict(receipt),
        "columns": column_entries,
        "frame_key": stored_frame_key,
        "weight": weight_entry,
        "opaque": opaque_entries,
        **({"outcome_key": outcome_entry} if outcome_entry is not None else {}),
    }
    store.put_json(
        _cache_record_key(key),
        record,
        node_key=key,
        verify_existing=verify_existing,
    )
    return manifest_artifacts, record


def _require_record_shape(
    raw: object,
    node: Node,
    *,
    key: str,
    kernel_impl_hash: str,
    capabilities: Capabilities,
    typed_artifacts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise StoreCorrupt(f"Cached receipt for node {node.id!r} is not an object.")
    required = {
        "schema_version",
        "node_id",
        "node_key",
        "kernel_ref",
        "kernel_impl_hash",
        "capabilities",
        "receipt",
        "columns",
        "frame_key",
        "weight",
        "opaque",
    }
    if capabilities.role is KernelRole.GATE:
        if set(raw) == required | ({"typed_artifacts"} if typed_artifacts else set()):
            raise StoreMiss(
                f"Cached validation node {node.id!r} predates stored outcomes."
            )
        required.add("outcome_key")
    if typed_artifacts:
        required.add("typed_artifacts")
    if set(raw) != required:
        raise StoreCorrupt(
            f"Cached receipt for node {node.id!r} has fields {sorted(raw)}, "
            f"not {sorted(required)}."
        )
    if raw["schema_version"] != (2 if typed_artifacts else 1):
        raise StoreUnavailable(
            f"Cached receipt for node {node.id!r} uses unsupported schema "
            f"{raw['schema_version']!r}."
        )
    if typed_artifacts and raw.get("typed_artifacts") != dict(typed_artifacts):
        raise StoreCorrupt(
            f"Cached node {node.id!r} typed artifact contracts disagree with the graph."
        )
    if typed_artifacts:
        opaque = _record_entries(raw, "opaque")
        names = [entry.get("name") for entry in opaque]
        if len(set(names)) != len(names):
            raise StoreCorrupt(f"Cached node {node.id!r} repeats an opaque artifact.")
        actual_outputs = {entry.get("name"): entry.get("key") for entry in opaque}
        for output in node.artifact_outputs:
            if output.name not in actual_outputs:
                raise StoreMiss(
                    f"Cached node {node.id!r} is missing declared artifact {output.name!r}."
                )
            if actual_outputs[output.name] != _opaque_artifact_key(key, output.name):
                raise StoreCorrupt(
                    f"Cached node {node.id!r} artifact identity mismatch."
                )
    expected = (node.id, key, node.kernel, kernel_impl_hash)
    actual = (
        raw["node_id"],
        raw["node_key"],
        raw["kernel_ref"],
        raw["kernel_impl_hash"],
    )
    if actual != expected:
        raise StoreCorrupt(
            f"Cached receipt identity for node {node.id!r} is {actual!r}, "
            f"not {expected!r}."
        )
    expected_capabilities = _capabilities_projection(capabilities)
    stored_capabilities = raw["capabilities"]
    if (
        isinstance(stored_capabilities, Mapping)
        and "tolerance" not in stored_capabilities
    ):
        raise StoreMiss(
            f"Cached receipt for node {node.id!r} has legacy_capabilities: "
            "the schema-v1 contract omits tolerance."
        )
    if raw["capabilities"] != expected_capabilities:
        raise StoreMiss(
            f"Cached receipt capabilities for node {node.id!r} disagree with "
            "the registered kernel contract."
        )
    if capabilities.role is KernelRole.GATE and raw.get(
        "outcome_key"
    ) != validation_outcome_key(key):
        raise StoreCorrupt(
            f"Cached validation outcome identity for node {node.id!r} is malformed."
        )
    if node.structural is StructuralDelta.EXPAND:
        raw_receipt = raw["receipt"]
        if not isinstance(raw_receipt, Mapping):
            raise StoreCorrupt(f"Cached node {node.id!r} receipt is malformed.")
        if "expand_writes" not in raw_receipt:
            raise StoreMiss(
                f"Cached EXPAND node {node.id!r} predates expand_writes provenance."
            )
        if "expand_declared" not in raw_receipt:
            raise StoreMiss(
                f"Cached EXPAND node {node.id!r} predates expand_declared provenance."
            )
        try:
            _parse_expand_declared(node, raw_receipt["expand_declared"])
            _parse_expand_writes(node, raw_receipt["expand_writes"])
        except ValueError as error:
            raise StoreCorrupt(
                f"Cached EXPAND node {node.id!r} has malformed EXPAND provenance."
            ) from error
    return raw


def _record_entries(
    record: Mapping[str, object], field: str
) -> list[dict[str, object]]:
    value = record[field]
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise StoreCorrupt(f"Cached node receipt field {field!r} is malformed.")
    return value  # type: ignore[return-value]


def _load_record(
    store: ContentStore,
    node: Node,
    *,
    key: str,
    kernel_impl_hash: str,
    capabilities: Capabilities,
    typed_artifacts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    raw = store.load_json(_cache_record_key(key))
    return _require_record_shape(
        raw,
        node,
        key=key,
        kernel_impl_hash=kernel_impl_hash,
        capabilities=capabilities,
        typed_artifacts=typed_artifacts,
    )


def _tolerance_writer_payload(
    writers: Mapping[tuple[str, str], tuple[str, ...]],
) -> dict[str, list[str]]:
    return {
        f"{entity}.{column}": list(writer_ids)
        for (entity, column), writer_ids in writers.items()
    }


def _require_tolerance_writer_receipt(
    node: Node,
    record: Mapping[str, object],
    writers: Mapping[tuple[str, str], tuple[str, ...]],
    *,
    exact: bool,
) -> None:
    """Reject cache receipts predating or disagreeing with writer provenance."""

    expected = _tolerance_writer_payload(writers)
    if not expected:
        return
    raw_receipt = record.get("receipt")
    if not isinstance(raw_receipt, Mapping):
        raise StoreCorrupt(f"Cached node {node.id!r} receipt is malformed.")
    raw_capabilities = raw_receipt.get("capabilities")
    actual = (
        raw_capabilities.get("tolerance_writers")
        if isinstance(raw_capabilities, Mapping)
        else None
    )
    expected_coordinates = set(expected)
    matches = (
        actual == expected
        if exact
        else (isinstance(actual, Mapping) and set(actual) == expected_coordinates)
    )
    if not matches:
        raise StoreMiss(
            f"Cached node {node.id!r} has stale tolerance_writers provenance."
        )

    evidence = raw_receipt.get("evidence")
    if isinstance(evidence, Mapping) and "tolerance" in evidence:
        evidence_writers = evidence.get("tolerance_writers")
        evidence_matches = (
            evidence_writers == expected
            if exact
            else (
                isinstance(evidence_writers, Mapping)
                and set(evidence_writers) == expected_coordinates
            )
        )
        if not evidence_matches:
            raise StoreMiss(
                f"Cached node {node.id!r} has stale evidence "
                "tolerance_writers provenance."
            )


def _preflight_record(store: ContentStore, record: Mapping[str, object]) -> None:
    for entry in _record_entries(record, "columns"):
        store.load_column(str(entry.get("key")))
    frame_artifact = record["frame_key"]
    if frame_artifact is not None:
        store.load_frame(str(frame_artifact))
    weight = record["weight"]
    if weight is not None:
        if not isinstance(weight, dict) or "key" not in weight:
            raise StoreCorrupt("Cached node weight entry is malformed.")
        store.load_column(str(weight["key"]))
    for entry in _record_entries(record, "opaque"):
        store.load_bytes(str(entry.get("key")))
    outcome_key = record.get("outcome_key")
    if outcome_key is not None:
        store.load_json(str(outcome_key), kind="validation-outcome")
    receipt = record.get("receipt")
    lineage = receipt.get("union_lineage") if isinstance(receipt, Mapping) else None
    if isinstance(lineage, Mapping) and isinstance(lineage.get("key"), str):
        store.load_json(lineage["key"], kind="union-lineage")


def _load_cached_result(
    store: ContentStore,
    node: Node,
    population: Population | None,
    record: Mapping[str, object],
) -> tuple[KernelResult, dict[tuple[str, str], str]]:
    stored_columns: dict[tuple[str, str], pd.Series] = {}
    manifest_artifacts: dict[tuple[str, str], str] = {}
    for entry in _record_entries(record, "columns"):
        try:
            entity = str(entry["entity"])
            column = str(entry["column"])
            output_key = str(entry["key"])
        except KeyError as error:
            raise StoreCorrupt("Cached node column entry is malformed.") from error
        coordinate = (entity, column)
        if coordinate in stored_columns:
            raise StoreCorrupt(f"Cached node repeats column {entity}.{column}.")
        stored_columns[coordinate] = store.load_column(output_key)
        manifest_artifacts[coordinate] = output_key

    result_columns: dict[tuple[str, str], pd.Series] = {}
    if node.structural in {StructuralDelta.NONE, StructuralDelta.REVISION}:
        for owned in node.outputs:
            coordinate = (owned.entity, owned.column)
            try:
                result_columns[coordinate] = stored_columns[coordinate]
            except KeyError as error:
                raise StoreMiss(
                    f"Cached node {node.id!r} is missing {owned.entity}.{owned.column}."
                ) from error

    loaded_frame: Frame | None = None
    frame_artifact = record["frame_key"]
    if frame_artifact is not None:
        loaded_frame = store.load_frame(str(frame_artifact))
    if (
        node.structural
        not in {
            StructuralDelta.NONE,
            StructuralDelta.REVISION,
        }
        and loaded_frame is None
    ):
        raise StoreMiss(f"Cached structural node {node.id!r} has no frame artifact.")

    loaded_weights: Weights | None = None
    weight = record["weight"]
    if weight is not None:
        if not isinstance(weight, dict):
            raise StoreCorrupt(f"Cached node {node.id!r} weight entry is malformed.")
        try:
            entity = str(weight["entity"])
            kind = WeightKind(str(weight["kind"]))
            weight_series = store.load_column(str(weight["key"]))
        except (KeyError, ValueError) as error:
            raise StoreCorrupt(
                f"Cached node {node.id!r} weight entry is malformed."
            ) from error
        expected_weight_entity = (
            node.weights.entity
            if node.weights is not None
            else node.params.get("expand_weight_entity")
            if node.structural is StructuralDelta.EXPAND
            else None
        )
        if entity != expected_weight_entity:
            raise StoreCorrupt(
                f"Cached node {node.id!r} carries undeclared weights for {entity!r}."
            )
        loaded_weights = Weights(
            values=weight_series.to_numpy(dtype=np.float64, copy=True), kind=kind
        )
    elif node.weights is not None or node.structural is StructuralDelta.EXPAND:
        raise StoreMiss(f"Cached node {node.id!r} is missing its weights artifact.")

    opaque: dict[str, bytes] = {}
    for entry in _record_entries(record, "opaque"):
        try:
            name = str(entry["name"])
            output_key = str(entry["key"])
        except KeyError as error:
            raise StoreCorrupt("Cached opaque artifact entry is malformed.") from error
        opaque[name] = store.load_bytes(output_key)

    raw_receipt = record["receipt"]
    if not isinstance(raw_receipt, dict):
        raise StoreCorrupt(f"Cached node {node.id!r} receipt is malformed.")
    outcome_key = record.get("outcome_key")
    if outcome_key is not None:
        stored_outcome = store.load_json(str(outcome_key), kind="validation-outcome")
        expected_outcome = {
            "schema_version": 1,
            "node_id": node.id,
            "node_key": str(record["node_key"]),
            "outcome": raw_receipt.get("outcome"),
            **(
                {"evidence": raw_receipt["evidence"]}
                if "evidence" in raw_receipt
                else {}
            ),
        }
        if stored_outcome != expected_outcome:
            raise StoreCorrupt(
                f"Stored validation outcome for node {node.id!r} disagrees "
                "with its receipt."
            )

    # Reapply FILTER/REWEIGHT to the current base so graph mass checks and
    # ledgers are reconstructed on a hit.  Their stored final frame was loaded
    # above solely for content validation.
    result_frame = loaded_frame
    loaded_keep: pd.Series | None = None
    if (
        node.structural is StructuralDelta.FILTER
        and loaded_frame is not None
        and population is not None
    ):
        person_entity = population.frame.schema.person_entity
        id_column = population.frame.schema.entity_id_column(person_entity)
        base_ids = population.frame.table(person_entity)[id_column]
        kept_ids = set(loaded_frame.table(person_entity)[id_column].tolist())
        loaded_keep = pd.Series(
            base_ids.isin(kept_ids).to_numpy(dtype=np.bool_),
            index=pd.Index(base_ids.to_numpy(copy=True), name=id_column),
            dtype="bool",
        )
        result_frame = None
    if (
        node.structural is StructuralDelta.REWEIGHT
        and loaded_weights is not None
        and population is not None
    ):
        result_frame = None
    return (
        KernelResult(
            columns=MappingProxyType(result_columns),
            frame=result_frame,
            keep=loaded_keep,
            weights=loaded_weights,
            artifacts=MappingProxyType(opaque),
            receipt=MappingProxyType(raw_receipt),
        ),
        manifest_artifacts,
    )


def _source_paths_and_keys(
    compiled: CompiledGraph,
    sources: Mapping[str, Path],
    store: ContentStore,
) -> tuple[dict[str, BoundSource], dict[str, str], dict[str, Mapping[str, object]]]:
    declared = {source.name: source for source in compiled.graph.sources}
    used = {name for node in compiled.graph.nodes for name in node.sources}
    missing = sorted(used - sources.keys())
    if missing:
        raise FileNotFoundError(f"No source path supplied for {missing!r}.")
    unknown = sorted(sources.keys() - declared.keys())
    if unknown:
        raise ValueError(f"Source paths supplied for undeclared names {unknown!r}.")
    resolved: dict[str, BoundSource] = {}
    identities: dict[str, str] = {}
    receipts: dict[str, Mapping[str, object]] = {}
    for name in sorted(used):
        path = Path(sources[name]).resolve(strict=True)
        declaration = declared[name]
        codec = declaration.codec
        configured = store.codecs
        if configured is None:
            loader = SOURCE_CODECS.get(codec)
            codec_identity = SOURCE_CODECS.implementation_hash(codec)
        elif isinstance(configured, SourceCodecRegistry):
            loader = configured.get(codec)
            codec_identity = configured.implementation_hash(codec)
        elif isinstance(configured, Mapping):
            loader = configured.get(codec)
            if not callable(loader):
                raise StoreUnavailable(f"Source codec {codec!r} is not installed.")
            codec_identity = source_hash(loader)
        else:  # defended by ContentStore.__init__
            raise StoreUnavailable("ContentStore has an invalid codec registry.")
        boundary_kind, calculated_sha256, calculated_size = source_content_identity(
            path
        )
        content_key = source_content_key(name, path)
        expectation_receipts: list[dict[str, object]] = []
        for expectation in declaration.expected:
            expected_path = path
            if expectation.boundary == "member":
                assert expectation.path is not None
                expected_path = path.joinpath(*expectation.path.split("/"))
                if expected_path.is_symlink() or not expected_path.is_file():
                    raise StoreUnavailable(
                        f"Source {name!r} expected member {expectation.path!r} "
                        "is not a regular file."
                    )
                member_kind, observed_sha256, observed_size = source_content_identity(
                    expected_path
                )
                assert member_kind == "file"
            else:
                observed_sha256 = calculated_sha256
                observed_size = calculated_size
            matches = expectation.sha256 == observed_sha256 and (
                expectation.size is None or expectation.size == observed_size
            )
            expectation_receipts.append(
                {
                    "boundary": expectation.boundary,
                    **(
                        {"path": expectation.path}
                        if expectation.path is not None
                        else {}
                    ),
                    "expected_sha256": expectation.sha256,
                    **(
                        {"expected_size": expectation.size}
                        if expectation.size is not None
                        else {}
                    ),
                    "calculated_sha256": observed_sha256,
                    "calculated_size": observed_size,
                    **(
                        {"identity_ref": expectation.identity_ref}
                        if expectation.identity_ref
                        else {}
                    ),
                    "matched": matches,
                }
            )
            if not matches:
                raise StoreUnavailable(
                    f"Source {name!r} content identity mismatch at "
                    f"{expectation.boundary!r} boundary"
                    + (f" {expectation.path!r}" if expectation.path is not None else "")
                    + f": expected {expectation.sha256}, calculated {observed_sha256}."
                )
        binding_identity = source_binding_key(
            content_key, codec, codec_identity, declaration.content_type
        )
        receipt: Mapping[str, object] = MappingProxyType(
            {
                "name": name,
                "content_type": declaration.content_type,
                **({"access": declaration.access} if declaration.access else {}),
                "content": {
                    "boundary": boundary_kind,
                    "sha256": calculated_sha256,
                    "size": calculated_size,
                    "key": content_key,
                },
                "codec": codec,
                "codec_impl_hash": codec_identity,
                "binding_key": binding_identity,
                "expected": expectation_receipts,
            }
        )
        resolved[name] = BoundSource(
            name=name,
            path=path,
            codec=codec,
            codec_impl_hash=codec_identity,
            content_key=content_key,
            binding_key=binding_identity,
            receipt=receipt,
            loader=loader,  # type: ignore[arg-type]
            store=store,
        )
        identities[name] = binding_identity
        receipts[name] = receipt
    return resolved, identities, receipts


def _all_node_keys(
    compiled: CompiledGraph,
    kernels: KernelRegistry,
    source_keys: Mapping[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    keys: dict[str, str] = {}
    implementations: dict[str, str] = {}
    for node_id in compiled.order:
        node = compiled.graph.node(node_id)
        kernel = kernels.get(node.kernel)
        implementation = kernel.implementation_hash()
        if not isinstance(implementation, str) or not implementation:
            raise ValueError(
                f"Kernel {node.kernel!r} returned an invalid implementation hash."
            )
        implementations[node_id] = implementation
        keys[node_id] = node_key(
            compiled,
            node_id,
            keys,
            implementation,
            source_keys,
            kernel_capabilities=kernel.capabilities,
        )
    return keys, implementations


def _preflight_require(
    compiled: CompiledGraph,
    store: ContentStore,
    keys: Mapping[str, str],
    implementations: Mapping[str, str],
    kernels: KernelRegistry,
) -> None:
    missing: list[str] = []
    outcomes: dict[str, str] = {}
    unreached: set[str] = set()
    for node_id in compiled.order:
        node = compiled.graph.node(node_id)
        required_producers = {
            compiled.product_nodes[name] for name in node.requires_success
        }
        if any(
            predecessor in unreached for predecessor in compiled.predecessors[node_id]
        ) or any(
            outcomes.get(producer) not in _CERTIFYING_GATE_OUTCOMES
            for producer in required_producers
        ):
            unreached.add(node_id)
            continue
        try:
            record = _load_record(
                store,
                node,
                key=keys[node_id],
                kernel_impl_hash=implementations[node_id],
                capabilities=kernels.get(node.kernel).capabilities,
                typed_artifacts=typed_contracts(compiled, node, keys, kernels),
            )
            _require_tolerance_writer_receipt(
                node,
                record,
                _input_writers(compiled, node_id),
                exact=False,
            )
            _preflight_record(store, record)
            raw_receipt = record.get("receipt")
            if kernels.get(
                node.kernel
            ).capabilities.role is KernelRole.GATE and isinstance(raw_receipt, Mapping):
                outcomes[node_id] = str(raw_receipt.get("outcome"))
        except StoreMiss:
            missing.append(node_id)
    if missing:
        raise StoreMiss(
            "resume='require' found cache misses before execution: "
            + ", ".join(repr(node_id) for node_id in missing)
        )


def _preflight_expand_declarations(compiled: CompiledGraph) -> None:
    """Reject malformed runtime EXPAND conventions before keys or cache I/O."""

    for node_id in compiled.order:
        node = compiled.graph.node(node_id)
        if node.structural is not StructuralDelta.EXPAND:
            continue
        try:
            _expand_writer_coordinates(node)
        except (TypeError, ValueError) as error:
            raise NodeRejected(
                f"Node {node.id!r} expand_cells declaration rejected: {error}"
            ) from error


def _weight_anchors(
    compiled: CompiledGraph,
    node: Node,
    population: Population | None,
    populations: Mapping[str, Population],
) -> Mapping[str, Weights]:
    transition = node.weights
    if transition is None or transition.anchor is None:
        return MappingProxyType({})
    if population is None:
        raise NodeRejected(f"Node {node.id!r} has no population for its weight anchor.")
    product_name = transition.anchor
    producer = compiled.product_nodes[product_name]
    version = compiled.versions[producer]
    try:
        anchor_population = populations[version]
        anchor = anchor_population.frame.weights_for(transition.entity)
    except (KeyError, ValueError) as error:
        raise NodeRejected(
            f"Node {node.id!r} cannot resolve weight anchor {product_name!r}."
        ) from error
    id_column = population.frame.schema.entity_id_column(transition.entity)
    current_ids = pd.Index(population.frame.table(transition.entity)[id_column])
    anchor_ids = pd.Index(anchor_population.frame.table(transition.entity)[id_column])
    if not current_ids.equals(anchor_ids):
        raise NodeRejected(
            f"Node {node.id!r} weight anchor {product_name!r} is not exactly "
            "aligned to the transition population."
        )
    return MappingProxyType({product_name: anchor})


def _weight_anchor_receipt(
    compiled: CompiledGraph,
    node: Node,
    updated: Population,
    anchors: Mapping[str, Weights],
    keys: Mapping[str, str],
) -> Mapping[str, object]:
    transition = node.weights
    if transition is None or transition.anchor is None:
        return MappingProxyType({})
    name = transition.anchor
    anchor = anchors[name]
    current = updated.frame.weights_for(transition.entity)
    ratios = np.divide(
        current.values,
        anchor.values,
        out=np.full(len(current.values), np.inf, dtype=np.float64),
        where=anchor.values > 0,
    )
    ratios[(anchor.values == 0) & (current.values == 0)] = 0.0
    realized = float(ratios.max())
    cap = node.params.get("max_weight_ratio")
    if cap is not None:
        if (
            isinstance(cap, bool)
            or not isinstance(cap, int | float)
            or not np.isfinite(float(cap))
            or float(cap) <= 0
        ):
            raise NodeRejected(
                f"Node {node.id!r} max_weight_ratio must be finite and positive."
            )
        if realized > float(cap) and not np.isclose(
            realized, float(cap), rtol=1e-12, atol=0.0
        ):
            raise NodeRejected(
                f"Node {node.id!r} realized weight ratio {realized!r} exceeds "
                f"{float(cap)!r} relative to {name!r}."
            )
    producer = compiled.product_nodes[name]
    return MappingProxyType(
        {
            "weight_anchor": {
                "product": name,
                "producer": producer,
                "producer_key": keys[producer],
                "entity": transition.entity,
                "kind": anchor.kind.value,
                "realized_max_weight_ratio": realized,
                **({"max_weight_ratio": float(cap)} if cap is not None else {}),
            }
        }
    )


def _blocked_by(
    compiled: CompiledGraph,
    node: Node,
    receipts: Mapping[str, NodeReceipt],
) -> tuple[str, ...]:
    """Return failed required validations or already-unreached predecessors."""

    blockers = {
        predecessor
        for predecessor in compiled.predecessors[node.id]
        if predecessor in receipts and receipts[predecessor].status == "unreached"
    }
    for product_name in node.requires_success:
        producer = compiled.product_nodes[product_name]
        receipt = receipts[producer]
        if (
            receipt.status == "unreached"
            or receipt.receipt.get("outcome") not in _CERTIFYING_GATE_OUTCOMES
        ):
            blockers.add(producer)
    return tuple(sorted(blockers))


def _graph_product_receipts(
    compiled: CompiledGraph, receipts: Mapping[str, NodeReceipt]
) -> Mapping[str, object]:
    """Resolve declared product names to portable producer and artifact records."""

    products: dict[str, object] = {}

    def coordinate_supplier(version: str, entity: str, column: str) -> str:
        owner = compiled.owners.get((version, entity, column))
        if owner is not None:
            return owner
        holder = compiled.graph.node(version)
        if holder.structural is StructuralDelta.REVISION:
            assert holder.base is not None
            return coordinate_supplier(holder.base, entity, column)
        return version

    for product in sorted(compiled.graph.products, key=lambda item: item.name):
        if product.kind is ProductKind.EXPORT:
            products[product.name] = {
                "kind": product.kind.value,
                "source": product.source,
                "codec": product.codec,
                "codec_version": product.codec_version,
            }
            continue
        assert product.node is not None
        producer_receipt = receipts[product.node]
        record: dict[str, object] = {
            "kind": product.kind.value,
            "producer": product.node,
            "producer_key": producer_receipt.key,
            "status": producer_receipt.status,
        }
        if producer_receipt.status == "unreached":
            products[product.name] = record
            continue
        if product.kind is ProductKind.POPULATION:
            record["version"] = compiled.versions[product.node]
        elif product.kind is ProductKind.COORDINATE:
            assert product.entity is not None and product.column is not None
            supplier = coordinate_supplier(
                compiled.versions[product.node], product.entity, product.column
            )
            record.update(
                {
                    "entity": product.entity,
                    "column": product.column,
                    "supplier": supplier,
                    "key": receipts[supplier].artifacts[
                        (product.entity, product.column)
                    ],
                }
            )
        elif product.kind is ProductKind.WEIGHTS:
            assert product.entity is not None
            record["entity"] = product.entity
            version = compiled.versions[product.node]
            state_receipt = receipts[version]
            while (
                state_receipt.weight_key is None
                and state_receipt.frame_key is None
                and compiled.graph.node(version).structural is StructuralDelta.REVISION
            ):
                base = compiled.graph.node(version).base
                assert base is not None
                version = base
                state_receipt = receipts[version]
            record["state"] = version
            record["key"] = state_receipt.weight_key or state_receipt.frame_key
        elif product.kind is ProductKind.ARTIFACT:
            assert product.artifact is not None
            record["artifact"] = product.artifact
            record["key"] = producer_receipt.opaque_artifacts[product.artifact]
        elif product.kind is ProductKind.VALIDATION:
            record["key"] = producer_receipt.outcome_key
            record["outcome"] = producer_receipt.receipt["outcome"]
        products[product.name] = record
    return MappingProxyType(products)


def run_graph(
    compiled: CompiledGraph,
    *,
    sources: Mapping[str, Path],
    store: ContentStore,
    kernels: KernelRegistry,
    resume: ResumePolicy = "auto",
    decisions: tuple[Decision, ...] = (),
    graph_source: object | None = None,
    graph_json: str | bytes | None = None,
) -> RunManifest:
    """Execute a compiled graph with content-addressed reuse and receipts."""

    if resume not in ("auto", "require", "forbid"):
        raise ValueError("resume must be 'auto', 'require', or 'forbid'.")
    normalized_decisions: list[Decision] = []
    for decision in decisions:
        if isinstance(decision, Decision):
            normalized_decisions.append(decision)
        elif isinstance(decision, Mapping):
            normalized_decisions.append(Decision.from_mapping(decision))
        else:
            raise TypeError("decisions must contain Decision records or mappings.")
    decisions = tuple(normalized_decisions)

    source_graph = getattr(graph_source, "graph", None)
    if graph_source is not None and source_graph != compiled.graph:
        raise ValueError("graph_source does not describe the compiled Graph.")
    graph_source_receipts = tuple(
        {
            "path": receipt.path,
            "sha256": receipt.sha256,
        }
        for receipt in getattr(graph_source, "receipts", ())
    )
    run_parameters = dict(getattr(graph_source, "parameters", {}))
    graph_json_key: str | None = None
    if graph_json is not None:
        graph_json_bytes = (
            graph_json.encode("utf-8") if isinstance(graph_json, str) else graph_json
        )
        decoded = graph_json_bytes.decode("utf-8")
        if graph_document_from_json(decoded) != compiled.graph:
            raise ValueError("graph_json does not serialize the compiled Graph.")
        graph_json_key = sha256_domain("graph-json", graph_json_bytes)
        store.put_bytes(graph_json_key, graph_json_bytes)

    validate_kernel_registry(compiled, kernels)
    _preflight_expand_declarations(compiled)
    started_at = _now()
    source_paths, source_keys, source_receipts = _source_paths_and_keys(
        compiled, sources, store
    )
    keys, implementations = _all_node_keys(compiled, kernels, source_keys)
    contracts = {
        node_id: typed_contracts(compiled, compiled.graph.node(node_id), keys, kernels)
        for node_id in compiled.order
    }
    if resume == "require":
        _preflight_require(compiled, store, keys, implementations, kernels)

    populations: dict[str, Population] = {}
    receipts: dict[str, NodeReceipt] = {}
    for node_id in compiled.order:
        node_started = time.perf_counter()
        node = compiled.graph.node(node_id)
        key = keys[node_id]
        implementation = implementations[node_id]
        kernel = kernels.get(node.kernel)
        if kernel.capabilities.structural is not node.structural:
            raise NodeRejected(
                f"Node {node.id!r} structural declaration does not match kernel "
                "capabilities."
            )
        blockers = _blocked_by(compiled, node, receipts)
        if blockers:
            receipts[node_id] = NodeReceipt(
                typed_artifacts={},
                key=key,
                hit=False,
                seed=seed(key),
                kernel_ref=node.kernel,
                kernel_impl_hash=implementation,
                capabilities=kernel.capabilities,
                receipt=MappingProxyType(
                    {
                        "blocked_by": list(blockers),
                        **(
                            {"outcome": "unreached"}
                            if kernel.capabilities.role is KernelRole.GATE
                            else {}
                        ),
                    }
                ),
                wall_time=time.perf_counter() - node_started,
                status="unreached",
                blocked_by=blockers,
            )
            continue

        union_lineage: Mapping[str, tuple[tuple[object, str, object], ...]] | None = (
            None
        )
        if node.structural is StructuralDelta.CREATE:
            incumbent: Population | None = None
        elif node.structural is StructuralDelta.UNION:
            try:
                incumbent, union_lineage = union_populations(
                    {base: populations[base] for base in node.bases}, node
                )
            except (TypeError, ValueError) as error:
                raise NodeRejected(
                    f"UNION node {node.id!r} rejected its bases: {error}"
                ) from error
        elif node.structural is StructuralDelta.NONE:
            incumbent = populations[compiled.versions[node_id]]
        else:
            assert node.base is not None
            incumbent = populations[node.base]
        _validate_population_declaration(node, incumbent)
        _validate_materialized_expand_outputs(compiled, node, incumbent, receipts)
        input_writers = _input_writers(compiled, node_id, receipts=receipts)
        input_numerics = _input_numerics(
            compiled, node_id, kernels, writers=input_writers
        )
        input_tolerances = _input_tolerances(
            compiled,
            node_id,
            kernels,
            writers=input_writers,
            numerics=input_numerics,
        )
        tolerance_writers = _tolerance_writer_payload(input_writers)
        weight_anchors = _weight_anchors(compiled, node, incumbent, populations)

        typed = contracts[node_id]
        artifact_values = {}
        for binding in node.artifact_inputs:
            entry = typed["inputs"][binding.name]
            producer_receipt = receipts[binding.producer]
            if producer_receipt.opaque_artifacts.get(binding.artifact) != entry["key"]:
                raise StoreCorrupt(
                    f"Node {node.id!r} artifact producer receipt disagrees with its declaration."
                )
            artifact_values[binding.name] = value_from_descriptor(
                store.load_bytes(entry["key"]), entry
            )
        hit = False
        replace_stale_record = False
        result: KernelResult | None = None
        record: dict[str, object] | None = None
        manifest_artifacts: dict[tuple[str, str], str] = {}
        if resume != "forbid":
            try:
                record = _load_record(
                    store,
                    node,
                    key=key,
                    kernel_impl_hash=implementation,
                    capabilities=kernel.capabilities,
                    typed_artifacts=typed,
                )
                try:
                    _require_tolerance_writer_receipt(
                        node, record, input_writers, exact=True
                    )
                except StoreMiss:
                    # This key predates the writer-provenance contract or was
                    # produced for different runtime entrant lineage.
                    replace_stale_record = True
                    raise
                result, manifest_artifacts = _load_cached_result(
                    store, node, incumbent, record
                )
                hit = True
            except StoreMiss:
                replace_stale_record = store.has(_cache_record_key(key))
                if resume == "require":  # defended by preflight; handles races
                    raise

        if result is None:
            context = _project_context(
                node,
                incumbent,
                key=key,
                sources=source_paths,
                tolerances=input_tolerances,
                numerics=input_numerics,
                artifacts=artifact_values,
                weight_anchors=weight_anchors,
            )
            before = _context_digest(context)
            try:
                result = kernel.run(context)
            except Exception as error:
                if kernel.capabilities.role is KernelRole.GATE:
                    result = _failed_gate_result(node, incumbent, error)
                elif isinstance(error, StoreUnavailable):
                    raise
                else:
                    raise NodeRejected(
                        f"Node {node.id!r} kernel {node.kernel!r} failed: {error}"
                    ) from error
            after = _context_digest(context)
            if before != after:
                raise NodeRejected(f"Node {node.id!r} mutated its input context.")
            for name in node.sources:
                current = source_content_key(name, source_paths[name].path)
                if current != source_paths[name].content_key:
                    raise NodeRejected(
                        f"Node {node.id!r} changed source {name!r} while running."
                    )

        normalized_receipt, opaque = _validate_result(
            node,
            kernel.capabilities,
            result,
            incumbent,
            cache_hit=hit,
        )
        _validate_entrant_materialization_contract(
            compiled, node, incumbent, normalized_receipt
        )
        if union_lineage is not None:
            lineage_payload = {
                entity: [list(entry) for entry in entries]
                for entity, entries in union_lineage.items()
            }
            lineage_key = union_lineage_key(key)
            store.put_json(
                lineage_key,
                lineage_payload,
                kind="union-lineage",
                node_key=key,
            )
            normalized_receipt["union_lineage"] = {
                "key": lineage_key,
                "rows": {
                    entity: len(entries) for entity, entries in union_lineage.items()
                },
            }
        if kernel.capabilities.role is KernelRole.RELEASE:
            derived_tier, gate_ids = _release_tier(compiled, node_id, receipts)
            _validate_release_tier(node, result, derived_tier)
            required_decisions = _required_decision_names(node)
            normalized_receipt["tier"] = derived_tier
            normalized_receipt["outcome"] = (
                "pass" if derived_tier == "certified" else "fail"
            )
            normalized_receipt["gate_ancestry"] = list(gate_ids)
            # Required names are derived from normative node params and live in
            # authenticated release provenance. The signed records themselves
            # remain top-level run provenance and never enter a node key.
            normalized_receipt["requires_decisions"] = list(required_decisions)
        receipt_capabilities = _capabilities_projection(kernel.capabilities)
        if tolerance_writers:
            receipt_capabilities["tolerance_writers"] = tolerance_writers
        normalized_receipt["capabilities"] = receipt_capabilities
        evidence = normalized_receipt.get("evidence")
        if (
            tolerance_writers
            and isinstance(evidence, Mapping)
            and "tolerance" in evidence
        ):
            normalized_receipt["evidence"] = {
                **evidence,
                "tolerance_writers": tolerance_writers,
            }
        expand_rewrites = _expand_rewrite_coordinates(compiled, node)
        updated = _apply_result(
            node,
            result,
            incumbent,
            cache_hit=hit,
            mass_partition=compiled.graph.mass_partition,
            rewrite_coordinates=expand_rewrites,
            weight_anchor=next(iter(weight_anchors.values()), None),
        )
        if node.structural is StructuralDelta.EXPAND:
            assert incumbent is not None
            normalized_receipt["expand_declared"] = _expand_declared_payload(node)
            try:
                authored_expand_writes = expand_writes_receipt(
                    incumbent.frame,
                    updated.frame,
                    node,
                    normalized_receipt,
                    rewrite_coordinates=expand_rewrites,
                )
            except (TypeError, ValueError) as error:
                raise NodeRejected(
                    f"Node {node.id!r} expand_writes receipt rejected: {error}"
                ) from error
            if hit:
                try:
                    stored_expand_writes = _parse_expand_writes(
                        node, normalized_receipt.get("expand_writes")
                    )
                except ValueError as error:  # defended by cached-record validation
                    raise StoreCorrupt(
                        f"Cached EXPAND node {node.id!r} has malformed "
                        "expand_writes provenance."
                    ) from error
                stored_payload = {
                    f"{entity}.{column}": list(classes)
                    for (entity, column), classes in stored_expand_writes.items()
                }
                if stored_payload != authored_expand_writes:
                    raise StoreCorrupt(
                        f"Cached EXPAND node {node.id!r} expand_writes provenance "
                        "disagrees with its materialized frame."
                    )
            normalized_receipt["expand_writes"] = authored_expand_writes
        if node.structural not in {
            StructuralDelta.NONE,
            StructuralDelta.CREATE,
            StructuralDelta.REVISION,
        }:
            existing_mass = normalized_receipt.get("mass", {})
            if not isinstance(existing_mass, Mapping):  # defended by mass validation
                raise NodeRejected(
                    f"Node {node.id!r} receipt['mass'] is not a mapping."
                )
            try:
                authored_mass = mass_record_receipt(updated.mass_ledger[-1])
            except (TypeError, ValueError) as error:
                raise NodeRejected(
                    f"Node {node.id!r} mass receipt rejected: {error}"
                ) from error
            normalized_receipt["mass"] = {**existing_mass, **authored_mass}
        normalized_receipt.update(weight_cap_receipt(updated, node))
        normalized_receipt.update(
            _weight_anchor_receipt(compiled, node, updated, weight_anchors, keys)
        )
        cache_receipt = normalized_receipt
        run_receipt = dict(cache_receipt)
        if kernel.capabilities.role is KernelRole.RELEASE:
            run_receipt["outcome"] = _release_outcome(
                node, str(cache_receipt["tier"]), decisions
            )
        if node.structural is StructuralDelta.NONE:
            populations[compiled.versions[node_id]] = updated
        else:
            populations[node.id] = updated

        if not hit:
            manifest_artifacts, record = _write_node(
                store,
                node,
                key=key,
                kernel_impl_hash=implementation,
                capabilities=kernel.capabilities,
                result=result,
                population=updated,
                receipt=cache_receipt,
                opaque_artifacts=opaque,
                verify_existing=(resume != "forbid" and not replace_stale_record),
                typed_artifacts=typed,
            )

        assert record is not None
        raw_frame_key = record["frame_key"]
        receipt_frame_key = None if raw_frame_key is None else str(raw_frame_key)
        raw_weight = record["weight"]
        if raw_weight is None:
            receipt_weight_key = None
        elif isinstance(raw_weight, dict) and isinstance(raw_weight.get("key"), str):
            receipt_weight_key = raw_weight["key"]
        else:  # generated records cannot reach this branch
            raise StoreCorrupt(f"Node {node.id!r} weight identity is malformed.")
        raw_outcome_key = record.get("outcome_key")
        receipt_outcome_key = (
            str(raw_outcome_key) if raw_outcome_key is not None else None
        )
        receipt_opaque: dict[str, str] = {}
        for entry in _record_entries(record, "opaque"):
            name = entry.get("name")
            artifact_identity = entry.get("key")
            if not isinstance(name, str) or not isinstance(artifact_identity, str):
                raise StoreCorrupt(
                    f"Node {node.id!r} opaque artifact identity is malformed."
                )
            receipt_opaque[name] = artifact_identity

        receipts[node_id] = NodeReceipt(
            typed_artifacts=typed,
            key=key,
            hit=hit,
            seed=seed(key),
            kernel_ref=node.kernel,
            kernel_impl_hash=implementation,
            capabilities=kernel.capabilities,
            receipt=run_receipt,
            artifacts=MappingProxyType(dict(manifest_artifacts)),
            wall_time=time.perf_counter() - node_started,
            frame_key=receipt_frame_key,
            weight_key=receipt_weight_key,
            opaque_artifacts=MappingProxyType(receipt_opaque),
            outcome_key=receipt_outcome_key,
        )

    return RunManifest(
        country=compiled.graph.country,
        nodes=MappingProxyType(receipts),
        decisions=decisions,
        started_at=started_at,
        finished_at=_now(),
        host=socket.gethostname(),
        populations=MappingProxyType(
            {version: population.frame for version, population in populations.items()}
        ),
        mass_ledgers=MappingProxyType(
            {
                version: population.mass_ledger
                for version, population in populations.items()
            }
        ),
        graph_key=graph_key(compiled.graph),
        graph_source_receipts=graph_source_receipts,
        parameters=run_parameters,
        source_bindings=MappingProxyType(source_receipts),
        graph_json_key=graph_json_key,
        products=_graph_product_receipts(compiled, receipts),
    )
