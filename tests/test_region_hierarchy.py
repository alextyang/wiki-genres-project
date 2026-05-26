from wiki_genres.loader.region_hierarchy import (
    is_low_value_collapsible,
    is_valuable_superregion,
    reviewed_kind_for_name,
)


def test_reviewed_kind_recognizes_country_and_territory_names() -> None:
    assert reviewed_kind_for_name("Belize", "cultural_region") == "country"
    assert reviewed_kind_for_name("Montserrat", "cultural_region") == "territory"


def test_reviewed_kind_promotes_us_states_to_subregions() -> None:
    assert reviewed_kind_for_name("Texas", "unknown") == "subregion"


def test_valuable_superregions_can_stay_for_organization() -> None:
    assert is_valuable_superregion(
        name="Middle East",
        kind="cultural_region",
        owned_count=0,
        child_count=1,
        country_child_count=0,
    )
    assert is_valuable_superregion(
        name="Small island group",
        kind="subregion",
        owned_count=1,
        child_count=8,
        country_child_count=0,
    )


def test_low_value_subregions_collapse_except_special_map_subregions() -> None:
    assert is_low_value_collapsible(
        name="Minor province",
        kind="subregion",
        owned_count=1,
        candidate_count=0,
        child_count=0,
        country_parent_count=1,
        has_united_states_parent=False,
    )
    assert not is_low_value_collapsible(
        name="Sichuan",
        kind="subregion",
        owned_count=1,
        candidate_count=0,
        child_count=0,
        country_parent_count=1,
        has_united_states_parent=False,
        has_special_map_parent=True,
    )
    assert is_low_value_collapsible(
        name="Colorado",
        kind="subregion",
        owned_count=0,
        candidate_count=0,
        child_count=0,
        country_parent_count=1,
        has_united_states_parent=True,
        has_special_map_parent=True,
    )


def test_cultural_regions_with_owned_genres_are_not_collapsed() -> None:
    assert not is_low_value_collapsible(
        name="Ainu",
        kind="cultural_region",
        owned_count=1,
        candidate_count=1,
        child_count=0,
        country_parent_count=1,
        has_united_states_parent=False,
    )


def test_candidate_signals_block_low_value_collapse() -> None:
    assert not is_low_value_collapsible(
        name="Minor province",
        kind="subregion",
        owned_count=0,
        candidate_count=2,
        child_count=0,
        country_parent_count=1,
        has_united_states_parent=False,
    )


def test_single_candidate_subregions_collapse_outside_special_maps() -> None:
    assert is_low_value_collapsible(
        name="Minor province",
        kind="subregion",
        owned_count=0,
        candidate_count=1,
        child_count=0,
        country_parent_count=1,
        has_united_states_parent=False,
        has_special_map_parent=False,
    )
