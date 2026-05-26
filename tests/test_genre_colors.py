"""Tests for graph-similarity genre colors."""

from wiki_genres.loader.genre_colors import (
    ColorEdge,
    ColorGenre,
    ColorRoot,
    compute_genre_colors,
)


def test_child_inherits_root_affinity_color() -> None:
    rows, _ = compute_genre_colors(
        [
            ColorGenre("rock", "Rock"),
            ColorGenre("metal", "Metal", 1000),
        ],
        [ColorRoot("rock", "Rock", "#c44e35")],
        [ColorEdge("rock", "metal", "subgenre", "infobox")],
    )

    metal = next(row for row in rows if row.genre_id == "metal")

    assert metal.root_affinity == {"Rock": 1.0}
    assert metal.confidence > 0.6
    assert metal.color_hex.startswith("#")


def test_multiple_parents_blend_root_affinities() -> None:
    rows, _ = compute_genre_colors(
        [
            ColorGenre("rock", "Rock"),
            ColorGenre("electronic", "Electronic"),
            ColorGenre("electro-rock", "Electro-rock", 500),
        ],
        [
            ColorRoot("rock", "Rock", "#c44e35"),
            ColorRoot("electronic", "Electronic", "#2397aa"),
        ],
        [
            ColorEdge("rock", "electro-rock", "subgenre", "infobox"),
            ColorEdge("electronic", "electro-rock", "fusion_genre", "infobox"),
        ],
    )

    blended = next(row for row in rows if row.genre_id == "electro-rock")

    assert blended.root_affinity["Rock"] > blended.root_affinity["Electronic"]
    assert blended.root_affinity["Electronic"] > 0.35
    assert blended.confidence > 0.65


def test_direct_electronic_root_parent_is_not_washed_out_by_dense_neighbors() -> None:
    rows, _ = compute_genre_colors(
        [
            ColorGenre("electronic", "Electronic"),
            ColorGenre("hip-hop", "Hip-hop"),
            ColorGenre("rock", "Rock"),
            ColorGenre("jazz", "Jazz"),
            ColorGenre("idm", "Intelligent dance music", 500),
            ColorGenre("breakcore", "Breakcore", 100),
            ColorGenre("trip-hop", "Trip hop", 100),
        ],
        [
            ColorRoot("electronic", "Electronic music", "#2397aa"),
            ColorRoot("hip-hop", "Hip-hop", "#d8872d"),
            ColorRoot("rock", "Rock", "#c44e35"),
            ColorRoot("jazz", "Jazz", "#6b63bd"),
        ],
        [
            ColorEdge("electronic", "idm", "derivative", "infobox"),
            ColorEdge("hip-hop", "trip-hop", "subgenre", "infobox"),
            ColorEdge("rock", "trip-hop", "subgenre", "infobox"),
            ColorEdge("trip-hop", "idm", "derivative", "infobox"),
            ColorEdge("jazz", "breakcore", "subgenre", "infobox"),
            ColorEdge("breakcore", "idm", "derivative", "infobox"),
        ],
    )

    idm = next(row for row in rows if row.genre_id == "idm")

    assert idm.root_affinity["Electronic music"] >= 0.5
    assert idm.root_affinity["Electronic music"] < 0.7


def test_non_electronic_direct_root_does_not_get_affinity_floor() -> None:
    rows, _ = compute_genre_colors(
        [
            ColorGenre("electronic", "Electronic"),
            ColorGenre("rock", "Rock"),
            ColorGenre("jazz", "Jazz"),
            ColorGenre("fusion", "Dense rock fusion", 500),
            ColorGenre("jazz-child", "Jazz child", 100),
        ],
        [
            ColorRoot("electronic", "Electronic", "#2397aa"),
            ColorRoot("rock", "Rock", "#c44e35"),
            ColorRoot("jazz", "Jazz", "#6b63bd"),
        ],
        [
            ColorEdge("rock", "fusion", "derivative", "infobox"),
            ColorEdge("jazz", "jazz-child", "subgenre", "infobox"),
            ColorEdge("jazz-child", "fusion", "derivative", "infobox"),
            ColorEdge("electronic", "fusion", "fusion_genre", "infobox"),
        ],
    )

    fusion = next(row for row in rows if row.genre_id == "fusion")

    assert fusion.root_affinity["Rock"] < 0.5


def test_related_genre_with_display_evidence_contributes_affinity() -> None:
    rows, _ = compute_genre_colors(
        [
            ColorGenre("pop", "Pop"),
            ColorGenre("dance-pop", "Dance-pop"),
        ],
        [ColorRoot("pop", "Pop", "#d85a9e")],
        [
            ColorEdge(
                "pop",
                "dance-pop",
                "related_genre",
                "inbound_index",
                evidence_relation="subgenre",
            )
        ],
    )

    dance_pop = next(row for row in rows if row.genre_id == "dance-pop")

    assert dance_pop.root_affinity == {"Pop": 1.0}
    assert dance_pop.confidence > 0.4


def test_music_region_inherits_affinity_from_colored_children() -> None:
    rows, _ = compute_genre_colors(
        [
            ColorGenre("rock", "Rock"),
            ColorGenre("music-of-example", "Music of Example"),
            ColorGenre("example-rock", "Example rock", 100),
        ],
        [ColorRoot("rock", "Rock", "#c44e35")],
        [
            ColorEdge("rock", "example-rock", "subgenre", "infobox"),
            ColorEdge("music-of-example", "example-rock", "regional_scene", "infobox"),
        ],
    )

    region = next(row for row in rows if row.genre_id == "music-of-example")

    assert region.root_affinity == {"Rock": 1.0}
    assert region.confidence > 0.4


def test_music_region_can_seed_uncolored_regional_children() -> None:
    rows, _ = compute_genre_colors(
        [
            ColorGenre("rock", "Rock"),
            ColorGenre("music-of-example", "Music of Example"),
            ColorGenre("known-example-rock", "Known Example rock", 100),
            ColorGenre("obscure-example-rock", "Obscure Example rock", 1),
        ],
        [ColorRoot("rock", "Rock", "#c44e35")],
        [
            ColorEdge("rock", "known-example-rock", "subgenre", "infobox"),
            ColorEdge("music-of-example", "known-example-rock", "regional_scene", "infobox"),
            ColorEdge("music-of-example", "obscure-example-rock", "regional_scene", "infobox"),
        ],
    )

    obscure = next(row for row in rows if row.genre_id == "obscure-example-rock")

    assert obscure.root_affinity == {"Rock": 1.0}
    assert obscure.confidence > 0.25


def test_regional_edges_do_not_muddy_non_regional_genres() -> None:
    rows, _ = compute_genre_colors(
        [
            ColorGenre("rock", "Rock", 1000),
            ColorGenre("pop", "Pop", 1000),
            ColorGenre("music-of-example", "Music of Example"),
            ColorGenre("example-pop", "Example pop", 10),
        ],
        [
            ColorRoot("rock", "Rock", "#c44e35"),
            ColorRoot("pop", "Pop", "#d85a9e"),
        ],
        [
            # Region is connected to a Pop-ish local child.
            ColorEdge("music-of-example", "example-pop", "regional_scene", "region_promotion"),
            ColorEdge("pop", "example-pop", "subgenre", "infobox"),
            # Region also connects to Rock; this must not pull Pop affinity into Rock.
            ColorEdge(
                "music-of-example",
                "rock",
                "regional_scene",
                "region_promotion",
                block_forward=True,
            ),
        ],
    )

    rock = next(row for row in rows if row.genre_id == "rock")

    assert rock.root_affinity == {"Rock": 1.0}
