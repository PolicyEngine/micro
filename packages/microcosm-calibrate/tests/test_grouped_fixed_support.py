"""Invented full-population contracts for opt-in fixed-zero grouped fitting."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest
import torch

from microcosm.calibrate import GroupedUpperBounds, Target, TargetSet, calibrate, solve
from microcosm.frame import EntitySchema, Frame, WeightKind, Weights


def _frame(weights=(0.0, 0.0, 40.0, 40.0, 0.0, 20.0)):
    return Frame(
        {
            "person": pd.DataFrame(
                {"person_id": range(6), "person_household_id": range(6)}
            ),
            "household": pd.DataFrame(
                {
                    "household_id": range(6),
                    "native": [1.0, 0.0, 1.0, 0.0, 1.0, 0.0],
                    "detail": [0.0, 1.0, 0.0, 1.0, 0.0, 1.0],
                }
            ),
        },
        EntitySchema(group_entities=("household",)),
        {"household": Weights(values=np.asarray(weights), kind=WeightKind.IMPORTANCE)},
    )


def _groups():
    # A zero-only origin, a positive clone pair and a mixed-support group.
    return GroupedUpperBounds(
        tuple(range(6)), np.array([0, 0, 1, 1, 2, 2]), np.array([0.0, 100.0, 30.0])
    )


def _targets():
    return TargetSet(
        (
            Target(name="native", entity="household", value=150.0, measure="native"),
            Target(name="detail", entity="household", value=10.0, measure="detail"),
        )
    )


def _fit(**kwargs):
    options = dict(
        epochs=20,
        learning_rate=0.08,
        grouped_upper_bounds=_groups(),
        grouped_preserve_zeros=True,
    )
    options.update(kwargs)
    return calibrate(_frame(), _targets(), **options)


@pytest.mark.parametrize("sparse", [False, True])
def test_full_population_survives_positive_only_log_parameters(monkeypatch, sparse):
    if sparse:
        monkeypatch.setattr(solve, "_SPARSE_MIN_CELLS", 1)
        monkeypatch.setattr(solve, "_SPARSE_DENSITY_CUTOFF", 1.0)
    original_adam = torch.optim.Adam
    parameter_sizes = []

    def adam(parameters, **kwargs):
        parameters = list(parameters)
        parameter_sizes.extend(x.numel() for x in parameters)
        return original_adam(parameters, **kwargs)

    monkeypatch.setattr(torch.optim, "Adam", adam)
    original_apply = solve._apply_constraint

    def apply(matrix, weights):
        assert weights.shape == (6,)
        assert weights.dtype == torch.float32 and weights.grad_fn is not None
        assert torch.equal(weights[[0, 1, 4]], torch.zeros(3))
        assert matrix.layout == (torch.sparse_csr if sparse else torch.strided)
        return original_apply(matrix, weights)

    monkeypatch.setattr(solve, "_apply_constraint", apply)
    observations = []
    result = _fit(_post_projection_observer=observations.append)
    assert parameter_sizes == [3]
    assert len(observations) == 21
    original = _frame()
    for entity in ("household", "person"):
        pd.testing.assert_frame_equal(
            result.frame.table(entity), original.table(entity)
        )
    for observation in observations:
        assert observation["weights"].shape == (6,)
        assert observation["household_ids"] == tuple(range(6))
        assert observation["weights"][[0, 1, 4]].tobytes() == np.zeros(3).tobytes()
        np.testing.assert_array_equal(
            _groups().check(observation["weights"]), observation["group_totals"]
        )
    assert result.weights[2] > 40.0 and result.weights[3] < 40.0
    assert result.weights.tobytes() == observations[-1]["weights"].tobytes()
    assert (
        result.frame.resolve_weights("household").values.tobytes()
        == result.weights.tobytes()
    )
    assert (
        result.initial_weights.tobytes()
        == original.resolve_weights("household").values.tobytes()
    )
    assert result.options["grouped_preserve_zeros"] == {
        "enabled": True,
        "fixed_zero_count": 3,
        "ordered_zero_mask_sha256": hashlib.sha256(
            bytes([1, 1, 0, 0, 1, 0])
        ).hexdigest(),
    }


@pytest.mark.parametrize(
    "warm",
    [
        [1.0, 0.0, 40.0, 40.0, 0.0, 20.0],
        [0.0, 0.0, 0.0, 40.0, 0.0, 20.0],
        [0.0, 0.0, 60.0, 60.0, 0.0, 20.0],
        [0.0, 0.0, 40.0, 40.0, -1.0, 20.0],
        [0.0, 0.0, float("nan"), 40.0, 0.0, 20.0],
        [0.0, 0.0, 40.0, 40.0, 0.0],
    ],
)
def test_invalid_warm_support_refuses_before_optimizer(monkeypatch, warm):
    calls = []
    monkeypatch.setattr(torch.optim, "Adam", lambda *a, **k: calls.append(1))
    with pytest.raises(ValueError):
        _fit(warm_start_weights=np.array(warm))
    assert calls == []


def test_valid_warm_starts_keep_original_support_and_initial_diagnostics():
    first = _fit()
    seen = []
    second = _fit(
        epochs=2,
        warm_start_weights=first.weights,
        _post_projection_observer=seen.append,
    )
    assert seen[0]["weights"].tobytes() == first.weights.tobytes()
    assert (
        second.initial_weights.tobytes()
        == _frame().resolve_weights("household").values.tobytes()
    )
    assert second.weights[[0, 1, 4]].tobytes() == np.zeros(3).tobytes()


@pytest.mark.parametrize("value", [1, "yes", None, np.bool_(True)])
def test_nonboolean_zero_option_refuses(value):
    with pytest.raises(ValueError, match="boolean"):
        _fit(grouped_preserve_zeros=value)


def test_zero_option_requires_grouping_and_default_keeps_positive_contract():
    with pytest.raises(ValueError, match="requires grouped"):
        _fit(grouped_upper_bounds=None)
    with pytest.raises(ValueError, match="strictly positive"):
        _fit(grouped_preserve_zeros=False)


@pytest.mark.parametrize("anchor", ["initial", "uniform", "explicit"])
def test_l2_penalty_is_finite_with_fixed_zero_support(anchor):
    options = {"l2_lambda": 0.01, "l2_anchor": anchor}
    if anchor == "explicit":
        options["l2_anchor_weights"] = np.array([1.0, 1.0, 40.0, 40.0, 1.0, 20.0])
    result = _fit(**options)
    assert (
        np.isfinite(result.loss_trajectory).all() and np.isfinite(result.weights).all()
    )
    assert result.weights[[0, 1, 4]].tobytes() == np.zeros(3).tobytes()


def test_all_zero_numeric_support_refuses_before_optimizer(monkeypatch):
    calls = []
    monkeypatch.setattr(torch.optim, "Adam", lambda *a, **k: calls.append(1))
    with pytest.raises(ValueError, match="positive initial"):
        solve._optimize(
            torch.ones((1, 2), dtype=torch.float32),
            torch.ones(1, dtype=torch.float32),
            None,
            torch.ones(1, dtype=torch.float32),
            10.0,
            np.zeros(2),
            epochs=2,
            learning_rate=0.02,
            conserve_mass=False,
            max_weight_ratio=None,
            l0_lambda=0.0,
            l2_lambda=0.0,
            target_records=None,
            init_mean=0.999,
            temperature=0.25,
            grouped_upper_bounds=GroupedUpperBounds(
                (0, 1), np.array([0, 0]), np.array([0.0])
            ),
            grouped_preserve_zeros=True,
        )
    assert calls == []


def test_observer_cannot_change_fixed_mask_or_accepted_weights():
    baseline = _fit()

    def corrupt(payload):
        payload["weights"][:] = 1.0
        payload["group_indices"][:] = 0
        payload["absolute_bounds"][:] = 99.0
        payload["group_totals"][:] = 99.0

    changed = _fit(_post_projection_observer=corrupt)
    assert changed.weights.tobytes() == baseline.weights.tobytes()


def test_materialized_zero_activation_refuses(monkeypatch):
    apply = solve._apply_weights

    def corrupt(*args, **kwargs):
        result = apply(*args, **kwargs)
        current = result.resolve_weights("household")
        values = current.values.copy()
        # Within a positive group bound, so group totals alone cannot catch this.
        values[4] = np.nextafter(0.0, 1.0)
        return result.with_weights(
            "household", current.with_values(values, kind=current.kind), mass="conserve"
        )

    monkeypatch.setattr(solve, "_apply_weights", corrupt)
    with pytest.raises(ValueError, match="zero support"):
        _fit()


def test_aligned_reordering_required_with_zero_rows():
    reordered = GroupedUpperBounds(
        (1, 0, 2, 3, 4, 5), np.array([0, 0, 1, 1, 2, 2]), np.array([0.0, 100.0, 30.0])
    )
    with pytest.raises(ValueError, match="ordered IDs"):
        _fit(grouped_upper_bounds=reordered)


def test_retained_zero_ratio_is_finite_and_activation_is_infinite():
    result = _fit()
    active = result.initial_weights > 0
    expected = float((result.weights[active] / result.initial_weights[active]).max())
    assert result.realized_max_weight_ratio == expected
    # A diagnostic must not hide invalid positive mass on an initial zero.
    from dataclasses import replace

    changed = result.weights.copy()
    changed[0] = 1.0
    assert replace(result, weights=changed).realized_max_weight_ratio == float("inf")


def test_returned_id_swap_refuses_even_when_weight_bytes_match(monkeypatch):
    apply = solve._apply_weights

    def corrupt(*args, **kwargs):
        result = apply(*args, **kwargs)
        result.table("household").loc[[0, 2], "household_id"] = [2, 0]
        return result

    monkeypatch.setattr(solve, "_apply_weights", corrupt)
    with pytest.raises(ValueError, match="ordered IDs"):
        _fit()


def test_late_options_identity_mutation_refuses(monkeypatch):
    apply = solve._apply_weights
    diagnostics = GroupedUpperBounds.diagnostics
    frames = []

    def capture(*args, **kwargs):
        result = apply(*args, **kwargs)
        frames.append(result)
        return result

    def corrupt(self, weights, last_corrected_count=0):
        result = diagnostics(self, weights, last_corrected_count)
        frames[-1].table("household").loc[[0, 2], "household_id"] = [2, 0]
        return result

    monkeypatch.setattr(solve, "_apply_weights", capture)
    monkeypatch.setattr(GroupedUpperBounds, "diagnostics", corrupt)
    with pytest.raises(ValueError, match="ordered IDs"):
        _fit()
