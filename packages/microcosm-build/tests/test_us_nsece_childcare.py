"""Synthetic source-code and Frame/export contracts; no NSECE microdata in CI."""

import json

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from microcosm.build.frame_checkpoint import (
    load_frame_checkpoint,
    write_frame_checkpoint,
)
from microcosm.build.us_runtime.childcare_attendance import (
    US_CHILDCARE_ATTENDANCE_COLUMNS,
)
from microcosm.build.us_runtime.nsece_childcare import (
    NSECE_CALENDAR_BLOCKS,
    NSECE_CHILD_INDICES,
    NSECE_PROVIDER_INDICES,
    assert_childcare_attendance_exportable,
    derive_nsece_childcare,
    load_nsece_childcare,
    nsece_childcare_calendar_columns,
    nsece_childcare_household_columns,
    nsece_childcare_validation_report,
    with_us_nsece_childcare_attendance,
)
from microcosm.frame import US_SCHEMA, Frame, WeightKind, Weights

MONTH, DAYS, HOURS = US_CHILDCARE_ATTENDANCE_COLUMNS


def _raw(n=1):
    household = pd.DataFrame(
        -9.0, index=range(n), columns=nsece_childcare_household_columns()
    )
    calendar = pd.DataFrame(
        -9.0, index=range(n), columns=nsece_childcare_calendar_columns()
    )
    for table in (household, calendar):
        table["HH4_METH_CASEID"] = np.arange(1, n + 1)
    household["HH4_METH_QUEXVERSION"] = 1
    household["HH4_REGION"] = 1
    household["HH4_PARWORK_STATUS"] = 2
    household["HH4_ECON_INCOME_ANNUAL"] = 40_000
    for child in NSECE_CHILD_INDICES:
        household[f"HHC4_METH_WEIGHT_{child}"] = np.nan
        household[f"HH4_MISSING_STATUS_CC_{child}"] = 0
    household["HHC4_AGE_AT_USAGE_1"] = 36
    household["HHC4_METH_WEIGHT_1"] = 100.0
    household["HH4_MISSING_STATUS_CC_1"] = 2
    for provider in NSECE_PROVIDER_INDICES:
        household[f"HH4_TYPEOFCARE_AGG_1_{provider}"] = -8
    household["HH4_TYPEOFCARE_AGG_1_1"] = 4
    for block in range(1, NSECE_CALENDAR_BLOCKS + 1):
        calendar[f"HH4_CHCAL_R_1_{block}"] = 0
    return household, calendar


def _care(calendar, *, row=0, day=0, hours=4, provider=1):
    start = day * 96 + 9 * 4 + 1
    columns = [f"HH4_CHCAL_R_1_{b}" for b in range(start, start + hours * 4)]
    calendar.loc[row, columns] = provider


def test_calendar_union_excludes_school_and_handles_multiple_providers():
    hh, cal = _raw()
    hh["HH4_TYPEOFCARE_AGG_1_2"] = 6  # K-8 school is not ECE attendance.
    hh["HH4_TYPEOFCARE_AGG_1_3"] = 3  # Unpaid care is still ECE.
    _care(cal, day=0, hours=4)
    _care(cal, day=1, hours=2, provider=3)
    _care(cal, day=2, hours=6, provider=2)
    before = (hh.copy(deep=True), cal.copy(deep=True))
    source = derive_nsece_childcare(hh, cal)
    child = source.children.iloc[0]
    assert child[DAYS] == 2
    assert child[HOURS] == 3
    assert child[MONTH] == 9
    assert child.ece_hours_per_week == 6
    assert child.ece_provider_count == 2
    assert source.weights.values.tolist() == [100]
    assert_frame_equal(hh, before[0])
    assert_frame_equal(cal, before[1])


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (0, 0, "missing_calendar"),
        (1, 0, "partial_calendar"),
        (2, -1, "ambiguous_calendar"),
        (2, 97, "ambiguous_calendar"),
        (2, 77, "ambiguous_calendar"),
    ],
)
def test_missing_or_ambiguous_calendar_never_becomes_observed_zero(
    status, code, expected
):
    hh, cal = _raw()
    hh["HH4_MISSING_STATUS_CC_1"] = status
    cal.loc[0, "HH4_CHCAL_R_1_1"] = code
    source = derive_nsece_childcare(hh, cal)
    assert source.children.attendance_status.tolist() == [expected]
    assert source.children[list(US_CHILDCARE_ATTENDANCE_COLUMNS)].isna().all().all()


def test_complete_parental_care_is_a_weighted_zero_donor():
    hh, cal = _raw()
    source = derive_nsece_childcare(hh, cal)
    donors, weights = source.donors()
    assert donors[list(US_CHILDCARE_ATTENDANCE_COLUMNS)].to_numpy().tolist() == [
        [0, 0, 0]
    ]
    assert weights.total == 100


def test_unknown_provider_type_is_not_a_zero_schedule():
    hh, cal = _raw()
    _care(cal)
    hh["HH4_TYPEOFCARE_AGG_1_1"] = 8
    source = derive_nsece_childcare(hh, cal)
    assert source.children.attendance_status.tolist() == ["ambiguous_calendar"]


def test_age_in_months_and_calendar_join_are_not_row_order_dependent():
    hh, cal = _raw(2)
    hh.loc[1, "HHC4_AGE_AT_USAGE_1"] = 156
    _care(cal)
    source = derive_nsece_childcare(hh, cal.iloc[::-1])
    assert source.children.age.tolist() == [3, 13]
    assert source.children.attendance_status.tolist() == [
        "complete",
        "age_out_of_scope",
    ]
    assert source.children.loc[0, DAYS] == 1


