# instagram-scrape-skill

`instagram-scrape-skill` archives media from your own Instagram account by attaching an AI coding agent to your real Chrome session over the Chrome DevTools Protocol (CDP), capturing the GraphQL payloads the Instagram web app itself requests while browsing a profile, and parsing them into a structured, durable index with optional in-browser download. No cookies, tokens, `.env` files, or login credentials are ever extracted or stored.

## Why this repo exists

This project started as a homework assignment in the AI Builders course. In the original homework, demonstrated during a live office-hours session, students opened browser DevTools, scrolled their own Instagram profile, saved the network activity as a HAR file, and asked an AI to extract image URLs from the HAR and generate threaded download code into a local folder.

A later live session in the course taught the core practice this repository embodies: "When a task repeats for the second time, distill it into a skill file." The skill file defines the goal, acceptance criteria, and operational pitfalls in plain, provider-neutral Markdown, discovered through a progressive-disclosure index so a fresh agent can re-run the task with minimal prompting.

This repository carries both meanings. It is the agent-native upgrade of that original homework, where the agent owns the full capture, parse, and archive loop instead of relying on a hand-exported HAR file, and it is a worked distillation example packaging working code, the distilled skill file, and honest documentation.

## How it works

```text
+------------------------------------------------------------------------+
| 1. CAPTURE (Real Chrome + Playwright CDP listener)                     |
|    Human logs in -> Agent scrolls grid -> Web app POSTs /api/graphql   |
|    Protocol-level page.on("response") writes raw payloads to disk      |
+------------------------------------------------------------------------+
                                   |
                                   v
+------------------------------------------------------------------------+
| 2. PARSE (Dialect-aware GraphQL extractor)                             |
|    Detects /api/graphql connection edges vs /graphql/query nodes       |
|    Extracts max-width images, max-height videos, and carousel items    |
+------------------------------------------------------------------------+
                                   |
                                   v
+------------------------------------------------------------------------+
| 3. ARCHIVE (Deduplicated JSONL index + optional in-browser download)   |
|    Merges records by (shortcode, image_url) -> media_index.jsonl       |
|    Optional page-context fetch(mediaUrl) -> base64 over CDP -> disk    |
+------------------------------------------------------------------------+
```

**Capture.** The tool launches Chrome with `--remote-debugging-port=9223`, `--user-data-dir=<fresh temp dir>`, `--no-first-run`, and `--no-default-browser-check`, opening `instagram.com` for manual login. A Python listener attaches via Playwright `chromium.connect_over_cdp("http://localhost:<port>")` and registers protocol-level `page.on("response")` and `page.on("request")` handlers that survive page refreshes while filtering out analytics noise and static assets. The browser does the fetching: the agent only drives pagination by running `window.scrollBy` via `page.evaluate` at ~2 second intervals, and every data request is issued by the Instagram web app itself as a `POST` to `https://www.instagram.com/api/graphql`. Each raw API response body (~300 KB JSON) is written to disk regardless of content type because pagination responses declare `content-type: text/javascript`.

**Parse.** The parser reads captured payloads and auto-detects between two coexisting GraphQL dialects: profile-pagination payloads under `data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[].node` and page-load payloads from `/graphql/query` with flat `display_url` and `video_url` fields. From each node, it extracts `code`, `taken_at`, `caption.text`, and `media_type` (`1` = photo, `2` = video, `8` = carousel), expands `carousel_media[]` albums into individual items, selects the maximum width from `image_versions2.candidates[]` for images and the maximum height from `video_versions[]` for videos, and constructs the post permalink `https://www.instagram.com/p/<code>/`.

**Archive.** Parsed page records are merged into one deduplicated media index (`media_index.jsonl`) keyed by `(shortcode, image URL)`, deriving the logged-in account identity from the session profile URL rather than payload strings. When `--download` is passed, the agent runs `fetch(mediaUrl)` inside the logged-in browser context—where signed CDN URLs are CORS-open—reads the blob back as base64 over the CDP channel, and decodes the file to disk before terminating the listener and Chrome and removing the temporary profile directory.

## Quickstart

1. Create a virtual environment with `uv` and install the package in editable mode:

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

2. Run `ig-scrape archive` for your own Instagram account:

```bash
ig-scrape archive --username example_user --max-items 120 --max-pages 10 --download --out ./output
```

A Chrome browser window will open to `instagram.com` with a fresh temporary profile. You must log in manually in that window and complete any checkpoint or 2FA prompts yourself. Once logged in, the tool probes the session, scrolls the profile grid, captures the GraphQL responses into `raw_pages/`, writes the deduplicated `media_index.jsonl`, and downloads media files into `media/`.

