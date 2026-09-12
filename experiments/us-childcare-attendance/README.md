# NSECE attendance candidate: 2026-09-12 diagnostic

Related: [#915](https://github.com/PolicyEngine/microcosm/issues/915) and
[draft PR #916](https://github.com/PolicyEngine/microcosm/pull/916).

**Verdict: candidate only; not ready for production activation.** The real source
adapter and local checkpoint path work. This experiment does not establish
national representativeness, target population validity, or state CCDF effects.

The [aggregate report](nsece-2024-v1-validation.json) was generated from the
2024 NSECE public household DS5 and calendar DS4 TSVs, ICPSR 39466 V1. It records
source hashes/size, seed, exact code hashes, and Python/library versions. It
contains no individual records or identifiers. Source archives, normalized donor
records, and local candidate checkpoints are not redistributed in this PR.
See the [mapping and reproduction guide](../../docs/us-childcare-attendance.md).

## Source coverage

| Status | Children |
| --- | ---: |
| Complete and unambiguous | 7,120 |
| Missing calendar | 3,095 |
| Partial calendar | 174 |
| Ambiguous calendar/provider | 1,222 |
| Age outside 0–12 | 134 |
| Total | 11,745 |

Complete schedules cover **60.26%** of the original weighted under-13 population.
This is source coverage, not an attendance participation rate. The original
child weights are used for conditional donor draws and descriptive comparisons;
using them after these exclusions does not validate national totals. Calendar
availability differs by questionnaire version, including the summer and
new-school-year instruments. Missing and ambiguous attendance stays unknown.

## Household-separated diagnostic

A stable hash with seed 915 holds out approximately 20% of households, keeping
siblings on the same side: 5,721 training children and 1,399 held-out children,
with zero household overlap. The final candidate matches exact child age,
Census region, and household parent-work status. Three held-out children lack
training support (weight 44,357.42) and are reported separately; 1,396 are scored.
No unsupported record is assigned a default zero.

| Weighted mean, supported children | Observed | Imputed |
| --- | ---: | ---: |
| Any ECE attendance | 44.82% | 45.99% |
| Days per week | 1.823 | 1.793 |
| Hours per week | 13.652 | 13.095 |

Means include participants and nonparticipants. Matching draws all three
attendance inputs jointly; it does not independently predict their means.

| Parent work group | Observed participation | Imputed participation |
| --- | ---: | ---: |
| All parents worked | 60.79% | 59.14% |
| Some parents worked | 25.44% | 30.49% |
| No parents worked | 28.59% | 33.79% |
| No parents present, supported subset | 28.83% | 20.26% |

An earlier age-and-region-only diagnostic on the same household split imputed
41.51% participation for all-working-parent households and 47.03% for
some-working-parent households, compared with observed 60.79% and 25.44%.
That motivated adding parent work. Consequently this split has been used during
model development and must not be treated as an untouched final acceptance set.
Age, region, and work-group detail is retained in the JSON; for example the
age-zero weekly-hours mean remains 9.85 imputed versus 13.48 observed. No
uncertainty intervals or acceptance thresholds have yet been established.

## Integration evidence and limits

The report's `candidate_frame_written: true` refers to a **two-person synthetic
target checkpoint with the real survey donor source**, not a production build.
The local CLI run preserved parent receipt metadata, entity links and household
weight, wrote a separate candidate checkpoint, and reloaded its attendance
columns without missing values for this fixture. The fixture's adult had
explicit observed zeros; the adapter did not infer adult zero attendance.

A separate synthetic-source CI test exports through `PolicyEngineUSEngine`,
reloads through `USSingleYearDataset`, and calculates weekly hours through a
real `Microsimulation`. Locally this ran with PolicyEngine-US 1.819.0 and period
2026. It verifies the person input/export contract only. It does not validate
benefit changes or production data.

The next acceptance work is source-selection/seasonality analysis, tested
harmonization of real target parent/work/region fields, sparse-cell handling,
sibling and provider conventions, older-child coverage, registered build and
input contracts, and a full population comparison with pinned parent and engine
artifacts. No release, production manifest change, or national CCDF result is
claimed here.
