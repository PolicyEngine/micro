"""Deterministic post-run materialization of declared local export products."""

from __future__ import annotations

import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Protocol

from .canonical import canonical_json, sha256_domain
from .decl import Graph, Product, ProductKind, compile_graph
from .errors import GraphRuntimeError
from .keys import graph_key, source_content_identity
from .manifest import RunManifest
from .reconstruct import reconstruct_population
from .store import ContentStore

__all__ = [
    "CandidateIndex",
    "Materializer",
    "MaterializedProduct",
    "MaterializerRegistry",
    "materialize_products",
]

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class Materializer(Protocol):
    """A deterministic writer for one declared product codec and version."""

    def __call__(self, value: object, destination: Path) -> None:
        """Write ``value`` below the caller-provided local destination."""
        ...


@dataclass(frozen=True)
class _RegisteredMaterializer:
    writer: Materializer
    implementation_hash: str


class MaterializerRegistry:
    """Exact codec/version bindings used only after graph execution."""

    def __init__(self) -> None:
        self._materializers: dict[tuple[str, int], _RegisteredMaterializer] = {}

    def register(
        self,
        codec: str,
        version: int,
        writer: Materializer,
        *,
        implementation_hash: str,
    ) -> None:
        if not isinstance(codec, str) or not codec:
            raise TypeError("Materializer codec must be a non-empty string.")
        if type(version) is not int or version < 1:
            raise TypeError("Materializer version must be a positive integer.")
        if not callable(writer):
            raise TypeError("Materializer writer must be callable.")
        if not isinstance(implementation_hash, str) or not _SHA256.fullmatch(
            implementation_hash
        ):
            raise TypeError("Materializer implementation_hash must be SHA-256.")
        key = (codec, version)
        if key in self._materializers:
            raise ValueError(f"Materializer {codec!r} version {version} is registered.")
        self._materializers[key] = _RegisteredMaterializer(writer, implementation_hash)

    def get(self, codec: str, version: int) -> _RegisteredMaterializer:
        try:
            return self._materializers[(codec, version)]
        except KeyError as error:
            raise GraphRuntimeError(
                f"No materializer is registered for {codec!r} version {version}."
            ) from error


@dataclass(frozen=True)
class MaterializedProduct:
    """Portable identity record for one local compatibility artifact."""

    name: str
    source: str
    codec: str
    codec_version: int
    codec_impl_hash: str
    path: str
    boundary: str
    sha256: str
    size: int
    content_key: str

    def payload(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "name": self.name,
                "source": self.source,
                "codec": self.codec,
                "codec_version": self.codec_version,
                "codec_impl_hash": self.codec_impl_hash,
                "path": self.path,
                "boundary": self.boundary,
                "sha256": self.sha256,
                "size": self.size,
                "content_key": self.content_key,
            }
        )


@dataclass(frozen=True)
class CandidateIndex:
    """The complete local result of post-run materialization."""

    manifest_key: str
    graph_key: str
    products: Mapping[str, MaterializedProduct]

    def __post_init__(self) -> None:
        object.__setattr__(self, "products", MappingProxyType(dict(self.products)))

    @property
    def key(self) -> str:
        return sha256_domain("candidate-index", canonical_json(self.content))

    @property
    def content(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "schema_version": 1,
                "manifest_key": self.manifest_key,
                "graph_key": self.graph_key,
                "products": {
                    name: self.products[name].payload()
                    for name in sorted(self.products)
                },
            }
        )

    def to_json(self) -> str:
        return canonical_json({**self.content, "key": self.key}).decode("utf-8")


