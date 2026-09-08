"""Presentation hierarchy for UK local controls not supplied by Chronicle."""

from __future__ import annotations

from functools import cache

from microcosm.build.ledger_targets import hierarchy_seed_from_catalog
from microcosm.build.uk_runtime.local_targets import (
    AREA_TYPE_TO_LEDGER_GEOGRAPHY_LEVEL,
    load_uk_population_contract,
)
from microcosm.calibrate import (
    CalibrationHierarchy,
    CalibrationHierarchySeed,
    HierarchyGeography,
    HierarchyNode,
)

UK_CENSUS_HOUSEHOLDS_CATEGORY_ID = "ons.household_composition"


@cache
def _uk_hierarchy_seed(category_id: str) -> CalibrationHierarchySeed:
    """Resolve a normalized provider/category declaration from the UK contract."""

    hierarchy = load_uk_population_contract().get("hierarchy")
    if not isinstance(hierarchy, dict):
        raise ValueError("The UK population contract has no hierarchy catalog.")
    return hierarchy_seed_from_catalog(hierarchy, category_id)


def uk_local_target_hierarchy(
    *,
    name: str,
    label: str,
    category_id: str,
    area_type: str,
    area_code: str,
    area_label: str | None = None,
) -> CalibrationHierarchy:
    """Complete a UK contract category for one generated local target."""

    try:
        geography_level = AREA_TYPE_TO_LEDGER_GEOGRAPHY_LEVEL[area_type]
    except KeyError as error:
        raise ValueError(f"Unsupported UK local area type {area_type!r}.") from error
    seed = _uk_hierarchy_seed(category_id)
    return CalibrationHierarchy(
        provider=seed.provider,
        category=seed.category,
        geography=HierarchyGeography(
            id=area_code,
            label=area_label or area_code,
            level=geography_level,
        ),
        dimensions=(),
        target=HierarchyNode(id=name, label=label),
    )
