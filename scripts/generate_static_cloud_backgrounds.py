#!/usr/bin/env python3
"""Generate static cloud background packets for Music and country clouds.

The generated JSON packet is the canonical artifact: it preserves the same
RGBA field quality that the browser receives from /v1/render/cloud/stream.
PNG files are lossless previews of that source RGBA field before the browser's
small blur/overlay postprocess.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import text

from wiki_genres.api.routes.genres import get_genre_cloud
from wiki_genres.api.routes.render import _cloud_background_packet_from_node
from wiki_genres.db import dispose_engine, session_scope

DEFAULT_OUTPUT_DIR = Path("src/wiki_genres/api/static/generated/cloud-backgrounds")


@dataclass(frozen=True)
class CloudBackgroundTarget:
    key: str
    label: str
    region_id: str | None = None
    country_name: str | None = None


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "untitled"


def _context_signature(target: CloudBackgroundTarget, width: int, height: int) -> str:
    return "|".join(("", target.region_id or "", str(width), str(height), "background"))


def _packet_stem(target: CloudBackgroundTarget, width: int, height: int) -> str:
    if target.region_id:
        return f"{_slug(target.label)}__{_slug(target.region_id)}__{width}x{height}"
    return f"music__{width}x{height}"


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(payload, crc)
    return len(payload).to_bytes(4, "big") + chunk_type + payload + crc.to_bytes(4, "big")


def _write_rgba_png(path: Path, *, width: int, height: int, rgba: bytes) -> None:
    expected = width * height * 4
    if len(rgba) != expected:
        raise ValueError(f"RGBA payload has {len(rgba)} bytes, expected {expected}")
    rows = bytearray()
    row_bytes = width * 4
    for y in range(height):
        rows.append(0)  # PNG filter type 0.
        start = y * row_bytes
        rows.extend(rgba[start : start + row_bytes])
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(
            b"IHDR",
            width.to_bytes(4, "big")
            + height.to_bytes(4, "big")
            + bytes((8, 6, 0, 0, 0)),
        )
        + _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
        + _png_chunk(b"IEND", b"")
    )
    path.write_bytes(payload)


async def _country_targets(*, include_non_manual: bool) -> list[CloudBackgroundTarget]:
    manual_filter = (
        ""
        if include_non_manual
        else "AND coalesce(region.raw_payload #>> '{region_accessibility,manual_access}', 'false') = 'true'"
    )
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    text(f"""
                        SELECT region.id AS region_id,
                               region.canonical_name,
                               promoted.wikipedia_title
                        FROM wg_regions region
                        JOIN wg_region_promoted_genres promoted ON promoted.region_id = region.id
                        JOIN wg_genres genre ON genre.id = promoted.genre_id
                        WHERE region.kind = 'country'
                          {manual_filter}
                          AND genre.deleted_at IS NULL
                          AND genre.is_non_genre = false
                          AND coalesce(region.raw_payload #>> '{{region_production_review,status}}', '') NOT IN (
                              'collapsed',
                              'rejected',
                              'demoted_source',
                              'hidden_from_ui'
                          )
                        ORDER BY region.canonical_name
                    """)
                )
            )
            .mappings()
            .fetchall()
        )
    return [
        CloudBackgroundTarget(
            key=f"country:{row['region_id']}",
            label=str(row["wikipedia_title"] or f"Music of {row['canonical_name']}"),
            region_id=str(row["region_id"]),
            country_name=str(row["canonical_name"]),
        )
        for row in rows
    ]


async def _load_cloud_data(target: CloudBackgroundTarget, *, limit: int) -> dict[str, Any]:
    result = await get_genre_cloud(
        limit=limit,
        x_min=None,
        x_max=None,
        y_min=None,
        y_max=None,
        scale=1.0,
        view_tx=0.0,
        view_ty=0.0,
        root_genre_id=None,
        region_id=target.region_id,
        selected_genre_id=None,
        atlas=True,
    )
    return jsonable_encoder(result)


async def _write_target(
    target: CloudBackgroundTarget,
    *,
    output_dir: Path,
    width: int,
    height: int,
    limit: int,
    force: bool,
    write_png: bool,
    packet_timeout: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = _packet_stem(target, width, height)
    packet_path = output_dir / f"{stem}.json"
    png_path = output_dir / f"{stem}.png"

    if packet_path.exists() and not force:
        packet = json.loads(packet_path.read_text())
        return {
            "key": target.key,
            "label": target.label,
            "region_id": target.region_id,
            "country_name": target.country_name,
            "packet": str(packet_path),
            "png": str(png_path) if png_path.exists() else None,
            "width": packet.get("width"),
            "height": packet.get("height"),
            "nodes": packet.get("source", {}).get("nodes"),
            "cached": True,
        }

    started = time.perf_counter()
    data = await _load_cloud_data(target, limit=limit)
    packet = _cloud_background_packet_from_node(
        data,
        viewport_width=width,
        viewport_height=height,
        context_signature=_context_signature(target, width, height),
        timeout_seconds=packet_timeout,
    )
    if not packet:
        raise RuntimeError(f"No background packet generated for {target.label}")

    packet = {
        **packet,
        "source": {
            "key": target.key,
            "label": target.label,
            "region_id": target.region_id,
            "country_name": target.country_name,
            "nodes": len(data.get("nodes") or []),
            "total_nodes": (data.get("stats") or {}).get("total_nodes"),
            "layout_key": (data.get("stats") or {}).get("layout_key"),
            "layout_source": (data.get("stats") or {}).get("layout_source"),
        },
    }
    packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n")

    if write_png:
        rgba = base64.b64decode(packet["rgba"])
        _write_rgba_png(
            png_path,
            width=int(packet["width"]),
            height=int(packet["height"]),
            rgba=rgba,
        )

    return {
        "key": target.key,
        "label": target.label,
        "region_id": target.region_id,
        "country_name": target.country_name,
        "packet": str(packet_path),
        "png": str(png_path) if write_png else None,
        "width": packet.get("width"),
        "height": packet.get("height"),
        "nodes": packet["source"]["nodes"],
        "total_nodes": packet["source"]["total_nodes"],
        "seconds": round(time.perf_counter() - started, 3),
        "cached": False,
    }


async def _targets(args: argparse.Namespace) -> list[CloudBackgroundTarget]:
    targets: list[CloudBackgroundTarget] = []
    if args.only in {"all", "music"}:
        targets.append(CloudBackgroundTarget(key="music", label="Music"))
    if args.only in {"all", "countries"}:
        countries = await _country_targets(include_non_manual=args.include_non_manual_countries)
        if args.region_id:
            region_ids = set(args.region_id)
            countries = [target for target in countries if target.region_id in region_ids]
        if args.country_limit is not None:
            countries = countries[: args.country_limit]
        targets.extend(countries)
    return targets


async def async_main(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    targets = await _targets(args)
    if not targets:
        print("No cloud background targets matched.")
        return 1

    manifest_entries: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, target in enumerate(targets, start=1):
        prefix = f"[{index}/{len(targets)}]"
        print(f"{prefix} {target.label}")
        try:
            entry = await _write_target(
                target,
                output_dir=output_dir,
                width=args.width,
                height=args.height,
                limit=args.limit,
                force=args.force,
                write_png=not args.no_png,
                packet_timeout=args.packet_timeout,
            )
        except Exception as exc:  # noqa: BLE001
            failures.append({"key": target.key, "label": target.label, "error": str(exc)})
            print(f"  failed: {exc}")
            if not args.continue_on_error:
                break
        else:
            manifest_entries.append(entry)
            cache_note = "cached" if entry.get("cached") else f"{entry.get('seconds')}s"
            print(f"  wrote {entry['packet']} ({entry['width']}x{entry['height']}, {cache_note})")

    manifest = {
        "version": "cloud-background-static-v1",
        "width": args.width,
        "height": args.height,
        "packet_kind": "rgba-base64",
        "png_kind": "lossless source RGBA before browser blur/overlay postprocess",
        "targets": manifest_entries,
        "failures": failures,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    await dispose_engine()
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--only", choices=("all", "music", "countries"), default="all")
    parser.add_argument("--region-id", action="append", help="Limit country generation to this region id.")
    parser.add_argument("--country-limit", type=int, help="Generate only the first N countries.")
    parser.add_argument("--include-non-manual-countries", action="store_true")
    parser.add_argument("--force", action="store_true", help="Regenerate existing packet files.")
    parser.add_argument("--no-png", action="store_true", help="Only write JSON packet files.")
    parser.add_argument("--packet-timeout", type=float, default=120)
    parser.add_argument("--continue-on-error", action="store_true")
    return parser.parse_args()


def main() -> None:
    raise SystemExit(asyncio.run(async_main(parse_args())))


if __name__ == "__main__":
    main()
