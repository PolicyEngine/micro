# Calibration target snapshots

An opt-in observer exposes target estimates already computed during an Adam
solve. It also records the estimates on the weights actually returned. Use it
to inspect fit over time without adding another model evaluation or changing
the optimization steps.

```python
from pathlib import Path

from microcosm.calibrate import (
    TargetSnapshotCadence,
    TargetSnapshotObserver,
    TargetSnapshotWriter,
    calibrate,
)

observer = TargetSnapshotObserver(
    sink=TargetSnapshotWriter(Path("runs/example/targets"), history_limit=256),
    run_id="example",
    cadence=TargetSnapshotCadence(every=25),
)
result = calibrate(frame, targets, method="adam", target_snapshots=observer)
```

The caller supplies its existing frame and targets. No observer is enabled by
default. The example cadence is a caller choice, not a measured country-build
default. A sink exception propagates, matching the existing progress callback.

Each snapshot has an ordered target identity, target values, achieved estimates,
relative errors, sequence, phase and iterate labels. Duplicate target names
remain distinguishable by ordered position. Honest nonfinite intermediate
estimates are represented by nulls and counts. Intermediate float32 estimates
and final float64 estimates are labeled with their actual iterate semantics.
Budget probes and subsequent selection/refit phases share one emission sequence.

Metadata accepts bounded flat scalar mappings and checked string identifiers;
it does not accept nested payloads or record vectors. `best_retained` must be a
complete `{available, epoch, loss}` mapping in a serialized snapshot. The emitter
can fill that mapping when no best iterate exists; the public validator rejects
a serialized null in its place. Each delivered payload is detached from the
caller's metadata and subsequent snapshots.

The local writer atomically replaces `latest.json`. History chunks become
visible only after their complete bytes are written and synced, and an existing
chunk cannot be overwritten. Retention and dropped-history counts are explicit.
Use a fresh run directory unless intentionally adopting existing history.

## The grouped US solver

The grouped/fixed-zero Adam path (`grouped_upper_bounds`, optionally
`grouped_preserve_zeros`) is instrumented at the same two seams and with the
same guarantees: the in-loop snapshot reads the exact float32 estimate tensor
the epoch's loss was computed from, and the closing `selected` snapshot reads
the same float64 `problem.estimates` the final diagnostics use. Enabling the
observer on a grouped run adds no matrix evaluation, no model evaluation and no
RNG advance, and returns bit-identical weights and trajectory.

Two grouped specifics a consumer must read correctly:

- Grouped Adam is a **closing-state** algorithm. It never runs the retain-best
  rule, so every grouped snapshot carries
  `best_retained = {"available": false, "epoch": null, "loss": null}` and the
  closing snapshot is stamped `epoch == epochs`. That is not the same as an
  ordinary run whose retain-best rule was switched off, so grouped snapshots
  also carry bounded `selection` labels — `rule: "closing_state"`,
  `constraint_mode: "grouped_upper_bounds"` and `grouped_preserve_zeros` —
  which mirror the run's `options["iterate_selection"]`.
- In-loop snapshots are **pre-update loss evaluations**, the same convention the
  ungrouped Adam loop uses. They are deliberately not the post-update projected
  accepted vector that the private `_post_projection_observer` proof seam
  reports at the same epoch number: those are different vectors, and producing
  target totals for the accepted one would require an extra matrix evaluation.
  That private seam carries record-length weights, household IDs, the group map
  and the absolute-bound vector; none of it reaches a snapshot, and the public
  codec rejects record-level key names outright.

Grouped runs keep every existing guard: fixed zeros stay in full-population
coordinates, the accepted-weight byte equality and ordered-household-ID checks
still run *after* the closing snapshot sink, and the unsupported grouped modes
(scalar cap, conserved mass, prox, L0/exact-k, gate initialization) are still
refused before the optimizer is constructed. Snapshot support does not turn any
of them into a permitted numeric path.

This implements the solver and local storage portion of
[issue 908](https://github.com/PolicyEngine/microcosm/issues/908). Country-host
wiring, staging upload, a dashboard consumer and native cadence/performance
acceptance remain separate work. In particular
`us_runtime/graph_fiscal_dense_calibration.py` still calls `calibrate` without
an observer: a solver-side integration alone produces no snapshot files for
that path, and wiring it needs an explicit host-owned instrumentation seam
rather than a callback or filesystem path serialized into graph node params.

The reviewed repair branch passed 307 calibration tests before the final strict
null correction. All 52 snapshot tests then passed after that one-line correction,
including passive solver parity tests. Independent review closed the metadata,
detachment, partial-publication and codec findings. See the
[invented benchmark evidence](../experiments/908-target-snapshot-bench-receipts.md)
for overhead measurements; those are not native US or UK benchmarks.
