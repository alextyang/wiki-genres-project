"""Wikidata entity parser.

Extracts the subset of a Wikidata entity response relevant to the genre graph:
English aliases and typed edges from the properties we care about.
"""

from __future__ import annotations

from typing import Any

import structlog

from wiki_genres.parser.types import ParsedEdge, ParsedWikidataEntity

logger = structlog.get_logger(__name__)

# Wikidata property ID → edge relation name.
_PROPERTY_RELATIONS: dict[str, str] = {
    "P279": "subclass_of",    # subclass of
    "P737": "influenced_by",  # influenced by
    "P361": "part_of",        # part of
    "P31":  "instance_of",    # instance of
}


def parse_wikidata_entity(
    entity_data: dict[str, Any], qid: str
) -> ParsedWikidataEntity:
    """Parse a ``wbgetentities`` API response for one entity."""
    entities = entity_data.get("entities", {})
    entity = entities.get(qid)
    if entity is None or entity.get("missing") == "":
        return ParsedWikidataEntity(qid=qid)

    aliases = _extract_aliases(entity)
    edges = _extract_edges(entity)

    return ParsedWikidataEntity(qid=qid, aliases=aliases, edges=edges)


def _extract_aliases(entity: dict[str, Any]) -> list[str]:
    """Return English aliases from the entity."""
    raw_aliases = entity.get("aliases", {}).get("en", [])
    seen: set[str] = set()
    result: list[str] = []
    for entry in raw_aliases:
        val = entry.get("value", "").strip()
        lower = val.lower()
        if val and lower not in seen:
            seen.add(lower)
            result.append(val)
    return result


def _extract_edges(entity: dict[str, Any]) -> list[ParsedEdge]:
    """Extract typed edges from the entity's claims."""
    claims = entity.get("claims", {})
    edges: list[ParsedEdge] = []

    for prop_id, relation in _PROPERTY_RELATIONS.items():
        statements = claims.get(prop_id, [])
        for ordinal, statement in enumerate(statements):
            # We only want normal rank (not deprecated).
            if statement.get("rank") == "deprecated":
                continue
            main_snak = statement.get("mainsnak", {})
            if main_snak.get("snaktype") != "value":
                continue
            data_value = main_snak.get("datavalue", {})
            if data_value.get("type") != "wikibase-entityid":
                continue
            target_qid = data_value.get("value", {}).get("id")
            if not target_qid:
                continue
            edges.append(
                ParsedEdge(
                    relation=relation,
                    raw_label=target_qid,  # resolved to title by the loader
                    wiki_target=None,       # filled in by the loader
                    source="wikidata",
                    ordinal=ordinal,
                )
            )

    return edges
