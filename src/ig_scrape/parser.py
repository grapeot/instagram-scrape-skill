"""Dialect-aware parser for captured Instagram GraphQL payloads.

Two payload dialects coexist in captured wire traffic:

- Pagination dialect (``/api/graphql``): media nodes under
  ``data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[].node``
  carry ``image_versions2.candidates[]``, ``video_versions[]`` and
  ``carousel_media[]``.
- Page-load dialect (``/graphql/query``): older flat nodes with
  ``display_url`` / ``video_url`` fields.

Detection happens per payload; never filter by content type, because
pagination responses are declared ``text/javascript`` on the wire.
"""

from __future__ import annotations

import json
from typing import Any, Iterable

DIALECT_PAGINATION = "pagination"
DIALECT_LEGACY = "legacy"

RECORD_FIELDS = (
    "username",
    "code",
    "permalink",
    "type",
    "taken_at",
    "caption",
    "image_url",
    "video_url",
    "carousel_media_count",
    "first_seen",
    "source_page",
)

TYPE_NAMES = {1: "photo", 2: "video", 8: "carousel"}

PAGINATION_PATH = (
    "data",
    "xdt_api__v1__feed__user_timeline_graphql_connection",
)


def _media_candidates(node: dict[str, Any]) -> str | None:
    versions = node.get("image_versions2") or {}
    best: dict[str, Any] | None = None
    best_w = -1
    for cand in versions.get("candidates") or []:
        if not isinstance(cand, dict) or not cand.get("url"):
            continue
        width = cand.get("width") or 0
        if width > best_w:
            best, best_w = cand, width
    return (best or {}).get("url")


def _video_candidates(node: dict[str, Any]) -> str | None:
    best: dict[str, Any] | None = None
    best_key = (-1, -1)
    for cand in node.get("video_versions") or []:
        if not isinstance(cand, dict) or not cand.get("url"):
            continue
        key = (cand.get("height") or 0, cand.get("width") or 0)
        if key > best_key:
            best, best_key = cand, key
    return (best or {}).get("url")


LEGACY_TYPE_NAMES = {"GraphVideo": "video", "GraphImage": "photo", "GraphSidecar": "carousel"}


def _caption_text(node: dict[str, Any]) -> str | None:
    caption = node.get("caption")
    if isinstance(caption, dict):
        text = caption.get("text")
        return text if text else None
    if isinstance(caption, str) and caption:
        return caption
    legacy = node.get("edge_media_to_caption") or {}
    for edge in (legacy.get("edges") or []):
        text = (edge or {}).get("node", {}).get("text")
        if text:
            return text
    return None


def _base_record(
    node: dict[str, Any],
    username: str,
    first_seen: str,
    source_page: str,
) -> dict[str, Any]:
    code = node.get("code") or node.get("shortcode")
    media_type = node.get("media_type")
    media_kind = TYPE_NAMES.get(media_type, LEGACY_TYPE_NAMES.get(node.get("__typename"), str(media_type)))
    return {
        "username": username,
        "code": code,
        "permalink": "https://www.instagram.com/p/%s/" % code if code else None,
        "type": media_kind,
        "taken_at": node.get("taken_at", node.get("taken_at_timestamp")),
        "caption": _caption_text(node),
        "image_url": node.get("display_url") or _media_candidates(node),
        "video_url": node.get("video_url") or _video_candidates(node),
        "carousel_media_count": node.get("carousel_media_count"),
        "first_seen": first_seen,
        "source_page": source_page,
    }


def _media_nodes_pagination(payload: dict[str, Any]) -> list[dict[str, Any]]:
    node = payload
    for key in PAGINATION_PATH:
        node = (node or {}).get(key) if isinstance(node, dict) else None
    edges = (node or {}).get("edges") or []
    out = []
    for edge in edges:
        media = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(media, dict) and media.get("code"):
            out.append(media)
    return out


def _media_nodes_legacy(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Find flat nodes carrying ``display_url`` anywhere in the payload."""
    found: list[dict[str, Any]] = []

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if item.get("display_url") and (item.get("code") or item.get("shortcode")):
                found.append(item)
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            for value in item:
                walk(value)

    walk(payload)
    return found


def detect_dialect(payload: dict[str, Any]) -> str | None:
    if _media_nodes_pagination(payload):
        return DIALECT_PAGINATION
    if _media_nodes_legacy(payload):
        return DIALECT_LEGACY
    return None


def parse_payload(
    payload: dict[str, Any],
    *,
    username: str = "unknown",
    first_seen: str = "",
    source_page: str = "",
) -> list[dict[str, Any]]:
    """Parse one captured GraphQL payload into media records.

    A carousel post (``media_type == 8``) yields one parent record with
    ``type: "carousel"`` plus one record per slide; slide records share
    the parent code/permalink and inherit ``taken_at``.
    """
    records: list[dict[str, Any]] = []

    def push(node: dict[str, Any]) -> None:
        record = _base_record(node, username, first_seen, source_page)
        records.append(record)

    if detect_dialect(payload) == DIALECT_PAGINATION:
        for media in _media_nodes_pagination(payload):
            push(media)
            for idx, child in enumerate(media.get("carousel_media") or []):
                if not isinstance(child, dict):
                    continue
                child_record = _base_record(
                    {**child, "code": child.get("code") or media.get("code"),
                     "taken_at": child.get("taken_at") or media.get("taken_at")},
                    username, first_seen, source_page,
                )
                child_record["permalink"] = "https://www.instagram.com/p/%s/" % media.get("code") if media.get("code") else None
                records.append(child_record)
    else:
        for media in _media_nodes_legacy(payload):
            push(media)
    return records


def load_payload(path: str) -> tuple[dict[str, Any] | None, str]:
    """Load one archived page file; returns (payload, error_or_empty)."""
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        return None, "cannot parse %s: %s" % (path, exc)
    return payload, ""


def dedupe_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str | None, str | None]] = set()
    unique = []
    for record in records:
        key = (record.get("code"), record.get("image_url"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(record)
    return unique