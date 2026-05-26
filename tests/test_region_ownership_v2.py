from __future__ import annotations

import pytest

from wiki_genres.loader.region_ownership_v2 import (
    RegionMentionContext,
    _score_region_mentions,
    classify_region_genre_ownership_v2,
)


class FakeResult:
    def __init__(self, payload: dict, ok: bool = True):
        self._payload = payload
        self.http_status = 200 if ok else 0
        self.content = b"{}"
        self.from_cache = True

    @property
    def ok(self) -> bool:
        return self.http_status == 200

    def json(self):
        return self._payload


class FakeFetcher:
    def __init__(self, *, wikitext: str = "", search_hits: list[dict] | None = None):
        self._wikitext = wikitext
        self._search_hits = search_hits or []

    async def fetch_wikitext(self, title: str):
        return FakeResult({"parse": {"wikitext": self._wikitext}})

    async def search_titles(self, query: str, *, limit: int = 5):
        return FakeResult({"query": {"search": list(self._search_hits)[:limit]}})


class FakeConn:
    def __init__(
        self,
        *,
        category_owned: bool = False,
        local_variant_hit: bool = False,
        local_variant_title: str = "Icelandic pop",
    ):
        self._category_owned = category_owned
        self._local_variant_hit = local_variant_hit
        self._local_variant_title = local_variant_title

    async def scalar(self, stmt, params=None):
        sql = str(stmt)
        if "FROM wg_region_genre_relationships" in sql and "source_type" in sql:
            return 1 if self._category_owned else None
        return None

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "FROM wg_genres g" in sql and "WHERE lower(g.wikipedia_title)" in sql:
            if self._local_variant_hit:
                return FakeMappings(
                    [
                        {
                            "genre_id": "wg-q1",
                            "title": self._local_variant_title,
                            "hit_kind": "title",
                        }
                    ]
                )
            return FakeMappings([])
        return FakeMappings([])


class FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def fetchall(self):
        return self._rows


def mention_context() -> RegionMentionContext:
    return RegionMentionContext(
        variants_by_id={
            "r-us": {"united states", "american", "new york", "bronx"},
            "r-australia": {"australia", "australian"},
            "r-iceland": {"iceland", "icelandic"},
            "r-china": {"china", "chinese"},
            "r-uk": {"united kingdom", "british", "london"},
            "r-jamaica": {"jamaica", "jamaican"},
        },
        names_by_id={
            "r-us": "United States",
            "r-australia": "Australia",
            "r-iceland": "Iceland",
            "r-china": "China",
            "r-uk": "United Kingdom",
            "r-jamaica": "Jamaica",
        },
        parent_ids_by_region={
            "r-us": [],
            "r-australia": [],
            "r-iceland": [],
            "r-china": [],
            "r-uk": [],
            "r-jamaica": [],
        },
        descendant_ids_by_region={
            "r-us": [],
            "r-australia": [],
            "r-iceland": [],
            "r-china": [],
            "r-uk": [],
            "r-jamaica": [],
        },
    )


def test_majority_scorer_counts_descendants_and_ancestors_in_scope() -> None:
    context = RegionMentionContext(
        variants_by_id={
            "r-china": {"china", "chinese"},
            "r-tibet": {"tibet", "tibetan"},
            "r-india": {"india", "indian"},
        },
        names_by_id={"r-china": "China", "r-tibet": "Tibet", "r-india": "India"},
        parent_ids_by_region={"r-tibet": ["r-china"], "r-china": [], "r-india": []},
        descendant_ids_by_region={"r-china": ["r-tibet"], "r-tibet": [], "r-india": []},
    )

    china_score = _score_region_mentions(
        text_value="Chinese music in Tibet and Tibetan styles also influenced Indian musicians.",
        region_id="r-china",
        context=context,
    )
    assert china_score.in_scope_mentions == 3
    assert china_score.out_scope_mentions == 1
    assert china_score.has_majority

    tibet_score = _score_region_mentions(
        text_value="Chinese music in Tibet and Tibetan styles also influenced Indian musicians.",
        region_id="r-tibet",
        context=context,
    )
    assert tibet_score.in_scope_mentions == 3
    assert tibet_score.out_scope_mentions == 1
    assert tibet_score.has_majority


