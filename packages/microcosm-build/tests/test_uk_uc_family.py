"""UC calibration family categories respect retained FRS relationships."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from microcosm.build.uk_runtime.measure_simulation import compute_uk_measure_input


def _fixture():
    # Single parent + 18-year-old QYP; unmarried parents + child;
    # childless couple including an 18-year-old partner; single claimant;
    # parent + reported 19-year-old who is not eligible for the child element.
    people = pd.DataFrame(
        {
            "person_id": np.arange(10),
            "person_benunit_id": [10, 10, 20, 20, 20, 30, 30, 40, 50, 50],
            "age": [49, 18, 35, 36, 8, 19, 18, 18, 45, 19],
            "is_benunit_head": [1, 0, 1, 0, 0, 1, 0, 1, 1, 0],
            "is_parent": [1, 0, 1, 1, 0, 0, 0, 0, 1, 0],
        }
    )
    benunits = pd.DataFrame(
        {
            "benunit_id": [50, 30, 10, 40, 20],  # deliberately different order
            "dependent_children": [1, 0, 1, 0, 1],
            "is_married": [False] * 5,  # cohabiting couples must remain couples
        }
    )
    frame = SimpleNamespace(
        table=lambda entity: {"person": people, "benunit": benunits}[entity]
    )
    child_variable = "is_child_or_qualifying_young_person_for_universal_credit"
    sim = SimpleNamespace(
        tax_benefit_system=SimpleNamespace(variables={}),
        calculate=lambda variable, year: (
            np.array([False, True, False, False, True, True, True, True, False, False])
            if variable == child_variable
            else None
        ),
    )
    return frame, sim


def test_uc_family_type_uses_relationships_and_recognises_older_children():
    frame, sim = _fixture()
    values, route = compute_uk_measure_input(
        frame, sim, "benunit", "uc_calibration_family_type", 2025
    )
    assert values.tolist() == [
        "LONE_PARENT",
        "COUPLE_NO_CHILDREN",
        "LONE_PARENT",
        "SINGLE",
        "COUPLE_WITH_CHILDREN",
    ]
    assert route == "frs_relationships_and_uc_child_status"


def test_uc_child_count_excludes_young_claimants_and_includes_reported_children():
    frame, sim = _fixture()
    values, _ = compute_uk_measure_input(
        frame, sim, "benunit", "uc_calibration_child_count", 2025
    )
    assert values.tolist() == [1, 0, 1, 0, 1]


def test_uc_family_measure_refuses_missing_source_relationships():
    frame, sim = _fixture()
    frame.table("person").drop(columns="is_parent", inplace=True)
    with pytest.raises(KeyError, match="is_parent"):
        compute_uk_measure_input(
            frame, sim, "benunit", "uc_calibration_family_type", 2025
        )


def test_uc_family_measure_refuses_ambiguous_claimant_count():
    frame, sim = _fixture()
    frame.table("person").loc[4, "is_parent"] = 1
    with pytest.raises(ValueError, match="one or two.*claimants"):
        compute_uk_measure_input(
            frame, sim, "benunit", "uc_calibration_family_type", 2025
        )
