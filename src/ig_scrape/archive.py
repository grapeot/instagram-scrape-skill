"""Index building and export for archived media records."""

from __future__ import annotations

import csv
import io
import json
import os
from typing import Any, Iterable

from .parser import RECORD_FIELDS, dedupe_records, load_payload, parse_payload


def collect_page_files(raw_pages_dir: str) -> list[str]:
    """List captured page files inside a (possibly nested) raw_pages directory."""
    out = []
    for root, _dirs, files in os.walk(raw_pages_dir):
        for name in sorted(files):
            if name.endswith(".json"):
                out.append(os.path.join(root, name))
    return sorted(out)


def build_index(raw_pages_dir: str, *, username: str = "unknown") -> tuple[list[dict[str, Any]], list[str]]:
    """Parse every archived page file into a deduplicated index.

    Returns (records, errors): errors carry per-file messages for unreadable
    or unrecognized payloads so the caller can surface them instead of
    silently dropping pages.
    """
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in collect_page_files(raw_pages_dir):
        payload, error = load_payload(path)
        if payload is None:
            errors.append(error)
            continue
        source_page = os.path.relpath(path, raw_pages_dir)
        page_records = parse_payload(
            payload, username=username, source_page=source_page,
        )
        if not page_records:
            errors.append("no media records recognized in %s" % path)
            continue
        records.extend(page_records)
    return dedupe_records(records), errors


def write_index(records: Iterable[dict[str, Any]], path: str) -> int:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    written = 0
    with open(path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
    return written


def read_index(path: str) -> list[dict[str, Any]]:
    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def export_json(records: list[dict[str, Any]]) -> str:
    return json.dumps(records, ensure_ascii=False, indent=2) + "\n"


def export_csv(records: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(RECORD_FIELDS))
    writer.writeheader()
    for record in records:
        writer.writerow({field: record.get(field) for field in RECORD_FIELDS})
    return buf.getvalue()


def export_index(path: str, fmt: str) -> str:
    records = read_index(path)
    if fmt == "json":
        return export_json(records)
    if fmt == "csv":
        return export_csv(records)
    raise ValueError("unsupported export format: %s" % fmt)