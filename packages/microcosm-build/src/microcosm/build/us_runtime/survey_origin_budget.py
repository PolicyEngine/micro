"""Source-qualified, sampling-aware budgets for the complete first survey clone.

Original publisher d is never replaced. The sampling reference b=d/p and
incoming a=s*b are different quantities. These development coefficients are
provisional; this module grants neither graph execution nor release authority.
Decoded bytes cannot issue a budget or a weight-only successor.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
import weakref
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from types import FunctionType

import numpy as np
import pandas as pd

from microcosm.calibrate import group_bounds
from microcosm.frame import Frame, WeightKind
from microcosm.graph import (
    ArtifactType,
    KernelResult,
    Node,
    StructuralDelta,
    WeightTransition,
)
from microcosm.graph.population import (
    Population,
    _mass_record,
    _storage_parts,
    storage_equal,
)

from . import graph_combined_clone as clone
from . import graph_survey_population as graph
from . import survey_population_preparation as source
from .graph_sources import frame_column_declarations
from .support_provenance import support_clone_index_column, support_source_id_column

BUDGET_PROTOCOL = "microcosm.us.sampling-origin-budget.v1"
SUCCESSOR_PROTOCOL = "microcosm.us.sampling-origin-weight-only-successor.v1"
BUDGET_TYPE = ArtifactType("microcosm.us.sampling_origin_budget", 1)
SUCCESSOR_TYPE = ArtifactType("microcosm.us.sampling_origin_weight_only_successor", 1)
MAX_PAYLOAD_BYTES = 64 * 1024**2
MAX_GROUPS = 1_000_000
MAX_SCALAR_CHARS = 4096
PRESCRIPTION = (
    "development-provisional-8b-4a-v1",
    "allocation=float(exact d*s/p)",
    "reference=float(exact d/p)",
    "bounds=min(8.0*reference,4.0*actual_incoming)",
)
_ISSUED = {}


class SurveyOriginBudgetError(ValueError):
    """Static refusal without source observations or identifiers."""


def _require(condition, reason):
    if not condition:
        raise SurveyOriginBudgetError(reason)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _json(value):
    return graph._bounded_json(value, MAX_PAYLOAD_BYTES)


def _pair(value):
    _require(type(value) is Fraction, "EXACT_FRACTION_REQUIRED")
    _require(
        value.numerator.bit_length() <= 128 and value.denominator.bit_length() <= 128,
        "FRACTION_BOUND",
    )
    return [value.numerator, value.denominator]


def _reference(d, p, s, actual_incoming):
    """Pure exact arithmetic, not source authority; no float-product shortcut."""
    for value in (d, p, s):
        _pair(value)
    _require(
        d >= 0 and 0 < p <= 1 and s in (Fraction(1), Fraction(1, 2)), "REFERENCE_DOMAIN"
    )
    _require(type(actual_incoming) is float, "INCOMING_FLOAT64_REQUIRED")
    b, a = d / p, d * s / p
    expected_a, reference = float(a), float(b)
    _require(
        math.isfinite(actual_incoming)
        and actual_incoming.hex() == expected_a.hex()
        and math.isfinite(reference),
        "ALLOCATION_OPERATION_ORDER",
    )
    design_bound, incoming_bound = 8.0 * reference, 4.0 * actual_incoming
    _require(
        all(math.isfinite(v) and v >= 0 for v in (design_bound, incoming_bound)),
        "REFERENCE_OVERFLOW",
    )
    upper = min(design_bound, incoming_bound)
    _require(upper == incoming_bound, "CURRENT_SHARE_BOUND_RELATION")
    return {
        "d": _pair(d),
        "p": _pair(p),
        "s": _pair(s),
        "b": _pair(b),
        "a": _pair(a),
        "original_float64_hex": float(d).hex(),
        "reference_float64_hex": reference.hex(),
        "actual_incoming_float64_hex": actual_incoming.hex(),
        "design_bound_float64_hex": design_bound.hex(),
        "incoming_bound_float64_hex": incoming_bound.hex(),
        "upper_float64_hex": upper.hex(),
    }


def _modules():
    return (
        sys.modules[__name__],
        graph,
        clone,
        group_bounds,
        sys.modules[Population.__module__],
        sys.modules[Frame.__module__],
        sys.modules[frame_column_declarations.__module__],
        sys.modules[support_source_id_column.__module__],
        sys.modules[clone.clone_us_frame_for_puf_support.__module__],
    )


def _live():
    result = {}
    for module in _modules():
        for name, value in vars(module).items():
            if isinstance(value, FunctionType):
                result[module.__name__, name] = source._function_seal(value)
            elif isinstance(value, type) and value.__module__ == module.__name__:
                result[module.__name__, name] = value
                for method, function in vars(value).items():
                    if isinstance(function, (staticmethod, classmethod)):
                        function = function.__func__
                    if isinstance(function, property):
                        function = function.fget
                    if isinstance(function, FunctionType):
                        result[module.__name__, name, method] = source._function_seal(
                            function
                        )
    result["contract"] = (
        BUDGET_PROTOCOL,
        SUCCESSOR_PROTOCOL,
        (BUDGET_TYPE.name, BUDGET_TYPE.schema_version),
        (SUCCESSOR_TYPE.name, SUCCESSOR_TYPE.schema_version),
        MAX_PAYLOAD_BYTES,
        MAX_GROUPS,
        MAX_SCALAR_CHARS,
        PRESCRIPTION,
        np.__version__,
        np.ndarray,
        np.float64,
    )
    return result


def _code_bytes():
    return {m.__name__: _sha(Path(m.__file__).read_bytes()) for m in _modules()}


def _producer():
    _require(_live() == _LIVE and _code_bytes() == _BYTES, "PRODUCER_CHANGED")
    return _BYTES


def _population_identity(population):
    _require(type(population) is Population, "LIVE_POPULATION_REQUIRED")
    return (
        source._frame_identity(population.frame),
        _physical_nonweight_identity(population.frame),
        population.version,
        tuple(sorted(population.owners.items())),
        tuple(population.weight_kind.items()),
        _json([asdict(record) for record in population.mass_ledger]),
        tuple(
            (e, str(v.dtype), v.shape, v.tobytes())
            for e, v in population.design_weights.items()
        ),
    )


def _physical_nonweight_identity(frame):
    """Detach actual storage, including masked numeric slots, one column at a time.

    Axis/schema/dtype identity is bound separately by the full Frame identity.
    This is an in-process population seal, not a cache canonicalization boundary.
    """
    digest = hashlib.sha256()
    for series in (
        *(
            frame.table(entity)[column]
            for entity in frame.entities
            for column in frame.table(entity)
        ),
        frame.strata,
    ):
        selected = np.ones(len(series), dtype=np.bool_)
        for part in _storage_parts(series, selected):
            digest.update(len(part).to_bytes(8, "little"))
            digest.update(part)
    return digest.hexdigest()


def _initial(view, allocated, expanded):
    _require(
        type(allocated) is Population and type(expanded) is Population,
        "LIVE_POPULATION_REQUIRED",
    )
    instructions = graph.allocation_instructions(
        view.selection_plan, view.receipt["origins"]["households"]
    )
    _require(0 < len(instructions) <= MAX_GROUPS, "GROUP_COUNT_BOUND")
    design = view.frame.weights_for("household").values.copy()
    _weights, _context, allocation, receipt, expected = graph._allocation_output(
        view.frame, view.context, instructions, _sha(view.payload)
    )
    columns = frame_column_declarations(view.frame)
    nodes = graph.survey_population_nodes(
        columns,
        preparation_sha256=_sha(view.payload),
        fraction=view.selection_plan.fraction,
        seed=view.selection_plan.seed,
    )
    clone_nodes = clone.us_combined_survey_clone_nodes(
        columns, base=graph.ALLOCATION_NODE, source_channels=("acs", "asec")
    )
    graph._same_frame(expected, allocated.frame)
    copied_design = graph._verify_cloned_frame(expected, expanded.frame, design)
    graph._check_design_anchors(allocated, design)
    graph._check_design_anchors(expanded, copied_design)
    allocation_ledger = (
        _mass_record(
            view.frame, expected, nodes[1], KernelResult(receipt=receipt), "declared"
        ),
    )
    cells = tuple((e, str(c)) for e in view.frame.entities for c in view.frame.table(e))
    graph._check_population_state(
        allocated,
        version=graph.ALLOCATION_NODE,
        owners=dict.fromkeys(cells, graph.ALLOCATION_NODE),
        kind=WeightKind.IMPORTANCE,
        ledger=allocation_ledger,
    )
    owners = dict.fromkeys(cells, clone.COMBINED_CLONE_NODE)
    owners.update(
        {
            (o.entity, o.column): clone.COMBINED_CLONE_CLAIM_NODE
            for o in clone_nodes[1].outputs
        }
    )
    graph._check_population_state(
        expanded,
        version=clone.COMBINED_CLONE_NODE,
        owners=owners,
        kind=WeightKind.IMPORTANCE,
        ledger=(
            *allocation_ledger,
            _mass_record(
                expected, expanded.frame, clone_nodes[0], KernelResult(), "conserve"
            ),
        ),
    )
    return instructions, allocation


def _document(view, allocated, expanded, instructions, allocation, producer):
    before, after = (
        allocated.frame.table("household"),
        expanded.frame.table("household"),
    )
    source_column = support_source_id_column("household")
    role_column = support_clone_index_column("household")
    positions = {int(value): i for i, value in enumerate(before[source_column])}
    _require(len(positions) == len(instructions), "ROOT_SOURCE_ID_COLLISION")
    members = [[] for _ in instructions]
    ids, groups = [], []
    for row in after[["household_id", source_column, role_column]].itertuples(
        index=False, name=None
    ):
        hh_id, source_id, role = (int(value) for value in row)
        _require(source_id in positions and role in (0, 1), "CLONE_ORIGIN_ROLE")
        group = positions[source_id]
        members[group].append((hh_id, role))
        ids.append(hh_id)
        groups.append(group)
    _require(
        len(ids) == 2 * len(instructions) and len(set(ids)) == len(ids),
        "CLONE_CARDINALITY",
    )
    incoming = allocated.frame.weights_for("household").values
    clone_weights = expanded.frame.weights_for("household").values
    by_id = {value: i for i, value in enumerate(ids)}
    bounds = []
    selected_by_key = {row.key: row for row in view.selection_plan.selected}

    def records():
        for i, (instruction, group_members) in enumerate(
            zip(instructions, members, strict=True)
        ):
            _require(
                len(group_members) == 2 and {m[1] for m in group_members} == {0, 1},
                "COMPLETE_CLONE_ROLES",
            )
            actual = float(incoming[i])
            _require(
                math.fsum(float(clone_weights[by_id[m[0]]]) for m in group_members)
                == actual,
                "CLONE_INCOMING_CONSERVATION",
            )
            reference = _reference(
                instruction.original_anchor,
                instruction.inclusion_probability,
                instruction.share,
                actual,
            )
            bounds.append(float.fromhex(reference["upper_float64_hex"]))
            key = instruction.key
            _require(
                type(key.native_id) is str and len(key.native_id) <= MAX_SCALAR_CHARS,
                "NATIVE_KEY_BOUND",
            )
            yield {
                "source": key.source.value,
                "source_year": key.source_year,
                "survey_year": key.survey_year,
                "raw_native_id": key.native_id,
                "selected_receiving_household_id": instruction.selected_receiving_household_id,
                "combined_household_id": instruction.household_id,
                "statistical_unit": selected_by_key[instruction.key].statistical_unit,
                "original_design_float64_bytes": allocated.design_weights["household"][
                    i : i + 1
                ]
                .tobytes()
                .hex(),
                **reference,
                "members": [[hh_id, role] for hh_id, role in group_members],
                "incoming_clone_float64_bytes": [
                    clone_weights[by_id[hh_id] : by_id[hh_id] + 1].tobytes().hex()
                    for hh_id, _role in group_members
                ],
            }

    header = {
        "protocol": BUDGET_PROTOCOL,
        "prescription": PRESCRIPTION,
        "coefficient_status": "provisional_development_not_scientific_approval",
        "current_share_simplification": "min(8b,4a)=4a; 8b is redundant for current shares",
        "preparation_sha256": _sha(view.payload),
        "source_producer": view.receipt["producer"],
        "source_native": view.receipt["native"],
        "source_catalogues": view.receipt["catalogues"],
        "selection_sha256": _sha(_json(view.receipt["selection"])),
        "allocation_sha256": _sha(allocation),
        "producer": producer,
        "allocated_frame_sha256": source._frame_identity(allocated.frame),
        "clone_frame_sha256": source._frame_identity(expanded.frame),
        "household_ids": ids,
        "group_indices": groups,
        "group_count": len(instructions),
        "release_eligible": False,
    }
    # Stream one bounded origin record at a time; never materialize an unbounded
    # list of origin dictionaries before the transport cap is checked.
    payload = bytearray()

    def append(piece):
        _require(len(piece) <= MAX_PAYLOAD_BYTES - len(payload), "TRANSPORT_LIMIT")
        payload.extend(piece)

    append(b"{")
    keys = sorted((*header, "origins"))
    for index, key in enumerate(keys):
        if index:
            append(b",")
        append(_json(key) + b":")
        if key == "origins":
            append(b"[")
            for position, record in enumerate(records()):
                if position:
                    append(b",")
                append(_json(record))
            append(b"]")
        else:
            append(_json(header[key]))
    append(b"}")
    constraint = group_bounds.GroupedUpperBounds(ids, groups, bounds)
    constraint.check(clone_weights, positive=False)
    return bytes(payload), constraint


@dataclass(frozen=True)
class _BudgetState:
    preparation: object
    preparation_entry: tuple
    initial_view: source.CheckedSurveyPopulationView
    allocated: Population
    expanded: Population
    preparation_payload: bytes
    allocated_identity: tuple
    expanded_identity: tuple


def _preparation_entry(preparation, payload, expected=None):
    """Check retained issuance identity without repeating source-file reads."""
    entry = source._ISSUED.get(id(preparation))
    _require(
        type(preparation) is source.AuthenticatedSurveyPopulationPreparation
        and entry is not None
        and (expected is None or entry is expected)
        and entry[0]() is preparation
        and type(preparation.payload) is bytes
        and preparation.payload == entry[1] == payload,
        "FINAL_PREPARATION_ISSUANCE",
    )
    return entry


def _final_budget_state(state):
    """Seal retained owners after helper/file I/O, with no recursive borrow.

    The owner's pure check still hashes retained Frames. It does not parse or
    reread source files, issue replacement capsules or grant decoded authority.
    """
    _producer()
    entry = _preparation_entry(
        state.preparation, state.preparation_payload, state.preparation_entry
    )
    source._pure_final(entry[2])
    _require(
        _population_identity(state.allocated) == state.allocated_identity
        and _population_identity(state.expanded) == state.expanded_identity,
        "FINAL_POPULATION_SEAL",
    )
    _require(_live() == _LIVE, "FINAL_PRODUCER_SEAL")
    _preparation_entry(
        state.preparation, state.preparation_payload, state.preparation_entry
    )


def _validate_budget(state, payload):
    _producer()
    _require(
        _population_identity(state.allocated) == state.allocated_identity
        and _population_identity(state.expanded) == state.expanded_identity,
        "INITIAL_POPULATION_CHANGED",
    )
    # This private retained view is only a reconstruction input. The single
    # fresh source borrow below must authenticate it after all helper/file I/O.
    view = state.initial_view
    _require(view.payload == state.preparation_payload, "SOURCE_PREPARATION_CHANGED")
    instructions, allocation = _initial(view, state.allocated, state.expanded)
    expected, constraint = _document(
        view, state.allocated, state.expanded, instructions, allocation, _producer()
    )
    _require(expected == payload, "BUDGET_RECONSTRUCTION")
    final = source.AuthenticatedSurveyPopulationPreparation.checked_view(
        state.preparation
    )
    _require(
        final.payload == view.payload
        and final.frame is view.frame
        and final.selection_plan is view.selection_plan,
        "FINAL_SOURCE_SEAL",
    )
    _initial(final, state.allocated, state.expanded)
    return constraint


def _entry(value, cls):
    entry = _ISSUED.get(id(value))
    _require(
        type(value) is cls
        and entry is not None
        and entry[0]() is value
        and type(value.payload) is bytes
        and value.payload == entry[1],
        "UNISSUED_OR_CHANGED",
    )
    return entry


def _issue(cls, payload, state):
    value = object.__new__(cls)
    object.__setattr__(value, "payload", payload)
    identifier = id(value)

    def forget(reference):
        current = _ISSUED.get(identifier)
        if current is not None and current[0] is reference:
            _ISSUED.pop(identifier, None)

    reference = weakref.ref(value, forget)
    _ISSUED[identifier] = (reference, payload, state)
    return value


@dataclass(frozen=True)
class SamplingOriginBudget:
    payload: bytes

    def __post_init__(self):
        raise SurveyOriginBudgetError("NO_PUBLIC_BUDGET_CONSTRUCTOR")

    def checked_view(self):
        entry = _entry(self, SamplingOriginBudget)
        document, digest = json.loads(entry[1]), _sha(entry[1])
        constraint = _validate_budget(entry[2], entry[1])
        result = CheckedSamplingOriginBudget(
            entry[1],
            digest,
            document,
            constraint,
            entry[2].preparation,
            entry[2].allocated,
            entry[2].expanded,
        )
        _final_budget_state(entry[2])
        _require(_entry(self, SamplingOriginBudget) is entry, "FINAL_BUDGET_SEAL")
        return result

    def to_bytes(self):
        return self.checked_view().payload


@dataclass(frozen=True)
class CheckedSamplingOriginBudget:
    """Defensive values and a numerical constraint, not source authority."""

    payload: bytes
    digest: str
    document: dict
    grouped_bounds: group_bounds.GroupedUpperBounds
    preparation: object
    allocated_population: Population
    initial_population: Population


def freeze_survey_origin_budget(
    preparation, *, allocated_population, clone_population, candidate=None
):
    _require(type(candidate) is bytes or candidate is None, "CANDIDATE_TYPE")
    _require(
        candidate is None or len(candidate) <= MAX_PAYLOAD_BYTES, "CANDIDATE_LIMIT"
    )
    _require(
        type(preparation) is source.AuthenticatedSurveyPopulationPreparation,
        "ISSUED_PREPARATION_REQUIRED",
    )
    producer = _producer()
    view = source.AuthenticatedSurveyPopulationPreparation.checked_view(preparation)
    preparation_entry = _preparation_entry(preparation, view.payload)
    instructions, allocation = _initial(view, allocated_population, clone_population)
    state = _BudgetState(
        preparation,
        preparation_entry,
        view,
        allocated_population,
        clone_population,
        view.payload,
        _population_identity(allocated_population),
        _population_identity(clone_population),
    )
    payload, _constraint = _document(
        view, allocated_population, clone_population, instructions, allocation, producer
    )
    final = source.AuthenticatedSurveyPopulationPreparation.checked_view(preparation)
    _require(
        final.payload == view.payload and final.frame is view.frame, "FINAL_SOURCE_SEAL"
    )
    _initial(final, allocated_population, clone_population)
    _require(candidate is None or candidate == payload, "CANDIDATE_RECONSTRUCTION")
    result = _issue(SamplingOriginBudget, payload, state)
    entry = _entry(result, SamplingOriginBudget)
    _final_budget_state(state)
    _require(_entry(result, SamplingOriginBudget) is entry, "FINAL_BUDGET_SEAL")
    return result


def verify_survey_origin_budget(budget):
    _require(type(budget) is SamplingOriginBudget, "BUDGET_TYPE")
    budget.checked_view()
    return budget


def _same_nonweight(before, after):
    _require(
        before.schema == after.schema
        and before.entities == after.entities
        and before.links == after.links == ()
        and before.metadata == after.metadata
        and before.mass_log == after.mass_log
        and before.weighted_entities == after.weighted_entities == ("household",),
        "SUCCESSOR_NONWEIGHT_CONTEXT",
    )
    try:
        for entity in before.entities:
            pd.testing.assert_frame_equal(
                before.table(entity),
                after.table(entity),
                check_exact=True,
                check_flags=True,
            )
            for column in before.table(entity):
                _require(
                    storage_equal(
                        before.table(entity)[column], after.table(entity)[column]
                    ),
                    "SUCCESSOR_NONWEIGHT_STORAGE",
                )
        pd.testing.assert_series_equal(before.strata, after.strata, check_exact=True)
        _require(
            storage_equal(before.strata, after.strata), "SUCCESSOR_NONWEIGHT_STORAGE"
        )
    except (AssertionError, ValueError, TypeError):
        raise SurveyOriginBudgetError("SUCCESSOR_NONWEIGHT_TABLE") from None


@dataclass(frozen=True)
class _SuccessorState:
    budget: SamplingOriginBudget
    budget_entry: tuple
    previous: Population
    current: Population
    previous_binding: object
    previous_identity: tuple
    current_identity: tuple


def _successor_document(state, budget_view):
    previous, current = state.previous, state.current
    _require(
        type(previous) is Population and type(current) is Population,
        "LIVE_POPULATION_REQUIRED",
    )
    initial = _entry(state.budget, SamplingOriginBudget)[2].expanded
    _require(state.previous_binding is None, "UNSUPPORTED_REFINEMENT")
    _require(previous is initial, "INITIAL_PREVIOUS_REQUIRED")
    _same_nonweight(initial.frame, previous.frame)
    _same_nonweight(initial.frame, current.frame)
    graph._check_design_anchors(previous, initial.design_weights["household"])
    graph._check_design_anchors(current, initial.design_weights["household"])
    _require(
        current.frame.weights_for("household").kind is WeightKind.CALIBRATED
        and current.version != previous.version,
        "SUCCESSOR_CALIBRATED_VERSION",
    )
    _require(
        previous.frame.weights_for("household").kind is WeightKind.IMPORTANCE,
        "UNSUPPORTED_REFINEMENT",
    )
    node = Node(
        current.version,
        "us.sampling_origin.weight_only_admission@1",
        base=previous.version,
        structural=StructuralDelta.REWEIGHT,
        weights=WeightTransition("household", "calibrated", mass="free"),
        mass="free",
    )
    ledger = (
        *previous.mass_ledger,
        _mass_record(previous.frame, current.frame, node, KernelResult(), "free"),
    )
    owners = dict.fromkeys(previous.owners, current.version)
    graph._check_population_state(
        current,
        version=current.version,
        owners=owners,
        kind=WeightKind.CALIBRATED,
        ledger=ledger,
    )
    constraint = budget_view.grouped_bounds
    constraint.check(previous.frame.weights_for("household").values, positive=False)
    totals = constraint.check(
        current.frame.weights_for("household").values, positive=False
    )
    # Explicit necessary per-row reference bound, in addition to group U.
    rows = budget_view.document["origins"]
    for position, group in enumerate(constraint.group_indices):
        _require(
            float(current.frame.weights_for("household").values[position])
            <= float.fromhex(rows[int(group)]["design_bound_float64_hex"]),
            "ROW_REFERENCE_BOUND",
        )
    return {
        "protocol": SUCCESSOR_PROTOCOL,
        "budget_sha256": budget_view.digest,
        "previous_binding_sha256": None,
        "previous_version": previous.version,
        "current_version": current.version,
        "previous_frame_sha256": source._frame_identity(previous.frame),
        "current_frame_sha256": source._frame_identity(current.frame),
        "mass_ledger": [asdict(record) for record in current.mass_ledger],
        "group_total_float64_hex": [float(v).hex() for v in totals],
        "constraint_digest": constraint.digest,
        "release_eligible": False,
    }


def _state_unchanged(state):
    _require(
        _population_identity(state.previous) == state.previous_identity
        and _population_identity(state.current) == state.current_identity,
        "FINAL_SUCCESSOR_POPULATION_SEAL",
    )


def _checked_successor_document(state, budget_view):
    """Only the actual initial IMPORTANCE to CALIBRATED transition is supported."""
    _state_unchanged(state)
    payload = _json(_successor_document(state, budget_view))
    _state_unchanged(state)
    return payload


def _final_successor_state(state):
    """Check actual retained upstream handles after the final document helper."""
    _require(
        _entry(state.budget, SamplingOriginBudget) is state.budget_entry,
        "FINAL_UPSTREAM_BUDGET_SEAL",
    )
    budget_state = state.budget_entry[2]
    _final_budget_state(budget_state)
    _state_unchanged(state)
    _require(_live() == _LIVE, "FINAL_PRODUCER_SEAL")
    _preparation_entry(
        budget_state.preparation,
        budget_state.preparation_payload,
        budget_state.preparation_entry,
    )
    _require(
        _entry(state.budget, SamplingOriginBudget) is state.budget_entry,
        "FINAL_UPSTREAM_BUDGET_SEAL",
    )


@dataclass(frozen=True)
class SamplingOriginSuccessor:
    payload: bytes

    def __post_init__(self):
        raise SurveyOriginBudgetError("NO_PUBLIC_SUCCESSOR_CONSTRUCTOR")

    def checked_view(self):
        entry = _entry(self, SamplingOriginSuccessor)
        document, digest = json.loads(entry[1]), _sha(entry[1])
        state = entry[2]
        view = state.budget.checked_view()
        expected = _checked_successor_document(state, view)
        _require(expected == entry[1], "SUCCESSOR_RECONSTRUCTION")
        final = state.budget.checked_view()
        _require(
            _checked_successor_document(state, final) == entry[1],
            "FINAL_SUCCESSOR_SEAL",
        )
        result = CheckedSamplingOriginSuccessor(
            entry[1],
            digest,
            document,
            state.budget,
            state.previous,
            state.current,
            state.previous_binding,
        )
        _final_successor_state(state)
        _require(_entry(self, SamplingOriginSuccessor) is entry, "FINAL_SUCCESSOR_SEAL")
        return result

    def to_bytes(self):
        return self.checked_view().payload


@dataclass(frozen=True)
class CheckedSamplingOriginSuccessor:
    """A checked value borrow; authority remains in the issued handles."""

    payload: bytes
    digest: str
    document: dict
    budget: SamplingOriginBudget
    previous: Population
    current: Population
    previous_binding: object


def admit_survey_weight_only_population(
    budget, *, previous, current, previous_binding=None
):
    # The actual graph permits only strictly forward weight-kind transitions.
    # Keeping this keyword fail-closed makes deferred refinement explicit.
    _require(previous_binding is None, "UNSUPPORTED_REFINEMENT")
    _require(type(previous) is Population, "LIVE_POPULATION_REQUIRED")
    _require(
        previous.frame.weights_for("household").kind is WeightKind.IMPORTANCE,
        "UNSUPPORTED_REFINEMENT",
    )
    _require(type(budget) is SamplingOriginBudget, "BUDGET_TYPE")
    view = budget.checked_view()
    state = _SuccessorState(
        budget,
        _entry(budget, SamplingOriginBudget),
        previous,
        current,
        previous_binding,
        _population_identity(previous),
        _population_identity(current),
    )
    payload = _checked_successor_document(state, view)
    final = budget.checked_view()
    _require(
        _checked_successor_document(state, final) == payload, "FINAL_SUCCESSOR_SEAL"
    )
    result = _issue(SamplingOriginSuccessor, payload, state)
    entry = _entry(result, SamplingOriginSuccessor)
    _final_successor_state(state)
    _require(_entry(result, SamplingOriginSuccessor) is entry, "FINAL_SUCCESSOR_SEAL")
    return result


def verify_survey_weight_only_successor(binding):
    _require(type(binding) is SamplingOriginSuccessor, "SUCCESSOR_TYPE")
    binding.to_bytes()
    return binding


_BYTES = _code_bytes()
_LIVE = _live()