@pytest.mark.asyncio
async def test_v2_title_region_specific_is_owned() -> None:
    row = {
        "region_id": "r-iceland",
        "genre_id": "g1",
        "region_name": "Iceland",
        "region_wikipedia_title": "Music of Iceland",
        "genre_title": "Icelandic folk music",
        "genre_summary": "",
        "source_title": "Music of Iceland",
        "source_section": None,
        "source_type": "wikipedia_article",
        "evidence_kind": "genre_section_link",
        "relation": "regional_scene",
        "status": "proposed",
    }
    decision, inferred = await classify_region_genre_ownership_v2(
        row=row,
        conn=FakeConn(),
        fetcher=FakeFetcher(),
        mention_context=mention_context(),
    )
    assert decision.ownership_class == "owned_regional_genre"
    assert decision.status == "accepted"
    assert inferred is None


@pytest.mark.asyncio
async def test_v2_united_states_can_own_broad_genre_by_majority() -> None:
    row = {
        "region_id": "r-us",
        "genre_id": "g1",
        "region_name": "United States",
        "region_wikipedia_title": "Music of the United States",
        "genre_title": "Hip-hop",
        "genre_summary": "Hip-hop originated in the Bronx and spread through the United States.",
        "source_title": "Music of the United States",
        "source_section": None,
        "source_type": "wikipedia_article",
        "evidence_kind": "lead_context_link",
        "relation": "regional_scene",
        "status": "proposed",
    }
    decision, payload = await classify_region_genre_ownership_v2(
        row=row,
        conn=FakeConn(category_owned=False),
        fetcher=FakeFetcher(wikitext="American DJs in New York shaped hip-hop in the United States."),
        mention_context=mention_context(),
    )
    assert decision.ownership_class == "owned_regional_genre"
    assert decision.status == "accepted"
    assert payload
    assert payload["region_mention_score"]["in_scope_share"] == 1.0


@pytest.mark.asyncio
async def test_v2_australia_does_not_own_generic_hip_hop_without_majority() -> None:
    row = {
        "region_id": "r-australia",
        "genre_id": "g1",
        "region_name": "Australia",
        "region_wikipedia_title": "Music of Australia",
        "genre_title": "Hip-hop",
        "genre_summary": "Hip-hop originated in New York and became an American music culture.",
        "source_title": "Music of Australia",
        "source_section": None,
        "source_type": "wikipedia_article",
        "evidence_kind": "lead_context_link",
        "relation": "local_scene",
        "status": "proposed",
    }
    decision, payload = await classify_region_genre_ownership_v2(
        row=row,
        conn=FakeConn(category_owned=False),
        fetcher=FakeFetcher(
            wikitext=(
                "American artists in the Bronx and New York developed the style. "
                "London grime and Jamaican sound systems are mentioned. "
                "Australia has a local scene."
            )
        ),
        mention_context=mention_context(),
    )
    assert decision.ownership_class == "regional_style_mention"
    assert decision.relation == "regional_style_mention"
    assert decision.status == "accepted"
    assert payload
    assert payload["region_mention_score"]["matched_out_scope"]["United States"] >= 1


@pytest.mark.asyncio
async def test_v2_australian_hip_hop_remains_owned_by_title() -> None:
    row = {
        "region_id": "r-australia",
        "genre_id": "g1",
        "region_name": "Australia",
        "region_wikipedia_title": "Music of Australia",
        "genre_title": "Australian hip-hop",
        "genre_summary": "",
        "source_title": "Music of Australia",
        "source_section": "Popular music",
        "source_type": "wikipedia_article",
        "evidence_kind": "genre_section_link",
        "relation": "regional_scene",
        "status": "proposed",
    }
    decision, inferred = await classify_region_genre_ownership_v2(
        row=row,
        conn=FakeConn(),
        fetcher=FakeFetcher(),
        mention_context=mention_context(),
    )
    assert decision.ownership_class == "owned_regional_genre"
    assert decision.status == "accepted"
    assert inferred is None


