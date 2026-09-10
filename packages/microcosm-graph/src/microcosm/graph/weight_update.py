"""Ordered entity-axis evidence for explicit same-kind weight updates."""

from collections.abc import Sequence
from numbers import Integral

from .canonical import canonical_json, sha256_domain


def weight_update_receipt(entity_ids: Sequence[int | str]) -> dict[str, object]:
    """Bind positional replacement weights to unique, ordered integer/string IDs.

    Place this result under ``KernelResult.receipt['weight_update']``. The
    executor recomputes it against the actual incumbent axis, including replay.
    """
    ids = []
    for value in entity_ids:
        if isinstance(value, Integral) and not isinstance(value, bool):
            ids.append(int(value))
        elif isinstance(value, str) and value:
            ids.append(value)
        else:
            raise ValueError("Weight update IDs must be integers or nonempty strings.")
    if len(set(ids)) != len(ids):
        raise ValueError("Weight update IDs must be unique.")
    return {
        "schema": "microcosm.graph.weight-update-axis.v1",
        "count": len(ids),
        "entity_ids_sha256": sha256_domain("weight-update-axis", canonical_json(ids)),
    }
