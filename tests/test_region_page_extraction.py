from wiki_genres.loader.region_page_extraction import (
    _is_region_list_source,
    _region_navbox_template_titles,
    extract_region_list_page_genre_links,
    extract_region_navbox_genre_links,
    extract_region_page_genre_links,
    normalize_link_title,
)
from wiki_genres.loader.region_ownership import classify_region_genre_ownership
from wiki_genres.loader.region_validation import review_region_genre_relationship


def test_normalize_link_title_skips_non_article_namespaces() -> None:
    assert normalize_link_title("Dancehall#History") == "Dancehall"
    assert normalize_link_title("Category:Jamaican styles of music") is None
    assert normalize_link_title("File:Cover.jpg") is None


def test_extract_region_page_genre_links_uses_exact_approved_link_targets() -> None:
    lookup = {
        "dancehall": ("wg-q45981", "Dancehall"),
        "reggae": ("wg-q9794", "Reggae"),
    }
    wikitext = """
{{Infobox country}}
'''Music of Jamaica''' includes [[reggae]].

== Popular music ==
* [[Dancehall]] developed from Jamaican popular music.

== See also ==
* [[Reggae]]
"""

    links = extract_region_page_genre_links(
        wikitext,
        page_title="Music of Jamaica",
        genre_title_lookup=lookup,
    )

    assert [(link.genre_title, link.section_title) for link in links] == [
        ("Dancehall", "Popular music"),
    ]
    assert links[0].evidence_kind == "list_row_link"


def test_extract_region_page_genre_links_reads_table_and_definition_context() -> None:
    lookup = {
        "benna": ("wg-benna", "Benna"),
        "calypso": ("wg-calypso", "Calypso"),
        "zouk": ("wg-zouk", "Zouk"),
    }
    wikitext = """
== Regional styles ==
{| class="wikitable"
! Area !! Genres
|-
| Antigua || [[Benna]] and [[Calypso]]
|}

== Traditions ==
; Guadeloupe: [[Zouk]]
"""

    links = extract_region_page_genre_links(
        wikitext,
        page_title="Music of the Caribbean",
        genre_title_lookup=lookup,
    )

    assert [(link.genre_title, link.evidence_kind) for link in links] == [
        ("Benna", "table_row_link"),
        ("Calypso", "table_row_link"),
        ("Zouk", "definition_row_link"),
    ]


def test_extract_region_page_genre_links_ignores_weak_lead_mentions() -> None:
    lookup = {"reggae": ("wg-q9794", "Reggae")}
    links = extract_region_page_genre_links(
        "'''Music of Jamaica''' includes [[reggae]].",
        page_title="Music of Jamaica",
        genre_title_lookup=lookup,
    )

    assert links == []


def test_extract_region_page_genre_links_skips_musician_sections() -> None:
    lookup = {"country music": ("wg-country", "Country music")}
    links = extract_region_page_genre_links(
        """
== Other musicians from Alabama ==
* Jane Doe plays [[country music]].
""",
        page_title="Music of Alabama",
        genre_title_lookup=lookup,
    )

    assert links == []


def test_extract_region_page_genre_links_skips_region_music_page_targets() -> None:
    lookup = {"music of samoa": ("wg-region-samoa", "Music of Samoa")}
    links = extract_region_page_genre_links(
        """
== Regional styles ==
* [[Music of Samoa]]
""",
        page_title="Music of Oceania",
        genre_title_lookup=lookup,
    )

    assert links == []


def test_extract_region_list_page_genre_links_binds_genres_to_row_region() -> None:
    genre_lookup = {
        "calypso music": ("wg-calypso", "Calypso music"),
        "cadence-lypso": ("wg-cadence", "Cadence-lypso"),
        "montserrat": ("wg-region-montserrat", "Montserrat"),
    }
    region_lookup = {
        "montserrat": ("region-montserrat", "Montserrat", "territory"),
    }

    links = extract_region_list_page_genre_links(
        """
; [[Montserrat]]: [[Calypso music]], [[Cadence-lypso]], [[Montserrat]]
""",
        page_title="List of Caribbean music genres",
        genre_title_lookup=genre_lookup,
        region_lookup=region_lookup,
    )

    assert [(link.genre_title, link.target_region_id) for link in links] == [
        ("Cadence-lypso", "region-montserrat"),
        ("Calypso music", "region-montserrat"),
    ]


