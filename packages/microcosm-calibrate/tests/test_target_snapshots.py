"""Per-target calibration estimate snapshots (microcosm#908, slice 1).

Covers the shared codec (schema identity, ordering, finiteness, signed
relative error with the zero-target convention, aggregate-only refusal),
the cadence, the atomic/immutable local store, and the solver seam:
emission from real Adam iterations, honest current/best_retained/selected
labelling, multi-phase and budget-search identity, and byte-identical
optimizer results with the observer off and on.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from microcosm.calibrate.solve import CONSERVE_MASS, calibrate, calibrate_l0_refit
from microcosm.calibrate.target import Target, TargetSet
from microcosm.calibrate.target_snapshots import (
    EVERY_EPOCH,
    ITERATE_BEST_RETAINED,
    ITERATE_CURRENT,
    ITERATE_SELECTED,
    LATEST_SNAPSHOT_FILENAME,
    TARGET_SNAPSHOT_SCHEMA,
    TARGET_SNAPSHOT_SCHEMA_VERSION,
    TargetSnapshotCadence,
    TargetSnapshotError,
    TargetSnapshotObserver,
    TargetSnapshotWriter,
    signed_relative_error,
    target_identity_digest,
    validate_target_snapshot,
)
from microcosm.frame import EntitySchema, Frame, WeightKind, Weights

#: One person per household, so household weights are the calibrated vector.
_SCHEMA = EntitySchema(group_entities=("household",))

#: A tiny invented frame: four households with an income and an adult count.
_INCOME = np.array([100.0, 200.0, 300.0, 400.0])
_ADULTS = np.array([1.0, 2.0, 1.0, 2.0])
_WEIGHTS = np.array([10.0, 10.0, 10.0, 10.0])


def _frame() -> Frame:
    import pandas as pd

    household_ids = np.arange(len(_WEIGHTS), dtype="int64")
    person = pd.DataFrame(
        {
            "person_id": household_ids,
            "person_household_id": household_ids,
        }
    )
    household = pd.DataFrame(
        {
            "household_id": household_ids,
            "income": _INCOME,
            "adults": _ADULTS,
        }
    )
    return Frame(
        {"person": person, "household": household},
        _SCHEMA,
        {"household": Weights(values=_WEIGHTS.copy(), kind=WeightKind.DESIGN)},
    )


def _targets() -> TargetSet:
    """Targets deliberately off the frame's aggregates, so the solver has to move."""
    return TargetSet(
        [
            Target(
                name="income",
                period=2024,
                entity="household",
                measure="income",
                value=12000.0,
            ),
            Target(
                name="adults",
                period=2024,
                entity="household",
                measure="adults",
                value=50.0,
            ),
        ]
    )


def _collect(**observer_kwargs) -> tuple[list[dict], TargetSnapshotObserver]:
    seen: list[dict] = []
    observer = TargetSnapshotObserver(
        sink=seen.append, run_id="run-1", **observer_kwargs
    )
    return seen, observer


# --------------------------------------------------------------------------
# Codec: identity, ordering, finiteness, zero-target semantics
# --------------------------------------------------------------------------


def test_target_identity_digest_is_order_sensitive_and_value_sensitive():
    names = ("a@2024", "b@2024")
    base = target_identity_digest(names, (1.0, 2.0))
    assert base == target_identity_digest(names, (1.0, 2.0))
    assert base != target_identity_digest(("b@2024", "a@2024"), (2.0, 1.0))
    assert base != target_identity_digest(names, (1.0, 2.5))
    assert len(base) == 64


def test_target_identity_digest_refuses_duplicate_or_non_finite():
    with pytest.raises(TargetSnapshotError):
        target_identity_digest(("a", "a"), (1.0, 2.0))
    with pytest.raises(TargetSnapshotError):
        target_identity_digest(("a", "b"), (1.0, float("nan")))
    with pytest.raises(TargetSnapshotError):
        target_identity_digest(("a", "b"), (1.0,))


def test_signed_relative_error_matches_the_solver_zero_target_convention():
    assert signed_relative_error(90.0, 100.0) == pytest.approx(-0.1)
    assert signed_relative_error(110.0, 100.0) == pytest.approx(0.1)
    # Zero target: the relative form is undefined, so the solver's diagnostics
    # report the signed absolute miss. The snapshot must agree exactly.
    assert signed_relative_error(3.0, 0.0) == pytest.approx(3.0)
    assert signed_relative_error(-3.0, 0.0) == pytest.approx(-3.0)


