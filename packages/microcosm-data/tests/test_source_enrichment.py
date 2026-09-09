"""The inheritance lane preserves calibration and rejects rehashed tampering."""

from __future__ import annotations

import json
import shutil

import h5py
import numpy as np
import pytest

from microcosm.data import source_enrichment as enrichment
from microcosm.data.contract import ReleaseContractError, validate_release_dir
from microcosm.data.h5_enrichment import append_native_spm_role, compare_h5_enrichment
from microcosm.data.publish_cli import main as publish_main
from microcosm.data.release import publish_release


def _write(path, payload):
    path.write_text(json.dumps(payload, sort_keys=True))


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    pd = pytest.importorskip("pandas")
    pytest.importorskip("tables")
    parent = tmp_path / "parent.h5"
    people = pd.DataFrame(
        {
            "person_id": [1, 2, 3],
            "person_spm_unit_id": [1, 1, 2],
            "person_household_id": [1, 1, 2],
            "person_weight": [2.0, 2.0, 1.0],
            "age": [12, 16, 45],
        }
    )
    with pd.HDFStore(parent, "w") as store:
        store.put("person", people, format="table", data_columns=True)
        for entity in ("household", "spm_unit", "tax_unit", "family", "marital_unit"):
            store.put(
                entity,
                pd.DataFrame({f"{entity}_id": [1, 2], f"{entity}_weight": [2.0, 1.0]}),
                format="table",
                data_columns=True,
            )
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    h5 = artifact_root / "populace_us_2024.h5"
    append_native_spm_role(
        parent,
        h5,
        np.array([False, True, True]),
        expected_parent_sha256=enrichment.sha256_file(parent),
    )
    release = tmp_path / "populace-us-2024-test-enrichment"
    release.mkdir()
    parent_payloads = {
        "parent_release_manifest.json": {"schema_version": 1},
        "parent_build_manifest.json": {"calibration": {"old": True}},
        "calibration_diagnostics.json": {"schema_version": 5, "targets": []},
        "us_source_coverage.json": {"schema_version": 1},
    }
    for name, payload in parent_payloads.items():
        _write(release / name, payload)
    pins = {name: enrichment.sha256_file(release / name) for name in parent_payloads}
    monkeypatch.setattr(enrichment, "PARENT_FILES", pins)
    monkeypatch.setattr(
        enrichment, "PARENT_DATASET_SHA256", enrichment.sha256_file(parent)
    )
    counts = {
        "persons_joined": 3,
        "native_spm_units": 2,
        "total_source_people": 3,
        "total_source_units": 2,
        "minor_only_units_resolved": 0,
        "classification_changed_units_vs_age_only": 1,
    }
    monkeypatch.setattr(enrichment, "EXPECTED_COUNTS", counts)
    evidence = release / enrichment.SOURCE_EVIDENCE_FILE
    evidence.write_text(
        "person_id,person_spm_unit_id,is_spm_independence_role\n1,1,False\n2,1,True\n3,2,True\n"
    )
    monkeypatch.setattr(
        enrichment, "SOURCE_EVIDENCE_SHA256", enrichment.sha256_file(evidence)
    )
    provenance = {
        **counts,
        "dataset_sha256": enrichment.PARENT_DATASET_SHA256,
        "unmatched_persons": 0,
        "adult_child_person_count_mismatch_units": 0,
        "complete_source_membership_units": 2,
        "weights_used": False,
        "ages_changed": False,
        "primitive_column": enrichment.ROLE_VARIABLE,
        "evidence_column": enrichment.EVIDENCE_COLUMN,
        "source_checks": [
            {
                "survey_year": year,
                "csv_sha256": csv_sha,
                "adult_child_person_count_mismatch_units": 0,
                **enrichment.CENSUS_ARCHIVE_PINS[year],
            }
            for year, csv_sha in enrichment.CENSUS_PERSON_PINS.items()
        ],
    }
    _write(release / enrichment.SOURCE_PROVENANCE_FILE, provenance)
    dataset = {"filename": h5.name, "sha256": enrichment.sha256_file(h5)}
    build = {
        "build_id": release.name,
        "release_type": "source_enrichment",
        "dataset": dataset,
        "code": {"git_commit": "a" * 40, "git_dirty": False},
        "calibration": {
            "mode": "inherited",
            "parent_build_id": enrichment.PARENT_BUILD_ID,
            "diagnostics_sha256": pins["calibration_diagnostics.json"],
            "diagnostics_schema_version": 5,
        },
    }
    _write(release / "build_manifest.json", build)
    report = {
        "schema_version": 1,
        "release_type": "source_enrichment",
        "operation": "add_native_spm_independent_minor_role",
        "parent": {
            "build_id": enrichment.PARENT_BUILD_ID,
            "repo_id": "policyengine/populace-us",
            "revision": enrichment.PARENT_BUILD_ID,
            "dataset_sha256": enrichment.PARENT_DATASET_SHA256,
            "calibration_diagnostics_schema_version": 5,
            "files": pins,
        },
        "dataset": dataset,
        "added_variable": {
            "name": enrichment.ROLE_VARIABLE,
            "entity": "person",
            "dtype": "bool",
            "age_gate_applied": False,
        },
        "preservation": compare_h5_enrichment(parent, h5),
        "source": {
            "person_evidence_filename": enrichment.SOURCE_EVIDENCE_FILE,
            "person_evidence_sha256": enrichment.sha256_file(evidence),
            "provenance_filename": enrichment.SOURCE_PROVENANCE_FILE,
            "provenance_sha256": enrichment.sha256_file(
                release / enrichment.SOURCE_PROVENANCE_FILE
            ),
        },
        "reconciliation": provenance,
        "compatibility": {"status": "pending"},
    }
    _write(release / enrichment.SOURCE_ENRICHMENT_FILE, report)
    manifest = {
        "schema_version": 1,
        "release_type": "source_enrichment",
        "build": {"build_id": release.name},
        "compatible_core_packages": [],
        "compatible_model_packages": [],
        "default_datasets": {"national": "dataset"},
        "artifacts": {},
    }
    for path in [
        *map(lambda name: release / name, pins),
        release / enrichment.SOURCE_ENRICHMENT_FILE,
        evidence,
        release / enrichment.SOURCE_PROVENANCE_FILE,
        h5,
    ]:
        manifest["artifacts"]["dataset" if path == h5 else path.stem] = {
            "kind": "microdata" if path == h5 else "diagnostics",
            "path": path.name,
            "repo_id": "policyengine/populace-us",
            "revision": release.name,
            "sha256": enrichment.sha256_file(path),
        }
    _write(release / "release_manifest.json", manifest)
    return release, parent, artifact_root


