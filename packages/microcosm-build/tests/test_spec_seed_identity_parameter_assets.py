"""Invented package inputs and real refusal probes; no engine or data import."""

import base64
import builtins
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def diagnostic():
    source = (
        Path(__file__).resolve().parents[3] / "tools/spec_seed_identity_diagnostics.py"
    )
    spec = importlib.util.spec_from_file_location("parameter_asset_controls", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def invented_package(diagnostic, monkeypatch, tmp_path):
    prefix = tmp_path / "venv"
    site = prefix / "site-packages"
    package = site / "policyengine_us"
    path = package / "parameters/gov/invented.csv"
    path.parent.mkdir(parents=True)
    content = b"invented,value\nA,1\n"
    path.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    record = importlib.metadata.PackagePath(
        "policyengine_us/parameters/gov/invented.csv"
    )
    record.size = len(content)
    record.hash = SimpleNamespace(
        mode="sha256",
        value=base64.urlsafe_b64encode(bytes.fromhex(sha)).decode().rstrip("="),
    )
    distribution = SimpleNamespace(
        version=diagnostic.PARAMETER_ASSET_VERSION,
        files=[record],
        locate_file=lambda name: site / str(name),
    )
    spec = SimpleNamespace(
        origin=str(package / "__init__.py"), submodule_search_locations=[str(package)]
    )
    monkeypatch.setattr(
        diagnostic, "PARAMETER_ASSETS", (("gov/invented.csv", len(content), sha),)
    )
    monkeypatch.setattr(diagnostic.sys, "prefix", str(prefix))
    monkeypatch.setattr(
        diagnostic.importlib.metadata, "distribution", lambda _: distribution
    )
    monkeypatch.setattr(diagnostic.importlib.util, "find_spec", lambda _: spec)
    hooks = []
    monkeypatch.setattr(diagnostic.sys, "addaudithook", hooks.append)
    policy = diagnostic.VerifiedParameterAssets()
    refusals = diagnostic.install_boundary(
        tmp_path / "repo",
        tmp_path / "owned",
        tmp_path / "output",
        parameter_assets=policy,
    )
    return SimpleNamespace(
        path=path,
        package=package,
        record=record,
        distribution=distribution,
        spec=spec,
        policy=policy,
        hook=hooks[0],
        refusals=refusals,
        content=content,
    )


def test_exact_record_and_bytes_enable_only_read_access(diagnostic, invented_package):
    case = invented_package
    with pytest.raises(diagnostic.RefusalError, match="^DATA_FILE$"):
        case.hook("open", (str(case.path), "r", os.O_RDONLY))
    evidence = {}
    case.policy.verify(evidence)
    case.hook("open", (str(case.path), "r", os.O_RDONLY))
    assert case.policy.permits(case.path, writing=False)
    assert not case.policy.permits(case.path, writing=True)
    assert evidence["engine_parameter_assets"]["assets"] == [
        {
            "path": str(case.record),
            "size_bytes": len(case.content),
            "sha256": hashlib.sha256(case.content).hexdigest(),
        }
    ]
    assert (
        evidence["engine_parameter_assets"]["record_origin_and_content_verified"]
        is True
    )
    # A recheck retains exactly the same declaration; it creates no new grant.
    case.policy.verify(evidence)
    assert case.policy._verified == frozenset({case.path})


@pytest.mark.parametrize(
    "kind",
    (
        "version",
        "record_hash",
        "record_size",
        "duplicate",
        "origin",
        "bytes",
        "size",
        "symlink",
    ),
)
def test_invalid_package_input_never_grants_reads(diagnostic, invented_package, kind):
    case = invented_package
    code = "PARAMETER_CONTENT"
    if kind == "version":
        case.distribution.version = "unreviewed"
        code = "PARAMETER_VERSION"
    elif kind == "record_hash":
        case.record.hash.value = "wrong"
        code = "PARAMETER_RECORD"
    elif kind == "record_size":
        case.record.size += 1
        code = "PARAMETER_RECORD"
    elif kind == "duplicate":
        case.distribution.files.append(case.record)
        code = "PARAMETER_RECORD"
    elif kind == "origin":
        case.spec.origin = str(case.package / "different.py")
        code = "PARAMETER_ORIGIN"
    elif kind == "bytes":
        case.path.write_bytes(case.content.replace(b"1", b"2"))
    elif kind == "size":
        case.path.write_bytes(case.content + b"changed")
    else:
        other = case.path.with_name("other.csv")
        other.write_bytes(case.content)
        case.path.unlink()
        case.path.symlink_to(other)
        code = "PARAMETER_ORIGIN"
    with pytest.raises(diagnostic.RefusalError, match="^" + code + "$"):
        case.policy.verify({})
    assert case.policy._verified == frozenset()
    assert case.policy._checking is None


def test_changed_bytes_revoke_a_previously_verified_roster(
    diagnostic, invented_package
):
    case = invented_package
    case.policy.verify({})
    case.path.write_bytes(case.content.replace(b"1", b"2"))
    with pytest.raises(diagnostic.RefusalError, match="^PARAMETER_CONTENT$"):
        case.policy.verify({})
    with pytest.raises(diagnostic.RefusalError, match="^DATA_FILE$"):
        case.hook("open", (str(case.path), "r", os.O_RDONLY))


@pytest.mark.parametrize(
    "kind", ("neighbor", "outside", "h5", "parquet", "gzip", "write", "read_write")
)
def test_roster_does_not_admit_other_data_or_asset_mutations(
    diagnostic, invented_package, kind
):
    case = invented_package
    case.policy.verify({})
    path = {
        "neighbor": case.path.with_name("neighbor.csv"),
        "outside": case.package.parent / "invented.csv",
        "h5": case.path.with_suffix(".h5"),
        "parquet": case.path.with_suffix(".parquet"),
        "gzip": case.path.with_suffix(".gz"),
        "write": case.path,
        "read_write": case.path,
    }[kind]
    flags = {"write": os.O_WRONLY, "read_write": os.O_RDWR}.get(kind, os.O_RDONLY)
    with pytest.raises(diagnostic.RefusalError, match="^DATA_FILE$"):
        case.hook("open", (str(path), "r", flags))


@pytest.fixture
def invented_urllib3(diagnostic, monkeypatch, tmp_path):
    package = tmp_path / "urllib3"
    spec = SimpleNamespace(
        origin=str(package / "__init__.py"), submodule_search_locations=[str(package)]
    )
    distribution = SimpleNamespace(
        version=diagnostic.URLLIB3_VERSION, locate_file=lambda _: package
    )
    monkeypatch.setattr(diagnostic.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(
        diagnostic.importlib.metadata, "distribution", lambda _: distribution
    )
    monkeypatch.setattr(diagnostic.importlib.util, "find_spec", lambda _: spec)
    for name in tuple(sys.modules):
        if name == "urllib3" or name.startswith("urllib3."):
            monkeypatch.delitem(sys.modules, name)
    connection = SimpleNamespace(
        __file__=str(package / "util/connection.py"),
        HAS_IPV6=False,
        allowed_gai_family=lambda: socket.AF_INET,
    )
    case = SimpleNamespace(
        package=package,
        connection=connection,
        fail=False,
        distribution=distribution,
        spec=spec,
    )
    original_import = builtins.__import__

    def import_dependency(name, *args, **kwargs):
        if name != "urllib3.util":
            return original_import(name, *args, **kwargs)
        assert socket.has_ipv6 is False
        if case.fail:
            raise RuntimeError("invented import failure")
        monkeypatch.setitem(
            sys.modules,
            "urllib3",
            SimpleNamespace(__file__=str(package / "__init__.py")),
        )
        return SimpleNamespace(connection=connection)

    monkeypatch.setattr(builtins, "__import__", import_dependency)
    return case


@pytest.mark.parametrize("fails", (False, True))
def test_ipv4_bootstrap_restores_scalar_and_preserves_callables(
    diagnostic, invented_urllib3, fails
):
    case = invented_urllib3
    case.fail = fails
    original = socket.has_ipv6
    callables = (socket.socket, socket.getaddrinfo, socket.create_connection)
    evidence = {}
    if fails:
        with pytest.raises(RuntimeError, match="invented import failure"):
            diagnostic.bootstrap_no_network_urllib3(evidence)
    else:
        diagnostic.bootstrap_no_network_urllib3(evidence)
    assert socket.has_ipv6 is original
    assert callables == (socket.socket, socket.getaddrinfo, socket.create_connection)
    assert evidence["urllib3"]["socket_flag_restored"] is True
    assert evidence["urllib3"]["socket_callables_unchanged"] is True
    assert evidence["urllib3"]["ipv4_fallback_verified"] is not fails


@pytest.mark.parametrize("kind", ("preloaded", "version", "origin", "fallback"))
def test_unreviewed_urllib3_path_refuses(
    diagnostic, invented_urllib3, monkeypatch, kind
):
    case = invented_urllib3
    code = "URLLIB3_" + kind.upper()
    if kind == "preloaded":
        monkeypatch.setitem(sys.modules, "urllib3.util", SimpleNamespace())
    elif kind == "version":
        case.distribution.version = "unreviewed"
    elif kind == "origin":
        case.spec.origin = "/outside/urllib3/__init__.py"
    else:
        case.connection.HAS_IPV6 = True
    original = socket.has_ipv6
    with pytest.raises(diagnostic.RefusalError, match="^" + code + "$"):
        diagnostic.bootstrap_no_network_urllib3({})
    assert socket.has_ipv6 is original


def test_non_stdlib_socket_origin_refuses_before_scalar_change(
    diagnostic, invented_urllib3, monkeypatch
):
    original = socket.has_ipv6
    monkeypatch.setattr(socket, "__file__", "/invented/socket.py")
    with pytest.raises(diagnostic.RefusalError, match="^SOCKET_ORIGIN$"):
        diagnostic.bootstrap_no_network_urllib3({})
    assert socket.has_ipv6 is original


def test_real_audit_still_refuses_socket_and_child_before_either_is_created(
    diagnostic, tmp_path
):
    # Only the harness starts a child. The child installs the real audit hook;
    # its own attempted network and child operations must both stop at that hook.
    script = """
import base64, hashlib, importlib.util, json, pathlib, socket, subprocess, sys
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location('diagnostic', sys.argv[1])
diagnostic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnostic)
root = pathlib.Path(sys.argv[2])
prefix = root / 'environment'
package = prefix / 'policyengine_us'
asset = package / 'parameters/gov/invented.csv'
asset.parent.mkdir(parents=True)
content = b'invented,value\\nA,1\\n'
asset.write_bytes(content)
sha = hashlib.sha256(content).hexdigest()
record = diagnostic.importlib.metadata.PackagePath('policyengine_us/parameters/gov/invented.csv')
record.size = len(content)
record.hash = SimpleNamespace(mode='sha256', value=base64.urlsafe_b64encode(bytes.fromhex(sha)).decode().rstrip('='))
diagnostic.PARAMETER_ASSETS = (('gov/invented.csv', len(content), sha),)
distribution = SimpleNamespace(version=diagnostic.PARAMETER_ASSET_VERSION, files=[record], locate_file=lambda name: prefix / str(name))
diagnostic.importlib.metadata.distribution = lambda _: distribution
diagnostic.importlib.util.find_spec = lambda _: SimpleNamespace(origin=str(package / '__init__.py'), submodule_search_locations=[str(package)])
sys.prefix = str(prefix)
policy = diagnostic.VerifiedParameterAssets()
refusals = diagnostic.install_boundary(root, root / 'owned', root / 'output', parameter_assets=policy)
policy.verify({})
assert asset.read_bytes() == content
policy.verify({})
assert not refusals
observed = []
for action in (lambda: socket.socket(socket.AF_INET), lambda: subprocess.run([sys.executable, '-c', 'raise SystemExit(99)'])):
    try:
        action()
    except diagnostic.RefusalError as error:
        observed.append(str(error))
assert observed == ['NETWORK_OR_CHILD', 'NETWORK_OR_CHILD']
assert refusals == ['NETWORK_OR_CHILD']
print(json.dumps(observed))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, diagnostic.__file__, str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout) == ["NETWORK_OR_CHILD", "NETWORK_OR_CHILD"]
