"""Shared entry point for one YAML root, one compiled graph, and one run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .decl import CompiledGraph, compile_graph
from .executor import run_graph
from .graph_source import LoadedGraphSource, load_graph_source
from .kernel import KernelRegistry
from .manifest import Decision, RunManifest
from .materialize import CandidateIndex, MaterializerRegistry, materialize_products
from .serialize import graph_document_to_json
from .store import ContentStore, ResumePolicy

__all__ = ["GraphRunResult", "run_graph_source"]


@dataclass(frozen=True)
class GraphRunResult:
    """Compiled declaration, saved run evidence, and optional local candidate."""

    source: LoadedGraphSource
    compiled: CompiledGraph
    manifest: RunManifest
    manifest_path: Path
    graph_json_path: Path | None
    candidate_index: CandidateIndex | None


def run_graph_source(
    root: str | Path,
    *,
    sources: Mapping[str, Path],
    store: ContentStore,
    kernels: KernelRegistry,
    manifest_path: str | Path,
    parameters: Mapping[str, object] | None = None,
    resume: ResumePolicy = "auto",
    decisions: tuple[Decision, ...] = (),
    graph_json_path: str | Path | None = None,
    materializers: MaterializerRegistry | None = None,
    candidate_directory: str | Path | None = None,
    materialized_outputs: Mapping[str, str] | None = None,
) -> GraphRunResult:
    """Compile and execute one selected YAML root, then save local products.

    Post-run materialization starts only after the canonical manifest has been
    saved. This helper has no publication or remote-write behavior.
    """

    loaded = load_graph_source(root, parameters=parameters)
    compiled = compile_graph(loaded.graph)
    graph_json = (
        graph_document_to_json(loaded.graph) if graph_json_path is not None else None
    )
    manifest = run_graph(
        compiled,
        sources=sources,
        store=store,
        kernels=kernels,
        resume=resume,
        decisions=decisions,
        graph_source=loaded,
        graph_json=graph_json,
    )
    saved_manifest = Path(manifest_path)
    manifest.save(saved_manifest)

    saved_graph_json: Path | None = None
    if graph_json_path is not None:
        assert graph_json is not None
        saved_graph_json = Path(graph_json_path)
        saved_graph_json.parent.mkdir(parents=True, exist_ok=True)
        saved_graph_json.write_text(graph_json, encoding="utf-8")

    outputs = {} if materialized_outputs is None else dict(materialized_outputs)
    candidate_index: CandidateIndex | None = None
    if outputs:
        if materializers is None or candidate_directory is None:
            raise ValueError(
                "materializers and candidate_directory are required when outputs "
                "are requested."
            )
        candidate_index = materialize_products(
            loaded.graph,
            saved_manifest,
            store,
            candidate_directory,
            materializers,
            outputs,
        )
    elif materializers is not None or candidate_directory is not None:
        raise ValueError(
            "materialized_outputs are required with post-run materialization options."
        )

    return GraphRunResult(
        source=loaded,
        compiled=compiled,
        manifest=manifest,
        manifest_path=saved_manifest,
        graph_json_path=saved_graph_json,
        candidate_index=candidate_index,
    )
