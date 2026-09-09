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

Block-first assignment is a required change, not completed functionality in this
branch. The existing geography operator chooses a joint tract/district cell.
The US and UK assignment contracts, existing implementation and remaining graph
work are distinguished in [Geography assignment](geography-assignment.md).

| Area | Main source entry points | What to review |
| --- | --- | --- |
| Graph execution and storage | `packages/microcosm-graph/src/microcosm/graph/{decl,executor,manifest,store,codecs,schema}.py` | Typed inputs and outputs, ownership, artifact ancestry, cache identity and nullable round trips |
| Survey source preparation | `packages/microcosm-build/src/microcosm/build/us_runtime/{acs_population_catalogue,asec_population_catalogue,survey_population_preparation}.py` | Source identity, entity links, source universes and current income transformations |
| Combined survey and clone | `us_runtime/{graph_composed_population,graph_survey_population,graph_combined_clone}.py` | ACS and ASEC composition before the clone; native versus detail channels |
| Enrichment | `us_runtime/{full_puf_enrichment,graph_full_puf_enrichment,graph_current_survey_puf_transfer}.py` | Target ordering, conditioning, observed-value preservation and complete replay |
| Conditional models | `packages/microcosm-fit/src/microcosm/fit/{qrf_target,graph_legacy_train,graph_legacy_apply_matrix}.py` | Reusable model artifacts, deterministic draws and target regimes |
| Geography | `us_runtime/{puma_ladder,puma_ladder_sources,graph_geography}.py` | Existing joint-cell implementation; pending block assignment, versioned projections and source/PUMA preservation |
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
grouped-bound, metadata-store and facade coverage work, which remains open.
Environment-specific prepatch byte fixtures do not establish portable CI byte
parity. Existing v1 graph stores remain preserved; v2 execution uses a new store
rather than silently promoting old frames.

Private runtime records and generated population artifacts stay outside this
source PR. Receipt identifiers are audit references, not reproducibility inputs.

## Component evidence and remaining work

Separate component work has verified the national Census joint-geography source
artifact: 2,462 PUMAs, 87,841 joint cells, all 50 states plus DC and 436 districts
including DC. PUF source ingestion retained 207,692 ordinary records and excluded
four disclosure records. A corrected SCF wage-code interpretation passed source
preparation and model-mechanism checks. Those results belong to their respective
component revisions; they do not establish a calibrated result on this branch.

The following work remains open:

1. Finish current survey predictors and demographic graph bindings, then connect
   them to the genuine combined survey population.
2. Integrate the genuine 59-output donor and its corrected integrity codec with
   the combined population, complete source-qualified Social Security recipient
   reconciliation, and supply SCF loan inputs. Separate component runs passed
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
4. Resolve repeated per-cell identity encoding in the survey verifier. One genuine
   successor run reached persisted-artifact verification but exhausted its
   two-hour CPU limit. That run failed; it is not a verified build. Performance
   changes must preserve the identity bytes and pass small controls first.
5. Run real model evaluation, national/CD calibration, holdout checks and complete
   export/replay verification, followed by a dashboard bound to that exact file.
   Check every pruned analysis file separately.

These are active workstreams. No release, merge or deployment is implied by this
draft, and the source changes do not relax the outstanding acceptance checks.

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
