# UK dataset sizes: implementation plan and operating boundary

This implements the candidate-building part of [#355](https://github.com/PolicyEngine/microcosm/issues/355)
on [#870](https://github.com/PolicyEngine/microcosm/pull/870)'s branch. The PR is still open as of
2026-09-05 and itself stacks on #852. Do not base the work on the old issue's
535,080-household 2023 dataset. The authoritative inputs are the current raw-FRS
2024-25 spine, OA ladder, and pinned Chronicle facts used by the joint candidate.

## Decisions retained

- Pool generation keeps clone count **K=15**. Requested output households is a
  different parameter, applied after cloning and materialization.
- The joint surface retains national, constituency and local-authority rows,
  the declared stretch bound **10**, loss cap **10**, **grain_equal** weighting,
  and **1,500 epochs** per solve in the normal driver defaults.
- Existing binding adjudications, signed deferrals, measure exclusions,
  census-vintage uprating, and all local gates remain in force. Size selection
  does not silently drop target rows, loosen ESS floors or change registers.
- Population-normalized engine measures are frozen from the full pool. The
  refit uses their selected household contributions rather than re-running
  those formulas on a smaller population.
- The Frame carries complete households, benefit units and people; every
  non-dry attempt retains the existing Logbook recording envelope.

## Implemented sequence

1. Build the usual joint dense solve from the pinned inputs. This also supplies
   the same-target reference loss for the size comparison.
2. Compute each household's maximum absolute target-contribution share from
   original pool weights and the compiled sparse matrix, following
   [#346's correction](https://github.com/PolicyEngine/microcosm/issues/346#issuecomment-4902880142).
   Protect the largest absolute weighted carrier of each nonzero target, with
   first-column tie breaking. Initialize open probabilities with
   `0.1 + 0.8 * score / (score + median_positive_score)`. This bounded smooth
   prior is an implementation choice for candidate evaluation, not a measured
   UK release ruling. Run L0 budget search; never select the largest prior scores.
3. Use the existing exact-count Sampford sampler on learned probabilities.
   Probability-one gates are certainties (`pi_hi=1`), including every protected
   carrier. Refuse impossible budgets or sampling designs rather than clamp.
   The certainty threshold is a candidate-run knob (`--selection-pi-hi`,
   default 1). The first licensed rehearsal (2026-09-08, 55,000 of 792,690 at
   100 epochs) was refused at the draw: the budget search meets its target on
   the count of not-fully-closed gates while the exact-count design can only
   draw from the open-probability mass, which fell a fifth short. The refusal
   and the size receipt now carry a feasibility measurement (boundary mass and
   largest gate, the largest feasible count at `pi_hi=1`, the smallest feasible
   threshold on a grid). Ruling (María, 2026-09-08): the smoke accepts the
   measured feasible count; the 55,000 candidate runs at `pi_hi=0.95` (the US
   exact-k ladder's setting) and 2,000 epochs. A threshold below one promotes
   learned near-certain gates and is recorded, never a release default.

   The same 2026-09-08 ruling fixes the local private-rent binding: each 2025
   PIPR calendar-year mean monthly rent is composed into the linear annual
   total `12 × mean × renter households`, using the matching authority's
   A17-uprated `ons.tenure.private_rent` count. The composed total remains the
   bound `rent/private_rent` target, and its inputs ride the cross-grain receipt.
4. Refit on the selected support through `microcosm.calibrate`, with no L0
   penalty. Reuse the existing normalized Horvitz–Thompson `w/q` baseline.
   The stretch multiplier remains 10 **relative to that inclusion-adjusted
   baseline**; this is the shared exact-k refit's contract, not a claim that
   sparse weights remain within 10 times the unexpanded pool-row weights.
   The manifest names the reference explicitly. Its empirical suitability for
   UK release remains to be assessed alongside the size scorecard.
5. Restore the prepared carrier and export only selected linked entities.
   Re-run the existing local gate battery on the compact frame. Each holdout
   fold independently reruns selection on training targets; held targets do
   not inform the prior or protected set.
6. Record requested/realized counts, pool positions, inclusion probabilities,
   protected count, seed, learned penalty, dense/refit loss and target change,
   the gate reports, and ordinary byte-pinned output metadata.

## Running a candidate

Use the inputs and environment from the existing
[UK dense assembly runbook](uk-dense-release-assembly-runbook-762.md).
Pass the same pinned source arguments to the existing driver and add:

```bash
uv run python tools/build_uk_rowwise_candidate.py \
  --input-h5 "$UK_SPINE_H5" --input-sha256 "$UK_SPINE_SHA256" \
  --ladder "$UK_LADDER_NPZ" --ladder-sha256 "$UK_LADDER_SHA256" \
  --ledger-facts "$UK_LEDGER_FACTS" \
  --ledger-facts-sha256 "$UK_LEDGER_FACTS_SHA256" \
  --ledger-manifest-sha256 "$UK_LEDGER_MANIFEST_SHA256" \
  --dataset-households 50000 --seed 42 --out out/uk-k50000
```

Repeat with another positive household count and a fresh output directory to
compare sizes. These are requested counts, not certified presets. Omit
`--dataset-households` to retain the existing dense path. Add `--dry-run` to
inspect input binding and parameters without solving or writing a candidate.
Never reduce `--n-clones` to request a smaller output. Full builds still need
the dense build's peak memory and add L0/refit work; the reduction is in the
exported dataset's storage and downstream loading/simulation footprint.

### The search stops on the draw's own feasibility; the solve is checkpointed before the draw (2026-09-09)

S2 on spine-p (55,000 at `--selection-pi-hi 0.95`, 2,000 epochs) was refused at the
exact-count draw after 4.8 hours. The mass-basis budget search had stopped inside its
±5% band at an open mass of 54,834, 166 rows *under* the request; the draw's
condition is one-sided (roughly "open mass at least the request", exactly
`(k − certainties) × max(boundary π) ≤ Σ boundary π`), and with near-binary gates the
tail below 0.95 held 291 rows of mass for 437 places. Two changes follow:

- The size selection's search now stops only on a probe whose gate probabilities
  admit the draw at the requested threshold (`calibrate(..., feasible_draw_pi_hi=…)`
  on the mass basis; verdicts from `exact_k_design_feasibility`, the draw's own
  inequality). An infeasible probe steers the bisection like a count miss (short
  boundary mass → smaller penalty, surplus certainties → larger). Every probe and the
  reason the search stopped are recorded under `selection_budget_search` in the size
  receipt; if no probe is drawable within the ten-probe budget the closest run is
  still returned and the draw refuses with its measurement, as before.
- A size run writes `size_selection_checkpoint.{npz,json}` into `--out` after the
  dense solve and the search, before the draw (the dense weights and trajectory, the
  selection's weights, gate probabilities and search receipt, the protected-carrier
  mask, and the identity of the pool, the target surface and the solve settings).
  `--resume-size-checkpoint DIR` re-derives the pool and the surface, verifies that
  identity, rebuilds both results through `rebuild_calibration_result`, and continues
  at the draw; `--selection-pi-hi` may differ from the threshold the search stopped
  on and both are recorded (`selection_pi_hi`, `selection_search_pi_hi`). A draw
  refusal therefore costs a re-draw, not the pool solve. `--no-size-checkpoint`
  opts out. The checkpoint is candidate evidence, never a release input.

## Certification and publication still required

The implementation produces **candidates**, not a new certified UK default.
A size request refuses `--release-candidate`, and its manifest records
`releasable=false` even if the diagnostic gate run passes. The dense assembler
must not interpret a compact candidate as the already reviewed dense line.
The existing registry, production pointers and pe.py default are unchanged.

Before any size can be promoted:

1. Run the licensed full-input build, retain all gate failures and measure
   local ESS and fit. A nominal 50k size is not guaranteed to clear the floors
   that motivated K=15.
2. Run #355's matched sound-comparison protocol and the referenced promotion
   scorecard, including reform/distributional validation and untargeted bases.
   Calibration loss alone is not a certificate. The included same-target loss
   comparison is a diagnostic, not a substitute for those protocols.
3. Adjudicate any new size-specific acceptance decisions, including the
   inclusion-adjusted stretch reference. A national-only product would need
   its own explicit scope; this implementation does not downgrade local claims.
4. Add size-specific certified release identities, assembly contracts and
   downstream bundle entries against that evidence; publication remains the
   repository's deliberate human step.

Accordingly, this increment does not close #355's default-flip requirement.
Synthetic CI checks prove code behavior and artifact structure; they do not
establish licensed-data fit, storage measurements, or release eligibility.