def _validate(candidate, **kwargs):
    release, parent, root = candidate
    return enrichment.validate_source_enrichment_candidate(
        release, parent_h5=parent, artifact_root=root, **kwargs
    )


def _refresh(release, filename):
    manifest_path = release / "release_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["artifacts"].values():
        if entry["path"] == filename:
            entry["sha256"] = enrichment.sha256_file(release / filename)
    _write(manifest_path, manifest)


def test_pending_candidate_is_valid_but_actual_release_gate_refuses(candidate):
    assert _validate(candidate)["compatibility"]["status"] == "pending"
    release, parent, root = candidate
    with pytest.raises(ReleaseContractError, match="compatibility is pending"):
        validate_release_dir(release, parent_h5=parent, artifact_root=root)


def test_publisher_refuses_before_constructing_hub_client(candidate, monkeypatch):
    import microcosm.data.release as release_module

    def no_hub():
        pytest.fail("publisher contacted Hub for a pending enrichment")

    monkeypatch.setattr(release_module, "_hf_api", no_hub)
    release, parent, root = candidate
    with pytest.raises(ReleaseContractError, match="compatibility is pending"):
        publish_release(
            release, "policyengine/populace-us", parent_h5=parent, artifact_root=root
        )


def test_preflight_runs_actual_gate_and_never_publishes(candidate, monkeypatch):
    import microcosm.data.publish_cli as cli

    monkeypatch.setattr(
        cli, "publish_release", lambda *a, **kw: pytest.fail("preflight published")
    )
    release, parent, root = candidate
    with pytest.raises(ReleaseContractError, match="compatibility is pending"):
        publish_main(
            [
                str(release),
                "--parent-h5",
                str(parent),
                "--artifact-root",
                str(root),
                "--preflight-only",
            ]
        )


