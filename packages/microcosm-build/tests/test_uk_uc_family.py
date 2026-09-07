"""UC calibration family categories respect retained FRS relationships."""

import json
from importlib import resources
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from microcosm.build.country_spec import load_country_spec
from microcosm.build.uk_runtime.ledger_targets import (
    UKFrameTargetAdapter,
    materialize_uk_ledger_targets,
)
from microcosm.build.uk_runtime.measure_simulation import compute_uk_measure_input
from microcosm.calibrate import TargetRegistry, TargetSpec
from microcosm.calibrate.matrix import build_constraint_matrix
from microcosm.frame import EntitySchema, Frame, WeightKind, Weights


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


def test_full_uc_payment_registry_matches_independent_relationship_and_band_cases():
    """All active rows count benefit units, retaining edges of excluded bands."""
    # Expected labels are stated by scenario, never calculated by the resolver.
    # Each member is (age, head, parent, native UC child/QYP status).
    scenarios = [
        ("SINGLE", 0, [(18, True, False, True)]),
        ("LONE_PARENT", 1, [(49, True, True, False), (18, False, False, True)]),
        ("LONE_PARENT", 1, [(45, True, True, False), (19, False, False, False)]),
        ("SINGLE", 1, [(45, True, True, False), (20, False, False, False)]),
        ("LONE_PARENT", 1, [(45, True, True, False), (20, False, False, True)]),
        ("COUPLE_NO_CHILDREN", 0, [(19, True, False, True), (18, False, False, True)]),
        (
            "COUPLE_WITH_CHILDREN",
            1,
            [
                (35, True, True, False),
                (36, False, True, False),
                (8, False, False, True),
            ],
        ),
    ]
    # Match the published decimal lower edges, independently of _band_bounds.
    # KNOWN source mismatch: the highest INCLUDED band is bounded in DWP's
    # labels (£2,400.01–£2,500/month); a separate £2,500.01+ category is absent
    # from this registry. Current interpretation opens the included band to
    # infinity. The £50,000 case pins that behavior, not source correctness.
    edges = [float(f"{100 * i}.01") * 12 for i in range(25)]
    awards = [-1.0, 0.0, 0.1, 50_000.0]
    for edge in edges:
        awards.extend([np.nextafter(edge, -np.inf), edge, np.nextafter(edge, np.inf)])
    people, benunits, expected_families, qualifying = [], [], [], []
    for family, dependent, members in scenarios:
        for award in awards:
            # Two identically eligible benefit units in a dwelling distinguish
            # summation from an any-member household indicator.
            household_id = len(benunits) // 2
            for _ in range(2):
                benunit_id = len(benunits)
                benunits.append(
                    {
                        "benunit_id": benunit_id,
                        "dependent_children": dependent,
                        "is_married": False,
                        "universal_credit": award,
                    }
                )
                expected_families.append(family)
                for age, head, parent, qyp in members:
                    people.append(
                        {
                            "person_id": len(people),
                            "person_benunit_id": benunit_id,
                            "person_household_id": household_id,
                            "age": age,
                            "is_benunit_head": head,
                            "is_parent": parent,
                        }
                    )
                    qualifying.append(qyp)
    # Reverse person-row order to expose positional aggregation assumptions;
    # Frame requires sorted group ids.
    bu = pd.DataFrame(benunits)
    hh = pd.DataFrame({"household_id": np.arange(len(benunits) // 2)})
    frame = Frame(
        {
            "person": pd.DataFrame(people).iloc[::-1].reset_index(drop=True),
            "benunit": bu,
            "household": hh,
        },
        EntitySchema(group_entities=("benunit", "household")),
        {"household": Weights(np.ones(len(hh)), WeightKind.DESIGN)},
    )
    sim = SimpleNamespace(calculate=lambda variable, year: np.asarray(qualifying[::-1]))
    family, _ = compute_uk_measure_input(
        frame, sim, "benunit", "uc_calibration_family_type", 2025
    )
    np.testing.assert_array_equal(family, expected_families)
    adapter = UKFrameTargetAdapter(frame)
    adapter.set_column("benunit", "uc_calibration_family_type", family)

    refs = [
        r
        for r in load_country_spec("uk").target_references
        if r.name.startswith("dwp/uc_payment_dist/")
    ]
    excluded = {
        row["name"]
        for row in json.loads(
            resources.files("microcosm.build.uk")
            .joinpath("calibration_measure_exclusions.json")
            .read_text()
        )["exclusions"]
    }
    specs = [
        TargetSpec(
            name=r.name,
            entity=r.entity,
            measure=r.measure,
            value=1.0,
            period=2025,
            source="synthetic",
            metadata={
                **dict(r.metadata),
                **{
                    f"ledger_filter_{key}": value
                    for key, value in r.ledger_selector["dimension_values"].items()
                },
            },
        )
        for r in refs
    ]
    full_registry = TargetRegistry(specs, country="uk")
    active = [spec for spec in specs if spec.name not in excluded]
    assert len(specs) == 100
    assert len(active) == 84
    assert len({s.name for s in specs} & excluded) == 16
    registry = TargetRegistry(active, country="uk")
    result = materialize_uk_ledger_targets(
        adapter, registry, period=2025, band_edge_registry=full_registry
    )
    assert not result.skipped
    problem = build_constraint_matrix(
        adapter.to_frame(), registry.to_target_set(), weight_entity="household"
    )
    assert not problem.skipped
    assert len(problem.names) == 84
    assert not {f"{name}@2025" for name in excluded}.intersection(problem.names)
    expected_family = np.asarray(expected_families)[bu.benunit_id.to_numpy()]
    uc = bu.universal_credit.to_numpy()
    # Synthetic ids encode the independent fixture's two-benefit-unit dwelling.
    bu_household = bu.benunit_id.to_numpy() // 2
    for spec, name, row in zip(
        active, problem.names, problem.matrix.toarray(), strict=True
    ):
        family_name, band_name = spec.name.split("/")[-1].split("_annual_payment_")
        band_index = int(band_name.split("_to_")[0].replace("_", "")) // 1200
        lower = edges[band_index]
        upper = edges[band_index + 1] if band_index < 24 else np.inf
        mask = (
            (expected_family == family_name) & (uc > 0) & (uc >= lower) & (uc < upper)
        )
        expected = np.array(
            [mask[bu_household == hid].sum() for hid in hh.household_id]
        )
        np.testing.assert_array_equal(row, expected, err_msg=name)
        assert row.max() == 2, name
