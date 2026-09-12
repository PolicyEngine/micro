# Current ASEC income reporting/routing source qualifier — lane progress

Branch `current-asec-income-routing-20260912`, worktree
`_worktrees/microcosm-current-asec-income-routing-20260912`, base
`d5cbe60b2c6402648565f5139dbf7d94be209def` (reviewed US integration).

Journal, not state. Check git/GitHub for current truth.

## Scope

Deliver a thin **source qualifier** plus a **pure reporting/routing projection**
for the five original-channel ASEC income families the current graph does not
yet supply: pension/annuity, IRA distributions, net property income, farm, and
other income. Consumed later by the already-owned `graph_us_survey_enrichment`
host, which root's active amount owner owns. This lane creates **no** host, no
issuer, no engine execution, no native cell writes, no release claim.

## State

- [x] Read the actual-current-graph trace
      (`_recovered/scratch-backup/893/codex-takeover-20260912/original-tax-graph-gap-source-trace.md`)
      and confirmed the current host does not call `derive_cps_carried_current_leaves`
      or the preclone gap-fill.
- [x] Verified the official 2025 dictionary bytes locally:
      SHA256 `5cb80973326ef8b625fbaae70d80b0c641ce5d2b3911abd2fb4427abd5908a6f`.
- [x] Read the accepted UC pattern
      (`current_asec_unemployment_source.py`, reviewed hash
      `624c76ae058e7b2a466a017eba348327c94751088d97011d3474cd8314187519`) read-only
      in the successor worktree; not mutated.
- [x] Read the in-base siblings `current_social_security_source.py`,
      `current_asec_demographics.py`, `current_survey_predictors.py`.
- [x] Extracted every target field's printed literal (length/position/range,
      verbatim Universe and Values) from the verified dictionary, and
      cross-checked each against `asec_current_money_domains_v1.json`: exact match
      on position, length, universe and values for all nine money fields.
- [ ] Module `current_asec_income_routing_source.py`
- [ ] Tests `test_us_current_asec_income_routing.py`
- [ ] Source contract note + changelog fragment
- [ ] Ruff, CI inventory `--verify`, bounded pytest

## Next

Write the qualifier and its invented-source tests; run red-then-green.

## Verified source literals (2025 dictionary, pages 43-49 + allocation pages)

All quoted verbatim from the pinned PDF.

| Field | Len | Pos | Range | Universe as printed |
| --- | --- | --- | --- | --- |
| PNSN_VAL | 7 | 571 | (0:9999999) | `PEN_YN = 1` |
| PEN_YN | 1 | 570 | (0:2) | `All Persons aged 15+` |
| ANN_VAL | 6 | 438 | (-1:999999) | `ANN_YN = 1` |
| ANN_YN | 1 | 444 | (0:2) | `All Persons aged 15+` |
| DST_VAL1 | 6 | 495 | (000000:999999) | `DST_SC1 = 1` |
| DST_VAL1_YNG | 6 | 501 | (000000:999999) | `DST_SC1_YNG = 1` |
| DST_VAL2 | 6 | 507 | (000000:999999) | `DST_SC2 = 1` |
| DST_VAL2_YNG | 6 | 513 | (000000:999999) | `DST_SC2_YNG = 1` |
| DST_SC1 | 1 | 491 | (0:7) | `DST_VAL1 > 0 and a_age >= 58` |
| DST_SC1_YNG | 1 | 492 | (0:7) | `DST_YN_YNG = 1 and a_age < 58` |
| DST_SC2 | 1 | 493 | (0:7) | `DST_VAL2 > 0 and a_age >= 58` |
| DST_SC2_YNG | 1 | 494 | (0:7) | `DST_VAL_YNG > 0 and a_age < 58` |
| DST_YN | 1 | 519 | (0:2) | `Persons aged 58 and over (a_age >= 58)` |
| DST_YN_YNG | 1 | 520 | (0:2) | `Persons under age 58 (a_age < 58)` |
| RNT_VAL | 6 | 621 | (-9999:999999) | `RNT_YN = 1` |
| RNT_YN | 1 | 627 | (0:2) | `All Persons aged 15+` |
| FRSE_VAL | 7 | 390 | (-9999999:9999999) | `ERN_YN=1 or FRMOTR=1` |
| FRSE_YN | 1 | 397 | (0:2) | `ERN_YN=1 or FRMOTR=1` |
| ERN_YN | 1 | 381 | (0:2) | `WORKYN=1 OR WTEMP=1` |
| FRMOTR | 1 | 389 | (0:2) | `ERN_OTR = 1` |
| OI_VAL | 6 | 549 | (0:999999) | `OI_YN = 1` |
| OI_OFF | 2 | 547 | (0:20) | `OI_YN = 1` |
| OI_YN | 1 | 555 | (0:2) | `All Persons aged 15+` |

Source-level questions that stay open (evidence, not modeling judgments):

- `PNSN_VAL` is printed as "total combined amount of pension income received
  from **all** pension sources". It is not an observed private/taxable amount.
  The legacy 0.590 split is a modeled assumption and is not applied here.
- `RNT_YN`'s printed question covers rent, royalties, roomers/boarders **and**
  estates or trusts; `RNT_VAL`'s printed question asks only about "income from
  rent after expenses". The receipt and amount questions do not have the same
  printed coverage, so the total is not independently labelled rental.
- `DST_SC*` code 4 is `Regular IRA`. Account identity does not observe a taxable
  fraction, so no taxable component is derived.
- `DST_VAL1`'s printed universe is `DST_SC1 = 1` (401k account) although its
  label is the source-1 distribution amount; preserved verbatim as an
  unresolved printed-universe ambiguity rather than silently corrected.
- `DST_SC2_YNG`'s printed universe names `DST_VAL_YNG`, a field with no
  dictionary entry; preserved verbatim.
- `OI_YN`'s printed `0` label is `none or niu`, unlike `PEN_YN`/`ANN_YN`/
  `RNT_YN`/`DST_YN` whose `0` is `niu`. Zero receipt literals are therefore not
  interchangeable across the five families.
- Published allocation flags exist for `ANN_VAL` (`I_ANNVAL`), `ANN_YN`
  (`I_ANNYN`), `PEN_YN` (`I_PENYN`), `RNT_VAL` (`I_RNTVAL`), `RNT_YN`
  (`I_RNTYN`), `OI_VAL` (`I_OIVAL`), `ERN_YN` (`I_ERNYN`), and the DST
  composites (`I_DSTSC`, `I_DSTSCCOMP`, `I_DSTVAL1COMP`, `I_DSTVAL2COMP`,
  `I_DSTYNCOMP`). The dictionary publishes **no** direct flag for `PNSN_VAL`,
  `FRSE_VAL`, `FRSE_YN`, `OI_OFF`, `DST_VAL*`, `DST_YN` or `FRMOTR`; their
  allocation provenance is therefore recorded as unresolved, not as "raw".
- `I_DSTVAL1COMP`'s printed `Universe:` line is empty in the dictionary.
