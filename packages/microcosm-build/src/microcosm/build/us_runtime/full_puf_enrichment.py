"""Complete canonical PUF enrichment boundaries; no source admission is issued.

An upstream source owner supplies interpreted, period-aligned canonical donor
columns and a complete survey recipient. This module does not read raw PUF,
reinterpret E19200, choose missing-value aliases, or manufacture source evidence.
It reuses the maintained ordered QRF protocol and person/tax-unit finalizer.
Graph hosts must authenticate actual typed edges and retain their independent
full-population replay checks. These value checks do not replace either duty.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from microcosm.fit import _graph_legacy_qrf as codec
from microcosm.fit import model_input, qrf, qrf_target
from microcosm.fit.graph_legacy_apply_matrix import decode_matrix_apply_state
from microcosm.fit.graph_legacy_qrf import (
    legacy_qrf_apply_matrix_nodes,
    legacy_qrf_train_nodes,
)
from microcosm.frame import Frame

from . import puf_support as support

PERSON_OUTPUTS = tuple(support.PUF_TAX_DETAIL_DEFAULT_PERSON_OUTPUTS)
TAX_UNIT_OUTPUTS = tuple(support.PUF_TAX_DETAIL_DEFAULT_TAX_UNIT_OUTPUTS)
TARGETS = (*PERSON_OUTPUTS, *TAX_UNIT_OUTPUTS)
PREDICTORS = tuple(support.PUF_TAX_DETAIL_DEFAULT_PREDICTORS)
PHASE = "us_full_canonical_puf_enrichment"


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def _numeric(values, *, label, boolean=False, nullable=False):
    """Validate physical values before conversion; never parse strings as money."""
    series = pd.Series(values, copy=False)
    if not nullable:
        _require(not series.isna().any(), f"PUF_UNKNOWN:{label}")
    observed = series.dropna()
    if boolean:
        valid = observed.map(lambda v: isinstance(v, (bool, np.bool_)))
    else:
        valid = observed.map(
            lambda v: (
                not isinstance(v, (bool, np.bool_))
                and isinstance(v, (int, float, np.integer, np.floating))
            )
        )
    _require(bool(valid.all()), f"PUF_PHYSICAL_TYPE:{label}")
    if not boolean:
        # Do not let integer source identities/amounts silently lose bits at
        # the explicit float64 model boundary.
        _require(
            all(
                not isinstance(v, (int, np.integer)) or abs(int(v)) <= 2**53
                for v in observed
            ),
            f"PUF_FLOAT64_INTEGER_RANGE:{label}",
        )
    numeric = series.to_numpy(dtype=np.float64, na_value=np.nan)
    _require(
        bool(np.isfinite(numeric[~series.isna().to_numpy()]).all()),
        f"PUF_NONFINITE:{label}",
    )
    return numeric


def _ids(values, label):
    series = pd.Series(values, copy=False)
    _require(series.dtype == np.dtype("int64"), f"PUF_ID_DTYPE:{label}")
    result = series.to_numpy(copy=True)
    _require(bool((result > 0).all()), f"PUF_ID_DOMAIN:{label}")
    return result


def _known(values, known, columns, label):
    _require(
        isinstance(known, pd.DataFrame)
        and known.index.equals(values.index)
        and tuple(known.columns) == tuple(columns),
        f"PUF_KNOWNNESS_AXIS:{label}",
    )
    for column in columns:
        mask = known[column]
        _numeric(mask, label=f"{label}.{column}.known", boolean=True)
        _require(bool(mask.all()), f"PUF_UNKNOWN:{label}.{column}")


def canonical_full_puf_donor(
    person,
    tax_unit,
    *,
    person_known,
    tax_unit_known,
    person_targets_at_tax_unit=(),
):
    """Reduce canonical columns after upstream interpretation, with no imputation.

    Some person destinations are observed only as return totals, for example
    self-employed pension contributions. Such targets must be explicitly listed
    in ``person_targets_at_tax_unit`` and supplied on the tax-unit table. A
    destination's eventual grain never changes the declared donor grain.
    Knownness covers every consumed nonstructural field, including true zeros.
    Raw-to-canonical judgments (including mortgage decomposition) belong upstream.
    When all person destinations are return totals, ``person=None`` avoids
    inventing donor persons. Supply the separately interpreted canonical
    ``tax_unit_person_count`` on the return table in that case.
    """
    _require(
        type(person_targets_at_tax_unit) is tuple
        and len(set(person_targets_at_tax_unit)) == len(person_targets_at_tax_unit)
        and set(person_targets_at_tax_unit) <= set(PERSON_OUTPUTS),
        "PUF_DONOR_GRAIN_DECLARATION",
    )
    pcols = tuple(c for c in PERSON_OUTPUTS if c not in person_targets_at_tax_unit)
    return_only = person is None
    _require(
        not return_only
        or (person_targets_at_tax_unit == PERSON_OUTPUTS and person_known is None),
        "PUF_RETURN_ONLY_GRAIN",
    )
    tcols = (
        "weight",
        "filing_status_code",
        *(("tax_unit_person_count",) if return_only else ()),
        *person_targets_at_tax_unit,
        *TAX_UNIT_OUTPUTS,
    )
    tables = [(tax_unit, ("tax_unit_id", *tcols), "tax_unit")]
    if not return_only:
        tables.append((person, ("person_id", "person_tax_unit_id", *pcols), "person"))
    for table, required, label in tables:
        _require(
            isinstance(table, pd.DataFrame)
            and table.index.is_unique
            and table.columns.is_unique
            and set(required) <= set(table.columns),
            f"PUF_DONOR_COLUMNS:{label}",
        )
    _require(
        (return_only or not set(person_targets_at_tax_unit) & set(person.columns))
        and not set(pcols) & set(tax_unit.columns),
        "PUF_DONOR_GRAIN_COLLISION",
    )
    tids = _ids(tax_unit.tax_unit_id, "tax_unit")
    _require(
        len(tids) > 0 and len(set(tids)) == len(tids),
        "PUF_DONOR_MEMBERSHIP",
    )
    if not return_only:
        pids = _ids(person.person_id, "person")
        links = _ids(person.person_tax_unit_id, "person_tax_unit_id")
        _require(
            len(set(pids)) == len(pids) and set(links) == set(tids),
            "PUF_DONOR_MEMBERSHIP",
        )
        _known(person, person_known, pcols, "person")
    _known(tax_unit, tax_unit_known, tcols, "tax_unit")
    # Validate EVERY source cell before groupby can skip a missing member.
    if not return_only:
        normalized = pd.DataFrame(index=person.index)
        for column in pcols:
            normalized[column] = _numeric(
                person[column],
                label=f"person.{column}",
                boolean=column in support._PUF_TAX_DETAIL_BOOLEAN_PERSON_OUTPUTS,
            )
        grouped = normalized.groupby(links, sort=False).sum(min_count=1).reindex(tids)
        count = pd.Series(links).value_counts(sort=False).reindex(tids).to_numpy()
    else:
        count = _numeric(tax_unit.tax_unit_person_count, label="tax_unit_person_count")
        _require(
            bool(((count >= 1) & (count == np.floor(count))).all()),
            "PUF_PERSON_COUNT_DOMAIN",
        )
    donor = pd.DataFrame(index=tax_unit.index)
    for column in (*person_targets_at_tax_unit, *TAX_UNIT_OUTPUTS):
        donor[column] = _numeric(tax_unit[column], label=f"tax_unit.{column}")
    for column in pcols:
        donor[column] = _numeric(grouped[column], label=f"reduced.{column}")
    status = _numeric(tax_unit.filing_status_code, label="filing_status_code")
    _require(bool(np.isin(status, [1, 2, 3, 4, 5]).all()), "PUF_FILING_STATUS_DOMAIN")
    for column in support._PUF_TAX_DETAIL_BOOLEAN_PERSON_OUTPUTS:
        values = donor[column].to_numpy()
        _require(
            bool(
                ((values >= 0) & (values <= count) & (values == np.floor(values))).all()
            ),
            f"PUF_BOOLEAN_COUNT_DOMAIN:{column}",
        )
    for column in support._PUF_TAX_DETAIL_DISCRETE_TAX_UNIT_OUTPUTS:
        values = donor[column].to_numpy()
        _require(
            bool(
                (
                    (values == 0)
                    | (
                        (values >= 1000)
                        & (values <= 9999)
                        & (values == np.floor(values))
                    )
                ).all()
            ),
            f"PUF_YEAR_DOMAIN:{column}",
        )
    # These are canonical arithmetic aliases, after complete cell validation.
    feature_values = (
        status,
        count.astype(np.float64),
        donor.employment_income_before_lsr.to_numpy(),
        donor.self_employment_income_before_lsr.to_numpy(),
        donor.taxable_interest_income.to_numpy(),
        donor.qualified_dividend_income.to_numpy()
        + donor.non_qualified_dividend_income.to_numpy(),
        donor.short_term_capital_gains.to_numpy(),
        donor.long_term_capital_gains_before_response.to_numpy(),
    )
    for name, values in zip(PREDICTORS, feature_values, strict=True):
        donor[name] = _numeric(values, label=name)
    donor["weight"] = _numeric(tax_unit.weight, label="weight")
    weights = donor.weight.to_numpy()
    _require(
        bool((weights >= 0).all()) and np.isfinite(weights.sum()) and weights.sum() > 0,
        "PUF_DONOR_WEIGHT_DOMAIN",
    )
    return donor.loc[:, [*PREDICTORS, *TARGETS, "weight"]].copy()


def _recipient_matrix(frame, *, predictor_known):
    tax_unit, person = frame.table("tax_unit"), frame.table("person")
    mask = support.puf_tax_detail_clone_mask(tax_unit, entity="tax_unit")
    ids = _ids(tax_unit.loc[mask, "tax_unit_id"], "recipient")
    selected_index = pd.Index(ids, name="tax_unit_id")
    _require(len(ids) > 0, "PUF_NO_RECIPIENTS")
    _require(
        isinstance(predictor_known, pd.DataFrame)
        and predictor_known.index.equals(selected_index),
        "PUF_RECIPIENT_KNOWNNESS_AXIS",
    )
    _known(predictor_known, predictor_known, PREDICTORS, "recipient_predictor")
    person_mask = person.person_tax_unit_id.isin(ids)
    # The maintained resolver below owns ACS source applicability and its exact
    # age-15 universe zeros. Screen physical numeric types first, since pandas
    # numeric conversion otherwise accepts strings, booleans or datetime values.
    for name in PREDICTORS:
        plan = support._strict_predictor_source_plan(
            name, tax_unit=tax_unit, person=person
        )
        if plan.source_column == "filing_status_code" or plan.entity == "derived":
            continue
        table = person if plan.entity == "person" else tax_unit
        rows = person_mask if plan.entity == "person" else mask
        for column in plan.columns:
            if column in table:
                _numeric(
                    table.loc[rows, column],
                    label=f"recipient.{plan.entity}.{column}",
                    nullable=True,
                )
    features, universe = support._strict_recipient_predictor_surface(
        frame, mask, PREDICTORS, person_outputs=PERSON_OUTPUTS
    )
    selected = features.loc[mask, list(PREDICTORS)].copy()
    selected.index = selected_index
    selected = selected.astype("float64")
    return (
        model_input.encode_recipient_matrix(
            selected, entity="tax_unit", entity_ids=ids
        ),
        universe,
    )


@dataclass(frozen=True)
class FullPufInputs:
    donor: pd.DataFrame
    donor_frame: Frame
    matrix: bytes
    recipient_universe: Mapping[str, object]


def prepare_full_puf_inputs(frame, donor, *, predictor_known):
    """Prepare the full input surfaces; absence never falls back to legacy zeros."""
    _require(
        isinstance(donor, pd.DataFrame)
        and tuple(donor.columns) == (*PREDICTORS, *TARGETS, "weight"),
        "PUF_FULL_DONOR_ROSTER",
    )
    for column in donor:
        _numeric(donor[column], label=f"donor.{column}")
    counts = donor[PREDICTORS[1]].to_numpy()
    weights = donor["weight"].to_numpy()
    _require(
        len(donor) > 0
        and donor.index.is_unique
        and bool(((counts >= 1) & (counts == np.floor(counts))).all())
        and bool(np.isin(donor[PREDICTORS[0]], [1, 2, 3, 4, 5]).all())
        and bool((weights >= 0).all())
        and np.isfinite(weights.sum())
        and weights.sum() > 0,
        "PUF_DONOR_MODEL_DOMAIN",
    )
    for column in support._PUF_TAX_DETAIL_BOOLEAN_PERSON_OUTPUTS:
        values = donor[column].to_numpy()
        _require(
            bool(
                (
                    (values >= 0) & (values <= counts) & (values == np.floor(values))
                ).all()
            ),
            f"PUF_BOOLEAN_COUNT_DOMAIN:{column}",
        )
    for column in support._PUF_TAX_DETAIL_DISCRETE_TAX_UNIT_OUTPUTS:
        values = donor[column].to_numpy()
        _require(
            bool(
                (
                    (values == 0)
                    | (
                        (values >= 1000)
                        & (values <= 9999)
                        & (values == np.floor(values))
                    )
                ).all()
            ),
            f"PUF_YEAR_DOMAIN:{column}",
        )
    matrix, universe = _recipient_matrix(frame, predictor_known=predictor_known)
    # Every input is now physically numeric, finite, and known. The maintained
    # helper constructs the actual weighted donor Frame and repeats its strict
    # source checks; its historical fillna operation has no missing values to fill.
    inputs = support.prepare_us_puf_tax_detail_chain_inputs(
        frame,
        donor,
        predictors=PREDICTORS,
        person_outputs=PERSON_OUTPUTS,
        tax_unit_outputs=TAX_UNIT_OUTPUTS,
        require_complete_recipient_predictors=True,
    )
    _require(
        inputs.donor.equals(donor) and inputs.recipient_predictor_universe == universe,
        "PUF_PREPARATION_CHANGED_CANONICAL_INPUT",
    )
    return FullPufInputs(inputs.donor, inputs.donor_frame, matrix, universe)


def full_puf_train_apply_nodes(
    *,
    donor_population,
    recipient_population,
    matrix_producer,
    seed,
    n_estimators,
    zero_atol,
    prefix="puf_full",
):
    """Declare all 65 real fits/draws; each draw reads its raw predecessors."""
    fits = legacy_qrf_train_nodes(
        prefix + ".fit",
        population=donor_population,
        entity="tax_unit",
        predictors=PREDICTORS,
        targets=TARGETS,
        seed=seed,
        n_estimators=n_estimators,
        zero_atol=zero_atol,
        phase=PHASE,
    )
    applies = legacy_qrf_apply_matrix_nodes(
        prefix + ".apply",
        population=recipient_population,
        fit_nodes=fits,
        matrix_producer=matrix_producer,
        seed=seed,
        phase=PHASE,
    )
    return fits, applies


def decode_full_puf_draws(
    *, matrix, matrix_producer_key, raw_draws, apply_state, training_state, seed
):
    """Check actual typed-edge payloads against the complete model/raw history."""
    _require(codec._hash(matrix_producer_key), "PUF_MATRIX_PRODUCER_KEY")
    prepared = model_input.decode_recipient_matrix(matrix)
    packet = decode_matrix_apply_state(apply_state)
    application, chain = codec.read_application(
        codec.encode_json(packet["application"])
    )
    training, fitted = codec.read_training(training_state)
    fitted_values = fitted.to_dict()
    applied_values = chain.to_dict()
    _require(
        prepared.entity == chain.entity == "tax_unit"
        and tuple(prepared.features.columns) == tuple(chain.predictors) == PREDICTORS
        and tuple(chain.targets) == tuple(chain.completed_targets) == TARGETS
        and tuple(fitted_values["completed_targets"]) == TARGETS
        and all(
            fitted_values[key] == applied_values[key]
            for key in (
                "predictors",
                "targets",
                "entity",
                "weight_kind",
                "weight_sha256",
                "model_config",
                "donor_index",
            )
        )
        and application["models"] == training["models"]
        and application["seed"] == seed
        and chain.recipient_index == qrf._index_identity(prepared.features.index),
        "PUF_FULL_CHAIN_IDENTITY",
    )
    _require(
        packet["matrix_sha256"] == codec.sha(matrix)
        and packet["matrix_producer_key"] == matrix_producer_key,
        "PUF_FULL_MATRIX_BINDING",
    )
    _require(
        isinstance(raw_draws, Mapping) and tuple(raw_draws) == TARGETS, "PUF_RAW_ROSTER"
    )
    _require(
        application["raw_targets"]
        == [
            {"target": target, "sha256": codec.sha(raw_draws[target])}
            for target in TARGETS
        ],
        "PUF_RAW_HISTORY",
    )
    return pd.DataFrame(
        {
            target: codec.read_raw_target(
                raw_draws[target], target=target, index=prepared.features.index
            )
            for target in TARGETS
        },
        index=prepared.features.index,
    )


def finalize_full_puf(
    frame,
    donor,
    *,
    predictor_known,
    matrix,
    matrix_producer_key,
    raw_draws,
    apply_state,
    training_state,
    last_model,
    seed,
):
    """Use actual finalizer judgments only after the complete raw chain validates.

    Returns a candidate Frame plus tail-cap/universe evidence. A graph placement
    owner must expose every changed person/tax-unit column, attach only on the
    PUF masks, and run the existing full-population replay verifier afterwards.
    This function itself never creates a live Population/source qualification.
    """
    inputs = prepare_full_puf_inputs(frame, donor, predictor_known=predictor_known)
    _require(matrix == inputs.matrix, "PUF_RECIPIENT_MATRIX_CHANGED")
    raw = decode_full_puf_draws(
        matrix=matrix,
        matrix_producer_key=matrix_producer_key,
        raw_draws=raw_draws,
        apply_state=apply_state,
        training_state=training_state,
        seed=seed,
    )
    # The final fitted target consumed every preceding donor outcome. Binding
    # its actual trusted producer bytes therefore checks the entire donor value
    # surface, including fields used only by sparsity/tail finalization. A donor
    # with the same index/weights but altered values cannot adjust these draws.
    training, fitted_state = codec.read_training(training_state)
    last = qrf_target.LegacyQRFTargetArtifact.from_trusted_bytes(
        last_model, expected_sha256=training["models"][-1]["sha256"]
    )
    _require(
        last.target == TARGETS[-1]
        and last.next_training_state == fitted_state
        and last.training_id == training["models"][-1]["training_id"],
        "PUF_FINAL_MODEL_BINDING",
    )
    resolved = qrf._resolve_qrf_fit_input(
        inputs.donor_frame, list(PREDICTORS), list(TARGETS), "design"
    )
    qrf.RegimeGatedQRF._validate_chain_donor(last.training_state._chain(), resolved)
    _require(
        last.donor_sha256
        == qrf_target._consumed_values_sha256(resolved.table, (*PREDICTORS, *TARGETS)),
        "PUF_DONOR_CONSUMED_BYTES",
    )
    mask = support.puf_tax_detail_clone_mask(frame.table("tax_unit"), entity="tax_unit")
    # Explicit adapter between separate graph entity-ID and pandas row indexes;
    # matrix recomputation above proves the ordered IDs before this relabeling.
    raw.index = frame.table("tax_unit").index[mask]
    caps = []
    result = support.finalize_us_puf_tax_detail_predictions(
        frame,
        inputs.donor,
        raw.copy(deep=True),
        person_outputs=PERSON_OUTPUTS,
        tax_unit_outputs=TAX_UNIT_OUTPUTS,
        tail_bound_diagnostics=caps,
        absent_cells=support.PUF_ABSENT_CELLS_PRESERVE_NULLS,
    )
    return result, {
        "scope": PHASE,
        "target_order": list(TARGETS),
        "recipient_universe": dict(inputs.recipient_universe),
        "tail_bounds": caps,
        "matrix_sha256": codec.sha(matrix),
        "raw_target_sha256": {
            target: codec.sha(raw_draws[target]) for target in TARGETS
        },
        "source_admission_issued": False,
        "release_eligible": False,
    }
