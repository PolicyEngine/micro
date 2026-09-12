# Amendment 20 — keyed draw streams (lane journal)

Branch: `amend-keyed-seed-and-uniform-draws`, cut from `origin/main` at `3094bfe84`.
Worktree: `~/PolicyEngine/_worktrees/microcosm-amend-keyed`. No push, no new branches.
Platform of record for H1 pins: **arm64/darwin/py3.14** (Python 3.14.4) — the
fixture's authoring platform.

## State

Implementation, tests, pins, charter and changelog are landed and committed.
`packages/microcosm-graph/tests` and `packages/microcosm-fit/tests` are green.
One item is deliberately left red and reported rather than fixed: see
**Open for decision** below.

## Done

1. `graph/kernel.py`: `SeedSource.KEYED` plus the `KernelContext.rng` docstring.
   `ArtifactValue` / `KernelContext.artifacts` deliberately NOT brought over.
2. `graph/randomness.py` (new, 69 lines): `keyed_uniform`, taken verbatim from
   `origin/microcosm-us-launch-integration-20260909`.
3. `graph/__init__.py`: `keyed_uniform` exported, inserted in sorted position
   among the lowercase callables (`graph_to_json`, `keyed_uniform`, `load_source`).
4. `fit/qrf.py`: `_draw_target_from_uniforms` + `predict_from_uniforms`, taken
   verbatim from the same branch (`6e3907f86`); the diff applied with no conflict.
5. `docs/graph-interface.lock`: `kernel.py` re-recorded
   `eaf07da2… → 3483d091b03b19ae35c0268c01cb9e0f76c4cd63742083130567321d70da6048`.
   The lock is plain `shasum -a 256` of the file bytes (confirmed against the
   unchanged `decl.py` line).
6. Tests: `test_graph_randomness.py` (new), `SeedSource.KEYED` contracts in
   `test_graph_kernel_contract.py`, `test_qrf_stateless.py` (new, verbatim from
   the integration branch), a `QRFKernel` non-widening guard in microcosm-fit's
   `test_kernels.py`, and `test_graph_parity_pins.py` (new).
7. `tools/graph_parity_repin.py` (new) + the re-pinned `fit.qrf` fixture.
8. `docs/graph-acceptance.md` amendment 20 + a `changelog.d` fragment.

**No `test_acceptance_*.py` file was edited at all**, so the "acceptance-suite
edit is its own commit" rule never had to be exercised.

## Key findings (verified this session)

- The integration branch carries **no** executor change for `KEYED` and **no**
  `fit/kernels.py` change. `grep` over `origin/main`'s `executor.py` finds no
  `seed_source` branch. Honouring `KEYED` therefore required no executor edit.
- `QRFKernel.implementation_hash()` hashes `microcosm.fit.qrf`'s module bytes,
  so editing `qrf.py` moved `fit.qrf@1`'s implementation hash
  (`02db8f5c… → d1f8b192…`) and all three pinned platform node keys.
- **Foreign-platform node keys are locally derivable.** Re-deriving the three
  OLD pinned keys from this Mac with the OLD implementation hash and only the
  fingerprint string varied reproduces all three exactly, so the platform
  reaches a key as that string and nothing else.
- **`tools/graph_parity_fixtures.py` must not be edited.** `ParityCsvSource`
  and `ParityRulesEngine` are defined there, so its bytes are inside
  `ParityCsvSource.implementation_hash()` and
  `SimulateRulesKernel.implementation_hash()`. Measured: adding the re-pin code
  there moved the calibrate node key `184ccd0a → f8c9ed4b` with its
  implementation hash unchanged. The re-pin logic therefore lives in a sibling
  module. Reverted.
- `generate()` resets `pins["platforms"]` to the local platform alone, so a bare
  regeneration would have dropped both `x86_64/linux` pins and silently put H1
  on its off-platform branch there (which asserts no bytes).
- `direct.csv` is byte-identical before and after on every platform
  (`7b8dbd56c91ee71552ff6d892a42c56494b1813fb5d4b11553a8a8ccc9b90dca`).

## Open for decision (Max / the merge owner)

1. **`tools/spec_engine_coverage.py --check` is red on this branch** (exit 0 on
   `origin/main`, exit 1 here) and so is
   `packages/microcosm-build/tests/test_spec_engine_inventory_coverage.py::test_us_inventory_is_structure_exact_and_complete`.
   Bisected to `packages/microcosm-fit/src/microcosm/fit/qrf.py` alone:
   `microcosm.fit.qrf` is in `_QRF_KERNEL_MODULES`
   (`spec_engine/seeds.py:353-362`), which feeds the `regime_gated_qrf` kernel
   attestation's `source_sha256`, the seed protocol digest and the seed-map
   digest. `SeedSource.KEYED`, `randomness.py` and the export move none of it.
   The lane brief says report, do not re-pin, so the branch carries the drift.
   The re-pin recipe is tested and written up in the lane report.
2. **Amendment numbering.** `main`'s list ends at 18, so 19 is the next free
   number by its own arithmetic. The brief assigns 20 (the artifacts lane owns
   19). Two unmerged commits on the
   `candidate-quality-producer-integration-20260905` family already claim both:
   `3ff92b0ae` = 19 ("Typed artifacts and stable draw coordinates", which
   bundles this lane's subject), `d2043d85e` = 20 ("Failed typed evidence
   remains a failed gate"). Neither is on `main` or on the integration branch.

## Next

- Nothing blocking. A reviewer should decide (1) and (2) above.
