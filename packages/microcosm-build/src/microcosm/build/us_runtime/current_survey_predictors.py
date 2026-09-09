"""Source-qualified current ASEC to ACS financial predictor preparation.

This is a survey-multispine operation before PUF enrichment. The live retained
preparation authenticates source observations; serialized evidence never issues
source authority. Financial ACS leaves are modeled from three current ASEC
money totals, with the maintained split assumptions applied after the draws.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields

import numpy as np
import pandas as pd

from microcosm.fit import _graph_legacy_qrf as codec
from microcosm.fit import model_input
from microcosm.frame import WeightKind

from . import acs_income_universe as universe
from . import cps_carried_current as leaves
from . import graph_puf_diagnostic_consumer as host
from . import support_provenance as provenance

source = host.survey_source
FEATURES = (
    "survey_predictor_age",
    "survey_predictor_employment_income",
    "survey_predictor_self_employment_income",
)
TARGETS = ("survey_current_INT_VAL", "survey_current_DIV_VAL", "survey_current_CAP_VAL")
MONEY_FIELDS = leaves.CPS_CURRENT_PREDICTOR_MONEY_FIELDS
OUTPUTS = leaves.CPS_CURRENT_PREDICTOR_PERSON_LEAVES
PROTOCOL = "microcosm.us.current-survey-predictor-completion.v1"
PHASE = "survey_multispine_current_financial_completion"
SEED = 578


def require(condition, reason):
    if not condition:
        raise ValueError("CURRENT_SURVEY_PREDICTOR_" + reason)


def _numeric(value, *, nullable=False):
    series = pd.Series(value, copy=False)
    require(
        pd.api.types.is_numeric_dtype(series.dtype)
        and not pd.api.types.is_bool_dtype(series.dtype)
        and not pd.api.types.is_complex_dtype(series.dtype),
        "PHYSICAL_NUMERIC_TYPE",
    )
    if pd.api.types.is_integer_dtype(series.dtype):
        require(bool(series.dropna().abs().le(2**53).all()), "FLOAT64_INTEGER_RANGE")
    result = series.to_numpy(dtype=np.float64, na_value=np.nan, copy=True)
    require(bool(np.isfinite(result[~np.isnan(result)]).all()), "NONFINITE")
    require(nullable or not np.isnan(result).any(), "UNKNOWN")
    return result


def _ids(values):
    require(values.dtype == np.dtype("int64"), "ID_DTYPE")
    result = values.to_numpy(copy=True)
    # Assembly preserves nonnegative source IDs, including native ACS ID zero.
    require(bool((result >= 0).all()) and len(set(result)) == len(result), "ID_AXIS")
    return result


def _acs_earnings(frame):
    """Verify both native adjustment identities before the named NIU operator."""
    person = frame.person
    mask = person[provenance.support_channel_column("person")].eq("acs")
    selected = person.loc[mask]
    require(len(selected) > 0, "ACS_EMPTY")
    require(selected.source_year.astype(str).eq("2024").all(), "ACS_PERIOD")
    age = _numeric(selected.age)
    raw_age = _numeric(selected.AGEP)
    require(
        np.array_equal(age, raw_age)
        and ((age >= 0) & (age <= 99) & (age == np.floor(age))).all(),
        "ACS_AGE_IDENTITY",
    )
    adjustment = _numeric(selected.ADJINC, nullable=True)
    require(np.isfinite(adjustment).all() and (adjustment > 0).all(), "ACS_ADJINC")
    for output, raw in universe.ACS_PUMS_EARNINGS_SOURCE_COLUMNS.items():
        require(raw in selected and output in selected, "ACS_EARNINGS_COLUMNS")
        original = _numeric(selected[raw], nullable=True)
        carried = _numeric(selected[output], nullable=True)
        observed = ~np.isnan(original)
        require(not (observed & (age < 15)).any(), "ACS_OUTSIDE_UNIVERSE_OBSERVED")
        require(
            np.array_equal(observed, ~np.isnan(carried)), "ACS_EARNINGS_MISSINGNESS"
        )
        if raw == "WAGP":
            require((original[observed] >= 0).all(), "ACS_WAGE_DOMAIN")
        expected = original * (adjustment / 1_000_000.0)
        require(
            np.array_equal(
                expected[observed].view("uint64"), carried[observed].view("uint64")
            ),
            "ACS_EARNINGS_ADJUSTMENT",
        )
        require(not ((age >= 15) & ~observed).any(), "ACS_ELIGIBLE_EARNINGS_UNKNOWN")
    applied = universe.apply_acs_pums_earnings_universe_zeros(
        frame,
        person_scope=mask,
        boundary="current survey financial predictor preparation",
    )
    return applied.frame, applied.receipt


@dataclass(frozen=True)
class QualifiedSurveyPredictors:
    """Computed values; callers requalify live owners at materialization/replay."""

    projection: bytes
    matrix: bytes
    source_frame: object
    donor_frame: object
    donor_columns: pd.DataFrame
    native_money: pd.DataFrame
    origins: pd.DataFrame
    evidence: dict


def qualify_current_survey_predictors(
    preparation, allocated_population, clone_population
):
    """Read the actual full-parent money owner once, then seal all retained state.

    ASEC donors retain original household design weights, before allocation or
    cloning. No legacy raw nominal dollar column can stand in for current money.
    The source periods are distinct: ASEC 2025 interview/2024 annual income,
    restated to 2024 price basis; ACS 2024 rolling prior-12-month amounts adjusted
    by ADJINC. This model uses that explicitly declared temporal harmonization;
    it does not claim the observation windows are equivalent.
    """
    require(
        type(preparation) is source.AuthenticatedSurveyPopulationPreparation,
        "PREPARATION_TYPE",
    )
    entry = preparation._checked()
    state = entry[2]
    view = source.CheckedSurveyPopulationView(
        entry[1], state.context, state.frame, state.plan, json.loads(entry[1])
    )
    _, allocation = host.survey_budget._initial(
        view, allocated_population, clone_population
    )
    seals = tuple(
        host.survey_budget._population_identity(p)
        for p in (allocated_population, clone_population)
    )
    native_entry = source.asec_native._ISSUED.get(id(state.native[1]))
    require(
        native_entry is not None
        and native_entry[0]() is state.native[1]
        and state.native[1].payload == native_entry[1],
        "NATIVE_ISSUANCE",
    )
    parent = native_entry[2].parent
    ready = parent.ready()
    header = json.loads(ready.header)
    require(
        header["target_year"] == 2024 and header["semantic"] == "annual_current_money",
        "CURRENT_MONEY_PERIOD",
    )
    corrected, universe_receipt = _acs_earnings(state.frame)
    people = corrected.person
    pids = _ids(people.person_id)
    channels = people[provenance.support_channel_column("person")].astype(str)
    require(set(channels) == {"asec", "acs"}, "SOURCE_CHANNELS")
    asec = channels.eq("asec").to_numpy()
    acs = ~asec
    native_ids = people[provenance.spine_source_id_column("person")].to_numpy(
        dtype=np.int64
    )
    require(
        set(native_ids[asec]) == set(state.source_frames[1].person.person_id),
        "SELECTED_ASEC_ROSTER",
    )
    scope = parent.scope
    positions = {pid: i for i, pid in enumerate(scope.person_ids)}
    require(len(positions) == len(scope.person_ids), "PARENT_ROSTER")
    require(all(int(pid) in positions for pid in native_ids[asec]), "PARENT_MEMBER")
    take = np.array([positions[int(pid)] for pid in native_ids[asec]], dtype=np.int64)
    require(all(scope.person_years[int(i)] == 2024 for i in take), "CURRENT_COHORT")
    index = pd.Index(pids, name="person_id")
    money = pd.DataFrame(np.nan, index=index, columns=MONEY_FIELDS, dtype=np.float64)
    field_evidence = {}
    for name in MONEY_FIELDS:
        field = ready.field(name)
        domain = next(d for d in parent.spec.fields if d.name == name)
        require(domain.entity == "person", "MONEY_ENTITY")
        amounts = field.amounts[take]
        valid = field.validity[take]
        require(
            (valid == 1).all() and np.isfinite(amounts).all(), "CURRENT_MONEY_UNKNOWN"
        )
        money.loc[pids[asec], name] = amounts
        field_evidence[name] = {
            "domain": {f.name: getattr(domain, f.name) for f in fields(domain)},
            "amount_sha256": codec.sha(amounts.astype("<f8").tobytes()),
            "status_hex": field.statuses[take].tobytes().hex(),
            "validity_hex": valid.tobytes().hex(),
            "zero_origin_hex": field.zero_origin[take].tobytes().hex(),
        }
    for name, column in zip(MONEY_FIELDS[:2], OUTPUTS[:2], strict=True):
        money.loc[pids[acs], name] = _numeric(people.loc[acs, column])
    # Source financial leaves must not be overwritten by this first completion.
    for column in OUTPUTS[2:]:
        require(
            column not in people or people.loc[acs, column].isna().all(),
            "ACS_FINANCIAL_LEAF_ALREADY_PRESENT",
        )
    age = _numeric(people.age)
    features = pd.DataFrame(
        {
            FEATURES[0]: age,
            FEATURES[1]: money.WSAL_VAL.to_numpy(),
            FEATURES[2]: money.SEMP_VAL.to_numpy(),
        },
        index=index,
        dtype=np.float64,
    )
    require(np.isfinite(features.to_numpy()).all(), "FEATURE_UNKNOWN")
    donor_columns = features.loc[pids[asec]].copy()
    for target, raw in zip(TARGETS, MONEY_FIELDS[2:], strict=True):
        donor_columns[target] = money.loc[pids[asec], raw].to_numpy()
    donor_frame = state.frame.select(asec)
    require(
        donor_frame.resolve_weights("person").kind is WeightKind.DESIGN,
        "DONOR_DESIGN_WEIGHT_KIND",
    )
    require(
        np.array_equal(donor_frame.person.person_id.to_numpy(), pids[asec]),
        "DONOR_ROW_ORDER",
    )
    origins = pd.DataFrame(
        {
            "person_id": pids,
            "native_person_id": native_ids,
            "source": channels.to_numpy(),
        },
        index=index,
    )
    native_receipt = json.loads(native_entry[1])
    require(
        native_receipt["income_year"] == 2024 and native_receipt["survey_year"] == 2025,
        "ASEC_PERIOD_RECEIPT",
    )
    evidence = {
        "protocol": PROTOCOL,
        "preparation_sha256": codec.sha(entry[1]),
        "allocation_sha256": codec.sha(allocation),
        "clone_sha256": source._frame_identity(clone_population.frame),
        "asec_native_sha256": codec.sha(native_entry[1]),
        "money_header": header,
        "money_header_sha256": codec.sha(ready.header),
        "money_fields": field_evidence,
        "asec_interview_year": native_receipt["survey_year"],
        "asec_income_window": "calendar_year_2024",
        "price_basis_year": 2024,
        "acs_income_window": "rolling_prior_12_months_at_2024_interview",
        "acs_price_adjustment": "source_amount*(ADJINC/1000000)",
        "observation_window_equivalence_claim": False,
        "asec_knownness": "full_parent_ready_then_selected_validity_equals_1",
        "acs_financial_origin": "QRF_modeled_from_current_ASEC_totals_then_maintained_splits",
        "donor_weight_kind": "design",
        "donor_weight_sha256": codec.sha(
            donor_frame.resolve_weights("person").values.astype("<f8").tobytes()
        ),
        # Snapshot the actual owner's read-only outer receipt at this JSON boundary.
        "earnings_universe": dict(universe_receipt),
        "split_contract": leaves.cps_carried_current_leaf_contract(),
        "model_judgments": {
            "conditioning": list(FEATURES),
            "omitted_sex_and_state": "current_ASEC_raw_source_projection_unbound; required_followup_before_launch",
            "quality_acceptance": "held_out_fit_quality_not_yet_assessed",
            "income_period_harmonization": "2024_price_basis_with_explicitly_different_interview_windows",
            "financial_chain": list(TARGETS),
            "prior_target_conditioning": "all_previous_drawn_totals",
        },
        "source_admission_issued": False,
        "release_eligible": False,
    }
    matrix = model_input.encode_recipient_matrix(
        features.loc[pids[acs]], entity="person", entity_ids=pids[acs].astype("<i8")
    )
    projection = host.survey_graph._bounded_json(
        {
            **evidence,
            "origins": origins.loc[
                :, ["person_id", "native_person_id", "source"]
            ].values.tolist(),
            "features_sha256": codec.sha(features.to_numpy(dtype="<f8").tobytes()),
            "native_money_sha256": codec.sha(money.to_numpy(dtype="<f8").tobytes()),
            "recipient_matrix_sha256": codec.sha(matrix),
        },
        source.MAX_PAYLOAD_BYTES,
    )
    source._pure_final(state)
    require(
        source.asec_native._ISSUED.get(id(state.native[1])) is native_entry
        and native_entry[2].parent is parent
        and state.native[1].payload == native_entry[1],
        "FINAL_NATIVE_ISSUANCE",
    )
    require(
        seals
        == tuple(
            host.survey_budget._population_identity(p)
            for p in (allocated_population, clone_population)
        ),
        "FINAL_POPULATION",
    )
    host.survey_budget._preparation_entry(preparation, entry[1], entry)
    return QualifiedSurveyPredictors(
        projection,
        matrix,
        state.frame,
        donor_frame,
        donor_columns,
        money,
        origins,
        evidence,
    )


def complete_predictor_columns(qualified, clone_frame, drawn_money):
    """Join native values/draws to both arms by source origin, never position."""
    require(type(qualified) is QualifiedSurveyPredictors, "QUALIFIED_VALUES_TYPE")
    matrix = model_input.decode_recipient_matrix(qualified.matrix)
    require(
        type(drawn_money) is pd.DataFrame
        and drawn_money.index.equals(matrix.features.index)
        and tuple(drawn_money.columns) == TARGETS,
        "DRAW_AXIS",
    )
    values = qualified.native_money.copy(deep=True)
    for target, raw in zip(TARGETS, MONEY_FIELDS[2:], strict=True):
        values.loc[drawn_money.index, raw] = _numeric(drawn_money[target])
    completed = leaves.derive_cps_current_predictor_leaves(
        {name: _numeric(values[name]) for name in MONEY_FIELDS}
    )
    native = pd.DataFrame(completed, index=values.index)
    person = clone_frame.person
    stack_ids = person[provenance.support_source_id_column("person")].to_numpy(
        dtype=np.int64
    )
    lookup = qualified.origins.reindex(stack_ids)
    require(not lookup.isna().any().any(), "CLONE_ORIGIN_COVERAGE")
    require(
        np.array_equal(
            lookup.native_person_id.to_numpy(),
            person[provenance.spine_source_id_column("person")].to_numpy(),
        )
        and np.array_equal(
            lookup.source.to_numpy(),
            person[provenance.support_channel_column("person")].astype(str).to_numpy(),
        ),
        "CLONE_ORIGIN_IDENTITY",
    )
    clones = person[provenance.support_clone_index_column("person")].to_numpy()
    require(np.isin(clones, (0, 1)).all(), "CLONE_ROLE_DOMAIN")
    pairs = pd.DataFrame({"source_id": stack_ids, "clone": clones})
    counts = pairs.groupby("source_id", sort=False).size()
    require(
        counts.eq(2).all()
        and len(counts) == len(values)
        and not pairs.duplicated().any(),
        "WHOLE_NATIVE_CLONE_PAIR",
    )
    aligned = native.reindex(stack_ids)
    index = pd.Index(_ids(person.person_id), name="person_id")
    return {
        ("person", name): pd.Series(
            aligned[name].to_numpy(copy=True), index=index, dtype=np.float64
        )
        for name in OUTPUTS
    }
