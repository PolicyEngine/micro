# microcosm#908 — closing the four reviewed findings on the snapshot slice

Lane journal for branch `calibration-target-snapshots-908-fixes-20260912`.
Journals are history, not state (see CLAUDE.md): check git/GitHub for current truth.

## State

Merged the completed slice (`bae1887ff`) onto `origin/main` `116d46ee9`, resolved
the four overlapping spec-engine identity pins by recomputing them on the merge
ref, and am now implementing the four reviewed findings. Not pushed, no PR.

## Review basis

`908-final-review-review-full-report.md` (head `bae1887ff`, merge base
`35fc76dd1`) with `probe.py` / `reproductions.json`. Four open findings:

1. **C1** — the aggregate-only claim is enforced by a denylist over arbitrary
   nested JSON, so record-level vectors ride through `context` and a
   mapping-valued `candidate_id`.
2. **A1** — nested metadata is copied only by `dict(...)`, so a sink mutating a
   delivered payload changes the caller's mapping and the next snapshot.
3. **A2** — `_write_chunk` creates the final `history/<n>.json` name before
   writing it, so a concurrent reader sees a partial chunk, and a failed write
   leaves an invalid immutable chunk behind.
4. **A3** — the public codec admits impossible metadata: `epoch > epochs`, a
   non-timestamp `created_at`, a non-string `candidate_id`, and a
   `best_retained` whose availability, epoch and loss contradict each other.

## Done

- Merged `bae1887ff` into this branch.

## Next

- Red regressions for all four findings, then the implementation.

## Identity pins recomputed on the merge ref

`microcosm.calibrate.solve` is attested (`_DIRECT_KERNEL_MODULES`); main's #912
edited the attested `microcosm.fit.qrf`, so both sides' pins were stale and the
merge conflicted on all four. Each was recomputed on the merged tree, after
first proving with the same interpreter that restoring **main's** `solve.py`
into the merged tree reproduces **main's** committed pins exactly — so the
drift is attributable to the slice's `solve.py` edit, not to an environment
leak.

| pin | main `116d46ee9` | slice `bae1887ff` | merged |
| --- | --- | --- | --- |
| `EXPECTED_HASHES["seed_protocol"]` | `553d5e0b…` | `f4dc507c…` | `d052fd87…` |
| `EXPECTED_HASHES["seed_map"]` | `20058e54…` | `32dea304…` | `d5a9694a…` |
| US resolved-spec `spec_sha256` | `1eeca53a…` | `35a3623b…` | `ff2c9703…` |
| minimal-spec loader golden | `b4659890…` | `a67bb78c…` | `8a240898…` |

`docs/evidence/spec-engine/us-f0-coverage.json` was regenerated with
`tools/spec_engine_coverage.py` (42156/42156 fields, 41/41 inventory checks).
The graph `calibrate.adam@1` parity pin merged cleanly and re-verified green
(25 parity tests). `fit.qrf` and `simulate` pins are untouched.
