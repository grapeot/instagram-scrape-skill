# Test Strategy

This document defines the testing and verification rules for `instagram-scrape-skill`.

## 1. Test Strategy: Offline Default vs. Manual Live Smoke

Offline unit tests are the default tier and the only suite executed in GitHub Actions CI:

```bash
pytest -q
```

Offline tests make no network requests, launch no browser processes, and require no credentials. Every test runs against local sanitized JSON fixtures and temporary directories.

Live capture smoke tests require a real Chrome session over CDP (`--remote-debugging-port=9223 --user-data-dir=<temp-dir>`) and a human logging into their own account by hand (including 2FA or checkpoint prompts) at human scroll pace (~2 s per scroll). Because live capture depends on interactive login and live account state, smoke tests are strictly manual, run by a human, and must never run in CI.

## 2. Unit Coverage Map

- **`parse`**:
  - **Dialect detection and record extraction**: Auto-detect and parse both `/api/graphql` pagination payloads (`data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[].node`) and `/graphql/query` page-load payloads (flat `display_url` and `video_url` fields) into normalized records (`code`, `taken_at`, `caption.text`, `media_type`, and permalink `https://www.instagram.com/p/<code>/`).
  - **Max-resolution candidate selection**: Pick the candidate with maximum width from `image_versions2.candidates[]` for images (`media_type == 1`) and maximum height from `video_versions[]` for videos (`media_type == 2`).
  - **Carousel expansion**: Expand `carousel_media[]` on album nodes (`media_type == 8`) into individual child media records sharing the parent `code` and `taken_at`.
  - **Missing-field tolerance**: Handle `caption: null`, missing `video_versions` on photo nodes, and non-timeline GraphQL responses without raising unhandled exceptions.
- **`merge`**:
  - **Dedupe key**: Deduplicate extracted records strictly by the `(code, image_url)` tuple across captured pages.
  - **Append-only index**: Preserve existing entries in `media_index.jsonl` and append only records with unseen `(code, image_url)` keys.
  - **Idempotent re-runs**: Re-running merge over the same `raw_pages/` directory produces an identical `media_index.jsonl` with zero duplicate rows.
- **`cli`**:
  - **Argument validation**: Validate required flags for `ig-scrape archive` (`--username`, `--max-items`), `ig-scrape parse` (`--page`), and `ig-scrape export` (`--index`, `--format json|csv`), and reject invalid arguments with a non-zero exit code.
  - **Out-dir behavior**: Verify that `<out>/<username>/media_index.jsonl`, `raw_pages/`, and optional `media/` directories are created as specified, and that per-session timestamped capture files never overwrite files from prior sessions.

## 3. Fixture Hygiene

All committed fixtures under `tests/fixtures/` must be sanitized before commit:

- Replace real account usernames and IDs with `example_user` and synthetic numeric IDs (ignoring suggested-account usernames embedded inside payloads).
- Replace real CDN hosts (`*.cdninstagram.com`, `*.fbcdn.net`) with fake CDN hosts (`cdn.example.test`).
- Replace signed URL query parameters (`oh`, `oe`, `_nc_ht`) with fake signatures (`oh=fake_sig&oe=00000000`).
- Remove personal captions, cookies, and session tokens.

Run the privacy scan against committed files before pushing; it must return zero matches:

```bash
git grep -nE '(cdninstagram\.com|fbcdn\.net|sessionid=|csrftoken=|_nc_ht=)' -- 'tests/' 'src/' 'skills/'
```

## 4. What "Done" Looks Like for a Change

1. **Full offline suite green**: `pytest -q` passes with zero network access, and the privacy scan command above returns zero matches on committed files.
2. **New fixtures for new payload shapes**: When a new GraphQL payload shape or missing-field variant appears in the wild, add a sanitized fixture under `tests/fixtures/` and a corresponding unit test in the same change.
3. **Live smoke note when capture behavior changes**: When modifying CDP attachment, protocol-level `page.on("response")` capture (including `content-type: text/javascript` handling), scroll pagination, in-browser `fetch(mediaUrl)` download, or cleanup, record a manual live smoke note in the PR/commit message stating pages captured, items indexed, and verified cleanup of the listener, Chrome process, and temporary `user-data-dir`.
