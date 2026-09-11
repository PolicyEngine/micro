# #890 receipts — bind DfT, HMRC, DESNZ, Ofgem, ORR and NTS facts for bus fares, road fuel, energy and rail

Plan: `repos/uk-890-implementation-plan.md` (María's rulings 2026-09-10/11: OBR cars receipts as
the fuel target; BUS0415 alignment on a calendar-year basis; donors uprated to FY2024-25; bus
incidence modelled take-up style on NTS frequency of use; two PRs, target binding first). Licensed
evidence lives under `data/ukds/acceptance/890-fuel-bus/` (SDC-safe aggregates only); this file
carries the digest-pinned receipts the PR's declarations anchor to.

## PR-T — calibration target binding

### Part A — Chronicle feed re-pin (national surface only)

Feed rebuilt from `PolicyEngine/chronicle` main `c6f9361492056b9fab7b8535a2be77eb2b6c93bb`
(2026-09-11, the merge of #258 on top of #255) with `chronicle build-bundle --suite uk` →
`build-consumer-artifact` (built 2026-09-11 from a worktree at that commit):

- `consumer_facts.jsonl` sha256 `45bda3ae730d4ae3fa059d9e03304e902f7f6e74c5099355ef937625ca03b72b`
- `manifest.json` sha256 `33a3031523e2cea2f0092a547b97065efbe103cdf85f842142e847b921bcdd9d`
- rows / schema: 138,847 / `policyengine_ledger.consumer_artifact.v2`; consumer-fact schema
  digest `72ad3149…` (was `76ac268e…`: chronicle added the `quarter` and `week` period types)
- previous national pin: `ec7169b`, 131,450 rows (`4a50ee95…` / `a95d0ee9…`)

Effect on the committed national surface before any binding change: none. 415 active, 7
deferred, 8 signed out, no resolved value or fact key moved; the compile-parity receipts
regenerate byte-identical. Only the membership feed label moves
(`chronicle-uk-ec7169b5-consumer-facts` → `chronicle-uk-c6f93614-consumer-facts`). The local
census, validation levels and local reference surfaces keep their separately reviewed
`ec7169b` pin; the local regeneration test now reads its own default file
(`.codex-work/consumer_facts_uk_local.jsonl`).

### Part B — vendored Chronicle facts (`tools/vendor_uk_ledger_facts.py`)

Nine per-concern resources under `uk/`, each carrying the feed identity above and
regenerating byte-identical from it under test; selection counts are asserted by the register
`uk/ledger_fact_vendor_selections.json`:

- `dft_bus_value_anchors.json` — 81 rows (BUS05ai 9, BUS05bi 9, BUS0415 39, NTS0705a 24); sha256 `2a92a656…`
- `road_fuel_anchors.json` — 69 rows (HMRC 12, DESNZ annual 6, OBR by vehicle 49, ONS population 2); `8dc10402…`
- `licensed_cars_fuel_type.json` — 36 rows; `83750dff…`
- `need_energy_facts.json` — 228 rows (E&W 144, Scotland 84); `5453d7fd…`
- `ofgem_price_cap_facts.json` — 268 rows (cap levels 256, benchmark consumption 12); `b668e351…`
- `nts_bus_use_frequency.json` — 54 rows (NTS0313 27, NTS0621 27); `2738c4f5…`
- `devolved_bus_finance.json` — 86 rows (Scotland 18, Wales 36, NITHC 8, DfI 24); `6bd24101…`
- `orr_rail_facts.json` — 99 rows; `02c8870b…`
- `ons_household_expenditure_facts.json` — 18 rows; `7c13e88a…`

### Part C — region leg and the London bus rows

- `_geography_pins` pins a region-only contract target at region level; the compiler refuses a
  region pin outside the nine English region codes (`UK_NATIONAL_REGION_ROSTER`) and a
  region-pinned reference that resolves a non-region fact.
- `dft.bus_fare_receipts.london` → fact FY label 2025 (comparable 2024), GBP 1,347,434,943.01;
  `dft.bus_net_support.london` → GBP 1,130,214,000; both region `E12000007`.
- England outside London: signed exclusion `derived_partition_member` (the partition
  reconciles within GBP 1,000 in `test_uk_bus_targets.py`). UK fares row: `no_publisher_uk_total`
  (Wales fare revenue unpublished). UK support row: `covered_by_country_legs`.

### Part D — BUS0415 alignment (fares only)

Factor = mean of the four quarter-end index values inside the calibration calendar year over
the mean of the four inside the receipts' April-to-March fiscal year, per series:

- England `E92000001`: from (2024-06, 2024-09, 2024-12, 2025-03) mean 193.125; to (2025-03,
  2025-06, 2025-09, 2025-12) mean 204.125; factor 1.05695792880259; value GBP 3,417,388,656.44
  → 3,612,036,036.22.
- London `E12000007`: 196.1 flat in both windows; factor 1.0.
- Net support rows are never aligned (#789 scope item 5).

### Part E — new national targets (pinned facts, registry scope, unmapped declarations)

- `obr.fuel_duties_cars`: OBR receipts by vehicle category, cars, FY2025 (projection, obr
  family policy) GBP 15,900,000,000 on `fuel_duty`. `obr.fuel_duties` (all road users) signed
  out; its #757 measure exclusion retired (register 51 → 50 entries).
- `orr.rail_government_support`: ORR 7270, FY2024 GBP 21,621,100,549 held to 2025, Great
  Britain (`region != NORTHERN_IRELAND`), on `rail_subsidy_spending`.
- `ons.household_energy_expenditure`: ONS COICOP 04.5 CY2025 GBP 43,427,000,000 on
  `domestic_energy_consumption`.
- `scotgov.bus.passenger_revenue` GBP 391,000,000; `scotgov.bus.government_support`
  GBP 499,000,000 (FY2024, region SCOTLAND).
- `welshgov.bus.public_support` GBP 131,489,970 (FY2024, concessionary fares GBP 62,443,460 +
  support to operators GBP 69,046,510 gross, region WALES).
- `dfi_ni.bus.passenger_receipts` GBP 150,082,817.49 (FY2024, Ulsterbus + Metro/Glider,
  region NORTHERN_IRELAND).
- `nithc.public_transport_support` GBP 111,700,000 (FY2024, PSO 61.8m + concessionary 49.9m,
  bus plus rail) on `bus_subsidy_spending + rail_subsidy_spending`, region NORTHERN_IRELAND.

Surface after Part E: 244 contract targets (registry scope 210, profile scope 34), 424 active
references, 7 deferred, 7 signed out; national runtime compile 424 / 0 unsupported.

### Part F — baseline national calibration on the current spine

(filled from `data/ukds/acceptance/890-fuel-bus/pr-t-baseline-spine-p/` once the run completes)

Runs on the newest gated national spine (`spine-p`, `data/ukds/acceptance/spine-p-355/spine-p.h5`,
sha `ae83e307…`, FRS 2024-25, stamped 2024), 1,500 epochs, `family_equal`, code `3a135c5f`:

- `pr-t-baseline-spine-p/` (`uk-frs-calibration-attempt-20260911T113749Z-0c7e79e2`): the terminal
  battery blocked on one row, `obr.fuel_duties_cars@2025` at −25.6%; every other new row inside the
  bound. Loss 0.01154, 96.0% within 10%, ESS 10,461 (0.198), max/median 100, 374 targets solved
  (424 compiled − 50 measure exclusions).
- `pr-t-baseline-spine-p-2/` (`…20260911T114304Z-61b7818a`): identical solve with the dated
  reviewed exclusion for that row in force (register entry approved 2026-09-11, expires
  2026-10-11, tracking the PR-S landing); battery passes, staging H5 written (not a release
  candidate).

Pre- and post-calibration fit of the new rows (initial → final relative error):

- bus fares England −46.3% → −0.0%; London −72.4% → +0.1%; support England −28.8% → +0.1%,
  London −72.5% → +0.1%
- `obr.fuel_duties_cars` −46.6% → −25.6% (excluded from the fence, still bound)
- `orr.rail_government_support` −71.8% → +0.2%
- `ons.household_energy_expenditure` +0.2% → +0.0%
- Scotland fares −63.0% → +0.0%; Scotland support −54.5% → +0.1%; Wales support −9.9% → +0.2%;
  NI fares −65.3% → −0.0%; NI public transport support +65.3% → −0.2%

How the solver closed them, measured on the calibrated staging H5 against spine-p design
weights (the receipt PR-S is built to change): the closures are weight stretch on the households
carrying the imputed column, not level. Share of the calibrated mass sitting on households whose
weight rose more than 3× (more than 5× in brackets): London fares 83% (73%), London support 85%
(77%), England fares 60% (48%), Scotland fares 64% (33%), Scotland support 69% (57%), NI fares
78% (3%), rail support GB 83% (71%), motor fuel 51%. Rail is the largest single stretch: the
frame carries GBP 6.1bn of `rail_subsidy_spending` at design weights against the ORR 7270 broad
total of GBP 21.6bn, so the 14% of households with rail use are stretched ×3.6 on average; the
7271 all-sources operational figure for FY2024 is recorded below for the open 7270-versus-7271
ruling. Northern Ireland public transport support runs the other way (frame GBP 185m at design
weights against GBP 112m published), because the ETB donor is a GB survey. Domestic energy
already sits on ONS 04.5 at design weights (GBP 43.5bn against 43.4bn), so that row costs
nothing; PR-S repricing to FY2024-25 cap rates with standing charges will move the frame off it
and is the point at which the NEED-versus-ONS level question is decided.

ORR FY2024 for the rail ruling: table 7270 total government support GBP 21.62bn (bound); table 7271 all sources GBP 11.86bn, of which Department for Transport GBP 9.47bn.
