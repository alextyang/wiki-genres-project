"""Timeline year-hint extraction and persistence."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text

from wiki_genres.db import get_engine, session_scope
from wiki_genres.db_migrations import apply_migrations

logger = structlog.get_logger(__name__)
PARSER_VERSION = "timeline-year-hints-v3"
REGIONAL_MUSIC_PAGE_RE = re.compile(r"^(?:the\s+)?music\s+of\s+.+", re.I)


@dataclass(frozen=True)
class YearHint:
    """One candidate year insight for a genre."""

    genre_id: str
    title: str
    year_start: int
    year_end: int | None
    confidence: str
    year_kind: str
    source_type: str
    source_field: str
    evidence: str
    reason: str
    score: int
    estimated_start: int | None = None
    estimated_end: int | None = None
    year_mean: float | None = None
    year_sd: float | None = None
    year_observation_count: int = 1
    beginning_start: int | None = None
    beginning_end: int | None = None
    beginning_mean: float | None = None
    beginning_sd: float | None = None
    beginning_observation_count: int = 1
    relevance_start: int | None = None
    relevance_end: int | None = None
    relevance_mean: float | None = None
    relevance_sd: float | None = None
    relevance_observation_count: int = 1
    excluded_reason: str | None = None


@dataclass(frozen=True)
class YearObservation:
    """One temporal mention with a relevance estimate."""

    start: int
    end: int | None
    weight: float
    confidence: str
    year_kind: str
    source_type: str
    source_field: str
    evidence: str
    reason: str
    score: int


@dataclass(frozen=True)
class YearHintEvaluation:
    """Summary from a read-only evaluation pass."""

    genres_sampled: int
    genres_with_any_hint: int
    total_hints: int
    best_by_source: Counter[str]
    best_by_confidence: Counter[str]
    mismatch_samples: list[dict[str, Any]]
    no_hint_samples: list[dict[str, str]]
    samples_by_source: dict[str, list[YearHint]]


@dataclass
class TimelineYearHintStats:
    total_genres: int = 0
    rows_written: int = 0
    hints_found: int = 0
    no_hint: int = 0
    excluded_regional: int = 0
    dry_run: bool = False
    by_source: Counter[str] = field(default_factory=Counter)
    by_confidence: Counter[str] = field(default_factory=Counter)
    sample: list[YearHint] = field(default_factory=list)


_YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2})\b")
_DECADE_RE = re.compile(r"\b(?:(early|mid|late)[-\s]+)?((?:1[0-9]|20)[0-9]0)s\b", re.I)
_CENTURY_RE = re.compile(r"\b([1-9][0-9]?)(?:st|nd|rd|th)[-\s]+century\b", re.I)
_YEAR_RANGE_RE = re.compile(
    r"\b(?:(early|mid|late)[-\s]+)?((?:1[0-9]|20)[0-9]0)s?\s*[-–]\s*"
    r"(?:(early|mid|late)[-\s]+)?((?:1[0-9]|20)[0-9]0)s?\b",
    re.I,
)

_STRONG_ORIGIN_RE = re.compile(
    r"\b(originated|emerged|developed|began|started|arose|came about|"
    r"was created|were created|created|was pioneered|were pioneered|pioneered|"
    r"first appeared|appeared|dates back|date back)\b",
    re.I,
)
_WEAKER_TEMPORAL_RE = re.compile(
    r"\b(popularized|became popular|gained popularity|rose to prominence|"
    r"has been popular|was popular|flourished|was introduced|were introduced)\b",
    re.I,
)
_INFLUENCE_TEMPORAL_RE = re.compile(
    r"\b(influenced by|inspired by|inspiration|precursor|forerunner|roots?|"
    r"evolved from|derived from|based on|draws? from|borrows? from)\b",
    re.I,
)
_NAMING_CONTEXT_RE = re.compile(
    r"\b(?:the\s+)?(?:term|word|name|phrase|label)\b.{0,90}"
    r"\b(?:originated|was coined|were coined|coined|derived|was derived)\b",
    re.I,
)


def extract_year_hints(
    *,
    genre_id: str,
    title: str,
    summary: str | None,
    origins: list[str],
    categories: list[str],
) -> list[YearHint]:
    """Extract candidate timeline years from already stored DB fields."""
    observations = _extract_year_observations(
        genre_id=genre_id,
        title=title,
        summary=summary,
        origins=origins,
        categories=categories,
    )
    if not observations:
        return []
    return [_build_weighted_hint(genre_id=genre_id, title=title, observations=observations)]


def is_regional_music_page_title(title: str) -> bool:
    """Return true for regional overview pages like ``Music of Austria``."""
    return bool(REGIONAL_MUSIC_PAGE_RE.match(title.strip()))


def _extract_year_observations(
    *,
    genre_id: str,
    title: str,
    summary: str | None,
    origins: list[str],
    categories: list[str],
) -> list[YearObservation]:
    observations: list[YearObservation] = []

    for origin in origins:
        for _, start, end in _parse_span_matches(origin):
            observations.append(
                YearObservation(
                    start=start,
                    end=end,
                    weight=10.0,
                    confidence="high",
                    year_kind="origin",
                    source_type="infobox_origin",
                    source_field="wg_origins.value",
                    evidence=_compact(origin),
                    reason="infobox_origin_has_parseable_temporal_hint",
                    score=95,
                )
            )

    if summary:
        for sentence_index, sentence in enumerate(_split_sentences(summary)):
            if not _has_temporal_hint(sentence):
                continue
            if _NAMING_CONTEXT_RE.search(sentence):
                continue

            is_lead = sentence_index <= 1
            spans = _parse_span_matches(sentence)
            for match_start, start, end in spans:
                context_kind = _temporal_context_kind(sentence, match_start)
                if context_kind is None:
                    continue
                local_context = sentence[max(0, match_start - 120): match_start + 120]
                if context_kind == "strong":
                    weight = 7.5 if is_lead else 5.0
                    confidence = "medium"
                    score = 84 if is_lead else 72
                    reason = (
                        "lead_summary_origin_verb_near_year"
                        if is_lead
                        else "summary_temporal_verb_near_year"
                    )
                    year_kind = _kind_from_sentence(local_context)
                elif context_kind == "weak":
                    weight = 3.2 if is_lead else 2.4
                    confidence = "low"
                    score = 50 if is_lead else 44
                    reason = "summary_popularity_temporal_hint"
                    year_kind = "popularity"
                else:
                    weight = 0.45
                    confidence = "low"
                    score = 18
                    reason = "summary_influence_temporal_hint"
                    year_kind = "influence"
                observations.append(
                    YearObservation(
                        start=start,
                        end=end,
                        weight=weight,
                        confidence=confidence,
                        year_kind=year_kind,
                        source_type="summary_sentence",
                        source_field=f"summary.sentence[{sentence_index}]",
                        evidence=_compact(sentence),
                        reason=reason,
                        score=score,
                    )
                )

    for category in categories:
        if not _category_is_timeline_relevant(category):
            continue
        for _, start, end in _parse_span_matches(category):
            span_width = _span_width(start, end)
            observations.append(
                YearObservation(
                    start=start,
                    end=end,
                    weight=0.65 if span_width <= 12 else 0.15,
                    confidence="low",
                    year_kind="period",
                    source_type="category",
                    source_field="wg_categories.category",
                    evidence=category,
                    reason="timeline_relevant_category_has_temporal_hint",
                    score=30,
                )
            )

    return observations


def _build_weighted_hint(
    *,
    genre_id: str,
    title: str,
    observations: list[YearObservation],
) -> YearHint:
    if all(item.source_type == "category" for item in observations):
        observations = _category_observations_for_timeline(observations)
    primary = max(observations, key=lambda item: (item.weight, item.score, -item.start))
    direct_core = [
        item
        for item in observations
        if item.source_type == "infobox_origin"
        or item.year_kind in {"origin", "emergence", "creation", "first_appearance"}
    ]
    non_influence = [
        item
        for item in observations
        if item.year_kind not in {"influence"} and item.weight >= 0.6
    ] or observations
    beginning_pool = direct_core or non_influence
    beginning_observations = _earliest_observation_cluster(beginning_pool)
    relevance_observations = (
        direct_core
        + [
            item
            for item in observations
            if item.year_kind == "popularity" and item.weight >= 1.0
        ]
        if direct_core
        else non_influence
    )
    category_only = all(item.source_type == "category" for item in observations)
    if category_only:
        beginning_observations = [primary]
        relevance_observations = _category_relevance_observations(
            observations,
            beginning_observations,
        )

    beginning_points = [
        (_span_midpoint(item.start, item.end), item.weight)
        for item in beginning_observations
    ]
    beginning_mean = _weighted_mean(beginning_points)
    beginning_sd = _weighted_sd(beginning_points, beginning_mean)
    beginning_start_points = [(item.start, item.weight) for item in beginning_observations]
    beginning_end_points = [
        ((item.end if item.end is not None else item.start), item.weight)
        for item in beginning_observations
    ]
    beginning_start = int(round(_weighted_quantile(beginning_start_points, 0.16)))
    beginning_end = int(round(_weighted_quantile(beginning_end_points, 0.84)))
    beginning_start = max(900, min(beginning_start, 2050))
    beginning_end = max(beginning_start, min(beginning_end, 2050))

    relevance_points = [
        (_span_midpoint(item.start, item.end), item.weight)
        for item in relevance_observations
    ]
    relevance_mean = _weighted_mean(relevance_points)
    relevance_sd = _weighted_sd(relevance_points, relevance_mean)
    relevance_end_points = [
        ((item.end if item.end is not None else item.start), item.weight)
        for item in relevance_observations
    ]
    relevance_start = beginning_start
    relevance_end_value = int(round(_weighted_quantile(relevance_end_points, 0.84)))
    relevance_end_value = max(relevance_start, min(relevance_end_value, 2050))
    relevance_end = (
        relevance_end_value
        if category_only or _has_later_relevance_evidence(relevance_observations, beginning_end)
        else None
    )
    year_end = beginning_end if beginning_end != beginning_start else None
    confidence = _combined_confidence(non_influence)

    return YearHint(
        genre_id=genre_id,
        title=title,
        year_start=beginning_start,
        year_end=year_end,
        confidence=confidence,
        year_kind=primary.year_kind,
        source_type=primary.source_type,
        source_field=primary.source_field,
        evidence=primary.evidence,
        reason="weighted_direct_year_distribution",
        score=max(item.score for item in non_influence),
        estimated_start=beginning_start,
        estimated_end=beginning_end,
        year_mean=round(beginning_mean, 2),
        year_sd=round(beginning_sd, 2),
        year_observation_count=len(observations),
        beginning_start=beginning_start,
        beginning_end=beginning_end,
        beginning_mean=round(beginning_mean, 2),
        beginning_sd=round(beginning_sd, 2),
        beginning_observation_count=len(beginning_observations),
        relevance_start=relevance_start,
        relevance_end=relevance_end,
        relevance_mean=round(relevance_mean, 2),
        relevance_sd=round(relevance_sd, 2),
        relevance_observation_count=len(relevance_observations),
    )


async def evaluate_year_hint_methods(limit: int = 4000) -> YearHintEvaluation:
    """Run the exploratory extractor against live rows and summarize output."""
    async with session_scope() as session:
        result = await session.execute(
            text(
                """
                SELECT
                    g.id,
                    g.wikipedia_title,
                    g.summary,
                    COALESCE(array_agg(DISTINCT o.value) FILTER (WHERE o.value IS NOT NULL), '{}')
                        AS origins,
                    COALESCE(
                        array_agg(DISTINCT c.category)
                            FILTER (WHERE c.category IS NOT NULL),
                        '{}'
                    ) AS categories,
                    min(o.parsed_year_start) FILTER (WHERE o.parsed_year_start IS NOT NULL)
                        AS existing_year_start
                FROM wg_genres g
                LEFT JOIN wg_origins o ON o.genre_id = g.id
                LEFT JOIN wg_categories c ON c.genre_id = g.id
                WHERE g.deleted_at IS NULL
                  AND g.is_non_genre = false
                GROUP BY g.id, g.wikipedia_title, g.summary
                ORDER BY g.monthly_views_p30 DESC NULLS LAST, g.wikipedia_title
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        rows = [dict(row) for row in result.mappings()]

    total_hints = 0
    with_any = 0
    best_by_source: Counter[str] = Counter()
    best_by_confidence: Counter[str] = Counter()
    samples_by_source: dict[str, list[YearHint]] = {}
    mismatch_samples: list[dict[str, Any]] = []
    no_hint_samples: list[dict[str, str]] = []

    for row in rows:
        if is_regional_music_page_title(row["wikipedia_title"]):
            continue
        hints = extract_year_hints(
            genre_id=row["id"],
            title=row["wikipedia_title"],
            summary=row["summary"],
            origins=list(row["origins"] or []),
            categories=list(row["categories"] or []),
        )
        total_hints += len(hints)

        if not hints:
            if len(no_hint_samples) < 20:
                no_hint_samples.append(
                    {
                        "id": row["id"],
                        "title": row["wikipedia_title"],
                        "summary": _compact(row["summary"] or "", limit=160),
                    }
                )
            continue

        with_any += 1
        best = hints[0]
        best_by_source[best.source_type] += 1
        best_by_confidence[best.confidence] += 1
        samples_by_source.setdefault(best.source_type, [])
        if len(samples_by_source[best.source_type]) < 12:
            samples_by_source[best.source_type].append(best)

        existing_year = row["existing_year_start"]
        if (
            existing_year is not None
            and abs(int(existing_year) - best.year_start) >= 10
            and len(mismatch_samples) < 30
        ):
            mismatch_samples.append(
                {
                    "id": row["id"],
                    "title": row["wikipedia_title"],
                    "existing_year_start": int(existing_year),
                    "best_year_start": best.year_start,
                    "best_year_end": best.year_end,
                    "source_type": best.source_type,
                    "confidence": best.confidence,
                    "evidence": best.evidence,
                }
            )

    return YearHintEvaluation(
        genres_sampled=len(rows),
        genres_with_any_hint=with_any,
        total_hints=total_hints,
        best_by_source=best_by_source,
        best_by_confidence=best_by_confidence,
        mismatch_samples=mismatch_samples,
        no_hint_samples=no_hint_samples,
        samples_by_source=samples_by_source,
    )


