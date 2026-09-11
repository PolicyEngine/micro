from __future__ import annotations

import hashlib
import json
from importlib.resources import files

import pytest


def test_national_feed_records_the_complete_merged_source_artifact():
    from microcosm.build.uk_runtime.national_chronicle_feed import (
        load_uk_national_chronicle_feed,
    )

    pin = load_uk_national_chronicle_feed()
    resource = files("microcosm.build.uk").joinpath("national_chronicle_feed.json")
    raw = resource.read_bytes()
    assert pin.source_commit == "c6f9361492056b9fab7b8535a2be77eb2b6c93bb"
    assert pin.source_repo == "PolicyEngine/chronicle"
    assert pin.fact_row_count == 138847
    assert pin.facts_sha256 == (
        "45bda3ae730d4ae3fa059d9e03304e902f7f6e74c5099355ef937625ca03b72b"
    )
    assert pin.manifest_sha256 == (
        "33a3031523e2cea2f0092a547b97065efbe103cdf85f842142e847b921bcdd9d"
    )
    assert pin.artifact_schema_version == "policyengine_ledger.consumer_artifact.v2"
    assert pin.consumer_fact_schema_sha256 == (
        "72ad3149564f8aab3e9bb6de5ea25950c8e19a3e8402e2cdcfc52d250bc8ee82"
    )
    assert pin.resource_sha256 == hashlib.sha256(raw).hexdigest()
    assert pin.resource_size_bytes == len(raw)
    assert pin.to_dict()["source_commit"] == pin.source_commit


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("facts_sha256", "not-a-digest"),
        ("manifest_sha256", "A" * 64),
        ("consumer_fact_schema_sha256", "a" * 63),
        ("source_commit", "ec7169b5"),
        ("fact_row_count", True),
        ("country", "us"),
    ],
)
def test_national_feed_rejects_malformed_identity(
    monkeypatch, tmp_path, field, bad_value
):
    from microcosm.build.uk_runtime import national_chronicle_feed

    raw = json.loads(national_chronicle_feed._feed_path().read_text())
    raw[field] = bad_value
    path = tmp_path / "pin.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setattr(national_chronicle_feed, "_feed_path", lambda: path)

    with pytest.raises(ValueError, match=field):
        national_chronicle_feed.load_uk_national_chronicle_feed()
