"""Invented ordinary Frames exercise lazy snapshot publication and replay."""

from __future__ import annotations

import errno
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import microcosm.graph.attachments as attachments
import microcosm.graph.executor as executor
import microcosm.graph.store as store_module
from microcosm.frame import EntitySchema, Frame, WeightKind, Weights
from microcosm.graph import (
    Capabilities,
    ContentStore,
    Determinism,
    Graph,
    KernelRegistry,
    KernelResult,
    Node,
    Owned,
    Slice,
    SourceRef,
    StructuralDelta,
    WeightTransition,
    compile_graph,
    run_graph,
)
from microcosm.graph.manifest import NodeReceipt
from microcosm.graph.population import Population
from microcosm.graph.store import StoreCorrupt, StoreUnavailable


def _frame(offset=0):
    # Match the ordinary executor fixture's three persons, two households,
    # weights and strata. All values and lineage identifiers are invented.
    return Frame(
        {
            "person": pd.DataFrame(
                {
                    "person_id": [1, 2, 3],
                    "person_household_id": [10, 10, 20],
                    "age": np.array([10, 20, 30], dtype="int64") + offset,
                    "source_person_id": [101, 102, 103],
                }
            ),
            "household": pd.DataFrame(
                {"household_id": [10, 20], "source_household_id": [201, 202]}
            ),
        },
        EntitySchema(group_entities=("household",)),
        {"household": Weights(np.array([1.0, 2.0]), WeightKind.DESIGN)},
        pd.Series(["a", "a", "b"], name="stratum"),
        metadata={
            "source_manifest": {
                "source_arm": "invented-ordinary",
                "sources": ({"sha256": "a" * 64, "rows": 3},),
                "flags": frozenset({"ordinary", "metadata-v2"}),
                "nullable": None,
                "flag": True,
            },
            "signed_zero": -0.0,
        },
    )


class _Kernel:
    def __init__(self, ref, capabilities, compute):
        self.ref = ref
        self.capabilities = capabilities
        self.compute = compute
        self.calls = 0

    def implementation_hash(self):
        return hashlib.sha256(self.ref.encode()).hexdigest()

    def run(self, context):
        self.calls += 1
        return self.compute(context)


def _case(tmp_path):
    # This generated source follows test_graph_executor._source_path; it is
    # interpreted by the CREATE kernel and is never a repository resource.
    source = tmp_path / "ordinary-source"
    source.mkdir()
    (source / "value.txt").write_text("0", encoding="utf-8")

    def create(context):
        offset = int((context.sources["survey"] / "value.txt").read_text())
        return KernelResult(frame=_frame(offset))

    def derive(context):
        table = context.tables["person"]
        return KernelResult(
            columns={
                ("person", context.params["target"]): pd.Series(
                    table[context.params["source"]].to_numpy(dtype="float64") * 2,
                    index=pd.Index(table["person_id"], name="person_id"),
                )
            }
        )

    def reweight(context):
        return KernelResult(
            weights=Weights(
                context.weights["household"].values * 2, WeightKind.IMPORTANCE
            ),
            # Person mass is 1 + 1 + 2 before and 2 + 2 + 4 after.
            receipt={
                "mass": {
                    "policy": "free",
                    "before": 4.0,
                    "after": 8.0,
                    "stratum_before": {"a": 2.0, "b": 2.0},
                    "stratum_after": {"a": 4.0, "b": 4.0},
                }
            },
        )

    graph = Graph(
        "toy",
        (SourceRef("survey", "csv-tables"),),
        (
            Node(
                "survey",
                "snapshot.source@1",
                sources=("survey",),
                structural=StructuralDelta.CREATE,
                outputs=(
                    Owned("person", "age", "int64"),
                    Owned("person", "source_person_id", "int64"),
                    Owned("household", "source_household_id", "int64"),
                ),
            ),
            Node(
                "column_before",
                "snapshot.derive@1",
                population="survey",
                inputs=(Slice("person", ("age",)),),
                outputs=(Owned("person", "doubled", "float64"),),
                params={"source": "age", "target": "doubled"},
            ),
            Node(
                "pool",
                "snapshot.reweight@1",
                structural=StructuralDelta.REWEIGHT,
                base="survey",
                inputs=(
                    Slice("person", ("doubled",)),
                    Slice("household", ("source_household_id",)),
                ),
                weights=WeightTransition("household", "importance", mass="free"),
                mass="free",
            ),
            Node(
                "column_after",
                "snapshot.derive@1",
                population="pool",
                inputs=(Slice("person", ("doubled",)),),
                outputs=(Owned("person", "quadrupled", "float64"),),
                params={"source": "doubled", "target": "quadrupled"},
            ),
        ),
    )
    registry = KernelRegistry()
    for ref, structural, compute in (
        ("snapshot.source@1", StructuralDelta.CREATE, create),
        ("snapshot.derive@1", StructuralDelta.NONE, derive),
        ("snapshot.reweight@1", StructuralDelta.REWEIGHT, reweight),
    ):
        registry.register(
            _Kernel(
                ref,
                Capabilities(Determinism.DETERMINISTIC, structural=structural),
                compute,
            )
        )
    return compile_graph(graph), {"survey": source}, registry


