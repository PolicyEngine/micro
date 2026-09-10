"""Actual full graph on synthetic target and engine-source adapters."""

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from test_uk_full_calibration_graph import preflight_payload
from test_uk_full_population_graph import Source, graph_and_registry
from test_uk_ladder_rowwise_clone import toy_ladder as toy_ladder

from microcosm.build.uk_runtime import full_targets, graph_targets, ledger_targets
from microcosm.build.uk_runtime.graph_build import (
    UKFullBuildConfig,
    register_uk_full_kernels,
    uk_full_graph,
)
from microcosm.build.uk_runtime.graph_calibration import UKGraphCalibrationConfig
from microcosm.build.uk_runtime.graph_terminal import FULL_GATE_REPORT_TYPE
from microcosm.build.uk_runtime.local_rowwise import UKRowwiseNationalRows
from microcosm.calibrate import TargetRegistry, TargetSpec
from microcosm.calibrate.artifacts import decode_problem
from microcosm.frame import Frame
from microcosm.graph import (
    ArtifactInput,
    ArtifactOutput,
    Capabilities,
    ContentStore,
    Determinism,
    Graph,
    KernelBase,
    KernelRegistry,
    KernelResult,
    Node,
    compile_graph,
    run_graph,
)


@pytest.fixture
def target_inputs(monkeypatch):
    national = TargetRegistry(
        [
            TargetSpec(
                name="country_households",
                entity="household",
                measure="test_ones",
                value=34.0,
                period=2026,
                family="fixture",
                source="fixture",
                metadata={"geography_level": "country", "geography_id": "UK"},
            ),
            TargetSpec(
                # Repeated names across periods must retain distinct metadata.
                name="country_households",
                entity="household",
                measure="test_ones",
                value=4.0,
                period=2025,
                family="fixture",
                source="fixture",
                filter="test_london",
                metadata={"geography_level": "region", "geography_id": "LONDON"},
            ),
        ],
        country="uk",
    )
    empty = TargetRegistry([], country="uk")
    monkeypatch.setattr(
        full_targets,
        "load_uk_full_target_inputs",
        lambda *args, **kwargs: {
            "national_registry": national,
            "band_edge_registry": national,
            "local_registry": empty,
            "artifact": SimpleNamespace(facts=()),
            "calibration_year": 2026,
            "measure_exclusions": {},
            "reviewed_unbound_higher_targets": {},
            "national_source_pin": {"fixture": True},
            "register_completeness": {"fixture": True},
            "ledger_provenance": {"fixture": True},
            "uk_ledger_compiled_registries": {2026: national},
            "uk_ledger_compiled_local_registries": {2026: empty},
        },
    )
    monkeypatch.setattr(
        graph_targets, "uk_ledger_households_total", lambda *args, **kwargs: 33.0
    )
    monkeypatch.setattr(
        graph_targets,
        "uk_ladder_household_uprating",
        lambda *args, **kwargs: {"applied": True},
    )

    def surface(registry, ladder, **kwargs):
        rows = []
        for grain, codes in (
            ("constituency", ladder.constituency_code),
            ("la", ladder.local_authority_code),
        ):
            for i, code in enumerate(codes):
                rows.append(
                    {
                        "area_type": grain,
                        "area_code": str(code),
                        "metric": "households",
                        "value": 3.0 if i < 2 else 10.0,
                        "target_name": f"{grain}/{code}/households",
                        "family": "census_households",
                        "period": 2026,
                        "source": "fixture",
                    }
                )
        return pd.DataFrame(rows), {"fixture": True}

    monkeypatch.setattr(ledger_targets, "uk_local_target_surface", surface)

    def measures(frame, national_registry, *, local_grains, **kwargs):
        tables = {e: frame.table(e).copy() for e in frame.entities}
        tables["household"]["test_ones"] = 1.0
        tables["household"]["test_london"] = (
            tables["household"]["region"] == "LONDON"
        ).astype(float)
        prepared = Frame(
            tables,
            frame.schema,
            {"household": frame.weights_for("household")},
            frame.strata,
            mass_log=frame.mass_log,
            metadata=frame.metadata,
        )
        return (
            prepared,
            lambda _: frame,
            UKRowwiseNationalRows(
                national_registry.to_target_set(), national_registry, ("fixture",)
            ),
            {
                g: pd.DataFrame(
                    {"households": np.ones(frame.n("household"))},
                    index=frame.table("household")["household_id"],
                )
                for g in local_grains
            },
            {"fixture": True},
        )

    monkeypatch.setattr(graph_targets, "resolve_uk_full_measures", measures)
    return {"national": national, "surface": surface, "measures": measures}