def _relative_output(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise ValueError(
            f"Materialized product path {value!r} is not a safe relative path."
        )
    if value == "candidate-index.json":
        raise ValueError("candidate-index.json is reserved for the candidate index.")
    return path


def _stored_product(
    graph: Graph,
    manifest: RunManifest,
    store: ContentStore,
    product: Product,
) -> object:
    record = manifest.products.get(product.name)
    if not isinstance(record, Mapping) or record.get("status") != "executed":
        raise GraphRuntimeError(
            f"Stored product {product.name!r} was not successfully produced."
        )
    key = record.get("key")
    if product.kind is ProductKind.POPULATION:
        return reconstruct_population(graph, manifest, store, product.name)
    if not isinstance(key, str):
        raise GraphRuntimeError(f"Stored product {product.name!r} has no content key.")
    if product.kind is ProductKind.COORDINATE:
        producer = record.get("supplier")
        if not isinstance(producer, str):
            raise GraphRuntimeError(
                f"Stored coordinate product {product.name!r} has no supplier."
            )
        return store.load_column(key, node_key=manifest.nodes[producer].key)
    if product.kind is ProductKind.WEIGHTS:
        state = record.get("state")
        if not isinstance(state, str):
            raise GraphRuntimeError(
                f"Stored weights product {product.name!r} has no population state."
            )
        if record.get("storage") == "column":
            return store.load_column(key, node_key=manifest.nodes[state].key)
        if record.get("storage") == "frame":
            assert product.entity is not None
            return store.load_frame(
                key, node_key=manifest.nodes[state].key
            ).weights_for(product.entity)
        raise GraphRuntimeError(
            f"Stored weights product {product.name!r} has unknown storage."
        )
    if product.kind is ProductKind.ARTIFACT:
        return store.load_bytes(key)
    if product.kind is ProductKind.VALIDATION:
        return store.load_json(key, kind="validation-outcome")
    raise GraphRuntimeError(f"Product {product.name!r} cannot be materialized.")


def materialize_products(
    graph: Graph,
    manifest_path: str | Path,
    store: ContentStore,
    destination: str | Path,
    registry: MaterializerRegistry,
    outputs: Mapping[str, str],
) -> CandidateIndex:
    """Write requested exports after loading a complete saved run manifest.

    The function writes only below ``destination`` and never performs remote
    publication. The candidate index is written last, so its presence denotes
    a complete set of requested local outputs.
    """

    compile_graph(graph)
    saved_manifest = RunManifest.from_json(Path(manifest_path).read_text("utf-8"))
    if saved_manifest.graph_key != graph_key(graph):
        raise GraphRuntimeError(
            "The saved manifest was produced from a different Graph declaration."
        )
    if saved_manifest.outcome != "success":
        raise GraphRuntimeError("An unsuccessful run cannot be materialized.")
    declarations = {product.name: product for product in graph.products}
    root = Path(destination).absolute()
    if root.is_symlink():
        raise ValueError(f"Candidate directory may not be a symlink: {root}")
    root.mkdir(parents=True, exist_ok=True)
    index_path = root / "candidate-index.json"
    if index_path.exists():
        raise FileExistsError(f"Candidate index already exists: {index_path}")

    materialized: dict[str, MaterializedProduct] = {}
    for name in sorted(outputs):
        product = declarations.get(name)
        if product is None or product.kind is not ProductKind.EXPORT:
            raise GraphRuntimeError(f"Requested product {name!r} is not an export.")
        assert product.source is not None
        assert product.codec is not None
        assert product.codec_version is not None
        source = declarations[product.source]
        relative = _relative_output(outputs[name])
        output_path = root.joinpath(*relative.parts)
        if output_path.exists() or output_path.is_symlink():
            raise FileExistsError(f"Materialized output already exists: {output_path}")
        current = root
        for part in relative.parts[:-1]:
            current /= part
            if current.is_symlink():
                raise ValueError(
                    f"Materialized output traverses a symlink: {output_path}"
                )
            current.mkdir(exist_ok=True)
        binding = registry.get(product.codec, product.codec_version)
        value = _stored_product(graph, saved_manifest, store, source)
        binding.writer(value, output_path)
        if not output_path.exists() or output_path.is_symlink():
            raise GraphRuntimeError(
                f"Materializer for {name!r} did not create the requested path."
            )
        if output_path.is_dir() and any(
            candidate.is_symlink() for candidate in output_path.rglob("*")
        ):
            raise GraphRuntimeError(
                f"Materializer for {name!r} created a symbolic link."
            )
        boundary, digest, size = source_content_identity(output_path)
        content_key = sha256_domain(
            "materialized-product",
            canonical_json(
                {
                    "name": name,
                    "source": product.source,
                    "codec": product.codec,
                    "codec_version": product.codec_version,
                    "codec_impl_hash": binding.implementation_hash,
                    "boundary": boundary,
                    "sha256": digest,
                    "size": size,
                }
            ),
        )
        materialized[name] = MaterializedProduct(
            name=name,
            source=product.source,
            codec=product.codec,
            codec_version=product.codec_version,
            codec_impl_hash=binding.implementation_hash,
            path=relative.as_posix(),
            boundary=boundary,
            sha256=digest,
            size=size,
            content_key=content_key,
        )

    index = CandidateIndex(saved_manifest.key, saved_manifest.graph_key, materialized)
    temporary = root / f".candidate-index.{uuid.uuid4().hex}.tmp"
    temporary.write_text(index.to_json(), encoding="utf-8")
    os.replace(temporary, index_path)
    return index
