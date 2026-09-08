"""Authored graph YAML composes deterministically into one declaration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from microcosm.graph import (
    ArtifactInput,
    ArtifactOutput,
    ArtifactType,
    Capabilities,
    Determinism,
    Graph,
    GraphParameterBindingError,
    GraphSourceCompositionError,
    GraphSourceParseError,
    GraphSourceValidationError,
    KernelBase,
    KernelRegistry,
    Node,
    Owned,
    Ownership,
    Product,
    ProductKind,
    Slice,
    SourceRef,
    StructuralDelta,
    WeightTransition,
    compiled_graph_from_yaml_file,
    graph_document_from_json,
    graph_document_to_json,
    graph_from_yaml_file,
    load_graph_source,
    load_yaml12,
)

SOURCES = """\
schema_version: 1
sources:
  - name: fixture
    codec: csv-tables
    description: exact fixture
"""

NODES = """\
schema_version: 1
nodes:
  - id: apply
    kernel: apply@1
    population: create
    inputs:
      - entity: person
        columns: [age]
    outputs:
      - entity: person
        column: score
        dtype: float64
    param_bindings:
      fraction: sample_fraction
  - id: create
    kernel: source.csv@1
    structural: create
    sources: [fixture]
    outputs:
      - entity: person
        column: age
        dtype: int64
"""


class _Create(KernelBase):
    ref = "source.csv@1"
    capabilities = Capabilities(
        Determinism.DETERMINISTIC, structural=StructuralDelta.CREATE
    )

    def run(self, context):  # pragma: no cover - compilation does not execute
        raise AssertionError("not executed")


class _Apply(KernelBase):
    ref = "apply@1"
    capabilities = Capabilities(Determinism.DETERMINISTIC)

    def run(self, context):  # pragma: no cover - compilation does not execute
        raise AssertionError("not executed")


def _registry() -> KernelRegistry:
    registry = KernelRegistry()
    registry.register(_Create())
    registry.register(_Apply())
    return registry


def _write_graph(root: Path, module_order: tuple[str, str]) -> Path:
    root.mkdir()
    (root / "sources.yaml").write_text(SOURCES)
    (root / "nodes.yaml").write_text(NODES)
    graph = root / "graph.yaml"
    graph.write_text(
        "schema_version: 1\n"
        "country: toy\n"
        "modules:\n"
        + "".join(f"  - {name}\n" for name in module_order)
        + "parameters:\n"
        "  sample_fraction:\n"
        "    type: number\n"
        "    required: false\n"
        "    default: 1.0\n"
        "    minimum: 0.0\n"
        "    maximum: 1.0\n"
    )
    return graph


def test_modules_lower_once_independent_of_authored_order(tmp_path: Path) -> None:
    first = _write_graph(tmp_path / "first", ("sources.yaml", "nodes.yaml"))
    second = _write_graph(tmp_path / "second", ("nodes.yaml", "sources.yaml"))

    one = load_graph_source(first, parameters={"sample_fraction": 0.25})
    two = load_graph_source(second, parameters={"sample_fraction": 0.25})

    assert one.graph == two.graph
    assert tuple(node.id for node in one.graph.nodes) == ("apply", "create")
    assert one.graph.node("apply").params["fraction"] == 0.25
    assert compiled_graph_from_yaml_file(first, kernels=_registry()).order == (
        "create",
        "apply",
    )
    assert tuple(receipt.path for receipt in one.receipts) == (
        "graph.yaml",
        "nodes.yaml",
        "sources.yaml",
    )
    generated = graph_document_to_json(one.graph)
    assert graph_document_from_json(generated) == one.graph
    assert json.loads(generated)["derived"] is True


def test_parameter_binding_is_declared_and_affects_only_consumers(
    tmp_path: Path,
) -> None:
    path = _write_graph(tmp_path / "graph", ("sources.yaml", "nodes.yaml"))
    default = graph_from_yaml_file(path)
    changed = graph_from_yaml_file(path, parameters={"sample_fraction": 0.5})
    assert default.node("create") == changed.node("create")
    assert default.node("apply") != changed.node("apply")
    with pytest.raises(GraphParameterBindingError, match="undeclared"):
        graph_from_yaml_file(path, parameters={"node.kernel": "other@1"})


def test_registry_contract_is_checked_before_execution(tmp_path: Path) -> None:
    path = _write_graph(tmp_path / "graph", ("sources.yaml", "nodes.yaml"))
    registry = _registry()
    registry.get("source.csv@1").capabilities = Capabilities(  # type: ignore[assignment]
        Determinism.DETERMINISTIC
    )
    with pytest.raises(GraphSourceValidationError, match="structural operation"):
        compiled_graph_from_yaml_file(path, kernels=registry)


def test_every_stack_base_declaration_field_lowers_exactly(tmp_path: Path) -> None:
    model = ArtifactType("test.model", 1)
    path = tmp_path / "graph.yaml"
    path.write_text(
        """\
schema_version: 1
country: toy
mass_partition: [person, period]
products:
  - {name: final, kind: population, target: {node: weights}}
sources:
  - {name: fixture, codec: csv-tables, description: exact fixture}
