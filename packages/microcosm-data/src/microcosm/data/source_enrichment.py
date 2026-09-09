"""Additive native-input releases that inherit an immutable calibration.

This release type does not certify a new calibration or upgrade its schema.
Its authority is the reviewed parent byte identity, an exhaustive H5 comparison,
Census source reconciliation, and separately measured native-loader compatibility.
Publication replays the latter checks before the Hub client is constructed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from microcosm.data.contract import ReleaseContractError

SOURCE_ENRICHMENT_RELEASE_TYPE = "source_enrichment"
SOURCE_ENRICHMENT_FILE = "source_enrichment.json"
ROLE_VARIABLE = "is_spm_independent_minor_role"
EVIDENCE_COLUMN = "is_spm_independence_role"
SOURCE_EVIDENCE_FILE = "source_spm_person_independence.csv"
SOURCE_EVIDENCE_SHA256 = (
    "22b5968d90fecfeef7614583e493fe10cc16bda8b5be82e6f49a5bc2102d3ce5"
)
SOURCE_PROVENANCE_FILE = "source_spm_independence_provenance.json"
COMPATIBILITY_FILE = "source_enrichment_compatibility.json"
COMPATIBILITY_PACKAGES = (
    "policyengine-us",
    "policyengine-core",
    "policyengine",
    "spm-calculator",
)
LOADED_SOURCE_PACKAGES = {
    "country_loader": "policyengine-us",
    "wrapper_loader": "policyengine",
    "native_role": "spm-calculator",
}
PARENT_BUILD_ID = "populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z"
PARENT_DATASET_SHA256 = (
    "48b9d479fb4fd1c3537f9383ce4697d130b6f618658409d74f6233c43b994c7e"
)
# Reviewed immutable BuildP evidence. Callers cannot grant another schema-5
# calibration permission to use the inheritance lane by supplying their own pins.
PARENT_FILES = {
    "parent_release_manifest.json": (
        "dd949ba3c4c7a56aff8442c6db5a031d2c84c3da59f5d14832f468c358604506"
    ),
    "parent_build_manifest.json": (
        "1990e8fd37ce66f499b8e6600c5896701bb07015be132a12de64e321a2edc67e"
    ),
    "calibration_diagnostics.json": (
        "870449b44e86b13b25bcea1a57f0e7af37f4d4db18be815eea3acdf9fe6eb40e"
    ),
    "us_source_coverage.json": (
        "6406c8686c292015a5bc7265a42402f89935f9395a8b63510efdd4d9562e7ff5"
    ),
}
CENSUS_PERSON_PINS = {
    2023: "19b56537e50e7663f954361ef2bb5ce9cef8d9d45f156fe1a69a99b654198ffe",
    2024: "21a2b9e0e4b08534563578a45acad77868af4ae9a7d46f23776b707d4a559aa7",
    2025: "06921fe83fc66c907e6c7b86b82255dc70458ee7d76258fc48297cb34f0c06b5",
}
EXPECTED_COUNTS = {
    "persons_joined": 166321,
    "native_spm_units": 59900,
    "total_source_people": 432523,
    "total_source_units": 176039,
    "minor_only_units_resolved": 28,
    "classification_changed_units_vs_age_only": 132,
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
PRODUCER_SOURCE_FILES = (
    "tools/build_us_spm_role_enrichment.py",
    "packages/microcosm-build/src/microcosm/build/us_runtime/spm_role_source.py",
    "packages/microcosm-build/src/microcosm/build/us_runtime/education_assistance_source.py",
    "packages/microcosm-data/src/microcosm/data/h5_enrichment.py",
    "packages/microcosm-data/src/microcosm/data/source_enrichment.py",
    "packages/microcosm-data/src/microcosm/data/contract.py",
)


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, failures: list[str]) -> dict:
    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("expected an object")
        return payload
    except (OSError, ValueError) as exc:
        failures.append(f"{path.name}: {exc}")
        return {}


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _check_person_evidence(path: Path, candidate: Path) -> dict:
    """Independently verify a complete, ordered, one-to-one native input join."""
    import h5py
    import numpy as np

    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        expected = ["person_id", "person_spm_unit_id", EVIDENCE_COLUMN]
        if reader.fieldnames != expected:
            raise ValueError(f"{path.name} must have exactly {expected}")
        rows = list(reader)
    if any(row[EVIDENCE_COLUMN] not in {"False", "True"} for row in rows):
        raise ValueError("source person evidence roles must be literal False or True")
    ids = np.array([int(row["person_id"]) for row in rows], dtype=np.int64)
    units = np.array([int(row["person_spm_unit_id"]) for row in rows], dtype=np.int64)
    roles = np.array([row[EVIDENCE_COLUMN] == "True" for row in rows], dtype=bool)
    if len(np.unique(ids)) != len(ids):
        raise ValueError("source person evidence has duplicate person IDs")
    with h5py.File(candidate, "r") as h5:
        table = h5["person/table"]
        for field, values in (
            ("person_id", ids),
            ("person_spm_unit_id", units),
            (ROLE_VARIABLE, roles),
        ):
            if not np.array_equal(table[field], values):
                raise ValueError(
                    f"source person evidence does not match native {field}"
                )
        role_index = table.dtype.names.index(ROLE_VARIABLE)
        if table.id.get_type().get_member_type(role_index) != h5py.h5t.NATIVE_B8 or (
            table.attrs.get(f"{ROLE_VARIABLE}_dtype") != b"bool"
        ):
            raise ValueError("native person role must have PyTables bool bitfield type")
    return {"persons_joined": len(ids), "native_spm_units": len(np.unique(units))}


def _check_source_provenance(provenance: Mapping, failures: list[str]) -> None:
    if provenance.get("dataset_sha256") != PARENT_DATASET_SHA256:
        failures.append(
            "source provenance dataset_sha256 must identify reviewed BuildP"
        )
    for key, expected in EXPECTED_COUNTS.items():
        if type(provenance.get(key)) is not int or provenance[key] != expected:
            failures.append(f"source provenance {key} must equal {expected}")
    for key in ("unmatched_persons", "adult_child_person_count_mismatch_units"):
        if type(provenance.get(key)) is not int or provenance[key] != 0:
            failures.append(f"source provenance {key} must equal zero")
    if (
        provenance.get("complete_source_membership_units")
        != EXPECTED_COUNTS["native_spm_units"]
    ):
        failures.append("source provenance must reconcile every native SPM unit")
    for key in ("weights_used", "ages_changed"):
        if provenance.get(key) is not False:
            failures.append(f"source provenance {key} must be false")
    if provenance.get("primitive_column") != ROLE_VARIABLE:
        failures.append("source provenance primitive_column must name the native role")
    if provenance.get("evidence_column") != EVIDENCE_COLUMN:
        failures.append("source provenance evidence_column must name the source role")
    checks = provenance.get("source_checks")
    if not isinstance(checks, list) or len(checks) != len(CENSUS_PERSON_PINS):
        failures.append("source provenance must carry every pinned Census source check")
        return
    seen = set()
    for raw in checks:
        row = _mapping(raw)
        year = row.get("survey_year")
        if type(year) is not int or year not in CENSUS_PERSON_PINS or year in seen:
            failures.append("source provenance has an unknown or duplicate Census year")
            continue
        seen.add(year)
        if row.get("csv_sha256") != CENSUS_PERSON_PINS[year]:
            failures.append(f"source provenance Census {year} CSV hash differs")
        if row.get("adult_child_person_count_mismatch_units") != 0:
            failures.append(
                f"source provenance Census {year} count reconciliation failed"
            )
        if not str(row.get("official_archive_url", "")).startswith(
            "https://www2.census.gov/"
        ):
            failures.append(
                f"source provenance Census {year} requires official archive"
            )
        archive_sha = row.get("archive_sha256")
        if not isinstance(archive_sha, str) or not _SHA256_RE.fullmatch(archive_sha):
            failures.append(f"source provenance Census {year} requires archive SHA256")


def validate_source_enrichment_candidate(
    release_dir: Path | str,
    *,
    parent_h5: Path | str | None,
    artifact_root: Path | str | None,
    require_compatibility: bool = False,
    compatibility_wheels: tuple[Path | str, ...] = (),
) -> dict:
    """Check the inheritance contract; pending candidates cannot be published.

    Unlike the standard release contract, this never treats parent diagnostics
    as measurements of the enriched model. Both actual H5 files are mandatory:
    a hand-written preservation receipt is not sufficient evidence.
    """
    from microcosm.data.h5_enrichment import compare_h5_enrichment

    release_dir = Path(release_dir)
    failures: list[str] = []
    manifest = _json(release_dir / "release_manifest.json", failures)
    build = _json(release_dir / "build_manifest.json", failures)
    report = _json(release_dir / SOURCE_ENRICHMENT_FILE, failures)
    if manifest.get("release_type") != SOURCE_ENRICHMENT_RELEASE_TYPE:
        failures.append(
            "release_manifest.json must declare release_type=source_enrichment"
        )
    if manifest.get("schema_version") != 1:
        failures.append(
            "source enrichment release manifest schema_version must equal 1"
        )
    if _mapping(manifest.get("build")).get("build_id") != release_dir.name:
        failures.append(
            "release manifest build_id must match its new release directory"
        )
    if release_dir.name == PARENT_BUILD_ID or not release_dir.name.startswith(
        "populace-us-2024-"
    ):
        failures.append("source enrichment requires a NEW US 2024 release id")
    if manifest.get("dataset_role", "national_default") != "national_default":
        failures.append("source enrichment supports only the national default dataset")
    if build.get("build_id") != release_dir.name:
        failures.append("build manifest build_id must match the new release directory")
    if build.get("release_type") != SOURCE_ENRICHMENT_RELEASE_TYPE:
        failures.append("build manifest must declare source_enrichment")
    if report.get("schema_version") != 1 or report.get("release_type") != (
        SOURCE_ENRICHMENT_RELEASE_TYPE
    ):
        failures.append(
            "source_enrichment.json must declare source_enrichment schema 1"
        )
    if report.get("operation") != "add_native_spm_independent_minor_role":
        failures.append("source enrichment operation must add only the native SPM role")
    parent = _mapping(report.get("parent"))
    expected_parent = {
        "build_id": PARENT_BUILD_ID,
        "repo_id": "policyengine/populace-us",
        "revision": PARENT_BUILD_ID,
        "dataset_sha256": PARENT_DATASET_SHA256,
        "calibration_diagnostics_schema_version": 5,
        "files": PARENT_FILES,
    }
    if parent != expected_parent:
        failures.append(
            "source enrichment parent must match the reviewed BuildP identity"
        )
    for name, expected in PARENT_FILES.items():
        path = release_dir / name
        if not path.is_file() or sha256_file(path) != expected:
            failures.append(f"inherited {name} must preserve the reviewed parent bytes")
    diagnostics = _json(release_dir / "calibration_diagnostics.json", failures)
    if (
        type(diagnostics.get("schema_version")) is not int
        or diagnostics.get("schema_version") != 5
    ):
        failures.append("inherited calibration_diagnostics must retain schema 5")
    if report.get("added_variable") != {
        "name": ROLE_VARIABLE,
        "entity": "person",
        "dtype": "bool",
        "age_gate_applied": False,
    }:
        failures.append(
            "added_variable must declare the person bool primitive before age gate"
        )
    dataset = _mapping(report.get("dataset"))
    filename = dataset.get("filename")
    if (
        not isinstance(filename, str)
        or Path(filename).name != filename
        or not (filename.endswith(".h5"))
    ):
        failures.append("source enrichment dataset.filename must be a bare H5 filename")
        filename = None
    candidate = Path(artifact_root) / filename if artifact_root and filename else None
    if parent_h5 is None or candidate is None:
        failures.append(
            "source enrichment requires parent_h5 and artifact_root for exact H5 verification"
        )
    elif not Path(parent_h5).is_file() or not candidate.is_file():
        failures.append("source enrichment parent and candidate H5 files must exist")
    else:
        if sha256_file(parent_h5) != PARENT_DATASET_SHA256:
            failures.append("parent H5 SHA256 differs from reviewed BuildP")
        if candidate.resolve() == Path(parent_h5).resolve():
            failures.append("source enrichment must create a NEW H5")
        if sha256_file(candidate) != dataset.get("sha256"):
            failures.append("candidate H5 SHA256 differs from source enrichment report")
        try:
            comparison = compare_h5_enrichment(Path(parent_h5), candidate)
            if report.get("preservation") != comparison:
                failures.append(
                    "preservation report differs from actual exhaustive H5 comparison"
                )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            failures.append(f"exact H5 preservation failed: {exc}")
    if _mapping(build.get("dataset")) != dataset:
        failures.append("build manifest dataset must match the new H5 identity")
    calibration = _mapping(build.get("calibration"))
    if calibration != {
        "mode": "inherited",
        "parent_build_id": PARENT_BUILD_ID,
        "diagnostics_sha256": PARENT_FILES["calibration_diagnostics.json"],
        "diagnostics_schema_version": 5,
    }:
        failures.append(
            "build calibration must explicitly inherit schema-5 parent evidence"
        )
    source = _mapping(report.get("source"))
    for field, expected_name in (
        ("person_evidence", SOURCE_EVIDENCE_FILE),
        ("provenance", SOURCE_PROVENANCE_FILE),
    ):
        name = source.get(f"{field}_filename")
        path = release_dir / expected_name
        if (
            name != expected_name
            or not path.is_file()
            or sha256_file(path) != source.get(f"{field}_sha256")
        ):
            failures.append(
                f"source enrichment {field} must bind the immutable {expected_name}"
            )
    evidence_path = release_dir / SOURCE_EVIDENCE_FILE
    if (
        not evidence_path.is_file()
        or sha256_file(evidence_path) != SOURCE_EVIDENCE_SHA256
    ):
        failures.append(
            "source evidence must match the independently reviewed Census-derived person table"
        )
    provenance = _json(release_dir / SOURCE_PROVENANCE_FILE, failures)
    _check_source_provenance(provenance, failures)
    if report.get("reconciliation") != provenance:
        failures.append("source enrichment reconciliation must equal source provenance")
    if (
        candidate
        and candidate.is_file()
        and (release_dir / SOURCE_EVIDENCE_FILE).is_file()
    ):
        try:
            counts = _check_person_evidence(
                release_dir / SOURCE_EVIDENCE_FILE, candidate
            )
            if any(provenance.get(key) != value for key, value in counts.items()):
                failures.append(
                    "source provenance coverage differs from actual person evidence"
                )
        except (ValueError, KeyError, OSError, TypeError) as exc:
            failures.append(f"native source evidence reconciliation failed: {exc}")
    required_artifacts = {
        *PARENT_FILES,
        SOURCE_ENRICHMENT_FILE,
        SOURCE_EVIDENCE_FILE,
        SOURCE_PROVENANCE_FILE,
    }
    artifacts = _mapping(manifest.get("artifacts"))
    by_path = {}
    for key, raw in artifacts.items():
        entry = _mapping(raw)
        path = entry.get("path")
        if not isinstance(path, str) or Path(path).name != path:
            failures.append(
                f"source enrichment artifact {key} must use a bare filename"
            )
            continue
        if path in by_path:
            failures.append(f"source enrichment duplicate artifact path {path}")
        by_path[path] = entry
        if (
            entry.get("repo_id") != "policyengine/populace-us"
            or entry.get("revision") != release_dir.name
        ):
            failures.append(
                f"source enrichment artifact {key} must pin the new repo/tag"
            )
        local = candidate if path == filename else release_dir / path
        if (
            local is None
            or not local.is_file()
            or sha256_file(local) != entry.get("sha256")
        ):
            failures.append(f"source enrichment artifact {key} hash/file mismatch")
    if not required_artifacts.issubset(by_path):
        failures.append(
            "release manifest must list every inherited and source enrichment artifact"
        )
    national = _mapping(manifest.get("default_datasets")).get("national")
    native_artifact = (
        _mapping(artifacts.get(national)) if isinstance(national, str) else {}
    )
    if (
        native_artifact.get("path") != filename
        or native_artifact.get("kind") != "microdata"
    ):
        failures.append("default_datasets.national must select the enriched native H5")
    if (
        len([entry for entry in by_path.values() if entry.get("kind") == "microdata"])
        != 1
    ):
        failures.append(
            "source enrichment must deliver exactly one native H5 microdata artifact"
        )
    compatibility = _mapping(report.get("compatibility"))
    if compatibility.get("status") == "pending":
        if require_compatibility:
            failures.append(
                "source enrichment compatibility is pending; run real candidate-wheel native loader qualification"
            )
        if manifest.get("compatible_core_packages") or manifest.get(
            "compatible_model_packages"
        ):
            failures.append(
                "pending source enrichment must not claim model/Core compatibility"
            )
        if any(
            key in _mapping(manifest.get("build"))
            for key in ("built_with_core_package", "built_with_model_package")
        ):
            failures.append(
                "pending source enrichment must not copy built-with package claims"
            )
    elif compatibility.get("status") == "passed":
        if COMPATIBILITY_FILE not in by_path:
            failures.append(
                "release manifest must deliver the native compatibility receipt"
            )
        _check_compatibility(
            release_dir,
            manifest,
            compatibility,
            candidate,
            require_compatibility,
            compatibility_wheels,
            failures,
        )
    else:
        failures.append(
            "source enrichment compatibility status must be pending or passed"
        )
    if require_compatibility:
        try:
            _check_producer_source_identity(_mapping(build.get("code")))
        except (OSError, ValueError) as exc:
            failures.append(f"producer source identity failed: {exc}")
    if failures:
        raise ReleaseContractError(release_dir, failures)
    return report


def _check_producer_source_identity(code: Mapping) -> None:
    """Bind clean build provenance to committed and currently executed sources.

    Publication/certification runs from a Microcosm checkout. A later docs-only
    commit is fine; each reviewed producer file must still have the exact bytes
    recorded in the build and in its immutable producer commit.
    """
    import subprocess

    from microcosm.data import contract, h5_enrichment

    commit = code.get("git_commit")
    if (
        code.get("git_dirty") is not False
        or not isinstance(commit, str)
        or not (re.fullmatch(r"[0-9a-f]{40}", commit))
    ):
        raise ValueError("publication requires a recorded clean producer commit")
    hashes = _mapping(code.get("source_files_sha256"))
    if set(hashes) != set(PRODUCER_SOURCE_FILES) or any(
        not isinstance(value, str) or not _SHA256_RE.fullmatch(value)
        for value in hashes.values()
    ):
        raise ValueError("producer must hash the exact reviewed source-file inventory")

    def git(*args: str) -> bytes:
        try:
            return subprocess.run(
                ["git", *args], check=True, capture_output=True
            ).stdout
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                "producer commit/source cannot be authenticated in the current Git checkout"
            ) from exc

    checkout = Path(git("rev-parse", "--show-toplevel").decode().strip())
    verified_commit = (
        git("rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    )
    if verified_commit != commit:
        raise ValueError("producer git_commit does not resolve to the recorded commit")
    for relative in PRODUCER_SOURCE_FILES:
        committed = git("show", f"{commit}:{relative}")
        if hashlib.sha256(committed).hexdigest() != hashes[relative]:
            raise ValueError(
                f"producer committed source differs from recorded hash: {relative}"
            )
        current = checkout / relative
        if not current.is_file() or sha256_file(current) != hashes[relative]:
            raise ValueError(
                f"producer checkout source differs from recorded hash: {relative}"
            )
    executing = {
        "packages/microcosm-data/src/microcosm/data/h5_enrichment.py": h5_enrichment.__file__,
        "packages/microcosm-data/src/microcosm/data/source_enrichment.py": __file__,
        "packages/microcosm-data/src/microcosm/data/contract.py": contract.__file__,
    }
    for relative, actual in executing.items():
        if actual is None or sha256_file(actual) != hashes[relative]:
            raise ValueError(
                f"executing producer contract differs from recorded source: {relative}"
            )


def _check_compatibility(
    release_dir,
    manifest,
    compatibility,
    candidate,
    require_wheel_proof,
    wheels,
    failures,
):
    receipt_path = release_dir / COMPATIBILITY_FILE
    receipt = _json(receipt_path, failures)
    if (
        compatibility.get("filename") != COMPATIBILITY_FILE
        or not receipt_path.is_file()
        or (compatibility.get("sha256") != sha256_file(receipt_path))
    ):
        failures.append(
            "source enrichment compatibility must hash-bind the actual test receipt"
        )
    if candidate is None or not candidate.is_file():
        return
    try:
        actual = run_native_loader_compatibility(
            candidate, require_wheels=require_wheel_proof, compatibility_wheels=wheels
        )
        if receipt != actual:
            failures.append(
                "compatibility receipt differs from actual native loader tests/runtime"
            )
        from microcosm.data.contract import _check_release_manifest

        _check_release_manifest(manifest, release_dir.name, failures)
        for package, field in (
            ("policyengine-us", "model"),
            ("policyengine-core", "core"),
        ):
            version = _mapping(actual.get("packages")).get(package, {}).get("version")
            if _mapping(
                _mapping(manifest.get("build")).get(f"built_with_{field}_package")
            ) != {"name": package, "version": version}:
                failures.append(
                    f"compatibility built-with {package} must match tested runtime"
                )
            if manifest.get(f"compatible_{field}_packages") != [
                {"name": package, "specifier": f"=={version}"}
            ]:
                failures.append(
                    f"compatibility {package} must pin exactly the tested version"
                )
    except (ValueError, OSError, ImportError, KeyError, TypeError) as exc:
        failures.append(f"native loader compatibility failed: {exc}")


def _wheel_files(path: Path) -> tuple[str, str, dict[str, bytes]]:
    from email.parser import BytesParser
    from zipfile import ZipFile

    with ZipFile(path) as wheel:
        metadata_files = [
            name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError(f"{path.name} must contain one wheel METADATA file")
        metadata = BytesParser().parsebytes(wheel.read(metadata_files[0]))
        return (
            metadata["Name"],
            metadata["Version"],
            {
                name: wheel.read(name)
                for name in wheel.namelist()
                if name.endswith(".py")
            },
        )


def _runtime_package_identities(compatibility_wheels, *, require_wheels: bool) -> dict:
    """Hash actual installed source; optional wheel proof is offline, not PyPI proof."""
    from importlib import metadata

    names = COMPATIBILITY_PACKAGES
    wheels = {}
    for raw_path in compatibility_wheels:
        path = Path(raw_path)
        name, version, files = _wheel_files(path)
        name = name.lower().replace("_", "-")
        if name not in names or name in wheels:
            raise ValueError(
                "compatibility wheels must uniquely name country, Core, wrapper, and calculator"
            )
        wheels[name] = (path, version, files)
    if require_wheels and set(wheels) != set(names):
        raise ValueError(
            "compatibility requires exact installed policyengine-us, policyengine-core, policyengine, and spm-calculator wheels; candidate wheels may be tested before publication, whose external proof remains the publisher's gate"
        )
    result = {}
    for name in names:
        dist = metadata.distribution(name)
        direct_url = dist.read_text("direct_url.json")
        source_files = sorted(
            str(file) for file in (dist.files or ()) if str(file).endswith(".py")
        )
        if not source_files:
            raise ValueError(
                f"cannot attest actual installed Python sources for {name}"
            )
        digest = hashlib.sha256()
        for relative in source_files:
            path = Path(dist.locate_file(relative))
            digest.update(relative.encode() + b"\0" + path.read_bytes() + b"\0")
        identity = {
            "version": dist.version,
            "source_sha256": digest.hexdigest(),
            "direct_url": json.loads(direct_url) if direct_url else None,
            "wheel_sha256": None,
        }
        if name in wheels:
            path, version, files = wheels[name]
            if version != dist.version:
                raise ValueError(
                    f"{name} wheel version differs from the tested install"
                )
            for relative, expected in files.items():
                installed = Path(dist.locate_file(relative))
                if not installed.is_file() or installed.read_bytes() != expected:
                    raise ValueError(
                        f"{name} installed source differs from wheel: {relative}"
                    )
            if set(source_files) != set(files):
                raise ValueError(
                    f"{name} installed source inventory differs from wheel"
                )
            if direct_url and json.loads(direct_url).get("dir_info", {}).get(
                "editable"
            ):
                raise ValueError(
                    f"{name} editable installation is not a publishable wheel identity"
                )
            identity["wheel_sha256"] = sha256_file(path)
        result[name] = identity
    return result


def run_native_loader_compatibility(
    candidate_h5: Path | str,
    *,
    require_wheels: bool = False,
    compatibility_wheels: tuple[Path | str, ...] = (),
) -> dict:
    """Run fixed native-loader tests and one complete-household input-precedence probe.

    This proves native delivery, not canonical SPM numerical-model acceptance or
    publication of package versions. Those remain the root release gates. An
    installed wheel is checked against its source bytes, never a claimed bool.
    """
    import inspect

    import h5py
    import numpy as np
    from policyengine.tax_benefit_models.us.datasets import PolicyEngineUSDataset
    from policyengine_us.data import USSingleYearDataset
    from policyengine_us.system import system

    candidate_h5 = Path(candidate_h5)
    packages = _runtime_package_identities(
        compatibility_wheels, require_wheels=require_wheels
    )
    variable = system.variables.get(ROLE_VARIABLE)
    if (
        variable is None
        or variable.entity.key != "person"
        or variable.value_type is not bool
    ):
        raise ValueError(
            f"tested country model must register {ROLE_VARIABLE} as a native person bool"
        )
    source_paths = {
        "country_loader": inspect.getsourcefile(USSingleYearDataset),
        "wrapper_loader": inspect.getsourcefile(PolicyEngineUSDataset),
        "native_role": inspect.getsourcefile(type(variable)),
    }
    if require_wheels:
        _check_loaded_source_ownership(source_paths)
    country = USSingleYearDataset(file_path=str(candidate_h5))
    wrapper = PolicyEngineUSDataset(
        name="native_spm_role_compatibility",
        description="Read-only native SPM role compatibility probe",
        filepath=str(candidate_h5),
        year=2024,
    )
    checked = []
    with h5py.File(candidate_h5, "r") as h5:
        for entity in (
            "person",
            "household",
            "tax_unit",
            "spm_unit",
            "family",
            "marital_unit",
        ):
            table = h5[f"{entity}/table"]
            columns = [f"{entity}_id"]
            weight_column = f"{entity}_weight"
            if weight_column in table.dtype.names:
                columns.append(weight_column)
            if entity == "person":
                columns += [ROLE_VARIABLE] + [
                    name
                    for name in table.dtype.names
                    if name.startswith("person_") and name.endswith("_id")
                ]
            for column in dict.fromkeys(columns):
                expected = table[column]
                if column == ROLE_VARIABLE:
                    expected = expected.astype(bool)
                for loader, frame in (
                    ("country", getattr(country, entity)),
                    ("wrapper", getattr(wrapper.data, entity)),
                ):
                    observed = frame[column].to_numpy()
                    if (
                        observed.dtype != expected.dtype
                        or observed.shape != expected.shape
                        or observed.tobytes() != expected.tobytes()
                    ):
                        raise ValueError(
                            f"{loader} native loader changed {entity}.{column}"
                        )
                    checked.append(f"{loader}:{entity}.{column}")
        if not np.asarray(country.person[ROLE_VARIABLE]).dtype == np.dtype(bool):
            raise ValueError("country native role dtype must remain bool")
    # The country engine may provide a household-role fallback for surveys
    # without this primitive. Opposite supplied values on one complete native
    # household must both reach Core unchanged, overriding any fixed fallback.
    _check_native_input_precedence(country)
    return {
        "schema_version": 1,
        "status": "passed",
        "scope": "native_input_loading_only",
        "external_package_publication": "not_attested",
        "canonical_spm_model_acceptance": "not_attested",
        "dataset_sha256": sha256_file(candidate_h5),
        "runner_sha256": sha256_file(__file__),
        "packages": packages,
        "loaded_source_packages": LOADED_SOURCE_PACKAGES.copy(),
        "loaded_source_sha256": {
            key: sha256_file(path) for key, path in source_paths.items()
        },
        "checks": [
            "country:registered_person_bool_input",
            "country:complete_household_native_input_overrides_default",
            *checked,
        ],
    }


def _check_loaded_source_ownership(source_paths: Mapping) -> None:
    """The country registers the native role supplied by the calculator wheel."""
    from importlib import import_module, metadata

    for package in COMPATIBILITY_PACKAGES:
        module_name = package.replace("-", "_")
        module = import_module(module_name)
        expected_root = Path(
            metadata.distribution(package).locate_file(module_name)
        ).resolve()
        if not Path(module.__file__).resolve().is_relative_to(expected_root):
            raise ValueError(
                f"tested {package} import does not come from the verified installed wheel"
            )
    for label, package in LOADED_SOURCE_PACKAGES.items():
        expected_root = Path(
            metadata.distribution(package).locate_file(package.replace("-", "_"))
        ).resolve()
        source = source_paths.get(label)
        if source is None or not Path(source).resolve().is_relative_to(expected_root):
            raise ValueError(
                f"tested {label} source does not come from the verified {package} wheel"
            )


def _check_native_input_precedence(country) -> None:
    import numpy as np
    from policyengine_us import Microsimulation
    from policyengine_us.data import USSingleYearDataset

    household_id = country.household["household_id"].iloc[0]
    person = country.person.loc[
        country.person["person_household_id"] == household_id
    ].copy()
    if person.empty:
        raise ValueError("native compatibility fixture has no complete household")
    tables = {"person": person, "time_period": 2024}
    for entity in ("household", "tax_unit", "spm_unit", "family", "marital_unit"):
        ids = person[f"person_{entity}_id"].unique()
        table = getattr(country, entity)
        tables[entity] = table.loc[table[f"{entity}_id"].isin(ids)].copy()
        if entity == "spm_unit":
            if (
                not country.person.loc[
                    country.person["person_spm_unit_id"].isin(ids),
                    "person_household_id",
                ]
                .eq(household_id)
                .all()
            ):
                raise ValueError("native compatibility household cuts an SPM unit")
    for supplied_value in (False, True):
        supplied = np.full(len(person), supplied_value, dtype=bool)
        tables["person"] = person.assign(**{ROLE_VARIABLE: supplied})
        simulation = Microsimulation(dataset=USSingleYearDataset(**tables))
        observed = np.asarray(simulation.calculate(ROLE_VARIABLE, 2024))
        if observed.dtype != supplied.dtype or not np.array_equal(observed, supplied):
            raise ValueError("country Core discarded the supplied native person role")


def certify_source_enrichment(
    release_dir: Path | str,
    output_dir: Path | str,
    *,
    parent_h5: Path | str,
    artifact_root: Path | str,
    compatibility_wheels: tuple[Path | str, ...],
) -> Path:
    """Create a separate certified bundle only after measured loader checks pass.

    H5 and source evidence are never modified. The caller still owns canonical
    model acceptance, package publication proof, and publisher authorization.
    """
    import shutil
    import tempfile
    from importlib import metadata

    release_dir, output_dir = Path(release_dir), Path(output_dir)
    if output_dir.exists() or output_dir.name != release_dir.name:
        raise ValueError(
            "output_dir must be new and keep the candidate release id as its basename"
        )
    report = validate_source_enrichment_candidate(
        release_dir, parent_h5=parent_h5, artifact_root=artifact_root
    )
    candidate = Path(artifact_root) / report["dataset"]["filename"]
    receipt = run_native_loader_compatibility(
        candidate, require_wheels=True, compatibility_wheels=compatibility_wheels
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".source-enrichment-", dir=output_dir.parent
    ) as staging:
        staged = Path(staging) / release_dir.name
        shutil.copytree(release_dir, staged)

        def write(name, value):
            (staged / name).write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n"
            )

        write(COMPATIBILITY_FILE, receipt)
        report["compatibility"] = {
            "status": "passed",
            "filename": COMPATIBILITY_FILE,
            "sha256": sha256_file(staged / COMPATIBILITY_FILE),
        }
        write(SOURCE_ENRICHMENT_FILE, report)
        manifest = json.loads((staged / "release_manifest.json").read_text())
        for package, field in (
            ("policyengine-us", "model"),
            ("policyengine-core", "core"),
        ):
            version = receipt["packages"][package]["version"]
            manifest["build"][f"built_with_{field}_package"] = {
                "name": package,
                "version": version,
            }
            manifest[f"compatible_{field}_packages"] = [
                {"name": package, "specifier": f"=={version}"}
            ]
        manifest["data_package"] = {
            "name": "microcosm-data",
            "version": metadata.version("microcosm-data"),
        }
        for entry in manifest["artifacts"].values():
            if entry["path"] == SOURCE_ENRICHMENT_FILE:
                entry["sha256"] = sha256_file(staged / SOURCE_ENRICHMENT_FILE)
        manifest["artifacts"]["source_enrichment_compatibility"] = {
            "kind": "diagnostics",
            "path": COMPATIBILITY_FILE,
            "repo_id": "policyengine/populace-us",
            "revision": release_dir.name,
            "sha256": sha256_file(staged / COMPATIBILITY_FILE),
        }
        write("release_manifest.json", manifest)
        validate_source_enrichment_candidate(
            staged,
            parent_h5=parent_h5,
            artifact_root=artifact_root,
            require_compatibility=True,
            compatibility_wheels=compatibility_wheels,
        )
        staged.rename(output_dir)
    return output_dir


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", required=True, type=Path)
    parser.add_argument("--parent-h5", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--certify", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--require-compatibility", action="store_true")
    parser.add_argument("--compatibility-wheel", action="append", type=Path, default=[])
    args = parser.parse_args(argv)
    if args.certify and args.output_dir is None:
        parser.error(
            "--certify requires a new --output-dir ending in the same release id"
        )
    try:
        if args.certify:
            result = certify_source_enrichment(
                args.release_dir,
                args.output_dir,
                parent_h5=args.parent_h5,
                artifact_root=args.artifact_root,
                compatibility_wheels=tuple(args.compatibility_wheel),
            )
            print(json.dumps({"certified_bundle": str(result), "published": False}))
        else:
            report = validate_source_enrichment_candidate(
                args.release_dir,
                parent_h5=args.parent_h5,
                artifact_root=args.artifact_root,
                require_compatibility=args.require_compatibility,
                compatibility_wheels=tuple(args.compatibility_wheel),
            )
            print(
                json.dumps(
                    {"valid": True, "compatibility": report["compatibility"]["status"]}
                )
            )
    except (ValueError, OSError, ImportError, KeyError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
