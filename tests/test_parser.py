"""Unit tests for the infobox and Wikidata parsers."""

from __future__ import annotations

from wiki_genres.parser.infobox import parse_genre_page
from wiki_genres.parser.wikidata import parse_wikidata_entity

# ------------------------------------------------------------------ #
# Infobox parser                                                       #
# ------------------------------------------------------------------ #

_JERK_WIKITEXT = """\
{{Infobox music genre
|name = Jerk
|other_names = Jerk music
|color_background = #ff69b4
|stylistic_origins = [[Hip hop music|Hip hop]], [[crunk]], [[snap music]]
|cultural_origins  = 2009, Inland Empire, Southern California, United States
|instruments       = [[Drum machine]], [[sampler (musical instrument)|Sampler]]
|derivatives       = [[twerking|Twerk music]]
|subgenres         = {{hlist|[[Jerkin']]|[[Likwit Junkies]]}}
}}

'''Jerk''' (also called '''jerk music''') is a style...
"""

_EDM_WIKITEXT = """\
{{Infobox music genre
|name            = Electronic dance music
|other_names     = EDM, Dance music, Electronic music
|stylistic_origins = [[House music|House]], [[techno]], [[trance music|Trance]]
|derivatives     = [[Big room house]], [[future bass]]
|color_background = #9932CC
}}
"""

_NO_INFOBOX = """\
'''Hip hop''' is a broad description of a culture...
"""


def test_parse_jerk_extracts_infobox() -> None:
    parsed = parse_genre_page(_JERK_WIKITEXT, "Jerk (music genre)")
    assert parsed.has_infobox
    assert parsed.infobox_color == "#FF69B4"


def test_parse_jerk_stylistic_origins() -> None:
    parsed = parse_genre_page(_JERK_WIKITEXT, "Jerk (music genre)")
    relations = [(e.relation, e.wiki_target or e.raw_label) for e in parsed.infobox_edges]
    assert ("stylistic_origin", "Hip hop music") in relations
    assert ("stylistic_origin", "Crunk") in relations  # [[crunk]] normalised
    assert ("stylistic_origin", "Snap music") in relations  # [[snap music]] normalised


def test_parse_jerk_subgenre_from_hlist() -> None:
    parsed = parse_genre_page(_JERK_WIKITEXT, "Jerk (music genre)")
    subgenres = [e for e in parsed.infobox_edges if e.relation == "subgenre"]
    assert any(e.wiki_target == "Jerkin'" for e in subgenres)


def test_parse_jerk_other_names_as_aliases() -> None:
    parsed = parse_genre_page(_JERK_WIKITEXT, "Jerk (music genre)")
    assert "Jerk music" in parsed.aliases


def test_parse_jerk_cultural_origin() -> None:
    parsed = parse_genre_page(_JERK_WIKITEXT, "Jerk (music genre)")
    assert parsed.origins
    origin = parsed.origins[0]
    assert origin.parsed_year_start == 2009
    assert origin.parsed_region == "Inland Empire"


def test_parse_jerk_instruments() -> None:
    parsed = parse_genre_page(_JERK_WIKITEXT, "Jerk (music genre)")
    assert any("Drum machine" in inst for inst in parsed.instruments)


def test_parse_jerk_new_titles_includes_wikilinks() -> None:
    parsed = parse_genre_page(_JERK_WIKITEXT, "Jerk (music genre)")
    assert "Hip hop music" in parsed.new_genre_titles
    assert "Twerking" in parsed.new_genre_titles
    assert "Southern California" not in parsed.new_genre_titles
    assert "United States" not in parsed.new_genre_titles


def test_parse_edm_other_names_comma_separated() -> None:
    parsed = parse_genre_page(_EDM_WIKITEXT, "Electronic dance music")
    assert "EDM" in parsed.aliases
    assert "Dance music" in parsed.aliases


def test_parse_no_infobox() -> None:
    parsed = parse_genre_page(_NO_INFOBOX, "Hip hop")
    assert not parsed.has_infobox
    assert parsed.infobox_edges == []


# ------------------------------------------------------------------ #
# Wikidata parser                                                      #
# ------------------------------------------------------------------ #

_WIKIDATA_RESPONSE = {
    "entities": {
        "Q188450": {
            "type": "item",
            "id": "Q188450",
            "aliases": {
                "en": [
                    {"language": "en", "value": "EDM"},
                    {"language": "en", "value": "dance music"},
                ]
            },
            "claims": {
                "P279": [
                    {
                        "rank": "normal",
                        "mainsnak": {
                            "snaktype": "value",
                            "property": "P279",
                            "datavalue": {
                                "type": "wikibase-entityid",
                                "value": {"id": "Q82955"},
                            },
                        },
                    }
                ],
                "P737": [
                    {
                        "rank": "normal",
                        "mainsnak": {
                            "snaktype": "value",
                            "property": "P737",
                            "datavalue": {
                                "type": "wikibase-entityid",
                                "value": {"id": "Q9759"},
                            },
                        },
                    }
                ],
                "P279_deprecated": [
                    {
                        "rank": "deprecated",
                        "mainsnak": {
                            "snaktype": "value",
                            "property": "P279",
                            "datavalue": {
                                "type": "wikibase-entityid",
                                "value": {"id": "Q999999"},
                            },
                        },
                    }
                ],
            },
        }
    }
}


def test_wikidata_aliases() -> None:
    entity = parse_wikidata_entity(_WIKIDATA_RESPONSE, "Q188450")
    assert "EDM" in entity.aliases
    assert "dance music" in entity.aliases


def test_wikidata_subclass_edge() -> None:
    entity = parse_wikidata_entity(_WIKIDATA_RESPONSE, "Q188450")
    subclass_edges = [e for e in entity.edges if e.relation == "subclass_of"]
    assert any(e.raw_label == "Q82955" for e in subclass_edges)


def test_wikidata_influenced_by_edge() -> None:
    entity = parse_wikidata_entity(_WIKIDATA_RESPONSE, "Q188450")
    influenced = [e for e in entity.edges if e.relation == "influenced_by"]
    assert any(e.raw_label == "Q9759" for e in influenced)


def test_wikidata_deprecated_rank_skipped() -> None:
    entity = parse_wikidata_entity(_WIKIDATA_RESPONSE, "Q188450")
    all_targets = [e.raw_label for e in entity.edges]
    assert "Q999999" not in all_targets


def test_wikidata_missing_entity() -> None:
    entity = parse_wikidata_entity({"entities": {"Q999": {"missing": ""}}}, "Q999")
    assert entity.aliases == []
    assert entity.edges == []
