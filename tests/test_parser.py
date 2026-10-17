"""Offline unit tests for the dialect-aware parser."""

import os

from ig_scrape.parser import (
    DIALECT_LEGACY,
    DIALECT_PAGINATION,
    detect_dialect,
    parse_payload,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def load_fixture(name):
    import json

    with open(os.path.join(HERE, "fixtures", name), encoding="utf-8") as fh:
        return json.load(fh)


def test_detects_pagination_dialect():
    payload = load_fixture("api_pagination_page.json")
    assert detect_dialect(payload) == DIALECT_PAGINATION


def test_detects_legacy_dialect():
    payload = load_fixture("legacy_display.json")
    assert detect_dialect(payload) == DIALECT_LEGACY


def test_unknown_dialect_returns_none():
    payload = load_fixture("unknown_dialect.json")
    assert detect_dialect(payload) is None
    assert parse_payload(payload) == []


def test_real_page_parses_all_records_with_unique_codes():
    payload = load_fixture("api_pagination_page.json")
    records = parse_payload(payload, username="example_user", source_page="page_test.json")
    assert records, "sanitized real page must produce records"
    pairs = {(r["code"], r["image_url"]) for r in records}
    assert len(pairs) == len(records)
    for record in records:
        assert record["username"] == "example_user"
        # Slide records point at the parent post's permalink; every record
        # permalink must still be a well-formed post URL.
        assert record["permalink"] and record["permalink"].startswith("https://www.instagram.com/p/")
        assert record["source_page"] == "page_test.json"


def test_video_node_selects_max_height():
    payload = load_fixture("pagination_small.json")
    records = parse_payload(payload)
    by_code = {r["code"]: r for r in records}
    video = by_code["ExVideo01AA"]
    assert video["type"] == "video"
    assert "video_dash_high" in video["video_url"], "must pick the tallest video rendition"
    assert "video_poster_b" in video["image_url"], "must pick the widest image candidate"


def test_missing_caption_and_video_versions_tolerated():
    payload = load_fixture("pagination_small.json")
    records = parse_payload(payload)
    by_code = {r["code"]: r for r in records}
    photo = by_code["ExPhoto01BB"]
    assert photo["type"] == "photo"
    assert photo["caption"] is None
    assert photo["video_url"] is None


def test_carousel_yields_parent_and_slide_records():
    payload = load_fixture("api_pagination_page.json")
    records = parse_payload(payload)
    parents = [r for r in records if r["type"] == "carousel"]
    assert parents, "sanitized page fixture contains carousel posts"
    for parent in parents:
        slides = [r for r in records
                  if r["type"] in ("photo", "video")
                  and r["permalink"] == parent["permalink"]]
        assert len(slides) == parent["carousel_media_count"]


def test_legacy_records_keep_flat_fields():
    payload = load_fixture("legacy_display.json")
    records = parse_payload(payload)
    by_code = {r["code"]: r for r in records}
    assert set(by_code) == {"LegPicture01", "LegMovie01"}
    assert by_code["LegMovie01"]["type"] == "video"
    assert by_code["LegMovie01"]["video_url"].endswith(".mp4?oh=fake_sig&oe=00000000")
    assert by_code["LegPicture01"]["type"] == "photo"
    assert by_code["LegPicture01"]["caption"] == "Legacy dialect example caption."