def test_requires_actual_parent_and_h5(candidate):
    release, _, root = candidate
    with pytest.raises(ReleaseContractError, match="requires parent_h5"):
        enrichment.validate_source_enrichment_candidate(
            release, parent_h5=None, artifact_root=root
        )


def test_schema_five_cannot_be_relabelled_even_with_rehashed_manifests(candidate):
    release, _, _ = candidate
    diagnostics = release / "calibration_diagnostics.json"
    _write(diagnostics, {"schema_version": 6, "targets": []})
    _refresh(release, diagnostics.name)
    with pytest.raises(ReleaseContractError, match="reviewed parent bytes"):
        _validate(candidate)


@pytest.mark.parametrize("field", ["person_weight", "person_spm_unit_id", "age"])
def test_preservation_rejects_changed_old_values(candidate, field):
    release, _, root = candidate
    h5 = root / "populace_us_2024.h5"
    with h5py.File(h5, "r+") as handle:
        table = handle["person/table"]
        row = table[0]
        row[field] += 1
        table[0] = row
    with pytest.raises(ReleaseContractError, match="exact H5 preservation failed"):
        _validate(candidate)


def test_rehashed_role_evidence_attack_still_fails_reviewed_source_pin(candidate):
    release, parent, root = candidate
    path = release / enrichment.SOURCE_EVIDENCE_FILE
    path.write_text(path.read_text().replace("1,1,False", "1,1,True"))
    h5 = root / "populace_us_2024.h5"
    with h5py.File(h5, "r+") as handle:
        table = handle["person/table"]
        row = table[0]
        row[enrichment.ROLE_VARIABLE] = True
        table[0] = row
    report_path = release / enrichment.SOURCE_ENRICHMENT_FILE
    report = json.loads(report_path.read_text())
    report["source"]["person_evidence_sha256"] = enrichment.sha256_file(path)
    report["dataset"]["sha256"] = enrichment.sha256_file(h5)
    report["preservation"] = compare_h5_enrichment(parent, h5)
    _write(report_path, report)
    _refresh(release, path.name)
    _refresh(release, report_path.name)
    with pytest.raises(
        ReleaseContractError, match="independently reviewed Census-derived"
    ):
        _validate(candidate)


def test_pending_candidate_cannot_copy_old_model_claims(candidate):
    release, _, _ = candidate
    path = release / "release_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["build"]["built_with_model_package"] = {
        "name": "policyengine-us",
        "version": "1.764.6",
    }
    manifest["compatible_model_packages"] = [
        {"name": "policyengine-us", "specifier": "==1.764.6"}
    ]
    _write(path, manifest)
    with pytest.raises(
        ReleaseContractError, match="must not claim model/Core compatibility"
    ):
        _validate(candidate)


def test_fabricated_passed_receipt_is_replayed(candidate, monkeypatch):
    release, _, _ = candidate
    report_path = release / enrichment.SOURCE_ENRICHMENT_FILE
    report = json.loads(report_path.read_text())
    receipt = release / enrichment.COMPATIBILITY_FILE
    _write(receipt, {"status": "passed"})
    report["compatibility"] = {
        "status": "passed",
        "filename": receipt.name,
        "sha256": enrichment.sha256_file(receipt),
    }
    _write(report_path, report)
    _refresh(release, report_path.name)
    calls = []

    def actual_test(*args, **kwargs):
        calls.append(kwargs)
        raise ValueError("actual country role is unavailable")

    monkeypatch.setattr(enrichment, "run_native_loader_compatibility", actual_test)
    with pytest.raises(
        ReleaseContractError, match="actual country role is unavailable"
    ):
        _validate(candidate, require_compatibility=True)
    assert calls == [{"require_wheels": True, "compatibility_wheels": ()}]


def test_unknown_release_type_cannot_fall_back_to_calibration(candidate):
    release, _, _ = candidate
    path = release / "release_manifest.json"
    manifest = json.loads(path.read_text())
    manifest["release_type"] = "trust_parent"
    _write(path, manifest)
    with pytest.raises(ReleaseContractError, match="unknown release_type"):
        validate_release_dir(release)


