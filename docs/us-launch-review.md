# US graph build: review guide

This branch consolidates the US graph build work for review. The intended file
supports national and 119th congressional district analysis from one population.
It is still a development build: complete enrichment, fiscal calibration and
release verification have not passed together.

## Architecture and review order

The intended construction order is ACS + CPS ASEC → combined survey multispine →
household Census block assignment → derived larger geographies → PUF clone and
donor enrichment → rules evaluation and calibration → verified full and pruned
exports. Enrichment clones inherit their household's assigned location. The PUF
operator acts on the combined survey frame. A separate ASEC–PUF base is not the
intended architecture.

The optional ten-node survey prefix now assigns a block before cloning, and its
thirteen-node age-calibration extension passes cold execution and required
replay on invented originals. A twenty-node extension now carries atomic
geography through current financial imputation and required replay. Native
Delaware and complete national block support pass source normalization;
national/CD acceptance of the enriched population remains pending. The earlier joint tract/district
operator is a separate path. See
[Geography assignment](geography-assignment.md) for the country contracts,
implementation and source boundaries.

| Area | Main source entry points | What to review |
| --- | --- | --- |
| Graph execution and storage | `packages/microcosm-graph/src/microcosm/graph/{decl,executor,manifest,store,codecs,schema}.py` | Typed inputs and outputs, ownership, artifact ancestry, cache identity and nullable round trips |
| Survey source preparation | `packages/microcosm-build/src/microcosm/build/us_runtime/{acs_population_catalogue,asec_population_catalogue,survey_population_preparation}.py` | Source identity, entity links, source universes and current income transformations |
| Combined survey and clone | `us_runtime/{graph_composed_population,graph_survey_population,graph_combined_clone}.py` | ACS and ASEC composition before the clone; native versus detail channels |
| Enrichment | `us_runtime/{full_puf_enrichment,graph_full_puf_enrichment,graph_current_survey_puf_transfer}.py` | Target ordering, conditioning, observed-value preservation and complete replay |
| Conditional models | `packages/microcosm-fit/src/microcosm/fit/{qrf_target,graph_legacy_train,graph_legacy_apply_matrix}.py` | Reusable model artifacts, deterministic draws and target regimes |
| Geography | `atomic_geography.py`; `us_runtime/{atomic_block_support,atomic_block_api_sources,survey_atomic_geography,graph_atomic_survey_population}.py` | Block-first assignment, observed-source constraints, versioned mappings and clone inheritance; the older joint-cell operator remains separate |
| Survey mass and calibration | `us_runtime/{survey_origin_budget,graph_survey_budget,graph_survey_calibration}.py`; `packages/microcosm-calibrate/src/microcosm/calibrate/{group_bounds,solve}.py` | Original survey mass, grouped bounds, fixed support and existing ungrouped solver behavior |
| Compatibility | `packages/microcosm-build/src/microcosm/build/{frame_checkpoint,us_runtime/__init__}.py` | Current-main APIs, checkpoint metadata and existing country consumers |

