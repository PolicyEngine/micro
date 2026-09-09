# US graph build: review guide

This branch consolidates the US graph build work for review. The intended file
supports national and 119th congressional district analysis from one population.
It is still a development build: complete enrichment, fiscal calibration and
release verification have not passed together.

## Architecture and review order

The construction order is ACS + CPS ASEC → combined survey multispine → PUF
clone and donor enrichment → supported joint geography → rules evaluation and
calibration → verified full and pruned exports. The PUF operator acts on the
combined survey frame. A separate ASEC–PUF base is not the intended architecture.

| Area | Main source entry points | What to review |
| --- | --- | --- |
| Graph execution and storage | `packages/microcosm-graph/src/microcosm/graph/{decl,executor,manifest,store,codecs,schema}.py` | Typed inputs and outputs, ownership, artifact ancestry, cache identity and nullable round trips |
| Survey source preparation | `packages/microcosm-build/src/microcosm/build/us_runtime/{acs_population_catalogue,asec_population_catalogue,survey_population_preparation}.py` | Source identity, entity links, source universes and current income transformations |
| Combined survey and clone | `us_runtime/{graph_composed_population,graph_survey_population,graph_combined_clone}.py` | ACS and ASEC composition before the clone; native versus detail channels |
| Enrichment | `us_runtime/{full_puf_enrichment,graph_full_puf_enrichment,graph_current_survey_puf_transfer}.py` | Target ordering, conditioning, observed-value preservation and complete replay |
| Conditional models | `packages/microcosm-fit/src/microcosm/fit/{qrf_target,graph_legacy_train,graph_legacy_apply_matrix}.py` | Reusable model artifacts, deterministic draws and target regimes |
| Geography | `us_runtime/{puma_ladder,puma_ladder_sources,graph_geography}.py` | Joint county/district support, vintage and source/PUMA preservation |
| Survey mass and calibration | `us_runtime/{survey_origin_budget,graph_survey_budget,graph_survey_calibration}.py`; `packages/microcosm-calibrate/src/microcosm/calibrate/{group_bounds,solve}.py` | Original survey mass, grouped bounds, fixed support and existing ungrouped solver behavior |
| Compatibility | `packages/microcosm-build/src/microcosm/build/{frame_checkpoint,us_runtime/__init__}.py` | Current-main APIs, checkpoint metadata and existing country consumers |

Paths beginning `us_runtime/` are relative to
`packages/microcosm-build/src/microcosm/build/`.
The branch contains a substantial consolidation; review each area and its tests
before deciding how to land it. Shared runtime changes overlap with
[#873](https://github.com/PolicyEngine/microcosm/pull/873) and Anthony's
[#885](https://github.com/PolicyEngine/microcosm/pull/885). Their final contracts
need reconciliation; this draft does not supersede either review.

## Verification completed on the integration checkout

- The first integration selection passed **36 tests**: eight solver, eleven
  snapshot/storage, nine geography and eight public-facade controls.
- After applying the independently reviewed replay correction, **57 enrichment
  graph tests** passed at `dfa7f872cd3eba3c42adf5758cde8b3ca38f3d17`. These include
  cold execution, required replay, reconstruction through a fresh Frame store,
  inherited tax-unit values and malformed artifact/ancestry refusals.
- The second run took 44.09 seconds wall time, 35.49 seconds CPU and 620.6 MB
  peak RSS. Its 273 source/control files, 5,983 model declaration files and eleven
  code resources matched before, after and in the external postcheck. The model
  declaration checks did not execute the tax-benefit engine.
- The CI test inventory accounts for all 413 tracked test files. This is not a
  claim that all 413 files or the complete repository CI have passed locally.

Both test selections use invented inputs. The replay correction also received
an independent Fable source review that closed seven findings. That review did
not rerun the tests or certify a population file.

The ordinary execution receipts are identified by SHA-256
`bd9f944ed95e08de5775b36bca2158c38dc18bed858e9d304ccdfa1f983a8d43`
and `5f8fb487153db50826695d10a6341eb5bd621d88343af70c4ebfe472599528f2`.
Private runtime records and generated population artifacts are kept outside this
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
2. Complete the 59-output PUF donor profile, target-year growth and SCF loan
   inputs. The existing 65-output mechanism remains a separately tested
   compatibility path; a passing synthetic donor does not supply the missing
   source information.
3. Verify every applicable model input on each source/clone channel. The proposed
   national/CD profile retains 161 required inputs, dropping block and tract
   requirements while retaining state and county as model inputs. Prior wages
   remain excluded. A source operator's existence is not complete cell coverage.
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
