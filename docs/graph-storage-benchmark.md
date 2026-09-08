# Graph value-storage benchmark

This benchmark measures the content-store payloads produced by the synthetic
US post-transfer parity fixture. The fixture uses the US entity schema and
executes the US graph kernels over a small, reviewable population.

Run it with:

```shell
uv run --package microcosm-graph pytest \
  packages/microcosm-graph/tests/test_acceptance_h_parity.py::test_h3_us_post_transfer_parity
```

The 2026-09-08 result on `codex/standardize-runtime-graph` is:

| Stored values | Payload bytes |
|---|---:|
| Structural frame | 110,180 |
| Duplicate standalone copies of its coordinates (comparison) | 120,176 |
| Metadata-only coordinate references (implemented) | 0 |
| Ordinary value patches retained for reconstruction | 11,221 |

The earlier representation wrote both the 110,180-byte structural frame and
120,176 bytes of standalone coordinate payloads. The new representation keeps
the frame once and stores each coordinate artifact key as a checked reference
to that frame. This removes 52.2% of the structural value payload while
preserving the coordinate keys used by manifests and investigation tools.

The test constructs the comparison objects from the same values and codec, so
the measurement includes repeated entity-ID arrays and nullable-value storage.
It also verifies that ordinary and value-revision outputs remain standalone,
content-validated patches. Reference loading checks the coordinate identity,
structural-frame identity, node identity, dtype, length, and entity IDs before
returning values.
