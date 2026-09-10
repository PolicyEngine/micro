"""Source pins and unreduced-register ownership in the full UK target path."""

from datetime import date
from types import SimpleNamespace

import pytest

from microcosm.build.uk_runtime import full_targets as runtime
from microcosm.calibrate import TargetRegistry, TargetSpec


def _registry(*names):
    return TargetRegistry(
        [
            TargetSpec(
                name=name,
                entity="person",
                value=1.0,
                measure="age",
                period=2024,
                source="test",
                family="population",
                metadata={"contract_target_id": name},
            )
            for name in names
        ],
        country="uk",
    )


@pytest.fixture
def prepared(monkeypatch):
    national = _registry("retained", "excluded")
    approved = _registry("retained")
    local = _registry("local")
    calls = []
    artifact = SimpleNamespace(
        facts=({"test": True},), facts_sha256="a" * 64, manifest_sha256="b" * 64
    )
    pin = SimpleNamespace(
        facts_sha256=artifact.facts_sha256,
        manifest_sha256=artifact.manifest_sha256,
        to_dict=lambda: {
            "facts_sha256": artifact.facts_sha256,
            "manifest_sha256": artifact.manifest_sha256,
        },
    )
    monkeypatch.setattr(runtime, "load_uk_national_chronicle_feed", lambda: pin)
    monkeypatch.setattr(
        runtime, "load_ledger_consumer_artifact", lambda *a, **kw: artifact
    )
    monkeypatch.setattr(runtime, "load_uk_local_area_crosswalk", lambda: {})

    def compile_national(facts, *, target_period):
        calls.append(("national", target_period))
        return SimpleNamespace(registry=national, unsupported=())

    def compile_local(facts, *, target_period, crosswalk):
        calls.append(("local", target_period))
        return SimpleNamespace(registry=local, unsupported=())

    monkeypatch.setattr(runtime, "compile_uk_target_registry", compile_national)
    monkeypatch.setattr(runtime, "compile_uk_local_target_registry", compile_local)
    monkeypatch.setattr(
        runtime, "load_uk_calibration_measure_exclusions", lambda path: ()
    )
    monkeypatch.setattr(
        runtime,
        "apply_uk_calibration_measure_exclusions",
        lambda registry, exclusions, now: (
            approved,
            {"excluded": {"reason": "reviewed"}},
        ),
    )
    return national, approved, local, artifact, calls


def _load(**kwargs):
    return runtime.load_uk_full_target_inputs(
        "facts.jsonl",
        calibration_year=2024,
        exclusions_evaluated_on=date(2026, 9, 10),
        **kwargs,
    )


def test_full_inputs_preserve_band_edges_and_validation_periods(prepared):
    national, approved, local, artifact, calls = prepared
    result = _load()
    assert result["artifact"] is artifact
    assert result["band_edge_registry"] is national
    assert result["national_registry"] is approved
    assert result["local_registry"] is local
    assert calls == [
        ("national", 2023),
        ("national", 2024),
        ("national", 2025),
        ("local", 2024),
        ("local", 2025),
    ]
    assert result["register_completeness"]["compiled_reference_count"] == 2
    assert result["register_completeness"]["approved_reference_count"] == 1
    assert result["reviewed_unbound_higher_targets"] == {
        "excluded": {"reason": "reviewed"}
    }


def test_source_pin_mismatch_refuses_before_read(prepared, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "load_ledger_consumer_artifact",
        lambda *a, **kw: pytest.fail("source read before pin agreement"),
    )
    with pytest.raises(ValueError, match="committed national feed"):
        _load(expected_facts_sha256="c" * 64)


def test_loaded_source_mismatch_refuses(prepared):
    prepared[3].manifest_sha256 = "c" * 64
    with pytest.raises(ValueError, match="Ledger artifact"):
        _load()


def test_frozen_register_compares_complete_not_measure_pruned_surface(
    prepared, tmp_path
):
    path = tmp_path / "register.json"
    prepared[0].to_json(path)
    assert (
        _load(register_json=path)["register_completeness"]["frozen_registry_version"]
        == prepared[0].version
    )
    prepared[1].to_json(path)
    with pytest.raises(ValueError, match="full national register differs"):
        _load(register_json=path)


def test_validation_reference_compilation_is_fail_closed(prepared, monkeypatch):
    monkeypatch.setattr(
        runtime,
        "compile_uk_target_registry",
        lambda *a, **kw: SimpleNamespace(
            registry=prepared[0], unsupported=({"target": "missing"},)
        ),
    )
    with pytest.raises(ValueError, match="failed to compile for 2023"):
        _load()
