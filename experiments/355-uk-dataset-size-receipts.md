# #355 dataset-size receipts: 55,000 households by informed L0 on the #877 machinery

Plan of record: `repos/uk-355-size-experiment-plan.md` (approved 2026-09-08, two rounds). These
receipts record what was run, on which pinned inputs, and what was measured. They are candidate
evidence only: no size run is releasable (`--release-candidate` is refused with
`--dataset-households`), no gate threshold is loosened, and nothing here promotes an artifact.
Kept separate from the #762 receipts (`experiments/762-uk-rowwise-candidate-receipts.md`).

Rulings carried in (María, 2026-09-08): K=15 cloning stays in front of the selection (the dense
joint solve runs on the whole 792,690-row pool; the size machinery then keeps 55,000 of those
rows); `--epochs 2000` on size runs (drives the dense solve, every L0 probe and the refit); skip
holdout on the first 55k run; no dense baseline on the new inputs unless the rough comparison with
R17 shows large deviations; engine policyengine-uk 2.94.0; Chronicle feed 6fb700e.

## Step 0 — #877 CI green before any run

CI run 34216367053 on 56aa4e25 (the spec-engine re-pin) was red in four jobs with one cause: the
`solve.py` edit in #877 moved two more source-hashed identities.

| lane | test | pin | fix |
|---|---|---|---|
| `fast (rest)` ×2 | `microcosm-graph/tests/test_acceptance_h_parity.py::test_h1_kernel_parity`, `test_graph_serialize.py::test_generated_parity_graphs_bind_real_kernels_and_direct_bytes` | `calibrate.adam@1` implementation hash a7a0330f… → d24fc41d… (`source_hash` over the calibrate modules) | H1 fixture regenerated on its authoring platform (arm64/darwin/py3.14; numpy 2.4.6, pandas 3.0.3, scipy 1.17.1, torch 2.12.0) with `tools/graph_parity_fixtures.py`; only `calibrate/pins.json` taken (direct bytes and graph unchanged). The generator also resets `fit.qrf/pins.json`'s platform map to the authoring platform, dropping its two linux pins; that file was reverted. |
| `engine-us (us-am)` ×2 | `test_us_multispine_pool_tool.py::test_constants_adapter_equals_live_constants_and_stays_out_of_identities` | US `spec_sha256` 9db29b4d… → 9db2d6db… | re-pinned |

Commit 1b0583b7. Local: graph 336 passed, multispine pool tool 187 passed, spec-engine pin files 50
passed. Pushed with C1/C2 below as d4043ec7; CI run 34223080395.

The run on d4043ec7 then failed in the `wheels` lane only (both Python versions): the size CLI test read
the exported H5 through `pd.HDFStore`, and the wheels venv has no pytables (7,963 passed, 587 skipped, that
one failure). The file's convention is `pytest.importorskip("tables")` + `importorskip("h5py")` at the top of
every CLI test; the size test lacked them, and the two new evaluation test files write PyTables-format H5
the same way. All three now skip without pytables (verified by blocking the import locally); the workspace
and engine lanes, which have pytables, run them in full.