def test_validate_rejects_reordered_rows_and_wrong_digest():
    seen, observer = _collect(cadence=TargetSnapshotCadence(every=EVERY_EPOCH))
    payload = observer.bind(
        names=("a@2024", "b@2024"), targets=np.array([10.0, 20.0])
    ).snapshot(np.array([9.0, 21.0]), epoch=1, epochs=1, iterate=ITERATE_CURRENT)
    validate_target_snapshot(payload)

    reordered = json.loads(json.dumps(payload))
    reordered["targets"] = list(reversed(reordered["targets"]))
    with pytest.raises(TargetSnapshotError, match="index"):
        validate_target_snapshot(reordered)

    wrong_digest = json.loads(json.dumps(payload))
    wrong_digest["targets_sha256"] = "0" * 64
    with pytest.raises(TargetSnapshotError, match="targets_sha256"):
        validate_target_snapshot(wrong_digest)


def test_validate_rejects_non_finite_and_inconsistent_relative_error():
    _, observer = _collect()
    bound = observer.bind(names=("a@2024",), targets=np.array([10.0]))
    payload = bound.snapshot(
        np.array([9.0]), epoch=1, epochs=1, iterate=ITERATE_CURRENT
    )
    broken = json.loads(json.dumps(payload))
    broken["targets"][0]["relative_error"] = 0.5
    with pytest.raises(TargetSnapshotError, match="relative_error"):
        validate_target_snapshot(broken)

    with pytest.raises(TargetSnapshotError, match="finite"):
        bound.snapshot(
            np.array([float("inf")]), epoch=1, epochs=1, iterate=ITERATE_CURRENT
        )


def test_validate_refuses_record_level_identifiers_in_context():
    _, observer = _collect(context={"household_id": 4})
    bound = observer.bind(names=("a@2024",), targets=np.array([10.0]))
    with pytest.raises(TargetSnapshotError, match="aggregate-only"):
        bound.snapshot(np.array([9.0]), epoch=1, epochs=1, iterate=ITERATE_CURRENT)


def test_validate_refuses_unknown_top_level_keys():
    _, observer = _collect()
    payload = observer.bind(names=("a@2024",), targets=np.array([10.0])).snapshot(
        np.array([9.0]), epoch=1, epochs=1, iterate=ITERATE_CURRENT
    )
    smuggled = json.loads(json.dumps(payload))
    smuggled["household_weights"] = [1.0, 2.0]
    with pytest.raises(TargetSnapshotError, match="unknown"):
        validate_target_snapshot(smuggled)


def test_schema_identity_is_pinned():
    _, observer = _collect()
    payload = observer.bind(names=("a@2024",), targets=np.array([10.0])).snapshot(
        np.array([9.0]), epoch=1, epochs=1, iterate=ITERATE_CURRENT
    )
    assert payload["schema"] == TARGET_SNAPSHOT_SCHEMA
    assert payload["schema_version"] == TARGET_SNAPSHOT_SCHEMA_VERSION
    assert payload["iterate"] in {
        ITERATE_CURRENT,
        ITERATE_BEST_RETAINED,
        ITERATE_SELECTED,
    }


# --------------------------------------------------------------------------
# Cadence
# --------------------------------------------------------------------------


def test_cadence_every_epoch_emits_every_epoch():
    cadence = TargetSnapshotCadence(every=EVERY_EPOCH)
    assert [cadence.emits(e, 5) for e in range(1, 6)] == [True] * 5


def test_bounded_cadence_emits_first_multiples_and_last():
    cadence = TargetSnapshotCadence(every=4)
    assert [cadence.emits(e, 10) for e in range(1, 11)] == [
        True,
        False,
        False,
        True,
        False,
        False,
        False,
        True,
        False,
        True,
    ]


def test_cadence_rejects_non_positive_every():
    with pytest.raises(ValueError):
        TargetSnapshotCadence(every=0)


# --------------------------------------------------------------------------
# Local store: atomic latest, immutable bounded history
# --------------------------------------------------------------------------


def _payloads(n: int) -> list[dict]:
    _, observer = _collect()
    bound = observer.bind(names=("a@2024",), targets=np.array([10.0]))
    return [
        bound.snapshot(
            np.array([9.0 + i]), epoch=i + 1, epochs=n, iterate=ITERATE_CURRENT
        )
        for i in range(n)
    ]


