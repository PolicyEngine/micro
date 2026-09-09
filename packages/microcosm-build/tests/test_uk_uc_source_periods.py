"""UK UC source windows must not drift when monthly fact availability changes."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from microcosm.build.country_spec import load_country_spec
from microcosm.build.ledger_targets import LedgerTargetReference
from microcosm.build.uk_runtime.ledger_targets import compile_uk_target_registry
from microcosm.build.uk_runtime.uc_source_periods import (
    EXPECTED_SOURCE_MONTHS,
    uc_source_month_metadata,
)
from tools.generate_uk_target_references import _reference_metadata

MONTHS = [f"2025-{month:02}" for month in range(4, 13)]


def _reference() -> LedgerTargetReference:
    return LedgerTargetReference(
        name="dwp.uc.households",
        ledger_selector={"source_concept": "dwp.uc_benefit_units"},
        value_operation="calendar_year_average",
        entity="benunit",
        measure="uc_households",
        period=2025,
        family="dwp_universal_credit",
        metadata=uc_source_month_metadata(MONTHS),
    )


def _fact(month: str, *, suffix: str = "", value: float = 100.0) -> dict:
    return {
        "aggregate_fact_key": f"uc-{month}{suffix}",
        "aggregation": {"method": "sum"},
        "assertion": "observation",
        "geography": {"level": "country", "id": "K03000001"},
        "layout": {
            "groupby_dimension": "dwp.uc_deductions_month",
            "measure_id": "total_units",
            "record_set_id": f"dwp.uc_deductions.{month}.total_units",
        },
        "observed_measure": {
            "source_name": "dwp",
            "source_concept": "dwp.uc_benefit_units",
            "source_measure_id": "total_units",
            "unit": "count",
        },
        "period": {"type": "month", "value": month},
        "value": value,
    }


def _compile(monkeypatch, facts: list[dict], reference=None, *, period=2025):
    monkeypatch.setattr(
        "microcosm.build.uk_runtime.ledger_targets.load_country_spec",
        lambda country: SimpleNamespace(target_references=[reference or _reference()]),
    )
    return compile_uk_target_registry(facts, target_period=period)


def test_declared_window_preserves_mean_and_receipts_each_actual_month(monkeypatch):
    result = _compile(
        monkeypatch,
        [_fact(month, value=100.0 + index) for index, month in enumerate(MONTHS)],
    )
    assert not result.unsupported
    (target,) = result.registry.specs
    assert (target.value, target.entity, target.measure) == (
        104.0,
        "benunit",
        "uc_households",
    )
    assert json.loads(target.metadata[EXPECTED_SOURCE_MONTHS]) == MONTHS
    assert json.loads(target.metadata["uk_uc_resolved_source_months"]) == MONTHS
    assert target.metadata["uk_uc_source_month_count"] == "9"
    assert target.metadata["uk_uc_source_period_basis"] == "mean_of_declared_months"


@pytest.mark.parametrize(
    "observed",
    [
        MONTHS[1:],
        ["2025-01", *MONTHS],
        [f"2025-{month:02}" for month in range(1, 10)],
        [*MONTHS, "2025-09"],
    ],
    ids=["missing", "extra", "same-count-wrong-months", "duplicate-month"],
)
def test_changed_month_coverage_is_unsupported_without_replacement(
    monkeypatch, observed
):
    result = _compile(
        monkeypatch,
        [_fact(month, suffix=f"-{index}") for index, month in enumerate(observed)],
    )
    assert not result.registry.specs
    assert len(result.unsupported) == 1
    assert "expected exactly one fact" in result.unsupported[0]["reason"]
    assert "resolved" in result.unsupported[0]["reason"]


def test_restamping_model_year_does_not_silently_restamp_source_window(monkeypatch):
    result = _compile(
        monkeypatch,
        [_fact(month.replace("2025", "2026")) for month in MONTHS],
        period=2026,
    )
    assert not result.registry.specs
    assert "UK UC source-month coverage" in result.unsupported[0]["reason"]


def test_missing_member_identity_is_reported_instead_of_aborting_compilation(
    monkeypatch,
):
    facts = [_fact(month) for month in MONTHS]
    facts[0].pop("aggregate_fact_key")
    facts[0]["lineage"] = None
    result = _compile(monkeypatch, facts)
    assert not result.registry.specs
    assert "must identify exactly one fact" in result.unsupported[0]["reason"]


def test_single_declared_month_uses_the_resolved_representative_fact(monkeypatch):
    reference = replace(_reference(), metadata=uc_source_month_metadata(["2025-04"]))
    result = _compile(monkeypatch, [_fact("2025-04")], reference)
    (target,) = result.registry.specs
    assert target.metadata["uk_uc_source_month_count"] == "1"
    assert target.value == 100.0


def test_undeclared_non_uc_reference_keeps_existing_available_month_behavior(
    monkeypatch,
):
    reference = replace(_reference(), family="other", metadata={})
    result = _compile(monkeypatch, [_fact("2025-06")], reference)
    (target,) = result.registry.specs
    assert target.value == 100.0
    assert EXPECTED_SOURCE_MONTHS not in target.metadata


@pytest.mark.parametrize(
    "months",
    [
        [],
        "2025-04",
        [4],
        ["2025-13"],
        ["2025-4"],
        MONTHS[::-1],
        [*MONTHS, "2025-12"],
        ["2024-12", "2025-01"],
    ],
)
def test_invalid_source_month_declarations_fail(months):
    with pytest.raises(ValueError, match="source_months"):
        uc_source_month_metadata(months)


def test_generator_preserves_observation_basis_and_explicit_months():
    contract = {
        "targets": [
            {
                "target_id": "uc",
                "family": "dwp_universal_credit",
                "measurement": {
                    "observation_basis": "monthly_stock",
                    "source_months": MONTHS,
                },
            }
        ]
    }
    assert _reference_metadata(contract) == {
        "uc": {"observation_basis": "monthly_stock", **uc_source_month_metadata(MONTHS)}
    }
    contract["targets"][0]["family"] = "other"
    with pytest.raises(ValueError, match="UK UC-only"):
        _reference_metadata(contract)


def test_shipped_uc_monthly_references_declare_the_pinned_nine_month_window():
    references = load_country_spec("uk").target_references
    monthly = [
        reference
        for reference in references
        if reference.family == "dwp_universal_credit"
    ]
    assert len(monthly) == 111
    assert {reference.metadata[EXPECTED_SOURCE_MONTHS] for reference in monthly} == {
        uc_source_month_metadata(MONTHS)[EXPECTED_SOURCE_MONTHS]
    }
    assert all(
        reference.value_operation == "calendar_year_average" for reference in monthly
    )
    assert not any(
        EXPECTED_SOURCE_MONTHS in reference.metadata
        for reference in references
        if reference.family != "dwp_universal_credit"
    )
