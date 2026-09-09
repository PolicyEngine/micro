# Native SPM role source-enrichment release

This lane creates a **new H5** from the reviewed BuildP population by adding
`is_spm_independent_minor_role` to its native person table. It performs no
calibration, population aging, weight adjustment, geography assignment, or
membership reconstruction. The country and wrapper use their existing H5
loaders. The keyed CSV is immutable source evidence, not a runtime join.

The supported parent is
`populace-us-2024-buildp-sparse-rmloss100-cae8640-20260728T011454Z`, H5 SHA256
`48b9d479fb4fd1c3537f9383ce4697d130b6f618658409d74f6233c43b994c7e`.
The data contract pins its original release/build manifests, schema-5
calibration diagnostics, and source coverage evidence by SHA256. This is
explicit inheritance of those measurements. It does not upgrade diagnostics
to schema 6 or assert that they measured a new model's results. Ordinary
calibration releases still require schema 6. A different parent requires a
separately reviewed contract; there is no caller-supplied legacy-schema waiver.

## Source reconstruction and exact preservation

`spm_role_source.py` reuses Microcosm's existing Census ASEC archive/member
pins from `education_assistance_source.py`. The complete source person CSVs
are `pppub23.csv`, `pppub24.csv`, and `pppub25.csv` (income years 2022–2024).
The release gate independently checks each survey year's exact archive SHA256,
official URL, person member and income year, alongside its existing CSV pin.
Rehashing provenance and enclosing manifests cannot authorize another archive.
The source role is:

```python
(SPM_HEAD == 1) | (A_FAMTYP.isin([1, 4]) & A_FAMREL.isin([1, 2]))
```

The stored Boolean is the role **before** the age gate. Reconciliation uses
`age >= 18 OR (age >= 15 AND role)` to reproduce `SPM_NUMADULTS`,
`SPM_NUMKIDS`, and `SPM_NUMPER` for all 176,039 source units and 59,900 native
BuildP units. This is an inference from documented relationships, exhaustively
checked for these sources; it is not a claim to possess the Census production
program. New source vintages must pass reconciliation independently.

The join uses income/source year and exact 22-digit string `PERIDNUM`.
Repeated source people across support clones are allowed; missing matches,
ambiguous source IDs, repeated people within one native SPM unit, partial
source units, and inconsistent raw fields are refused. Older missing
relationship cells remain missing. Existing model ages must equal observed
source ages. No weights enter the reconciliation.

BuildP uses a PyTables compound dataset at `/person/table`. Adding a native
column necessarily extends that compound type; a new unrelated H5 group would
be ignored by the existing country loader. The only permitted physical schema
changes are:

- Append one HDF bitfield byte (pandas Boolean) after every original record's
  bytes. All original field names, order, offsets, types, shapes, and bytes
  remain exact, including NaN payloads and signed zero.
- Append the new column's registration to the four `/person` attributes
  `data_columns`, `values_cols`, `non_index_axes`, and `info`, and add its five
  PyTables field attributes. Every existing registration entry remains intact.

All other H5 groups, datasets, indexes, types, shapes, attributes, and bytes
are compared against the actual parent. Thus logical pre-existing variable
identity is exact; the enclosing compound datatype is explicitly extended.
The builder copies the parent and does not repack it, so the new file can
retain unused space from the replaced person table. New HDF object timestamps
are disabled for deterministic output within the recorded runtime.

The generated three-column evidence CSV must also match independently reviewed
SHA256 `22b5968d90fecfeef7614583e493fe10cc16bda8b5be82e6f49a5bc2102d3ce5`.
The CSV is never used to derive the role. Parent and source evidence are copied
unchanged into the release bundle; H5 and evidence files are read-only on exit.
The H5 belongs only in `artifact_root`, for upload at its manifest-declared root
path. A same-named entry in the release directory is rejected before compatibility
probing or Hub client activity, including identical copies and symlinks: either
would otherwise change the publisher's upload destination.

## Build and validate a local candidate

Use the repository's installed environment. These commands do not fetch data,
calibrate, or publish. Populate the source cache through the existing pinned
Census source acquisition pipeline, or supply its directory explicitly.
The parent evidence directory contains the original `release_manifest.json`,
`build_manifest.json`, `calibration_diagnostics.json`, and
`us_source_coverage.json`.

```bash
python tools/build_us_spm_role_enrichment.py \
  --parent-h5 /path/to/certified/populace_us_2024.h5 \
  --parent-release-dir /path/to/buildp-release-source-receipts \
  --source-cache /path/to/pinned/census-person-csvs \
  --reference-evidence-csv /path/to/source-spm-person-independence-private.csv \
  --output-dir /path/to/new-candidate \
  --release-id populace-us-2024-buildp-spm-role-REVIEWED-NEW-ID

python -m microcosm.data.source_enrichment \
  --release-dir /path/to/new-candidate/releases/RELEASE_ID \
  --parent-h5 /path/to/certified/populace_us_2024.h5 \
  --artifact-root /path/to/new-candidate/artifacts
```