def test_extract_region_list_page_genre_links_requires_region_context() -> None:
    links = extract_region_list_page_genre_links(
        """
* [[Baroque music]]
* [[Chamber music]]
""",
        page_title="List of classical music genres",
        genre_title_lookup={
            "baroque music": ("wg-baroque", "Baroque music"),
            "chamber music": ("wg-chamber", "Chamber music"),
        },
        region_lookup={"italy": ("region-italy", "Italy", "country")},
    )

    assert links == []


def test_region_list_source_rejects_unknown_generic_genre_lists() -> None:
    genre_lookup = {"blues": ("wg-blues", "Blues")}

    assert not _is_region_list_source(
        page_title="List of blues music genres",
        region_name="blues",
        region_kind="unknown",
        genre_title_lookup=genre_lookup,
    )

    assert _is_region_list_source(
        page_title="List of Latin music genres",
        region_name="Latin",
        region_kind="cultural_region",
        genre_title_lookup=genre_lookup,
    )


def test_extract_region_navbox_genre_links_reads_structured_genre_groups() -> None:
    lookup = {
        "bugaku": ("wg-bugaku", "Bugaku"),
        "city pop": ("wg-city-pop", "City pop"),
        "japanese hip hop": ("wg-jp-hip-hop", "Japanese hip-hop"),
        "oricon singles chart": ("wg-chart", "Oricon Singles Chart"),
        "traditional japanese musical instruments": ("wg-instruments", "Traditional Japanese musical instruments"),
    }

    links = extract_region_navbox_genre_links(
        """
{{Navbox
| name = Music of Japan
| title = [[Music of Japan]]
| group1 = [[Traditional Japanese music|Traditional]]
| list1 = [[Traditional Japanese musical instruments|Instruments]]
{{Navbox|subgroup
  | group1 = Genres and styles
  | list1 = [[Bugaku]]
}}
| group2 = Post-War
| list2 = {{Navbox|subgroup
  | group1 = 1970-present
  | list1 = [[City pop]] [[Japanese hip hop|Hip hop]]
}}
| group3 = Charts
| list3 = [[Oricon Singles Chart]]
}}
""",
        page_title="Template:Music of Japan",
        genre_title_lookup=lookup,
    )

    assert [(link.genre_title, link.section_title) for link in links] == [
        ("Bugaku", "Traditional > Genres and styles"),
        ("City pop", "Post-War > 1970-present"),
        ("Japanese hip-hop", "Post-War > 1970-present"),
    ]
    assert {link.evidence_kind for link in links} == {"navbox_genre_link"}


def test_extract_region_navbox_genre_links_reads_music_sidebar_genre_params() -> None:
    lookup = {
        "calypso music": ("wg-calypso", "Calypso music"),
        "chutney music": ("wg-chutney", "Chutney music"),
        "music of barbados": ("wg-barbados", "Music of Barbados"),
        "steelpan": ("wg-steelpan", "Steelpan"),
        "trinidad and tobago entertainment network": ("wg-media", "Trinidad and Tobago Entertainment Network"),
    }

    links = extract_region_navbox_genre_links(
        """
{{Music of sidebar
|pagename = Music of Trinidad and Tobago
|genres =
* [[Calypso music|Calypso]]
* [[Steelpan]]
|ethnic =
* [[Chutney music|Chutney]]
|media =
* [[Trinidad and Tobago Entertainment Network]]
|othregions =
* [[Music of Barbados|Barbados]]
}}
""",
        page_title="Template:Music of Trinidad and Tobago",
        genre_title_lookup=lookup,
    )

    assert [(link.genre_title, link.section_title) for link in links] == [
        ("Calypso music", "Genres"),
        ("Steelpan", "Genres"),
        ("Chutney music", "Ethnic music"),
    ]