class Preflight(KernelBase):
    """Synthetic source verdict: tests below exercise numerical graph ownership."""

    ref = "uk.test.target-preflight@1"
    capabilities = Capabilities(Determinism.DETERMINISTIC)

    def run(self, context):
        selection = json.loads(context.artifacts["selection"].payload)["receipt"]
        return KernelResult(
            artifacts={"preflight": preflight_payload(selection=selection)}
        )


def build(
    tmp_path,
    ladder_path,
    levels,
    *,
    n_clones=1,
    seed=7,
    dataset_households=None,
    resume="auto",
    forbid_execution=False,
):
    primitive, _ = graph_and_registry(1)
    base = Graph(
        "uk",
        tuple(s for s in primitive.sources if s.name == "fixture"),
        (primitive.node("source"),),
    )
    config = UKFullBuildConfig(
        calibration_year=2026,
        time_period="2023",
        source_year=2023,
        n_clones=n_clones,
        geography_levels=levels,
        seed=seed,
        calibration=UKGraphCalibrationConfig(
            epochs=8, seed=seed, dataset_households=dataset_households
        ),
    )
    full = uk_full_graph(config, spine=base, spine_population="source")
    preflight = Node(
        "fixture.preflight",
        Preflight.ref,
        population="uk.full.pool",
        artifact_inputs=(
            ArtifactInput(
                "selection",
                "uk.full.target_selection",
                "selection",
                graph_targets.TARGET_SELECTION_TYPE,
            ),
        ),
        artifact_outputs=(ArtifactOutput("preflight", FULL_GATE_REPORT_TYPE),),
    )
    full = replace(
        full,
        graph=replace(
            full.graph,
            nodes=(
                *(
                    replace(
                        node,
                        artifact_inputs=(
                            *node.artifact_inputs,
                            ArtifactInput(
                                "preflight",
                                preflight.id,
                                "preflight",
                                FULL_GATE_REPORT_TYPE,
                            ),
                        ),
                    )
                    if node.id == full.calibration.dense_producer
                    else node
                    for node in full.graph.nodes
                ),
                preflight,
            ),
        ),
    )
    registry = KernelRegistry()
    registry.register(Source())
    registry.register(Preflight())
    register_uk_full_kernels(registry)
    if forbid_execution:
        for kernel in registry.as_mapping().values():
            kernel.run = lambda *args, **kwargs: pytest.fail(
                "cached full graph executed"
            )
    store = ContentStore(tmp_path / "store")
    manifest = run_graph(
        compile_graph(full.graph),
        sources={
            "fixture": ladder_path,
            "uk_ladder": ladder_path,
            "uk_ledger_facts": ladder_path,
        },
        store=store,
        kernels=registry,
        resume=resume,
    )
    problem = decode_problem(
        store.load_bytes(manifest.nodes["uk.full.problem"].opaque_artifacts["problem"])
    )
    return full, manifest, problem


@pytest.mark.requires_uk
def test_explicit_country_filter_runs_same_full_graph_without_local_constraints(
    target_inputs, toy_ladder, tmp_path
):
    _, path = toy_ladder
    full, manifest, problem = build(tmp_path, path, ("country",))
    assert problem.problem.names == ("country_households@2026",)
    assert {m["geography_level"] for m in problem.target_metadata} == {"country"}
    assert manifest.population(full.population).n("household") == 4
    assert len(problem.bindings["target_selection"]["excluded"]) > 0
    assert "uk.full.dense" in manifest.nodes
    assert "uk.full.locations" in manifest.nodes


def test_default_scope_contains_all_levels_and_never_depends_on_k_or_k_small():
    default = UKFullBuildConfig(calibration_year=2026)
    for config in (
        default,
        replace(default, n_clones=1),
        replace(
            default, calibration=replace(default.calibration, dataset_households=20)
        ),
    ):
        graph = uk_full_graph(config).graph
        assert graph.node("uk.full.target_selection").params["geography_levels"] is None


