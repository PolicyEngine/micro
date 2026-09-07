"""Generate synthetic schema-8 diagnostics for every registered UK target.

The generated numbers are deliberately artificial.  The artifact exists to
exercise the complete declaration -> Chronicle match -> scalar reference ->
TargetSpec -> registry -> Target -> diagnostics path without restricted data.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from dataclasses import asdict
from hashlib import sha256
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from microcosm.build.country_spec import load_country_spec
from microcosm.build.ledger_targets import compile_ledger_target_references
from microcosm.calibrate import TargetRegistry
from microcosm.calibrate.diagnostics import diagnostics_payload
from microcosm.calibrate.score import score_targets
from microcosm.frame import EntitySchema, Frame, WeightKind, Weights

DEFAULT_RELEASE_ID = "microcosm-uk-schema8-synthetic-all"
FIT_MULTIPLIERS = (0.78, 0.88, 0.94, 0.99, 1.02, 1.07, 1.14, 1.26)
REPRESENTATIVE_REFERENCE_NAMES = frozenset(
    {
        "obr.income_tax",
        "dwp.uc.two_child_limit.households_affected",
        "ons.population.uk_total",
        "hmrc/employment_income_income_band_12_570_to_15_000",
        "slc.repayments.england_plan_2",
        "obr.esa",
        "hmrc.cgt.gains_total",
        "hmrc.cgt.taxpayers_total",
    }
)
REPRESENTATIVE_FEED_ROWS = (
    Path(__file__).parents[1]
    / "packages"
    / "microcosm-build"
    / "tests"
    / "fixtures"
    / "uk_target_reference_feed_rows.jsonl"
)


def _humanize(value: object) -> str:
    text = re.sub(r"[._/:-]+", " ", str(value)).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:1].upper() + text[1:] if text else "Target"


def _dimension_label(dimension_id: str) -> str:
    """Match Microcosm's fallback label for a Chronicle dimension id."""

    tail = dimension_id.rsplit("/", 1)[-1].rsplit(".", 1)[-1]
    return _humanize(tail)


def _safe_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "target"


def _digest(value: str) -> str:
    return sha256(value.encode()).hexdigest()[:24]


def _target_label(reference: object) -> str:
    name = str(reference.name)
    source = str(reference.ledger_selector.get("source_name", ""))
    remainder = re.sub(rf"^{re.escape(source)}[./]", "", name)
    return _humanize(remainder)


def _value_combinations(reference: object) -> list[dict[str, object]]:
    pins = dict(reference.ledger_selector.get("dimension_values") or {})
    if reference.value_operation != "sum":
        return [
            {
                key: value[0] if isinstance(value, list) else value
                for key, value in pins.items()
            }
        ]
    keys = list(pins)
    candidates = [
        value if isinstance(value, list) else [value] for value in pins.values()
    ]
    return [dict(zip(keys, values, strict=True)) for values in product(*candidates)]


def _fact_dimensions(
    reference: object,
    values: dict[str, object],
) -> dict[str, object]:
    declared = reference.ledger_selector.get("dimensions")
    if isinstance(declared, list):
        return {
            str(key): values.get(str(key), f"synthetic_{_safe_token(str(key))}")
            for key in declared
        }
    dimensions = dict(declared) if isinstance(declared, dict) else {}
    dimensions.update(values)
    return dimensions


def _source_measure_id(reference: object) -> str:
    selected = reference.ledger_selector.get("source_measure_id")
    if isinstance(selected, list):
        return str(selected[0])
    if selected not in (None, ""):
        return str(selected)
    concept = str(reference.ledger_selector.get("source_concept", ""))
    return _safe_token(concept.rsplit(".", 1)[-1] or reference.name)


