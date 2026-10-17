"""ig-scrape: browser-native Instagram media archiving CLI."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

from . import archive as archive_mod
from . import parser as parser_mod


def _cmd_archive(args: argparse.Namespace) -> int:
    from .capture import CaptureSession, cleanup_chrome, launch_chrome, wait_for_cdp

    out_root = os.path.abspath(args.out)
    username_dir = os.path.join(out_root, args.username)
    index_path = os.path.join(username_dir, "media_index.jsonl")

    profile_dir = os.path.join(
        os.path.abspath(args.tmpdir or tempfile.gettempdir()),
        "ig_profile_%d" % int(time.time()),
    )
    chrome_proc = launch_chrome(args.port, profile_dir, chrome_bin=args.chrome)
    try:
        wait_for_cdp(args.port)
        session = CaptureSession(args.port, username_dir)
        deadline = time.time() + args.login_timeout
        print("Waiting for manual login (timeout %ds)..." % args.login_timeout)
        while time.time() < deadline:
            if session.login_wall() or session.active_profile_url() is None:
                time.sleep(5)
                continue
            break
        else:
            print("Login did not complete in time; giving up.", file=sys.stderr)
            return 3
        if session.login_wall():
            print("Still on a login/challenge page. Authenticate manually and retry.", file=sys.stderr)
            return 4

        if args.max_pages is None:
            rounds_budget = 200
        else:
            rounds_budget = max(args.max_pages * 3, args.max_pages + 6)
        page_paths = session.scroll_profile(rounds_budget, max_pages=args.max_pages)
        records, errors = archive_mod.build_index(session_dir_holder(username_dir), username=args.username)
        for error in errors:
            print("[parse] %s" % error, file=sys.stderr)
        if args.max_items is not None:
            records = records[: args.max_items]

        # record metadata enrichment for freshness
        first_seen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for record in records:
            record["first_seen"] = record.get("first_seen") or ""
            record["username"] = args.username

        deduped = parser_mod.dedupe_records(records)
        written = archive_mod.write_index(deduped, index_path)
        print("indexed %d records -> %s" % (written, index_path))

        if args.download:
            from urllib.parse import urlparse

            media_dir = os.path.join(username_dir, "media")
            if session.login_wall():
                print("Cannot download while on a login/challenge page.", file=sys.stderr)
                return 5
            for record in deduped:
                url = record.get("image_url") or record.get("video_url")
                if not url:
                    continue
                name = "%s_%s" % (record["code"], os.path.basename(urlparse(url).path)[:1] or "media")
                try:
                    session.download_media(url, media_dir, name)
                except Exception as exc:  # noqa: BLE001 - report and continue
                    print("[download] %s: %s" % (record.get("code"), exc), file=sys.stderr)
        session.close()
        return 0
    finally:
        cleanup_chrome(profile_dir, args.port, chrome_proc)


def session_dir_holder(username_dir: str) -> str:
    return os.path.join(username_dir, "raw_pages")


def _cmd_parse(args: argparse.Namespace) -> int:
    username_dir = os.path.abspath(args.out)
    os.makedirs(username_dir, exist_ok=True)
    payload, error = parser_mod.load_payload(args.page)
    if payload is None:
        print(error, file=sys.stderr)
        return 2
    first_seen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    records = parser_mod.parse_payload(
        payload, username=args.username, first_seen=first_seen,
        source_page=os.path.basename(args.page),
    )
    out_path = os.path.join(
        username_dir, os.path.splitext(os.path.basename(args.page))[0] + ".records.jsonl",
    )
    written = archive_mod.write_index(records, out_path)
    print("parsed %d records -> %s" % (written, out_path))
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    try:
        content = archive_mod.export_index(args.index, args.format)
    except (OSError, ValueError, ValueError) as exc:
        # ValueError covers unsupported format and malformed JSON lines
        print("export error: %s" % exc, file=sys.stderr)
        return 2
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(content)
        print("exported -> %s" % args.out)
    else:
        sys.stdout.write(content)
    return 0


def build_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="ig-scrape", description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)

    arch = sub.add_parser("archive", help="archive a profile by driving a real Chrome session")
    arch.add_argument("--username", required=True, help="profile handle to archive (your own account)")
    arch.add_argument("--max-items", type=int, default=None, help="stop after N media records")
    arch.add_argument("--max-pages", type=int, default=None, help="cap captured payload pages")
    arch.add_argument("--download", action="store_true", help="download media files in the browser context")
    arch.add_argument("--out", default="data", help="output root directory (default: data)")
    arch.add_argument("--port", type=int, default=9223, help="CDP port for the launched Chrome")
    arch.add_argument("--chrome", default=None, help="Chrome binary path override")
    arch.add_argument("--tmpdir", default=None, help="parent dir for the temporary Chrome profile")
    arch.add_argument("--login-timeout", type=int, default=600, help="seconds to wait for manual login")
    arch.set_defaults(func=_cmd_archive)

    parse_cmd = sub.add_parser("parse", help="re-parse one archived GraphQL payload offline")
    parse_cmd.add_argument("--page", required=True, help="archived payload JSON file")
    parse_cmd.add_argument("--out", default="data", help="output directory for the parsed records")
    parse_cmd.add_argument("--username", default="unknown", help="record username attribution")
    parse_cmd.set_defaults(func=_cmd_parse)

    exp = sub.add_parser("export", help="export media_index.jsonl to JSON or CSV")
    exp.add_argument("--index", required=True, help="media_index.jsonl path")
    exp.add_argument("--format", choices=("json", "csv"), required=True)
    exp.add_argument("--out", default=None, help="optional output file (default: stdout)")
    exp.set_defaults(func=_cmd_export)
    return root


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())