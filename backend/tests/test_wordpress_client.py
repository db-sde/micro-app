"""Tests for publish-time reconciliation in pipeline/wordpress_client.py.

This is where our internal payload is reshaped into what the live
WordPress ACF schema actually accepts, and where most production 400s
originated. Everything here is exercised without network access: the
pure transforms directly, and the HTTP-backed lookups through the fake
client from conftest.

Two production bugs have dedicated regressions below:
  * the post-title cache never expired, so once warmed it hid every
    university/course created afterwards and linked_university stopped
    resolving entirely;
  * relationship names written in the document were ignored in favour of
    a weaker derived name.
"""

from __future__ import annotations

import pytest

from pipeline import wordpress_client as wc
from tests.conftest import FakeResponse


# ────────────────────────────── post types ──────────────────────────────────


def test_post_type_defaults_to_the_page_type_name() -> None:
    assert wc.get_post_type("university") == "university"
    assert wc.get_post_type("course") == "course"
    assert wc.get_post_type("specialization") == "specialization"


def test_blog_and_category_use_their_real_rest_bases() -> None:
    """"blog" is WordPress's native post type (REST base "posts"), and
    "category" would collide with the built-in category taxonomy."""
    assert wc.get_post_type("blog") == "posts"
    assert wc.get_post_type("category") == "category-page"


def test_post_type_is_overridable_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORDPRESS_POST_TYPE_COURSE", "programme")
    assert wc.get_post_type("course") == "programme"


def test_is_configured_requires_all_three_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert wc.is_configured() is False
    monkeypatch.setenv("WORDPRESS_SITE_URL", "https://wp.test")
    assert wc.is_configured() is False
    monkeypatch.setenv("WORDPRESS_APP_USER", "u")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "p")
    assert wc.is_configured() is True


