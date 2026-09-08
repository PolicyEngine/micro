"""Content identities for graph sources, nodes, and artifacts."""

from __future__ import annotations

import hashlib
import platform as _platform
import sys
from collections.abc import Mapping
from pathlib import Path

from .canonical import canonical_json, normative, sha256_domain
from .decl import CompiledGraph, Graph, StructuralDelta
from .kernel import Capabilities, Numeric

__all__ = [
    "opaque_artifact_key",
    "platform_fingerprint",
    "artifact_key",
    "frame_key",
    "graph_key",
    "node_key",
    "seed",
    "source_content_key",
    "source_content_identity",
    "source_binding_key",
    "validation_outcome_key",
    "union_lineage_key",
    "weights_key",
]


def _hash_parts(domain: str, *parts: object) -> str:
    return sha256_domain(domain, canonical_json(parts))


def _directory_identity(path: Path) -> tuple[str, int]:
    """Hash a directory as a deterministic sequence of relative file bytes.

    Both built-in source codecs consume directories.  Relative names are
    length-prefixed into this aggregate, so renaming the source directory is
    inert while renaming or changing a file inside it changes the identity.
    ``size`` is the sum of regular-file payload sizes.
    """

    digest = hashlib.sha256(b"microcosm-graph/source-directory/1\0")
    size = 0
    files = sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        content = candidate.read_bytes()
        digest.update(len(relative).to_bytes(8, "little"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "little"))
        digest.update(content)
        size += len(content)
    return digest.hexdigest(), size


def source_content_key(name: str, path: str | Path) -> str:
    """Return the path-independent identity of one named source's content.

    A regular file follows the normative ``sha256(bytes), size`` formula.
    Directories use a deterministic packed representation for the directory-
    based ``frame-store`` and ``csv-tables`` codecs.
    """

    _, content_hash, size = source_content_identity(path)
    return _hash_parts("source", name, content_hash, size)


def source_content_identity(path: str | Path) -> tuple[str, str, int]:
    """Return ``(boundary kind, SHA-256, size)`` without including a path."""

    source_path = Path(path)
    if source_path.is_file():
        content = source_path.read_bytes()
        return "file", hashlib.sha256(content).hexdigest(), len(content)
    if source_path.is_dir():
        content_hash, size = _directory_identity(source_path)
        return "directory", content_hash, size
    raise FileNotFoundError(f"Source path does not exist: {source_path}")


def source_binding_key(
    content_key: str, codec: str, codec_impl_hash: str, content_type: str
) -> str:
    """Bind verified bytes to their declared decoder and logical content type."""

    return _hash_parts(
        "source-binding", content_key, codec, codec_impl_hash, content_type
    )


def graph_key(graph: Graph) -> str:
    """Return the semantic identity of a complete Graph, independent of order."""

    if not isinstance(graph, Graph):
        raise TypeError("graph_key requires a Graph declaration.")
    payload = {
        "country": graph.country,
        "mass_partition": graph.mass_partition,
        "sources": tuple(
            normative(source)
            for source in sorted(graph.sources, key=lambda item: item.name)
        ),
        "nodes": tuple(
            normative(node) for node in sorted(graph.nodes, key=lambda item: item.id)
        ),
        "products": tuple(
            normative(product)
            for product in sorted(graph.products, key=lambda item: item.name)
        ),
    }
    return _hash_parts("semantic-graph", payload)


def platform_fingerprint() -> str:
    """The platform a platform-bitwise kernel's bytes belong to.

    Architecture, operating system, and Python minor version: the axes along
    which ``fit.qrf@1`` was measured to move (``docs/graph-qrf-cross-platform.md``).
    """
    return (
        f"{_platform.machine()}/{sys.platform}/"
        f"py{sys.version_info.major}.{sys.version_info.minor}"
    )


def artifact_key(node_key: str, entity: str, column: str) -> str:
    """Derive one column artifact identity from its producing node."""

    return _hash_parts("artifact", node_key, entity, column)


def opaque_artifact_key(node_key: str, name: str) -> str:
    """Identity of an opaque or typed byte output (legacy domain preserved)."""
    return _hash_parts("node-artifact", node_key, name)


def frame_key(node_key: str) -> str:
    """Derive the structural frame artifact identity from its node."""

    return _hash_parts("frame", node_key)


def weights_key(node_key: str, entity: str) -> str:
    """Derive a typed-weight artifact identity outside the column namespace."""

    return _hash_parts("weights", node_key, entity)


def validation_outcome_key(node_key: str) -> str:
    """Identity of the executor-preserved validation outcome for one node."""

    return _hash_parts("validation-outcome", node_key)


def union_lineage_key(node_key: str) -> str:
    """Identity of deterministic per-row source lineage for a union node."""

    return _hash_parts("union-lineage", node_key)


def _required_key(keys: Mapping[str, str], node_id: str, consumer: str) -> str:
    try:
        return keys[node_id]
    except KeyError as error:
        raise KeyError(
            f"Node {consumer!r} needs the key of predecessor {node_id!r}; "
            "compute keys in CompiledGraph.order."
        ) from error


def _canonical_tolerance_float(value: int | float) -> float:
    number = float(value)
    return 0.0 if number == 0.0 else number


def _capabilities_projection(capabilities: Capabilities) -> dict[str, object]:
    """Return the complete canonical payload for a kernel contract."""

    tolerance = capabilities.tolerance
    return {
        "determinism": capabilities.determinism.value,
        "numeric": capabilities.numeric.value,
        "seed_source": capabilities.seed_source.value,
        "structural": capabilities.structural.value,
        "role": capabilities.role.value,
        "consumes_se": capabilities.consumes_se,
        "dependencies": list(capabilities.dependencies),
        "tolerance": (
            None
            if tolerance is None
            else {
                "rtol": _canonical_tolerance_float(tolerance.rtol),
                "atol": _canonical_tolerance_float(tolerance.atol),
                "ulps": tolerance.ulps,
            }
        ),
    }


