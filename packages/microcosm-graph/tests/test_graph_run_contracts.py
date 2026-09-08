"""Verified source bindings and run-level validation behavior."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pandas as pd
import pytest

from microcosm.graph import (
    Capabilities,
    ContentStore,
    Determinism,
    ExpectedContent,
    Graph,
    GraphSourceReceipt,
    KernelBase,
    KernelResult,
    LoadedGraphSource,
    Node,
    Owned,
    Product,
    ProductKind,
    RunManifest,
    Slice,
    SourceRef,
    StructuralDelta,
    compile_graph,
    graph_document_to_json,
    run_graph,
)
from microcosm.graph.codecs import SourceCodecRegistry, load_csv_tables, load_source
from microcosm.graph.store import StoreUnavailable

spec = importlib.util.spec_from_file_location(
    "_run_contract_toy", Path(__file__).with_name("_toy.py")
)
toy = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = toy
spec.loader.exec_module(toy)


class WrongCodec(KernelBase):
    ref = "source.wrong-codec@1"
    capabilities = Capabilities(
        Determinism.DETERMINISTIC, structural=StructuralDelta.CREATE
    )

    def run(self, context):
        return KernelResult(frame=load_source("frame-store", context.sources["survey"]))


class RecordAdvisory(KernelBase):
    ref = "test.record-advisory@1"
    capabilities = Capabilities(Determinism.DETERMINISTIC)

    def run(self, context):
        table = context.tables["release"]
        assert table["gate_verdict"].iloc[0] == "fail"
        ids = pd.Index(table["release_id"], name="release_id")
        return KernelResult(
            columns={
                ("release", "advisory_seen"): pd.Series(
                    [True], index=ids, dtype="boolean"
                )
            }
        )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_expected_source_identity_is_verified_and_recorded(tmp_path: Path) -> None:
    sources = toy.toy_sources(tmp_path)
    member = sources["survey"] / "person.csv"
    source = SourceRef(
        "survey",
        "csv-tables",
        content_type="application/vnd.microcosm.frame-source",
        access="public",
        expected=(
            ExpectedContent(
                _sha256(member),
                boundary="member",
                path="person.csv",
                size=member.stat().st_size,
                identity_ref="chronicle://census/example/2023/person.csv",
            ),
        ),
    )
    manifest = run_graph(
        compile_graph(Graph("toy", (source,), (toy.CREATE,))),
        sources=sources,
        store=ContentStore(tmp_path / "store"),
        kernels=toy.toy_registry(),
    )

    binding = manifest.source_bindings["survey"]
    assert binding["codec"] == "csv-tables"
    assert binding["content_type"] == "application/vnd.microcosm.frame-source"
    assert binding["access"] == "public"
    assert binding["expected"][0]["matched"] is True
    assert binding["expected"][0]["calculated_sha256"] == _sha256(member)
    assert len(binding["codec_impl_hash"]) == 64
    assert manifest.graph_key
    assert json.loads(manifest.to_json())["schema_version"] == 4
    assert RunManifest.from_json(manifest.to_json()).graph_key == manifest.graph_key


def test_manifest_binds_yaml_parameters_and_optional_graph_json(
    tmp_path: Path,
) -> None:
    graph = Graph("toy", (toy.SOURCE,), (toy.CREATE,))
    loaded = LoadedGraphSource(
        graph=graph,
        schema_version=1,
        parameters=MappingProxyType({"period": 2024}),
        receipts=(GraphSourceReceipt("graph.yaml", "a" * 64),),
    )
    graph_json = graph_document_to_json(graph)
    store = ContentStore(tmp_path / "store")
    manifest = run_graph(
        compile_graph(graph),
        sources=toy.toy_sources(tmp_path),
        store=store,
        kernels=toy.toy_registry(),
        graph_source=loaded,
        graph_json=graph_json,
    )

    assert manifest.graph_source_receipts == (
        {"path": "graph.yaml", "sha256": "a" * 64},
    )
    assert manifest.parameters == {"period": 2024}
    assert manifest.graph_json_key is not None
    assert store.load_bytes(manifest.graph_json_key) == graph_json.encode()

    mismatched = replace(loaded, graph=replace(graph, country="other"))
    with pytest.raises(ValueError, match="does not describe"):
        run_graph(
            compile_graph(graph),
            sources=toy.toy_sources(tmp_path, name="other-source"),
            store=store,
            kernels=toy.toy_registry(),
            graph_source=mismatched,
        )


def test_source_identity_mismatch_prevents_kernel_execution(tmp_path: Path) -> None:
    registry = toy.toy_registry()
    source_kernel = registry.get(toy.CREATE.kernel)
    source = replace(
        toy.SOURCE,
        expected=(ExpectedContent("0" * 64, boundary="member", path="person.csv"),),
    )
    with pytest.raises(StoreUnavailable, match="content identity mismatch"):
        run_graph(
            compile_graph(Graph("toy", (source,), (toy.CREATE,))),
            sources=toy.toy_sources(tmp_path),
            store=ContentStore(tmp_path / "store"),
            kernels=registry,
        )
    assert source_kernel.calls == 0


def test_codec_name_and_implementation_change_consuming_identity(
    tmp_path: Path,
) -> None:
    sources = toy.toy_sources(tmp_path)
    first_codecs = SourceCodecRegistry()
    first_codecs.register("csv-copy", load_csv_tables, implementation_hash="1" * 64)
    second_codecs = SourceCodecRegistry()
    second_codecs.register("csv-copy", load_csv_tables, implementation_hash="2" * 64)
    changed_name = SourceCodecRegistry()
    changed_name.register("csv-other", load_csv_tables, implementation_hash="1" * 64)

    def execute(codec: str, codecs: SourceCodecRegistry, suffix: str) -> str:
        graph = Graph("toy", (SourceRef("survey", codec),), (toy.CREATE,))
        return (
            run_graph(
                compile_graph(graph),
                sources=sources,
                store=ContentStore(tmp_path / suffix, codecs=codecs),
                kernels=toy.toy_registry(),
            )
            .nodes["survey"]
            .key
        )

    first = execute("csv-copy", first_codecs, "first")
    assert execute("csv-copy", second_codecs, "second") != first
    assert execute("csv-other", changed_name, "third") != first


def test_kernel_cannot_override_declared_source_codec(tmp_path: Path) -> None:
    registry = toy.toy_registry()
    registry.register(WrongCodec())
    graph = Graph(
        "toy",
        (toy.SOURCE,),
        (replace(toy.CREATE, kernel=WrongCodec.ref),),
    )
    with pytest.raises(StoreUnavailable, match="declares codec 'csv-tables'"):
        run_graph(
            compile_graph(graph),
            sources=toy.toy_sources(tmp_path),
            store=ContentStore(tmp_path / "store"),
            kernels=registry,
        )


def test_failed_required_validation_records_unreached_descendants(
    tmp_path: Path,
) -> None:
    gate = toy.gate_node(
        "income_validation",
        population="survey",
        column="income",
        low=-2.0,
        high=-1.0,
    )
    blocked = replace(
        toy.derive("after_validation", ("age",), "after_validation"),
        requires_success=("income.valid",),
    )
    graph = Graph(
        "toy",
        (toy.SOURCE,),
        (blocked, gate, toy.CREATE),
        products=(
            Product("income.valid", ProductKind.VALIDATION, node="income_validation"),
            Product(
                "after.population", ProductKind.POPULATION, node="after_validation"
            ),
        ),
    )
    compiled = compile_graph(graph)
    store = ContentStore(tmp_path / "store")
    sources = toy.toy_sources(tmp_path)
    registry = toy.toy_registry()
    manifest = run_graph(compiled, sources=sources, store=store, kernels=registry)

    validation = manifest.nodes["income_validation"]
    descendant = manifest.nodes["after_validation"]
    assert validation.receipt["outcome"] == "fail"
    assert validation.outcome_key is not None
    assert (
        store.load_json(validation.outcome_key, kind="validation-outcome")["outcome"]
        == "fail"
    )
    assert descendant.status == "unreached"
    assert descendant.blocked_by == ("income_validation",)
    assert not descendant.artifacts
    assert manifest.outcome == "not_successful"
    assert manifest.products["income.valid"]["key"] == validation.outcome_key
    assert manifest.products["after.population"]["status"] == "unreached"

    resumed = run_graph(
        compiled,
        sources=sources,
        store=store,
        kernels=registry,
        resume="require",
    )
    assert resumed.nodes["income_validation"].hit
    assert resumed.nodes["after_validation"].status == "unreached"
    assert RunManifest.from_json(resumed.to_json()).outcome == "not_successful"


def test_advisory_validation_is_recorded_without_blocking_dependents(
    tmp_path: Path,
) -> None:
    advisory = toy.gate_node(
        "income_advisory",
        population="survey",
        column="income",
        low=-2.0,
        high=-1.0,
    )
    dependent = Node(
        "record_advisory",
        RecordAdvisory.ref,
        inputs=(Slice("release", ("gate_verdict",)),),
        outputs=(Owned("release", "advisory_seen", "boolean"),),
        population="survey",
    )
    graph = Graph(
        "toy",
        (toy.SOURCE,),
        (dependent, advisory, toy.CREATE),
        products=(
            Product("income.advisory", ProductKind.VALIDATION, node=advisory.id),
        ),
    )
    registry = toy.toy_registry()
    registry.register(RecordAdvisory())
    store = ContentStore(tmp_path / "store")

    manifest = run_graph(
        compile_graph(graph),
        sources=toy.toy_sources(tmp_path),
        store=store,
        kernels=registry,
    )

    validation = manifest.nodes[advisory.id]
    assert validation.receipt["outcome"] == "fail"
    assert validation.outcome_key is not None
    assert (
        store.load_json(validation.outcome_key, kind="validation-outcome")["outcome"]
        == "fail"
    )
    assert manifest.nodes[dependent.id].status == "executed"
    assert manifest.products["income.advisory"]["key"] == validation.outcome_key
    assert manifest.outcome == "success"
