from wiki_genres.loader.region_production import (
    AliasProxyCandidate,
    _classify_zero_child_promoted_region,
    _is_valid_regional_title,
    _is_valid_review_decision,
    _is_safe_alias_proxy_target,
    _is_style_proxy_title,
    _parent_preference_rank,
    proxy_genre_evidence,
    relation_for_proxy_title,
)


def test_style_proxy_title_accepts_demonym_music_pages() -> None:
    assert _is_style_proxy_title("Jamaican styles of music", "jamaican")
    assert _is_style_proxy_title("Albanian folk music", "albanian")
    assert not _is_style_proxy_title("Music of Jamaica", "jamaican")


def test_alias_proxy_cleanup_keeps_broad_cultural_targets_for_review() -> None:
    candidate = AliasProxyCandidate(
        old_region_id="region-assyrian-syriac",
        old_name="assyrian/syriac",
        old_kind="unknown",
        old_wikipedia_title="Assyrian/Syriac folk music",
        target_region_id="region-middle-east",
        target_name="Middle East",
        target_kind="subregion",
    )

    assert not _is_safe_alias_proxy_target(candidate)


def test_alias_proxy_cleanup_allows_country_targets() -> None:
    candidate = AliasProxyCandidate(
        old_region_id="region-jamaican",
        old_name="jamaican",
        old_kind="cultural_region",
        old_wikipedia_title="Jamaican styles of music",
        target_region_id="region-jamaica",
        target_name="Jamaica",
        target_kind="cultural_region",
    )

    assert _is_safe_alias_proxy_target(candidate)


def test_proxy_title_relation_prefers_traditional_for_folk_pages() -> None:
    assert relation_for_proxy_title("Albanian folk music") == "traditional_region"
    assert relation_for_proxy_title("Bahamian styles of music") == "regional_scene"


def test_proxy_genre_evidence_names_source_and_target() -> None:
    evidence = proxy_genre_evidence("Jamaican styles of music", "jamaican", "Jamaica")

    assert "Jamaican styles of music" in evidence
    assert "'jamaican'" in evidence
    assert "'Jamaica'" in evidence


def test_valid_regional_title_detection_accepts_music_of_and_demonym_titles() -> None:
    assert _is_valid_regional_title("Music of Ghana")
    assert _is_valid_regional_title("Ghanaian music")
    assert not _is_valid_regional_title("List of Sub-Saharan African folk music traditions")


def test_review_decision_validation_accepts_broad_specific_keep_decisions() -> None:
    assert _is_valid_review_decision("keep_broad")


def test_reviewed_empty_zero_child_staged_keep_explanation_is_not_unresolved() -> None:
    classification = _classify_zero_child_promoted_region(
        {
            "reason": "reviewed_empty",
            "staged_decision": {
                "decision": "keep_broad",
                "explanation": "High-confidence keep with explanation.",
            },
        }
    )

    assert classification.reason == "reviewed_empty"
    assert classification.unresolved is False


def test_non_city_zero_child_reasons_are_not_unresolved_blockers() -> None:
    classification = _classify_zero_child_promoted_region(
        {
            "reason": "only_context_or_style_mentions",
            "staged_decision": None,
        }
    )

    assert classification.reason == "only_context_or_style_mentions"
    assert classification.unresolved is False


def test_city_zero_child_reason_remains_unresolved_until_hidden_or_removed() -> None:
    classification = _classify_zero_child_promoted_region(
        {
            "reason": "city_scene_without_owned_children",
            "staged_decision": None,
        }
    )

    assert classification.unresolved is True


def test_parent_preference_helper_ranks_country_parents_ahead_of_continent_parents() -> None:
    assert _parent_preference_rank(kind="country", name="Ghana") < _parent_preference_rank(
        kind="continent",
        name="Africa",
    )
