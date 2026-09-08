"""Schema-integrity invariants for acf/fields.py.

ACF_FIELDS is the single source of truth for what each page type may
send to WordPress. Everything downstream (extraction, validation, the
Fix-Mappings UI, publish-time reconciliation) keys off it, so a typo or
a duplicated key here surfaces as a confusing 400 from WordPress rather
than a local error. These tests pin the structural rules.
"""

from __future__ import annotations

import pytest

from acf.fields import (
    ACF_FIELDS,
    FILE,
    IMAGE,
    JSON_ARRAY,
    NON_EXTRACTABLE_TYPES,
    RELATION,
    SKIP_EXTRACTION_FIELDS,
    get_all_valid_field_keys,
    get_field_type,
    get_file_field_keys,
    get_first_sub_field_key,
    get_image_field_keys,
    get_valid_field_keys,
)

KNOWN_TYPES = {"text", "html", "textarea", "json", "stat", "image", "relation", "file"}
PAGE_TYPES = ("university", "course", "specialization", "blog", "category")


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_page_type_exists(page_type: str) -> None:
    assert page_type in ACF_FIELDS
    assert ACF_FIELDS[page_type], f"{page_type} has no fields"


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_field_keys_are_unique_within_page_type(page_type: str) -> None:
    """A duplicated key silently shadows the earlier definition — and
    since get_field_type() returns the FIRST match, the shadowed entry's
    type is what wins, which is rarely what the duplicate intended."""
    keys = [f["key"] for f in ACF_FIELDS[page_type]]
    duplicates = {k for k in keys if keys.count(k) > 1}
    assert not duplicates, f"{page_type} has duplicate field keys: {sorted(duplicates)}"


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_every_field_has_required_shape(page_type: str) -> None:
    for field in ACF_FIELDS[page_type]:
        assert "key" in field, f"{page_type}: field missing 'key': {field}"
        assert "type" in field, f"{page_type}: {field.get('key')} missing 'type'"
        assert field["type"] in KNOWN_TYPES, (
            f"{page_type}: {field['key']} has unknown type {field['type']!r}"
        )
        assert field["key"] == field["key"].strip().lower(), (
            f"{page_type}: {field['key']!r} should be lowercase and unpadded"
        )


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_json_array_fields_declare_sub_fields(page_type: str) -> None:
    """A repeater with no sub_fields can't be coerced from a stray string
    (publish_payload falls back to a 'value' sub-key that WordPress will
    reject), and the Fix-Mappings UI has nothing to render."""
    for field in ACF_FIELDS[page_type]:
        if field["type"] != JSON_ARRAY:
            continue
        assert field.get("sub_fields"), (
            f"{page_type}: repeater {field['key']} declares no sub_fields"
        )


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_extractable_fields_have_embed_text(page_type: str) -> None:
    """Embeddings are how untagged headings find their field. A field
    that is extractable but has an empty 'embed' can never be matched by
    the embedding router."""
    for field in ACF_FIELDS[page_type]:
        if field["type"] in NON_EXTRACTABLE_TYPES:
            continue
        assert field.get("embed", "").strip(), (
            f"{page_type}: {field['key']} is extractable but has no embed text"
        )


def test_skip_extraction_fields_are_exactly_the_relation_fields() -> None:
    """linked_university / linked_course / category_page are WordPress
    post-ID references resolved at publish time, never extracted as-is."""
    relation_keys = {
        f["key"]
        for fields in ACF_FIELDS.values()
        for f in fields
        if f["type"] == RELATION
    }
    assert SKIP_EXTRACTION_FIELDS == relation_keys
    assert relation_keys, "expected at least one RELATION field"


def test_non_extractable_types_cover_images_files_and_relations() -> None:
    assert NON_EXTRACTABLE_TYPES == {IMAGE, RELATION, FILE}


def test_get_valid_field_keys_matches_declared_keys() -> None:
    for page_type in PAGE_TYPES:
        assert get_valid_field_keys(page_type) == {
            f["key"] for f in ACF_FIELDS[page_type]
        }


def test_get_valid_field_keys_unknown_page_type_is_empty() -> None:
    assert get_valid_field_keys("not-a-page-type") == set()


def test_get_all_valid_field_keys_is_the_union() -> None:
    expected = {f["key"] for fields in ACF_FIELDS.values() for f in fields}
    assert get_all_valid_field_keys() == expected


def test_get_field_type_is_page_type_scoped() -> None:
    """The same key can be a different type per page type, so a lookup
    that ignores page_type would mis-coerce values at publish time."""
    assert get_field_type("faqs", "university") == JSON_ARRAY
    assert get_field_type("linked_university", "specialization") == RELATION


def test_get_field_type_defaults_to_text_for_unknown_keys() -> None:
    """Deliberate: an unregistered key degrades to plain text rather than
    raising, so one stray key can't crash a whole extraction run. Publish
    safety comes from get_valid_field_keys filtering instead."""
    assert get_field_type("does_not_exist", "university") == "text"
    assert get_field_type("anything", "not-a-page-type") == "text"


def test_get_first_sub_field_key_returns_leading_sub_field() -> None:
    """publish_payload uses this to rescue a repeater that arrived as a
    plain string, so it must return the first declared sub-field."""
    assert get_first_sub_field_key("faqs", "university") == "question"
    assert get_first_sub_field_key("seo_title", "university") is None
    assert get_first_sub_field_key("does_not_exist", "university") is None


def test_image_and_file_helpers_are_typed_subsets() -> None:
    for page_type in PAGE_TYPES:
        images = get_image_field_keys(page_type)
        files = get_file_field_keys(page_type)
        assert not (images & files), f"{page_type}: a key is both IMAGE and FILE"
        for key in images:
            assert get_field_type(key, page_type) == IMAGE
        for key in files:
            assert get_field_type(key, page_type) == FILE


def test_hero_image_is_never_a_plain_acf_field() -> None:
    """hero_image is published as the native WordPress featured image and
    is popped out of the acf payload — if it were ever declared as a
    non-IMAGE type, publish_payload would forward it into 'acf' and 400."""
    for page_type in PAGE_TYPES:
        if "hero_image" in get_valid_field_keys(page_type):
            assert get_field_type("hero_image", page_type) == IMAGE


@pytest.mark.parametrize("page_type", ("university", "course", "specialization"))
def test_seo_fields_present_on_every_full_page_type(page_type: str) -> None:
    keys = get_valid_field_keys(page_type)
    assert {"seo_title", "meta_description"} <= keys
