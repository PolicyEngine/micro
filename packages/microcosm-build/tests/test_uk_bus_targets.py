from __future__ import annotations

import json
from importlib import resources as importlib_resources
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "uk_bus05i_fy2025.json"
BUS_PREFIX = "dft.bus_"


def _resource(name: str) -> dict:
    return json.loads(
        importlib_resources.files("microcosm.build.uk").joinpath(name).read_text()
    )


def test_bus05i_fy2025_subareas_reconcile_to_england() -> None:
    fixture = json.loads(FIXTURE.read_text())
    rows = fixture["rows"]

    assert len(rows) == 6
    assert {row["period"]["type"] for row in rows} == {"fiscal_year"}
    assert {row["period"]["value"] for row in rows} == {2025}
    assert {row["unit"] for row in rows} == {"gbp"}

    for concept in {
        "dft.local_bus_passenger_fare_receipts",
        "dft.local_bus_total_estimated_net_support",
    }:
        values = {
            row["groupby_value_id"]: row["value"]
            for row in rows
            if row["source_concept"] == concept
        }
        assert values["london"] + values["england_outside_london"] == pytest.approx(
            values["england"], abs=1_000
        )


def test_bus_targets_are_active_or_signed_excluded_as_declared() -> None:
    contract = _resource("uk_population_targets.json")
    references = {
        row["name"]: row
        for row in _resource("target_references.json")["target_references"]
    }
    membership = _resource("target_reference_membership.json")
    exclusions = {
        row["target_id"]: row
        for row in _resource("target_reference_signed_exclusions.json")["exclusions"]
    }
    bus = {
        row["target_id"]: row
        for row in contract["targets"]
        if row["target_id"].startswith(BUS_PREFIX)
    }

    active = {
        "dft.bus_fare_receipts.england",
        "dft.bus_net_support.england",
        "dft.bus_fare_receipts.london",
        "dft.bus_net_support.london",
    }
    excluded = set(bus) - active
    assert len(bus) == 8
    assert active <= set(references)
    assert excluded.isdisjoint(references)
    assert set(exclusions) >= excluded
    assert {exclusions[target_id]["reason_id"] for target_id in excluded} == {
        "derived_partition_member",
        "no_publisher_uk_total",
    }
    assert all(
        membership["targets"][target_id]["status"] == "signed_excluded"
        for target_id in excluded
    )
    # The London rows pin the publisher's region-stamped fact, not a country
    # row, and the England rows keep the country pin.
    for target_id in ("dft.bus_fare_receipts.london", "dft.bus_net_support.london"):
        selector = references[target_id]["ledger_selector"]
        assert selector["geography_level"] == "region"
        assert selector["geography_id"] == "E12000007"
        assert membership["targets"][target_id]["status"] == "active"
    for target_id in ("dft.bus_fare_receipts.england", "dft.bus_net_support.england"):
        selector = references[target_id]["ledger_selector"]
        assert selector["geography_level"] == "country"
        assert selector["geography_id"] == "E92000001"


def test_london_bus_rows_resolve_the_publisher_partition() -> None:
    fixture = json.loads(FIXTURE.read_text())
    published = {
        (row["source_concept"], row["groupby_value_id"]): row["value"]
        for row in fixture["rows"]
    }
    membership = _resource("target_reference_membership.json")["targets"]
    for target_id, concept in (
        ("dft.bus_fare_receipts.london", "dft.local_bus_passenger_fare_receipts"),
        ("dft.bus_net_support.london", "dft.local_bus_total_estimated_net_support"),
    ):
        resolved = membership[target_id]["candidates"][0]["resolved_value"]
        assert resolved == pytest.approx(published[(concept, "london")], abs=1.0)


def test_bus_selectors_do_not_consume_nts_or_bus0415() -> None:
    targets = [
        row
        for row in _resource("uk_population_targets.json")["targets"]
        if row["target_id"].startswith(BUS_PREFIX)
    ]
    selected_concepts = {
        row["ledger_selector"].get("source_concept", "") for row in targets
    }

    assert selected_concepts == {
        "dft.local_bus_passenger_fare_receipts",
        "dft.local_bus_total_estimated_net_support",
    }
    england_notes = " ".join(
        row["bindings"]["policyengine"]["notes"]
        for row in targets
        if row["target_id"].endswith("england")
    )
    assert "NTS0705a" in england_notes
    assert "BUS0415" in england_notes
    assert "#890" in england_notes
    assert "#790" not in england_notes


def test_generator_pins_region_only_targets_at_region_level() -> None:
    from tools.generate_uk_target_references import _geography_pins

    pins = _geography_pins(_resource("uk_population_targets.json"))
    assert pins["dft.bus_fare_receipts.london"] == {
        "geography_level": "region",
        "geography_id": "E12000007",
    }
    assert pins["dft.bus_fare_receipts.england"] == {
        "geography_level": "country",
        "geography_id": "E92000001",
    }
    assert pins["dft.bus_fare_receipts.england_outside_london"]["geography_level"] == (
        "country"
    )


def test_compiler_refuses_region_pins_outside_the_english_region_roster() -> None:
    from microcosm.build.ledger_targets import LedgerTargetReference
    from microcosm.build.uk_runtime.ledger_targets import (
        UK_NATIONAL_REGION_ROSTER,
        _assert_national_region_pin,
    )

    assert UK_NATIONAL_REGION_ROSTER == frozenset(
        f"E1200000{index}" for index in range(1, 10)
    )
    good = LedgerTargetReference(
        name="probe",
        ledger_selector={"geography_level": "region", "geography_id": "E12000007"},
        entity="household",
        measure="probe",
        family="dft_local_bus",
        period=2025,
    )
    _assert_national_region_pin(good)
    bad = LedgerTargetReference(
        name="probe",
        ledger_selector={"geography_level": "region", "geography_id": "W99999999"},
        entity="household",
        measure="probe",
        family="dft_local_bus",
        period=2025,
    )
    with pytest.raises(ValueError, match="not in the English region roster"):
        _assert_national_region_pin(bad)