def test_writer_replaces_latest_atomically_and_never_leaves_partial_json(tmp_path):
    writer = TargetSnapshotWriter(tmp_path)
    for payload in _payloads(3):
        writer(payload)
        text = (tmp_path / LATEST_SNAPSHOT_FILENAME).read_text()
        validate_target_snapshot(json.loads(text))
    assert json.loads((tmp_path / LATEST_SNAPSHOT_FILENAME).read_text())["epoch"] == 3
    # No temporary files survive a completed write.
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [LATEST_SNAPSHOT_FILENAME, "history", "history_index.json"]
    )


def test_writer_history_chunks_are_write_once(tmp_path):
    writer = TargetSnapshotWriter(tmp_path)
    payloads = _payloads(2)
    writer(payloads[0])
    chunk = next((tmp_path / "history").iterdir())
    with pytest.raises(TargetSnapshotError, match="immutable"):
        writer._write_chunk(chunk, payloads[0])


def test_writer_bounds_retained_history_and_records_what_it_dropped(tmp_path):
    writer = TargetSnapshotWriter(tmp_path, history_limit=2)
    for payload in _payloads(5):
        writer(payload)
    chunks = sorted(p.name for p in (tmp_path / "history").iterdir())
    assert len(chunks) == 2
    index = json.loads((tmp_path / "history_index.json").read_text())
    assert index["retained"] == chunks
    assert index["dropped"] == 3
    assert index["last_sequence"] == 5
    # The retained chunks are the most recent ones and still validate.
    for name in chunks:
        validate_target_snapshot(json.loads((tmp_path / "history" / name).read_text()))


# --------------------------------------------------------------------------
# Solver seam
# --------------------------------------------------------------------------


def test_observer_off_is_the_default_and_changes_nothing():
    baseline = calibrate(_frame(), _targets(), epochs=20, seed=0)
    seen, observer = _collect(cadence=TargetSnapshotCadence(every=EVERY_EPOCH))
    observed = calibrate(
        _frame(), _targets(), epochs=20, seed=0, target_snapshots=observer
    )
    np.testing.assert_array_equal(
        baseline.weights,
        observed.weights,
    )
    np.testing.assert_array_equal(baseline.loss_trajectory, observed.loss_trajectory)
    assert seen, "an enabled observer must actually receive snapshots"


def test_every_epoch_emits_one_snapshot_per_epoch_plus_the_selected_one():
    seen, observer = _collect(cadence=TargetSnapshotCadence(every=EVERY_EPOCH))
    calibrate(_frame(), _targets(), epochs=6, seed=0, target_snapshots=observer)
    epochs = [s["epoch"] for s in seen if s["iterate"] != ITERATE_SELECTED]
    assert epochs == [1, 2, 3, 4, 5, 6]
    selected = [s for s in seen if s["iterate"] == ITERATE_SELECTED]
    assert len(selected) == 1
    for snapshot in seen:
        validate_target_snapshot(snapshot)


def test_bounded_cadence_emits_fewer_snapshots_than_every_epoch():
    dense, dense_observer = _collect(cadence=TargetSnapshotCadence(every=EVERY_EPOCH))
    calibrate(_frame(), _targets(), epochs=40, seed=0, target_snapshots=dense_observer)
    sparse, sparse_observer = _collect(cadence=TargetSnapshotCadence(every=10))
    calibrate(_frame(), _targets(), epochs=40, seed=0, target_snapshots=sparse_observer)
    assert len(sparse) < len(dense)
    assert [s["epoch"] for s in sparse if s["iterate"] != ITERATE_SELECTED] == [
        1,
        10,
        20,
        30,
        40,
    ]


def test_snapshot_values_are_the_real_iterate_estimates():
    seen, observer = _collect(cadence=TargetSnapshotCadence(every=EVERY_EPOCH))
    result = calibrate(
        _frame(), _targets(), epochs=30, seed=0, target_snapshots=observer
    )
    selected = [s for s in seen if s["iterate"] == ITERATE_SELECTED][-1]
    by_name = {d.name: d for d in result.diagnostics}
    for row in selected["targets"]:
        diagnostic = by_name[row["name"]]
        assert row["estimate"] == pytest.approx(diagnostic.final_estimate, rel=1e-9)
        assert row["target"] == pytest.approx(diagnostic.target, rel=1e-9)
        assert row["relative_error"] == pytest.approx(
            diagnostic.relative_error, rel=1e-9
        )


