"""Reconstruct the complete pre-clone geography Population from live sources.

The immutable recipe names normalized support bytes; their digest proves byte
integrity, not publisher provenance. A native source adapter must establish the
latter separately. This helper executes the maintained pure geography operators,
not graph kernels, and issues no source, Population, or release authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import asdict, dataclass, replace
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pandas as pd

from microcosm.build import atomic_geography as atomic
from microcosm.build import graph_atomic_geography as atomic_graph
from microcosm.frame import Frame, WeightKind, Weights
from microcosm.graph import Graph, KernelResult, Node, SourceRef, compile_graph
from microcosm.graph.canonical import canonical_json
from microcosm.graph.codecs import RAW_BYTES_MAX_BYTES
from microcosm.graph.population import Population, _mass_record, _storage_parts, patch

from . import atomic_block_support as blocks
from . import current_survey_geography as observed
from . import graph_current_survey_geography as observed_graph
from . import graph_survey_population as graph
from . import survey_population_preparation as source
from . import survey_population_replay as replay
from .graph_sources import frame_column_declarations

PROTOCOL = "microcosm.us.atomic-survey-reconstruction.v1"
MAX_SUPPORT_BYTES = RAW_BYTES_MAX_BYTES
MAX_SUPPORT_EXPANDED_BYTES = 2 * 1024**3
MAX_SUPPORT_MEMBERS = 32


def _require(condition, reason):
    if not condition:
        raise ValueError("ATOMIC_SURVEY_RECONSTRUCTION_" + reason)


def _sha(payload):
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class AtomicSurveyReconstruction:
    """Exact immutable inputs; construction itself authenticates no source."""

    support_path: str
    support_sha256: str
    source_ids: tuple[tuple[str, str], ...]
    seed: int

    def __post_init__(self):
        _config_bytes(self)

    def to_bytes(self):
        """Revalidate and detach the recipe, including the literal source path."""
        return _config_bytes(self)


def _config_bytes(config):
    _require(type(config) is AtomicSurveyReconstruction, "CONFIG_TYPE")
    _require(
        type(config.support_path) is str
        and 0 < len(config.support_path) <= 4096
        and "\0" not in config.support_path
        and Path(config.support_path).is_absolute()
        and ".." not in Path(config.support_path).parts,
        "SUPPORT_PATH",
    )
    _require(
        type(config.support_sha256) is str
        and re.fullmatch(r"[0-9a-f]{64}", config.support_sha256) is not None,
        "SUPPORT_DIGEST",
    )
    _require(
        type(config.source_ids) is tuple
        and len(config.source_ids) == 3
        and all(
            type(pair) is tuple
            and len(pair) == 2
            and all(type(value) is str for value in pair)
            and 0 < len(pair[1]) <= 4096
            and pair[1].strip() == pair[1]
            for pair in config.source_ids
        )
        and tuple(pair[0] for pair in config.source_ids)
        == ("district", "population", "puma"),
        "SOURCE_IDENTITIES",
    )
    _require(type(config.seed) is int and 0 <= config.seed < 2**63, "SEED")
    return canonical_json(
        {
            "protocol": PROTOCOL,
            "support_path": config.support_path,
            "support_sha256": config.support_sha256,
            "source_ids": dict(config.source_ids),
            "seed": config.seed,
        }
    )


def _file_identity(value):
    return tuple(
        getattr(value, name)
        for name in ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    )


def _read_support(config):
    """Read one bounded regular file and verify its exact pinned bytes."""
    descriptor = os.open(
        config.support_path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(
            stat.S_ISREG(before.st_mode) and 0 < before.st_size <= MAX_SUPPORT_BYTES,
            "SUPPORT_SIZE",
        )
        payload = stream.read(before.st_size + 1)
        after = os.fstat(stream.fileno())
    current = os.stat(config.support_path, follow_symlinks=False)
    _require(
        stat.S_ISREG(current.st_mode)
        and _file_identity(before) == _file_identity(after) == _file_identity(current)
        and len(payload) == before.st_size
        and _sha(payload) == config.support_sha256,
        "SUPPORT_CHANGED",
    )
    return payload, _file_identity(current)


def _decode_support(payload):
    # Bound declared decompressed bytes before numpy opens any array. The shared
    # decoder still owns every schema, value, mapping and sampling-weight check.
    with ZipFile(BytesIO(payload)) as archive:
        members = archive.infolist()
        _require(
            0 < len(members) <= MAX_SUPPORT_MEMBERS
            and sum(member.file_size for member in members)
            <= MAX_SUPPORT_EXPANDED_BYTES,
            "SUPPORT_EXPANDED_SIZE",
        )
        for member in members:
            with archive.open(member) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    shape, _fortran, dtype = np.lib.format.read_array_header_1_0(stream)
                elif version == (2, 0):
                    shape, _fortran, dtype = np.lib.format.read_array_header_2_0(stream)
                else:
                    raise ValueError("ATOMIC_SURVEY_RECONSTRUCTION_SUPPORT_NPY_VERSION")
                # A small ZIP member must not claim a huge allocation in its
                # NPY header. Validate the physical payload length before load.
                _require(
                    not dtype.hasobject
                    and all(type(size) is int and size >= 0 for size in shape)
                    and math.prod(shape) * dtype.itemsize
                    == member.file_size - stream.tell(),
                    "SUPPORT_ARRAY_SIZE",
                )
    return atomic.decode_atomic_support(payload)


def _copy_population(population):
    frame = population.frame
    return replace(
        population,
        frame=Frame(
            {entity: frame.table(entity).copy(deep=True) for entity in frame.entities},
            frame.schema,
            {
                entity: Weights(
                    frame.weights_for(entity).values.copy(),
                    frame.weights_for(entity).kind,
                )
                for entity in frame.weighted_entities
            },
            frame.strata.copy(deep=True),
            # Frame recursively freezes fresh metadata containers. The admitted
            # mass records contain scalars and immutable tuples; replacing each
            # record avoids deepcopy's reflective dataclass class-cache writes.
            metadata=frame.metadata,
            mass_log=tuple(replace(record) for record in frame.mass_log),
        ),
        owners=dict(population.owners),
        weight_kind=dict(population.weight_kind),
        design_weights={
            name: values.copy() for name, values in population.design_weights.items()
        },
        mass_ledger=tuple(replace(record) for record in population.mass_ledger),
    )


def _population_stamp(population):
    """Pure in-process seal, including storage beneath nullable masks."""
    _require(type(population) is Population, "POPULATION_TYPE")
    digest = hashlib.sha256()
    frame = population.frame
    digest.update(
        canonical_json(
            {
                "frame": source._frame_identity(frame),
                "version": population.version,
                "owners": sorted(population.owners.items()),
                "weight_kind": list(population.weight_kind.items()),
                "mass_ledger": [asdict(record) for record in population.mass_ledger],
            }
        )
    )
    for series in (
        *(
            frame.table(entity)[column]
            for entity in frame.entities
            for column in frame.table(entity)
        ),
        frame.strata,
    ):
        for part in _storage_parts(series, np.ones(len(series), dtype=np.bool_)):
            digest.update(len(part).to_bytes(8, "little"))
            digest.update(part)
    for entity, values in population.design_weights.items():
        digest.update(canonical_json((entity, str(values.dtype), values.shape)))
        digest.update(values.tobytes())
    return digest.hexdigest()


def _raw_allocation(view, population):
    """Reconstruct the original allocation, retaining all existing checks."""
    _require(type(population) is Population, "RAW_POPULATION_TYPE")
    instructions = graph.allocation_instructions(
        view.selection_plan, view.receipt["origins"]["households"]
    )
    _weights, _context, _allocation, receipt, expected = graph._allocation_output(
        view.frame, view.context, instructions, _sha(view.payload)
    )
    columns = frame_column_declarations(view.frame)
    nodes = graph.survey_population_nodes(
        columns,
        preparation_sha256=_sha(view.payload),
        fraction=view.selection_plan.fraction,
        seed=view.selection_plan.seed,
    )
    graph._same_frame(expected, population.frame)
    replay.same_replayed_frame(expected, population.frame)
    design = view.frame.weights_for("household").values
    graph._check_design_anchors(population, design)
    cells = (
        (entity, str(column))
        for entity in view.frame.entities
        for column in view.frame.table(entity)
    )
    ledger = (
        _mass_record(
            view.frame, expected, nodes[1], KernelResult(receipt=receipt), "declared"
        ),
    )
    graph._check_population_state(
        population,
        version=graph.ALLOCATION_NODE,
        owners=dict.fromkeys(cells, graph.ALLOCATION_NODE),
        kind=WeightKind.IMPORTANCE,
        ledger=ledger,
    )
    return columns, nodes


@dataclass(frozen=True, slots=True)
class AtomicSurveyGeographyStage:
    """Expected complete Population and pure receipt, never executor evidence."""

    node: Node
    population: Population
    receipt: bytes
    artifacts: tuple[tuple[str, bytes], ...] = ()


@dataclass(frozen=True, slots=True)
class AtomicSurveyGeographyReconstruction:
    """Detached reconstruction values; consumers must independently requalify."""

    population: Population
    stages: tuple[AtomicSurveyGeographyStage, ...]
    nodes: tuple[Node, ...]
    definition: bytes
    projection_receipt: bytes
    support_payload: bytes
    sources: tuple[tuple[str, str], ...]
    config_sha256: str
    receipt: bytes


def reconstruct_atomic_survey_geography(preparation, allocated_population, config):
    """Qualify sources and reconstruct geography on the exact raw allocation.

    Stage values follow the actual compiled order of the source/allocation plus
    geography graph. A support import may precede the observed-column projection.
    Callers compare these complete expected Populations to executor observations
    on cold and required-warm runs; these values do not replace those checks.
    """
    config_bytes = _config_bytes(config)
    _require(
        type(preparation) is source.AuthenticatedSurveyPopulationPreparation,
        "PREPARATION_TYPE",
    )
    entry = preparation._checked()
    payload, state = entry[1], entry[2]
    view = source.CheckedSurveyPopulationView(
        payload, state.context, state.frame, state.plan, json.loads(payload)
    )
    columns, source_nodes = _raw_allocation(view, allocated_population)
    original_stamp = _population_stamp(allocated_population)
    current = _copy_population(allocated_population)
    support_payload, support_identity = _read_support(config)
    support = _decode_support(support_payload)
    supports = {blocks.SYSTEM: support}
    definition = blocks.assignment_definition(
        identity=(observed.COLUMNS[0],),
        state_column=observed.COLUMNS[1],
        puma_column=observed.COLUMNS[2],
        source_ids=dict(config.source_ids),
        seed=config.seed,
    )
    definition_bytes = canonical_json(definition)
    projection = observed.qualify_current_survey_geography(preparation)
    projection_receipt = projection.receipt
    observed_graph._check_projection(
        observed, projection, payload=payload, receipt_sha256=_sha(projection_receipt)
    )
    _require(
        projection.household.index.tolist()
        == current.frame.table("household").household_id.tolist(),
        "PROJECTION_ORDER",
    )
    observation = observed_graph.current_survey_geography_node(
        preparation_sha256=_sha(payload),
        projection_receipt_sha256=_sha(projection_receipt),
        population=graph.ALLOCATION_NODE,
    )
    geography = atomic_graph.atomic_geography_nodes(
        definition, (*columns, *observation.outputs), base=graph.ALLOCATION_NODE
    )
    nodes = (observation, *geography)
    compiled = compile_graph(
        Graph(
            "us",
            (
                SourceRef(graph.SOURCE_NAME, graph.SOURCE_CODEC),
                SourceRef(blocks.SOURCE, "raw-bytes-v1"),
            ),
            (*source_nodes, *nodes),
        )
    )
    wanted = {node.id for node in nodes}
    ordered = tuple(
        compiled.graph.node(name) for name in compiled.order if name in wanted
    )
    stages = []
    for node in ordered:
        values, artifacts = {}, ()
        if node.id == observation.id:
            values = {
                ("household", name): projection.household[name].copy(deep=True)
                for name in observed.COLUMNS
            }
            receipt = {
                "phase": observed_graph.PHASE,
                "preparation_sha256": _sha(payload),
                "projection_receipt_sha256": _sha(projection_receipt),
                "source_projection": json.loads(projection_receipt),
                "population_admission_issued": False,
                "release_eligible": False,
            }
        elif node.kernel == atomic_graph.AtomicSupportImportKernel.ref:
            _require(
                support.metadata["system"] == node.params["system"], "SUPPORT_SYSTEM"
            )
            artifacts = (("support", support_payload),)
            receipt = {
                "support_sha256": support.sha256,
                "areas": len(support.arrays["area"]),
                "metadata": support.metadata,
            }
        else:
            households = current.frame.table("household")
            if node.kernel == atomic_graph.AtomicAssignKernel.ref:
                output = atomic.assign_atomic(households, definition, supports)
                receipt = {
                    "scope": "atomic_area_assignment",
                    "households": len(output),
                    "support_sha256": {
                        name: value.sha256 for name, value in supports.items()
                    },
                }
            elif node.kernel == atomic_graph.AtomicDeriveKernel.ref:
                output = atomic.derive_geography(households, definition, supports)
                receipt = {
                    "scope": "atomic_area_functional_lookup",
                    "layers": {
                        system["id"]: system["layers"]
                        for system in definition["systems"]
                    },
                }
            else:
                _require(
                    node.kernel == atomic_graph.AtomicGeographyGateKernel.ref,
                    "STAGE_ROSTER",
                )
                output = None
                receipt = atomic.validate_geography(households, definition, supports)
            if output is not None:
                ids = pd.Index(households.household_id.to_numpy(), name="household_id")
                values = {
                    ("household", name): pd.Series(output[name].array.copy(), index=ids)
                    for name in output
                }
        current = _copy_population(patch(current, node, KernelResult(columns=values)))
        stages.append(
            AtomicSurveyGeographyStage(
                node, current, canonical_json(receipt), artifacts
            )
        )
    stage_tuple = tuple(stages)
    receipt = canonical_json(
        {
            "protocol": PROTOCOL,
            "config_sha256": _sha(config_bytes),
            "preparation_sha256": _sha(payload),
            "projection_receipt_sha256": _sha(projection_receipt),
            "support_sha256": _sha(support_payload),
            "definition_sha256": _sha(definition_bytes),
            "stages": [stage.node.id for stage in stage_tuple],
            "frame_sha256": source._frame_identity(current.frame),
            "population_sha256": _population_stamp(current),
            "publisher_provenance_established": False,
            "source_admission_issued": False,
            "population_admission_issued": False,
            "release_eligible": False,
        }
    )
    result = AtomicSurveyGeographyReconstruction(
        population=_copy_population(current),
        stages=stage_tuple,
        nodes=nodes,
        definition=definition_bytes,
        projection_receipt=projection_receipt,
        support_payload=support_payload,
        sources=((blocks.SOURCE, config.support_path),),
        config_sha256=_sha(config_bytes),
        receipt=receipt,
    )
    result_stamps = tuple(
        _population_stamp(stage.population) for stage in result.stages
    )
    stage_values = tuple(
        (stage.node, stage.receipt, stage.artifacts) for stage in result.stages
    )
    final_stamp = _population_stamp(result.population)
    # Finish support and source-owner I/O before pure rechecks of every retained
    # input and every detached expected Population. No callback is an authority.
    _require(
        _read_support(config) == (support_payload, support_identity), "FINAL_SUPPORT"
    )
    final_entry = preparation._checked()
    support_after = os.stat(config.support_path, follow_symlinks=False)
    _require(
        final_entry is entry
        and source._ISSUED.get(id(preparation)) is entry
        and preparation.payload == payload
        and _config_bytes(config) == config_bytes,
        "FINAL_ISSUANCE",
    )
    _require(
        stat.S_ISREG(support_after.st_mode)
        and _file_identity(support_after) == support_identity,
        "FINAL_SUPPORT_STAT",
    )
    source._pure_final(state)
    _raw_allocation(view, allocated_population)
    _require(
        _population_stamp(allocated_population) == original_stamp
        and tuple(_population_stamp(stage.population) for stage in result.stages)
        == result_stamps
        and _population_stamp(result.population) == final_stamp,
        "FINAL_POPULATIONS",
    )
    observed_graph._check_projection(
        observed, projection, payload=payload, receipt_sha256=_sha(projection_receipt)
    )
    _require(
        result.nodes == nodes
        and tuple(stage.node for stage in result.stages) == ordered
        and tuple(
            (stage.node, stage.receipt, stage.artifacts) for stage in result.stages
        )
        == stage_values
        and result.definition == definition_bytes
        and result.projection_receipt == projection_receipt
        and result.support_payload == support_payload
        and result.sources == ((blocks.SOURCE, config.support_path),)
        and result.config_sha256 == _sha(config_bytes)
        and result.receipt == receipt,
        "FINAL_RESULT",
    )
    return result
