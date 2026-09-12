# US and UK release path

Planning snapshot, 12 September 2026. This is a release work plan, not a
certification of either country. Component tests, historical candidates and
current-candidate acceptance are distinct evidence.

## Products and common construction

The US product must support national and congressional-district analysis. The
UK product must support national, constituency and local-authority analysis.
Each country should have one fully constructed population from which full and
smaller analysis files are derived. Record the survey, monetary, policy and
boundary reference periods explicitly; do not infer them from a filename.

After constructing and harmonizing the complete multispine, including its
initial clones, assign one atomic area to each resulting household and derive
larger geographies from versioned mappings. Distinct clones may receive different
areas, constrained by observed source geography and keyed by stable clone
identity. Subsequent enrichment retains the assigned location. Once construction
and enrichment are complete,
calibration changes household weights; scope selection and pruning retain the
original values, missingness and relationships for every retained household.

For a shared set of weights and consistent measurement definitions, additive
local totals must reconcile to national totals. Separately refitted compact
views need declared approximation tolerances and their own diagnostics. A
common source population alone does not guarantee identical estimates.

## Release sequence

| Stage | US work | UK work | Exit evidence |
| --- | --- | --- | --- |
| Source and period coverage | ACS and ASEC survey multispine; PUF tax detail; SCF and other required auxiliary sources; declared aging | Raw FRS 2024–25; SPI/HMRC, WAS, LCFS/ETB and other required stages; declared uprating | Source register, licensed-input boundaries, source definitions, missingness, units and periods; every applicable input has a producer |
| Complete population | Harmonized relationships and tax/benefit units; geography; financial and PUF enrichment; remaining benefit, disability, housing and asset inputs | Integrated FRS stages and current relationship/claimant definitions; income, wealth, consumption and benefit inputs | Small real end-to-end build; source-channel coverage; plausible distributions and joints; no silent engine-default substitutions |
| Geographic support | Block assignment after initial multispine cloning; versioned county/PUMA/CD derivation; enough household types in each district | Shared atomic-area assignment after full spine cloning, and derivation for each nation; adequate constituency/LA support | Observed geography respected; distinct stable clone draws; subsequent location invariance; support and fit measured at advertised levels |
| Model and calibration | Locked US model; national/state/CD target matrix from identified facts | Locked UK model and companion input changes; national/local matrix with corrected UC and other target definitions | Baseline engine evaluation, calibrated population, target-level errors, support/weight diagnostics and explicit outstanding failures |
| Independent quality | Held-out distributions and geographic cells; tax/benefit totals and representative reforms; comparison with the incumbent | Current release battery, held-out areas and complete incumbent comparison; resolve remaining support and target-fit failures | Candidate-specific reports; explained regressions; thresholds agreed before choosing a candidate |
| Scale and compact views | Increase local build size after smaller checks; derive and refit the intended full/sparse family | Choose a size that meets local support and quality needs; complete compact/exact-count release evidence | Measured time, memory and cache replay; retained-input invariance; full/compact error and performance comparisons |
| Release and consumption | Exact-file dashboard, methods/papers, immutable package and real PolicyEngine loading | Exact-file dashboard and certification; immutable cut, loader/pointer integration and PolicyEngine-UK adoption | Fresh export/readback, reproducible manifest and checksums, consumer calculation smoke test, reviewed release and rollback path |

## Current position

| Stage | US demonstrated result | UK demonstrated result |
| --- | --- | --- |
| Population construction | Small real ACS/ASEC composition, clone and financial enrichment pass; complete PUF and remaining inputs pending | Real FRS 2024–25 spine and earlier whole-spine parity; latest integrated stage set needs fresh coverage and verification |
| Geography | Small native post-clone block assignment and financial extension passed on 11 September; strict replay is running; complete CD support/fit pending | Existing OA-ladder assignment exercised in real candidates; shared post-clone adapter passes 52 scoped checks with lazy imports, while native graph integration remains pending |
| Calibration | Solver controls pass; fully enriched native national/CD solve pending | Real 55,000-household build/calibration experiments complete but fail area-support and target-fit gates |
| Independent quality | Complete-candidate engine outcomes, holdouts and reform validation pending | Prior comparisons and diagnostics exist; the recorded 55k candidates skipped holdout evaluation and do not establish release quality |
| Full/compact files | Small prefix replay and 36 supplied-parent full/pruned/local export checks pass; complete enriched release family pending | Size-selection implementation and measured candidates exist; current accepted full/compact local family pending |
| Delivery | No accepted new-architecture release or default consumer adoption | Assembly implementation and historical assembled cuts exist; current certification and default promotion pending |

The 11 September native pilot passed the corrected survey → full initial
support clone → atomic block assignment → financial-enrichment order. At a
1/1000 source sample, its 1,584 source households and 3,464 people become
3,168 households and 6,928 people after cloning. The nineteen-node graph fits
and attaches seven financial fields. Its closed receipt is tied to frozen
source `2ca11c85a`, and reports 5,362 seconds elapsed and 9.31 GB peak RSS.
This supersedes the earlier assignment-before-cloning milestone for ordering;
it does not establish full PUF enrichment or national/CD calibration.

