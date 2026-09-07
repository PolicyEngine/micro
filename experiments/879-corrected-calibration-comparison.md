# PR 879: matched national comparison after measurement corrections

Both requested measurement corrections are implemented and the matched national calibrations are complete. The corrected SPI comparison reduces loss by **39.81%**, but remains release-blocked. England council-tax measurements now fit closely. The two high-payment childless-couple bands are empty in both corrected spines, establishing a support gap rather than a treatment-only regression.

## What changed

- National VOA bands A–H and total explicitly require `country == ENGLAND`, matching their `E92000001` facts. Local VOA and Scottish bindings are unchanged.
- The UC payment-distribution and family-composition measurements use retained FRS claimant/parent roles rather than a generic adult count. This preserves cohabiting couples and prevents an older child becoming a partner. UC child counts include reported child members under 20 and native UC child/qualifying-young-person status, excluding the claimants themselves. The five child-count targets use the same child definition.
- SPI price-year corrections, income draws, take-up, target values, all 44 measure exclusions, reviewed fit exclusions, solver settings and gates are unchanged.

This is a measurement correction. Every UC award in each rerun was checked bit-for-bit against its original full-model award before solving. The underlying UK model still has a separate standard-allowance relationship error; relabelling calibration families does not repair entitlement.

## Controlled experiment and matrix verification

Both runs reuse byte-identical copies of the complete 2024 spines already built on the publication control and SPI treatment. The common measurement code is `117860efe96b4fc1e336e0c9bfab10917cd3aa59`. The control spine originated at `d43b4203`; the SPI spine at `fc49b482`. Both calibrate 2025 using UK 2.94.0 / Core 3.31.0, Chronicle `6fb700e`, 371 identical active targets, 1,500 epochs, family-equal loss weights, learning rate 0.02, maximum weight ratio 10 and seed 0.

Before either optimizer ran, all nine actual VOA matrix rows were asserted equal to the appropriate England indicator derived independently from the nine English regions. All 84 active UC payment-band rows were checked against the corrected family masks, actual band bounds and benefit-unit-to-household links. Full-register edges were retained so existing exclusions do not widen adjacent bands. The comparison receipt verifies unchanged initial weights and bit-identical matrix rows outside the authorized VOA and UC-composition changes. Original and copied spine hashes remain equal after both runs.

## Results

| Corrected run | Final loss | Targets within 10% | Effective sample size |
|---|---:|---:|---:|
| Control | 0.021724747 | 337 / 371 | 6,127.6 |
| SPI treatment | 0.013076866 | 341 / 371 | 6,110.6 |

The previous and corrected runs use different measurement definitions, so the within-pair SPI contrast is the controlled comparison. The four columns below show how correcting those definitions also changes the apparent baseline problems.

| Target | Previous control error | Previous SPI error | Corrected control error | Corrected SPI error |
|---|---:|---:|---:|---:|
| VOA England Band A | +22.804% | +28.182% | +0.049% | -0.027% |
| VOA England total dwellings | +15.930% | +15.787% | +0.036% | +0.010% |
| Income tax | -12.151% | -12.562% | -12.067% | -12.709% |
| Total state pension | -8.136% | -11.695% | -7.909% | -11.430% |
| UC single with children | -35.309% | -34.525% | -31.365% | -27.923% |
| UC total benefit units | -13.400% | -12.975% | -11.189% | -10.006% |
| UC childless couples, £27.6–28.8k | -0.014% | -100.000% | -100.000% | -100.000% |
| UC childless couples, highest band | +0.270% | +0.228% | -100.000% | -100.000% |
| OBR capital gains tax | +44.180% | +43.744% | +44.919% | +44.819% |

England Band A now has weighted estimates of 6,106,286 and 6,101,679, against 6,103,320. These are actual recalibrated estimates, superseding the earlier fixed-weight England-only diagnostic. Other targets still compete through the common household weights. Interest targets account for 91.5% of the net objective gain, so lower total loss should not be treated as uniform improvement in joint tax/benefit quality.

## Reassessing the high-payment childless-couple bands

The formerly decisive two duplicated records are classified as lone-parent benefit units in both runs. Their awards remain £27,646.60 in the control and £27,489.43 in the SPI treatment. Neither provides support for the corrected childless-couple distribution. The correction changes family classification for 769 / 768 benefit-unit rows, of which 144 / 154 have positive UC in control / treatment.

