# SPI comparison on the UK publication baseline

This experiment ports the reviewed SPI changes in [#879](https://github.com/PolicyEngine/microcosm/pull/879)
onto the UK publication stack identified in [Max's 7 September handoff](https://github.com/PolicyEngine/microcosm/issues/665#issuecomment-5562794129).
The treatment preserves observed FRS inputs below age 16, rebases selected SPI
income flows to the build period, and conditions the FRS-only imputation on a
pension-receipt proxy. Source review also identified an omitted OTHERINV index
and corrected the interpretation of the age boundary.

**Status: the combined native-validation verdict and genuine matched-build
results are pending.** This report defines the comparison before those results
are available. The old experiment's loss reduction does not measure this port.
No candidate is certified by this report.

## Publication and runtime provenance

| Item | Pin or status |
|---|---|
| Control publication commit | `d43b4203c6ebe10e062cb3ef3034e66731ea055d` on `uk-publication-stack-834` |
| Earlier #874 head | `8de6bf44d7bd4a5b6ce5c8c24add4501c0944824` |
| Original SPI delta | `bc11803f915fe72afd724515a27a3863035f4efc` → `194111af32b265b226dcbefe33cc735f362461dc` |
| Treatment identification | Publication control plus the reviewed SPI delta, the source-review corrections below, and its recorded implementation hashes; final commit and genuine-run hashes pending |
| PolicyEngine-UK / Core | `2.94.0` / `3.31.0` |
| NumPy / pandas / scikit-learn | `2.4.6` / `3.0.3` / `1.8.0` |
| Both environments' `uv.lock` SHA-256 | `ca9305fcebb5854d8d8369eb10fd134c918da7a79ab90f21c932c946b35165e5` |
| SPI source period / FRS build period / calibration year | `2022` / `2024` / `2025` |
| Genuine control/treatment H5 hashes | Pending |

The port applies the declared-base SPI delta selectively. The publication stack
is not a descendant of the old SPI base, so inheriting the entire old branch
would change more than the SPI treatment. The earlier local candidate
`0feec085888790ea6387a0085878dc681f2e8445` described in the handoff was not
available in this checkout; it is not this treatment's execution receipt.

The selected publication tree includes #874's Chronicle loader/target repairs,
childcare inputs and England bus targets, plus the later publication deferral
register and gate-clock wiring. [#874's committed receipts](https://github.com/PolicyEngine/microcosm/blob/d43b4203c6ebe10e062cb3ef3034e66731ea055d/experiments/834-childcare-tfc-receipts.md)
identify the earlier composition evidence. Those results do not certify the
later publication tip. The [historical SPI report](840-spi-income-coherence.md)
retains the separate `bc11803f` / UK 2.92.1 experiment and its unchanged paired JSON.

## Reviewed source behavior

### Recipient age

[SPI Annex A, physical page 12](https://doc.ukdataservice.ac.uk/doc/9422/mrdoc/pdf/9422_put_2223_full_documentation.pdf#page=12)
labels its first published age band “Under 25.” The pipeline's existing
`_SPI_AGE_RANGES` constructs ages from 16 upward. The treatment therefore uses
16 as an explicit recipient boundary to avoid applying that constructed support
to younger people. It does not interpret 16 as verified SPI survey eligibility.
A 15-year-old retains the observed FRS inputs protected by this stage; a
16-year-old remains eligible for its SPI draws.

The [FRS 2024–25 methodology](https://www.gov.uk/government/statistics/family-resources-survey-financial-year-2024-to-2025/family-resources-survey-background-information-and-methodology)
includes qualifying 16–19-year-olds in its dependent-child definition. This
change preserves under-16 inputs, not every FRS child's inputs. The treatment
leaves the imputation of qualifying older children as an explicit limitation.

Stage 1 consumes the full existing query shape and discards under-16 draws
before assignment. That preserves the random stream shared with the subsequent
base-channel dividend redraw. Both SPI stages preserve the protected under-16
inputs, and the base dividend redraw preserves under-16 FRS dividends.

### Income periods and mappings

The source-year label `2022` represents SPI 2022–23. The FRS loader stores the
2024 period for its [April 2024–March 2025 collection](https://www.gov.uk/government/statistics/family-resources-survey-financial-year-2024-to-2025/family-resources-survey-financial-year-2024-to-2025).
The treatment applies the selected model index at `2024-01-01` divided by that
index at `2022-01-01`, before conditioning stage 2 on the resulting incomes.
This annual convention does not harmonize individual interview months or
establish exact fiscal/calendar alignment. The later 2024-to-2025 projection
is a separate model step.

The installed [PolicyEngine-UK 2.94.0 distribution](https://pypi.org/project/policyengine-uk/2.94.0/)
resolves the following indices. These are modeling growth assumptions, not
HMRC-prescribed growth rates or factors fitted to this experiment's residuals.

| SPI flows | Installed model index | 2022-to-2024 factor |
|---|---|---:|
| Employment components | OBR average earnings | 1.116368286445 |
| Self-employment | OBR per-capita mixed income | 1.021134421134 |
| Private pension | OBR private-pension index | 1.102502017756 |
| Dividends, property, miscellaneous income and OTHERINV | OBR per-capita GDP | 1.092376803703 |
| Taxable savings interest | ONS household interest income | 2.269155046634 |

The old treatment held OTHERINV nominal. [Annex A, physical page 19, note 1](https://doc.ukdataservice.ac.uk/doc/9422/mrdoc/pdf/9422_put_2223_full_documentation.pdf#page=19)
and the installed `variables/input/other_investment_income.py` describe the
corresponding residual investment-income concept. The existing stage-1
crosswalk already maps OTHERINV directly to `other_investment_income`; the
publication treatment now uses that variable's declared OBR per-capita GDP
index. GDP remains a proxy for this taxable component's growth.

Six SPI flows remain explicitly nominal because this review did not establish
a same-scope indexed mapping:

| Flow | Retained limitation |
|---|---|
| GIFTAID and GIFTINV | The corresponding charity inputs have no declared uprating index. |
| INCPBEN | The SPI field is taxable-only. The broader model's reported incapacity benefit has a CPI index, but its scope does not establish the required taxable-income mapping. |
| OSSBEN | The field aggregates other taxable social-security payments. |
| UBISJA | The field combines unemployment benefit, income support and Jobseeker's Allowance. |
| SRP | The SPI pension concept includes widow's pensions and certain retirement lump sums. |

[HMRC's PAYE manual](https://www.gov.uk/hmrc-internal-manuals/paye-manual/paye77001)
distinguishes taxable and exempt incapacity-benefit categories. [SPI Annex A,
physical pages 17](https://doc.ukdataservice.ac.uk/doc/9422/mrdoc/pdf/9422_put_2223_full_documentation.pdf#page=17)
and [19](https://doc.ukdataservice.ac.uk/doc/9422/mrdoc/pdf/9422_put_2223_full_documentation.pdf#page=19)
define the pension field and qualify the treatment of identifiable lump sums.
These scope differences remain visible in the treatment's uprating receipt.

Only an explicit null mapping can produce a `held_nominal` receipt. A declared
mapped variable with a missing, blank or unsupported index, a missing parameter,
or a non-finite/non-positive index value fails rather than silently becoming
nominal. Tests exercise that contract with the actual installed UK engine and
with deliberately incomplete index definitions.

SPI taxable interest is rebased before the build-year FRS tax-free interest is
added once. The treatment also rebases base-channel dividends for recipients
aged 16 and older and reconstructs employment and HMRC accounting aggregates
from the changed leaves. The treatment does not resolve the remaining
interest/ONS scope question in #866 or all period-selection questions in #862.

### Pension-receipt conditioning

The FRS-only forest receives `state_pension_reported > 0` for its training rows
and `hmrc_spi_state_pension_income > 0` for SPI recipients. Given the wider SPI
pension scope, this is a predictive proxy rather than an exact receipt or
amount identity. The forest can still draw a different receipt status. Reduced
discordance alone would not establish entitlement accuracy or consistent
pension amounts. The comparison reports the two pension-income bands and
aggregate pension/tax separately.

The reviewed SPI documentation has SHA-256
`6b39771e6122391c4f0b262dcfb33ec6454264a55638da0f59677696029d2897`;
the source review visually inspected physical pages 12, 17 and 19.

## Matched genuine-build contract

The control and treatment use the same raw FRS inputs, input sample, raw design
weights, source-selection algorithms, generation seeds, build period and
solver settings. Only the reviewed SPI code/specification differs. Both runs
rebuild every downstream stage. Changed SPI incomes can alter downstream
predictors, CGT support and cloning; final row counts and generated prior
weights must therefore be measured, not assumed identical.

The licensed source set is FRS 2024–25, SPI 2022–23, WAS round 8, LCFS 2023–24
and ETB 1977–2024, together with the pinned HMRC income and CGT workbooks.
The SPI donor `put2223uk.tab` has SHA-256
`5ef829461060c91a2a47be59ad541d9b519fc3976d66ca80d4920f711bb96f66`.
The exact source-file hashes and build arguments belong in each genuine run's
receipts; no licensed person or household rows are committed. The separate
[#878 CGT treatment](https://github.com/PolicyEngine/microcosm/pull/878) remains
outside this experiment.

| Calibration setting | Shared value |
|---|---|
| Geography and scale | Full national spine; national targets only |
| Year | 2025 |
| Optimizer | Adam, 1,500 epochs, learning rate 0.02 |
| Target weighting | `family_equal` |
| Solver seed | 0 |
| Maximum weight ratio | 10 |
| Gate evaluation date | Record each run's actual date; use the same day for the pair |
| Target, measure-exclusion, gate, take-up and CGT-source definitions | Preserve the publication control's definitions |

Both runs use the canonical Chronicle consumer artifact produced from source
`6fb700e`, with 128,717 facts and schema
`policyengine_ledger.consumer_artifact.v2`:

- Facts SHA-256: `6ae49d7d7ab297df25a0b9bfe2d6776827c672d284fbb360957fe8337089549f`.
- Manifest SHA-256: `dcda51d6496aea67f768a284e7955c7520e7c8b91e2bed3569f247567b7153f0`.

The publication loader verifies both hashes. Its runtime compiles the national
reference declarations and then applies the reviewed measure exclusions.
The prior #874 receipts reported 415 active references and 371 matrix targets;
these are historical counts to check, not substitutes for compiling this
publication tip. Before interpreting the genuine results, record and compare
the actual target names, target values, binding provenance, excluded measures
and loss weights from both runs. A changed target surface cannot establish an
SPI improvement.

## Protected publication decisions

Ten of the 11 files carrying the publication stack's additional changes remain
byte-identical: the UK country package, gates and target-fit exclusion register;
the battery bindings, calibration runner, terminal gates and weighted integrity
implementation; the terminal-gate tests; and the data contract and its test.
The remaining file, `test_spec_engine_country_bundles.py`, changes only its
expected UK specification identity from
`0accc39d40d8c8106f4c9bc5562ccca50f1212cd2a8cdf72f416978ca12570ff` to
`e0dd9175920f6d1368a74957367182dc4d6357ffbdb1f728457ead91dd16dd9b`.

Native validation exposed this inherited identity pin after the reviewed SPI
specification changed. The unchanged publication control passed its original
expectation; the shared compiler produced the new treatment identity. The
repair updates that exact expected-hash literal and preserves every assertion
and publication-added test. Reversing the one replacement reproduces the
publication file's recorded bytes. This is a documented correction to the
overnight isolated harness's claim that all 11 files could remain byte-identical.
Source-owned coverage and graph regeneration update their derived evidence;
the publication's gate, register and take-up decisions remain unchanged.

The [existing childcare receipts](https://github.com/PolicyEngine/microcosm/blob/d43b4203c6ebe10e062cb3ef3034e66731ea055d/experiments/834-childcare-tfc-receipts.md)
retain the following choices for both runs:

| Decision | Status retained in this comparison |
|---|---|
| A22/A23 TFC and targeted-childcare rates | Hold at 0.88 and 0.597 pending adjudication. |
| Extended and universal-childcare rates | Retain the landed 0.6054 and 0.4539 values. |
| UC with-children target-fit deferrals | Retain existing reasons and expiry of 30 September 2026. |
| Private-pension £100–150k count deferral | Retain its existing entry during the matched comparison; assess staleness from the resulting receipts. |
| CGT target-fit deferral | Retain #875's existing timing/translation reason and expiry of 5 October 2026. |

The historical expected-count childcare fit pushed TFC toward 0.997 and targeted
childcare to 1.0. Its expected TFC spending and child-count ratios were 0.804 and
1.138; targeted childcare reached 0.852 of its target at the fitted vector.
Those ceiling results explain the recorded holds, not a decision to adopt the
ceiling rates. The committed fit receipt pin is
`c56ca568ef446f07f773ea03253bc2f9d878aeea6bc781ee38ed268d1fedde96`.

No new binding, exclusion, expiry extension, take-up change or gate suppression
is part of the SPI comparison. A release gate becoming stale remains a reported
failure until its existing decision is separately reviewed.

## Validation and results

Combined native validation is pending. The required checks include normal UK
package initialization, source/schema/coverage contracts, full invented
country/graph execution against the live legacy oracle, and actual UK-engine
uprating contracts. Invented parity fixtures establish executable contracts;
they do not establish population fit. Any inherited failure must be reported
alongside its same-runtime control reproduction.

Genuine control/treatment builds and national calibration results are pending.
The completed comparison will report the following outcomes without dropping
regressions:

| Outcome | Control | SPI treatment |
|---|---|---|
| Person, benefit-unit and household counts; generated prior weight totals | Pending | Pending |
| Final national loss and contributions by target/family | Pending | Pending |
| Aggregate income tax and state pension | Pending | Pending |
| HMRC pension amounts in the £20–30k and £50–70k income bands | Pending | Pending |
| ONS savings-interest fit | Pending | Pending |
| UC with-children support and fit | Pending | Pending |
| CGT level/fit and downstream support changes | Pending | Pending |
| Weight concentration and effective sample size | Pending | Pending |
| Every terminal-gate verdict and stale/expired decision | Pending | Pending |

The shared quality schema/exporter described in the handoff is not present on
the selected publication tree. Its existing `tools/emit_lineage_dashboard.py`
exports US imputation lineage. Exporting a genuine UK candidate requires the
actual shared schema/adapter and the completed run's grain, decisions and
incomplete checks. The invented UK dashboard prototype is not genuine dataset
evidence. Release publication remains a separate decision.

Refs #665, #736, #796, #840, #866 and #862; independent CGT work remains in
#878 and #875.