On 12 September, a strict required replay of that frozen source was launched
with a fresh output directory and a read-only retained store. It must verify
all source bytes again, reuse every node, and reproduce complete artifact
content, excluding only operational timing and cache-hit fields. Its outcome
is pending. Meanwhile the maintained graph's observer-mutation defect has been
fixed and independently reviewed, and the shared graph changes are being
consolidated against the amended main interface. These software changes still
need their own native candidate verification; the frozen pilot does not
certify the newer source.

The remaining critical sequence is complete PUF/input integration, a small
real full build, model and calibration evaluation, then progressive scale
and release verification. The existing age-development runner is a separate
prefix demonstration, not calibration of the nineteen-node financial result. See
[the US review guide](us-launch-review.md) for scoped acceptance records.

UK work already includes raw-source enrichment, national/local calibration,
size experiments and release assembly. Its recorded P50/P95b 55,000-household
candidates fail area-support and target-fit checks; the skipped holdout does
not establish an incumbent-comparison pass. Historical dense assembly also
does not satisfy today's release battery. See
[the size evidence](../experiments/355-uk-dataset-size-receipts.md) and
[the current dense release runbook](uk-dense-release-assembly-runbook-762.md).

The current UK route clones for geographic support and then uses the existing
OA ladder. It has not adopted the new shared atomic geography graph keyed to
stable post-clone household identity. Its existing placement after cloning is
consistent with the user's 10 September ordering correction; the source,
identity and shared-operator migration remain separate work. Maria's
[PR #900](https://github.com/PolicyEngine/microcosm/pull/900) updates Chronicle
household targets and the Northern Ireland lookup; that source work does not
by itself migrate the assignment owner. Anthony's
[PR #896](https://github.com/PolicyEngine/microcosm/pull/896) provides staging
telemetry and synthetic smoke evidence, not a calibrated release.

The shared UK adapter now has accepted supplied-array tests for England/Wales
Output Areas, Scottish Output Areas and Northern Ireland Data Zones. These
checks cover source conventions, observed-region constraints, stable post-clone
identity and row-order/subset invariance. Ordinary UK imports also preserve the
public export contract without eagerly loading unrelated stages or country
engines. All 52 checks passed with unchanged source bytes and no unexpected
access attempts; see the [scoped acceptance record](../experiments/uk-atomic-area-lazy52-20260910.json).
No native UK area source, whole-spine build or calibration result is certified
by those checks. Maria can use these shared primitives in the existing UK graph
integration rather than starting a second country runtime.

UK release coverage must be re-established on the chosen integrated build and
locked model. The declared 145-input contract's older candidate evidence must
not certify the current stage set. The
[migration epic](https://github.com/PolicyEngine/microcosm/issues/665) tracks
source and calibration work;
[exact-count release parity](https://github.com/PolicyEngine/microcosm/issues/898)
and [default promotion](https://github.com/PolicyEngine/microcosm/issues/823)
remain separate consumer-release requirements. Existing open issues are leads
for candidate-specific verification, not proof every historical defect remains.

## Team meeting decisions

This document is the shared US/UK release-path reference. The country review
guides and run receipts provide supporting detail; update the sequence and
ownership here when they change.

The 10 September coordination sequence is:

- Maria's #900 source/target reconciliation merged on 10 September at 14:54 UTC;
  Anthony's #855 target hierarchy/diagnostics and corresponding dashboard
  consumer follow it. Its merge clears that dependency, not all release gates.
- Maria owns registering every existing UK stage as a graph node, stacking on
  #893. Changes to UK stage order follow in a separate PR. The shared atomic-area
  adapter work supports that integration and does not create a second UK graph.
- Anthony's UK staging #896 can proceed independently. His earlier runtime
  proposal #885 is superseded in intent, not another required implementation.
- US construction and verification continue alongside these changes. Complete
  graph coverage in both countries is required for the broader advertised
  launch; passing tests for individual stages does not establish that coverage.

The latest UK full rebuild and evaluation were reported as underway at the
meeting. Its new report must replace historical quality evidence only after the
actual candidate and results are available; the approximate four-hour runtime
reported for that build is not a US or release ETA.

1. Confirm the release years, advertised geographies and full/compact products.
2. Assign one accountable owner to each country candidate and one owner to each
   shared dependency: runtime, calibration, diagnostics and release consumers.
3. Review every row above for the latest actual candidate. Name the missing
   artifact and next measurable result, rather than reporting code completion
   as population acceptance.
4. Agree calibration, holdout, incumbent and representative-reform criteria,
   including which differences need explanation and which block release.
5. Set dates for the next complete small candidate, the full quality review and
   the production-sized candidate using measured runs rather than linear timing
   extrapolation.

Country data work, target/source reconciliation, independent validation, and
dashboard/consumer integration can run in parallel. Each final dashboard and
release verdict must refer to the same candidate bytes. Cross-sectional release
does not require retirement dynamics, every possible forecast year, or a
complete Chronicle/Orrery redesign. Keep those workstreams active without
making them prerequisites for the first accepted cross-section.
