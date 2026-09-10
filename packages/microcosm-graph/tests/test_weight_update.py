"""Same-kind normalization remains explicit, aligned and replayable."""

import hashlib

import numpy as np
import pandas as pd
import pytest

from microcosm.frame import EntitySchema, Frame, MassChangeRecord, WeightKind, Weights
from microcosm.graph import (
    Capabilities,
    ContentStore,
    Determinism,
    Graph,
    KernelBase,
    KernelRegistry,
    KernelResult,
    Node,
    Numeric,
    Owned,
    Slice,
    SourceRef,
    StructuralDelta,
    WeightTransition,
    WeightUpdate,
    compile_graph,
    run_graph,
    weight_update_receipt,
)
from microcosm.graph.population import Population, PopulationError, patch
from microcosm.graph.serialize import graph_from_json, graph_to_json


def frame():
    return Frame(
        {
            "person": pd.DataFrame(
                {"person_id": [1, 2], "person_household_id": [10, 20]}
            ),
            "household": pd.DataFrame({"household_id": [10, 20], "value": [2.0, 3.0]}),
        },
        EntitySchema(group_entities=("household",)),
        {"household": Weights(np.array([2.0, 3.0]), WeightKind.DESIGN)},
        pd.Series(["a", "b"], name="stratum"),
        metadata={"time_period": "2024", "source": {"years": [2023, 2024]}},
        mass_log=(MassChangeRecord("household", 5.0, 5.0, 1.0, "source"),),
    )


def update_node():
    return Node(
        "normalize",
        "normalize@1",
        base="source",
        structural=StructuralDelta.REWEIGHT,
        inputs=(Slice("household", ("value",)),),
        mass="declared",
        weights=WeightUpdate("household", "design", "restore sampled mass"),
    )


def update_result(ids=(10, 20), after=10.0):
    return KernelResult(
        weights=Weights(np.array([4.0, 6.0]), WeightKind.DESIGN),
        receipt={
            "weight_update": weight_update_receipt(ids),
            "mass": {
                "policy": "declared",
                "before": 5.0,
                "after": after,
                "stratum_before": {"a": 2.0, "b": 3.0},
                "stratum_after": {"a": 4.0, "b": 6.0},
            },
        },
    )


def test_normalization_keeps_design_ancestry_and_refuses_misaligned_ids():
    original = Population.from_frame(frame(), "source")
    updated = patch(original, update_node(), update_result())
    np.testing.assert_array_equal(
        updated.frame.weights_for("household").values, [4.0, 6.0]
    )
    np.testing.assert_array_equal(updated.design_weights["household"], [2.0, 3.0])
    assert updated.mass_ledger[-1].after_total == 10.0
    assert updated.frame.weights_for("household").kind is WeightKind.DESIGN
    with pytest.raises(PopulationError, match="axis"):
        patch(original, update_node(), update_result((20, 10)))
    with pytest.raises(PopulationError, match="computed value"):
        patch(original, update_node(), update_result(after=11.0))


def test_forward_transition_and_same_kind_contracts_are_distinct():
    original = Population.from_frame(frame(), "source")
    ordinary = Node(
        "bad",
        "bad@1",
        base="source",
        structural=StructuralDelta.REWEIGHT,
        weights=WeightTransition("household", "design", "free"),
        mass="free",
    )
    with pytest.raises(PopulationError, match="forward"):
        patch(original, ordinary, update_result())
    mismatch = Node(
        "bad",
        "bad@1",
        base="source",
        structural=StructuralDelta.REWEIGHT,
        weights=WeightUpdate("household", "importance", "normalize"),
        mass="declared",
    )
    with pytest.raises(PopulationError, match="same kind"):
        patch(original, mismatch, update_result())


class Source(KernelBase):
    ref = "source@1"
    capabilities = Capabilities(
        Determinism.DETERMINISTIC,
        numeric=Numeric.BITWISE,
        structural=StructuralDelta.CREATE,
    )

    def implementation_hash(self):
        return hashlib.sha256(self.ref.encode()).hexdigest()

    def run(self, context):
        return KernelResult(frame=frame())


class Normalize(Source):
    ref = "normalize@1"
    capabilities = Capabilities(
        Determinism.DETERMINISTIC,
        numeric=Numeric.BITWISE,
        structural=StructuralDelta.REWEIGHT,
    )

    def run(self, context):
        assert context.frame_metadata["time_period"] == "2024"
        assert context.frame_column_order["household"] == ("household_id", "value")
        with pytest.raises(TypeError):
            context.frame_column_order["household"] = ()
        assert context.frame_mass_log[0].reason == "source"
        with pytest.raises(TypeError):
            context.frame_metadata["source"]["years"] = ()
        return update_result(tuple(context.tables["household"]["household_id"]))


def test_context_exposes_original_order_of_only_the_declared_columns():
    from microcosm.graph.executor import _project_context

    original = frame()
    household = original.table("household")
    household.insert(0, "secret", [100, 200])
    household.insert(0, "another", [3, 4])
    context = _project_context(
        Node(
            "reader",
            "reader@1",
            population="source",
            inputs=(Slice("household", ("value", "another")),),
        ),
        Population.from_frame(original, "source"),
        key="0" * 64,
        sources={},
        tolerances={},
        numerics={},
    )
    assert context.frame_column_order["household"] == (
        "another",
        "household_id",
        "value",
    )
    assert "secret" not in context.frame_column_order["household"]


def test_normalization_roundtrip_and_required_replay(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("value\n1\n")
    graph = Graph(
        "test",
        (SourceRef("source", "raw-bytes-v1"),),
        (
            Node(
                "source",
                "source@1",
                structural=StructuralDelta.CREATE,
                sources=("source",),
                outputs=(Owned("household", "value", "float64"),),
            ),
            update_node(),
        ),
    )
    assert graph_from_json(graph_to_json(graph)) == graph
    registry = KernelRegistry()
    registry.register(Source())
    registry.register(Normalize())
    store = ContentStore(tmp_path / "store")
    first = run_graph(
        compile_graph(graph), kernels=registry, store=store, sources={"source": source}
    )
    second = run_graph(
        compile_graph(graph),
        kernels=registry,
        store=store,
        sources={"source": source},
        resume="require",
    )
    assert all(receipt.hit for receipt in second.receipts.values())
    assert first.mass_ledger("normalize") == second.mass_ledger("normalize")
