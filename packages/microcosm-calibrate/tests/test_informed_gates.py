"""Informed L0 must preserve rare carriers without replacing the search."""

import numpy as np
import pytest
import torch
from scipy import sparse

from microcosm.calibrate.gates import HardConcrete
from microcosm.calibrate.initialization import contribution_initialization


def test_small_weight_large_measure_is_protected():
    init = contribution_initialization(
        sparse.csr_array([[1000.0, 0, 0], [0, 1, 1]]),
        np.array([0.01, 100.0, 100.0]),
        np.array([10.0, 200.0]),
    )
    assert init.protected[0]
    assert init.probabilities[0] > init.probabilities[1]


def test_protected_gates_stay_open_during_training_and_evaluation():
    gates = HardConcrete(
        3,
        initial_probabilities=np.array([0.2, 0.4, 0.8]),
        protected_mask=np.array([True, False, False]),
    )
    assert np.allclose(gates.get_active_prob().detach().numpy(), [1, 0.4, 0.8])
    with torch.no_grad():
        gates.qz_logits.fill_(-100)
    for training in (True, False):
        gates.train(training)
        assert gates()[0].item() == 1
    assert gates.get_active_prob()[0].item() == 1


@pytest.mark.parametrize(
    "probabilities", [[0, 0.5], [0.5, 1], [float("nan"), 0.5], [0.5]]
)
def test_invalid_initial_probabilities_refuse(probabilities):
    with pytest.raises(ValueError):
        HardConcrete(2, initial_probabilities=np.array(probabilities))


def test_mass_basis_budget_search_tracks_open_probability_mass():
    import numpy as np
    import pandas as pd

    from microcosm.calibrate import Target, TargetSet, calibrate
    from microcosm.calibrate.solve import (
        BUDGET_BASIS_NONZERO_COUNT,
        BUDGET_BASIS_OPEN_PROBABILITY_MASS,
    )
    from microcosm.frame import EntitySchema, Frame, WeightKind, Weights

    n = 60
    rng = np.random.default_rng(3)
    household = pd.DataFrame(
        {"household_id": np.arange(1, n + 1), "x": rng.uniform(1, 5, n)}
    )
    person = pd.DataFrame(
        {"person_id": np.arange(1, n + 1), "person_household_id": np.arange(1, n + 1)}
    )
    frame = Frame(
        {"person": person, "household": household},
        EntitySchema(group_entities=("household",)),
        {"household": Weights(np.ones(n), WeightKind.DESIGN)},
    )
    targets = TargetSet(
        [
            Target("count", "household", lambda f: np.ones(f.n("household")), 30.0),
            Target(
                "x",
                "household",
                lambda f: f.table("household")["x"].to_numpy(),
                30.0 * 3.0,
            ),
        ]
    )
    common = dict(epochs=200, learning_rate=0.05, seed=1, budget_iters=10)
    by_mass = calibrate(
        frame,
        targets,
        target_records=20,
        budget_basis=BUDGET_BASIS_OPEN_PROBABILITY_MASS,
        **common,
    )
    assert by_mass.options["budget_basis"] == BUDGET_BASIS_OPEN_PROBABILITY_MASS
    assert by_mass.gate_open_probabilities is not None
    mass = float(np.sum(by_mass.gate_open_probabilities))
    # The search's own tolerance is 5% of the budget (at least one record).
    assert abs(mass - 20) <= max(1, round(0.05 * 20)) + 1
    # The count basis on the same problem lands below the budget in mass.
    by_count = calibrate(
        frame,
        targets,
        target_records=20,
        budget_basis=BUDGET_BASIS_NONZERO_COUNT,
        **common,
    )
    assert by_count.options["budget_basis"] == BUDGET_BASIS_NONZERO_COUNT
    with pytest.raises(ValueError, match="budget_basis"):
        calibrate(frame, targets, target_records=20, budget_basis="bogus", **common)
    with pytest.raises(ValueError, match="target_records"):
        calibrate(
            frame, targets, budget_basis=BUDGET_BASIS_OPEN_PROBABILITY_MASS, **common
        )