def test_mismatched_or_duplicate_household_ids_raise():
    hh, cal = _raw(2)
    cal.loc[0, "HH4_METH_CASEID"] = 3
    with pytest.raises(ValueError, match="ID sets"):
        derive_nsece_childcare(hh, cal)
    cal.loc[0, "HH4_METH_CASEID"] = 2
    with pytest.raises(ValueError, match="unique"):
        derive_nsece_childcare(hh, cal)


def test_loader_refuses_unpinned_source(tmp_path):
    path = tmp_path / "source.tsv"
    path.write_text("wrong file\n")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_nsece_childcare(path, path)


def _frame(*, parent_observed=True):
    person = pd.DataFrame(
        {"person_id": [1, 2], "person_source_id": ["adult", "child"], "age": [30, 3]}
    )
    tables = {}
    for entity in US_SCHEMA.group_entities:
        person[f"person_{entity}_id"] = 1
        tables[entity] = pd.DataFrame({f"{entity}_id": [1]})
    if parent_observed:
        for column in US_CHILDCARE_ATTENDANCE_COLUMNS:
            person[column] = [0.0, np.nan]
    tables["person"] = person
    return Frame(
        tables,
        US_SCHEMA,
        {"household": Weights(np.array([100.0]), WeightKind.DESIGN)},
        metadata={"existing_receipt": "preserved"},
    )


def _source():
    hh, cal = _raw()
    for day in range(5):
        _care(cal, day=day, hours=8)
    return derive_nsece_childcare(hh, cal)


def test_candidate_frame_preserves_structure_weights_and_checkpoint_receipts(tmp_path):
    frame = _frame()
    before = frame.table("person").copy(deep=True)
    candidate = with_us_nsece_childcare_attendance(
        frame, _source(), seed=915, match_columns=("age",)
    )
    assert_frame_equal(frame.table("person"), before)
    assert candidate.table("person")[DAYS].tolist() == [0, 5]
    assert candidate.metadata["existing_receipt"] == "preserved"
    assert candidate.metadata["nsece_childcare_attendance"]["candidate_only"] is True
    np.testing.assert_array_equal(
        candidate.weights_for("household").values, frame.weights_for("household").values
    )
    for entity in US_SCHEMA.group_entities:
        assert_frame_equal(candidate.table(entity), frame.table(entity))
    path = tmp_path / "candidate.h5"
    receipts = json.loads(json.dumps(candidate.metadata, default=dict))
    write_frame_checkpoint(path, candidate, metadata={"frame_metadata": receipts})
    stored = load_frame_checkpoint(path)
    reloaded = load_frame_checkpoint(
        path, frame_metadata=stored.metadata["frame_metadata"]
    ).frame
    # Checkpoint JSON sorts mapping keys; receipts retain the same content.
    assert json.loads(json.dumps(reloaded.metadata, default=dict)) == receipts
    assert_frame_equal(reloaded.table("person"), candidate.table("person"))


def test_candidate_export_refuses_unresolved_out_of_scope_inputs():
    candidate = with_us_nsece_childcare_attendance(
        _frame(parent_observed=False), _source(), seed=915, match_columns=("age",)
    )
    assert pd.isna(candidate.table("person").loc[0, DAYS])
    with pytest.raises(ValueError, match="unresolved"):
        assert_childcare_attendance_exportable(candidate)


@pytest.mark.requires_us
def test_real_engine_export_reload_preserves_child_attendance(tmp_path):
    from policyengine_us import Microsimulation
    from policyengine_us.data import USSingleYearDataset

    from microcosm.frame.adapters.policyengine_us import PolicyEngineUSEngine

    candidate = with_us_nsece_childcare_attendance(
        _frame(), _source(), seed=915, match_columns=("age",)
    )
    assert_childcare_attendance_exportable(candidate)
    # Project canonical engine inputs; keep source provenance in the checkpoint.
    tables = {e: candidate.table(e).copy() for e in candidate.entities}
    tables["person"] = tables["person"].drop(
        columns=[
            "person_source_id",
            *(f"{c}_source" for c in US_CHILDCARE_ATTENDANCE_COLUMNS),
        ]
    )
    projected = Frame(
        tables,
        candidate.schema,
        {"household": candidate.weights_for("household")},
        candidate.strata,
        mass_log=candidate.mass_log,
        metadata=candidate.metadata,
    )
    path = tmp_path / "engine.h5"
    PolicyEngineUSEngine().write_dataset(projected, path, period=2026)
    dataset = USSingleYearDataset(file_path=str(path))
    assert dataset.person[MONTH].tolist() == [0, 22]
    assert dataset.person[HOURS].tolist() == [0, 8]
    sim = Microsimulation(dataset=dataset)
    assert sim.calculate("childcare_hours_per_week", 2026).tolist() == [0, 40]


def test_validation_holds_out_whole_households_and_reports_exclusions(monkeypatch):
    import microcosm.build.us_runtime.nsece_childcare as module

    hh, cal = _raw(30)
    hh.loc[29, "HH4_MISSING_STATUS_CC_1"] = 0
    for row in range(29):
        _care(cal, row=row)
    source = derive_nsece_childcare(hh, cal)
    original = module.impute_us_childcare_attendance

    def checked(recipient, donor, **kwargs):
        assert set(recipient.source_household_id).isdisjoint(donor.source_household_id)
        return original(recipient, donor, **kwargs)

    monkeypatch.setattr(module, "impute_us_childcare_attendance", checked)
    report = nsece_childcare_validation_report(source)
    assert report["household_overlap"] == 0
    assert report["production_ready"] is False
    assert report["under13_complete_weight_share"] == pytest.approx(29 / 30)
    assert report["comparisons"][0]["observed"] == report["comparisons"][0]["predicted"]
