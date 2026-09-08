"""Portable population reconstruction and post-run local materialization."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from microcosm.frame import Frame
from microcosm.graph import (
    ContentStore,
    Graph,
    MaterializerRegistry,
    Product,
    ProductKind,
    StoreCorruptError,
    materialize_products,
    reconstruct_population,
    run_graph_source,
)

if "_reconstruction_toy" not in sys.modules:
    _SPEC = importlib.util.spec_from_file_location(
        "_reconstruction_toy", Path(__file__).with_name("_toy.py")
    )
    sys.modules["_reconstruction_toy"] = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(sys.modules["_reconstruction_toy"])
toy = sys.modules["_reconstruction_toy"]


def _assert_frame_equal(actual: Frame, expected: Frame) -> None:
    assert actual.schema == expected.schema
    assert actual.metadata == expected.metadata
    assert actual.links == expected.links
    for entity in expected.entities:
        pd.testing.assert_frame_equal(
            actual.table(entity), expected.table(entity), check_exact=True
        )
    pd.testing.assert_series_equal(actual.strata, expected.strata, check_exact=True)
    assert actual.weighted_entities == expected.weighted_entities
    for entity in expected.weighted_entities:
        assert actual.weights_for(entity).kind is expected.weights_for(entity).kind
        np.testing.assert_array_equal(
            actual.weights_for(entity).values,
            expected.weights_for(entity).values,
        )


def _product_graph() -> Graph:
    base = toy.small_graph()
    return Graph(
        base.country,
        base.sources,
        base.nodes,
        products=(
            Product("final.population", ProductKind.POPULATION, node="target_b"),
            Product(
                "final.h5",
                ProductKind.EXPORT,
                source="final.population",
                codec="test-h5",
                codec_version=1,
            ),
        ),
    )


def test_named_population_reconstructs_ordinary_patches_without_runtime_inputs(
    tmp_path: Path,
) -> None:
    graph = _product_graph()
    run = toy.run_toy(graph, tmp_path / "run")
    expected = run.manifest.population("survey")
    manifest_path = tmp_path / "manifest.json"
    run.manifest.save(manifest_path)
    shutil.rmtree(next(iter(run.sources.values())))

    reconstructed = reconstruct_population(
        graph,
        type(run.manifest).from_json(manifest_path.read_text()),
        run.store,
        "final.population",
    )

    _assert_frame_equal(reconstructed, expected)
    assert "target_a" in reconstructed.table("person")
    assert "target_b" in reconstructed.table("person")


def test_structural_coordinates_reference_one_verified_frame_object(
    tmp_path: Path,
) -> None:
    graph = Graph(
        "toy",
        (toy.SOURCE,),
        (toy.CREATE,),
        products=(Product("initial", ProductKind.POPULATION, node="survey"),),
    )
    run = toy.run_toy(graph, tmp_path / "run")
    receipt = run.manifest.nodes["survey"]
    assert receipt.frame_key is not None
    frame_metadata = run.store.metadata(receipt.frame_key, kind="frame")
    frame_payload_bytes = sum(
        int(entry["size"]) for entry in frame_metadata["payloads"].values()
    )
    assert frame_payload_bytes > 0

    for coordinate, key in receipt.artifacts.items():
        metadata = run.store.metadata(key, kind="column")
        assert metadata["encoding"] == "frame-column-ref-v1"
        assert metadata["frame_key"] == receipt.frame_key
        assert metadata["payloads"] == {}
        entity, column = coordinate
        expected = run.manifest.population("survey").table(entity)
        id_column = run.manifest.population("survey").schema.entity_id_column(entity)
        pd.testing.assert_series_equal(
            run.store.load_column(key),
            pd.Series(
                expected[column].array.copy(),
                index=pd.Index(expected[id_column].array.copy(), name=id_column),
                name=column,
                dtype=expected[column].dtype,
            ),
            check_exact=True,
        )

    altered_key = next(iter(receipt.artifacts.values()))
    metadata_path = run.store.object_path(altered_key) / "meta.json"
    altered = json.loads(metadata_path.read_text())
    altered["column"] = "different_column"
    metadata_path.write_text(json.dumps(altered))
    with pytest.raises(StoreCorruptError, match="node identity"):
        run.store.load_column(altered_key)


def test_h5_materialization_uses_saved_values_and_records_candidate_identity(
    tmp_path: Path,
) -> None:
    graph = _product_graph()
    run = toy.run_toy(graph, tmp_path / "run")
    manifest_path = tmp_path / "manifest.json"
    run.manifest.save(manifest_path)
    calls_before = toy.total_calls(run.registry)
    shutil.rmtree(next(iter(run.sources.values())))

    registry = MaterializerRegistry()

    def write_h5(value: object, destination: Path) -> None:
        import h5py

        assert isinstance(value, Frame)
        person = value.table("person")
        with h5py.File(destination, mode="w") as h5:
            h5.create_dataset(
                "person_id",
                data=person["person_id"].to_numpy(),
                track_times=False,
            )
            h5.create_dataset(
                "target_b",
                data=person["target_b"].to_numpy(),
                track_times=False,
            )

    registry.register("test-h5", 1, write_h5, implementation_hash="a" * 64)
    first = materialize_products(
        graph,
        manifest_path,
        run.store,
        tmp_path / "candidate-one",
        registry,
        {"final.h5": "microdata.h5"},
    )
    second = materialize_products(
        graph,
        manifest_path,
        run.store,
        tmp_path / "candidate-two",
        registry,
        {"final.h5": "microdata.h5"},
    )

    assert toy.total_calls(run.registry) == calls_before
    assert first.key == second.key
    assert first.to_json() == second.to_json()
    record = first.products["final.h5"]
    assert record.boundary == "file"
    assert record.size > 0
    assert len(record.sha256) == 64
    assert len(record.content_key) == 64
    saved = json.loads((tmp_path / "candidate-one/candidate-index.json").read_text())
    assert saved["manifest_key"] == run.manifest.key
    assert saved["products"]["final.h5"]["sha256"] == record.sha256


def test_shared_runner_executes_one_yaml_root_and_saves_before_materializing(
    tmp_path: Path,
) -> None:
    graph_yaml = tmp_path / "graph.yaml"
    graph_yaml.write_text(
        """\
