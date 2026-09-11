# Amendment 20 — keyed draw streams (lane journal)

Branch: `amend-keyed-seed-and-uniform-draws`, cut from `origin/main` at `3094bfe84`.
Worktree: `~/PolicyEngine/_worktrees/microcosm-amend-keyed`. No push, no new branches.
Platform of record for H1 pins: **arm64/darwin/py3.14** (the authoring platform).

## State

Starting. Reconnaissance complete; nothing implemented yet.

## Scope (what this lane lands)

1. `graph/kernel.py`: `SeedSource.KEYED` + the `KernelContext.rng` docstring change.
   **Not** `ArtifactValue` / `KernelContext.artifacts` — a separate lane owns those.
2. `graph/randomness.py` (new): `keyed_uniform` and its coordinate encoding.
3. `graph/__init__.py`: export `keyed_uniform`, inserted in sorted position.
4. `fit/qrf.py`: `_draw_target_from_uniforms` + `FittedRegimeGatedQRF.predict_from_uniforms`.
5. `docs/graph-acceptance.md`: amendment 20 entry.
6. `docs/graph-interface.lock`: re-record `kernel.py`.
7. Tests: `SeedSource.KEYED` contract; `keyed_uniform` units; `predict_from_uniforms` units.
8. H1 parity: regenerate `fit.qrf` pins (implementation hash moves because `qrf.py`
   changed); `direct.csv` must stay byte-identical.

## Reconnaissance findings (verified, 2026-09-11)

- The integration branch adds **no** amendment text and **no** executor change that
  honours `KEYED`: `git diff origin/main origin/microcosm-us-launch-integration-20260909
  -- .../executor.py` is entirely artifacts / lazy population retention / execution
  metadata. `fit/kernels.py` has **no** diff on that branch. So the minimal coherent
  subset for `KEYED` touches neither file.
- `QRFKernel.implementation_hash()` hashes `microcosm.fit.qrf`'s module bytes
  (`packages/microcosm-fit/src/microcosm/fit/kernels.py`), so editing `qrf.py`
  moves the `fit.qrf@1` implementation hash and every `fit.qrf` node key.
- `node_key` folds in `kernel_impl_hash` **and**, for `PLATFORM_BITWISE`, the platform
  fingerprint (`graph/keys.py`). `fit.qrf/pins.json` pins three platforms
  (`arm64/darwin/py3.14`, `x86_64/linux/py3.13`, `x86_64/linux/py3.14`); all three
  node keys move, and only the local one can be produced by running the graph.
- `tools/graph_parity_fixtures.py generate()` **resets** `pins["platforms"]` to the
  local platform only, so a bare regeneration would silently drop the two x86_64 pins
  and orphan their `direct.csv` files, downgrading CI on Linux to the off-platform
  branch of `test_h1_kernel_parity` (which asserts no bytes).
- C4's static check (`test_acceptance_c_seeds.py::test_c4_seed_from_identity`) ASTs
  every `microcosm/graph/**/*.py`: no `RandomState`, no `*.random.seed`, and any
  `default_rng` call takes exactly one argument. `randomness.py` uses none of these.
- New test files must sit flat in `packages/<shard>/tests/` and be `test_*.py`;
  `microcosm-graph`/`microcosm-fit` classify to fast `rest` and engine `us-am`
  (`tools/ci_test_groups.py`), so no lane bookkeeping is needed beyond `--verify`.

## Done

- (nothing yet)

## Next

- Red-first tests, then the implementation, then the pins.