def _qualify_candidate(candidate, tmp_path, monkeypatch):
    from importlib import metadata

    release, parent, root = candidate
    receipt = {
        "status": "passed",
        "dataset_sha256": enrichment.sha256_file(root / "populace_us_2024.h5"),
        "packages": {
            "policyengine-us": {"version": "1.999.0"},
            "policyengine-core": {"version": "3.99.0"},
            "policyengine": {"version": "5.99.0"},
            "spm-calculator": {"version": "1.0.0"},
        },
    }
    calls = []

    def actual_test(*args, **kwargs):
        calls.append(kwargs)
        return receipt

    monkeypatch.setattr(enrichment, "run_native_loader_compatibility", actual_test)
    monkeypatch.setattr(metadata, "version", lambda name: "0.1.0")
    monkeypatch.setattr(
        enrichment, "_check_producer_source_identity", lambda code: None
    )
    output = tmp_path / "certified" / release.name
    result = enrichment.certify_source_enrichment(
        release,
        output,
        parent_h5=parent,
        artifact_root=root,
        compatibility_wheels=(tmp_path / "country.whl",),
    )
    assert result == output
    return output, calls


def test_certification_writes_new_bundle_and_preflight_replays(
    candidate, tmp_path, monkeypatch
):
    release, parent, root = candidate
    original_report = (release / enrichment.SOURCE_ENRICHMENT_FILE).read_bytes()
    output, calls = _qualify_candidate(candidate, tmp_path, monkeypatch)
    assert (release / enrichment.SOURCE_ENRICHMENT_FILE).read_bytes() == original_report
    assert (output / enrichment.SOURCE_EVIDENCE_FILE).read_bytes() == (
        release / enrichment.SOURCE_EVIDENCE_FILE
    ).read_bytes()
    assert (
        publish_main(
            [
                str(output),
                "--parent-h5",
                str(parent),
                "--artifact-root",
                str(root),
                "--compatibility-wheel",
                str(tmp_path / "country.whl"),
                "--preflight-only",
            ]
        )
        == 0
    )
    assert len(calls) == 3  # Test, staged revalidation, then real publisher preflight.
    assert all(call["require_wheels"] for call in calls)


@pytest.mark.parametrize("duplicate", ["identical", "different", "symlink"])
@pytest.mark.parametrize(
    "entrypoint", ["candidate", "preflight", "publisher", "publisher_existing_client"]
)
def test_release_local_h5_duplicate_is_rejected_before_hub_activity(
    candidate, tmp_path, monkeypatch, duplicate, entrypoint
):
    import microcosm.data.release as release_module

    _, parent, root = candidate
    release, _ = _qualify_candidate(candidate, tmp_path, monkeypatch)
    # The unduplicated fixture passes the full gate: pending compatibility or
    # synthetic source identity must not accidentally account for rejection.
    validate_release_dir(release, parent_h5=parent, artifact_root=root)
    h5 = root / "populace_us_2024.h5"
    local = release / h5.name
    if duplicate == "symlink":
        local.symlink_to(h5)
    else:
        shutil.copyfile(h5, local)
        if duplicate == "different":
            with h5py.File(local, "r+") as handle:
                row = handle["person/table"][0]
                row["person_weight"] += 1
                handle["person/table"][0] = row
    monkeypatch.setattr(
        release_module,
        "_hf_api",
        lambda: pytest.fail("duplicate reached Hub client construction"),
    )

    class NoHubActivity:
        def __getattr__(self, name):
            pytest.fail(f"duplicate accessed supplied Hub client: {name}")

    monkeypatch.setattr(
        enrichment,
        "run_native_loader_compatibility",
        lambda *a, **kw: pytest.fail("duplicate reached compatibility probing"),
    )
    with pytest.raises(ReleaseContractError, match="release-local H5"):
        if entrypoint == "candidate":
            _validate((release, parent, root))
        elif entrypoint == "preflight":
            publish_main(
                [
                    str(release),
                    "--parent-h5",
                    str(parent),
                    "--artifact-root",
                    str(root),
                    "--preflight-only",
                ]
            )
        else:
            publish_release(
                release,
                "policyengine/populace-us",
                parent_h5=parent,
                artifact_root=root,
                notify=False,
                api=NoHubActivity()
                if entrypoint == "publisher_existing_client"
                else None,
            )