def _assert_frame_equal(actual, expected):
    assert actual.metadata == expected.metadata
    assert store_module._encode_frame_metadata(
        actual.metadata
    ) == store_module._encode_frame_metadata(expected.metadata)
    assert actual.schema == expected.schema
    assert actual.mass_log == expected.mass_log
    pd.testing.assert_series_equal(actual.strata, expected.strata)
    for entity in expected.entities:
        pd.testing.assert_frame_equal(actual.table(entity), expected.table(entity))
    for entity in expected.weighted_entities:
        assert actual.weights_for(entity).kind is expected.weights_for(entity).kind
        assert (
            actual.weights_for(entity).values.tobytes()
            == expected.weights_for(entity).values.tobytes()
        )


def _assert_snapshots(manifest, eager, store):
    assert isinstance(manifest.populations, attachments._LazyPopulations)
    assert manifest.key == eager.key
    assert manifest.content_addressed == eager.content_addressed
    for version in ("survey", "pool"):
        reference = manifest.populations._references[version]
        # Both versions contain nonstructural columns, so structural reuse
        # cannot accidentally hide a broken snapshot publication header.
        assert reference.key != manifest.nodes[version].frame_key
        header = store.metadata(reference.key, kind="frame")
        encoded = json.loads(
            (store.object_path(reference.key) / "frame.json").read_text()
        )
        expected_hash = hashlib.sha256(
            store_module._canonical_json(encoded["metadata"])
        ).hexdigest()
        assert header["frame_metadata_sha256"] == expected_hash
        assert header["frame_format"] == store_module._FRAME_FORMAT
        assert header["node_key"] == manifest.nodes[version].key
        restored = store.load_frame(reference.key, node_key=reference.node_key)
        _assert_frame_equal(restored, eager.population(version))
        _assert_frame_equal(manifest.population(version), eager.population(version))
        assert manifest.mass_ledger(version) == eager.mass_ledger(version)
    pool = manifest.population("pool")
    assert pool.weights_for("household").kind is WeightKind.IMPORTANCE
    assert pool.person["source_person_id"].tolist() == [101, 102, 103]
    assert pool.table("household")["source_household_id"].tolist() == [201, 202]
    assert pool.person["quadrupled"].tolist() == [40.0, 80.0, 120.0]


def test_nonstructural_snapshots_publish_metadata_and_reload_with_eager_parity(
    tmp_path,
):
    compiled, sources, kernels = _case(tmp_path)
    eager = run_graph(
        compiled,
        sources=sources,
        kernels=kernels,
        store=ContentStore(tmp_path / "eager"),
        resume="forbid",
    )
    store = ContentStore(tmp_path / "lazy")
    lazy = run_graph(
        compiled,
        sources=sources,
        kernels=kernels,
        store=store,
        population_retention="lazy",
        resume="forbid",
    )
    _assert_snapshots(lazy, eager, store)


def test_required_replay_republishes_missing_auxiliary_snapshots_without_kernels(
    tmp_path,
):
    compiled, sources, kernels = _case(tmp_path)
    store = ContentStore(tmp_path / "store")
    eager = run_graph(compiled, sources=sources, kernels=kernels, store=store)
    calls = {ref: kernel.calls for ref, kernel in kernels.as_mapping().items()}
    for attempt in range(2):
        replay = run_graph(
            compiled,
            sources=sources,
            kernels=kernels,
            store=store,
            population_retention="lazy",
            resume="require",
        )
        assert all(node.hit for node in replay.nodes.values())
        assert calls == {
            ref: kernel.calls for ref, kernel in kernels.as_mapping().items()
        }
        _assert_snapshots(replay, eager, store)
        if attempt == 0:
            for reference in replay.populations._references.values():
                shutil.rmtree(store.object_path(reference.key))