Paths beginning `us_runtime/` are relative to
`packages/microcosm-build/src/microcosm/build/`.
The branch contains a substantial consolidation; review each area and its tests
before deciding how to land it. Shared runtime changes overlap with
[#873](https://github.com/PolicyEngine/microcosm/pull/873) and Anthony's
[#885](https://github.com/PolicyEngine/microcosm/pull/885). Their final contracts
need reconciliation; this draft does not supersede either review.

## Verification and review scope

The previously published head `a85c9cbb79081a980e7d3afe8916c80153de5bf8`
passed 36 integration controls and 57 enrichment/replay controls on invented
inputs. The 36 cover eight solver, eleven snapshot/storage, nine geography and
eight facade cases. The 57 include cold execution, required replay, reconstruction
through a fresh Frame store, inherited tax-unit values and malformed ancestry
refusals. Source/control, model-declaration and resource pins matched before,
after and in external postchecks; the tax-benefit engine was not executed.

Those receipts are identified by SHA-256
`ad8ab6d8761db3d21343bc1fc60023c0dfa305e1367622630a5de6c68892d62a`
and `85a192f8c5c851648875d66b90bea6b8a4ee11e86e67d1875c3ca34a076ee014`.
These checks do not certify subsequent source additions or the entire repository.

CI exposed test-helper collection failures and a pool/registry circular import.
This revision adds the test helper directory to pytest's path and moves the
registry import after the pool functions it validates. Two fresh-process import
regressions are assigned to the US-engine CI lane; their runtime result remains
pending. No import-order result is inferred from an AST check.

The corrected checkpoint test selection passed all 58 invented controls against
the current integration checkpoint source, including nullable integer widths,
missing-value masks, deterministic round trips and malformed v4 refusals. It
took 5.36 seconds wall time and 348.5 MB peak RSS. All 45 source/control files,
three provider pins and two code resources matched in the external postcheck.
Receipt: `f8009ec6d07d076eff6a90ec97061d538756293547a21758ab2bc38fa5f7aab8`.

Fable's earlier replay review closed seven findings. A separate review of the
published consolidation identified the checkpoint test gap and additional
grouped-bound, metadata-store and facade coverage work. The portable grouped-bound,
fixed-support and metadata-store selection now passes all 117 tests with no skips.
The fixes reject nonfinite stored JSON as `StoreCorrupt` and normalize the deprecated
`apg` alias before grouped-mode validation. Source/control, resource and provider
bytes match before, after and in an external postcheck. Receipt:
`3674af9d610417897539da6eae766726d0f582ae6dd3bc2c3e550fefa45bab68`.
The historical platform fixture and complete facade import coverage remain separate.
Environment-specific prepatch byte fixtures do not establish portable CI byte
parity. Existing v1 graph stores remain preserved; v2 execution uses a new store
rather than silently promoting old frames.

Private runtime records and generated population artifacts stay outside this
source PR. Receipt identifiers are audit references, not reproducibility inputs.

The composed 156-case test run against source commit `8157300` at documentation
head `78d84f9` passed 152 cases and failed four current-survey cases with
`PRODUCER_CHANGED`. Its execution guard also recorded unexpected test-bytecode
and installed-model cache-directory probes. Source/control, model-source and
resource bytes remained unchanged. This is a failed integration run, not a
replacement for the earlier passing component evidence. Its receipt is
`67ff10fef45c58d2d6ea15c72b4311a4daa901dd2aae263fbb863d38c13bc7c8`.
The successor now passes all 314 selected invented integration and identity
checks with no skips or unexpected refusals. This includes the original 156
cases, five metadata-copy/mutation regressions and 153 encoder controls; seven
synthetic-issuance controls remain explicitly outside this selection. Shallow
copy, deepcopy and pickle previously added a class cache entry captured by
Python 3.14 annotation closures. An explicit immutable-metadata representation
avoids that mutation without weakening producer checks. Two stale ACS pins were
updated only after verifying AST equality with their accepted source revisions.
All 476 source/control, 5,983 model-source and 12 resource entries matched before,
after and in the external postcheck. The run took 253.5 seconds and 738.7 MB peak
RSS. Receipt:
`d940913f918af4455dab2b9e680d55f9efc7bb922f72ff3d8fe26b0530b070f7`.

A separate 16-case current seven-node age-development run initially passed 13
cases and failed three on exact diagnostic reconstruction. The checker omitted
two solver-option fields added by the consolidated solver. Reconstructing the
grouped solver's closing-state selection and empty selection receipt fixes that
mismatch while retaining exact whole-document comparison. All 16 tests now pass,
including actual seven-node execution and late target/successor mutation checks,
in 170.3 seconds at 541.9 MB peak RSS. All 469 source/control, 5,983 model-source
and 12 resource entries matched before/after/current checks. Receipt:
`5849dd42e914e4d8304a5d290ff451da45910e7ac9a61e76fff36468949ffe3a`.
Broader CI's missing helpers and stale schema, seed and runtime classification
expectations remain separate from these selected passing suites.

## Component evidence and remaining work

Separate component work has verified the national Census joint-geography source
artifact: 2,462 PUMAs, 87,841 joint cells, all 50 states plus DC and 436 districts
including DC. PUF source ingestion retained 207,692 ordinary records and excluded
four disclosure records. A corrected SCF wage-code interpretation passed source
preparation and model-mechanism checks. Those results belong to their respective
component revisions; they do not establish a calibrated result on this branch.

The corrected canonical-donor codec v2 was rebuilt from the same accepted typed
PUF source. All 207,692 returns and 59 outputs passed selected-cohort replay and
byte/value serialization checks in 24.37 seconds, using 1.95 GB peak RSS. The 481
source/control files and four resources matched their before/after/current pins.
Receipt: `6b334ca8df6c6ba721b60f84d28c43151a1e1b54e097616a3c0fa208daeb8cba`.
This run constructs the donor; it does not fit or place it onto survey recipients.

The identity encoder passed two 40-case preflights and four 40-case
timing runs in both execution orders. The 36 tiny invented cases retain exact
identity bytes and mutation checks. Nine of the 72 case/trial comparisons were
slower, including the small Python-string Frame in both orders; larger numeric
fixtures improved substantially. These timings do not establish genuine-build
speed. It is now integrated and passes the current 314-case selection, with the
newer current-wage projection preserved byte for byte. That projection was absent
from the benchmark's accepted baseline.

The following work remains open:

1. Run the accepted twenty-node atomic and financial composition on the genuine
   combined survey population. Its cold/required replay, complete retained
   fields and geography, default three-feature versus explicit five-feature
   conditioning, and both final mutation refusals pass on invented inputs.
   Two test-code mistakes in the initial four-case run were corrected and
   rerun separately; the passing mutation cases were preserved. See the
   [composition acceptance](../experiments/us-atomic-financial-composition-acceptance-20260909.json).
   Native fit quality and admission of the financial result into subsequent
   calibration remain unassessed.
2. Integrate the adopted Social Security conditioning measurement and qualify
   recipient return roles before native PUF55 fitting. Thirty-one invented
   controls pass the authenticated filer/joint-spouse report-sum proxy, source
   preservation, missingness and refusal checks. An incomplete selected report
   uses a separately declared eight-predictor route; a known total uses nine.
   The helper uses the preparation's retained modeled roles, whose relationship
   to current-money tax-unit construction still needs explicit qualification.
   See the [measurement decision](puf55-survey-ss-measurement-decision.md) and
   [scoped control result](../experiments/us-puf55-survey-ss-measurement-31-controls-20260909.json).
   Route-aware graph fitting and attachment remain pending. The genuine
   207,692-return canonical donor has already passed its 55-output projection;
   that does not establish recipient matching. Complete survey
   beneficiary/component modeling, and supply SCF loan inputs. Separate component runs passed
   128 profile/compatibility controls and 26 current-survey predictor controls;
   see [the implementation status](current-survey-puf59-progress.md) and
   [donor construction and growth](puf2015-canonical59-and-growth.md).
   The genuine 207,692-return donor construction does not establish survey fit
   quality, complete enrichment or a releasable population.
3. Verify every applicable model input on each source/clone channel. The proposed
   national/CD profile retains 161 required model inputs, with state and county
   but without requiring the engine to consume block and tract. Independently,
   the build must retain one assigned Census block and derive its larger
   geographies. Prior wages remain excluded. A source operator's existence is
   not complete cell coverage.
4. Extend the accepted small native replay to the complete build. The genuine
   seven-node age-development run now passes at 1/1000: 1,584 source households,
   3,168 records after the support clone, final export/readback and owner/target
   verification, 71.1 minutes and 8.26 GB peak RSS. Its source is frozen at
   `a9895d8a5`, before the new Social Security, PUF55 and atomic-geography work.
   The prior two-hour failure and stale-derived-attachment failure remain failed
   historical runs. [The scoped acceptance record](../experiments/us-survey-age-development-20260909.json)
   does not certify enrichment, full national/CD calibration or a release.
5. Run real model evaluation, national/CD calibration, holdout checks and complete
   export/replay verification, followed by a dashboard bound to that exact file.
   Check every pruned analysis file separately.

These are active workstreams. No release, merge or deployment is implied by this
draft, and the source changes do not relax the outstanding acceptance checks.

The population-only Census API adapter passes thirty-five invented controls.
The native Delaware source control preserves all 15,317 populated blocks and
reconciles them to the independent Census state total of 989,948. It counts
4,881 zero-population blocks, checks CD119/PUMA joins and exactly reads back its
79,769-byte support artifact. The run took 10.94 seconds and 1.735 GB peak RSS.
The first attempt correctly refused an incomplete ZIP-member declaration;
a separate metadata probe established the six-member archive roster, and the
corrected check still decompresses only `NationalCD119.txt`. The
[accepted source control](../experiments/us-atomic-native-de-corrected-1-control-20260909.json)
preserves the original failed evidence. This is not national population or
release acceptance. Delaware-only support must not enter the national survey
graph.

The subsequent population-only national acquisition and normalization now pass
for all fifty states and DC. The 104 exact sources produce 5,769,942 populated
blocks, independently reconciling every state to a total of 331,449,281 people.
Every block retains its identity and population, with complete CD119/PUMA joins.
The full support artifact is 28,862,508 bytes and passes exact serialization and
readback. Normalization took 82.97 seconds and 6.814 GB peak RSS. Its SHA-256 is
`5edc0e77471ba31d550a1eed416d5b46ada0a35425718eb87cfabe4d66fe4960`;
see the [national source control](../experiments/us-atomic-native-national-1-control-20260909.json).
Postchecks reauthenticated code and compared the 104 native pins from bounded
receipts without reopening source bodies. This clears the national support
normalization check; assigning households, evaluating geographic fit and
calibrating the enriched survey remain separate acceptance steps.

The financial successor's positive control reached its 600 CPU-second limit
without a final receipt. A separate, bounded profile of the unchanged invented
cold/required financial fixture now passes its test, original teardown and all
final code/resource checks: 303.90 CPU seconds, 308.26 wall seconds and 594.3 MB
peak RSS. This diagnoses the fixture; it does not accept the financial successor.
See the [profile evidence](../experiments/us-financial-fixture-profile-20260910.json).
Loaded ACS code verification accounts for 180.20 cumulative seconds inside the
298.15-second profiled fixture. Its nested function checker runs 2,009,108 times
and uses 91.05 self seconds; complete Frame identity uses 7.31 cumulative seconds.
Cumulative timings overlap and profiling adds overhead. The invocation-local
code comparison memo now passes all 18 focused invented controls, including
changed source, aliases, globals, closures, mutable constants and the historical
catalogue caller. Source and resource checks pass before, after and in the
external postcheck. See the [control evidence](../experiments/us-acs-loaded-code-controls-20260910.json).
The paired full-fixture run also passed correctness and final checks, but took
319.79 wall seconds versus 308.26 for the baseline. The memo added eligibility
work and demonstrated no speed improvement, so its implementation was not
adopted. The exact experimental patch and [paired comparison](../experiments/us-acs-code-memo-comparison-20260910.json)
remain recorded. Further profiling is narrowing the original verification cost;
the remaining successor controls and native financial pilot remain pending.

Current CI separately reports stale source-attested spec/seed fingerprints.
The worker resource identity test now follows the actual lazy import closure
and includes an invented opened-JSON regression; its new CI result is pending.
Neither the component passes nor this profile establishes a green consolidation.

## Related reviews

- [Microcosm → Orrery exporter, #888](https://github.com/PolicyEngine/microcosm/pull/888):
  already published separately. It preserves the supplied schema metadata and
  exact large integers; graph visibility does not infer domain verdicts.
- [Orrery review index, #6](https://github.com/TheAxiomFoundation/orrery/pull/6)
  and [search improvements, #4](https://github.com/TheAxiomFoundation/orrery/pull/4).
- [Dynamics graph integration, #420](https://github.com/PolicyEngine/microcosm-dynamics/pull/420):
  owned by the separate retirement-model task and tested on synthetic inputs.
- [Candidate methods and paper updates, site #72](https://github.com/PolicyEngine/microcosm.institute/pull/72):
  public component evidence and remaining release checks.

The accepted local shared viewer remains a separate consumer. There is no package
upgrade or competing generic graph shell in this consolidation.