@pytest.mark.parametrize("year", [2023, 2024, 2025])
@pytest.mark.parametrize(
    "field", ["archive_sha256", "official_archive_url", "member", "income_year"]
)
def test_resealed_provenance_rejects_archive_identity_from_another_year(
    candidate, year, field
):
    other_year = 2023 if year != 2023 else 2024
    replacement = enrichment.CENSUS_ARCHIVE_PINS[other_year][field]
    _assert_resealed_archive_rejected(candidate, year, field, replacement)


@pytest.mark.parametrize("year", [2023, 2024, 2025])
def test_resealed_provenance_rejects_unpinned_archive_sha(candidate, year):
    _assert_resealed_archive_rejected(candidate, year, "archive_sha256", "0" * 64)


def _assert_resealed_archive_rejected(candidate, year, field, replacement):
    assert _validate(candidate)["compatibility"]["status"] == "pending"
    release, _, _ = candidate
    provenance_path = release / enrichment.SOURCE_PROVENANCE_FILE
    provenance = json.loads(provenance_path.read_text())
    row = next(row for row in provenance["source_checks"] if row["survey_year"] == year)
    row[field] = replacement
    _write(provenance_path, provenance)
    report_path = release / enrichment.SOURCE_ENRICHMENT_FILE
    report = json.loads(report_path.read_text())
    report["source"]["provenance_sha256"] = enrichment.sha256_file(provenance_path)
    report["reconciliation"] = provenance
    _write(report_path, report)
    _refresh(release, provenance_path.name)
    _refresh(release, report_path.name)
    with pytest.raises(
        ReleaseContractError, match=f"Census {year} pinned archive {field} differs"
    ):
        _validate(candidate)


def test_native_compatibility_requires_wheels_for_all_runtime_packages():
    with pytest.raises(ValueError, match="exact installed policyengine-us"):
        enrichment._runtime_package_identities((), require_wheels=True)


@pytest.mark.parametrize("distribution_name", ["policyengine-us", "spm-calculator"])
def test_wheel_identity_rejects_changed_installed_source(
    tmp_path, monkeypatch, distribution_name
):
    from importlib import metadata
    from zipfile import ZipFile

    package = tmp_path / "pkg"
    package.mkdir()
    (package / "module.py").write_text("VALUE = 2\n")
    normalized = distribution_name.replace("-", "_")
    wheel = tmp_path / f"{normalized}-1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"{normalized}-1.0.dist-info/METADATA",
            f"Name: {distribution_name}\nVersion: 1.0\n",
        )
        archive.writestr("pkg/module.py", "VALUE = 1\n")

    class Installed:
        version = "1.0"
        files = ["pkg/module.py"]

        def read_text(self, name):
            return None

        def locate_file(self, relative):
            return tmp_path / relative

    monkeypatch.setattr(metadata, "distribution", lambda name: Installed())
    with pytest.raises(ValueError, match="installed source differs from wheel"):
        enrichment._runtime_package_identities((wheel,), require_wheels=False)


def test_three_wheels_cannot_omit_calculator(tmp_path, monkeypatch):
    monkeypatch.setattr(enrichment, "_wheel_files", lambda path: (path.stem, "1.0", {}))
    wheels = tuple(
        tmp_path / f"{name}.whl"
        for name in ("policyengine-us", "policyengine-core", "policyengine")
    )
    with pytest.raises(ValueError, match="spm-calculator wheels"):
        enrichment._runtime_package_identities(wheels, require_wheels=True)


