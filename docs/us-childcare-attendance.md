# Child-care attendance inputs: source-backed preparation

Related: [Microcosm #915](https://github.com/PolicyEngine/microcosm/issues/915).

## Status and boundary

`microcosm.build.us_runtime.childcare_attendance.impute_us_childcare_attendance`
is an **opt-in preparation primitive**. The verified NSECE source adapter and
`with_us_nsece_childcare_attendance` now support a local candidate `Frame` and
checkpoint flow, with aggregate diagnostics on the downloaded survey. Neither
operation is registered in the default US production pipeline. This change does
not populate published datasets or resolve #915. It does not change PolicyEngine-US defaults,
the engine ABI, or the existing SPM-unit childcare expense stage.

The three outputs belong on the **person records of children receiving care**:

- `childcare_attending_days_per_month` (integer)
- `childcare_days_per_week`
- `childcare_hours_per_day`

These are YEAR-defined engine inputs describing attendance frequency, not annual
totals. `childcare_hours_per_week` remains derived by the engine from days times
hours. Do not put the child's schedule on parents or replicate it to every
household member. Separate attendance from CCDF eligibility, enrollment, and
subsidy receipt. Zero household expenses do not establish nonattendance, and
positive expenses do not establish a full-time schedule.

## Implemented donor contract

The function takes a person table, a normalized child donor table, positional
typed `Weights`, a seed, and exact matching columns including whole-year age.
Donors require unique canonical string `donor_id` values, complete matching
fields, and all three attendance inputs. Source normalization must remove
survey-specific missing codes; unknown attendance must not become zero.
Nonparticipants must be present as measured three-zero records with their
survey weights. The current donor domain is ages 0–12, matching the proposed
NSECE source scope, **not** a universal CCDF age-eligibility rule.

The function draws a complete schedule with probability proportional to donor
survey weight among compatible donors. Thus participation and intensity remain
joint rather than making three independent predictions. Observed cells,
including zero, constrain the donor match and are never overwritten. Incomplete
or contradictory records, duplicate donors, missing matching fields, and empty
positive-weight matching cells raise errors. There is no fallback to a full-time
schedule or silent broadening of a matching cell. A fitted conditional model or
explicit sparse-cell strategy can later provide support without changing the
preservation contract.

Recipients use canonical string `person_source_id` identifiers. Clones must have
identical matching fields and compatible observations. A stable hash of seed
and source person selects one donor for all clones; donor sorting makes the
selection independent of input order. Complete observations on a clone can fill
the others without donor support. All clones of a source person must be processed
together. Distinct siblings are not forced to share a schedule; joint household
matching remains a requirement to evaluate before activation.

Every output has a companion `<variable>_source` column identifying observations,
donor assignments, or propagation from another copy of the source person.
Missing values outside the age domain remain null, while observed older-child
or adult values are retained. This is an intermediate table: it must **not** be
sent to the engine as a complete dataset until unresolved values are addressed
and the source coverage and production contracts below are satisfied. Provenance must be retained in build artifacts
and excluded from the engine input projection.

## Verified source adapter

The [2024 NSECE V1 release](https://www.childandfamilydataarchive.org/cfda/archives/cfda/studies/39466/datadocumentation)
contains public household (DS5) and calendar (DS4) files. Both were downloaded
under the ICPSR agreement for this work. Each has 6,403 household records. The
loader verifies exact TSV SHA-256 hashes before parsing; hashes and byte counts
are recorded in the validation report. Raw records, donor tables, and source
archives remain local and are not included in the repository or CI fixtures.

The mapping follows the Household Data Files User's Guide, printed pages HH-57,
HH-81, HH-279–280, HH-334, HH-554, and HH-565–568:

| Source field | Adapter meaning |
| --- | --- |
| `HH4_METH_CASEID` | One-to-one household/calendar join; child suffixes agree across files |
| `HHC4_AGE_AT_USAGE_X` | Reference-week age in months; divide by 12 and floor; -9 means no child |
| `HHC4_METH_WEIGHT_X` | Child design weight, positive for present children |
| `HH4_MISSING_STATUS_CC_X` | 0 missing calendar, 1 partial, 2 complete |
| `HH4_CHCAL_R_X_Z` | 672 successive 15-minute blocks, starting Monday midnight |
| `HH4_TYPEOFCARE_AGG_X_Y` | Provider type for child X and provider Y |
| `HH4_REGION` | Four Census regions, not observed state |
| `HH4_PARWORK_STATUS` | Parents of any household child: -1 no parents, 0 none worked, 1 some worked, 2 all worked |
| `HH4_METH_QUEXVERSION` | Main, summer, or new-school-year questionnaire; retained for diagnostics |
| `HH4_ECON_INCOME_ANNUAL` | Annual household income for 2023; retained, not currently matched |

ECE includes individual paid/unpaid care, centers, other organizations, and
irregular arrangements (types 1–5 and 7). K–8 schooling (type 6) is excluded.
The calendar already identifies one final provider per block. Attendance is the
union of ECE blocks: days count days with any ECE, and hours per day equal total
weekly ECE hours divided by those days. Multiple providers are counted for
subsequent diagnostics, but this does not solve provider-specific pricing.

Monthly days use `floor(days_per_week * 52 / 12 + 0.5)`: five weekly days map to
22 monthly days. This is an explicit representative-week approximation, not an
observed month or an engine default. Summer and new-school-year questionnaires
lack the required calendar; weekly-hours summaries alone cannot recover days.

**Missing calendars must not become observed zeros.** The guide warns that some
summary variables encode absent calendars as parental-only care. The adapter
requires a complete calendar and classifiable blocks. Unknown provider types,
missing blocks, and ambiguous gap-check codes leave all three inputs null with
an exclusion reason. A complete parental/self-care or school-only calendar is a
valid weighted zero donor. Unsupported codes are never guessed.

## Candidate integration and reproduction

Run locally after obtaining both TSVs under the archive's terms:

```bash
uv sync --all-packages --locked --extra us
uv run python tools/prepare_us_childcare_attendance.py \
  --household-tsv /local/39466-0005-Data.tsv \
  --calendar-tsv /local/39466-0004-Data.tsv \
  --report /local/nsece-validation.json
```

To apply to a local US `Frame` checkpoint, add
`--input-checkpoint /local/parent.h5 --output-checkpoint /local/candidate.h5`.
The output paths must be new. The operation preserves entity links, row order,
weights, strata, mass history, and inherited metadata. Source hashes, matching
columns, seed, and a candidate-only receipt accompany the checkpoint; the report
also records environment versions and code hashes. It neither publishes a
release nor updates production manifests.

The target person table must already contain canonical `person_source_id` plus
harmonized `age`, `region`, and `parent_work_status`. These are the default exact
matching columns. Parent work must be derived from actual parent relationships,
not by classifying every adult as a parent. This CLI does not yet perform that
harmonization for production population sources. `--match-columns` allows
explicit experiments; age is mandatory. Existing known attendance, including
zero, is preserved. The caller must distinguish genuinely observed zeros from
previously materialized engine defaults before invoking the operation.

Unknown attendance outside ages 0–12 remains null. Before an engine export,
`assert_childcare_attendance_exportable` requires all three columns to be finite
for every person; it does not certify representativeness. Retain provenance in
the checkpoint and project only canonical inputs to the engine. A synthetic
integration test exports a `Frame`, reloads it through `USSingleYearDataset`, and
verifies child weekly hours in a real `Microsimulation`. The CLI was also run
with the real source and a synthetic target checkpoint; this establishes data
flow, not population validity.

## Actual source diagnostics

See [the recorded experiment](../experiments/us-childcare-attendance/README.md)
and its aggregate JSON. Of 11,745 source children, 134 are outside ages 0–12.
There are 7,120 complete, unambiguous schedules, covering **60.26%** of weighted
under-13 children. Another 3,095 have missing calendars, 174 partial calendars,
and 1,222 ambiguous calendars. Original survey weights do not by themselves
make this selected subset nationally representative.

A deterministic household split holds out 1,399 children and trains on 5,721;
no household occurs on both sides. Matching age, region, and parent work leaves
three held-out children unsupported, explicitly excluded from scoring. Among
1,396 supported children, weighted participation is **44.82% observed versus
45.99% imputed**; average weekly days are 1.82 versus 1.79 and weekly hours
13.65 versus 13.09. These are means across participants and nonparticipants.

Age-and-region-only matching initially substantially understated attendance for
all-working-parent households and overstated it for some-working-parent
households. Adding parent work improves those comparisons, but the same split
was reused in development. It is a diagnostic, not an untouched final test set.
Subgroup differences, sampling uncertainty, missing-calendar selection, and
population transfer remain unresolved. The report explicitly records
`production_ready: false`.

## Remaining production acceptance work

1. Address calendar selection and seasonality using source design/response
   evidence; quantify differences between included and excluded children and
   validate a response adjustment or complementary source. Retain unknowns as
   unknowns. Do not simply reuse the selected sample's weights as national totals.
2. Implement and test source-specific target harmonization for parent links,
   work/activity, region, school status, income year, and stable source IDs.
   Measure target matching support. Specify and validate a sparse-cell model
   rather than silently broadening failed exact matches.
3. Evaluate joint household assignments for sibling coherence, mixed-provider
   schedules against the engine's scalar provider inputs, and the monthly
   conversion against consuming formulas. Resolve older children, including
   disability-related care, and other out-of-domain records before export.
4. Register the operation and late producer through normal generation tools;
   update source specs, generated manifests, coverage and producer inventories,
   and engine input contracts. Verify build ordering on a real parent artifact.
   The opt-in candidate path here is not that default-build activation.
5. Run a full candidate population with pinned parent/engine/code identities.
   Predeclare validation criteria, use fresh evaluation data or cross-validation,
   quantify uncertainty, and inspect participation and days/hours distributions
   by age, income, work pattern, geography, and provider. Compare state CCDF
   outcomes before/after; synthetic positive-benefit examples cannot certify
   those population estimates.

Provider and activity inputs need their own evidence. Earlier diagnostic
households required explicit MA/MD provider types and Nevada's activity input
after attendance was supplied; populating attendance alone is not a complete
CCDF data solution. Likewise,
[PolicyEngine-US #9405](https://github.com/PolicyEngine/policyengine-us/issues/9405)
concerns which state benefits enter the household aggregate and is independent
of this source preparation.

## Local checks

```bash
uv sync --all-packages --locked --extra us
uv run pytest packages/microcosm-build/tests/test_us_childcare_attendance.py
uv run pytest packages/microcosm-build/tests/test_us_nsece_childcare.py
uv run pytest packages/microcosm-build/tests/test_us_spine_blindness.py
uv run ruff check .
uv run python tools/ci_test_groups.py --verify
```

The donor tests use only explicitly synthetic records. They check survey-weighted
participation, joint schedules, preservation of observed zeros, source-clone
coherence, stable ordering/chunking, age scope, and rejection of unsupported or
invalid input. Production data validation remains separate from PR CI.

The runtime inventory in `test_us_spine_blindness.py` explicitly classifies both
preparation modules outside the population-treatment registry. That classification
does not exempt it from the all-runtime source-spine access scan. Registering it
as a production stage must update its classification as well as the source and
coverage contracts above.