def node_key(
    compiled: CompiledGraph,
    node_id: str,
    input_keys: Mapping[str, str],
    kernel_impl_hash: str,
    source_keys: Mapping[str, str],
    *,
    kernel_capabilities: Capabilities,
) -> str:
    """Derive a node key from its declaration and resolved input identities.

    ``input_keys`` maps already-visited node ids to their node keys.  The
    function resolves each declared column exactly as ``compile_graph`` does:
    a local owner supplies its artifact, while a carried column is supplied by
    the current structural version's frame.
    """

    node = compiled.graph.node(node_id)
    input_version: str | None
    if node.structural is StructuralDelta.CREATE:
        input_version = None
    elif node.structural is StructuralDelta.NONE:
        input_version = compiled.versions[node_id]
    else:
        input_version = None if node.structural is StructuralDelta.UNION else node.base

    def supplier(version: str, entity: str, column: str) -> str:
        owner = compiled.owners.get((version, entity, column))
        if owner is not None:
            return owner
        holder = compiled.graph.node(version)
        if holder.structural is StructuralDelta.REVISION:
            assert holder.base is not None
            return supplier(holder.base, entity, column)
        return version

    resolved: dict[tuple[str, str], str] = {}
    rewritten = {
        (owned.entity, owned.column) for owned in node.outputs if owned.rewrite
    }
    if input_version is not None:
        for slice_ in node.inputs:
            for column in slice_.columns:
                coordinate = (slice_.entity, column)
                producer = (
                    input_version
                    if coordinate in rewritten
                    else supplier(input_version, slice_.entity, column)
                )
                producer_key = _required_key(input_keys, producer, node_id)
                resolved[coordinate] = artifact_key(producer_key, slice_.entity, column)
    input_artifacts = tuple(
        (entity, column, resolved[(entity, column)])
        for entity, column in sorted(resolved)
    )

    if node.structural is StructuralDelta.NONE:
        version = compiled.versions[node_id]
        population_input = {
            "population": frame_key(_required_key(input_keys, version, node_id))
        }
    elif node.structural is StructuralDelta.CREATE:
        population_input = {}
    elif node.structural is StructuralDelta.UNION:
        population_input = {
            "bases": tuple(
                (
                    base,
                    frame_key(_required_key(input_keys, base, node_id)),
                    tuple(
                        (member, _required_key(input_keys, member, node_id))
                        for member in compiled.predecessors[node_id]
                        if compiled.versions.get(member) == base and member != base
                    ),
                )
                for base in node.bases
            )
        }
    else:
        assert node.base is not None
        population_input = {
            "base": frame_key(_required_key(input_keys, node.base, node_id)),
            # A structural transform receives the fully patched base version,
            # not merely the original structural Frame.  compile_graph makes
            # every ordinary member of that version a predecessor; binding
            # their keys prevents an old FILTER/EXPAND/REWEIGHT frame from
            # surviving a changed base patch (including a weight-only node).
            "members": tuple(
                (predecessor, _required_key(input_keys, predecessor, node_id))
                for predecessor in compiled.predecessors[node_id]
                if predecessor != node.base
            ),
        }

    if node.sources:
        resolved_sources = {
            name: source_keys[name]
            for name in sorted(node.sources)
            if name in source_keys
        }
        missing_sources = sorted(set(node.sources) - source_keys.keys())
        if missing_sources:
            joined = ", ".join(repr(name) for name in missing_sources)
            raise KeyError(f"Node {node_id!r} has no content key for source {joined}.")
    else:
        resolved_sources = {}

    # Graph-level mass semantics (amendment 12) change what a structural node
    # computes, so they enter its key; an ordinary node's key is unaffected.
    graph_facts = (
        {} if node.structural is StructuralDelta.NONE else compiled.graph.normative()
    )
    # Capabilities are executable contract, independent of implementation
    # bytes. Bind the complete declaration so a cache entry produced under one
    # contract cannot satisfy another kernel with the same ref and code hash.
    capabilities = _capabilities_projection(kernel_capabilities)
    # A platform-bitwise kernel's bytes belong to one platform (amendment 16):
    # its key carries the platform, so a shared store never serves another
    # platform's output. Other kernels' keys are unchanged by this.
    platform_scope = (
        (platform_fingerprint(),)
        if kernel_capabilities.numeric is Numeric.PLATFORM_BITWISE
        else ()
    )
    typed_inputs = (
        (
            {
                "typed_artifacts": tuple(
                    (
                        item.name,
                        opaque_artifact_key(
                            _required_key(input_keys, item.producer, node_id),
                            item.artifact,
                        ),
                        normative(item.type),
                    )
                    for item in sorted(
                        node.artifact_inputs, key=lambda value: value.name
                    )
                )
            },
        )
        if node.artifact_inputs
        else ()
    )
    required_outcomes = (
        (
            {
                "required_validation_outcomes": tuple(
                    (
                        product_name,
                        _required_key(
                            input_keys,
                            compiled.product_nodes[product_name],
                            node_id,
                        ),
                    )
                    for product_name in sorted(node.requires_success)
                )
            },
        )
        if node.requires_success
        else ()
    )
    return _hash_parts(
        "node",
        normative(node),
        input_artifacts,
        population_input,
        kernel_impl_hash,
        resolved_sources,
        graph_facts,
        capabilities,
        *platform_scope,
        *typed_inputs,
        *required_outcomes,
    )


def seed(node_key: str) -> int:
    """Derive the node's unsigned 64-bit little-endian RNG seed."""

    digest = hashlib.sha256(b"seed\0" + node_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little")
