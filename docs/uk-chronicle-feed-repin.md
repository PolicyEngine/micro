# Re-pin the UK Chronicle consumer feed

The national and local target surfaces have independently reviewed Chronicle
artifact pins. National calibration reads `uk/national_chronicle_feed.json`;
local calibration and validation retain their existing pins. A national
update does not authorize changes to local census membership or values.

Rebuild the complete UK bundle and consumer artifact in
`PolicyEngine/chronicle` at the declared commit. Keep the resulting
`consumer_facts.jsonl` and `manifest.json` together; do not commit either file.
Because the two surfaces are pinned independently, each has its own default
location under `.codex-work`: the national feed at
`.codex-work/consumer_facts_uk.jsonl` + `consumer_facts_uk_manifest.json`
(also mirrored as the artifact directory `.codex-work/uk-artifact/` for the
calibration runner), the local feed at `.codex-work/consumer_facts_uk_local.jsonl`
+ `consumer_facts_uk_local_manifest.json`. After a national-only re-pin the
local files stay at the local pin's artifact.

Verify both SHA-256 digests and the manifest's `facts_sha256`, row count, and
schema version. For a national update, update
`uk/national_chronicle_feed.json` and regenerate the national references and
membership with `tools/generate_uk_target_references.py`. Verify the complete
compiled target diff, including targets outside the intended policy area.
The hermetic national regeneration test accepts `CHRONICLE_UK_FACTS`.
Two-level (country + region) contract targets fan out over the region tier
(`UK_REGION_TIER` in `uk_runtime/geography_ladder.py`), one reference per area
(microcosm#905); their cells resolve Chronicle's region- and country-stamped
facts, so a re-pin must carry all twelve areas or the generator refuses.
The cross-grain legs of English constituencies and authorities come from
`region_code_by_area` in `local_area_crosswalk.json`, regenerated from the
sha-pinned ladder with `tools/generate_uk_local_area_crosswalk.py`.

For a separately reviewed local update, update `_LEDGER_FACT_FEED_PIN` in
`uk_runtime/local_target_census.py`, the local validation-level pin, and their
tests together. Regenerate the local census with
`uv run --no-sync python tools/census_uk_local_targets.py`.

Regenerate the local reference surface with
`tools/generate_uk_local_target_references.py`, then rebuild the signed compile
parity receipts affected by that update with
`tools/build_uk_ledger_compile_parity_signed_differences.py`. The hermetic
local regeneration test accepts either the default `.codex-work` files or a
`CHRONICLE_UK_LOCAL_FACTS` override and skips only when neither is present.

The national calibration runner refuses a feed whose facts or manifest digest
differs from its committed pin. `--allow-unpinned-feed` is an explicit diagnostic override and
is recorded in the run manifest; it is not a re-pin procedure.

After the `c6f9361` national re-pin (#890), the national surface carries the
chronicle #254/#255 and #257/#258 transport and energy packages; the local
surface stays on `ec7169b`. Vendored per-concern copies of pinned facts for the
spine stages are regenerated with `tools/vendor_uk_ledger_facts.py` from the
national feed (`uk/ledger_fact_vendor_selections.json` names them).

After the `ec7169b` re-pin, census household targets use the same Chronicle
compile path as every other bound UK local family. The OA ladder now supplies
geography assignment and diagnostic household dispersion only; it no longer
creates calibration targets or a non-contract reconciliation surface.
