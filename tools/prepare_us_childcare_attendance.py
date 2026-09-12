#!/usr/bin/env python3
"""Prepare a local NSECE attendance candidate and aggregate validation report.

No source downloads, remote uploads or release publication occur. Download the
DS4/DS5 TSVs under the ICPSR terms first. A Frame checkpoint is optional; source
validation is useful before a population candidate is available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path

from microcosm.build.frame_checkpoint import (
    load_frame_checkpoint,
    write_frame_checkpoint,
)
from microcosm.build.us_runtime import childcare_attendance, nsece_childcare
from microcosm.build.us_runtime.nsece_childcare import (
    NSECE_CHILDCARE_MATCH_COLUMNS,
    load_nsece_childcare,
    nsece_childcare_validation_report,
    with_us_nsece_childcare_attendance,
)
from microcosm.frame import Frame


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--household-tsv", type=Path, required=True)
    parser.add_argument("--calendar-tsv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=915)
    parser.add_argument(
        "--match-columns", nargs="+", default=list(NSECE_CHILDCARE_MATCH_COLUMNS)
    )
    parser.add_argument("--input-checkpoint", type=Path)
    parser.add_argument("--output-checkpoint", type=Path)
    args = parser.parse_args()
    if bool(args.input_checkpoint) != bool(args.output_checkpoint):
        parser.error(
            "--input-checkpoint and --output-checkpoint must be supplied together"
        )
    outputs = [p for p in (args.report, args.output_checkpoint) if p is not None]
    if any(p.exists() for p in outputs):
        parser.error(
            "Output paths must be new; existing artifacts will not be overwritten"
        )
    if len({p.resolve() for p in outputs}) != len(outputs):
        parser.error("Report and checkpoint paths must differ")
    source = load_nsece_childcare(args.household_tsv, args.calendar_tsv)
    report = nsece_childcare_validation_report(
        source, seed=args.seed, match_columns=tuple(args.match_columns)
    )
    report["candidate_frame_written"] = False
    report["environment"] = {
        package: version(package)
        for package in ("numpy", "pandas", "microcosm-build", "microcosm-frame")
    }
    report["environment"]["python"] = platform.python_version()
    report["code_sha256"] = {
        path.name: _sha256(path)
        for path in (
            Path(__file__),
            Path(childcare_attendance.__file__),
            Path(nsece_childcare.__file__),
        )
    }
    try:
        if args.input_checkpoint is not None:
            original = load_frame_checkpoint(args.input_checkpoint)
            # The checkpoint protocol deliberately stores Frame receipts as
            # external metadata; restore them explicitly rather than dropping
            # the parent build's source/ownership evidence.
            parent = original.frame
            parent = Frame(
                {entity: parent.table(entity) for entity in parent.entities},
                parent.schema,
                {
                    entity: parent.weights_for(entity)
                    for entity in parent.weighted_entities
                },
                parent.strata,
                mass_log=parent.mass_log,
                metadata={
                    **parent.metadata,
                    **original.metadata.get("frame_metadata", {}),
                },
            )
            candidate = with_us_nsece_childcare_attendance(
                parent,
                source,
                seed=args.seed,
                match_columns=tuple(args.match_columns),
            )
            write_frame_checkpoint(
                args.output_checkpoint,
                candidate,
                metadata={
                    "artifact_kind": "nsece_childcare_candidate",
                    "childcare_candidate_only": True,
                    "parent_checkpoint_metadata": original.metadata,
                    "parent_checkpoint_sha256": _sha256(args.input_checkpoint),
                    "frame_metadata": json.loads(
                        json.dumps(candidate.metadata, default=dict)
                    ),
                },
            )
            report["candidate_frame_written"] = True
    except Exception as exc:
        report["candidate_error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(f"Validation report: {args.report}")
    print("Candidate only; production readiness is not certified.")


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


if __name__ == "__main__":
    main()
