# Child-care attendance inputs: source-backed preparation

Related: [Microcosm #915](https://github.com/PolicyEngine/microcosm/issues/915).

## Status and boundary

`microcosm.build.us_runtime.childcare_attendance.impute_us_childcare_attendance`
is an **opt-in preparation primitive** with synthetic-fixture tests. It is not
registered in the US production pipeline. This change alone does not populate
published datasets or resolve #915. It does not change PolicyEngine-US defaults,
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
sent to the engine as a complete dataset until the source coverage and export
contracts below are implemented. Provenance must be retained in build artifacts
and excluded from the engine input projection.

## Proposed source and remaining work

The [2024 NSECE release](https://www.childandfamilydataarchive.org/cfda/archives/cfda/studies/39466/datadocumentation?archive=cfda&tenant=icpsr)
contains a public household file (DS5) and household calendar file (DS4).
They are candidates for a child-level arrangement donor source; this PR does
not claim to have mapped or validated their raw fields. Download access requires
accepting ICPSR terms, including redistribution restrictions. No NSECE records
are included in the repository or fixtures.

Before enabling this routine in the US build:

1. Review permitted use of source and derived artifacts. Pin the release,
   download coordinates, file hashes, survey year, and codebook references in a
   source manifest. Implement a reproducible source adapter. Verify child and
   household links, the appropriate survey weights, imputation flags, missing
   codes, participation, calendar episodes, and provider categories.
2. Define an attendance estimand suitable for the engine: for example a
   representative care week with documented school-year/summer treatment.
   Derive attended days from the union of care days and daily hours from
   non-overlapping care episodes. Do not sum different providers' hours and then
   price all those hours at one provider's rate. Decide how to represent multiple
   providers in a model with scalar attendance inputs.
3. Document the monthly conversion and rounding. For a representative-week
   convention, `round(days_per_week * 52 / 12)` is one possible approximation
   (five days maps to 22); it is **not** a measured monthly calendar and is not
   implemented or imposed on observed monthly values here. Verify the convention
   against consuming formulas before adoption.
4. Select matching features available on both source and target: age, school
   attendance, family composition, parental work/activity, income, and supported
   geography. Public-use region must not be represented as observed state.
   Measure support and sparse-cell failures; evaluate household donor matching
   for sibling coherence and a weighted conditional model for generalization.
   Do not fit on replicated support clones as independent respondents.
5. Address older children with disabilities or other state-specific exceptions
   using appropriate source evidence. An under-13 survey cannot establish zero
   care for all older children. Define an explicit missing-data/export policy;
   never silently coerce unresolved child inputs to zero.
6. Register the source operation and late producer, persist person outputs,
   update source specifications and generated manifests, coverage declarations,
   producer inventories, and engine-input ABI declarations through the normal
   generation tools. Test build ordering and actual export/reload behavior.
7. Validate weighted participation and days/hours distributions by age, income,
   family work pattern, and provider; inspect sibling and clone consistency.
   Compare state CCDF outcomes before and after on real data. Record exact engine
   and dataset versions. Synthetic positive-benefit examples do not certify
   population estimates.

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
uv run ruff check .
uv run python tools/ci_test_groups.py --verify
```

The donor tests use only explicitly synthetic records. They check survey-weighted
participation, joint schedules, preservation of observed zeros, source-clone
coherence, stable ordering/chunking, age scope, and rejection of unsupported or
invalid input. Production data validation remains separate from PR CI.
