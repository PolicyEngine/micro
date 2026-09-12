"""Actual source readers over constructed, privately pinned invented bytes.

No native microdata, no country engine and no full PUF donor fixture: the
current ASEC income routing qualifier only needs the bounded survey preparation
fixture plus invented member literals.
"""

import ast
import hashlib
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_us_asec_coverage_authentication import _changed_parent
from test_us_survey_population_preparation import fixture

from microcosm.build.frame_checkpoint import load_frame_checkpoint
from microcosm.build.us_runtime import asec_coverage_authentication as coverage
from microcosm.build.us_runtime import asec_person_income_source as restoration
from microcosm.build.us_runtime import current_asec_income_routing_source as owner

# Invented current-year people. Ages 55/14 come from the shared fixture; the
# older adult exercises the printed age-58 distribution route.
CURRENT_PEOPLE = (105, 106, 107, 108)
AGES = {105: 55, 106: 14, 107: 70, 108: 14}
AMOUNTS = {
    #            PNSN   ANN   DSTV1 DSTV1Y DSTV2 DSTV2Y   RNT    FRSE    OI
    105: (12000.0, -1.0, 0.0, 7000.0, 0.0, 0.0, -400.0, 0.0, 3000.0),
    106: (0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    107: (9000.0, 0.0, 5000.0, 0.0, 0.0, 0.0, 500.0, -9000.0, 250.0),
    108: (0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 700.0),
}
AMOUNT_ORDER = (
    "PNSN_VAL",
    "ANN_VAL",
    "DST_VAL1",
    "DST_VAL1_YNG",
    "DST_VAL2",
    "DST_VAL2_YNG",
    "RNT_VAL",
    "FRSE_VAL",
    "OI_VAL",
)
LITERALS = {
    105: {
        "PEN_YN": "1",
        "ANN_YN": "0",
        "DST_YN": "0",
        "DST_YN_YNG": "1",
        "DST_SC1_YNG": "4",
        "RNT_YN": "1",
        "FRSE_YN": "1",
        "ERN_YN": "1",
        "OI_YN": "1",
        "OI_OFF": "20",
    },
    106: {},
    107: {
        "PEN_YN": "2",
        "ANN_YN": "1",
        "DST_YN": "1",
        "DST_SC1": "9",
        "RNT_YN": "0",
        "FRSE_YN": "1",
        "ERN_YN": "1",
        "OI_YN": "1",
        "OI_OFF": "0",
    },
    108: {"OI_YN": "0", "ERN_YN": "", "FRMOTR": ""},
}
DEFAULT_LITERAL = {
    **{name: "0" for name in owner.RECEIPT_ENTRIES},
    **{name: "0" for name in owner.ACCOUNT_ENTRIES},
    "OI_OFF": "0",
    **{name: "0" for name in owner.ALLOCATION_ENTRIES},
}


def _member_literals(person_id):
    return {**DEFAULT_LITERAL, **LITERALS.get(person_id, {})}


def routing_arguments(tmp_path, monkeypatch, *, reverse=True, ages=None):
    """Extend the invented member before any owner issues a preparation.

    Only fixture registry pins change. No source issuer, ready() or native
    loader is replaced, and the person-income attachment is rebuilt from the
    changed member bytes exactly as production would.
    """
    arguments = fixture(tmp_path, monkeypatch)
    asec = arguments["source_dir"] / "asec"
    parent_path, attachment = asec / "parent.h5", asec / "household-attachment.h5"
    person = load_frame_checkpoint(parent_path).frame.person
    ids = person.person_id.to_numpy()
    ages = AGES if ages is None else ages
    changes = {}
    for offset, field in enumerate(AMOUNT_ORDER):
        data = person[field].to_numpy(dtype="float64", copy=True)
        for person_id in CURRENT_PEOPLE:
            positions = np.flatnonzero(ids == person_id)
            assert len(positions) == 1
            data[positions[0]] = AMOUNTS[person_id][offset]
        changes[field] = data
    age_column = person.A_AGE.to_numpy(copy=True)
    for person_id in CURRENT_PEOPLE:
        age_column[np.flatnonzero(ids == person_id)[0]] = ages[person_id]
    changes["A_AGE"] = age_column
    _changed_parent(parent_path, attachment, monkeypatch, changes)
    updated = load_frame_checkpoint(parent_path).frame.person.set_index("PERIDNUM")
    paths, pins = {}, []
    for year, member, archive, *_ in coverage._MEMBER_PINS:
        path = asec / f"pppub{year - 1999}.csv"
        raw = pd.read_csv(path, dtype=str, keep_default_na=False)
        for field in (*AMOUNT_ORDER, "A_AGE"):
            raw[field] = [str(int(updated.loc[key, field])) for key in raw.PERIDNUM]
        keys = [int(key) for key in raw.PERIDNUM]
        current = dict(zip(keys, updated.loc[raw.PERIDNUM].person_id, strict=True))
        for name in DEFAULT_LITERAL:
            raw[name] = [_member_literals(int(current[key]))[name] for key in keys]
        assert raw.notna().all().all()
        ordered = raw.iloc[::-1] if reverse else raw
        ordered.to_csv(path, index=False)
        data = path.read_bytes()
        pins.append(
            (
                year,
                member,
                archive,
                hashlib.sha256(data).hexdigest(),
                len(raw),
                len(data),
            )
        )
        paths[year] = path
    for module in (coverage, restoration):
        monkeypatch.setattr(module, "_MEMBER_PINS", tuple(pins))
    output = tmp_path / "routing-restored-money"
    restoration.restore_asec_person_income_source(
        parent_path, attachment, member_paths=paths, output_dir=output
    )
    shutil.copyfile(
        output / restoration.CHECKPOINT_FILENAME, asec / "person-income-attachment.h5"
    )
    return arguments


def _qualified(tmp_path, monkeypatch, **kwargs):
    arguments = routing_arguments(tmp_path, monkeypatch, **kwargs)
    prepared = owner.source.prepare_authenticated_survey_population(**arguments)
    return prepared, owner.qualify_current_asec_income_routing(prepared)


def test_actual_invented_member_joins_the_real_preparation_by_native_keys(
    tmp_path, monkeypatch
):
    prepared, qualified = _qualified(tmp_path, monkeypatch)
    person = qualified.person.set_index("native_person_id")
    assert set(person.index) == set(CURRENT_PEOPLE)
    # Borrowed money, native identity and member literal agree row by row.
    assert person.loc[105, "pension_annuity_pension_source_total"] == 12000.0
    assert person.loc[105, "pension_annuity_pension_reporting_status"] == (
        "known_receipt"
    )
    assert person.loc[105, "pension_annuity_pension_known_amount"] == 12000.0
    assert person.source_age.to_dict() == {k: float(v) for k, v in AGES.items()}
    literals = qualified.asec_literals.set_index("PERIDNUM")
    for person_id in CURRENT_PEOPLE:
        key = str(person_id - 100).zfill(22)
        assert int(literals.loc[key, "PNSN_VAL"]) == AMOUNTS[person_id][0]
        assert int(literals.loc[key, "A_AGE"]) == AGES[person_id]
    assert person.amount_validity_PNSN_VAL.eq(1).all()
    assert (
        hashlib.sha256(qualified.person.to_json(orient="table").encode()).hexdigest()
        == qualified.evidence["projection_sha256"]
    )
    assert not qualified.evidence["source_admission_issued"]
    assert not qualified.evidence["release_eligible"]
    prepared.checked_view()


def test_pension_and_annuity_totals_stay_separate_and_unsplit(tmp_path, monkeypatch):
    _, qualified = _qualified(tmp_path, monkeypatch)
    person = qualified.person.set_index("native_person_id")
    # PNSN_VAL is the printed combined total over all pension sources. Neither
    # a private share nor a taxable share is derived from it.
    assert person.loc[105, "pension_annuity_combined_total_scope"] == (
        owner.PENSION_TOTAL_SCOPE
    )
    assert not person.pension_annuity_private_share_applied.any()
    assert not person.pension_annuity_taxable_amount_known.any()
    assert not person.pension_annuity_pension_total_has_published_flag.any()
    # ANN_VAL's printed -1 is a NIU code, never a one dollar annuity loss.
    assert np.isnan(person.loc[105, "pension_annuity_annuity_source_total"])
    assert person.loc[105, "pension_annuity_annuity_amount_kind"] == "declared_niu"
    assert person.loc[105, "pension_annuity_annuity_reporting_status"] == "niu"
    # A yes answer with a zero gross amount is ambiguous, not a known zero.
    assert person.loc[107, "pension_annuity_annuity_reporting_status"] == (
        "ambiguous_recipient_zero"
    )
    assert np.isnan(person.loc[107, "pension_annuity_annuity_known_amount"])
    # A no answer against a positive total is a retained contradiction.
    assert person.loc[107, "pension_annuity_pension_reporting_status"] == (
        "contradictory_no_nonzero"
    )
    assert person.loc[107, "pension_annuity_pension_source_total"] == 9000.0
    assert np.isnan(person.loc[107, "pension_annuity_pension_known_amount"])


def test_distribution_routing_preserves_slots_ages_and_unresolved_accounts(
    tmp_path, monkeypatch
):
    _, qualified = _qualified(tmp_path, monkeypatch)
    person = qualified.person.set_index("native_person_id")
    assert person.loc[105, "retirement_distribution_route"] == "under_age58"
    assert person.loc[107, "retirement_distribution_route"] == "age58_and_over"
    # Regular IRA is account code 4; the slot amount is not a taxable amount.
    assert person.loc[105, "retirement_distribution_slot1_young_account_code"] == 4
    assert person.loc[105, "retirement_distribution_slot1_young_account_label"] == (
        "Regular IRA"
    )
    assert person.loc[105, "retirement_distribution_regular_ira_amount"] == 7000.0
    assert person.loc[105, "retirement_distribution_regular_ira_slots"] == 1
    assert person.loc[105, "retirement_distribution_source_total"] == 7000.0
    assert not person.retirement_distribution_taxable_amount_known.any()
    assert bool(person.loc[107, "retirement_distribution_route_has_published_flag"])
    assert not bool(person.loc[105, "retirement_distribution_route_has_published_flag"])
    # An account literal outside the printed range leaves the composition and
    # the regular IRA share unresolved rather than defaulting either way.
    assert person.loc[107, "retirement_distribution_slot1_account_literal"] == "9"
    assert person.loc[107, "retirement_distribution_slot1_account_literal_status"] == (
        "outside_printed_range"
    )
    assert person.loc[107, "retirement_distribution_slot1_slot_status"] == (
        "unresolved_slot_account"
    )
    assert pd.isna(person.loc[107, "retirement_distribution_slot1_account_code"])
    assert np.isnan(person.loc[107, "retirement_distribution_regular_ira_amount"])
    assert pd.isna(person.loc[107, "retirement_distribution_regular_ira_slots"])
    # The slot total is still the retained literal sum for the applicable route.
    assert person.loc[107, "retirement_distribution_source_total"] == 5000.0
    # The printed distribution universes name only the age 58 split, so
    # coverage below age 15 is a source question, not a resolved answer.
    assert pd.isna(person.loc[106, "retirement_distribution_source_reporting_universe"])
    assert person.loc[106, "retirement_distribution_reporting_status"] == (
        "unresolved_reporting_universe"
    )


def test_signed_property_and_farm_totals_keep_losses_and_net_zero_receipt(
    tmp_path, monkeypatch
):
    _, qualified = _qualified(tmp_path, monkeypatch)
    person = qualified.person.set_index("native_person_id")
    assert person.loc[105, "net_property_source_total"] == -400.0
    assert person.loc[105, "net_property_known_amount"] == -400.0
    assert person.loc[105, "net_property_reporting_status"] == "known_receipt"
    assert bool(person.loc[105, "net_property_is_net_loss"])
    # The receipt question is wider than the amount question, so the total is
    # not independently labelled rental and no component split is claimed.
    assert person.loc[105, "net_property_receipt_scope"] == (
        owner.NET_PROPERTY_RECEIPT_SCOPE
    )
    assert person.loc[105, "net_property_amount_scope"] == (
        owner.NET_PROPERTY_AMOUNT_SCOPE
    )
    assert not person.net_property_component_split_known.any()
    # A NIU receipt literal against a positive amount stays a contradiction.
    assert person.loc[107, "net_property_reporting_status"] == (
        "contradictory_niu_nonzero"
    )
    assert person.loc[107, "net_property_source_total"] == 500.0
    assert np.isnan(person.loc[107, "net_property_known_amount"])
    # Farm receipt with a net zero is distinct from absence, NIU and unknown.
    assert person.loc[105, "farm_reporting_status"] == "receipt_with_net_zero"
    assert person.loc[105, "farm_known_amount"] == 0.0
    assert person.loc[107, "farm_source_total"] == -9000.0
    assert person.loc[107, "farm_reporting_status"] == "known_receipt"
    assert bool(person.loc[107, "farm_is_net_loss"])
    assert not person.farm_is_nonfarm_self_employment.any()
    # The farm universe comes from ERN_YN/FRMOTR evidence, never from age.
    assert bool(person.loc[105, "farm_source_reporting_universe"])
    assert pd.isna(person.loc[108, "farm_source_reporting_universe"])
    assert person.loc[108, "farm_reporting_status"] == "unresolved_reporting_universe"


def test_other_income_keeps_reported_alimony_apart_from_residual_rules(
    tmp_path, monkeypatch
):
    _, qualified = _qualified(tmp_path, monkeypatch)
    person = qualified.person.set_index("native_person_id")
    assert person.loc[105, "other_income_category_code"] == 20
    assert person.loc[105, "other_income_category_label"] == "alimony"
    assert person.loc[105, "other_income_routing_status"] == "reported_category"
    assert bool(person.loc[105, "other_income_is_reported_alimony"])
    assert person.loc[105, "other_income_source_total"] == 3000.0
    # A receipt without a category is retained as an unresolved pattern; no
    # residual rule assigns it to alimony or to miscellaneous income.
    assert person.loc[107, "other_income_routing_status"] == "receipt_without_category"
    assert not bool(person.loc[107, "other_income_is_reported_alimony"])
    assert not person.other_income_residual_rule_applied.any()
    # A NIU receipt with a positive amount is a contradiction, not a nonfiler.
    assert person.loc[108, "other_income_reporting_status"] == (
        "contradictory_outside_reporting_universe"
    )
    assert person.loc[108, "other_income_source_total"] == 700.0
    assert np.isnan(person.loc[108, "other_income_known_amount"])