def _measure_unit(reference: object) -> str:
    text = " ".join(
        (
            str(reference.name),
            str(reference.measure),
            str(reference.ledger_selector.get("source_concept", "")),
            _source_measure_id(reference),
        )
    ).lower()
    count_markers = (
        "count",
        "claimant",
        "children",
        "household",
        "population",
        "pupil",
        "recipient",
        "stock",
        "taxpayer",
        "unit",
        "user",
    )
    return "count" if any(marker in text for marker in count_markers) else "gbp"


def _groupby_identity(
    reference: object,
    dimensions: dict[str, object],
) -> tuple[str, str, str]:
    selector = reference.ledger_selector
    source = str(selector.get("source_name", "other"))
    dimension_id = str(
        selector.get("groupby_dimension") or f"{source}.{reference.family}_line"
    )
    if dimension_id in dimensions:
        value_id = str(dimensions[dimension_id])
        value_label = _humanize(value_id)
    else:
        value_id = _safe_token(str(reference.name))
        value_label = _target_label(reference)
    return dimension_id, value_id, value_label


def _period_rows(reference: object) -> list[dict[str, object]]:
    if reference.value_operation == "calendar_year_average":
        return [
            {"type": "month", "value": f"2025-{month:02d}"} for month in range(1, 13)
        ]
    return [{"type": "year", "value": reference.period or 2025}]


def _geography_label(geography_id: str) -> str:
    return {
        "K02000001": "United Kingdom",
        "K03000001": "Great Britain",
        "E92000001": "England",
        "W92000004": "Wales",
        "S92000003": "Scotland",
        "N92000002": "Northern Ireland",
    }.get(geography_id, geography_id)


