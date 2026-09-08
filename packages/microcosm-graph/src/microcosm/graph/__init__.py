"""microcosm-graph: a content-addressed DAG of cell-ownership nodes.

Public API. ``decl`` and ``kernel`` are the frozen interfaces; the runtime
modules implement execution, storage, provenance, and inspection against them.
"""

from __future__ import annotations

from importlib import metadata as _metadata

from .decl import (
    DESCRIPTIVE_FIELDS,
    DTYPES,
    GATE_OUTCOMES,
    MASS_POLICIES,
    PARTITION_DTYPES,
    ROWS_ALL,
    WEIGHT_KINDS,
    ArtifactInput,
    ArtifactOutput,
    ArtifactType,
    CompiledGraph,
    ExpectedContent,
    Graph,
    GraphError,
    Node,
    Owned,
    Ownership,
    Param,
    Product,
    ProductKind,
    Slice,
    SourceRef,
    StructuralDelta,
    WeightTransition,
    compile_graph,
)
from .errors import (
    GraphRuntimeError,
    NodeRejectedError,
    StoreCorruptError,
    StoreMissError,
    StoreUnavailableError,
)
from .graph_source import (
    GRAPH_SOURCE_SCHEMA_VERSION,
    GraphSourceReceipt,
    LoadedGraphSource,
    compiled_graph_from_yaml_file,
    graph_from_yaml_file,
    load_graph_source,
    validate_kernel_registry,
)
from .kernel import (
    ArtifactValue,
    Capabilities,
    Determinism,
    Kernel,
    KernelBase,
    KernelContext,
    KernelRegistry,
    KernelResult,
    KernelRole,
    Numeric,
    NumericScope,
    SeedSource,
    Tolerance,
    source_hash,
)
from .keys import platform_fingerprint
from .randomness import keyed_uniform
from .source_errors import (
    GraphParameterBindingError,
    GraphSourceCompositionError,
    GraphSourceError,
    GraphSourceParseError,
    GraphSourceSchemaError,
    GraphSourceValidationError,
)
from .yaml12 import load_json_strict, load_yaml12, load_yaml12_file, parse_yaml12

__all__ = [
    "ArtifactInput",
    "ArtifactOutput",
    "ArtifactType",
    "ArtifactValue",
    "BoundSource",
    "GRAPH_SOURCE_SCHEMA_VERSION",
    "keyed_uniform",
    "platform_fingerprint",
    "DESCRIPTIVE_FIELDS",
    "DTYPES",
    "GATE_OUTCOMES",
    "MASS_POLICIES",
    "PARTITION_DTYPES",
    "ROWS_ALL",
    "WEIGHT_KINDS",
    "Capabilities",
    "CompiledGraph",
    "ContentStore",
    "Decision",
    "Determinism",
    "ExpectedContent",
    "Graph",
    "GraphError",
    "GraphParameterBindingError",
    "GraphRuntimeError",
    "GraphSourceCompositionError",
    "GraphSourceError",
    "GraphSourceParseError",
    "GraphSourceReceipt",
    "GraphSourceSchemaError",
    "GraphSourceValidationError",
    "Kernel",
    "KernelBase",
    "KernelContext",
    "KernelRegistry",
    "KernelResult",
    "KernelRole",
    "LoadedGraphSource",
    "GraphRunResult",
    "MassRecord",
    "MaterializedProduct",
    "MaterializerRegistry",
    "Node",
    "NodeReceipt",
    "NodeRejected",
    "NodeRejectedError",
    "Numeric",
    "Owned",
    "Ownership",
    "Param",
    "Population",
    "PopulationView",
    "Product",
    "ProductKind",
    "PopulationError",
    "ResumePolicy",
    "RunManifest",
    "CandidateIndex",
    "SOURCE_CODECS",
    "SeedSource",
    "NumericScope",
    "Tolerance",
    "Slice",
    "SourceCodec",
    "SourceCodecRegistry",
    "SourceRef",
    "StoreCorruptError",
    "StoreMissError",
    "StoreUnavailableError",
    "StoreCorrupt",
    "StoreError",
    "StoreMiss",
    "StoreUnavailable",
    "StructuralDelta",
    "WeightTransition",
    "compile_graph",
    "compiled_graph_from_yaml_file",
    "describe",
    "explain_html",
    "graph_from_json",
    "graph_from_yaml_file",
    "graph_document_from_json",
    "graph_document_to_json",
    "graph_to_json",
    "load_graph_source",
    "load_json_strict",
    "load_yaml12",
    "load_yaml12_file",
    "load_source",
    "materialize_products",
    "run_graph",
    "run_graph_source",
    "parse_yaml12",
    "reconstruct_population",
    "source_hash",
    "validate_kernel_registry",
]

_FRAME_SERIES = "0.1"


def _check_frame_version() -> None:
    try:
        version = _metadata.version("microcosm-frame")
    except _metadata.PackageNotFoundError:
        return
    if not version.startswith(_FRAME_SERIES + "."):
        raise ImportError(
            f"microcosm-graph requires microcosm-frame {_FRAME_SERIES}.x, found "
            f"{version}."
        )


_check_frame_version()

from .codecs import (  # noqa: E402 - check dependency series before runtime import
    SOURCE_CODECS,
    BoundSource,
    SourceCodec,
    SourceCodecRegistry,
    load_source,
)
from .executor import NodeRejected, run_graph  # noqa: E402
from .explain import explain_html  # noqa: E402
from .manifest import Decision, NodeReceipt, PopulationView, RunManifest  # noqa: E402
from .materialize import (  # noqa: E402
    CandidateIndex,
    MaterializedProduct,
    MaterializerRegistry,
    materialize_products,
)
from .population import MassRecord, Population, PopulationError  # noqa: E402
from .reconstruct import reconstruct_population  # noqa: E402
from .runner import GraphRunResult, run_graph_source  # noqa: E402
from .serialize import (  # noqa: E402
    graph_document_from_json,
    graph_document_to_json,
    graph_from_json,
    graph_to_json,
)
from .store import (  # noqa: E402
    ContentStore,
    ResumePolicy,
    StoreCorrupt,
    StoreError,
    StoreMiss,
    StoreUnavailable,
)
from .view import describe  # noqa: E402
