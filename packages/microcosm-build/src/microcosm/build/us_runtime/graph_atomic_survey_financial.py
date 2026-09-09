"""Checked atomic survey geography plus current financial development output.

This twenty-node composition retains the raw allocation and the pre-financial
clone separately. It grants neither a budget successor nor PUF recipient or
release authority. Support bytes establish integrity, not publisher provenance.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from types import FunctionType, SimpleNamespace

from microcosm.fit import qrf_target
from microcosm.fit.graph_legacy_apply_matrix import LegacyQRFApplyMatrixKernel
from microcosm.fit.graph_legacy_train import LegacyQRFTrainKernel
from microcosm.graph import KernelResult, compile_graph, run_graph
from microcosm.graph import population as population_ops
from microcosm.graph.artifact_edges import typed_contracts
from microcosm.graph.executor import _all_node_keys, _source_paths_and_keys
from microcosm.graph.keys import _capabilities_projection
from microcosm.graph.population import Population
from microcosm.graph.serialize import graph_to_json

from . import graph_atomic_survey_population as atomic
from . import graph_current_survey_predictors as financial

values = financial.values
codec = financial.codec
survey = atomic.survey
reconstruction = atomic.reconstruction
require = values.require


@dataclass(frozen=True)
class AtomicSurveyFinancialRunValues:
    """Development output, retaining the independently admitted prefix values."""

    prefix: atomic.AtomicSurveyPopulationRunValues
    financial_population: Population
    manifest: object
    compiled: object
    store: object
    kernels: object
    sources: dict
    projection: bytes
    matrix: bytes


def _live():
    """Pure final fence over this composition and its existing owner closure."""
    result = dict(values.host.survey_budget._live())
    modules = (
        sys.modules[__name__],
        atomic,
        financial,
        values,
        codec,
        qrf_target,
        financial.qrf,
        financial.model_input,
        sys.modules[LegacyQRFTrainKernel.__module__],
        sys.modules[LegacyQRFApplyMatrixKernel.__module__],
    )
    for module in modules:
        for name, value in vars(module).items():
            if isinstance(value, FunctionType):
                result[module.__name__, name] = values.source._function_seal(value)
            elif isinstance(value, type) and value.__module__ == module.__name__:
                result[module.__name__, name] = value
                for method, function in vars(value).items():
                    if isinstance(function, (staticmethod, classmethod)):
                        function = function.__func__
                    if isinstance(function, property):
                        function = function.fget
                    if isinstance(function, FunctionType):
                        result[module.__name__, name, method] = (
                            values.source._function_seal(function)
                        )
    result["financial_contract"] = values.source._runtime_marker(
        (
            values.FEATURES,
            values.DEMOGRAPHIC_FEATURES,
            values.TARGETS,
            values.OUTPUTS,
            values.PROTOCOL,
            values.PHASE,
            values.SEED,
        )
    )
    return result


def _artifacts(manifest, compiled, store, kernels, keys, implementations):
    """Read only the declared outputs after binding their actual producer keys."""
    require(set(manifest.nodes) == set(compiled.order), "ATOMIC_NODE_ROSTER")
    loaded = {}
    for node_id in compiled.order:
        node, record = compiled.graph.node(node_id), manifest.node(node_id)
        kernel = kernels.get(node.kernel)
        require(
            record.key == keys[node_id]
            and record.kernel_ref == node.kernel
            and record.kernel_impl_hash == implementations[node_id]
            and _capabilities_projection(record.capabilities)
            == _capabilities_projection(kernel.capabilities)
            and record.typed_artifacts
            == typed_contracts(compiled, node, keys, kernels),
            "ATOMIC_ARTIFACT_PRODUCER",
        )
        require(
            set(record.opaque_artifacts) == {o.name for o in node.artifact_outputs},
            "ATOMIC_ARTIFACT_ROSTER",
        )
        for output in node.artifact_outputs:
            payload = store.load_bytes(record.opaque_artifacts[output.name])
            survey._final_artifact(
                manifest,
                store,
                node_id=node_id,
                name=output.name,
                type_=output.type,
                payload=payload,
                capabilities=kernel.capabilities,
            )
            loaded[node_id, output.name] = payload
    return loaded


def _model_receipts(nodes, donor, qualified, loaded, matrix_key):
    """Bind fitted checkpoints to the exact source-derived design-weight donor.

    The start-chain operation only resolves inputs and initializes RNG state;
    this verifier does not fit a second model. Pickles are decoded only after
    the caller has checked the actual store and typed graph producer closure.
    """
    fits = tuple(n for n in nodes if n.kernel == LegacyQRFTrainKernel.ref)
    first = fits[0]
    model_frame = codec.model_frame(
        SimpleNamespace(weights={"person": donor.frame.resolve_weights("person")}),
        first.inputs[0],
        donor.frame.person,
    )
    predictors = values.feature_columns(qualified.demographic_conditioning)
    model = financial.qrf.RegimeGatedQRF(
        seed=values.SEED,
        n_estimators=first.params["n_estimators"],
        zero_atol=0,
        max_samples_leaf=None,
    )
    before = qrf_target.LegacyQRFTrainingState.from_chain(
        model.start_chain(
            model_frame, list(predictors), list(values.TARGETS), weights="design"
        )
    )
    receipts, history = {}, []
    for i, fit in enumerate(fits):
        target = values.TARGETS[i]
        payload = loaded[fit.id, "model"]
        packet, after = codec.read_training(loaded[fit.id, "training_state"])
        require(
            len(packet["models"]) == i + 1
            and packet["models"][:i] == history
            and packet["models"][-1]["sha256"] == codec.sha(payload),
            "ATOMIC_TRAINING_HISTORY",
        )
        fitted = qrf_target.LegacyQRFTargetArtifact.from_trusted_bytes(
            payload, expected_sha256=packet["models"][-1]["sha256"]
        )
        require(
            fitted.training_state == before
            and fitted.next_training_state == after
            and fitted.donor_sha256
            == qrf_target._consumed_values_sha256(
                model_frame.person, (*predictors, *values.TARGETS[:i], target)
            ),
            "ATOMIC_TRAINING_DONOR",
        )
        history = [
            *history,
            {
                "target": target,
                "sha256": codec.sha(payload),
                "training_id": fitted.training_id,
            },
        ]
        require(packet["models"] == history, "ATOMIC_TRAINING_HISTORY")
        before = after
        receipts[fit.id] = {
            "phase": values.PHASE,
            "target": target,
            "training_id": fitted.training_id,
            "model_sha256": codec.sha(payload),
            "donor_rows": len(model_frame.person),
            "entity": "person",
            "weight_kind": "design",
            "regime": fitted.regime,
        }
        apply_id = f"{financial.APPLY_PREFIX}.{i:03d}"
        application = financial.decode_matrix_apply_state(
            loaded[apply_id, "apply_state"]
        )
        require(
            application["application"]["models"] == history,
            "ATOMIC_APPLY_MODEL_HISTORY",
        )
        receipts[apply_id] = {
            "phase": values.PHASE,
            "target": target,
            "recipient_rows": len(
                financial.model_input.decode_recipient_matrix(qualified.matrix).features
            ),
            "entity": "person",
            "model_sha256": codec.sha(payload),
            "raw_sha256": codec.sha(loaded[apply_id, "raw_draw"]),
            "regime": fitted.regime,
            "matrix_sha256": codec.sha(qualified.matrix),
            "matrix_producer_key": matrix_key,
        }
    return receipts


def run_atomic_survey_financial(
    source_dir,
    *,
    snapshot_root,
    store_root,
    fraction,
    seed,
    geography_config,
    demographic_conditioning=False,
    n_estimators=100,
    resume="auto",
    return_values=False,
):
    """Execute and verify all twenty nodes, including required cache replay."""
    require(type(return_values) is bool, "RETURN_VALUES_FLAG")
    values.feature_columns(demographic_conditioning)
    live = _live()
    config_bytes = values.host.survey_budget._config_payload(geography_config)
    require(config_bytes is not None, "ATOMIC_GEOGRAPHY_REQUIRED")
    prefix = atomic.run_atomic_survey_population(
        source_dir,
        snapshot_root=snapshot_root,
        store_root=store_root,
        fraction=fraction,
        seed=seed,
        geography_config=geography_config,
        resume=resume,
        return_values=True,
    )
    entry = prefix.preparation._checked()
    prefix_objects = (
        prefix.preparation,
        prefix.manifest,
        prefix.compiled,
        prefix.store,
        prefix.kernels,
        prefix.sources,
    )
    prefix_manifest_bytes = prefix.manifest.to_json_bytes()
    prefix_declaration = graph_to_json(prefix.compiled.graph)
    retained = {
        name: (
            getattr(prefix, name),
            reconstruction._population_stamp(getattr(prefix, name)),
        )
        for name in ("allocated_population", "geography_population", "clone_population")
    }
    qualified = values.qualify_current_survey_predictors(
        prefix.preparation,
        prefix.allocated_population,
        prefix.clone_population,
        demographic_conditioning=demographic_conditioning,
        geography_config=geography_config,
    )
    projection_bytes, matrix_bytes = qualified.projection, qualified.matrix
    geography = reconstruction.reconstruct_atomic_survey_geography(
        prefix.preparation, prefix.allocated_population, geography_config
    )
    pins, prefix_artifacts = {}, {}
    for node_id, record in prefix.manifest.nodes.items():
        for name, key in record.opaque_artifacts.items():
            prefix_artifacts[node_id, name] = prefix.store.load_bytes(key)
    for edge in financial.host.current_survey_host_edges():
        record = prefix.manifest.node(edge.producer)
        pins[edge.name] = {
            "producer_key": record.key,
            "artifact_key": record.opaque_artifacts[edge.artifact],
            "payload_sha256": codec.sha(prefix_artifacts[edge.producer, edge.artifact]),
        }
    nodes = financial.current_survey_predictor_nodes(
        qualified,
        prefix.clone_population.frame,
        host_pins=pins,
        n_estimators=n_estimators,
    )
    compiled = compile_graph(
        replace(prefix.compiled.graph, nodes=(*prefix.compiled.graph.nodes, *nodes))
    )
    require(
        len(prefix.compiled.order) == 10 and len(compiled.order) == 20,
        "ATOMIC_COMPILER_ROSTER",
    )
    declaration = graph_to_json(compiled.graph)
    kernels, store, sources = prefix.kernels, prefix.store, dict(prefix.sources)
    source_items = tuple(sorted(sources.items()))
    for cls in (
        financial.CurrentSurveyPredictorProjectionKernel,
        financial.CurrentSurveyPredictorDonorFilterKernel,
        financial.CurrentSurveyPredictorDonorColumnsKernel,
        financial.CurrentSurveyPredictorAttachKernel,
    ):
        kernels.register(
            cls(
                prefix.preparation,
                prefix.allocated_population,
                prefix.clone_population,
                host_pins=pins,
                n_estimators=n_estimators,
                demographic_conditioning=demographic_conditioning,
                geography_config=geography_config,
            )
        )
    kernels.register(LegacyQRFTrainKernel())
    kernels.register(LegacyQRFApplyMatrixKernel())
    _, source_keys = _source_paths_and_keys(compiled, sources, store)
    keys, implementations = _all_node_keys(compiled, kernels, source_keys)
    base_expected = {
        survey.CREATE_NODE: Population.from_frame(entry[2].frame, survey.CREATE_NODE),
        survey.ALLOCATION_NODE: prefix.allocated_population,
        **{s.node.id: s.population for s in geography.stages},
    }
    receipts = {
        **{n: r.receipt for n, r in prefix.manifest.nodes.items()},
        **{s.node.id: json.loads(s.receipt) for s in geography.stages},
    }
    cloned, clone_receipts = atomic._clone_expectations(
        geography, prefix.compiled.graph.nodes, compiled
    )
    base_expected.update(cloned)
    receipts.update(clone_receipts)
    donor_node = compiled.graph.node(financial.DONOR_NODE)
    donor = population_ops.patch(
        base_expected[survey.CREATE_NODE],
        donor_node,
        KernelResult(frame=qualified.donor_frame),
    )
    receipts[donor_node.id] = {
        "selection": "ASEC_native_whole_households",
        "fit_weight_kind": "design",
        "release_eligible": False,
    }
    columns_node = compiled.graph.node(financial.DONOR_COLUMNS_NODE)
    donor_columns = population_ops.patch(
        donor,
        columns_node,
        KernelResult(
            columns={
                ("person", c): qualified.donor_columns[c]
                for c in (
                    *values.feature_columns(demographic_conditioning),
                    *values.TARGETS,
                )
            }
        ),
    )
    receipts[financial.PROJECTION_NODE] = qualified.evidence
    receipts[columns_node.id] = qualified.evidence
    observed, observed_stamps = {}, {}

    def observe(node_id, population):
        require(node_id not in observed, "ATOMIC_OBSERVER_DUPLICATE")
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
    require(tuple(observed) == compiled.order, "ATOMIC_OBSERVER_ROSTER")
    loaded = _artifacts(manifest, compiled, store, kernels, keys, implementations)
    require(
        all(loaded[k] == v for k, v in prefix_artifacts.items()),
        "ATOMIC_PREFIX_ARTIFACTS",
    )
    require(
        loaded[financial.PROJECTION_NODE, "projection"] == projection_bytes
        and loaded[financial.PROJECTION_NODE, "matrix"] == matrix_bytes,
        "ATOMIC_SOURCE_ARTIFACTS",
    )
    raw = tuple(
        loaded[f"{financial.APPLY_PREFIX}.{i:03d}", "raw_draw"] for i in range(3)
    )
    applications = tuple(
        loaded[f"{financial.APPLY_PREFIX}.{i:03d}", "apply_state"] for i in range(3)
    )
    matrix_key = keys[financial.PROJECTION_NODE]
    drawn = financial.read_current_survey_draws(
        matrix_bytes,
        matrix_key,
        raw,
        applications,
        demographic_conditioning=demographic_conditioning,
    )
    receipts.update(
        _model_receipts(nodes, donor_columns, qualified, loaded, matrix_key)
    )
    receipts[financial.ATTACH_NODE] = {
        **qualified.evidence,
        "raw_sha256": [codec.sha(r) for r in raw],
        "all_output_cells_available": True,
        "ACS_financial_origin": "modeled",
        "paired_draws": "source_origin_join",
        "host_weights_changed": False,
    }
    expected, current = {}, {}
    for node_id in compiled.order:
        node, version = compiled.graph.node(node_id), compiled.versions[node_id]
        if node_id == donor_node.id:
            population = donor
        elif node_id == columns_node.id:
            population = donor_columns
        elif node_id == financial.ATTACH_NODE:
            population = population_ops.patch(
                current[version],
                node,
                KernelResult(
                    columns=values.complete_predictor_columns(
                        qualified, prefix.clone_population.frame, drawn
                    )
                ),
            )
        elif node_id == "geography.clone_gate":
            population = current[version]
        elif node_id in base_expected:
            population = base_expected[node_id]
        else:
            population = current[version]
        expected[node_id] = current[version] = population
        atomic.same_replayed_population(population, observed[node_id])
    expected_stamps = {
        n: reconstruction._population_stamp(p) for n, p in expected.items()
    }
    states = atomic._states(compiled, kernels, source_keys, expected, receipts)
    survey._check_node_states(manifest, states)
    result = AtomicSurveyFinancialRunValues(
        prefix,
        observed[financial.ATTACH_NODE],
        manifest,
        compiled,
        store,
        kernels,
        sources,
        projection_bytes,
        matrix_bytes,
    )
    # Implementation/source/store I/O precedes the last owner/support borrow.
    current_keys, current_implementations = _all_node_keys(
        compiled, kernels, source_keys
    )
    require(
        current_keys == keys and current_implementations == implementations,
        "ATOMIC_FINAL_IMPLEMENTATIONS",
    )
    financial.verify_materialized_current_survey_predictors(
        prefix.preparation,
        prefix.allocated_population,
        prefix.clone_population,
        population=result.financial_population,
        projection=projection_bytes,
        matrix=matrix_bytes,
        matrix_producer_key=matrix_key,
        raw_draws=raw,
        apply_states=applications,
        host_pins=pins,
        n_estimators=n_estimators,
        demographic_conditioning=demographic_conditioning,
        geography_config=geography_config,
    )
    values.source._pure_final(entry[2])
    require(
        values.source._ISSUED.get(id(prefix.preparation)) is entry
        and prefix.preparation.payload == entry[1]
        and prefix.geography_config is geography_config
        and values.host.survey_budget._config_payload(geography_config) == config_bytes
        and result.prefix is prefix
        and result.manifest is manifest
        and result.compiled is compiled
        and result.store is store
        and result.kernels is kernels
        and result.financial_population is observed[financial.ATTACH_NODE]
        and result.projection == projection_bytes
        and result.matrix == matrix_bytes
        and all(
            a is b
            for a, b in zip(
                (
                    prefix.preparation,
                    prefix.manifest,
                    prefix.compiled,
                    prefix.store,
                    prefix.kernels,
                    prefix.sources,
                ),
                prefix_objects,
                strict=True,
            )
        )
        and prefix.manifest.to_json_bytes() == prefix_manifest_bytes
        and graph_to_json(prefix.compiled.graph) == prefix_declaration
        and prefix.compiled == compile_graph(prefix.compiled.graph)
        and tuple(sorted(result.sources.items())) == source_items
        and tuple(sorted(prefix.sources.items())) == source_items
        and graph_to_json(compiled.graph) == declaration
        and compiled == compile_graph(compiled.graph)
        and _live() == live,
        "ATOMIC_FINAL_BINDINGS",
    )
    for name, (population, stamp) in retained.items():
        require(
            getattr(prefix, name) is population
            and reconstruction._population_stamp(population) == stamp,
            "ATOMIC_FINAL_PREFIX_MUTATION",
        )
    for version, population in (
        (survey.CREATE_NODE, base_expected[survey.CREATE_NODE]),
        (survey.ALLOCATION_NODE, prefix.geography_population),
        (atomic.clone.COMBINED_CLONE_NODE, prefix.clone_population),
    ):
        survey._same_frame(population.frame, prefix.manifest.population(version))
        require(
            population.mass_ledger == prefix.manifest.mass_ledger(version),
            "ATOMIC_FINAL_PREFIX_LEDGER",
        )
    for node_id, population in expected.items():
        require(
            reconstruction._population_stamp(population) == expected_stamps[node_id]
            and reconstruction._population_stamp(observed[node_id])
            == observed_stamps[node_id],
            "ATOMIC_FINAL_POPULATION_MUTATION",
        )
        atomic.same_replayed_population(population, observed[node_id])
    for version, population in current.items():
        survey._same_frame(population.frame, manifest.population(version))
        require(
            population.mass_ledger == manifest.mass_ledger(version),
            "ATOMIC_FINAL_LEDGER",
        )
    survey._check_node_states(manifest, states)
    return result if return_values else manifest
