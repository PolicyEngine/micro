#!/usr/bin/env python3
"""Render a saved graph run as one self-contained offline HTML page."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from microcosm.graph import (
    ContentStore,
    RunManifest,
    StructuralDelta,
    compile_graph,
    explain_html,
    graph_document_from_json,
    graph_from_json,
    graph_key,
    load_graph_source,
)


def _load_populations(compiled, manifest: RunManifest, store: ContentStore):
    """Reattach structural frames that portable manifest JSON references."""

    populations = {}
    for node_id in compiled.order:
        node = compiled.graph.node(node_id)
        receipt = manifest.nodes[node_id]
        if node.structural is StructuralDelta.NONE or receipt.frame_key is None:
            continue
        populations[node_id] = store.load_frame(receipt.frame_key, node_key=receipt.key)
    return replace(manifest, populations=populations)


def _load_graph(path: Path):
    """Load authoritative YAML, generated Graph JSON, or legacy Graph JSON."""

    if path.suffix.lower() in {".yaml", ".yml"}:
        return load_graph_source(path).graph
    text = path.read_text(encoding="utf-8")
    try:
        return graph_document_from_json(text)
    except (TypeError, ValueError):
        return graph_from_json(text)


def render_saved_run(
    manifest_path: Path,
    graph_path: Path,
    output_path: Path,
    *,
    store_path: Path | None = None,
) -> None:
    """Validate and render one saved manifest/graph pair."""

    graph = _load_graph(graph_path)
    compiled = compile_graph(graph)
    resolved_store = store_path or manifest_path.parent / "store"
    if not resolved_store.is_dir():
        raise FileNotFoundError(
            f"Content store does not exist: {resolved_store}. "
            "Place it beside the manifest or pass --store."
        )
    store = ContentStore(resolved_store)
    manifest = RunManifest.load(manifest_path, store=store)
    if manifest.graph_key and manifest.graph_key != graph_key(graph):
        raise ValueError("The saved manifest belongs to a different Graph.")
    manifest = _load_populations(compiled, manifest, store)
    rendered = explain_html(compiled, manifest)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--store",
        type=Path,
        help="content store (default: a store directory beside the manifest)",
    )
    args = parser.parse_args(argv)
    render_saved_run(args.manifest, args.graph, args.out, store_path=args.store)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
