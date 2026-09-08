"""Population-state operations retain values, lineage, products, and anchors."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from microcosm.frame import Frame, WeightKind, Weights
from microcosm.graph import (
    Capabilities,
    ContentStore,
    Determinism,
    Graph,
    KernelBase,
    KernelResult,
    Node,
    Owned,
    Population,
    Product,
    ProductKind,
    Slice,
    StructuralDelta,
    WeightTransition,
    compile_graph,
    graph_from_json,
    graph_to_json,
    run_graph,
)
from microcosm.graph.population import patch

spec = importlib.util.spec_from_file_location(
    "_state_toy", Path(__file__).with_name("_toy.py")
)
toy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = toy
spec.loader.exec_module(toy)


class ReviseIncome(KernelBase):
    ref = "state.revise-income@1"
    capabilities = Capabilities(
        Determinism.DETERMINISTIC, structural=StructuralDelta.REVISION
    )

    def run(self, context):
        table = context.tables["person"]
        ids = pd.Index(table.person_id, name="person_id")
        values = table.income.to_numpy() + float(context.params["increment"])
        return KernelResult(
            columns={
                ("person", "income"): pd.Series(values, index=ids, dtype="float64")
            }
        )


class Union(KernelBase):
    ref = "graph.union@1"
    capabilities = Capabilities(
        Determinism.DETERMINISTIC, structural=StructuralDelta.UNION
    )

    def run(self, context):
        assert not context.tables
        return KernelResult()


class AnchorCalibration(KernelBase):
    ref = "state.anchor-calibration@1"
    capabilities = Capabilities(
        Determinism.DETERMINISTIC, structural=StructuralDelta.REWEIGHT
    )

    def run(self, context):
        current = context.weights["household"]
        anchor = context.weight_anchors["pool.weights"]
        assert np.array_equal(current.values, anchor.values)
        return KernelResult(weights=Weights(current.values, WeightKind.CALIBRATED))


def test_successive_value_revisions_preserve_each_value_artifact(
    tmp_path: Path,
) -> None:
    first = Node(
        "revision.one",
        ReviseIncome.ref,
        inputs=(Slice("person", ("income",)),),
        outputs=(Owned("person", "income", "float64", rewrite=True),),
        params={"increment": 1.0},
        structural=StructuralDelta.REVISION,
        base="survey",
    )
    second = replace(first, id="revision.two", base=first.id, params={"increment": 2.0})
    graph = Graph("toy", (toy.SOURCE,), (toy.CREATE, first, second))
    compiled = compile_graph(graph)
    registry = toy.toy_registry()
    registry.register(ReviseIncome())
    store = ContentStore(tmp_path / "store")
    sources = toy.toy_sources(tmp_path)
    manifest = run_graph(
        compiled,
        sources=sources,
        store=store,
        kernels=registry,
    )

    source_key = manifest.nodes["survey"].artifacts[("person", "income")]
    first_key = manifest.nodes[first.id].artifacts[("person", "income")]
    second_key = manifest.nodes[second.id].artifacts[("person", "income")]
    original = store.load_column(source_key)
    after_first = store.load_column(first_key)
    after_second = store.load_column(second_key)
    assert np.array_equal(after_first.to_numpy(), original.to_numpy() + 1.0)
    assert np.array_equal(after_second.to_numpy(), original.to_numpy() + 3.0)
    assert manifest.nodes[first.id].frame_key is None
    assert manifest.nodes[second.id].frame_key is None
    assert compiled.owners[(second.id, "person", "income")] == second.id

    warm = run_graph(
        compiled,
        sources=sources,
        store=store,
        kernels=registry,
    )
    assert warm.nodes[first.id].hit and warm.nodes[second.id].hit


def test_nested_parameters_are_recursively_frozen_and_lossless() -> None:
    nested = {"solver": {"steps": [1, 2], "options": {"exact": True}}}
    node = replace(toy.CREATE, params=nested)
    nested["solver"]["steps"].append(3)
    assert node.params["solver"]["steps"] == (1, 2)
    with pytest.raises(TypeError):
        node.params["solver"]["new"] = "value"
    restored = graph_from_json(graph_to_json(Graph("toy", (toy.SOURCE,), (node,))))
    assert restored == Graph("toy", (toy.SOURCE,), (node,))


def test_products_reject_missing_and_incompatible_targets() -> None:
    missing = Graph(
        "toy",
        (toy.SOURCE,),
        (toy.CREATE,),
        products=(Product("missing", ProductKind.POPULATION, node="unknown"),),
    )
    with pytest.raises(ValueError, match="unknown node"):
        compile_graph(missing)
    wrong_artifact = Graph(
        "toy",
        (toy.SOURCE,),
        (toy.CREATE,),
        products=(
            Product(
                "model",
                ProductKind.ARTIFACT,
                node="survey",
                artifact="absent",
            ),
        ),
    )
    with pytest.raises(ValueError, match="undeclared artifact"):
        compile_graph(wrong_artifact)


def test_union_remaps_collisions_and_records_source_lineage(tmp_path: Path) -> None:
    asec = replace(toy.CREATE, id="asec")
    acs = replace(toy.CREATE, id="acs")
    union = Node(
        "combined",
        Union.ref,
        structural=StructuralDelta.UNION,
        bases=("asec", "acs"),
    )
    graph = Graph(
        "toy",
        (toy.SOURCE,),
        (union, acs, asec),
        products=(
            Product("combined.population", ProductKind.POPULATION, node="combined"),
        ),
    )
    compiled = compile_graph(graph)
    registry = toy.toy_registry()
    registry.register(Union())
    store = ContentStore(tmp_path / "store")
    manifest = run_graph(
        compiled,
        sources=toy.toy_sources(tmp_path),
        store=store,
        kernels=registry,
    )

    source = manifest.populations["asec"]
    combined = manifest.populations["combined"]
    assert combined.n("person") == 2 * source.n("person")
    assert combined.table("person").person_id.is_unique
    assert combined.table("household").household_id.is_unique
    assert compiled.product_nodes["combined.population"] == "combined"
    lineage_ref = manifest.nodes["combined"].receipt["union_lineage"]
    lineage = store.load_json(lineage_ref["key"], kind="union-lineage")
    assert len(lineage["person"]) == combined.n("person")
    assert {entry[1] for entry in lineage["person"]} == {"acs", "asec"}
    assert manifest.mass_ledgers["combined"][-1].operation == "union"


def test_named_weight_anchor_is_aligned_exposed_and_recorded(tmp_path: Path) -> None:
    calibration = Node(
        "calibrated",
        AnchorCalibration.ref,
        inputs=(
            Slice("person", ("age",)),
            Slice("household", ("household_size",)),
        ),
        params={"max_weight_ratio": 1.0},
        structural=StructuralDelta.REWEIGHT,
        base="pool",
        weights=WeightTransition("household", "calibrated", "conserve", "pool.weights"),
        mass="conserve",
    )
    graph = Graph(
        "toy",
        (toy.SOURCE,),
        (toy.CREATE, toy.POOL, calibration),
        products=(
            Product(
                "pool.weights",
                ProductKind.WEIGHTS,
                node="pool",
                entity="household",
            ),
            Product("final", ProductKind.POPULATION, node="calibrated"),
        ),
    )
    compiled = compile_graph(graph)
    registry = toy.toy_registry()
    registry.register(AnchorCalibration())
    manifest = run_graph(
        compiled,
        sources=toy.toy_sources(tmp_path),
        store=ContentStore(tmp_path / "store"),
        kernels=registry,
    )
    receipt = manifest.nodes["calibrated"].receipt["weight_anchor"]
    assert receipt["product"] == "pool.weights"
    assert receipt["producer"] == "pool"
    assert receipt["producer_key"] == manifest.nodes["pool"].key
    assert receipt["realized_max_weight_ratio"] == 1.0


def test_named_weight_anchor_controls_mass_comparison(tmp_path: Path) -> None:
    source = toy.read_toy_frame(toy.toy_sources(tmp_path)["survey"])
    source_weights = source.weights_for("household")
    incumbent = Frame(
        {entity: source.table(entity).copy() for entity in source.entities},
        source.schema,
        {"household": Weights(source_weights.values * 2.0, WeightKind.IMPORTANCE)},
        source.strata,
        metadata=source.metadata,
    )
    population = Population.from_frame(incumbent, "importance")
    node = Node(
        "calibrated",
        "test@1",
        structural=StructuralDelta.REWEIGHT,
        base="importance",
        weights=WeightTransition(
            "household", "calibrated", "conserve", "reviewed.weights"
        ),
        mass="conserve",
    )
    result = patch(
        population,
        node,
        KernelResult(weights=Weights(source_weights.values, WeightKind.CALIBRATED)),
        weight_anchor=source_weights,
    )
    record = result.mass_ledger[-1]
    assert np.isclose(record.before_total, record.after_total)
    assert np.isclose(record.before_total, float(source.stratum_mass().sum()))