def test_site_url_trailing_slash_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Otherwise every request URL ends up with a double slash."""
    monkeypatch.setenv("WORDPRESS_SITE_URL", "https://wp.test/")
    assert wc._site_url() == "https://wp.test"


# ─────────────────────────────── post titles ────────────────────────────────


def test_build_title_prefers_the_most_specific_name() -> None:
    payload = {"university_name": "Sharda", "program_name": "MBA"}
    assert wc._build_title(payload, "course", "Untitled") == "Sharda"


def test_build_title_falls_back_through_to_seo_title() -> None:
    """blog/category posts have none of the name fields."""
    payload = {"seo_title": "IGNOU MBA Admission 2026"}
    assert wc._build_title(payload, "blog", "Untitled") == "IGNOU MBA Admission 2026"


def test_build_title_uses_the_fallback_when_nothing_is_usable() -> None:
    assert wc._build_title({"university_name": None}, "course", "Untitled") == "Untitled"


# ──────────────────────────── repeater reshaping ────────────────────────────


def test_repeater_becomes_an_html_list() -> None:
    items = [{"t": "Flexible", "d": "Study anytime"}]
    html = wc._repeater_to_html_list(items, "t", "d")
    assert html == "<ul>\n<li><strong>Flexible</strong>: Study anytime</li>\n</ul>"


def test_repeater_row_with_only_one_populated_side() -> None:
    html = wc._repeater_to_html_list([{"t": "Flexible", "d": ""}], "t", "d")
    assert html == "<ul>\n<li>Flexible</li>\n</ul>"


def test_repeater_html_is_escaped() -> None:
    """Content is written by hand in Word; an unescaped < breaks the
    surrounding markup once WordPress renders it."""
    html = wc._repeater_to_html_list(
        [{"t": "A & B", "d": "<script>x</script>"}], "t", "d"
    )
    assert "&amp;" in html
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


@pytest.mark.parametrize("value", [None, [], "not a list", [{}], [None]])
def test_repeater_reshaping_returns_none_for_unusable_input(value: object) -> None:
    assert wc._repeater_to_html_list(value, "t", "d") is None


# ───────────────────────────── faculty members ──────────────────────────────


def test_faculty_extra_sub_fields_are_merged_not_dropped() -> None:
    """Live WordPress removed member_program and member_qualification.
    Sending either 400s the whole repeater, so both are folded into
    member_designation rather than losing the information."""
    rows = [
        {
            "member_name": "Dr. Ananya Rao",
            "member_designation": "Professor",
            "member_program": "MBA Program",
            "member_qualification": "Ph.D. in Marketing",
        }
    ]
    fixed = wc._fix_faculty_members(rows)
    assert fixed == [
        {
            "member_name": "Dr. Ananya Rao",
            "member_designation": "Professor, MBA Program, Ph.D. in Marketing",
        }
    ]


def test_faculty_row_without_extra_sub_fields_is_unchanged() -> None:
    rows = [{"member_name": "X", "member_designation": "Professor"}]
    assert wc._fix_faculty_members(rows) == rows


def test_faculty_merge_never_leaves_the_rejected_keys_behind() -> None:
    rows = [{"member_name": "X", "member_program": "MBA"}]
    fixed = wc._fix_faculty_members(rows)
    assert "member_program" not in fixed[0]
    assert fixed[0]["member_designation"] == "MBA"


def test_faculty_input_that_is_not_a_list_passes_through() -> None:
    assert wc._fix_faculty_members(None) is None
    assert wc._fix_faculty_members("x") == "x"


# ────────────────────────────── fee plan mapping ────────────────────────────


def test_fee_plans_map_onto_course_tier_fields() -> None:
    plans = [
        {"plan_name": "Per Semester", "plan_amount": "25,000", "plan_total": "100,000"},
        {"plan_name": "Annual Plan", "plan_amount": "50,000"},
        {"plan_name": "One-Time Payment", "plan_amount": "90,000"},
    ]
    out = wc._remap_fee_plans(plans, "course")
    assert out["semester_plan_amount"] == "25,000"
    assert out["semester_plan_amount_total"] == "100,000"
    assert out["annual_plan_amount"] == "50,000"
    assert out["one-time_payment_amount"] == "90,000"


def test_fee_plans_use_different_field_names_on_specialization() -> None:
    plans = [{"plan_name": "Per Semester", "plan_amount": "25,000"}]
    assert wc._remap_fee_plans(plans, "specialization") == {
        "semester_plan_value": "25,000"
    }


def test_unrecognised_fee_tier_is_left_out_rather_than_guessed() -> None:
    plans = [{"plan_name": "Scholarship Adjusted", "plan_amount": "10,000"}]
    assert wc._remap_fee_plans(plans, "course") == {}


def test_fee_plans_on_a_page_type_without_tier_fields() -> None:
    assert wc._remap_fee_plans([{"plan_name": "Per Semester"}], "university") == {}


def test_first_matching_plan_wins_per_tier() -> None:
    plans = [
        {"plan_name": "Semester Plan", "plan_amount": "25,000"},
        {"plan_name": "Semester Plan Revised", "plan_amount": "30,000"},
    ]
    assert wc._remap_fee_plans(plans, "course")["semester_plan_amount"] == "25,000"


# ───────────────────────────── name normalisation ───────────────────────────


def test_normalise_title_ignores_case_punctuation_and_filler() -> None:
    assert wc._normalize_title("UPES Online") == wc._normalize_title("upes")
    assert wc._normalize_title("Sharda University!") == "sharda"


def test_slugify() -> None:
    assert wc._slugify("  Online MBA  ") == "online-mba"
    assert wc._slugify("A+ Grade") == "a-grade"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("UPES Online MBA in Marketing", "mba"),
        ("Online MCA Program", "mca"),
        ("Executive MBA", "executive mba"),
        ("B.Tech in CS", "b.tech"),
        ("A general course page", None),
    ],
)
def test_degree_keyword_extraction(text: str, expected: str | None) -> None:
    assert wc._extract_degree_keyword(text) == expected


# ───────────────────── post lookup + the stale cache bug ────────────────────


def _install_posts(monkeypatch: pytest.MonkeyPatch, posts: list[dict]) -> dict:
    """Serve `posts` from a fake WordPress, counting fetches."""
    state = {"fetches": 0, "posts": posts}

    class _Client:
        def __init__(self, *a, **k) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kwargs):
            state["fetches"] += 1
            return FakeResponse(
                [{"id": p["id"], "title": {"rendered": p["title"]}} for p in state["posts"]],
                headers={"X-WP-TotalPages": "1"},
            )

    monkeypatch.setattr(wc.httpx, "Client", _Client)
    return state


def test_posts_are_cached_within_the_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _install_posts(monkeypatch, [{"id": 1, "title": "Sharda University"}])
    wc._get_all_posts_lite("university")
    wc._get_all_posts_lite("university")
    assert state["fetches"] == 1


def test_cache_expires_so_external_changes_are_picked_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the cache had no expiry, so a long-running server kept
    serving the first snapshot forever. After the site's data was cleared
    and republished, relationship matching kept comparing against posts
    that no longer existed and resolved nothing."""
    state = _install_posts(monkeypatch, [{"id": 1, "title": "Sharda University"}])
    wc._get_all_posts_lite("university")

    clock = {"now": 0.0}
    monkeypatch.setattr(wc.time, "monotonic", lambda: clock["now"])
    # Re-seed the timestamp under the patched clock, then step past the TTL.
    wc._post_title_cache_ts["university"] = 0.0
    clock["now"] = wc._POST_CACHE_TTL_SECONDS + 1

    state["posts"] = [{"id": 2, "title": "UPES Online"}]
    refreshed = wc._get_all_posts_lite("university")
    assert state["fetches"] == 2
    assert refreshed == [{"id": 2, "title": "UPES Online"}]


