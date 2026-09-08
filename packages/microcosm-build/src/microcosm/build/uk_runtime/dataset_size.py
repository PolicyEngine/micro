"""Exact household-count UK candidates on a fixed, materialized target surface."""

import json
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from microcosm.calibrate import (
    CalibrationResult,
    TargetSet,
    assert_exact_k_support,
    calibrate,
    refit_l0_selection,
    select_exact_k,
)
from microcosm.calibrate.initialization import contribution_initialization
from microcosm.frame import Frame


@dataclass(frozen=True)
class UKDatasetSize:
    """A compact refit with its full-pool row identities and selection evidence."""

    result: CalibrationResult
    support: np.ndarray
    receipt: dict[str, object]


def refit_uk_dataset_size(
    frame: Frame,
    dense: CalibrationResult,
    *,
    households: int,
    epochs: int,
    learning_rate: float,
    seed: int,
    pi_hi: float = 1.0,
) -> UKDatasetSize:
    """Run informed L0, a fixed-size draw, and refit under the dense doctrine.

    Freeze the already compiled household contributions, including engine
    measures that depend on the full population. Re-evaluating those formulas
    on a subset would change the target system. Target values, order, loss
    weights, cap and stretch bound remain those of the dense solve.

    ``pi_hi`` is the exact-count draw's certainty threshold: gates whose
    learned open probability reaches it are taken with certainty and only the
    rest are drawn. The default ``1.0`` keeps exactly the protected carriers
    as certainties; a lower threshold (the US exact-k ladder runs 0.95)
    promotes learned near-certain gates and is a reviewed candidate-run
    setting recorded in the size receipt, never a release default.
    """
    n = frame.n("household")
    if (
        isinstance(households, bool)
        or not isinstance(households, int)
        or not 0 < households <= n
    ):
        raise ValueError(f"households must be an integer in [1, {n}]; never clamped.")
    if (
        dense.skipped
        or len(dense.weights) != n
        or dense.l0_lambda != 0
        or dense.weight_entity != "household"
        or not np.array_equal(
            frame.table("household")["household_id"].to_numpy(),
            dense.frame.table("household")["household_id"].to_numpy(),
        )
        or not np.array_equal(
            frame.weights_for("household").values, dense.initial_weights
        )
    ):
        raise ValueError(
            "size selection requires an aligned, fully compiled dense solve."
        )
    if households == n:
        return UKDatasetSize(
            dense,
            np.arange(n),
            {
                "method": "full_pool",
                "requested_households": n,
                "realized_households": n,
                "pool_households": n,
                "seed": seed,
            },
        )
    problem = dense.problem
    # Input weights are the pool design, not the concentrated dense weights.
    init = contribution_initialization(
        problem.matrix, dense.initial_weights, problem.target_vector
    )
    if int(init.protected.sum()) > households:
        raise ValueError(
            f"requested {households} households cannot retain {int(init.protected.sum())} protected target carriers."
        )
    common = dict(
        weight_entity="household",
        epochs=epochs,
        learning_rate=learning_rate,
        mass=dense.options["mass"],
        max_weight_ratio=dense.options["max_weight_ratio"],
        seed=seed,
        target_loss_weights=dense.target_loss_weights,
        target_loss_scales=dense.target_loss_scales,
        target_loss_cap=dense.target_loss_cap,
    )
    selection = calibrate(
        frame,
        TargetSet(problem.targets),
        target_records=households,
        gate_initialization=init,
        mass_reason=dense.options["mass_reason"],
        **common,
    )
    probabilities = selection.gate_open_probabilities
    if probabilities is None:
        raise RuntimeError("informed L0 returned no selection probabilities.")
    if not isinstance(pi_hi, float | int) or isinstance(pi_hi, bool):
        raise ValueError("pi_hi must be a number in (0, 1].")
    pi_hi = float(pi_hi)
    if not (0.0 < pi_hi <= 1.0):
        raise ValueError("pi_hi must be a number in (0, 1].")
    # Exact-one certainties are protected by the gates themselves. At the
    # default pi_hi=1.0 no learned boundary score is promoted; a lower
    # threshold promotes near-certain gates and is recorded in the receipt.
    feasibility = selection_feasibility(
        probabilities,
        households,
        protected=init.protected,
        n_nonzero=int(selection.n_nonzero),
        l0_lambda=float(selection.l0_lambda),
        requested_pi_hi=pi_hi,
    )
    try:
        support, sampling, q = select_exact_k(
            probabilities, households, pi_hi=pi_hi, seed=seed
        )
    except ValueError as error:
        # The draw refuses rather than clamps; carry the measured gate mass
        # with the refusal so the ruling it needs can be made from the receipt.
        raise ValueError(
            f"{error} Selection feasibility (requested pi_hi={pi_hi:g}): "
            f"{json.dumps(feasibility, sort_keys=True)}"
        ) from error
    support = assert_exact_k_support(support, households, pool_size=n)
    if not np.isin(np.flatnonzero(init.protected), support).all():
        raise RuntimeError("exact-count selection lost a protected carrier.")
    frozen = _frozen_targets(frame, dense, support)
    refit = refit_l0_selection(
        frame,
        frozen,
        selection,
        support=support,
        k=households,
        support_inclusion_probabilities=q,
        mass_reason=dense.options["mass_reason"],
        **common,
    ).refit
    if (
        refit.skipped
        or refit.frame.n("household") != households
        or (refit.weights <= 0).any()
    ):
        raise RuntimeError("compact refit lost targets or positive household support.")
    if not np.array_equal(refit.problem.target_vector, problem.target_vector):
        raise RuntimeError("compact refit changed target values.")
    errors_dense = np.asarray([d.final_estimate for d in dense.diagnostics])
    errors_small = np.asarray([d.final_estimate for d in refit.diagnostics])
    return UKDatasetSize(
        refit,
        support,
        {
            "method": "contribution_informed_l0_exact_count_refit",
            "requested_households": households,
            "realized_households": households,
            "pool_households": n,
            "seed": seed,
            "protected_carriers": int(init.protected.sum()),
            "selection_receipt": sampling,
            "selection_pi_hi": pi_hi,
            "selection_feasibility": feasibility,
            "selection_l0_lambda": selection.l0_lambda,
            "selection_epochs": epochs,
            "refit_epochs": epochs,
            "pool_row_indices": support.tolist(),
            "inclusion_probabilities": q.tolist(),
            "refit_baseline": "normalized_horvitz_thompson_w_over_q",
            "stretch_reference": "normalized_horvitz_thompson_w_over_q",
            "dense_loss": dense.final_loss,
            "compact_loss": refit.final_loss,
            "max_target_scaled_change": float(
                np.max(np.abs(errors_small - errors_dense) / dense.target_loss_scales)
            ),
            "certification": "candidate_only_pending_matched_comparison_and_promotion_scorecard",
        },
    )