def test_extract_region_navbox_genre_links_reads_collapsible_sidebar_lists() -> None:
    lookup = {
        "american classical music": ("wg-classical", "American classical music"),
        "american folk music": ("wg-folk", "American folk music"),
        "american music awards": ("wg-awards", "American Music Awards"),
        "american patriotic music": ("wg-patriotic", "American patriotic music"),
        "music of alabama": ("wg-alabama", "Music of Alabama"),
    }

    links = extract_region_navbox_genre_links(
        """
{{sidebar with collapsible lists
|name = US music
|list1title = General topics
|list1 = [[Music education in the United States]]
|list2title = Genres
|list2 = [[American classical music|Classical]] [[American folk music|Folk]]
|list3title = Awards
|list3 = [[American Music Awards]]
|list4title = Nationalistic and patriotic songs
|list4 = [[American patriotic music]] [[The Star-Spangled Banner]]
|list5title = Regional and state scenes
|list5 = [[Music of Alabama]]
}}
""",
        page_title="Template:US music",
        genre_title_lookup=lookup,
    )

    assert [(link.genre_title, link.section_title) for link in links] == [
        ("American classical music", "Genres"),
        ("American folk music", "Genres"),
        ("American patriotic music", "Nationalistic and patriotic songs"),
    ]


def test_extract_region_navbox_genre_links_accepts_broader_music_group_labels() -> None:
    lookup = {
        "indian classical music": ("wg-classical", "Indian classical music"),
        "indian folk music": ("wg-folk", "Indian folk music"),
        "shruti (music)": ("wg-shruti", "Shruti (music)"),
        "lavani": ("wg-lavani", "Lavani"),
    }

    links = extract_region_navbox_genre_links(
        """
{{Navbox
| name = Indian Music
| group1 = Main
| list1 = [[Indian classical music]] [[Indian folk music]]
| group2 = Concepts
| list2 = [[Shruti (music)]]
| group3 = Indian folk music
| list3 = [[Lavani]]
}}
""",
        page_title="Template:Indian Music",
        genre_title_lookup=lookup,
    )

    assert [(link.genre_title, link.section_title) for link in links] == [
        ("Indian classical music", "Main"),
        ("Indian folk music", "Main"),
        ("Lavani", "Indian folk music"),
    ]


def test_region_navbox_template_titles_requires_page_title_match() -> None:
    assert _region_navbox_template_titles(
        "{{Music of Japan}}\n{{Japan topics}}\n{{Music of Asia}}",
        page_title="Music of Japan",
    ) == ["Template:Music of Japan"]


def test_region_navbox_template_titles_accepts_demonym_and_compact_owner_aliases() -> None:
    assert _region_navbox_template_titles(
        "{{Indian music}}\n{{Music of Asia}}",
        page_title="Music of India",
        region_name="India",
    ) == ["Template:Indian music"]

    assert _region_navbox_template_titles(
        "{{Scottish folk music}}\n{{Music of Europe}}",
        page_title="Music of Scotland",
        region_name="Scotland",
    ) == ["Template:Scottish folk music"]

    assert _region_navbox_template_titles(
        "{{USmusic}}\n{{Music of North America}}",
        page_title="Music of the United States",
        region_name="United States",
    ) == ["Template:USmusic"]


def test_region_navbox_template_titles_rejects_bare_region_templates() -> None:
    assert _region_navbox_template_titles(
        "{{Alabama}}\n{{Music of the United States}}",
        page_title="Music of Alabama",
        region_name="Alabama",
    ) == []


def test_article_region_genre_review_accepts_regional_music_page_links() -> None:
    decision = review_region_genre_relationship(
        {
            "region_name": "Jamaica",
            "genre_title": "Dancehall",
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of Jamaica",
            "source_section": "Popular music",
        }
    )

    assert decision.status == "accepted"


def test_region_ownership_downgrades_generic_local_style_links() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of Iceland",
            "source_section": "Popular music",
            "evidence_kind": "genre_section_link",
            "region_name": "Iceland",
            "region_wikipedia_title": "Music of Iceland",
            "genre_title": "Pop music",
            "genre_summary": "Pop music originated elsewhere.",
        }
    )

    assert decision.ownership_class == "regional_style_mention"
    assert decision.relation == "regional_style_mention"


def test_region_ownership_keeps_region_specific_genre_titles() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of Iceland",
            "source_section": "Folk music",
            "evidence_kind": "genre_section_link",
            "region_name": "Iceland",
            "region_wikipedia_title": "Music of Iceland",
            "genre_title": "Icelandic folk music",
        }
    )

    assert decision.ownership_class == "owned_regional_genre"
    assert decision.relation == "regional_scene"


