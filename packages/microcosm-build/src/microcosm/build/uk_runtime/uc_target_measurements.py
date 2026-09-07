"""UC statistical measurements, separate from benefit entitlement formulas.

DWP's two-child-limit statistics include exceptions and count the claim's
own dependent children/qualifying young people. They do not count everyone
under 18 in the dwelling, or only children losing an element:
https://www.gov.uk/government/statistics/universal-credit-claimants-statistics-on-the-two-child-limit-policy-april-2025/background-information-and-methodology

The retained frame does not identify April open claims or exact birth dates.
The affected measures therefore explicitly remain positive-award/birth-year
proxies. Their receipts record those gaps; improved fit is not evidence that
the administrative population has been reconstructed.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from microcosm.build.uk_runtime.uc_relationships import frs_uc_claimant_mask

UC_TARGET_VARIABLES = frozenset(
    {
        "uc_tcl_qualifying_child_count",
        "uc_tcl_affected_child_count_proxy",
        "uc_tcl_affected_benunit_proxy",
        "uc_tcl_claimant_receives_pip",
        "uc_tcl_receives_disabled_child_element",
        "uc_calibration_has_child_under_one",
    }
)


def uc_tcl_comparison_contract(year: int) -> dict[str, Any]:
    """Expose the remaining source/model differences to run receipts."""
    return {
        "source_unit": "UC claim (single claimant or couple)",
        "model_unit": "benunit",
        "source_child_definition": "own dependent children or qualifying young people",
        "includes_exceptions": True,
        "source_claim_state": "open claim within source observation month",
        "model_claim_state_proxy": "universal_credit > 0",
        "source_birth_cutoff": "2017-04-06",
        "model_birth_cutoff_proxy": "model birth_year >= 2017",
        "birth_precision": (
            "model year minus retained age input; source-age observation "
            "date/advancement and exact birth date unavailable"
        ),
        "source_period": "April snapshot; retain matched fact's observation year",
        "model_period": str(year),
        "period_alignment": "annual model state; not an April claim-history replay",
        "status": "partial_alignment_with_explicit_proxies",
    }


def compute_uc_target_measure(
    frame: Any, simulation: Any, variable: str, year: int
) -> np.ndarray:
    """Return a statistical measurement in benefit-unit row order.

    All member reductions use the person's own benefit unit. Child elements and
    PIP on another unit in the same dwelling must not leak into these counts.
    """
    if variable not in UC_TARGET_VARIABLES:
        raise KeyError(variable)
    person, benunit = frame.table("person"), frame.table("benunit")
    members = person["person_benunit_id"].to_numpy()
    ids = benunit["benunit_id"].to_numpy()
    claimant = frs_uc_claimant_mask(person, benunit)

    def calculate(name: str, *, entity: str = "person") -> np.ndarray:
        raw = simulation.calculate(name, year)
        values = np.asarray(raw.values if hasattr(raw, "values") else raw)
        if values.ndim != 1 or len(values) != len(frame.table(entity)):
            raise ValueError(f"UC measurement {name} must align with {entity} rows.")
        if values.dtype.kind not in "biuf" or not np.isfinite(values).all():
            raise ValueError(f"UC measurement {name} must be finite numeric values.")
        return values

    def count(mask: np.ndarray) -> np.ndarray:
        return (
            pd.Series(mask.astype(float))
            .groupby(members, sort=False)
            .sum()
            .reindex(ids)
            .to_numpy()
        )

    if variable == "uc_calibration_has_child_under_one":
        age = calculate("age")
        return count(~claimant & (age >= 0) & (age < 1)) > 0
    if variable == "uc_tcl_claimant_receives_pip":
        return count(claimant & (calculate("pip") > 0)) > 0

    children = ~claimant & calculate(
        "is_child_or_qualifying_young_person_for_universal_credit"
    ).astype(bool)
    child_count = count(children)
    if variable == "uc_tcl_qualifying_child_count":
        return child_count
    if variable == "uc_tcl_receives_disabled_child_element":
        return (
            count(children & (calculate("uc_individual_disabled_child_element") > 0))
            > 0
        )

    birth_year = calculate("birth_year")
    if not np.equal(birth_year, np.floor(birth_year)).all():
        raise ValueError("UC birth-year proxy requires integer model birth years.")
    # The first two children are the oldest. This count is invariant to person
    # row order and ties, and deliberately includes excepted later children.
    post_cutoff_count = count(children & (birth_year >= 2017))
    affected_count = np.minimum(post_cutoff_count, np.maximum(child_count - 2, 0))
    if variable == "uc_tcl_affected_child_count_proxy":
        return affected_count
    return (affected_count > 0) & (calculate("universal_credit", entity="benunit") > 0)
