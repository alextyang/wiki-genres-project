"""Compact display cache for precomputed cloud layouts."""

from __future__ import annotations

from sqlalchemy import text


async def refresh_cloud_display_cache(conn: object, *, layout_key: str) -> int:
    """Refresh compact draw-time rows for one semantic cloud layout."""
    await conn.execute(  # type: ignore[attr-defined]
        text("DELETE FROM wg_genre_cloud_display_nodes WHERE layout_key = :layout_key"),
        {"layout_key": layout_key},
    )
    result = await conn.execute(  # type: ignore[attr-defined]
        text("""
            INSERT INTO wg_genre_cloud_display_nodes (
                layout_key,
                genre_id,
                x,
                y,
                text_width,
                text_height,
                box_width,
                box_height,
                box_pad_x,
                box_pad_y,
                priority,
                lod_score,
                min_visible_scale,
                show_scale,
                hide_scale,
                lod_rank,
                lod_tier,
                display_source,
                indexed_at
            )
            SELECT
                layout_key,
                genre_id,
                COALESCE(radial_x, x)::real AS x,
                COALESCE(radial_y, y)::real AS y,
                COALESCE(NULLIF(text_width, 0), width)::real AS text_width,
                COALESCE(NULLIF(text_height, 0), height)::real AS text_height,
                COALESCE(NULLIF(box_width, 0), COALESCE(NULLIF(text_width, 0), width) + box_pad_x * 2)::real AS box_width,
                COALESCE(NULLIF(box_height, 0), COALESCE(NULLIF(text_height, 0), height) + box_pad_y * 2)::real AS box_height,
                box_pad_x::real,
                box_pad_y::real,
                priority::real,
                lod_score::real,
                min_visible_scale::real,
                show_scale::real,
                hide_scale::real,
                lod_rank,
                lod_tier::smallint,
                CASE WHEN radial_x IS NOT NULL AND radial_y IS NOT NULL THEN 2 ELSE 1 END::smallint,
                now()
            FROM wg_genre_semantic_layouts
            WHERE layout_key = :layout_key
        """),
        {"layout_key": layout_key},
    )
    return int(result.rowcount or 0)
