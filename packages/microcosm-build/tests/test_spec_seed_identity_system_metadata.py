"""Invented metadata controls; no main, engine, data, child or real audit hook."""

import importlib.util
import os
import platform
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def diagnostic():
    source = (
        Path(__file__).resolve().parents[3] / "tools/spec_seed_identity_diagnostics.py"
    )
    spec = importlib.util.spec_from_file_location("system_metadata_controls", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def invented_uname(diagnostic, monkeypatch):
    observed = SimpleNamespace(
        sysname="Linux",
        nodename="invented-host",
        release="invented-release",
        version="invented-version",
        machine="invented_arch",
    )
    info = platform.uname_result(
        observed.sysname,
        observed.nodename,
        observed.release,
        observed.version,
        observed.machine,
    )
    monkeypatch.setattr(diagnostic.sys, "platform", "linux")
    monkeypatch.setattr(diagnostic.os, "uname", lambda: observed)
    monkeypatch.setattr(diagnostic.platform, "uname", lambda: info)

    def forbidden(*args, **kwargs):
        pytest.fail("processor metadata attempted a subprocess")

    monkeypatch.setattr(subprocess, "check_output", forbidden)
    return info, observed


def test_real_cached_property_uses_machine_without_replacing_stdlib(
    diagnostic, invented_uname
):
    info, observed = invented_uname
    before = (
        platform.uname,
        platform.processor,
        platform.uname_result,
        vars(type(info))["processor"],
    )
    bootstrap = {}
    state = diagnostic.prime_processor_metadata(bootstrap)
    assert platform.processor() == observed.machine
    assert tuple(info) == (
        observed.sysname,
        observed.nodename,
        observed.release,
        observed.version,
        observed.machine,
        observed.machine,
    )
    assert bootstrap["system_metadata"]["uname_p_parity_claimed"] is False
    assert bootstrap["system_metadata"]["source"] == "os.uname.machine"
    assert before == (
        platform.uname,
        platform.processor,
        platform.uname_result,
        vars(type(info))["processor"],
    )
    diagnostic.verify_processor_metadata(state, bootstrap)
    # An already-cached identical machine value is not silently altered.
    again = diagnostic.prime_processor_metadata(bootstrap)
    assert again == state


def test_conflicting_observed_processor_cache_is_not_overwritten(
    diagnostic, invented_uname
):
    info, _ = invented_uname
    info.processor = "different_observed_processor"
    bootstrap = {}
    with pytest.raises(diagnostic.RefusalError, match="^PROCESSOR_CACHE_CONFLICT$"):
        diagnostic.prime_processor_metadata(bootstrap)
    assert info.processor == "different_observed_processor"
    assert bootstrap == {}


@pytest.mark.parametrize("change", ("cached_value", "os_machine", "evidence"))
def test_metadata_change_refuses(diagnostic, invented_uname, change):
    info, observed = invented_uname
    bootstrap = {}
    state = diagnostic.prime_processor_metadata(bootstrap)
    if change == "cached_value":
        info.processor = "changed"
    elif change == "os_machine":
        observed.machine = "changed"
    else:
        bootstrap["system_metadata"]["uname_p_parity_claimed"] = True
    with pytest.raises(diagnostic.RefusalError, match="^PROCESSOR_METADATA_CHANGED$"):
        diagnostic.verify_processor_metadata(state, bootstrap)


@pytest.fixture
def audited(diagnostic, monkeypatch):
    hooks = []
    monkeypatch.setattr(diagnostic.sys, "addaudithook", hooks.append)
    monkeypatch.setattr(diagnostic.os, "getpid", lambda: 321)
    monkeypatch.setattr(diagnostic.os, "readlink", lambda _: "pipe:[invented]")
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: Path("/invented/repo")))

    def resolve(path):
        return Path("/proc/321/maps") if path == Path("/proc/self/maps") else path

    monkeypatch.setattr(Path, "resolve", resolve)
    refusals = diagnostic.install_boundary(
        Path("/invented/repo"), Path("/invented/owned"), Path("/invented/output")
    )
    assert len(hooks) == 1
    return hooks[0], refusals


@pytest.mark.parametrize("path", ("/proc/self/maps", "/proc/321/maps"))
def test_only_logical_and_resolved_own_maps_are_admitted(audited, path):
    hook, refusals = audited
    hook("open", (path, "r", os.O_RDONLY))
    assert refusals == []


@pytest.mark.parametrize(
    "kind", ("other_process", "other_file", "relative", "descriptor", "child")
)
def test_maps_alias_does_not_admit_other_paths_descriptors_or_children(
    diagnostic, audited, kind
):
    hook, refusals = audited
    path = {
        "other_process": "/proc/322/maps",
        "other_file": "/proc/321/mem",
        "relative": "maps",
        "descriptor": 55,
        "child": None,
    }[kind]
    code = "NETWORK_OR_CHILD" if kind == "child" else "READ_SCOPE"
    with pytest.raises(diagnostic.RefusalError, match="^" + code + "$"):
        if kind == "child":
            hook("subprocess.Popen", ("uname", ["uname", "-p"], None, None))
        else:
            hook("open", (path, "r", os.O_RDONLY))
    assert refusals == [code]
