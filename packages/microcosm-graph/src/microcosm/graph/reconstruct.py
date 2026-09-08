"""Portable reconstruction of named population products from stored values."""

from __future__ import annotations

from collections.abc import Mapping

from microcosm.frame import Frame

from .decl import Graph, ProductKind, StructuralDelta, compile_graph
from .errors import GraphRuntimeError, StoreCorruptError
from .kernel import KernelResult
from .keys import graph_key
from .manifest import RunManifest
from .population import Population, patch
from .store import ContentStore

__all__ = ["reconstruct_population"]


def _owners_for_stored_frame(
    frame: Frame,
    *,
    node_id: str,
    base: Population | None,
) -> Mapping[tuple[str, str], str]:
    """Restore the ownership needed to apply later stored column patches."""

    coordinates = {
        (entity, str(column))
        for entity in frame.entities
        for column in frame.table(entity).columns
    }
    if base is not None and set(base.owners) == coordinates:
        return base.owners
    return {coordinate: node_id for coordinate in coordinates}


def reconstruct_population(
    graph: Graph,
    manifest: RunManifest,
    store: ContentStore,
    product_name: str,
) -> Frame:
    """Reconstruct a named population without kernels or original source files.

    Structural states are restored from their stored frames. Ordinary and
    revision nodes are replayed as stored column patches in canonical execution
    order through the product's declared node.
    """

    if manifest.graph_key != graph_key(graph):
        raise GraphRuntimeError(
            "The manifest was produced from a different Graph declaration."
        )
    compiled = compile_graph(graph)
    if set(manifest.nodes) != set(compiled.order):
        raise GraphRuntimeError(
            "The manifest does not contain exactly the compiled Graph nodes."
        )
    declarations = {product.name: product for product in graph.products}
    try:
        product = declarations[product_name]
    except KeyError as error:
        raise KeyError(f"Graph has no product named {product_name!r}.") from error
    if product.kind is not ProductKind.POPULATION:
        raise GraphRuntimeError(
            f"Product {product_name!r} is {product.kind.value!r}, not a population."
        )
    assert product.node is not None
    try:
        target_index = compiled.order.index(product.node)
    except ValueError as error:  # defended by compilation
        raise GraphRuntimeError(
            f"Population product {product_name!r} names an unknown node."
        ) from error

    product_record = manifest.products.get(product_name)
    if not isinstance(product_record, Mapping):
        raise GraphRuntimeError(
            f"Manifest has no record for population product {product_name!r}."
        )
    if (
        product_record.get("kind") != ProductKind.POPULATION.value
        or product_record.get("producer") != product.node
        or product_record.get("status") != "executed"
    ):
        raise GraphRuntimeError(
            f"Manifest record for population product {product_name!r} is unusable."
        )

    populations: dict[str, Population] = {}
    for node_id in compiled.order[: target_index + 1]:
        node = graph.node(node_id)
        receipt = manifest.nodes[node_id]
        if receipt.status == "unreached":
            continue
        if receipt.status != "executed":
            raise StoreCorruptError(
                f"Manifest node {node_id!r} has unknown status {receipt.status!r}."
            )

        if node.structural not in {
            StructuralDelta.NONE,
            StructuralDelta.REVISION,
        }:
            if receipt.frame_key is None:
                raise StoreCorruptError(
                    f"Structural node {node_id!r} has no stored frame key."
                )
            frame = store.load_frame(receipt.frame_key, node_key=receipt.key)
            base = None
            if node.structural is not StructuralDelta.CREATE:
                if node.structural is StructuralDelta.UNION:
                    base = None
                else:
                    assert node.base is not None
                    base = populations.get(node.base)
            populations[node_id] = Population.from_frame(
                frame,
                node_id,
                _owners_for_stored_frame(frame, node_id=node_id, base=base),
            )
        else:
            version = compiled.versions[node_id]
            if node.structural is StructuralDelta.REVISION:
                assert node.base is not None
                incumbent = populations[node.base]
            else:
                incumbent = populations[version]
            columns = {
                coordinate: store.load_column(key, node_key=receipt.key)
                for coordinate, key in receipt.artifacts.items()
            }
            updated = patch(
                incumbent,
                node,
                KernelResult(columns=columns),
                mass_partition=graph.mass_partition,
            )
            populations[version] = updated

    target_version = compiled.versions[product.node]
    try:
        return populations[target_version].frame
    except KeyError as error:
        raise GraphRuntimeError(
            f"Population product {product_name!r} could not be reconstructed."
        ) from error