The candidate has `release_type: source_enrichment` and
`compatibility.status: pending`. It includes no inherited built-with or model
compatibility claims. An existing output directory is refused, and a failed
build removes its staging output. Its producer receipt identifies the actual
Git commit, dirty status, and source files. Rebuild from the reviewed clean
producer commit before certification; do not edit a dirty receipt to say clean.
The producer also records Python, HDF5, NumPy, pandas, h5py, PyTables, and data
package versions so serialization can be reproduced in the same runtime.

## Actual compatibility, preflight, and authorized publication

Install the actual country, Core, wrapper, and `spm-calculator` wheels in an
isolated qualification environment. These may be local candidate wheels; prior
registry publication or wrapper certification on the new H5 is not required.
Certification runs the real country and wrapper
native H5 loaders, verifies the role, IDs, memberships and existing weights,
checks that the country registers a person Boolean variable, and calculates
only the primitive on a small complete native household to prove explicit
inputs override its default formula. It does not run a population simulation.
Installed Python sources must match all four supplied wheels and their versions.
The country registers the native role class supplied by
`spm_calculator/policyengine_adapter.py`; its source is bound to the calculator
wheel, while country and wrapper loader sources bind to their respective wheels.

```bash
python -m microcosm.data.source_enrichment --certify \
  --release-dir /path/to/new-candidate/releases/RELEASE_ID \
  --output-dir /path/to/certified/releases/RELEASE_ID \
  --parent-h5 /path/to/certified/populace_us_2024.h5 \
  --artifact-root /path/to/new-candidate/artifacts \
  --compatibility-wheel /path/to/policyengine_us-EXACT.whl \
  --compatibility-wheel /path/to/policyengine_core-EXACT.whl \
  --compatibility-wheel /path/to/policyengine-EXACT.whl \
  --compatibility-wheel /path/to/spm_calculator-EXACT.whl

microcosm-publish-release /path/to/certified/releases/RELEASE_ID \
  --repo-id policyengine/populace-us \
  --parent-h5 /path/to/certified/populace_us_2024.h5 \
  --artifact-root /path/to/new-candidate/artifacts \
  --compatibility-wheel /path/to/policyengine_us-EXACT.whl \
  --compatibility-wheel /path/to/policyengine_core-EXACT.whl \
  --compatibility-wheel /path/to/policyengine-EXACT.whl \
  --compatibility-wheel /path/to/spm_calculator-EXACT.whl \
  --preflight-only
```

Certification creates a separate bundle with measured compatibility; it leaves
the candidate H5 and source evidence unchanged. Both the preflight above and
the real publisher invoke the source-enrichment validator and replay the H5
and compatibility checks before constructing a Hub client. The evidence-tier
publisher cannot be used as an escape hatch. Pending compatibility and a
recorded dirty producer build are hard publication failures.

Coordinated order: build local candidate wheels, test them against the existing
immutable candidate H5, then let root commit the clean reviewed producer and
create fresh qualification receipts. Root separately verifies external package
publication and numerical/Fable acceptance before data publication and consumer
promotion. A wrapper candidate can load this local H5 before either is published,
so H5 qualification does not depend on an already certified wrapper release.
Qualification retains `external_package_publication: not_attested` and
`scope: native_input_loading_only`; it never substitutes for numerical acceptance.

These receipts deliberately state that external package publication and
canonical SPM numerical acceptance are **not attested**. Root owns exact Fable
review, canonical calculator/country/wrapper/Axiom parity, and the immutable
published package proof. Once those gates pass and root authorizes publication,
use `tools/publish_release.sh` with the same directory and arguments, remove
`--preflight-only`, and add `--tag-name RELEASE_ID`. The existing publisher
creates the new immutable Hugging Face tag; its standard invocation also
updates `latest.json`. An inspect-only tag uses `--no-latest --tag-only`.
Neither candidate construction nor certification authorizes either mutation.

Run certification and publisher commands from the Microcosm checkout. Publication
authenticates the six recorded producer source hashes against the recorded Git
commit, the checkout, and the executing data contract modules. A later docs-only
commit is allowed; an invented clean flag, missing commit, changed source, or
older installed producer module is refused.

## Local regression checks

```bash
python -m pytest \
  packages/microcosm-build/tests/test_us_spm_role_source.py \
  packages/microcosm-build/tests/test_us_spm_role_enrichment_builder.py \
  packages/microcosm-data/tests/test_h5_enrichment.py \
  packages/microcosm-data/tests/test_source_enrichment.py \
  packages/microcosm-data/tests/test_contract.py \
  packages/microcosm-data/tests/test_release.py \
  packages/microcosm-data/tests/test_publish_guard.py
python tools/ci_test_groups.py --verify
ruff check .
```

These tests use synthetic populations. Their success is not certification of
the full private artifact or compatibility with an unreleased model.