_FEASIBILITY_PI_HI_GRID = (0.999, 0.99, 0.98, 0.95, 0.9, 0.8, 0.7, 0.5)


def selection_feasibility(
    probabilities: np.ndarray,
    households: int,
    *,
    protected: np.ndarray,
    n_nonzero: int,
    l0_lambda: float,
    requested_pi_hi: float = 1.0,
) -> dict[str, object]:
    """Measure whether an exact-count draw is feasible on these gate probabilities.

    ``select_exact_k`` with ``pi_hi=1.0`` keeps every gate below one in the
    boundary and scales its open probabilities to the remaining draw size
    ``m``; the scaled value of the largest boundary gate must not exceed one,
    i.e. ``m * max(pi_boundary) <= sum(pi_boundary)``. The L0 budget search
    stops on the count of not-fully-closed gates, which can sit well above the
    open-probability mass when gates are only partly polarised, so the draw
    can refuse. This records the measured mass and the two ways out — the
    smallest certainty threshold on a fixed grid that makes the design
    feasible, and the largest household count feasible at ``pi_hi=1.0`` — so
    the refusal is a ruling with numbers, never a silent clamp.
    """

    pi = np.asarray(probabilities, dtype=np.float64)
    protected_mask = np.asarray(protected, dtype=bool)
    if pi.shape != protected_mask.shape:
        raise ValueError("selection feasibility needs aligned probabilities and mask.")
    certainty = pi >= 1.0
    boundary = pi[~certainty]
    positive = boundary[boundary > 0.0]
    m = int(households) - int(certainty.sum())
    boundary_mass = float(positive.sum()) if positive.size else 0.0
    boundary_max = float(positive.max()) if positive.size else 0.0
    feasible = m <= 0 or (
        positive.size >= m and boundary_max * m <= boundary_mass * (1.0 + 1e-12)
    )
    max_feasible_k = (
        int(certainty.sum()) + int(np.floor(boundary_mass / boundary_max))
        if boundary_max > 0.0
        else int(certainty.sum())
    )
    scan: dict[str, object] = {}
    smallest_feasible_pi_hi: float | None = 1.0 if feasible else None
    for threshold in _FEASIBILITY_PI_HI_GRID:
        certain_t = pi >= threshold
        c_t = int(certain_t.sum())
        m_t = int(households) - c_t
        boundary_t = pi[~certain_t]
        positive_t = boundary_t[boundary_t > 0.0]
        mass_t = float(positive_t.sum()) if positive_t.size else 0.0
        max_t = float(positive_t.max()) if positive_t.size else 0.0
        ok = m_t >= 0 and (
            m_t == 0
            or (positive_t.size >= m_t and max_t * m_t <= mass_t * (1.0 + 1e-12))
        )
        scan[f"{threshold:g}"] = {
            "certainties": c_t,
            "boundary_draw": m_t,
            "boundary_mass": mass_t,
            "boundary_max": max_t,
            "feasible": bool(ok),
        }
        if ok and smallest_feasible_pi_hi is None:
            smallest_feasible_pi_hi = threshold
    quantiles = (
        {f"p{q * 100:g}": float(np.quantile(pi, q)) for q in (0.5, 0.9, 0.99, 0.999)}
        if pi.size
        else {}
    )
    requested = _feasible_at(pi, int(households), float(requested_pi_hi))
    return {
        "requested_households": int(households),
        "requested_pi_hi": float(requested_pi_hi),
        "feasible_at_requested_pi_hi": bool(requested),
        "pool_households": int(pi.size),
        "protected_carriers": int(protected_mask.sum()),
        "certainties_at_pi_hi_1": int(certainty.sum()),
        "boundary_draw": m,
        "boundary_positive_gates": int(positive.size),
        "boundary_mass": boundary_mass,
        "boundary_max": boundary_max,
        "feasible_at_pi_hi_1": bool(feasible),
        "max_feasible_households_at_pi_hi_1": max_feasible_k,
        "smallest_feasible_pi_hi_on_grid": smallest_feasible_pi_hi,
        "pi_hi_scan": scan,
        "pi_sum": float(pi.sum()),
        "pi_quantiles": quantiles,
        "gates_above": {
            f"{t:g}": int((pi >= t).sum()) for t in (0.5, 0.9, 0.99, 0.999)
        },
        "budget_search_n_nonzero": int(n_nonzero),
        "selection_l0_lambda": float(l0_lambda),
    }


