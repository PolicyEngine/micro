"""Compose shared geography before the combined-survey support clone.

This declaration has no country-specific geography kernel or source admission.
Callers provide normalized, qualified observed columns and declared support.
"""

from dataclasses import replace

from microcosm.build.graph_atomic_geography import atomic_geography_nodes

from .graph_combined_clone import us_combined_survey_clone_nodes


def atomic_survey_clone_nodes(
    definition,
    columns,
    *,
    base,
    geography_prefix="geography",
    clone_prefix="combined_survey_puf_support_clone",
):
    """Assign once on the base, inherit every location, then recheck the clone.

    Structural graph nodes depend on every member of their base version. The
    pre-clone integrity gate therefore precedes EXPAND even though it owns no
    cells. The post-clone gate derives mappings without drawing again.
    """
    columns = tuple(columns)
    geography = atomic_geography_nodes(
        definition, columns, base=base, prefix=geography_prefix
    )
    clones = us_combined_survey_clone_nodes(
        (*columns, *(output for node in geography for output in node.outputs)),
        base=base,
        source_channels=("acs", "asec"),
        prefix=clone_prefix,
    )
    final_gate = replace(
        geography[-1],
        id=f"{geography_prefix}.clone_gate",
        population=clones[0].id,
        description="Recheck inherited atomic geography on every support clone.",
    )
    return (*geography, *clones, final_gate)