The support columns below show **benefit-unit rows / unique source benefit units**. Duplicated or SPI-cloned rows are not independent source cases.

| Annual band (rounded bounds) | Status | Control support | SPI support | Control error | SPI error |
|---|---|---:|---:|---:|---:|
| £20,400–£21,600 | Active | 8 / 4 | 6 / 3 | +0.06% | +0.52% |
| £21,600–£22,800 | Active | 2 / 1 | 2 / 1 | +0.03% | -0.03% |
| £22,800–£24,000 | Active | 2 / 1 | 2 / 1 | +0.68% | +0.59% |
| £24,000–£25,200 | Active | 6 / 3 | 6 / 3 | +0.45% | +0.06% |
| £25,200–£26,400 | Active | 4 / 2 | 4 / 2 | -0.24% | -0.31% |
| £26,400–£27,600 | Excluded | 0 / 0 | 0 / 0 | -100.00% | -100.00% |
| £27,600–£28,800 | Active | 0 / 0 | 0 / 0 | -100.00% | -100.00% |
| £28,800+ (highest labelled band) | Active | 0 / 0 | 0 / 0 | -100.00% | -100.00% |

There are 14 / 13 active payment-band targets with fewer than five unique source benefit units in control / treatment. All 100 bands, including excluded bands, have row counts, unique-source counts and weighted results in the companion receipt. The old two-row fit is not the success baseline. These tails need genuine support; a good weighted fit on one duplicated source case would still be fragile.

## Gate verdict

Both reruns remain blocked by the unchanged `uk_target_fit` gate and refuse calibrated H5 export. The corrected SPI run's unreviewed target-fit failures are:

| Target | Corrected SPI error |
|---|---:|
| `dwp/uc_payment_dist/COUPLE_NO_CHILDREN_annual_payment_27_600_to_28_800@2025` | -100.000% |
| `dwp/uc_payment_dist/COUPLE_NO_CHILDREN_annual_payment_28_800_to_30_000@2025` | -100.000% |
| `hmrc/self_employment_income_income_band_50_000_to_70_000@2025` | +34.485% |
| `hmrc/state_pension_income_band_20_000_to_30_000@2025` | +27.941% |

The existing reviewed private-pension count exclusion for the £100–150k income band is stale in both runs because the result is back inside its bound. The exclusion for UC households with exactly two children is also stale in the corrected treatment. Both remain unchanged in this controlled comparison. The receipt records the full gate statuses. This is not a certified dataset or a release-readiness claim.

## UC target inventory and remaining measurement limitations

There are **100 payment-band references: 25 × four family types; 84 active and 16 excluded**. There are also 11 active general UC targets and 15 active two-child-limit targets, giving **110 active UC-related targets** out of 371 overall. Two OBR UC expenditure references are compiled but excluded; including these and the 16 excluded bands gives 128 compiled UC-related references. The separate inventory lists every band, target value and activation status.

Most source bins span £100 per month, annualised as £1,200. The current interpreter starts at source lower edges × 12 and uses half-open intervals. Its final compiled band is open-ended despite the published £2,400.01–£2,500 monthly label (readable annual label £28,800–£30,000). That existing upper-bound mismatch was held fixed; pooling bands or correcting the tail boundary would be a separate experiment.

DWP family types use the standard-allowance single/couple rate and reported children under 20. The new FRS relationship measure is a better composition proxy than generic age-only categories, but it does not resolve the pinned model's couple-allowance treatment of some parents with older children, nor partner-ineligibility exceptions or all administrative child-reporting differences. Those limitations should be addressed before interpreting the corrected family cells as exact administrative matches. [DWP Family Type metadata](https://stat-xplore.dwp.gov.uk/webapi/metadata/UC_Households/Family%20Type.html), [DWP child-count metadata](https://stat-xplore.dwp.gov.uk/webapi/metadata/UC_Households/Number%20of%20Children.html).

## Validation

Focused validation covers 305 distinct passing tests and two existing skips after updating two stale country-resource-roster assertions to include the already-registered reviewed target-fit exclusion resource. The initial measurement suite had 111 passes and two skips; the additional country-package/calibration/gate suite had 192 passes and two inherited roster failures, both then repaired and rerun successfully. This is not a full-repository test claim. Repository Ruff and CI test-inventory verification pass. The pinned-feed target-reference regeneration test passes. No release gate, exclusion policy, take-up input or original spine was altered.