3. Re-parse a single archived payload offline or export the index to JSON or CSV:

```bash
# Offline re-parse of one archived GraphQL response payload
ig-scrape parse --page ./output/example_user/raw_pages/page_0001.json --out ./reparse_out

# Export the JSONL index to flat JSON or CSV
ig-scrape export --index ./output/example_user/media_index.jsonl --format json
ig-scrape export --index ./output/example_user/media_index.jsonl --format csv
```

## Output

Running `ig-scrape archive` creates the following directory structure under `--out`:

```text
output/
└── example_user/
    ├── media_index.jsonl
    ├── raw_pages/
    │   ├── 20261017T083012Z_page_0001.json
    │   └── 20261017T083015Z_page_0002.json
    └── media/
        ├── CLPf-i2Pb0k_01.jpg
        └── CLPf-i2Pb0k_02.mp4
```

Each line in `media_index.jsonl` is one JSON object with exactly eleven fields (`username`, `code`, `permalink`, `type`, `taken_at`, `caption`, `image_url`, `video_url`, `carousel_media_count`, `first_seen`, `source_page`); `source_page` points back to the archived raw payload so every row can be re-parsed offline. A carousel post produces one parent record with `type: "carousel"` plus one record per slide. Example (fake data):

```json
{
  "username": "example_user",
  "code": "CLPf-i2Pb0k",
  "permalink": "https://www.instagram.com/p/CLPf-i2Pb0k/",
  "type": "photo",
  "taken_at": 1690000000,
  "caption": "Sample caption from archived profile post.",
  "image_url": "https://cdn-images.example/v/t51.29350-15/CLPf-i2Pb0k_1440x1085.jpg?oh=fake_sig&oe=00000000",
  "video_url": null,
  "carousel_media_count": null,
  "first_seen": "2026-10-17T08:30:12Z",
  "source_page": "raw_pages/20261017T083012Z/page_0001.json"
}
```

## The distilled skill

The reusable agent skill ships at `skills/instagram-scrape/SKILL.md` and embodies the course lesson of distilling a repeating task into a provider-neutral Markdown specification. It gives an AI coding agent the exact goal, CDP connection workflow, acceptance criteria, and seven live-verified operational pitfalls so the agent does not have to rediscover them by trial and error: pagination responses served with `content-type: text/javascript` that JSON MIME filters silently drop, two coexisting GraphQL dialects (`/api/graphql` vs. `/graphql/query`), protocol-level `page.on("response")` capture instead of `window.fetch` monkey-patches that die on page reload, per-session timestamped file numbering so restarted listeners never overwrite earlier captures, deriving user identity from the session profile URL rather than suggested-account usernames embedded in payloads, parameterizing the CDP port with a fresh `user-data-dir` per session to avoid port collisions and stale-profile SSO loops, and mandatory cleanup of the listener, Chrome process, and temporary profile directory on exit.

## Limitations & honest notes

- **Signed CDN URLs expire:** Direct `image_url` and `video_url` links carry short-lived signatures that expire within days. The index therefore treats CDN URLs as ephemeral and records the post permalink (`https://www.instagram.com/p/<code>/`) plus capture timestamp as the durable identifier; pass `--download` at archive time if you want local media files.
- **Login walls are human-only:** Authentication, security checkpoints, and 2FA are strictly manual. If the tool detects a login wall during session probing or scrolling, it refuses and stops immediately.
- **Terms of Service nuance:** Meta's terms disallow unauthorized automated collection. Own-account archiving at a human-like pace is the lowest-risk use; this repo explicitly does not claim broader clearance, ships no bulk-collection affordances, and stores or reuses no signed-URL or fingerprint tricks offline.
- **v0 scope:** This tool targets your own profile grid only (photos, videos, and expanded carousel items). Stories, reels tabs, saved collections, mass-crawl loops, username fan-out, and anonymous scraping modes are excluded by design.

## Repository layout

```text
instagram-scrape-skill/
├── README.md
├── README.zh-CN.md
├── LICENSE
├── pyproject.toml
├── docs/                   # prd / rfc / working / test
├── skills/
│   └── instagram-scrape/
│       └── SKILL.md        # the distilled agent skill
├── scripts/
│   └── ig-scrape           # CLI entrypoint
├── src/
│   └── ig_scrape/
│       ├── __init__.py
│       ├── cli.py
│       ├── capture.py      # CDP session: launch, attach, scroll, capture
│       ├── parser.py       # dialect-aware payload -> media records
│       └── archive.py      # merge, export, in-browser download
└── tests/
    ├── fixtures/           # sanitized GraphQL payload fixtures
    ├── test_parser.py
    └── test_archive.py
```

## License

MIT License. See `LICENSE` for full text.