The run on fb85c8fe then failed only in the two UK lanes on one new test: the evaluation command timed
each downstream script with `/usr/bin/time -l`, a BSD flag GNU `time` rejects with exit 125, so on the
linux runners a failing stub could not surface its own exit code. Replaced by an in-process rusage shim
(the child script runs in a child interpreter that reports its own peak resident set in bytes on exit;
wall time measured by the caller; exit code the script's own), commit e8f7c6f2, pushed with the
`--selection-pi-hi` knob (a6b1e0ca) and the by-name refusal (b1d206d6); CI run 34239851890.

## Code landed on the branch before the runs

- **C1 (d4043ec7)** — a size run keeps the dense joint solve it was cut from: `UKRowwiseDoctrineSolve.dense_reference` (weights, initial weights, local and national diagnostics, losses, past-cap censuses; the evidence labelling moved into `_doctrine_solve_evidence` and runs for both results), written as `dense_reference_diagnostics.csv` (every target's dense estimate with a `grain` column) and summarised under `solve.dataset_size.dense_reference`; and the selection itself as `dataset_size_selection.csv` (`pool_row_index, household_id, clone_index, design_weight, inclusion_probability, certainty, ht_baseline_weight, refit_weight`). Both are listed under `outputs` with digests; dense runs are unchanged. The dense reference is byte-identical to a standalone dense run on the same inputs, seed and epochs, so the size-only delta needs no second full-pool solve.
- **C2 (d4043ec7)** — `--selection-seed` (requires `--dataset-households`, defaults to `--seed`) seeds only the informed L0 search, the exact-count draw and the refit, threaded through the holdout as well; recorded as `parameters.selection_seed` and in the size receipt's `seed`. `--seed` still governs the ladder clone assignment and the dense solve, so two selections compare on one pool and one dense reference.
- **C3/C4 (251e67d4)** — evaluation library `uk_runtime/size_evaluation.py` (`load_run`, `run_acceptance`, `fit_tables`, `weight_tables`, `area_support_tables`, `gate_table`, `paired_targets`, `dense_reference_deltas`, `frozen_vs_recomputed`, `footprint`, `summarize` with `PRE_REGISTERED_OUTCOMES_V1`) and the one command `tools/evaluate_uk_dataset_size.py` (steps `00-run-acceptance`, `10-dense-reference`, `20-vs-reference/<label>`, `30-incumbent-score`, `40-incumbent-surface`, `50-downstream`, `90-summary` into `<run>/evaluation/`, each with `receipt.json`); `_fit_by_family` lifted into `uk_runtime/diagnostics.py::uk_fit_by_family`. Implemented by Codex from `.codex-work/PLAN.md`; its final report was lost when the companion broker restarted, so the review was done on the diff directly (lift byte-for-byte; grain rule, `time -l` parsing, multiplier inference matching `id_multiplier_for_values` with the manifest self-check, red-row mapping through family/area/metric, the R18 evaluator's `national_rows`/`candidate_estimate` shape, flags exactly as pre-registered) and verified independently: ruff, format, `ci_test_groups --verify`, 88 tests across the four UK rowwise/evaluation files.
- **Feasibility diagnostic (4bbd01f6)** — see S1 below.

## Rebase onto main after #879 (María's instruction before any further push)

Main moved by PR #879 (SPI income coherence, e07a4735; 13 commits, 42 files) after the branch was
cut. Intersection with the branch: one file, one line — the UK country-bundle digest in
`test_spec_engine_country_bundles.py`, which both sides had moved (#879 through `uk/spec/sources.yaml`
and `country_package.json`; this branch through `solve.py`'s seed-protocol attestation). Rebased
(`git rebase origin/main`), resolved that line, then re-cut it once for the combined tree:
d57d248fe947c3215850020bb16c6def308e373c92afa433395c81e8eda91fce (commit 573c4b43). The am/be
digests, the loader golden vector, the seed-protocol/seed-map digests and the committed US coverage
report were unchanged by #879 (49/50 pin tests passed before the cut). Rebased heads: acbc6332 (size
machinery), 08ae0caf (spec re-pin), 366b8263 (H1 + US spec re-pin), cfd57e03 (C1/C2), 12b9a7ce
(feasibility diagnostic), 6ec596c3 (C3/C4), 573c4b43 (UK digest re-cut).

Isolated re-verification instead of the full suite (her call: the conflict surface is minimal): the
four spec-engine pin files; graph H1 parity and serialisation; the multispine pool-tool test (US spec
digest); the branch's own suites (calibrate, local rowwise, rowwise candidate, informed gates, the two
evaluation tests); and the battery neighbours #879 touched (country spec, local gate battery, gate
battery contract pins, terminal gates, battery bindings). Results on the rebased tree: spec-engine pin
files 50/50 after the one re-cut; graph H1 parity + serialisation + multispine pool tool 195 passed;
calibrate + local rowwise + rowwise candidate + informed gates + the two evaluation tests 313 passed;
battery neighbours 231 passed. Pushed 2026-09-08 (force-with-lease from d4043ec7 → 573c4b43); PR #877
MERGEABLE on main with 7 commits; CI run 34230891965 (the earlier run 34223080395 on d4043ec7 had
every engine lane and the fast trade/rest lanes green when superseded). CI runs the full lanes on the push.

#879 also changed the SPI income spine stage (`hmrc_spi_income_spine` gained `donor_income_period`
2022 and `income_uprating_variables` in `source_stages.json`; `spi_income.py`, `spi_spine.py`), so
spine-o is stale on the rebased tree: **spine-p** is rebuilt from the clean tree at 573c4b43 (same
recipe) and S0 re-run on it before any further size run.