def _feasible_at(pi: np.ndarray, households: int, threshold: float) -> bool:
    certain = pi >= threshold
    draw = households - int(certain.sum())
    if draw < 0:
        return False
    if draw == 0:
        return True
    boundary = pi[~certain]
    positive = boundary[boundary > 0.0]
    if positive.size < draw:
        return False
    return bool(float(positive.max()) * draw <= float(positive.sum()) * (1.0 + 1e-12))


def _frozen_targets(
    frame: Frame, dense: CalibrationResult, support: np.ndarray
) -> TargetSet:
    """Bind sparse contribution rows to selected ids, with one shared id join."""
    ids = pd.Index(frame.table("household")["household_id"].iloc[support])
    matrix = dense.problem.matrix[:, support].tocsr()
    cached_ids = None
    cached_positions = None

    def positions(subset):
        nonlocal cached_ids, cached_positions
        current = subset.table("household")["household_id"]
        if cached_ids is None or not current.equals(cached_ids):
            cached_positions = ids.get_indexer(current)
            if (cached_positions < 0).any():
                raise ValueError("frozen target requested unknown household ids.")
            cached_ids = current.copy()
        return cached_positions

    def measure(row):
        def values(subset):
            return np.asarray(matrix[[row], :].toarray()).reshape(-1)[positions(subset)]

        return values

    return TargetSet(
        [
            replace(target, entity="household", measure=measure(row), filter=None)
            for row, target in enumerate(dense.problem.targets)
        ]
    )