nodes:
  - id: create
    kernel: create@1
    structural: create
    sources: [fixture]
    params: {nested: [true, null, [2.5, x]]}
    outputs:
      - {entity: person, column: age, dtype: int64}
      - {entity: person, column: period, dtype: int64}
      - {entity: person, column: selected, dtype: boolean}
    description: source node
    citation: synthetic
  - id: train
    kernel: train@1
    population: create
    inputs:
      - {entity: person, columns: [age]}
    artifact_outputs:
      - {name: model, type: {name: test.model, schema_version: 1}}
  - id: expand
    kernel: expand@1
    structural: expand
    base: create
    inputs:
      - {entity: person, columns: [age]}
    entrants: true
    mass: free
  - id: apply
    kernel: apply@1
    population: expand
    inputs:
      - {entity: person, columns: [age, selected], rows: selected}
    outputs:
      - {entity: person, column: age, dtype: int64, rows: selected, ownership: produced, rewrite: true}
      - {entity: person, column: score, dtype: float64, rows: selected, ownership: absent}
    artifact_inputs:
      - {name: fitted, producer: train, artifact: model, type: {name: test.model, schema_version: 1}}
  - id: weights
    kernel: weights@1
    structural: reweight
    base: expand
    inputs:
      - {entity: person, columns: [age]}
    weights: {entity: person, to_kind: importance, mass: free}
    mass: free
"""
    )
    expected = Graph(
        "toy",
        (SourceRef("fixture", "csv-tables", "exact fixture"),),
        (
            Node(
                "apply",
                "apply@1",
                inputs=(Slice("person", ("age", "selected"), "selected"),),
                outputs=(
                    Owned("person", "age", "int64", "selected", rewrite=True),
                    Owned(
                        "person",
                        "score",
                        "float64",
                        "selected",
                        Ownership.ABSENT,
                    ),
                ),
                population="expand",
                artifact_inputs=(ArtifactInput("fitted", "train", "model", model),),
            ),
            Node(
                "create",
                "create@1",
                outputs=(
                    Owned("person", "age", "int64"),
                    Owned("person", "period", "int64"),
                    Owned("person", "selected", "boolean"),
                ),
                params={"nested": (True, None, (2.5, "x"))},
                structural=StructuralDelta.CREATE,
                sources=("fixture",),
                description="source node",
                citation="synthetic",
            ),
            Node(
                "expand",
                "expand@1",
                inputs=(Slice("person", ("age",)),),
                structural=StructuralDelta.EXPAND,
                base="create",
                mass="free",
                entrants=True,
            ),
            Node(
                "train",
                "train@1",
                inputs=(Slice("person", ("age",)),),
                population="create",
                artifact_outputs=(ArtifactOutput("model", model),),
            ),
            Node(
                "weights",
                "weights@1",
                inputs=(Slice("person", ("age",)),),
                structural=StructuralDelta.REWEIGHT,
                base="expand",
                weights=WeightTransition("person", "importance", "free"),
                mass="free",
            ),
        ),
        ("person", "period"),
        products=(Product("final", ProductKind.POPULATION, node="weights"),),
    )
    assert graph_from_yaml_file(path) == expected


def test_closed_schema_reports_pointer_and_source_location(tmp_path: Path) -> None:
    path = _write_graph(tmp_path / "graph", ("sources.yaml", "nodes.yaml"))
    nodes = path.parent / "nodes.yaml"
    nodes.write_text(
        NODES.replace("    kernel: apply@1", "    kernel: apply@1\n    surprise: true")
    )
    with pytest.raises(GraphSourceValidationError) as caught:
        graph_from_yaml_file(path)
    assert caught.value.source == str(nodes)
    assert caught.value.pointer == "/nodes/0/surprise"
    assert (caught.value.line, caught.value.column) == (5, 5)


@pytest.mark.parametrize(
    "bad",
    ["../outside.yaml", "/absolute.yaml", "directory\\module.yaml"],
)
def test_unsafe_module_paths_are_rejected(tmp_path: Path, bad: str) -> None:
    graph = tmp_path / "graph.yaml"
    graph.write_text(f"schema_version: 1\ncountry: toy\nmodules: [{bad!r}]\n")
    with pytest.raises(GraphSourceCompositionError, match="module path|unsafe"):
        graph_from_yaml_file(graph)


def test_duplicate_and_recursive_modules_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "module.yaml").write_text("schema_version: 1\nmodules: [module.yaml]\n")
    graph = tmp_path / "graph.yaml"
    graph.write_text("schema_version: 1\ncountry: toy\nmodules: [module.yaml]\n")
    with pytest.raises(GraphSourceCompositionError, match="cycle"):
        graph_from_yaml_file(graph)


@pytest.mark.parametrize(
    "text",
    [
        "value: 1\nvalue: 2\n",
        "value: !!str 1\n",
        "value: 2026-09-08\n",
        "value: .nan\n",
        "first: 1\n---\nsecond: 2\n",
        "1: value\n",
        "cycle: &cycle [*cycle]\n",
    ],
)
def test_shared_yaml_parser_rejects_ambiguous_features(text: str) -> None:
    with pytest.raises(GraphSourceParseError):
        load_yaml12(text, source="fixture.yaml")


def test_generated_graph_document_has_a_closed_versioned_envelope(
    tmp_path: Path,
) -> None:
    path = _write_graph(tmp_path / "graph", ("sources.yaml", "nodes.yaml"))
    generated = graph_document_to_json(graph_from_yaml_file(path))
    payload = json.loads(generated)
    payload["serialization_version"] = 2
    with pytest.raises(ValueError, match="Unsupported"):
        graph_document_from_json(json.dumps(payload))
    payload["serialization_version"] = 1
    payload["extra"] = True
    with pytest.raises(ValueError, match="fields"):
        graph_document_from_json(json.dumps(payload))
    with pytest.raises(ValueError, match="duplicate"):
        graph_document_from_json(
            '{"derived":true,"derived":true,"document_type":"microcosm.graph",'
            '"graph":{},"serialization_version":1}'
        )