## P0 — inputs and pins

| input | path | sha256 | note |
|---|---|---|---|
| Chronicle consumer artifact 6fb700e | `data/ukds/acceptance/chronicle-uk-artifact-6fb700e/consumer_facts.jsonl` | 6ae49d7d7ab297df25a0b9bfe2d6776827c672d284fbb360957fe8337089549f | 128,717 rows; manifest dcda51d6496aea67f768a284e7955c7520e7c8b91e2bed3569f247567b7153f0; the feed main's registers compile against. Upstream chronicle main is 7 commits ahead; the one fact change (#250, UC family-type totals 2023–2025, merged 2026-09-08) is not consumed by any register and is the next re-pin candidate, not part of this experiment. |
| OA ladder | `populace-877/build/uk/uk_oa_ladder_2021.npz` | 9c6d56b90d2e975d750106b175020a54c5ec6acf42ef8909d304a9d7fc3868a7 | copied from `populace-762b/build/uk/` |
| spine-o | `data/ukds/acceptance/spine-o-355/spine-o.h5` | 3ef32dfb3e8a86e1c93a8f74b463492fe8eeb81d10ebc746c7b396aa47c2eeca | built 2026-09-08 from the clean tree at d4043ec7 (`build_twin.sh` recipe, all licensed tabs; 352 s wall, 7.05 GB peak): 28 stages with `age_tail` second and `uc_deduction_attributes` present, policyengine-uk 2.94.0, 15/15 spine gates passed, `tax_free_childcare_spend_routed_share` nonzero share 1.0, 52,846 households / 61,234 benunits / 113,626 persons, mass 29,247,433.0; sidecar `spine-o.build.json`. Rebuilt because spine-m (R17) predates #850, #842 and #874; see below |