def test_region_ownership_keeps_curated_origin_genres() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of the United States",
            "source_section": "Country music",
            "evidence_kind": "section_heading",
            "region_name": "United States",
            "region_wikipedia_title": "Music of the United States",
            "genre_title": "Country music",
        }
    )

    assert decision.ownership_class == "owned_regional_genre"
    assert decision.relation == "regional_scene"


def test_region_ownership_does_not_match_short_region_code_inside_music() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of the United States",
            "source_section": "Pop music",
            "evidence_kind": "section_heading",
            "region_name": "United States",
            "region_wikipedia_title": "Music of the United States",
            "genre_title": "Pop music",
            "genre_summary": "Pop music originated in its modern form in the United States.",
        }
    )

    assert decision.ownership_class == "regional_style_mention"
    assert decision.relation == "regional_style_mention"


def test_region_ownership_does_not_treat_british_model_as_uk_origin() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "local_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of the United Kingdom",
            "source_section": None,
            "evidence_kind": "lead_context_link",
            "region_name": "United Kingdom",
            "region_wikipedia_title": "Music of the United Kingdom",
            "genre_title": "American march music",
            "genre_summary": (
                "American march music is march music written and/or performed in the "
                "United States. The American genre developed after the British model."
            ),
        }
    )

    assert decision.ownership_class == "regional_style_mention"
    assert decision.relation == "regional_style_mention"


def test_region_ownership_keeps_curated_non_country_origin_style() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of Indonesia",
            "source_section": "Gamelan",
            "evidence_kind": "section_heading",
            "region_name": "Indonesia",
            "region_wikipedia_title": "Music of Indonesia",
            "genre_title": "Gamelan",
            "genre_summary": "Gamelan is the traditional ensemble music of Indonesia.",
        }
    )

    assert decision.ownership_class == "owned_regional_genre"
    assert decision.relation == "regional_scene"


def test_region_ownership_downgrades_list_article_links() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "List of classical music genres",
            "source_section": "Classical and Romantic",
            "evidence_kind": "list_row_link",
            "region_name": "classical",
            "region_wikipedia_title": "List of classical music genres",
            "genre_title": "Baroque music",
            "genre_summary": "Baroque music is part of the classical music canon.",
        }
    )

    assert decision.ownership_class == "regional_style_mention"
    assert decision.relation == "regional_style_mention"


def test_region_ownership_does_not_treat_diaspora_hyphen_as_country_origin() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of Italy",
            "source_section": "Modern dance",
            "evidence_kind": "genre_section_link",
            "region_name": "Italy",
            "region_wikipedia_title": "Music of Italy",
            "genre_title": "Disco",
            "genre_summary": (
                "Disco is a genre that emerged in the United States' urban nightlife "
                "scene, particularly in African-American, Italian-American, Latino and "
                "gay and lesbian communities."
            ),
        }
    )

    assert decision.ownership_class == "regional_style_mention"
    assert decision.relation == "regional_style_mention"


def test_region_ownership_does_not_treat_african_root_as_africa_ownership() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of Africa",
            "source_section": None,
            "evidence_kind": "lead_context_link",
            "region_name": "Africa",
            "region_wikipedia_title": "Music of Africa",
            "genre_title": "Salsa music",
            "genre_summary": (
                "Salsa has origins in Cuba, though its rhythms and cultural essence "
                "are rooted in musical traditions from West and Central Africa."
            ),
        }
    )

    assert decision.ownership_class == "regional_style_mention"
    assert decision.relation == "regional_style_mention"


def test_region_ownership_does_not_treat_african_origin_context_as_africa_ownership() -> None:
    decision = classify_region_genre_ownership(
        {
            "relation": "regional_scene",
            "source_type": "wikipedia_article",
            "source_title": "Music of Africa",
            "source_section": None,
            "evidence_kind": "lead_context_link",
            "region_name": "Africa",
            "region_wikipedia_title": "Music of Africa",
            "genre_title": "Kaiso",
            "genre_summary": (
                "Kaiso is a type of music popular in Trinidad and Tobago which "
                "originated in West Africa and later evolved into calypso music."
            ),
        }
    )

    assert decision.ownership_class == "regional_style_mention"
    assert decision.relation == "regional_style_mention"
