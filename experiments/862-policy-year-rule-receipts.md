# #862 policy-year rule receipts

Stage-level receipt for microcosm#862 (uk-data#475, uk-data#476, uk-data#478 inherited
through parity): the declared FRS stages were run in order through
`frs_education_grant_split` (frs_spine, frs_employment, frs_council_tax, frs_disability,
frs_education, frs_legacy_proxies, frs_education_grant_split; the transforms
`tools/build_uk_frs_spine.py` binds) on the pinned FRS 2024-25 tabs, once on `main` and
once on this branch, with a scratch script that records the disability category bands,
the three flag masses and the DSA column. Person weights are the household weights of the
person's household. Categories are string columns, so their parity share is structurally
1.0; the band counts below are the real check. No calibration ran: the two two-child-limit
disability cells (#808 lineage) are not re-measured here, and a full licensed spine +
calibration run remains available as a follow-up.

## Inputs and code

| item | value |
|---|---|
| release | `frs_2024_25` (`uk/frs_release.json`: survey 2024, base 2024, calibration 2025) |
| tabs | UKDS SN 9563 tab zip sha256 `05dd0069587dbd25e5719d355ce05fc0827d5edd58c24ece9ab85acd954a9aeb`, hash-checked per tab by `frs_spine._read_pinned_tab` |
| frame | 34,966 persons, 68,251,110 weighted, `time_period` `2024` on both sides |
| engine | policyengine-uk 2.92.1, policyengine-core 3.31.0 |
| before | `main` `c1b83241` |
| after | this branch (`uk-policy-year-rule-862`; head recorded in the PR) |
| runtime | about 24 s per side, 2026-09-07 |

## Disability categories (records, weighted persons): identical before and after

| column | band | records | weighted |
|---|---|---|---|
| aa_category | HIGHER | 635 | 869,690 |
| aa_category | LOWER | 372 | 523,290 |
| dla_sc_category | HIGHER | 212 | 367,409 |
| dla_sc_category | MIDDLE | 292 | 549,247 |
| dla_sc_category | LOWER | 90 | 136,176 |
| dla_m_category | HIGHER | 255 | 391,710 |
| dla_m_category | LOWER | 257 | 511,494 |
| pip_m_category | ENHANCED | 983 | 1,710,945 |
| pip_m_category | STANDARD | 500 | 882,913 |
| pip_dl_category | ENHANCED | 966 | 1,776,373 |
| pip_dl_category | STANDARD | 793 | 1,373,522 |

Reading: moving the category thresholds from the `baseline` clone (FY 2023-24 rates) to
the fiscal-converted `gov.dwp` tree at the survey year (FY 2024-25 rates) moves no row.
Respondents report the statutory rate in force and adjacent bands are about 49% apart, so
the GBP 6.80 to 7.80 per week threshold shift lands inside every band. This is the same
result uk-data#480 recorded on the incumbent side with the same tabs.

## Disability flags: identical before and after

| flag | records | weighted |
|---|---|---|
| is_disabled_for_benefits | 3,729 | 6,184,013 |
| is_enhanced_disabled_for_benefits | 1,813 | 3,013,472 |
| is_severely_disabled_for_benefits | 2,219 | 3,588,886 |

The SPI refresh now calls the same derivation with the same rates, so the SPI-redrawn
rows cannot diverge from these figures (previously it divided categories by 52 instead of
365.25/7; a unit test pins the equivalence).

## DSA seed at the calibration year

| measure | before (`main`) | after (this branch) |
|---|---|---|
| `disabled_students_allowance_eligible_expenses` records > 0 | 0 | 1 |
| weighted people with a positive value | 0 | 4,654 |
| weighted GBP | 0 | 83,772,000 |
| row value | 0 | 18,000 (DfE maximum at 2025-01-01) |
| `education_grants` residual, weighted GBP | 2,816,276,654 | 2,732,504,654 |
| `education_grants` records > 0 | 189 | 188 |

Reading: the DSA capacity is evaluated at the release calibration year (2025) with the
three eligibility booleans materialised at that year on the 2024 frame, so the seed opens
to one record whose full reported grant moves out of the residual (delta GBP 83,772,000 on
both lines). uk-data#480's receipt on the same tabs found the same thin seed (1 record,
4.7k weighted, GBP 83.8m). The pinned enhanced-FRS parity reference still lists the column
as zero-share, so the register signs it as a candidate-only column
(`dsa-eligible-expenses-seeded-at-calibration-year`) rather than re-minting the reference.