async def rebuild_timeline_year_hints(
    *,
    dry_run: bool = False,
    sample_size: int = 20,
) -> TimelineYearHintStats:
    """Rebuild the persisted best-hint table for all visible genres."""
    await apply_migrations()
    engine = get_engine()
    stats = TimelineYearHintStats(dry_run=dry_run)

    async with engine.begin() as conn:
        rows = (
            (
                await conn.execute(
                    text("""
                        SELECT
                            g.id,
                            g.wikipedia_title,
                            g.summary,
                            COALESCE(
                                array_agg(DISTINCT o.value)
                                    FILTER (WHERE o.value IS NOT NULL),
                                '{}'
                            ) AS origins,
                            COALESCE(
                                array_agg(DISTINCT c.category)
                                    FILTER (WHERE c.category IS NOT NULL),
                                '{}'
                            ) AS categories
                        FROM wg_genres g
                        LEFT JOIN wg_origins o ON o.genre_id = g.id
                        LEFT JOIN wg_categories c ON c.genre_id = g.id
                        WHERE g.deleted_at IS NULL
                          AND g.is_non_genre = false
                        GROUP BY g.id, g.wikipedia_title, g.summary
                        ORDER BY g.wikipedia_title
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
        stats.total_genres = len(rows)

        materialized_rows = []
        for row in rows:
            if is_regional_music_page_title(row["wikipedia_title"]):
                stats.excluded_regional += 1
                materialized_rows.append(
                    {
                        "genre_id": row["id"],
                        "has_hint": False,
                        "year_start": None,
                        "year_end": None,
                        "confidence": None,
                        "year_kind": None,
                        "source_type": None,
                        "source_field": None,
                        "evidence": None,
                        "reason": None,
                        "score": None,
                        "estimated_start": None,
                        "estimated_end": None,
                        "year_mean": None,
                        "year_sd": None,
                        "year_observation_count": None,
                        "beginning_start": None,
                        "beginning_end": None,
                        "beginning_mean": None,
                        "beginning_sd": None,
                        "beginning_observation_count": None,
                        "relevance_start": None,
                        "relevance_end": None,
                        "relevance_mean": None,
                        "relevance_sd": None,
                        "relevance_observation_count": None,
                        "excluded_reason": "regional_music_overview_page",
                        "parser_version": PARSER_VERSION,
                    }
                )
                continue
            hints = extract_year_hints(
                genre_id=row["id"],
                title=row["wikipedia_title"],
                summary=row["summary"],
                origins=list(row["origins"] or []),
                categories=list(row["categories"] or []),
            )
            best = hints[0] if hints else None
            if best is None:
                stats.no_hint += 1
                materialized_rows.append(
                    {
                        "genre_id": row["id"],
                        "has_hint": False,
                        "year_start": None,
                        "year_end": None,
                        "confidence": None,
                        "year_kind": None,
                        "source_type": None,
                        "source_field": None,
                        "evidence": None,
                        "reason": None,
                        "score": None,
                        "estimated_start": None,
                        "estimated_end": None,
                        "year_mean": None,
                        "year_sd": None,
                        "year_observation_count": None,
                        "beginning_start": None,
                        "beginning_end": None,
                        "beginning_mean": None,
                        "beginning_sd": None,
                        "beginning_observation_count": None,
                        "relevance_start": None,
                        "relevance_end": None,
                        "relevance_mean": None,
                        "relevance_sd": None,
                        "relevance_observation_count": None,
                        "excluded_reason": None,
                        "parser_version": PARSER_VERSION,
                    }
                )
                continue

            stats.hints_found += 1
            stats.by_source[best.source_type] += 1
            stats.by_confidence[best.confidence] += 1
            if len(stats.sample) < sample_size:
                stats.sample.append(best)
            materialized_rows.append(
                {
                    "genre_id": best.genre_id,
                    "has_hint": True,
                    "year_start": best.year_start,
                    "year_end": best.year_end,
                    "confidence": best.confidence,
                    "year_kind": best.year_kind,
                    "source_type": best.source_type,
                    "source_field": best.source_field,
                    "evidence": best.evidence,
                    "reason": best.reason,
                    "score": best.score,
                    "estimated_start": best.estimated_start,
                    "estimated_end": best.estimated_end,
                    "year_mean": best.year_mean,
                    "year_sd": best.year_sd,
                    "year_observation_count": best.year_observation_count,
                    "beginning_start": best.beginning_start,
                    "beginning_end": best.beginning_end,
                    "beginning_mean": best.beginning_mean,
                    "beginning_sd": best.beginning_sd,
                    "beginning_observation_count": best.beginning_observation_count,
                    "relevance_start": best.relevance_start,
                    "relevance_end": best.relevance_end,
                    "relevance_mean": best.relevance_mean,
                    "relevance_sd": best.relevance_sd,
                    "relevance_observation_count": best.relevance_observation_count,
                    "excluded_reason": None,
                    "parser_version": PARSER_VERSION,
                }
            )

        if dry_run:
            return stats

        await conn.execute(text("DELETE FROM wg_timeline_year_hints"))
        if materialized_rows:
            await conn.execute(
                text("""
                    INSERT INTO wg_timeline_year_hints (
                        genre_id,
                        has_hint,
                        year_start,
                        year_end,
                        confidence,
                        year_kind,
                        source_type,
                        source_field,
                        evidence,
                        reason,
                        score,
                        estimated_start,
                        estimated_end,
                        year_mean,
                        year_sd,
                        year_observation_count,
                        beginning_start,
                        beginning_end,
                        beginning_mean,
                        beginning_sd,
                        beginning_observation_count,
                        relevance_start,
                        relevance_end,
                        relevance_mean,
                        relevance_sd,
                        relevance_observation_count,
                        excluded_reason,
                        parser_version,
                        updated_at
                    )
                    VALUES (
                        :genre_id,
                        :has_hint,
                        :year_start,
                        :year_end,
                        :confidence,
                        :year_kind,
                        :source_type,
                        :source_field,
                        :evidence,
                        :reason,
                        :score,
                        :estimated_start,
                        :estimated_end,
                        :year_mean,
                        :year_sd,
                        :year_observation_count,
                        :beginning_start,
                        :beginning_end,
                        :beginning_mean,
                        :beginning_sd,
                        :beginning_observation_count,
                        :relevance_start,
                        :relevance_end,
                        :relevance_mean,
                        :relevance_sd,
                        :relevance_observation_count,
                        :excluded_reason,
                        :parser_version,
                        now()
                    )
                """),
                materialized_rows,
            )
        stats.rows_written = len(materialized_rows)
        logger.info(
            "timeline_year_hints_rebuilt",
            total_genres=stats.total_genres,
            hints_found=stats.hints_found,
            no_hint=stats.no_hint,
            excluded_regional=stats.excluded_regional,
        )

    return stats


def _hint_sort_key(hint: YearHint) -> tuple[int, int, int]:
    confidence_rank = {"high": 0, "medium": 1, "low": 2}
    return (confidence_rank.get(hint.confidence, 9), -hint.score, hint.year_start)


def _split_sentences(text_value: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text_value).strip()
    if not normalized:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]


def _has_temporal_hint(text_value: str) -> bool:
    return bool(
        _YEAR_RE.search(text_value)
        or _DECADE_RE.search(text_value)
        or _CENTURY_RE.search(text_value)
    )


def _parse_span(text_value: str) -> tuple[int, int | None] | None:
    spans = _parse_spans(text_value)
    return spans[0] if spans else None


def _parse_spans(text_value: str) -> list[tuple[int, int | None]]:
    return [(start, end) for _, start, end in _parse_span_matches(text_value)]


def _parse_span_matches(text_value: str) -> list[tuple[int, int, int | None]]:
    candidates: list[tuple[int, int, int, int | None]] = []

    for match in _YEAR_RANGE_RE.finditer(text_value):
        start = _qualified_decade_start(match.group(1), int(match.group(2)))
        end = _qualified_decade_end(match.group(3), int(match.group(4)))
        candidates.append((match.start(), 0, start, end if end >= start else None))

    range_spans = [match.span() for match in _YEAR_RANGE_RE.finditer(text_value)]

    for match in _DECADE_RE.finditer(text_value):
        if _inside_any_span(match.span(), range_spans):
            continue
        decade = int(match.group(2))
        qualifier = match.group(1)
        candidates.append(
            (
                match.start(),
                1,
                _qualified_decade_start(qualifier, decade),
                _qualified_decade_end(qualifier, decade),
            )
        )

    for match in _YEAR_RE.finditer(text_value):
        if _inside_any_span(match.span(), range_spans):
            continue
        year = int(match.group(1))
        candidates.append((match.start(), 2, year, None))

    for match in _CENTURY_RE.finditer(text_value):
        century = int(match.group(1))
        start = (century - 1) * 100
        candidates.append((match.start(), 3, start, start + 99))

    candidates.sort(key=lambda candidate: (candidate[0], candidate[1]))
    return [(position, start, end) for position, _, start, end in candidates]


def _temporal_context_kind(sentence: str, match_start: int) -> str | None:
    before = sentence[:match_start]
    after = sentence[match_start: match_start + 90]
    strong_pos = _last_match_end(_STRONG_ORIGIN_RE, before)
    weak_pos = _last_match_end(_WEAKER_TEMPORAL_RE, before)
    influence_pos = _last_match_end(_INFLUENCE_TEMPORAL_RE, before)
    positions = [
        (pos, kind)
        for pos, kind in (
            (strong_pos, "strong"),
            (weak_pos, "weak"),
            (influence_pos, "influence"),
        )
        if pos is not None
    ]
    if positions:
        nearest_pos, nearest_kind = max(positions, key=lambda item: item[0])
        if match_start - nearest_pos <= 120:
            return nearest_kind
    if _WEAKER_TEMPORAL_RE.search(after):
        return "weak"
    if _INFLUENCE_TEMPORAL_RE.search(after):
        return "influence"
    return None


def _last_match_end(pattern: re.Pattern[str], text_value: str) -> int | None:
    matches = list(pattern.finditer(text_value))
    if not matches:
        return None
    return matches[-1].end()


def _span_midpoint(start: int, end: int | None) -> float:
    if end is None:
        return float(start)
    return (start + end) / 2


def _span_width(start: int, end: int | None) -> int:
    if end is None:
        return 0
    return max(0, end - start)


def _category_observations_for_timeline(
    observations: list[YearObservation],
) -> list[YearObservation]:
    """Prefer specific period categories over broad century buckets."""
    narrow = [item for item in observations if _span_width(item.start, item.end) <= 12]
    return narrow or observations


def _category_relevance_observations(
    observations: list[YearObservation],
    beginning_observations: list[YearObservation],
) -> list[YearObservation]:
    """Use activity-by-decade categories as relevance spans when available."""
    activity_periods = [
        item
        for item in observations
        if _span_width(item.start, item.end) <= 12
        and re.search(r"\b(?:1[0-9]|20)[0-9]0s\s+in\s+music\b", item.evidence, re.I)
    ]
    return activity_periods or beginning_observations


def _earliest_observation_cluster(
    observations: list[YearObservation],
) -> list[YearObservation]:
    """Keep beginning uncertainty anchored to the first direct temporal cluster."""
    if not observations:
        return []
    earliest = min(observations, key=lambda item: (item.start, item.end or item.start))
    earliest_end = earliest.end if earliest.end is not None else earliest.start
    max_start = max(earliest.start + 12, earliest_end)
    cluster = [item for item in observations if item.start <= max_start]
    return cluster or [earliest]


def _has_later_relevance_evidence(
    observations: list[YearObservation],
    beginning_end: int,
) -> bool:
    """Return true when evidence extends beyond the beginning window itself."""
    for item in observations:
        item_end = item.end if item.end is not None else item.start
        if item_end <= beginning_end + 2:
            continue
        if item.year_kind in {"popularity", "period"}:
            return True
        if (
            item.year_kind in {"origin", "emergence", "creation", "first_appearance"}
            and item.start > beginning_end + 2
        ):
            return True
        if item.source_type == "infobox_origin" and item.start > beginning_end + 2:
            return True
        if item.start <= beginning_end and item_end - beginning_end >= 8:
            return True
    return False


def _weighted_mean(points: list[tuple[float, float]]) -> float:
    total_weight = sum(weight for _, weight in points)
    if total_weight <= 0:
        return points[0][0] if points else 0
    return sum(value * weight for value, weight in points) / total_weight


def _weighted_sd(points: list[tuple[float, float]], mean: float) -> float:
    total_weight = sum(weight for _, weight in points)
    if total_weight <= 0:
        return 0
    variance = sum(((value - mean) ** 2) * weight for value, weight in points) / total_weight
    return variance**0.5


def _weighted_quantile(points: list[tuple[int | float, float]], quantile: float) -> float:
    if not points:
        return 0
    ordered = sorted(points, key=lambda item: item[0])
    total_weight = sum(max(0, weight) for _, weight in ordered)
    if total_weight <= 0:
        return float(ordered[0][0])
    threshold = total_weight * max(0, min(1, quantile))
    running = 0.0
    for value, weight in ordered:
        running += max(0, weight)
        if running >= threshold:
            return float(value)
    return float(ordered[-1][0])


def _combined_confidence(observations: list[YearObservation]) -> str:
    if any(item.confidence == "high" and item.weight >= 5 for item in observations):
        return "high"
    if any(item.confidence in {"high", "medium"} and item.weight >= 2 for item in observations):
        return "medium"
    return "low"


def _inside_any_span(span: tuple[int, int], enclosing_spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(
        start >= range_start and end <= range_end
        for range_start, range_end in enclosing_spans
    )


def _qualified_decade_start(qualifier: str | None, decade: int) -> int:
    if qualifier is None:
        return decade
    q = qualifier.lower()
    if q == "mid":
        return decade + 4
    if q == "late":
        return decade + 7
    return decade


def _qualified_decade_end(qualifier: str | None, decade: int) -> int:
    if qualifier is None:
        return decade + 9
    q = qualifier.lower()
    if q == "early":
        return decade + 3
    if q == "mid":
        return decade + 6
    return decade + 9


def _kind_from_sentence(sentence: str) -> str:
    lower = sentence.lower()
    if "first appeared" in lower or "appeared" in lower:
        return "first_appearance"
    if "popular" in lower or "prominence" in lower:
        return "popularity"
    if "created" in lower or "pioneered" in lower:
        return "creation"
    if "originated" in lower or "emerged" in lower or "arose" in lower:
        return "emergence"
    return "period"


def _category_is_timeline_relevant(category: str) -> bool:
    lower = category.lower()
    if "music" not in lower and "genre" not in lower and "counterculture" not in lower:
        return False
    if "birth" in lower or "death" in lower:
        return False
    return bool(_DECADE_RE.search(category) or _CENTURY_RE.search(category))


def _compact(text_value: str, limit: int = 220) -> str:
    compacted = re.sub(r"\s+", " ", text_value).strip()
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 1].rstrip() + "…"
