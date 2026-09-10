"""Validate and merge the two PUF55 raw chains before one finalization.

This is a values-only boundary. The host must freshly qualify the recipient
matrices against its actual financial run, authenticate every typed graph edge,
and verify donor/model ownership before using the result. Caller bytes and this
receipt issue no source, Population, donor, fit or release authority. No model
pickle is loaded, no fit is performed, and no output column is attached here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from microcosm.fit import model_input

from . import full_puf_enrichment as full
from . import support_provenance as provenance

PROTOCOL = "microcosm.us.puf55-route-raw-merge.v1"
PROFILES = (full.PUF55_SURVEY_SS, full.PUF55_SURVEY_SS_NO_TOTAL)


def _require(condition, reason):
    if not condition:
        raise ValueError("PUF55_ROUTE_" + reason)


@dataclass(frozen=True)
class Puf55RouteDraws:
    """Descriptive typed-chain bytes, never an authenticated producer capsule."""

    profile: full.PufOutputProfile
    matrix: bytes
    matrix_producer_key: str
    raw_draws: tuple[tuple[str, bytes], ...]
    apply_state: bytes
    training_state: bytes


def _route_snapshot(route):
    _require(type(route) is Puf55RouteDraws, "INPUT_TYPE")
    # Frozen dataclasses can still be changed with object.__setattr__. Read each
    # field once and use only these immutable retained values during decoding.
    result = (
        route.profile,
        route.matrix,
        route.matrix_producer_key,
        route.raw_draws,
        route.apply_state,
        route.training_state,
    )
    profile, matrix, key, raw, apply_state, training_state = result
    _require(type(profile) is full.PufOutputProfile and profile in PROFILES, "PROFILE")
    _require(
        all(type(value) is bytes for value in (matrix, apply_state, training_state))
        and type(key) is str
        and full.codec._hash(key),
        "ARTIFACT_TYPES",
    )
    _require(
        type(raw) is tuple
        and all(
            type(pair) is tuple
            and len(pair) == 2
            and type(pair[0]) is str
            and type(pair[1]) is bytes
            for pair in raw
        )
        and tuple(pair[0] for pair in raw) == profile.targets,
        "RAW_ROSTER",
    )
    return result


def _receiving_axis(frame):
    table = frame.table("tax_unit")
    column = provenance.support_clone_index_column("tax_unit")
    _require(
        table.columns.is_unique
        and table.index.is_unique
        and column in table
        and table[column].dtype == np.dtype("int64")
        and bool(table[column].isin((0, 1)).all()),
        "CLONE_AXIS",
    )
    all_ids = full._ids(table.tax_unit_id, "route_receiving")
    _require(len(set(all_ids.tolist())) == len(all_ids), "RECEIVING_IDS")
    mask = table[column].eq(1).to_numpy()
    ids = all_ids[mask]
    _require(len(ids) > 0, "NO_RECIPIENTS")
    return ids, table.index[mask].copy()


def merge_puf55_route_draws(frame, *, recipient_matrices, route_draws, seed):
    """Return all 55 raw targets in complete receiving pandas row order.

    ``recipient_matrices`` is the exact immutable matrix roster freshly derived
    by the host's authenticated recipient qualifier. Empty routes are omitted
    in nine/eight order. This function checks values, not that upstream duty.
    Finalize the complete returned table once, after checking both donor/model
    bindings; never finalize subsets or attach a route over another route.
    """
    _require(type(seed) is int and seed >= 0, "SEED")
    _require(
        type(recipient_matrices) is tuple
        and all(
            type(pair) is tuple
            and len(pair) == 2
            and type(pair[0]) is str
            and type(pair[1]) is bytes
            for pair in recipient_matrices
        ),
        "MATRIX_ROSTER",
    )
    _require(type(route_draws) is tuple and 1 <= len(route_draws) <= 2, "ROUTE_ROSTER")
    retained = tuple(_route_snapshot(route) for route in route_draws)
    names = tuple(values[0].value for values in retained)
    _require(
        names == tuple(p.value for p in PROFILES if p.value in names)
        and tuple(name for name, _ in recipient_matrices) == names,
        "ROUTE_ORDER",
    )
    ids, row_index = _receiving_axis(frame)
    tables, seen, evidence, raw_seals = [], set(), [], []
    for values, (_, expected_matrix) in zip(retained, recipient_matrices, strict=True):
        profile, matrix, key, raw, apply_state, training_state = values
        _require(matrix == expected_matrix, "RECIPIENT_MATRIX_CHANGED")
        prepared = model_input.decode_recipient_matrix(matrix)
        route_ids = tuple(prepared.entity_ids.tolist())
        _require(
            prepared.entity == "tax_unit"
            and tuple(prepared.features.columns) == profile.predictors
            and prepared.features.index.name == "tax_unit_id",
            "MATRIX_PROFILE",
        )
        _require(not seen.intersection(route_ids), "OVERLAPPING_IDS")
        seen.update(route_ids)
        decoded = full.decode_full_puf_draws(
            matrix=matrix,
            matrix_producer_key=key,
            raw_draws=dict(raw),
            apply_state=apply_state,
            training_state=training_state,
            seed=seed,
            profile=profile,
        )
        # Check the detached decoder result against the immutable input bytes;
        # comparing two mutable returned tables would not anchor its values.
        _require(
            type(decoded) is pd.DataFrame
            and tuple(decoded.columns) == profile.targets
            and decoded.index.equals(pd.Index(route_ids, name="tax_unit_id"))
            and all(dtype == np.dtype("float64") for dtype in decoded.dtypes)
            and all(
                full.codec.encode_raw_target(
                    decoded[target].to_numpy(), target=target, index=decoded.index
                )
                == payload
                for target, payload in raw
            ),
            "DECODED_RAW_CHANGED",
        )
        tables.append(decoded.copy(deep=True))
        raw_seals.append((route_ids, raw))
        evidence.append(
            {
                "profile": profile.value,
                "rows": len(route_ids),
                "matrix_sha256": full.codec.sha(matrix),
                "matrix_producer_key": key,
                "apply_state_sha256": full.codec.sha(apply_state),
                "training_state_sha256": full.codec.sha(training_state),
                "raw_target_sha256": {target: full.codec.sha(p) for target, p in raw},
            }
        )
    _require(seen == set(ids.tolist()), "INCOMPLETE_RECIPIENT_UNION")
    combined = (
        pd.concat(tables, axis=0).loc[ids.tolist(), list(PROFILES[0].targets)].copy()
    )
    # The IDs above establish the one explicit bridge to the existing pandas
    # row index required by the maintained whole-cohort finalizer.
    combined.index = row_index.copy()
    fresh_ids, fresh_index = _receiving_axis(frame)
    _require(
        np.array_equal(ids, fresh_ids) and row_index.identical(fresh_index),
        "RECEIVING_AXIS_CHANGED",
    )
    receipt = full.codec.encode_json(
        {
            "protocol": PROTOCOL,
            "routes": evidence,
            "recipient_rows": len(ids),
            "target_order": list(PROFILES[0].targets),
            "ordered_recipient_ids_sha256": full.codec.sha(ids.tobytes()),
            "merge": "disjoint complete clone-one union in receiving order",
            "finalization_performed": False,
            "donor_model_binding_verified_here": False,
            "source_admission_issued": False,
            "population_admission_issued": False,
            "release_eligible": False,
        }
    )
    _require(len(receipt) <= 128 * 1024, "RECEIPT_SIZE")
    # A later route decoder could have changed an earlier detached table. Check
    # every final route slice against its original bytes after all decoding.
    positions = {value: position for position, value in enumerate(ids.tolist())}
    _require(
        tuple(combined.columns) == PROFILES[0].targets
        and combined.index.identical(row_index)
        and all(dtype == np.dtype("float64") for dtype in combined.dtypes)
        and all(
            full.codec.encode_raw_target(
                combined[target].to_numpy()[[positions[value] for value in route_ids]],
                target=target,
                index=pd.Index(route_ids, name="tax_unit_id"),
            )
            == payload
            for route_ids, raw in raw_seals
            for target, payload in raw
        ),
        "MERGED_RAW_CHANGED",
    )
    return combined, receipt