def test_registered_native_role_is_owned_by_calculator_wheel(tmp_path, monkeypatch):
    import importlib
    from importlib import metadata
    from types import SimpleNamespace

    monkeypatch.setattr(
        metadata,
        "distribution",
        lambda name: SimpleNamespace(locate_file=lambda relative: tmp_path / relative),
    )
    imported = []

    def module(name):
        imported.append(name)
        return SimpleNamespace(__file__=str(tmp_path / name / "__init__.py"))

    monkeypatch.setattr(importlib, "import_module", module)
    paths = {
        "country_loader": tmp_path / "policyengine_us/data/dataset_schema.py",
        "wrapper_loader": tmp_path / "policyengine/tax_benefit_models/us/datasets.py",
        "native_role": tmp_path / "spm_calculator/policyengine_adapter.py",
    }
    enrichment._check_loaded_source_ownership(paths)
    assert set(imported) == {
        "policyengine_us",
        "policyengine_core",
        "policyengine",
        "spm_calculator",
    }
    # A same-named country class or source outside the verified calculator is
    # not the production calculator-owned primitive.
    for replacement in (
        tmp_path / "policyengine_us/native_role.py",
        tmp_path / "unverified_calculator/policyengine_adapter.py",
    ):
        with pytest.raises(ValueError, match="native_role.*spm-calculator wheel"):
            enrichment._check_loaded_source_ownership(
                paths | {"native_role": replacement}
            )


def test_evidence_tier_cannot_bypass_enrichment_gate(candidate):
    from microcosm.data.contract import validate_evidence_release_dir

    release, _, _ = candidate
    with pytest.raises(ReleaseContractError, match="evidence tier does not accept"):
        validate_evidence_release_dir(release)


def test_core_probe_rejects_silently_discarded_native_input(candidate, monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    import pandas as pd

    _, _, root = candidate
    with pd.HDFStore(root / "populace_us_2024.h5", "r") as store:
        tables = {
            entity: store[entity]
            for entity in (
                "person",
                "household",
                "tax_unit",
                "spm_unit",
                "family",
                "marital_unit",
            )
        }
    for entity in ("tax_unit", "family", "marital_unit"):
        tables["person"][f"person_{entity}_id"] = tables["person"][
            "person_household_id"
        ]
    calls = []

    class IgnoresInput:
        def __init__(self, dataset):
            calls.append(dataset)
            self.dataset = dataset

        def calculate(self, variable, year):
            return np.zeros(len(self.dataset.person), dtype=bool)

    fake_country = ModuleType("policyengine_us")
    fake_country.Microsimulation = IgnoresInput
    fake_data = ModuleType("policyengine_us.data")
    fake_data.USSingleYearDataset = lambda **kwargs: SimpleNamespace(**kwargs)
    monkeypatch.setitem(sys.modules, "policyengine_us", fake_country)
    monkeypatch.setitem(sys.modules, "policyengine_us.data", fake_data)
    with pytest.raises(ValueError, match="discarded the supplied native person role"):
        enrichment._check_native_input_precedence(SimpleNamespace(**tables))
    assert len(calls) == 2
    assert all(len(dataset.person) == 2 for dataset in calls)
    assert all(
        dataset.person["person_spm_unit_id"].tolist() == [1, 1] for dataset in calls
    )


def test_producer_identity_rejects_fabricated_clean_commit():
    code = {
        "git_commit": "0" * 40,
        "git_dirty": False,
        "source_files_sha256": {
            name: "a" * 64 for name in enrichment.PRODUCER_SOURCE_FILES
        },
    }
    with pytest.raises(ValueError, match="cannot be authenticated"):
        enrichment._check_producer_source_identity(code)


def test_producer_identity_rejects_uncommitted_source_mutation(tmp_path, monkeypatch):
    import hashlib
    import subprocess
    from pathlib import Path
    from types import SimpleNamespace

    root = Path(__file__).resolve().parents[3]
    commit = "a" * 40
    sources = {
        name: (root / name).read_bytes() for name in enrichment.PRODUCER_SOURCE_FILES
    }
    for name, content in sources.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    changed = tmp_path / enrichment.PRODUCER_SOURCE_FILES[0]
    changed.write_bytes(changed.read_bytes() + b"\n# uncommitted source edit\n")
    code = {
        "git_commit": commit,
        "git_dirty": False,
        "source_files_sha256": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in sources.items()
        },
    }

    def git_result(args, **kwargs):
        if args[1:] == ["rev-parse", "--show-toplevel"]:
            return SimpleNamespace(stdout=str(tmp_path).encode())
        if args[1] == "rev-parse":
            return SimpleNamespace(stdout=commit.encode())
        return SimpleNamespace(stdout=sources[args[2].split(":", 1)[1]])

    monkeypatch.setattr(subprocess, "run", git_result)
    with pytest.raises(ValueError, match="checkout source differs"):
        enrichment._check_producer_source_identity(code)