def test_invalidate_forces_the_next_lookup_to_refetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A university published in one request must be visible to a course
    published immediately after, without waiting out the TTL."""
    state = _install_posts(monkeypatch, [])
    assert wc._get_all_posts_lite("university") == []

    state["posts"] = [{"id": 4871, "title": "Sharda University Online"}]
    wc._invalidate_post_cache("university")
    assert wc._get_all_posts_lite("university") == [
        {"id": 4871, "title": "Sharda University Online"}
    ]
    assert state["fetches"] == 2


def test_lookup_failure_degrades_to_empty_rather_than_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hiccup here must not take down an otherwise valid publish."""

    class _Boom:
        def __init__(self, *a, **k) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            raise RuntimeError("connection reset")

    monkeypatch.setattr(wc.httpx, "Client", _Boom)
    assert wc._get_all_posts_lite("university") == []


def test_match_returns_every_duplicate_post_not_just_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live site genuinely has several posts for one institution, so
    picking one arbitrarily would drop valid links."""
    _install_posts(
        monkeypatch,
        [
            {"id": 10, "title": "KL University"},
            {"id": 11, "title": "KL University"},
            {"id": 12, "title": "Sharda University"},
        ],
    )
    assert sorted(wc._match_posts_by_name("university", "KL University")) == [10, 11]


def test_match_is_tolerant_of_partial_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_posts(monkeypatch, [{"id": 4871, "title": "Sharda University Online"}])
    assert wc._match_posts_by_name("university", "Sharda University") == [4871]


def test_match_returns_nothing_rather_than_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attaching a wrong post ID is worse than leaving the link unset."""
    _install_posts(monkeypatch, [{"id": 1, "title": "Amity University"}])
    assert wc._match_posts_by_name("university", "Sharda University") == []


def test_match_on_an_empty_name_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_posts(monkeypatch, [{"id": 1, "title": "Amity University"}])
    assert wc._match_posts_by_name("university", "   ") == []


# ─────────────────────── relationship resolution ────────────────────────────


def test_relationships_are_not_derived_for_university_pages() -> None:
    assert wc._derive_relationships({}, {}, "university") == ({}, [])


def test_document_stated_link_name_wins_over_the_derived_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the doc says "Linked_university - UPES Online", but
    resolution used university_name, which on this document is a weak
    filename fallback ("Upes") — so the explicit instruction was ignored."""
    _install_posts(
        monkeypatch,
        [
            {"id": 500, "title": "UPES Online"},
            {"id": 501, "title": "Amity University"},
        ],
    )
    payload = {
        "_meta": {
            "document_title": "Copy of UPES Online MBA in Marketing.docx",
            "relationship_hints": {"linked_university": "UPES Online"},
        }
    }
    resolved, warnings = wc._derive_relationships(
        payload, {"university_name": "Amity University"}, "specialization"
    )
    assert resolved["linked_university"] == [500]
    assert not any("university" in w for w in warnings)


def test_falls_back_to_the_derived_name_when_the_doc_states_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Most documents have no Linked_* line, so the older path must keep
    working."""
    _install_posts(monkeypatch, [{"id": 4871, "title": "Sharda University Online"}])
    resolved, _ = wc._derive_relationships(
        {"_meta": {}}, {"university_name": "Sharda University Online"}, "course"
    )
    assert resolved["linked_university"] == [4871]


