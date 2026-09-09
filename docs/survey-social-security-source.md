# Survey Social Security source semantics

The source-report Social Security total precedes PUF enrichment. The current
qualifier verifies the original observations and preserves their limits; it
does not fit a completion model, assign individual beneficiaries, or certify a
population. The intended PUF successor has 55 outputs and uses the retained
total as a ninth conditioning input. Historical full65 and PUF59 behavior is
unchanged until a caller explicitly selects that successor.

## Source measurements

The [2025 ASEC dictionary](https://www2.census.gov/programs-surveys/cps/datasets/2025/march/asec2025_ddl_pub_full.pdf)
describes `SS_YN` and `SS_VAL` on PDF page 49. The question covers people aged
15 or older and permits combined family payments on a person's report. A
positive report is therefore not necessarily one individual beneficiary's
payment. The qualifier preserves the source report's grain.

The retained ASEC original member supplies `PERIDNUM`, household/line/age
coordinates, `SS_VAL`, `SS_YN`, `RESNSS1`, `RESNSS2`, `RESNSSA`, `I_SSVAL`
and `I_SSYN`. Source keys, the complete current cohort, raw member size/hash,
live source issuance and exact current money values must all agree. Source
year and income year are 2024; interview year is 2025. Carried reason fields
are not a substitute for these original literals.

The [2024 ACS dictionary](https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/PUMS_Data_Dictionary_2024.pdf)
defines combined `SSP`, its age-15 question universe, and allocation flag
`FSSP`. The qualifier binds the retained 2024 ACS issuance and verifies
`SSP * (ADJINC / 1000000)` against the prepared amount. This remains a rolling
income window expressed in the survey's price basis. `FSSP` is not in the
current native projection, so publisher allocation provenance stays explicitly
unresolved; no observed-value claim is inferred from a missing flag.

## Mapping judgments and unknownness

The reason mapping is an explicit judgment at source-report grain. Retirement
and disability map to their corresponding component. Widowed and surviving
child reasons map to survivors; spouse and dependent child reasons map to
dependents. A single resolved component receives the report total. Repeated
reasons in the same component do not duplicate the amount.

Distinct component reasons, missing reasons, code 7's combined child categories
and code 8's residual category leave the component amounts unknown. The
published reasons restrict possible components where they can; there is no
reason priority, age fallback or equal-share default. Separately observed
component amounts and individual beneficiary assignments are not claimed.

An ASEC under-15 `SS_VAL=0` is a not-in-universe sentinel. Both ASEC and ACS
under-15 beneficiary totals remain unknown in the projection, with the raw
ASEC zero retained in the separate literal table. An in-universe zero remains
a known report total of zero. Contradictory universe/recipiency combinations
and invalid nonempty codes refuse; blank literals remain distinguishable
from invalid codes.

An eventual component model may normalize nonnegative scores within allowed
components, preserving the source total and already resolved source basis.
It must supply positive allowed mass. The numerical helper does not authenticate
such a model; the graph must bind real fit/apply artifacts. A reporting-unit
convention, allocation to individual beneficiaries where necessary, explicit
income periods, design-weighted training, native-to-clone inheritance and
held-out checks remain separate required work.

## Verification scope

The 52-case control run executes 50 numerical/literal tests and two complete
maintained source issuances from invented original CSV/checkpoint fixtures.
It verifies source-identity joins despite reordered rows, repeat qualification,
defensive returned data, exact source totals, unknown components and unchanged
input frames. Source/control files, installed model source and the 12 admitted
code resources were unchanged before, after and in the external postcheck.

The run completed in 67.6 seconds with 428.9 MB peak RSS. Receipt SHA256:
`2b9d8e45cec11a6ebda2ccc01c5f12374e794ec0c006ba6525f082fd6454049b`.
These controls are not native-source execution, a fitted component model,
PUF55 integration, policy-engine validation or release acceptance.
