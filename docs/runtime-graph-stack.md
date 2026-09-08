# Runtime graph stack ownership and source identity

This document records the development boundary for the
`standardize-runtime-graph` change. It is an implementation note for the
stacked pull request, not a second graph specification.

## Stack ownership

The child branch was created from draft PR #873 at commit
`ee617ea672a7a81b4a86b3c03091a29f084682d4`. Its pull request base is Max
Ghenis's `model-artifact-graph-20260904` branch. The child branch is
`codex/standardize-runtime-graph` and its push upstream must be
`origin/codex/standardize-runtime-graph`.

No push command for this change may name or force-update
`model-artifact-graph-20260904`. That branch is an immutable dependency of the
child changes.

When PR #873 changes:

1. fetch `origin/model-artifact-graph-20260904` and record its new commit;
2. rebase the independently owned child branch onto that commit;
3. resolve only conflicts in the child changes, leaving upstream conflicts
   with `main` for PR #873's owner;
4. update the recorded commit in this document and the child pull request;
5. rerun typed-artifact characterization and the complete child validation
   suite; and
6. push the rebased child branch with a lease that names only
   `origin/codex/standardize-runtime-graph`.

After PR #873 merges, rebase the child branch onto the resulting `main`
commit, confirm that the semantic diff relative to #873 is unchanged, rerun
validation, and change the child pull request base to `main`. The child branch
remains the only branch that this work pushes.

## Typed-artifact baseline supplied by PR #873

The recorded PR #873 commit supplies the following interfaces:

- `ArtifactType`, `ArtifactInput`, and `ArtifactOutput` declarations;
- compiler-validated typed byte dependencies between nodes, including nodes
  attached to different population states;
- typed input identities in consuming node keys;
- immutable `ArtifactValue` objects in the kernel context;
- typed input and output descriptors in node receipts and schema-version 3
  manifests;
- content-store loading and integrity verification before a consumer runs;
- lossless Graph JSON serialization of typed declarations;
- separate QRF training and application kernels; and
- stable keyed randomness based on entity identifiers and draw coordinates.

The focused tests in `test_artifact_edges.py`, `test_graph_models.py`, and
`test_keyed_randomness.py` characterize these behaviors. The runtime-graph
change builds on those interfaces rather than replacing them.

## Reviewed source identities and runtime content identities

PR #853 defines reviewed identities for the exact file or archive boundary
named by a source manifest and, where applicable, a Chronicle registration.
Those reviewed records are repository configuration. The graph runtime must
refer to them without copying their digest values into graph YAML.

The graph runtime calculates a separate path-independent identity for the
bytes supplied to a `SourceRef`. A regular file is identified by its complete
byte sequence. A directory source is identified by the deterministic sequence
of relative file names and file bytes accepted by its declared codec. The
calculated identity is an execution fact and is recorded in the run manifest.

The two identities have different purposes and may cover different byte
boundaries:

| Record | Byte boundary | Authority | Runtime action |
| --- | --- | --- | --- |
| Reviewed expected identity | The file, archive, or archive member declared by the source manifest | PR #853 source metadata | Verify before the first consumer runs |
| Calculated graph identity | The complete file or deterministic directory payload bound to `SourceRef` | `microcosm.graph` source codec | Use in node identity and record in the run manifest |
| Codec implementation identity | The implementation that decodes the bound payload | Registered graph codec | Use in every consuming node identity |

A source binding therefore records the reviewed expectation and the calculated
execution identity as distinct fields. If their boundaries are the same, the
runtime compares the digests directly. If a reviewed archive contains the
runtime member or extracted directory, the source metadata must declare that
relationship explicitly; the runtime must not treat unrelated hashes as equal.
Graph YAML references the reviewed source record by stable identifier and does
not maintain an independent copy of its digest.