schema_version: 1
country: toy
sources:
  - {name: survey, codec: csv-tables}
nodes:
  - id: survey
    kernel: source.csv@1
    structural: create
    sources: [survey]
    outputs:
      - {entity: person, column: age, dtype: int64}
      - {entity: person, column: income, dtype: float64}
      - {entity: person, column: is_adult, dtype: boolean}
      - {entity: person, column: receives_x, dtype: boolean}
      - {entity: household, column: household_size, dtype: int64}
products:
  - {name: final.population, kind: population, target: {node: survey}}
  - name: final.h5
    kind: export
    target: {product: final.population}
    codec: test-h5
    codec_version: 1
"""
    )
    sources = toy.toy_sources(tmp_path / "sources")
    kernels = toy.toy_registry()
    manifest_path = tmp_path / "evidence/run.json"
    registry = MaterializerRegistry()

    def write_after_manifest(value: object, destination: Path) -> None:
        assert manifest_path.is_file()
        assert isinstance(value, Frame)
        destination.write_bytes(
            b"test-h5\0" + value.table("person").to_csv(index=False).encode()
        )

    registry.register("test-h5", 1, write_after_manifest, implementation_hash="b" * 64)
    result = run_graph_source(
        graph_yaml,
        sources=sources,
        store=ContentStore(tmp_path / "store"),
        kernels=kernels,
        manifest_path=manifest_path,
        graph_json_path=tmp_path / "evidence/graph.json",
        materializers=registry,
        candidate_directory=tmp_path / "candidate",
        materialized_outputs={"final.h5": "microdata.h5"},
    )

    assert toy.total_calls(kernels) == 1
    assert result.manifest_path == manifest_path
    assert result.candidate_index is not None
    assert result.candidate_index.manifest_key == result.manifest.key
    assert (tmp_path / "candidate/candidate-index.json").is_file()
    assert (tmp_path / "evidence/graph.json").is_file()