@pytest.mark.asyncio
async def test_v2_list_source_does_not_demote_specific_regional_title() -> None:
    row = {
        "region_id": "r-australia",
        "genre_id": "g1",
        "region_name": "Australia",
        "region_wikipedia_title": "Music of Australia",
        "genre_title": "Australian hip-hop",
        "genre_summary": "",
        "source_title": "List of Australian music genres",
        "source_section": "Genres",
        "source_type": "wikipedia_article",
        "evidence_kind": "list_link",
        "relation": "regional_scene",
        "status": "proposed",
    }
    decision, inferred = await classify_region_genre_ownership_v2(
        row=row,
        conn=FakeConn(),
        fetcher=FakeFetcher(),
        mention_context=mention_context(),
    )
    assert decision.ownership_class == "owned_regional_genre"
    assert decision.status == "accepted"
    assert inferred is None


@pytest.mark.asyncio
async def test_v2_variant_discovery_local_hit_keeps_base_as_context() -> None:
    row = {
        "region_id": "r-iceland",
        "genre_id": "g1",
        "region_name": "Iceland",
        "region_wikipedia_title": "Music of Iceland",
        "genre_title": "Pop music",
        "genre_summary": "",
        "source_title": "Music of Iceland",
        "source_section": "Popular music",
        "source_type": "wikipedia_article",
        "evidence_kind": "genre_section_link",
        "relation": "regional_scene",
        "status": "proposed",
    }
    decision, payload = await classify_region_genre_ownership_v2(
        row=row,
        conn=FakeConn(local_variant_hit=True),
        fetcher=FakeFetcher(),
        mention_context=mention_context(),
    )
    assert decision.status == "accepted"
    assert decision.ownership_class == "regional_style_mention"
    assert payload and payload["inferred"]["candidate_kind"] == "existing_db_hit"


@pytest.mark.asyncio
async def test_v2_navbox_base_target_stages_regional_variant_instead_of_owning_base() -> None:
    row = {
        "region_id": "r-australia",
        "genre_id": "g1",
        "region_name": "Australia",
        "region_wikipedia_title": "Music of Australia",
        "genre_title": "Hip-hop",
        "genre_summary": "Hip-hop is an American genre from New York.",
        "source_title": "Music of Australia",
        "source_section": "Popular music",
        "source_type": "wikipedia_navbox",
        "evidence_kind": "template_link",
        "relation": "regional_scene",
        "status": "proposed",
    }
    decision, payload = await classify_region_genre_ownership_v2(
        row=row,
        conn=FakeConn(local_variant_hit=True, local_variant_title="Australian hip-hop"),
        fetcher=FakeFetcher(wikitext="American New York Bronx."),
        mention_context=mention_context(),
    )
    assert decision.ownership_class == "regional_style_mention"
    assert decision.status == "accepted"
    assert payload and payload["inferred"]["candidate_kind"] == "existing_db_hit"
    assert payload["inferred"]["hits"][0]["title"] == "Australian hip-hop"


@pytest.mark.asyncio
async def test_v2_section_inferred_stages_candidate() -> None:
    row = {
        "region_id": "r-iceland",
        "genre_id": "g1",
        "region_name": "Iceland",
        "region_wikipedia_title": "Music of Iceland",
        "genre_title": "Pop music",
        "genre_summary": "",
        "source_title": "Music of Iceland",
        "source_section": "Popular music",
        "source_type": "wikipedia_article",
        "evidence_kind": "genre_section_link",
        "relation": "regional_scene",
        "status": "proposed",
    }
    decision, payload = await classify_region_genre_ownership_v2(
        row=row,
        conn=FakeConn(local_variant_hit=False),
        fetcher=FakeFetcher(search_hits=[]),
        mention_context=mention_context(),
    )
    # Without a local or Wikipedia hit, we should still stage a section-inferred candidate.
    assert decision.status == "accepted"
    assert decision.ownership_class == "regional_style_mention"
    assert payload and payload["inferred"]["candidate_kind"] == "section_inferred"
