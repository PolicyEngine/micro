"""Invented numeric artifact/solver checks; no source or release admission."""

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import test_us_national_age_counts as fixture
import test_us_survey_age_artifact as age_fixture

from microcosm.build.us_runtime import graph_survey_calibration as stage
from microcosm.graph import ArtifactValue, KernelContext
from microcosm.graph.canonical import canonical_json
from microcosm.graph.kernel import Numeric, NumericScope
from microcosm.graph.keys import opaque_artifact_key


def numeric_document():
    return {
        "protocol": stage.BOUNDS_PROTOCOL,
        "budget_sha256": "a" * 64,
        "population": "invented",
        "household_ids": list(fixture.HOUSEHOLD_IDS),
        "group_indices": [0, 0, 1, 1, 2],
        "group_upper_hex": [float(v).hex() for v in (800, 800, 0)],
        "row_upper_hex": [float(v).hex() for v in (1600, 1600, 1600, 1600, 0)],
        "incoming_hex": [float(v).hex() for v in (100, 100, 100, 100, 0)],
    }


def artifact(payload, type_, name):
    producer = "b" * 64
    return ArtifactValue(
        payload,
        type_,
        opaque_artifact_key(producer, name),
        producer,
        NumericScope(Numeric.BITWISE),
    )


def context():
    node = stage.survey_age_calibration_node(
        fixture.fixture_registry(),
        base="invented",
        budget_node="budget",
        count_node="counts",
        epochs=12,
        learning_rate=0.1,
    )
    count_payload = age_fixture.measured()[2].artifacts["counts"]
    return KernelContext(
        node=node,
        tables={},
        weights={},
        strata=pd.Series([], dtype=object),
        params=node.params,
        rng=np.random.default_rng(0),
        artifacts={
            "bounds": artifact(
                canonical_json(numeric_document()), stage.BOUNDS_TYPE, "numeric_bounds"
            ),
            "counts": artifact(count_payload, stage.ages.COUNTS_TYPE, "counts"),
        },
    )


def test_real_solver_retains_zero_rows_and_returns_weights_only():
    value = context()
    output = stage.SurveyAgeCalibrationKernel().run(value)
    assert output.frame is None and not output.columns
    weights = output.weights.values
    assert len(weights) == 5 and weights[-1] == 0
    assert np.all(weights[:-1] > 0)
    assert weights.tobytes() != np.array([100, 100, 100, 100, 0], dtype=float).tobytes()
    bounds = stage.decode_numeric_survey_bounds(value.artifacts["bounds"].payload)
    stage.check_numeric_survey_weights(bounds, weights)
    diagnostics = json.loads(output.artifacts["diagnostics"])
    assert diagnostics and output.receipt["fixed_zero_rows"] == 1
    assert output.receipt["release_eligible"] is False
    assert output.receipt["source_admission"] == "required_from_country_runner"


@pytest.mark.parametrize(
    "change",
    [
        {"protocol": "wrong"},
        {"budget_sha256": "z" * 64},
        {"population": ""},
        {"household_ids": [7, 15, 22, 40, True]},
        {"household_ids": [7, 15, 22, 40, 40]},
        {"household_ids": [90, 40, 22, 15, 7]},
        {"household_ids": [7, 15, 22, 40, 2**63]},
        {"group_indices": [0, 0, 1, 1, True]},
        {"group_indices": [0, 0, 1, 1, 3]},
        {"group_upper_hex": ["nan", "0x1.0p+10", "0x0.0p+0"]},
        {"group_upper_hex": ["0x1p+999999", "0x1.0p+10", "0x0.0p+0"]},
        {"row_upper_hex": [float(1).hex()] * 5},
        {"incoming_hex": [float(0).hex()] * 5},
        {"incoming_hex": [float(900).hex()] * 5},
    ],
)
def test_numeric_decoder_refuses_malformed_or_infeasible_bounds(change):
    with pytest.raises(ValueError):
        stage.decode_numeric_survey_bounds(
            canonical_json({**numeric_document(), **change})
        )


def test_numeric_values_are_defensive_and_noncanonical_bytes_refuse():
    raw = canonical_json(numeric_document())
    first = stage.decode_numeric_survey_bounds(raw)
    first.incoming[0] = 999
    first.row_upper[0] = 0
    second = stage.decode_numeric_survey_bounds(raw)
    assert second.incoming[0] == 100 and second.row_upper[0] == 1600
    with pytest.raises(ValueError, match="CANONICAL"):
        stage.decode_numeric_survey_bounds(b" " + raw)
    with pytest.raises(ValueError):
        stage.decode_numeric_survey_bounds(raw[:-1])


@pytest.mark.parametrize("change", ["ordered_ids", "population", "edge", "params"])
def test_kernel_refuses_mismatched_inputs_before_solver(monkeypatch, change):
    value = context()
    if change == "ordered_ids":
        document = {**numeric_document(), "household_ids": [8, 15, 22, 40, 90]}
        value = replace(
            value,
            artifacts={
                **value.artifacts,
                "bounds": artifact(
                    canonical_json(document), stage.BOUNDS_TYPE, "numeric_bounds"
                ),
            },
        )
    elif change == "population":
        document = {**numeric_document(), "population": "other"}
        value = replace(
            value,
            artifacts={
                **value.artifacts,
                "bounds": artifact(
                    canonical_json(document), stage.BOUNDS_TYPE, "numeric_bounds"
                ),
            },
        )
    elif change == "edge":
        value = replace(
            value,
            artifacts={
                **value.artifacts,
                "bounds": replace(value.artifacts["bounds"], key="c" * 64),
            },
        )
    else:
        value = replace(value, params={**value.params, "grouped_preserve_zeros": False})
    calls = []
    monkeypatch.setattr(stage, "calibrate", lambda *a, **k: calls.append(True))
    with pytest.raises(ValueError):
        stage.SurveyAgeCalibrationKernel().run(value)
    assert not calls


@pytest.mark.parametrize("change", ["weights", "ids"])
def test_late_diagnostics_mutation_is_refused(monkeypatch, change):
    original = stage.diagnostics_payload

    def mutate(result, **kwargs):
        payload = original(result, **kwargs)
        if change == "ids":
            result.frame.table("household").loc[0, "household_id"] = 999
        else:
            object.__setattr__(
                result.frame.weights_for("household"), "values", np.zeros(5)
            )
        return payload

    monkeypatch.setattr(stage, "diagnostics_payload", mutate)
    with pytest.raises(ValueError):
        stage.SurveyAgeCalibrationKernel().run(context())


def test_projection_can_preserve_the_full_signed_id_domain():
    document = {**numeric_document(), "household_ids": [-(2**63), -1, 0, 1, 2**63 - 1]}
    assert stage.decode_numeric_survey_bounds(
        canonical_json(document)
    ).grouped.household_ids == tuple(document["household_ids"])