def test_stated_course_name_resolves_linked_course(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_posts(monkeypatch, [{"id": 4872, "title": "UPES Online MBA"}])
    payload = {
        "_meta": {"relationship_hints": {"linked_course": "UPES Online MBA"}}
    }
    resolved, _ = wc._derive_relationships(payload, {}, "specialization")
    assert resolved["linked_course"] == [4872]


def test_course_resolves_its_category_page_by_degree_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_posts(monkeypatch, [{"id": 4087, "title": "Online MBA"}])
    resolved, _ = wc._derive_relationships(
        {"_meta": {"document_title": "Sharda Online MBA.docx"}},
        {"university_name": "Sharda", "program_name": "Sharda Online MBA"},
        "course",
    )
    assert resolved["category_page"] == [4087]


def test_unresolved_links_produce_actionable_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the target page genuinely does not exist yet, the publish must
    still succeed and tell the editor exactly what to link by hand."""
    _install_posts(monkeypatch, [])
    payload = {
        "_meta": {
            "relationship_hints": {
                "linked_university": "UPES Online",
                "linked_course": "UPES Online MBA",
            }
        }
    }
    resolved, warnings = wc._derive_relationships(payload, {}, "specialization")
    assert resolved == {}
    assert any("UPES Online" in w and "linked_university" in w for w in warnings)
    assert any("UPES Online MBA" in w and "linked_course" in w for w in warnings)


def test_missing_university_name_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_posts(monkeypatch, [])
    _, warnings = wc._derive_relationships({"_meta": {}}, {}, "course")
    assert any("linked_university" in w for w in warnings)


# ───────────────── publish-map integrity against the schema ─────────────────


def test_publish_rename_sources_exist_in_the_schema() -> None:
    """A rename keyed on a field that no longer exists is dead config: the
    value silently never reaches WordPress under either name."""
    from acf.fields import get_valid_field_keys

    for page_type, renames in wc._PUBLISH_FIELD_RENAMES.items():
        valid = get_valid_field_keys(page_type)
        for our_key in renames:
            assert our_key in valid, (
                f"{page_type}: rename source {our_key!r} is not in ACF_FIELDS"
            )


def test_html_list_transform_sources_exist_in_the_schema() -> None:
    from acf.fields import get_valid_field_keys

    for mapping in (wc._PUBLISH_HTML_LIST_TRANSFORMS, wc._PUBLISH_HTML_LIST_COPY):
        for page_type, transforms in mapping.items():
            valid = get_valid_field_keys(page_type)
            for our_key in transforms:
                assert our_key in valid, (
                    f"{page_type}: transform source {our_key!r} is not in ACF_FIELDS"
                )


def test_numeric_derive_sources_exist_in_the_schema() -> None:
    from acf.fields import get_valid_field_keys

    for page_type, derives in wc._PUBLISH_NUMERIC_DERIVE.items():
        valid = get_valid_field_keys(page_type)
        for source_key in derives.values():
            assert source_key in valid, (
                f"{page_type}: numeric-derive source {source_key!r} is not in ACF_FIELDS"
            )


def test_volatile_numeric_fields_are_reachable_at_publish_time() -> None:
    """A volatile key must be something we can actually send: either one
    of our own schema fields, or a WordPress-only field synthesised by
    _PUBLISH_NUMERIC_DERIVE (program_duration is the latter — it has no
    internal field and is derived from `duration`). A key that is neither
    can never be coerced, so its live type check is dead code."""
    from acf.fields import get_valid_field_keys

    for page_type, keys in wc._VOLATILE_NUMERIC_FIELDS.items():
        reachable = get_valid_field_keys(page_type) | set(
            wc._PUBLISH_NUMERIC_DERIVE.get(page_type, {})
        )
        assert keys <= reachable, (
            f"{page_type}: volatile keys {sorted(keys - reachable)} are neither "
            "schema fields nor publish-time derived fields"
        )


def test_publish_refuses_to_run_without_credentials() -> None:
    """Guards against a misconfigured deploy silently doing nothing."""
    with pytest.raises(RuntimeError, match="not configured"):
        wc.publish_payload({}, "university")


def test_publish_rejects_an_unknown_status(wp_configured: None) -> None:
    with pytest.raises(ValueError, match="Invalid status"):
        wc.publish_payload({}, "university", status="live")