def test_structural_collision_forces_reloadable_metadata_snapshot(tmp_path):
    compiled, sources, kernels = _case(tmp_path)
    create_only = compile_graph(
        Graph("toy", compiled.graph.sources, (compiled.graph.node("survey"),))
    )
    store = ContentStore(tmp_path / "store")
    eager = run_graph(create_only, sources=sources, kernels=kernels, store=store)
    receipt = eager.nodes["survey"]
    # Leave the structural Frame visible while removing only its node record.
    # The next auto run genuinely recomputes into a structural-key collision.
    shutil.rmtree(store.object_path(executor._cache_record_key(receipt.key)))
    lazy = run_graph(
        create_only,
        sources=sources,
        kernels=kernels,
        store=store,
        population_retention="lazy",
    )
    assert not lazy.nodes["survey"].hit
    reference = lazy.populations._references["survey"]
    assert reference.key != receipt.frame_key
    assert lazy.key == eager.key
    _assert_frame_equal(store.load_frame(reference.key), eager.population("survey"))
    _assert_frame_equal(lazy.population("survey"), eager.population("survey"))


def _snapshot_fixture():
    population = Population.from_frame(_frame(), "survey")
    structural = NodeReceipt(
        key="a" * 64,
        hit=False,
        seed=0,
        kernel_ref="snapshot.source@1",
        kernel_impl_hash="b" * 64,
        capabilities=Capabilities(
            Determinism.DETERMINISTIC, structural=StructuralDelta.CREATE
        ),
        frame_key="c" * 64,
    )
    return population, structural


def _damage_header(path, damage):
    header = json.loads(path.read_text())
    if damage == "missing":
        header.pop("frame_metadata_sha256")
    elif damage == "wrong":
        header["frame_metadata_sha256"] = "0" * 64
    elif damage == "old_codec":
        header["frame_format"] = "microcosm-graph-frame-v1"
    path.write_text(json.dumps(header), encoding="utf-8")


@pytest.mark.parametrize("damage", ["missing", "wrong", "old_codec"])
def test_existing_snapshot_rejects_invalid_metadata_header(tmp_path, damage):
    store = ContentStore(tmp_path / "store")
    population, structural = _snapshot_fixture()
    key, _ = attachments._snapshot(
        store, population, structural, (), verify_existing=True
    )
    header_path = store.object_path(key) / "meta.json"
    _damage_header(header_path, damage)
    damaged = header_path.read_bytes()
    expected = StoreUnavailable if damage == "old_codec" else StoreCorrupt
    with pytest.raises(expected):
        store.load_frame(key, node_key=structural.key)
    with pytest.raises(expected):
        attachments._snapshot(store, population, structural, (), verify_existing=True)
    assert header_path.read_bytes() == damaged


@pytest.mark.parametrize("damage", ["valid", "missing", "wrong", "old_codec"])
def test_atomic_publication_race_validates_incumbent_metadata(
    tmp_path, monkeypatch, damage
):
    store = ContentStore(tmp_path / "store")
    population, structural = _snapshot_fixture()
    baseline = ContentStore(tmp_path / "baseline")
    key, _ = attachments._snapshot(
        baseline, population, structural, (), verify_existing=True
    )
    destination = store.object_path(key)
    real_replace = store_module.os.replace
    collisions = []

    def competing_writer(source, target):
        if Path(target) == destination:
            # Publish a complete competing object after _put's initial
            # exists check, then force its actual EEXIST/ENOTEMPTY branch.
            assert not destination.exists()
            shutil.copytree(source, destination)
            _damage_header(destination / "meta.json", damage)
            collisions.append(destination)
            raise OSError(errno.ENOTEMPTY, "ordinary competing snapshot")
        return real_replace(source, target)

    monkeypatch.setattr(store_module.os, "replace", competing_writer)
    if damage == "valid":
        actual, _ = attachments._snapshot(
            store, population, structural, (), verify_existing=True
        )
        assert actual == key
        _assert_frame_equal(store.load_frame(key), population.frame)
    else:
        expected = StoreUnavailable if damage == "old_codec" else StoreCorrupt
        with pytest.raises(expected):
            attachments._snapshot(
                store, population, structural, (), verify_existing=True
            )
    assert collisions == [destination]
    assert not any(store.tmp.iterdir())


def test_lazy_reload_refuses_decoded_frame_replacement(tmp_path, monkeypatch):
    store = ContentStore(tmp_path / "store")
    population, structural = _snapshot_fixture()
    key, payload_hash = attachments._snapshot(
        store, population, structural, (), verify_existing=True
    )
    views = attachments._LazyPopulations(
        store,
        {
            "survey": attachments._StoredPopulation(
                key, structural.key, population.frame.metadata, payload_hash
            )
        },
    )
    # The validated header stays unchanged; the decoded Frame itself changes
    # after verification. The attachment must bind that actual decoded value.
    monkeypatch.setattr(store, "load_frame", lambda *args, **kwargs: _frame(offset=1))
    with pytest.raises(StoreCorrupt, match="decoded population attachment changed"):
        views["survey"]
    assert not views._cache