@pytest.mark.requires_uk
def test_default_all_has_direct_matrix_and_solver_parity_and_replays(
    target_inputs, toy_ladder, tmp_path
):
    from test_uk_full_population_graph import source_frame

    from microcosm.build.uk_runtime.full_problem import build_uk_full_local_problem
    from microcosm.build.uk_runtime.local_rowwise import (
        prepare_uk_full_solve,
        solve_uk_dense_reference,
    )
    from microcosm.build.uk_runtime.rowwise_dataset import (
        clone_uk_dataset_with_ladder_geography,
    )

    ladder, path = toy_ladder
    default, default_run, default_problem = build(
        tmp_path / "default", path, None, n_clones=10
    )
    explicit, explicit_run, explicit_problem = build(
        tmp_path / "explicit",
        path,
        ("country", "region", "constituency", "la"),
        n_clones=10,
    )
    assert {row["geography_level"] for row in default_problem.target_metadata} == {
        "country",
        "region",
        "constituency",
        "la",
    }
    assert default_problem.problem.n_targets == 12
    assert default_problem.problem.names == explicit_problem.problem.names
    np.testing.assert_array_equal(
        default_problem.problem.matrix.toarray(),
        explicit_problem.problem.matrix.toarray(),
    )
    np.testing.assert_array_equal(
        default_problem.problem.target_vector, explicit_problem.problem.target_vector
    )
    np.testing.assert_array_equal(
        default_run.population(default.population).weights_for("household").values,
        explicit_run.population(explicit.population).weights_for("household").values,
    )
    assert default_problem.bindings["target_selection"]["selector"]["explicit"] is False
    assert explicit_problem.bindings["target_selection"]["selector"]["explicit"] is True

    # Independently execute the maintained pre-graph numerical helpers on the
    # same original spine, legacy location draw, target rows and solver options.
    assignment = clone_uk_dataset_with_ladder_geography(
        source_frame(),
        ladder,
        n_clones=10,
        seed=7,
        source_year=2023,
        expected_constituency_vintage="2024_pcon",
    )
    prepared_frame, _, national_rows, metrics, _ = target_inputs["measures"](
        assignment.frame, target_inputs["national"], local_grains=("constituency", "la")
    )
    surface, cross = target_inputs["surface"](None, ladder)
    _, local, _, families, _ = build_uk_full_local_problem(
        SimpleNamespace(result=SimpleNamespace(frame=prepared_frame), ladder=ladder),
        target_ladder=ladder,
        local_registry=TargetRegistry([], country="uk"),
        national_registry=target_inputs["national"],
        local_metrics=metrics,
        period=2026,
        sample_fraction=1.0,
        reviewed_unbound_higher_targets={},
        selected_surface=surface,
        surface_receipt=cross,
    )
    prepared = prepare_uk_full_solve(
        prepared_frame,
        local,
        bound_families=families,
        national_rows=national_rows,
        target_weight_rule="uniform",
    )
    direct = solve_uk_dense_reference(prepared, epochs=8, seed=7)
    np.testing.assert_array_equal(
        default_problem.problem.matrix.toarray(), direct.problem.matrix.toarray()
    )
    np.testing.assert_array_equal(
        default_run.population(default.population).weights_for("household").values,
        direct.weights,
    )

    _, replay, _ = build(
        tmp_path / "default",
        path,
        None,
        n_clones=10,
        resume="require",
        forbid_execution=True,
    )
    assert all(receipt.hit for receipt in replay.nodes.values())
    np.testing.assert_array_equal(
        replay.population(default.population).weights_for("household").values,
        direct.weights,
    )


@pytest.mark.requires_uk
def test_unsupported_default_all_refuses_without_narrowing(
    target_inputs, toy_ladder, tmp_path
):
    from microcosm.graph.errors import NodeRejectedError

    _, path = toy_ladder
    # At K=1 London's only household cannot occupy both positive area cells.
    with pytest.raises(NodeRejectedError, match="[Ss]upport|unassigned|positive"):
        build(tmp_path / "all", path, None, n_clones=1)
    country, result, problem = build(
        tmp_path / "country", path, ("country",), n_clones=1
    )
    assert problem.problem.names == ("country_households@2026",)
    assert result.population(country.population).n("household") == 4


def test_local_surface_selection_keeps_exact_target_periods():
    rows = pd.DataFrame(
        {
            "target_name": ["same", "same", "different"],
            "period": [2025, 2026, 2026],
            "value": [2.0, 3.0, 4.0],
        }
    )
    selected = [
        TargetSpec(
            name="same",
            entity="household",
            measure="count",
            value=3.0,
            period=2026,
            source="fixture",
            family="fixture",
        )
    ]
    actual = graph_targets._selected_local_surface(rows, selected)
    assert actual.to_dict(orient="records") == [
        {"target_name": "same", "period": 2026, "value": 3.0}
    ]


@pytest.mark.requires_uk
def test_target_kernel_identity_binds_country_reference_resources(monkeypatch):
    kernel = graph_targets.UKFullProblemKernel()
    original = kernel.implementation_hash()
    monkeypatch.setattr(
        graph_targets,
        "load_country_spec",
        lambda _country: SimpleNamespace(fingerprint="changed-reference-resource"),
    )
    assert kernel.implementation_hash() != original