| spine-p | `data/ukds/acceptance/spine-p-355/spine-p.h5` | ae83e3075d1fd99adf3dbb1ea8bbf96398fa48b8eb251b802ae682ada03fb19a | built 2026-09-08 from the clean tree at 573c4b43 (rebased onto #879; same recipe; 424 s wall, 3.84 GB peak): 28 stages, `age_tail` second, `uc_deduction_attributes`, policyengine-uk 2.94.0, 15/15 spine gates, TFC routed share 1.0, 52,846 households / 61,213 benunits / 113,590 persons (the #879 SPI donor change moves 21 benunits and 36 persons against spine-o), mass 29,247,433.0. **The spine every size run from here stands on.** |

Why the spine was rebuilt: R17 stood on spine-m (27 stages, engine 2.92.1, feed 1cab809). Main since
then added `uc_deduction_attributes` and the WAS debt columns (#850), moved `age_tail` second with
int64 age (#842), and added `tax_free_childcare_spend_routed_share`, the `hmrc.tfc.*` and DfT bus
targets, the 6fb700e feed pin and the 2.94.0 engine floor (#874). No spine on disk carried the TFC
column.

## Runs

Runner: `data/ukds/acceptance/355-dataset-size/run_size_candidate.sh <name> [--prev <row>] <driver args>`
(spine-o, ladder, 6fb700e feed, seed 42, `/usr/bin/time -l`, log copied into the run dir). Root
`data/ukds/acceptance/355-dataset-size/spine-o/`. Preflight `--env` on the pins: OK.

### S0 — dry run (`--dry-run --dataset-households 55000 --epochs 2000`)

Exit 0, 96.9 s, 6.0 GB. Pins bound; plan reports the joint surface 20,430 targets × 792,690 households
(K=15 clones of 52,846), `parameters.dataset_households 55000`, `epochs 2000`, `engine_blocks 1`, the
resolved vintages (UC 2025-05, HMRC 2023, ONS housing 2021/2022/2025-12, ONS population 2024).
No files written (dry runs never do).

### S1 — rehearsal (`--dataset-households 55000 --epochs 100 --skip-holdout`, chained on R17's row)

**Refused at the exact-count draw** after 1,542 s (25.7 min; 9.48 GB peak): the dense solve and the
informed L0 budget search completed (100 epochs each; `git_dirty` true because the evaluation tool was
being written in the same tree — a rehearsal, so noted and accepted), then
`microcosm.calibrate.exact_k._draw_boundary` raised

> degenerate boundary mass: proportional normalization would require a boundary inclusion
> probability greater than one; adjust pi_hi or k.

Logbook row d15c0224… (disposition `failed`, phases reached through `targets_bound`, error receipt
`logbook-receipts/…/error.json`). Mechanism: `select_exact_k(pi, k, pi_hi=1.0)` treats only exact-one
gates (the protected carriers) as certainties, scales every other gate's open probability to the
remaining draw size `m`, and refuses when the largest scaled value exceeds one — i.e. when
`m · max(pi_boundary) > Σ pi_boundary`. The L0 budget search stops when the **count** of
not-fully-closed gates is within 5 % of 55,000; with gates only partly polarised that count sits above
the open-probability **mass**, so the boundary mass fell short of the draw. The refusal carried no
numbers, so a feasibility diagnostic was added to `refit_uk_dataset_size` (boundary mass, largest
boundary gate, feasibility at `pi_hi=1`, the largest feasible household count at `pi_hi=1`, the
smallest feasible `pi_hi` on a fixed grid, gate quantiles) — attached to the refusal and to the size
receipt on success — and the rehearsal is re-run below. This is a design ruling for #877, not a run
setting: the US exact-k ladder release runs with `pi_hi = 0.95` (`tools/build_us_exact_k_ladder_release.py`),
while the UK size plan deliberately pins `pi_hi = 1` ("no post-hoc promotion of learned boundary scores").

### S1b — rehearsal re-run with the feasibility numbers (same inputs, seed 42, epochs 100, chained on S1's row)

**Refused at the same point** after 1,592 s (26.5 min; 8.49 GB peak; commit 4bbd01f6). The dense solve
and the L0 budget search are deterministic on the same inputs, so the refusal is the same; the
diagnostic now says why:

| quantity | value |
|---|---|
| pool households | 792,690 |
| requested households (k) | 55,000 |
| protected carriers = certainties at `pi_hi = 1` | 9,869 |
| boundary draw m = k − certainties | 45,131 |
| budget search stopped at `n_nonzero` (count of not-fully-closed gates) | 52,490 (inside the ±5 % band round 55,000) |
| total open-probability mass Σπ | 45,743 |
| boundary mass Σπ (π < 1) | 35,874 |
| largest boundary gate | 0.9982 |
| gates with π ≥ 0.5 / 0.9 / 0.99 / 0.999 | 36,527 / 25,267 / 10,761 / 9,869 |
| π quantiles p50 / p90 | 0.0063 / 0.053 |
| learned λ | 4.2e-06 |
| feasible at `pi_hi = 1`? | no: m · max π = 45,048 > 35,874 |
| largest feasible k at `pi_hi = 1` on these gates | 45,809 |
| smallest feasible `pi_hi` on the grid {0.999 … 0.5} | 0.5 (0.7 fails by 3 %: 22,664 × 0.7 = 15,865 > 15,329) |

Reading: the budget search hit its target on the **count** of not-fully-closed gates (52,490), but the
**expected number of open gates** — the mass the exact-count design can draw from — is 45,743, a fifth
short of 55,000. Most of the 782,821 boundary gates are near-closed (median π 0.006) yet not closed,
so they count towards `n_nonzero` while contributing almost no mass; the ~15,000 gates between 0.9 and
0.99 carry most of the boundary mass and cannot be scaled up to fill a 45,131 draw. With `pi_hi = 1`
the draw is feasible only up to ~45.8k households at this polarisation. The US precedent (`pi_hi =
0.95`) would not rescue it either at 100 epochs — only thresholds at or below about 0.65 are feasible
here. Whether 2,000 epochs polarises the gates enough to close the gap is unknown; the count-versus-
mass mismatch in the stopping rule remains regardless of epochs. Ruling requested from María (see
the session report): (A) expose `pi_hi` as a candidate-run knob; (B) make the size selection's budget
search stop on open-probability mass Σπ ≈ k instead of `n_nonzero`, which keeps `pi_hi = 1` and makes
the draw feasible by construction; (C) accept k ≈ Σπ; (D) spend the 2,000-epoch run to see. Nothing
was clamped; Logbook row for S1b is chained on S1's.

### S0 on spine-p — dry run after the rebase (`--dry-run --dataset-households 55000 --epochs 2000`)

Exit 0, 97.7 s, 4.84 GB (2026-09-08 13:15Z, code 573c4b43, engine 2.94.0, preflight `--env` OK on
`pins-spine-p.txt`). Plan: matrix 20,796 rows (20,430 local + 366 national) × 792,690 columns
(K=15 clones of 52,846); `parameters` dataset_households 55,000, epochs 2,000, n_clones 15, seed 42,
selection_seed 42, engine_blocks 1; `releasable` false; engine not run. The 7 extra national rows
against spine-o's dry run are #879's SPI rows. Every size run from here stands on spine-p; the
spine-o runs above (S0, S1, S1b) remain valid evidence about the L0 machinery, which #879 did not touch.

### Ruling (María, 2026-09-08) and the knob it needed

Smoke: accept the measured feasible count (45,800 at `pi_hi = 1` on the 100-epoch gates) so every
mechanical piece downstream of the draw runs once at scale — the Sampford rejection path on 792,690
gates, the frozen-target refit, the compact export with closed links, the six-gate battery on a compact
frame, the dense-reference and selection sidecars, the manifest's size receipt, and then the evaluation
command end to end (run acceptance, dense-reference deltas, the comparison with R17, the incumbent
scorer on a compact candidate, the incumbent-surface evaluator re-resolving the engine on a compact
rowwise frame, the eval-home scripts loading a compact H5 with their footprint timings, the summary).
Its fit numbers are not evidence (100 epochs); its footprint numbers are.

Full run: `--selection-pi-hi 0.95` (the US exact-k ladder's setting) with `--epochs 2000` at 55,000.
Commit a6b1e0ca makes the certainty threshold a recorded candidate-run knob (default 1.0; bounded to
(0, 1]; requires `--dataset-households`; recorded as `parameters.selection_pi_hi`, in the size receipt
and in the feasibility measurement as `requested_pi_hi` / `feasible_at_requested_pi_hi`). Risk stated
up front: at 100 epochs 0.95 was not feasible either (34,944 × 0.95 > 25,954); 2,000 epochs should
polarise the gates, and if the draw still refuses, the receipt names the smallest feasible threshold.

### Smoke — 45,800 on spine-p (`--dataset-households 45800 --epochs 100 --skip-holdout`, chained on S1b's row 399e1e7d…)

**Refused before the selection**, 608 s in (10.1 min; 10.6 GB peak; code a6b1e0ca), inside
`contribution_initialization`: `nonzero target at row 20648 has no support`. Row 20648 is national
row 218 of the 366 the rebased tree binds; reproducing the driver's engine-free registry compile
names it: `dwp/uc_payment_dist/COUPLE_NO_CHILDREN_annual_payment_27_600_to_28_800` (family
`dwp_universal_credit`, benunit grain, target 746.3 units), whose constraint row is all zeros on
the cloned pool. R17 had support for the same band on spine-m under the pre-#879 engine
`family_type` (initial estimate 551 against a then-target of 654) and no national row without
support at all; #879 re-points the payment-distribution rows to the relationship-based
`uc_calibration_family_type` proxy, under which no benefit unit in the pool is a couple without
children with an annual UC payment in that band. The dense solve carries such a row as a capped miss;
a size selection cannot carry it. Logbook row 1c7f25dd… (failed).

Response: `refit_uk_dataset_size` now refuses unsupported nonzero targets **by name**, all at once,
before initialisation (commit b1d206d6, `unsupported_nonzero_targets()`), and the smoke is re-run to
obtain the complete list. Handling is a ruling for María: a signed measure exclusion for the affected
rows (the A16 register), a fix to the proxy or the band edges upstream in #879's register, or a
recorded smoke-only drop of unsupported rows from the selection problem (the dense reference keeps them
as misses). Nothing is selected around silently.

Re-run (`f100-k15-h45800-e100-smoke2`, chained on 1c7f25dd…; 589 s to the check, 10.6 GB; code b1d206d6):
the by-name pre-check refuses exactly two rows, both in `dwp_universal_credit`:

- `dwp/uc_payment_dist/COUPLE_NO_CHILDREN_annual_payment_27_600_to_28_800@2025` (target 746.3)
- `dwp/uc_payment_dist/COUPLE_NO_CHILDREN_annual_payment_28_800_to_30_000@2025`

These are the same two rows #879's corrected-measurement comparison reports at −100 %
(`experiments/879-corrected-calibration-comparison.md`, rows 112–113): under the relationship-based
`uc_calibration_family_type` proxy no benefit unit in the spine is a couple without children with an
annual UC award above £27,600. The national seam carries them as capped misses; the catalogue and
upper-band repair is tracked in microcosm#736; 16 payment bands already sit in the reviewed measure
exclusion register. **Proposed (unsigned) handling**: two entries in
`calibration_measure_exclusions.json` on the zero-support-channel precedent
(`slc.repayments.england_postgraduate`), approved by María if she rules so; until then no size run
can start on the rebased tree. Logbook row for smoke2 chained on smoke's.

**Ruling (María, 2026-09-08): sign the two exclusions; run the next round; rebase #877 later.** Signed as
commit 2959e177 into `calibration_measure_exclusions.json` on the zero-support-channel precedent
(approved_by juaristi22, approved_on 2026-09-08, expires_on 2026-12-08, tracking microcosm#736,
adjudication microcosm#355); the register's census pins move with it (51 entries; 18 payment-band
exclusions; 82 active payment bands). Smoke re-launched as `f100-k15-h45800-e100-smoke3`, chained on
smoke2's row. No push until the later rebase.

### Smoke3 — 45,800 on spine-p with the exclusions signed (`--epochs 100 --skip-holdout`, `pi_hi` 1.0)

Passed the by-name check (364 national rows) and **refused at the draw** after 1,512 s (25.2 min;
11.7 GB): on spine-p's 100-epoch gates the measured numbers are

| quantity | spine-o (S1b, k 55,000) | spine-p (smoke3, k 45,800) |
|---|---|---|
| protected carriers = certainties at `pi_hi = 1` | 9,869 | 10,026 |
| budget search `n_nonzero` | 52,490 | 43,938 |
| total open-probability mass Σπ | 45,743 | 39,577 |
| boundary draw m / boundary mass | 45,131 / 35,874 | 35,774 / 29,551 |
| largest boundary gate | 0.998 | 0.998 |
| largest feasible k at `pi_hi = 1` | 45,809 | 39,638 |
| smallest feasible `pi_hi` on the grid | 0.5 | 0.7 (0.8 fails) |
| `pi_hi = 0.95` | infeasible | infeasible (27,443 × 0.95 = 26,071 > 21,439) |

Reading: the "largest feasible count at `pi_hi = 1`" is not a stable target. The budget search
re-learns the gates for whatever count is requested and stops on the count of not-fully-closed gates;
in both measurements the open-probability mass came out at 87–90 % of that count, so requesting the
measured feasible count would only measure a new, lower one. What the measurement does guarantee is
feasibility on the same gates at a lower certainty threshold. Smoke4 therefore runs 45,800 at
`--selection-pi-hi 0.7` (the smallest grid value feasible on these gates), 100 epochs, chained on
smoke3's row bd9ebb9b…; it is the first run to pass the draw. Risk carried forward to S2: at 100 epochs
`pi_hi = 0.95` is infeasible by 18 %; whether 2,000 epochs polarise the gates enough is unknown, and
the count-versus-mass mismatch in the stopping rule does not depend on epochs.

### Smoke4 — 45,800 at `pi_hi 0.7` on spine-p: the first run through the whole size pipeline

Exit 1 = gates failed with the evidence bundle written (the candidate outcome). 1,344 s (22.4 min),
10.6 GB, code 27eb74a1 with a clean tree, engine 2.94.0 in one block. Draw: 27,858 certainties at
`pi_hi 0.7` over a boundary pool of 764,832, Sampford, `feasible_at_requested_pi_hi` true; refit on
the frozen surface; compact export 45,800 households (H5 187 MB against R17's 2.36 GB); the six-gate
battery on the compact frame; both sidecars (`dense_reference_diagnostics.csv` 20,794 rows,
`dataset_size_selection.csv` 45,800 rows) listed in `outputs` with digests; Logbook row 363c8c4f….
Plumbing numbers, not evidence (100 epochs): dense reference loss 0.409 → 0.138, compact 0.613 →
0.172; realised stretch 10.0 against the Horvitz–Thompson baseline; mass 29,247,433 → 27,974,030
(−4.4 %); Kish ESS 9,034 (fraction 0.197); max/median positive weight 244; area support 960 of 1,011
areas below floor (constituency ESS minimum 2.3); target fit 1,321 rows past 25 %.

**Defect found in the surface, not the smoke: `ons.rent.private_rent` (314 local-authority rows, family
`private_rent`, source ONS PIPR).** Every row sits at a relative error of 10^5 to 10^6 on both the dense
reference and the compact fit: the target is a mean monthly rent (£552 to £3,633 per authority) while
the metric `rent/private_rent` is `household_rent × is_private_renter` summed with weights, an annual
rent total (10^8 to 10^9). R17's surface had no `private_rent` rows (19,105 local rows; this tree binds
19,419). The rows became active with #874's re-pin of the local references to Chronicle 6fb700e; the
census entry for the source is signed-deferred (`private_rent_pipr_partial_coverage_2025`: the feed's
only PIPR period is 2026-06, after the 2025 target period) yet 314 of 673 candidates are active. At the
loss cap these rows distort the dense solve as much as the selection, so they block S2 regardless of
`pi_hi`. Ruling requested: extend the signed deferral to the whole target (the surface returns to R17's
ten local families, making the comparison like for like) and fix the metric's semantics (a weighted
mean among private renters, on the PIPR period policy) as its own change; or fix the metric first.