def synthetic_facts_for_reference(
    reference: object,
    reference_index: int,
    *,
    dimension_label_catalog: Mapping[str, str] | None = None,
    dimension_value_label_catalog: Mapping[tuple[str, str], str] | None = None,
) -> list[dict[str, Any]]:
    """Create Chronicle consumer facts that satisfy one scalar selector."""

    selector = reference.ledger_selector
    source = str(selector.get("source_name", "other"))
    source_measure_id = _source_measure_id(reference)
    concept = str(selector.get("source_concept") or f"{source}.{source_measure_id}")
    geography_level = str(selector.get("geography_level", "country"))
    geography_id = str(selector.get("geography_id", "K02000001"))
    assertion = (
        "source_projection"
        if reference.assertion_policy == "allow_source_projection"
        else "observation"
    )
    unit = _measure_unit(reference)
    facts: list[dict[str, Any]] = []
    ordinal = 0
    for combination_index, values in enumerate(_value_combinations(reference)):
        dimensions = _fact_dimensions(reference, values)
        dimension_labels = {
            str(dimension_id): (
                (dimension_label_catalog or {}).get(str(dimension_id))
                or _dimension_label(str(dimension_id))
            )
            for dimension_id in dimensions
        }
        dimension_value_labels = {
            str(dimension_id): {
                str(value): (
                    (dimension_value_label_catalog or {}).get(
                        (str(dimension_id), str(value))
                    )
                    or _humanize(value)
                )
            }
            for dimension_id, value in dimensions.items()
        }
        groupby_id, groupby_value_id, groupby_value_label = _groupby_identity(
            reference,
            dimensions,
        )
        for period in _period_rows(reference):
            identity = json.dumps(
                {
                    "reference": reference.name,
                    "dimensions": dimensions,
                    "period": period,
                    "combination": combination_index,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            key = _digest(identity)
            target_label = _target_label(reference)
            value = float(100_000 + (reference_index + 1) * 17_000 + ordinal * 1_300)
            facts.append(
                {
                    "schema_version": "ledger.consumer_fact.v1",
                    "aggregate_fact_key": f"ledger.aggregate_fact.v2:{key}",
                    "semantic_fact_key": f"ledger.semantic_fact.v2:{key}",
                    "legacy_fact_key": f"ledger.fact.v1:{key}",
                    "aggregation": {"method": "sum"},
                    "assertion": assertion,
                    "geography": {
                        "level": geography_level,
                        "id": geography_id,
                        "name": _geography_label(geography_id),
                        "vintage": "synthetic-current",
                    },
                    "entity": {
                        "name": reference.entity,
                        "role": "synthetic_dashboard_preview",
                    },
                    "dimensions": dimensions,
                    "dimension_labels": dimension_labels,
                    "dimension_value_labels": dimension_value_labels,
                    "label": target_label,
                    "layout": {
                        "groupby_dimension": groupby_id,
                        "groupby_dimension_label": (
                            (dimension_label_catalog or {}).get(groupby_id)
                            or _dimension_label(groupby_id)
                        ),
                        "groupby_ordinal": reference_index * 100 + combination_index,
                        "groupby_value_id": groupby_value_id,
                        "groupby_value_label": (
                            (dimension_value_label_catalog or {}).get(
                                (groupby_id, groupby_value_id)
                            )
                            or groupby_value_label
                        ),
                        "measure_id": source_measure_id,
                        "measure_label": f"{target_label} ({unit})",
                        "measure_ordinal": 0,
                        "record_set_id": (
                            f"synthetic.uk.{_safe_token(str(reference.name))}"
                        ),
                        "record_set_spec_id": (
                            f"synthetic.uk.{_safe_token(str(reference.name))}.v1"
                        ),
                        "source_column_id": source_measure_id,
                        "source_row_id": groupby_value_id,
                        "table_record_kind": "synthetic",
                    },
                    "lineage": {
                        "source_record_id": (
                            f"synthetic.uk.{_safe_token(str(reference.name))}.{key}"
                        )
                    },
                    "observed_measure": {
                        "source_name": source,
                        "source_concept": concept,
                        "source_measure_id": source_measure_id,
                        "source_table": "Synthetic UK dashboard preview",
                        "unit": unit,
                    },
                    "concept_alignment": {
                        "authority": source,
                        "canonical_concept": concept,
                        "relation": "synthetic_dashboard_preview",
                        "source_concept": concept,
                    },
                    "period": period,
                    "provenance_class": "synthetic",
                    "source": {
                        "source_name": source,
                        "source_table": "Synthetic UK dashboard preview",
                        "extraction_method": (
                            "Generated from a registered Microcosm UK target selector"
                        ),
                        "url": "https://github.com/PolicyEngine/microcosm",
                        "vintage": "synthetic",
                    },
                    "universe_constraints": {
                        "domain": _safe_token(str(reference.family))
                    },
                    "value": value,
                    "value_type": "number",
                }
            )
            ordinal += 1
    return facts


def _deduplicate_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for fact in facts:
        unique.setdefault(str(fact["aggregate_fact_key"]), fact)
    return list(unique.values())


def _representative_facts() -> list[dict[str, Any]]:
    """Load the public Chronicle-shaped rows used by UK contract tests."""

    return [
        json.loads(line)
        for line in REPRESENTATIVE_FEED_ROWS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _representative_label_catalogs(
    facts: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """Index Chronicle labels so generated facts reuse established identifiers."""

    dimension_labels: dict[str, str] = {}
    dimension_value_labels: dict[tuple[str, str], str] = {}
    for fact in facts:
        raw_dimension_labels = fact.get("dimension_labels")
        raw_value_labels = fact.get("dimension_value_labels")
        for dimension_id, value in (fact.get("dimensions") or {}).items():
            dimension_id = str(dimension_id)
            value_id = str(value)
            explicit_dimension_label = (
                raw_dimension_labels.get(dimension_id)
                if isinstance(raw_dimension_labels, Mapping)
                else None
            )
            dimension_labels.setdefault(
                dimension_id,
                str(explicit_dimension_label).strip()
                if explicit_dimension_label
                else _dimension_label(dimension_id),
            )
            explicit_values = (
                raw_value_labels.get(dimension_id)
                if isinstance(raw_value_labels, Mapping)
                else None
            )
            explicit_value_label = (
                explicit_values.get(value_id)
                if isinstance(explicit_values, Mapping)
                else None
            )
            dimension_value_labels.setdefault(
                (dimension_id, value_id),
                str(explicit_value_label).strip()
                if explicit_value_label
                else _humanize(value),
            )

        layout = fact.get("layout")
        if not isinstance(layout, Mapping):
            continue
        groupby_id = str(layout.get("groupby_dimension") or "").strip()
        groupby_value_id = str(layout.get("groupby_value_id") or "").strip()
        if not groupby_id:
            continue
        groupby_label = str(layout.get("groupby_dimension_label") or "").strip()
        dimension_labels.setdefault(
            groupby_id,
            groupby_label or _dimension_label(groupby_id),
        )
        if groupby_value_id:
            groupby_value_label = str(
                layout.get("groupby_value_label") or ""
            ).strip()
            dimension_value_labels.setdefault(
                (groupby_id, groupby_value_id),
                groupby_value_label or _humanize(groupby_value_id),
            )
    return dimension_labels, dimension_value_labels


def _synthetic_frame(registry: TargetRegistry) -> Frame:
    record_ids = np.arange(3, dtype="int64")
    weights = np.array([10.0, 20.0, 30.0])
    columns: dict[str, dict[str, np.ndarray]] = {
        "person": {},
        "benunit": {},
        "household": {},
    }
    for index, compiled in enumerate(registry.specs):
        scale = (
            float(compiled.value) * FIT_MULTIPLIERS[index % len(FIT_MULTIPLIERS)] / 50.0
        )
        columns[compiled.entity][compiled.measure] = np.array([scale, 2.0 * scale, 0.0])
    return Frame(
        {
            "person": pd.DataFrame(
                {
                    "person_id": record_ids,
                    "person_benunit_id": record_ids,
                    "person_household_id": record_ids,
                    **columns["person"],
                }
            ),
            "benunit": pd.DataFrame({"benunit_id": record_ids, **columns["benunit"]}),
            "household": pd.DataFrame(
                {"household_id": record_ids, **columns["household"]}
            ),
        },
        EntitySchema(group_entities=("benunit", "household")),
        {"household": Weights(values=weights, kind=WeightKind.DESIGN)},
        metadata={"time_period": "2025", "synthetic": True},
    )


def _write_json(output_directory: Path, filename: str, value: object) -> None:
    (output_directory / filename).write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def generate_artifact(
    output_directory: Path,
    *,
    release_id: str = DEFAULT_RELEASE_ID,
) -> dict[str, object]:
    """Generate and validate the complete synthetic UK schema-8 artifact."""

    country_spec = load_country_spec("uk")
    references = list(country_spec.target_references)
    representative_facts = _representative_facts()
    dimension_labels, dimension_value_labels = _representative_label_catalogs(
        representative_facts
    )
    facts = _deduplicate_facts(
        representative_facts
        + [
            fact
            for index, reference in enumerate(references)
            if reference.name not in REPRESENTATIVE_REFERENCE_NAMES
            for fact in synthetic_facts_for_reference(
                reference,
                index,
                dimension_label_catalog=dimension_labels,
                dimension_value_label_catalog=dimension_value_labels,
            )
        ]
    )
    compiled_registry = compile_ledger_target_references(
        facts,
        references,
        country="uk",
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    registry_path = compiled_registry.to_json(output_directory / "target_registry.json")
    registry = TargetRegistry.from_json(registry_path)
    if registry.version != compiled_registry.version:
        raise AssertionError("The registry hierarchy changed during serialization.")
    if any(reference.hierarchy is None for reference in references):
        raise AssertionError(
            "Every registered UK reference must have a hierarchy seed."
        )
    target_set = registry.to_target_set()
    for compiled, reloaded, target in zip(
        compiled_registry.specs,
        registry.specs,
        target_set.targets,
        strict=True,
    ):
        if compiled.hierarchy != reloaded.hierarchy:
            raise AssertionError(
                f"Hierarchy changed during registry reload for {compiled.name!r}."
            )
        if reloaded.hierarchy != target.hierarchy:
            raise AssertionError(
                f"Hierarchy changed during Target compilation for {compiled.name!r}."
            )
    result = score_targets(_synthetic_frame(registry), target_set)
    diagnostics = diagnostics_payload(
        result,
        target_registry=registry,
        build={
            "build_id": release_id,
            "country": "uk",
            "artifact_kind": "synthetic_dashboard_preview",
            "registered_target_count": len(references),
            "synthetic_fact_count": len(facts),
        },
    )
    diagnostics["release_id"] = release_id
    diagnostics["description"] = (
        "Schema-8 dashboard preview compiled from every registered Microcosm "
        "UK national target and synthetic Chronicle-shaped facts."
    )
    rows = diagnostics["targets"]
    if len(references) != len(registry.specs) or len(registry.specs) != len(rows):
        raise AssertionError(
            "Registered references, compiled specs, and diagnostic rows must align."
        )
    if any(not row.get("hierarchy") for row in rows):
        raise AssertionError("Every schema-8 diagnostic target must carry a hierarchy.")
    rows_by_target = {row["target_name"]: row for row in rows}
    for spec in registry.specs:
        serialized_hierarchy = json.loads(json.dumps(asdict(spec.hierarchy)))
        if rows_by_target[spec.name]["hierarchy"] != serialized_hierarchy:
            raise AssertionError(
                f"Hierarchy changed during diagnostics serialization for {spec.name!r}."
            )

    provider_labels = {
        row["hierarchy"]["provider"]["id"]: row["hierarchy"]["provider"]["label"]
        for row in rows
    }
    _write_json(output_directory, "calibration_diagnostics.json", diagnostics)
    sample_names = (
        "obr.income_tax",
        "hmrc/employment_income_income_band_12_570_to_15_000",
        "dwp.uc.two_child_limit.households_affected",
    )
    _write_json(
        output_directory,
        "calibration_hierarchy_samples.json",
        [rows_by_target[name] for name in sample_names],
    )
    _write_json(
        output_directory,
        "build_manifest.json",
        {
            "build_id": release_id,
            "country": "uk",
            "description": diagnostics["description"],
            "synthetic": True,
            "gates": {
                "target_compilation": {
                    "declared_targets": len(references),
                    "compiled_candidate_targets": len(registry.specs),
                    "dropped_target_names": [],
                }
            },
        },
    )
    _write_json(
        output_directory,
        "release_manifest.json",
        {
            "schema_version": 1,
            "description": diagnostics["description"],
            "is_default": True,
            "default_datasets": {"national": release_id},
            "publisher_labels": provider_labels,
            "country": {
                "code": "uk",
                "label": "United Kingdom",
                "geography_id": "K02000001",
                "geography_label": "United Kingdom",
                "repository_visibility": "private",
                "capabilities": ["calibration", "targets", "compare"],
            },
            "presentation": {
                "overview_intro": (
                    "Synthetic UK schema-8 preview covering every registered "
                    "national target."
                ),
                "targets_intro": (
                    "Every registered UK target compiled from synthetic "
                    "Chronicle-shaped facts."
                ),
            },
        },
    )

    dimension_count = sum(len(row["hierarchy"]["dimensions"]) for row in rows)
    return {
        "output_directory": str(output_directory),
        "schema_version": diagnostics["schema_version"],
        "registered_references": len(references),
        "synthetic_facts": len(facts),
        "compiled_targets": len(registry.specs),
        "diagnostic_targets": len(rows),
        "providers": provider_labels,
        "categories": len({row["hierarchy"]["category"]["id"] for row in rows}),
        "dimension_records": dimension_count,
        "registry_version": registry.version,
        "sample_targets": list(sample_names),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--release-id", default=DEFAULT_RELEASE_ID)
    args = parser.parse_args()
    summary = generate_artifact(args.output_directory, release_id=args.release_id)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
