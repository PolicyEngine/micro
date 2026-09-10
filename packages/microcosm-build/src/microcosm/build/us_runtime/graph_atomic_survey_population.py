"""Execute qualified survey geography before the first support clone.

The existing runner independently admits the raw allocation. This extension
reconstructs every added column from the live preparation and pinned normalized
support, then checks the complete graph populations on cold and warm execution.
Normalized support integrity does not establish its publisher provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from types import SimpleNamespace

import numpy as np

from microcosm.build import atomic_geography
from microcosm.build.graph_atomic_geography import (
    ATOMIC_SUPPORT_TYPE,
    AtomicSupportImportKernel,
    register_atomic_geography_kernels,
)
from microcosm.frame import US_SCHEMA
from microcosm.graph import (
    Graph,
    KernelResult,
    SourceRef,
    StructuralDelta,
    compile_graph,
    run_graph,
)
from microcosm.graph.artifact_edges import typed_contracts
from microcosm.graph.codecs import load_raw_bytes
from microcosm.graph.executor import (
    _all_node_keys,
    _expand_declared_payload,
    _expand_rewrite_coordinates,
    _input_writers,
    _source_paths_and_keys,
    _tolerance_writer_payload,
)
from microcosm.graph.keys import (
    _capabilities_projection,
    artifact_key,
    frame_key,
    opaque_artifact_key,
    weights_key,
)
from microcosm.graph.keys import seed as node_seed
from microcosm.graph.manifest import _freeze_json
from microcosm.graph.population import (
    Population,
    _mass_record,
    expand_lineage_receipt,
    expand_writes_receipt,
    mass_record_receipt,
    weight_cap_receipt,
)

from . import graph_combined_clone as clone
from . import graph_current_survey_geography as projection
from . import graph_survey_population as survey
from . import puf_support
from . import survey_atomic_geography as reconstruction
from .graph_sources import frame_column_declarations
from .survey_population_replay import same_replayed_population


@dataclass(frozen=True)
class AtomicSurveyPopulationRunValues:
    """Actual run values, without a new source or release certificate."""

    manifest: object
    preparation: object
    allocated_population: Population
    geography_population: Population
    clone_population: Population
    geography_config: reconstruction.AtomicSurveyReconstruction
    compiled: object
    store: object
    kernels: object
    sources: dict


def _clone_expectations(geography, nodes, compiled):
    """Independently reconstruct the complete clone, including inherited cells."""
    before = geography.population
    expanded = puf_support.clone_us_frame_for_puf_support(
        before.frame,
        clone_attachment_fraction=1.0,
        clone_attachment_seed=0,
    )
    design = survey._verify_cloned_frame(
        before.frame, expanded, before.design_weights["household"]
    )
    expand = next(n for n in nodes if n.structural is StructuralDelta.EXPAND)
    claim = next(n for n in nodes if n.id == clone.COMBINED_CLONE_CLAIM_NODE)
    gate = next(n for n in nodes if n.id == "geography.clone_gate")
    ledger = (
        *before.mass_ledger,
        _mass_record(before.frame, expanded, expand, KernelResult(), "conserve"),
    )
    owners = {
        (e, str(c)): expand.id for e in expanded.entities for c in expanded.table(e)
    }
    expected, receipts = {}, {}
    lineage, facts = {}, {}
    for entity in US_SCHEMA.entities:
        lineage[entity], facts[entity] = clone._entity_lineage(
            before.frame, expanded, entity
        )
    authority = puf_support.validate_puf_clone_attachment(
        expanded, boundary=survey.PHASE, expected_fraction=1.0, expected_seed=0
    )
    receipt = clone.USCombinedSurveyCloneExpandKernel._receipt(
        before.frame, expanded, ("acs", "asec"), authority, facts
    )
    receipt["expand"] = expand_lineage_receipt(lineage)
    receipt["expand_declared"] = _expand_declared_payload(expand)
    receipt["expand_writes"] = expand_writes_receipt(
        before.frame,
        expanded,
        expand,
        receipt,
        rewrite_coordinates=_expand_rewrite_coordinates(compiled, expand),
    )
    receipts[expand.id] = receipt
    receipts[claim.id] = {
        "phase": clone.COMBINED_CLONE_PHASE,
        "claimed_cells": sorted(f"{o.entity}.{o.column}" for o in claim.outputs),
    }
    definition = json.loads(geography.definition)
    system = definition["systems"][0]["id"]
    receipts[gate.id] = atomic_geography.validate_geography(
        expanded.table("household"),
        definition,
        {system: atomic_geography.decode_atomic_support(geography.support_payload)},
    )
    # The gate and the ownership claim can have either topological order.
    for node_id in compiled.order:
        if node_id not in receipts:
            continue
        if node_id == claim.id:
            owners.update({(o.entity, o.column): claim.id for o in claim.outputs})
        expected[node_id] = Population.from_frame(
            expanded,
            expand.id,
            owners=owners,
            mass_ledger=ledger,
            design_weights={"household": np.array(design, copy=True)},
        )
    return expected, receipts


def _states(compiled, kernels, source_keys, expected_populations, raw_receipts):
    """Bind independent domain receipts to current implementation and graph keys."""
    keys, implementations = _all_node_keys(compiled, kernels, source_keys)
    states, writer_receipts = {}, {}
    for node_id in compiled.order:
        node = compiled.graph.node(node_id)
        population = expected_populations[node_id]
        key = keys[node_id]
        structural = node.structural is not StructuralDelta.NONE
        cells = (
            tuple(
                (e, str(c))
                for e in population.frame.entities
                for c in population.frame.table(e)
            )
            if structural
            else tuple((o.entity, o.column) for o in node.outputs)
        )
        weight_entity = (
            node.weights.entity
            if node.weights is not None
            else node.params.get("expand_weight_entity")
            if node.structural is StructuralDelta.EXPAND
            else None
        )
        capabilities = _capabilities_projection(kernels.get(node.kernel).capabilities)
        receipt = dict(raw_receipts[node_id])
        receipt["capabilities"] = dict(capabilities)
        writers = _tolerance_writer_payload(
            _input_writers(compiled, node_id, receipts=writer_receipts)
        )
        if writers:
            receipt["capabilities"]["tolerance_writers"] = writers
        if structural and node.structural is not StructuralDelta.CREATE:
            receipt["mass"] = {
                **receipt.get("mass", {}),
                **mass_record_receipt(population.mass_ledger[-1]),
            }
        receipt.update(weight_cap_receipt(population, node))
        states[node_id] = {
            "key": key,
            "ref": node.kernel,
            "capabilities": capabilities,
            "implementation": implementations[node_id],
            "typed_artifacts": typed_contracts(compiled, node, keys, kernels),
            "seed": node_seed(key),
            "frame_key": frame_key(key) if structural else None,
            "weight_key": weights_key(key, weight_entity) if weight_entity else None,
            "artifacts": {(e, c): artifact_key(key, e, c) for e, c in cells},
            "opaque_artifacts": {
                o.name: opaque_artifact_key(key, o.name) for o in node.artifact_outputs
            },
            "receipt": _freeze_json(receipt),
        }
        writer_receipts[node_id] = SimpleNamespace(receipt=states[node_id]["receipt"])
    return states


def run_atomic_survey_population(
    source_dir,
    *,
    snapshot_root,
    store_root,
    fraction,
    seed,
    geography_config,
    resume="auto",
    return_values=False,
):
    """Build one block location before cloning and independently verify replay."""
    survey._require(type(return_values) is bool, "RETURN_VALUES_FLAG")
    prefix = survey.run_authenticated_survey_population(
        source_dir,
        snapshot_root=snapshot_root,
        store_root=store_root,
        fraction=fraction,
        seed=seed,
        resume=resume,
        clones=False,
        return_values=True,
    )
    source_owner = survey._source_owner()
    preparation_entry = prefix.preparation._checked()
    geography = reconstruction.reconstruct_atomic_survey_geography(
        prefix.preparation, prefix.allocated_population, geography_config
    )
    _, view = survey._checked_preparation(prefix.preparation)
    instructions = survey.allocation_instructions(
        view.selection_plan, view.receipt["origins"]["households"]
    )
    _, allocated_context, allocation_payload, _, _ = survey._allocation_output(
        view.frame, view.context, instructions, survey._sha(view.payload)
    )
    prefix_artifacts = {
        (survey.CREATE_NODE, "preparation"): view.payload,
        (survey.CREATE_NODE, "frame_context"): view.context,
        (survey.ALLOCATION_NODE, "allocation"): allocation_payload,
        (survey.ALLOCATION_NODE, "frame_context"): allocated_context,
    }
    clone_nodes = clone.us_combined_survey_clone_nodes(
        frame_column_declarations(geography.population.frame),
        base=survey.ALLOCATION_NODE,
        source_channels=("acs", "asec"),
    )
    gate = replace(
        geography.nodes[-1],
        id="geography.clone_gate",
        population=clone_nodes[0].id,
    )
    additions = (*geography.nodes, *clone_nodes, gate)
    compiled = compile_graph(
        Graph(
            "us",
            (
                *prefix.compiled.graph.sources,
                *(SourceRef(name, "raw-bytes-v1") for name, _ in geography.sources),
            ),
            (*prefix.compiled.graph.nodes, *additions),
        )
    )
    sources = {**prefix.sources, **dict(geography.sources)}
    kernels, store = prefix.kernels, prefix.store
    store.codecs.register_bytes("raw-bytes-v1", load_raw_bytes)
    kernels.register(projection.CurrentSurveyGeographyKernel(prefix.preparation))
    register_atomic_geography_kernels(kernels)
    clone.register_us_combined_survey_clone_kernels(kernels)
    expected = {
        survey.CREATE_NODE: Population.from_frame(
            prefix.manifest.population(survey.CREATE_NODE), survey.CREATE_NODE
        ),
        survey.ALLOCATION_NODE: prefix.allocated_population,
        **{stage.node.id: stage.population for stage in geography.stages},
    }
    receipts = {
        **{name: record.receipt for name, record in prefix.manifest.nodes.items()},
        **{stage.node.id: json.loads(stage.receipt) for stage in geography.stages},
    }
    cloned, clone_receipts = _clone_expectations(geography, additions, compiled)
    expected.update(cloned)
    receipts.update(clone_receipts)
    expected_stamps = {
        name: reconstruction._population_stamp(value)
        for name, value in expected.items()
    }
    raw_stamp = reconstruction._population_stamp(prefix.allocated_population)
    source_items = tuple(sorted(sources.items()))
    config_bytes = geography_config.to_bytes()
    _, source_keys = _source_paths_and_keys(compiled, sources, store)
    states = _states(compiled, kernels, source_keys, expected, receipts)
    observed, observed_stamps = {}, {}

    def observe(node_id, population):
        survey._require(node_id not in observed, "DUPLICATE_POPULATION_OBSERVATION")
        same_replayed_population(expected[node_id], population)
        observed[node_id] = population
        observed_stamps[node_id] = reconstruction._population_stamp(population)

    manifest = run_graph(
        compiled,
        sources=sources,
        store=store,
        kernels=kernels,
        resume=resume,
        _population_observer=observe,
    )
    survey._require(tuple(observed) == compiled.order, "POPULATION_OBSERVER_COVERAGE")
    survey._check_node_states(manifest, states)
    for node in geography.nodes:
        if node.kernel == AtomicSupportImportKernel.ref:
            survey._final_artifact(
                manifest,
                store,
                node_id=node.id,
                name="support",
                type_=ATOMIC_SUPPORT_TYPE,
                payload=geography.support_payload,
                capabilities=AtomicSupportImportKernel.capabilities,
            )
    # Validate prefix artifacts separately from column materialization.
    for (node_id, name), payload in prefix_artifacts.items():
        key = prefix.manifest.node(node_id).opaque_artifacts[name]
        survey._require(
            manifest.node(node_id).opaque_artifacts.get(name) == key,
            "ATOMIC_PREFIX_ARTIFACT_KEY",
        )
        survey._require(
            store.load_bytes(key) == payload, "ATOMIC_PREFIX_ARTIFACT_BYTES"
        )
    clone_terminal = next(
        name
        for name in reversed(compiled.order)
        if compiled.versions[name] == clone_nodes[0].id
    )
    result = AtomicSurveyPopulationRunValues(
        manifest,
        prefix.preparation,
        prefix.allocated_population,
        observed[geography.nodes[-1].id],
        observed[clone_terminal],
        geography_config,
        compiled,
        store,
        kernels,
        sources,
    )
    current_keys, current_implementations = _all_node_keys(
        compiled, kernels, source_keys
    )
    survey._require(
        current_keys == {name: value["key"] for name, value in states.items()}
        and current_implementations
        == {name: value["implementation"] for name, value in states.items()},
        "ATOMIC_FINAL_IMPLEMENTATIONS",
    )
    # Finish source/support I/O before final comparisons of returned objects.
    fresh = reconstruction.reconstruct_atomic_survey_geography(
        prefix.preparation, prefix.allocated_population, geography_config
    )
    survey._require(
        source_owner._ISSUED.get(id(prefix.preparation)) is preparation_entry
        and prefix.preparation.payload == preparation_entry[1],
        "ATOMIC_FINAL_PREPARATION",
    )
    source_owner._pure_final(preparation_entry[2])
    survey._require(
        fresh.config_sha256 == geography.config_sha256
        and fresh.projection_receipt == geography.projection_receipt
        and fresh.support_payload == geography.support_payload
        and fresh.definition == geography.definition
        and geography_config.to_bytes() == config_bytes
        and result.geography_config is geography_config
        and result.preparation is prefix.preparation
        and result.allocated_population is prefix.allocated_population
        and result.geography_population is observed[geography.nodes[-1].id]
        and result.clone_population is observed[clone_terminal]
        and result.manifest is manifest
        and result.compiled is compiled
        and result.store is store
        and result.kernels is kernels
        and tuple(sorted(result.sources.items())) == source_items
        and reconstruction._population_stamp(prefix.allocated_population) == raw_stamp,
        "ATOMIC_FINAL_RECONSTRUCTION",
    )
    same_replayed_population(fresh.population, result.geography_population)
    for node_id, population in expected.items():
        survey._require(
            reconstruction._population_stamp(population) == expected_stamps[node_id]
            and reconstruction._population_stamp(observed[node_id])
            == observed_stamps[node_id],
            "ATOMIC_FINAL_POPULATION_MUTATION",
        )
        same_replayed_population(population, observed[node_id])
    latest = {}
    for node_id in compiled.order:
        latest[compiled.versions[node_id]] = node_id
    for version, node_id in latest.items():
        survey._same_frame(expected[node_id].frame, manifest.population(version))
        survey._require(
            manifest.mass_ledger(version) == expected[node_id].mass_ledger,
            "ATOMIC_FINAL_MASS_LEDGER",
        )
    survey._check_node_states(manifest, states)
    return result if return_values else manifest
