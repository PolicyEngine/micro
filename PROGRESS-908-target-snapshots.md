# microcosm#908 — per-target calibration estimate snapshots (bounded slice 1)

Lane journal for branch `calibration-target-snapshots-908-20260912`.
Journals are history, not state (see CLAUDE.md): check git/GitHub for current truth.

## State

In progress. Bounded first slice only — see "Out of scope for this slice".

## Scope of this slice

1. A shared, leaf-level typed snapshot codec in `microcosm-calibrate`:
   schema name + version, aggregate-only per-target rows, ordered target
   identity digest, finite-value and ordering validation, signed relative
   error with the repo's existing zero-target convention.
2. Real emission from the actual Adam solver loop in
   `microcosm.calibrate.solve`, at a configurable bounded cadence with an
   explicit every-epoch option, opt-in (off by default).
3. Honest iterate labelling: current / best_retained / selected, with the
   selected snapshot taken from the weights the solver actually returns.
4. Atomic local `latest.json` plus immutable, bounded history chunks.
5. A synthetic-only benchmark at US/UK-sized dimensions (invented matrices).

## Out of scope for this slice (remaining #908 acceptance scope)

- Version-2 staging upload / remote publication (PR896's country host).
- Calibration Diagnostics UI (different repository, by the issue's own text).
- Real UK/US native calibration measurements — this host is forbidden native
  microdata, engine runs and installs, so no real-run cadence default is
  announced here.

## Done

- (nothing yet)

## Next

- Read scouts, write failing tests, implement, bench, commit.