def test_current_iterates_are_never_labelled_best_when_they_are_not():
    seen, observer = _collect(cadence=TargetSnapshotCadence(every=EVERY_EPOCH))
    calibrate(_frame(), _targets(), epochs=30, seed=0, target_snapshots=observer)
    epoch_snapshots = [s for s in seen if s["iterate"] != ITERATE_SELECTED]
    best_so_far = math.inf
    for snapshot in epoch_snapshots:
        loss = snapshot["loss"]
        is_incumbent = loss < best_so_far
        best_so_far = min(best_so_far, loss)
        expected = ITERATE_BEST_RETAINED if is_incumbent else ITERATE_CURRENT
        assert snapshot["iterate"] == expected, (
            f"epoch {snapshot['epoch']} labelled {snapshot['iterate']}"
        )
        assert snapshot["best_retained"]["available"] is True
    assert any(s["iterate"] == ITERATE_BEST_RETAINED for s in epoch_snapshots)


def test_a_run_that_retains_no_best_says_so_instead_of_claiming_one():
    seen, observer = _collect(cadence=TargetSnapshotCadence(every=EVERY_EPOCH))
    calibrate(
        _frame(),
        _targets(),
        epochs=10,
        seed=0,
        mass=CONSERVE_MASS,
        target_snapshots=observer,
    )
    epoch_snapshots = [s for s in seen if s["iterate"] != ITERATE_SELECTED]
    assert epoch_snapshots
    assert all(s["iterate"] == ITERATE_CURRENT for s in epoch_snapshots)
    assert all(s["best_retained"]["available"] is False for s in epoch_snapshots)


def test_multi_phase_and_search_identity_is_unambiguous():
    seen, observer = _collect(cadence=TargetSnapshotCadence(every=5))
    calibrate_l0_refit(
        _frame(),
        _targets(),
        epochs=10,
        refit_epochs=10,
        target_records=2,
        budget_iters=2,
        seed=0,
        target_snapshots=observer,
    )
    phases = {s["phase"] for s in seen}
    assert {"l0_selection", "post_l0_refit"} <= phases
    searched = [s for s in seen if s["search"] is not None]
    assert searched, "budget-search probes must carry their search identity"
    assert {s["search"]["budget_iteration"] for s in searched} >= {1, 2}
    # (phase, search iteration, epoch, iterate) must identify a snapshot.
    keys = [
        (
            s["phase"],
            None if s["search"] is None else s["search"]["budget_iteration"],
            s["epoch"],
            s["iterate"],
            s["sequence"],
        )
        for s in seen
    ]
    assert len({k[:4] for k in keys}) == len(keys)
    assert [k[4] for k in keys] == sorted(k[4] for k in keys)
    for snapshot in seen:
        validate_target_snapshot(snapshot)


def test_sink_exceptions_follow_the_progress_callback_contract():
    def boom(_payload):
        raise RuntimeError("sink down")

    observer = TargetSnapshotObserver(
        sink=boom, run_id="run-1", cadence=TargetSnapshotCadence(every=EVERY_EPOCH)
    )
    with pytest.raises(RuntimeError, match="sink down"):
        calibrate(_frame(), _targets(), epochs=4, seed=0, target_snapshots=observer)


def test_sink_mutation_cannot_reach_the_next_snapshot():
    seen: list[dict] = []

    def mutating(payload):
        payload["targets"].clear()
        payload["run_id"] = "mutated"
        seen.append(json.loads(json.dumps(payload)))

    observer = TargetSnapshotObserver(
        sink=mutating,
        run_id="run-1",
        cadence=TargetSnapshotCadence(every=EVERY_EPOCH),
    )
    kept: list[dict] = []
    observer_two = TargetSnapshotObserver(
        sink=kept.append,
        run_id="run-1",
        cadence=TargetSnapshotCadence(every=EVERY_EPOCH),
    )
    mutated_result = calibrate(
        _frame(), _targets(), epochs=5, seed=0, target_snapshots=observer
    )
    clean_result = calibrate(
        _frame(), _targets(), epochs=5, seed=0, target_snapshots=observer_two
    )
    np.testing.assert_array_equal(
        mutated_result.weights,
        clean_result.weights,
    )
    assert all(len(s["targets"]) == 0 for s in seen)
    assert all(len(s["targets"]) == 2 for s in kept)


def test_snapshots_carry_no_record_level_vectors(tmp_path: Path):
    seen, observer = _collect(cadence=TargetSnapshotCadence(every=EVERY_EPOCH))
    result = calibrate(
        _frame(), _targets(), epochs=5, seed=0, target_snapshots=observer
    )
    n_records = int(result.weights.shape[0])
    for snapshot in seen:
        text = json.dumps(snapshot)
        assert "household_id" not in text
        assert "household_weight" not in text
        for value in snapshot.values():
            assert not (
                isinstance(value, list)
                and len(value) == n_records
                and value
                and isinstance(value[0], float)
            )
