"""Seed list generation for the bootstrap crawl.

Primary path: Wikidata SPARQL returning all entities that are instances or
subclasses of music genre (Q188451) / musical style (Q2944929) that have an
English Wikipedia sitelink.

Fallback: Wikipedia's ``Category:Music_genres`` and related category pages,
used when the SPARQL endpoint is unreachable or the query times out.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote

import structlog

from wiki_genres.crawler.fetcher import WIKIPEDIA_API, WikiFetcher

logger = structlog.get_logger(__name__)

# QIDs whose instances/subclasses we treat as music genres.
_GENRE_CLASS_QIDS = [
    "Q188451",  # music genre
    "Q2944929",  # musical style
]

# Paginated SPARQL query.  Uses only P31 (instance_of) — the transitive P279+
# variant times out on Wikidata's public endpoint at the required scale.
_SPARQL_TEMPLATE = """
SELECT DISTINCT ?genre ?article WHERE {{
  VALUES ?genreClass {{ {class_values} }}
  ?genre wdt:P31 ?genreClass .
  ?article schema:about ?genre ;
           schema:isPartOf <https://en.wikipedia.org/> .
  FILTER NOT EXISTS {{ ?genre wdt:P31 wd:Q5 }}
}}
ORDER BY ?genre
LIMIT {limit}
OFFSET {offset}
"""

_FALLBACK_CATEGORIES = [
    "Category:Music_genres",
    "Category:Electronic_music_genres",
    "Category:Hip_hop_genres",
    "Category:Rock_music_genres",
    "Category:Pop_music_genres",
]


@dataclass
class SeedEntry:
    wikipedia_title: str
    wikidata_qid: str | None = None


async def fetch_seeds(fetcher: WikiFetcher, page_size: int = 1000) -> list[SeedEntry]:
    """Return a deduplicated list of genre Wikipedia titles from Wikidata SPARQL."""
    logger.info("fetching_seeds_sparql")
    seeds: dict[str, SeedEntry] = {}
    class_values = " ".join(f"wd:{qid}" for qid in _GENRE_CLASS_QIDS)

    offset = 0
    while True:
        query = _SPARQL_TEMPLATE.format(class_values=class_values, limit=page_size, offset=offset)
        result = await fetcher.fetch_sparql(query)
        if not result.ok:
            logger.warning(
                "sparql_failed",
                status=result.http_status,
                offset=offset,
            )
            break

        data = result.json()
        bindings = data.get("results", {}).get("bindings", [])
        if not bindings:
            break

        for row in bindings:
            article_url = row.get("article", {}).get("value", "")
            title = _url_to_title(article_url)
            if not title:
                continue
            qid_url = row.get("genre", {}).get("value", "")
            qid = qid_url.rsplit("/", 1)[-1] if qid_url else None
            if title not in seeds:
                seeds[title] = SeedEntry(wikipedia_title=title, wikidata_qid=qid)

        logger.info("sparql_page", offset=offset, returned=len(bindings), total=len(seeds))

        if len(bindings) < page_size:
            break
        offset += page_size

    if not seeds:
        logger.warning("sparql_returned_nothing_trying_categories")
        return await fetch_category_seeds(fetcher)

    logger.info("seeds_loaded", total=len(seeds))
    return list(seeds.values())


async def fetch_category_seeds(fetcher: WikiFetcher) -> list[SeedEntry]:
    """Fallback: walk Wikipedia categories to collect genre article titles."""
    logger.info("fetching_seeds_from_categories")
    seeds: dict[str, SeedEntry] = {}

    for cat in _FALLBACK_CATEGORIES:
        await _walk_category(fetcher, cat, seeds, depth=0, max_depth=2)

    logger.info("category_seeds_loaded", total=len(seeds))
    return list(seeds.values())


async def _walk_category(
    fetcher: WikiFetcher,
    category: str,
    seeds: dict[str, SeedEntry],
    depth: int,
    max_depth: int,
) -> None:
    """Recursively collect article titles from a Wikipedia category."""
    url = (
        f"{WIKIPEDIA_API}?action=query&list=categorymembers"
        f"&cmtitle={category}&cmtype=page|subcat&cmlimit=500"
        f"&formatversion=2&format=json"
    )
    result = await fetcher._get(url, host="en.wikipedia.org")
    if not result.ok:
        return

    data = result.json()
    members = data.get("query", {}).get("categorymembers", [])

    for member in members:
        ns = member.get("ns", -1)
        title = member.get("title", "")
        if ns == 0:  # article namespace
            if title not in seeds:
                seeds[title] = SeedEntry(wikipedia_title=title)
        elif ns == 14 and depth < max_depth:  # Category namespace
            await _walk_category(fetcher, title, seeds, depth + 1, max_depth)


def _url_to_title(url: str) -> str | None:
    """Convert a Wikipedia article URL to a page title."""
    prefix = "https://en.wikipedia.org/wiki/"
    if not url.startswith(prefix):
        return None
    return unquote(url[len(prefix) :]).replace("_", " ")
