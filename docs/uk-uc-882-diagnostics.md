# UC target repair diagnostics, September 2026

The first controlled comparison shows that paid-claim target repairs improve
the broad UC fit but **do not close the lone-parent gap**. These are private
development calibrations reported as aggregates, not a certified release.
The [target contract](uk-uc-paid-target-contract.md) describes the statistical
repair and its remaining approximations. [#882](https://github.com/PolicyEngine/microcosm/issues/882)
remains open.

## Retained-spine experiment

The baseline uses merged Microcosm `a19582bd`, released PolicyEngine-UK 2.97.0
and the authenticated retained FRS/SPI spine. All arms hold the 52,846
household identities/order, priors, source ancestry, simulation outputs, active
366-row roster and family coefficients fixed. The historical 371-row/UK2.94
replay is not the causal control: five additional non-UC exclusions and the
engine upgrade were already merged before this experiment.

Each solve uses 1,500 updates, learning rate .02, seed zero, free mass,
maximum weight/prior ratio 10, no sparsity penalty, target loss cap 10 and
`family_equal`. No extra epochs or new joint targets are introduced. The loss
cap is not a 10% fit tolerance. The tool validates input, code and dependency
identities at both ends of each run and authenticates the baseline's saved
inputs and weights before comparing them.

| Fit against each arm's own source target | Old contract | Paid CY2025 | Paid FY2025/26 |
|---|---:|---:|---:|
| UC headline | −4.49% | −4.29% | −5.12% |
| Single with children | −18.12% | −12.78% | −15.31% |
| Couple with children | −0.03% | +0.09% | +0.05% |
| Five-plus reported children | +0.29% | −0.07% | −0.05% |

Changing the denominator explains part of the apparent lone-parent improvement.
Against the **same CY paid target of 2,138,780**, the old-contract weights are
14.77% below target; CY recalibration is 12.78% below. The estimate rises from
1,822,793 to 1,865,550. The repair therefore improves the weighted estimate
without establishing closure.

The CY structural-family and allowance-family arms produce identical matrices
and weights. Both use a matrix identical to the baseline on this retained
sample. The changed values are ten right-hand-side targets; the family
measurement introduces no new support here. The explicit allowance definition
is still the appropriate comparison contract and preserves structural roles.

Evaluated against one common CY matrix, target vector and coefficient vector,
the ten broad count rows' weighted mean absolute percentage error falls from
9.15% to 4.35%; seven of ten are within 5%, compared with five before. The FY
weights give 5.97% on that same CY comparison. This does not select CY because
it fits better: the two windows represent different observation conventions.

CY household ESS changes from 13,846 to 13,722 and original-source household
ESS from 5,026 to 4,956. The maximum ratio remains 10. Compared with the
same-engine old-contract fit, CY income tax changes +0.12%, National Insurance
+0.15%, state pension +0.57%, Child Benefit −0.29%, employment income +0.16%
and Housing Benefit +3.09%. Housing Benefit remains a reviewed excluded
calibration row; this is an outcome change, not a validation pass.

After these retained runs, a compiler guard was tightened to reject missing
publication identities. Recompiling the real feed before and after that change
gives identical values and metadata for all 415 targets. The fresh run below
uses the tightened guard; the completed retained comparisons remain bound to
their original code receipts.

## Fresh combined source build and calibration

The full unsampled source build completes in 391.51 seconds with 40 graph
nodes and all 15 source-scope gates passing. It uses stock UK 2.97.0, the
pinned FRS2024/25 inputs and seed 578. The first attempt exposed two missing
read declarations on the capital stage: `person.is_benunit_head` and
`person.is_parent` existed in the full checkpoint but were removed by graph
scoping. Adding those dependencies fixes execution. The regression exercises
that exact scoped call, and the legacy-versus-graph parity check passes.

The final spine contains 52,846 households, 61,213 benefit units and 113,590
persons, with complete original ancestry for all descendants. The 16,288
original households and 18,850 original benefit units survive. The capital
stage processes 893 SPI reporter redraws and refreshes 265 would-claim flags.
Source child counts and claimant couple status remain unchanged through the
inspected same-ID imputation, reporter and capital stages. Source-stage
snapshots do not store calculated UC awards/components, so they cannot
establish the first stage at which an upper payment cell became empty.

The production national solve completes at the same 1,500-update budget in
180.90 seconds including compilation and checks. Its paid lone-parent estimate
is 1,839,214 against 2,138,780, a **14.01% shortfall**. The headline is 4.71%
below target; couples with children and five-plus reported children are within
0.13%. This confirms that the repaired targets do not close the gap on the
fresh combined pipeline either.

The terminal gate refuses export: both unsupported payment bands remain at
−100%, and five old fit exemptions are now within the permitted bound and
flagged as stale. No calibrated H5 or passing calibration build record is
produced. The signed failed-gate report and its bound diagnostic file are
retained; they are not converted into a release pass. The source HMRC replay
has reviewed-exclusion coverage only, with zero numerical comparison coverage,
so the source build's gate pass is not an HMRC fit claim.

## Empty cells and bounded feasibility

Two positive-target childless-couple payment rows have zero model records in
every retained arm:

| Monthly payment band | Source target | Model support |
|---|---:|---:|
| £2,300.01–£2,400 | 746.33 | 0 |
| £2,400.01–£2,500 | 605.78 | 0 |

Their annual matrix bands are £27,600–£28,800 and £28,800–£30,000. Reweighting
leaves both at −100% under every feasible weight vector. These rows stay in
the evaluation; they are not silently excluded to claim a successful fit.
The same limitation was acknowledged in the
[diagnostic comment on #883](https://github.com/PolicyEngine/microcosm/pull/883#issuecomment-5587342177).

Diagnostic linear programs use bounds of zero to ten times each prior and
explicit 5% row tolerances. The complete 110-row UC/TCL set is infeasible
because of the two zero rows. Two separate, explicitly scoped checks are
feasible: the other 108 UC/TCL rows, and the ten broad UC counts together with
four named OBR targets and 24 HMRC employment amount/count bands. Neither
proves feasibility of all 366 rows, or of all 108 UC/TCL rows jointly with
every protected target. Feasible witness weights are not release candidates
or proof that Adam has converged. They justify investigating competing rows
and objective allocation before increasing the epoch budget.

The amount comparison remains unresolved: DWP monthly cash can contain
advances and payments on the claimant's behalf, while the model provides an
annual recurring award. No recurring entitlement is invented to fill these
cells. Component, deduction and timing evidence must precede support generation.

## Five-plus children and independent support

The CY paid five-plus target itself has 80 household rows from 29 original
source households, source ESS 9.96 and a largest-source share of 27.6%.
Its near-zero residual does not demonstrate robust joint support.

The matrix contrast **reported five-plus minus TCL five-child households
minus TCL six-plus households** has four nonzero clone rows from just **one
original family**. Its source ESS is one and its largest-source share is 100%.
For CY the fitted contrast is 21,079 against target arithmetic of 21,040.
The three component rows' 5% tolerances imply a contrast interval of
[14,460, 27,620]. Removing all descendants of that one source leaves attainable
contrast [0, 0], so the three rows cannot jointly retain that fit. The FY arm
has the same one-source dependency.

This subtraction explains optimizer algebra across different concepts and
windows. It is not an administrative statistical identity or a newly inferred
joint. Extra clones of the same record do not provide independent evidence.
Diagnostics group descendants before calculating source concentration and
leave-one-source-out capacity.

## Date, claim and relationship limits

The source audit found birth-date fields entirely blank in the delivered
adult and child files. Current-year official documentation confirms completed
age, adult age-80 top-coding and household `INTDATE` as interview-start date.
It does not establish the numeric TAB date encoding or exactness of every age
at that date. [UKDS variable listing](https://doc.ukdataservice.ac.uk/doc/9563/mrdoc/excel/9563_frs2425_variable_listing_eul.xlsx),
[derived-variable summary](https://doc.ukdataservice.ac.uk/doc/9563/mrdoc/excel/9563_dv_summary_2425.xlsx),
[questionnaire](https://doc.ukdataservice.ac.uk/doc/9563/mrdoc/pdf/9563_frs_2024-25_question_instructions_final.pdf#page=14)

A conditional interval sensitivity, assuming days since 1960 and accurate age
at the household start date, finds three original large families that could
have no post-cutoff child. None is confirmed unaffected. Two survive as paid
five-plus families in the retained spine; neither supplies the one-source
contrast above. The previous model-year-minus-age proxies do not identify
these ambiguous cases. No exact birthdays are imputed and no blanket age
increment is applied.

The next date repair must retain raw age/date validity and ancestry, verify
the encoding, then test before/after/ambiguous intervals around 6 April 2017
independently of model-year labels. April open/nil claim history, TCL exceptions,
education transitions and exact administrative child attachment remain
separate limitations. Annual zero awards or take-up flags cannot establish
open nil claims. The new Chronicle crosses do not supply these histories.
