# microcosm-graph

`microcosm.graph.Graph` is the single declaration compiled and executed for one
run. Versioned YAML is the human-authored source; a generated, versioned Graph
JSON document is an optional exact serialization for evidence and interchange.

A `Node` declares the slices it reads, the cells it owns, its parameters,
and the kernel that computes it. Its key is the hash of that declaration,
the artifact keys of its inputs, and the kernel's implementation hash. The
executor projects immutable input views, runs the kernel, patches only the
owned positions with a storage-preserving assignment, and memoizes every
output in a content-addressed store keyed by node key. Seeds derive from
node keys. The graph-bound run manifest records the semantic graph identity,
authored YAML receipts, parameters, verified source bindings, node receipts,
named products, and signed human decisions. Actual dataframe values and typed
artifacts remain in `ContentStore` and are referenced by content keys.

`docs/graph-acceptance.md` is the definition of done: every property there
is an executable test, committed red, and the shard is finished when none
is marked `xfail`.

Module map:

| Module | Owns |
|---|---|
| `decl.py` | Frozen declarations (`Graph`, `Node`, `Slice`, `Owned`, `SourceRef`) and `compile_graph` — **frozen interface** |
| `kernel.py` | `Kernel` protocol, `KernelContext`, `KernelResult`, `Capabilities`, `KernelRegistry`, `source_hash` — **frozen interface** |
| `canonical.py` | Canonical JSON of the normative projection; domain-separated SHA-256 |
| `keys.py` | Node key and artifact key derivation |
| `store.py` | `ContentStore`: atomic content-addressed artifacts, codecs, resume policy |
| `population.py` | Immutable population versions: `Frame` + owner map + weight lineage + mass ledger |
| `executor.py` | `run_graph`: projection, patching, ownership enforcement, receipts |
| `manifest.py` | `RunManifest`, `NodeReceipt`, human decision records |
| `graph_source.py` | Restricted YAML loading, declared parameter binding, and deterministic module composition |
| `serialize.py` | Optional canonical, versioned Graph JSON serialization |
| `reconstruct.py` | Named population reconstruction from a Graph, manifest, and content store |
| `materialize.py` | Versioned post-run codecs and the local candidate index |
| `runner.py` | One-root helper that compiles once, executes once, saves evidence, then materializes locally |
| `view.py` | `describe(node)`: the one-screen view |

The package depends on `microcosm-frame` plus its YAML and JSON Schema parsing
libraries. It does not depend on `microcosm-build` or a country package.
Kernels that wrap fitting, calibration, or a rules engine live in their owning
packages and register here.

## Author and run a graph

The root YAML may contain declarations directly or list exact relative module
paths. Modules organize source text only: they combine into one `Graph` and are
never compiled or executed independently.

```yaml
schema_version: 1
country: example
modules: [sources.yaml, population.yaml]
parameters:
  period:
    type: integer
    required: true
products:
  - name: example.final
    kind: population
    target: {node: finalize}
  - name: example.h5
    kind: export
    target: {product: example.final}
    codec: policyengine-h5
    codec_version: 1
```

`load_graph_source(path, parameters=...)` parses the restricted YAML 1.2
subset, validates the closed packaged schema, resolves the explicitly listed
modules, and freezes declared parameter values. It does not import code named
by YAML, read runtime sources, expand environment variables, or access the
network. `compile_graph` derives execution order from declared dependencies,
not YAML order.

Use `run_graph_source` when a caller wants the complete sequence in one API:

```python
result = run_graph_source(
    "graph.yaml",
    parameters={"period": 2026},
    sources={"survey": survey_path},
    store=ContentStore("run/store"),
    kernels=registry,
    manifest_path="run/manifest.json",
    graph_json_path="run/graph.json",  # optional generated evidence
)
```

The helper selects one root, compiles one `CompiledGraph`, calls `run_graph`
once, and saves the completed manifest. Country-specific Python code registers
kernel implementations and supplies source paths; it does not define a second
execution plan.

## Reconstruct and materialize stored products

Population products can be reconstructed after the original process exits:

```python
manifest = RunManifest.from_json(Path("run/manifest.json").read_text())
frame = reconstruct_population(graph, manifest, store, "example.final")
```

This needs no source path, kernel registry, or kernel execution. It restores
structural frames and applies stored ordinary and value-revision column patches
in canonical execution order through the product's declared node. Structural
coordinate keys refer to their one stored frame instead of duplicating its
values; ordinary patches remain standalone exact-value objects. See
`docs/graph-storage-benchmark.md` for the US fixture measurement.

Large compatibility products are written only after a complete manifest has
been saved. A `MaterializerRegistry` binds an exact declared codec/version to a
deterministic local writer and its implementation hash. `materialize_products`
loads named stored values, writes below the supplied candidate directory, and
writes `candidate-index.json` last with the manifest identity, graph identity,
codec identity, and output content identities. It has no publication behavior;
uploading files, modifying remote release references, or sending notifications
belongs to a separate command.

## Reusable typed artifacts

A fitted model can be a dependency across population versions without owning a
population column. `ArtifactOutput("model", ArtifactType("example.model", 1))`
declares a required byte output. A consumer names it with
`ArtifactInput("fitted", "train", "model", ArtifactType("example.model", 1))`
and reads `context.artifacts["fitted"].payload`. The executor exposes only the
declared aliases as immutable `ArtifactValue` objects, including producer
identity and numeric scope. A nominal type/version is an interface contract;
the consuming kernel must validate its decoded payload. Existing opaque
model/diagnostic bytes remain supported, but cannot satisfy an edge unless the
producer declares their type.

The compiler adds these edges to dependency ordering, cycle checks, and gate
ancestry. A change to recipient inputs can reuse the fitted producer. Typed
node cache records use schema 2. Graph-bound runs use manifest schema 4; older
typed runs remain readable as schema 3. Legacy nodes omit the new empty
declarations from keys and JSON, and legacy runs retain manifest schema 2.
Cache reload validates the same contracts as fresh execution.

Numeric contracts are deliberately restrictive: bitwise artifacts permit any
consumer class; platform-bitwise artifacts require platform-bitwise consumers;
tolerance-bound artifacts require tolerance-bound consumers with their own
output tolerance. Mixed platform/tolerance artifact inputs are refused. The
executor does not infer error propagation through an arbitrary computation.

## Stable random coordinates

Opt-in kernels declare `SeedSource.KEYED`, put their stream tuple in normative
node parameters, and include `microcosm.graph.randomness` in their implementation
hash. The existing node-key RNG behavior remains available unchanged.

```python
from microcosm.graph import keyed_uniform

stream = ("sha256-u53-v1", "comparison", 0, 42)
values = keyed_uniform(
    stream=stream,
    keys=[(person_id, "mortality", 2027, 0) for person_id in person_ids],
)
```

The read-only float64 result is stable through reordering, chunk boundaries, and
unrelated inserted identities. Duplicate coordinates intentionally repeat a
draw. Integer and string identities differ. The versioned algorithm hashes a
canonical, type-tagged coordinate tuple with the stream and maps the leading
53 digest bits to `[0, 1)`. This is an explicit experiment stream independent
of cache identity; changing its normative specification still invalidates the
application node.
