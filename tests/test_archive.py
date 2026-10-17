"""Offline unit tests for index building, dedupe and export."""

import json
import os
import subprocess
import sys

import pytest

from ig_scrape.archive import build_index, export_csv, export_json, read_index, write_index
from ig_scrape.parser import RECORD_FIELDS, dedupe_records
from ig_scrape import parser as parser_mod

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")


def _records_from_fixture(name, username="example_user"):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        payload = json.load(fh)
    return parser_mod.parse_payload(payload, username=username, source_page=name)


def test_dedupe_key_is_code_and_image_url():
    base = _records_from_fixture("pagination_small.json")[0]
    duplicate = dict(base)
    records = [base, duplicate]
    assert len(dedupe_records(records)) == 1
    altered = dict(base, image_url=base["image_url"] + "&variant=x")
    assert len(dedupe_records([base, altered])) == 2


def test_build_index_from_nested_raw_pages(tmp_path):
    raw_dir = tmp_path / "raw_pages"
    session = raw_dir / "session_1"
    session.mkdir(parents=True)
    fixture_text = (os.path.join(FIXTURES, "pagination_small.json"),)
    # split real fixture across two session directories to test nested walk
    with open(os.path.join(FIXTURES, "pagination_small.json"), encoding="utf-8") as fh:
        payload = json.load(fh)
    edges = payload["data"]["xdt_api__v1__feed__user_timeline_graphql_connection"]["edges"]
    first, second = edges[:1], edges[1:]
    json.dump({"data": {"xdt_api__v1__feed__user_timeline_graphql_connection": {"edges": first}}},
              open(session / "page_0001.json", "w", encoding="utf-8"))
    session2 = raw_dir / "session_2"
    session2.mkdir()
    json.dump({"data": {"xdt_api__v1__feed__user_timeline_graphql_connection": {"edges": second}}},
              open(session2 / "page_0001.json", "w", encoding="utf-8"))

    records, errors = build_index(str(raw_dir), username="example_user")
    assert not errors
    assert {r["code"] for r in records} == {"ExVideo01AA", "ExPhoto01BB"}
    for record in records:
        assert record["source_page"].startswith("session_")


def test_build_index_reports_unrecognized_pages(tmp_path):
    raw_dir = tmp_path / "raw_pages"
    raw_dir.mkdir()
    with open(os.path.join(FIXTURES, "unknown_dialect.json"), encoding="utf-8") as fh:
        text = fh.read()
    (raw_dir / "page_bad.json").write_text(text, encoding="utf-8")
    records, errors = build_index(str(raw_dir))
    assert records == []
    assert errors and "no media records" in errors[0]


def test_write_index_idempotent(tmp_path):
    records = dedupe_records(_records_from_fixture("pagination_small.json"))
    path = tmp_path / "media_index.jsonl"
    assert write_index(records, str(path)) == len(records)
    first_read = read_index(str(path))
    write_index(records, str(path))
    assert read_index(str(path)) == first_read


def test_export_json_roundtrip(tmp_path):
    records = dedupe_records(_records_from_fixture("pagination_small.json"))
    path = tmp_path / "media_index.jsonl"
    write_index(records, str(path))
    exported = json.loads(export_json(read_index(str(path))))
    assert exported == records


def test_export_csv_headers(tmp_path):
    records = derecords = dedupe_records(_records_from_fixture("pagination_small.json"))
    csv_text = export_csv(records)
    header = csv_text.splitlines()[0]
    assert [field.strip('"') for field in header.split(",")] == list(RECORD_FIELDS)
    lines = csv_text.splitlines()
    assert len(lines) == len(records) + 1


def _run_cli(args, cwd=None, env=None):
    repo_root = os.path.dirname(HERE)
    script = os.path.join(repo_root, "scripts", "ig-scrape")
    return subprocess.run(
        [sys.executable, script, *args], capture_output=True, text=True, cwd=cwd, env=env,
    )


def test_cli_parse_command(tmp_path):
    result = _run_cli([
        "parse", "--page", os.path.join(FIXTURES, "pagination_small.json"),
        "--out", str(tmp_path), "--username", "example_user",
    ])
    assert result.returncode == 0, result.stderr
    out_file = tmp_path / "pagination_small.records.jsonl"
    assert out_file.exists()
    records = [json.loads(line) for line in out_file.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert {r["username"] for r in records} == {"example_user"}


def test_cli_export_command(tmp_path):
    records = dedupe_records(_records_from_fixture("pagination_small.json"))
    index_path = tmp_path / "media_index.jsonl"
    write_index(records, str(index_path))
    result = _run_cli(["export", "--index", str(index_path), "--format", "csv"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0].startswith("username,")

    bad = _run_cli(["export", "--index", str(index_path), "--format", "yaml"])
    assert bad.returncode == 2


def test_cli_parse_unreadable_file(tmp_path):
    result = _run_cli(["parse", "--page", str(tmp_path / "missing.json"), "--out", str(tmp_path)])
    assert result.returncode == 2