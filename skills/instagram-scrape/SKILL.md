---
name: instagram-scrape
description: Load this skill when the user asks to archive, export, list, or download media from their own Instagram profile, or mentions Chrome DevTools Protocol (CDP), Playwright, or Instagram scraping for personal account backup.
---

## Goal

Produce a durable, structured media archive (`media_index.jsonl`, raw GraphQL pages, and optional media downloads) for the logged-in user's own Instagram profile by letting the real browser fetch and capturing its wire traffic, with no forged requests.

## When To Use / When Not To Use

- **Use when**: Archiving the user's own Instagram account, listing media URLs and post metadata, or running a periodic re-sync of their profile.
- **Do not use when**: Accessing other people's accounts, performing bulk or anonymous collection, fanning out across usernames, or automating login, 2FA, or challenge flows.

## Prerequisites

- **Chrome binary**: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` on macOS, or `google-chrome` / `chromium` on Linux.
- **Python package**: Python 3 with `playwright` installed (`playwright.sync_api` or `playwright.async_api`).
- **CDP port**: Parameterized debugging port, defaulting to `9223` to avoid collisions with default `9222` sessions.
- **Temporary profile**: A fresh temporary `--user-data-dir` created per session and deleted on exit.

## Hard Boundaries

- **Human-only authentication**: Login, security checkpoints, and 2FA are strictly manual. Detect any login wall, stop immediately, and ask the user to authenticate in the browser.
- **Own account only**: Never run mass-crawl loops, username fan-out, or anonymous scraping modes.
- **Human-paced scrolling**: Pause ~2 seconds between scroll actions. If the platform rate-limits or serves a challenge, stop the session immediately and do not retry through obstacles.
- **Zero credential persistence**: Never write passwords, cookies, tokens, or `.env` files to disk or repository files.
- **Ephemeral CDN URLs**: Signed CDN media URLs expire within days. Record the post `permalink` and `first_seen` timestamp as durable references, and download files during the archive run if local copies are needed.

## Method

### Default Path: CLI Shortcuts

When the `instagram-scrape-skill` package (`ig-scrape`) is installed, use the CLI first:

- `ig-scrape archive --username NAME --max-items N [--max-pages N] [--download] [--out DIR]` — runs the full loop: session probe, scroll pagination, wire capture, parse, and index merge into `<out>/<username>/media_index.jsonl`, `raw_pages/`, and optional `media/`.
- `ig-scrape parse --page FILE [--out DIR]` — offline re-parse of a single archived GraphQL payload.
- `ig-scrape export --index FILE --format json|csv` — projects `media_index.jsonl` to flat JSON or CSV.

### Fallback Path: Manual Browser-Attach Loop

Treat this sequence as enabling guidance rather than a rigid checklist; adapt scroll pacing and stop conditions to the live session context and requested item count:

1. **Launch Chrome**: Start Chrome with `--remote-debugging-port=<port> --user-data-dir=<fresh-temp-dir> --no-first-run --no-default-browser-check` and open `https://www.instagram.com`. Wait for the user to log in manually and open their profile page.
2. **Attach listener**: Connect via Playwright `chromium.connect_over_cdp("http://localhost:<port>")` and register protocol-level `page.on("response")` and `page.on("request")` handlers, which survive page refreshes. Filter out static assets and analytics noise.
3. **Scroll and capture**: Drive pagination by evaluating `window.scrollBy(0, window.innerHeight)` via `page.evaluate`, pacing ~2 seconds between scrolls. Each threshold triggers a POST to `https://www.instagram.com/api/graphql`. Save every API response body (~300 KB JSON each) to disk.
4. **Parse pagination payloads**: Read `data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[].node`. Extract `code`, `taken_at`, `caption.text`, and `media_type` (`1` = photo, `2` = video, `8` = carousel). Pick the maximum-width entry from `image_versions2.candidates[]`, maximum-height entry from `video_versions[]`, and expand `carousel_media[]` for albums. Format permalinks as `https://www.instagram.com/p/<code>/`.
5. **Auto-detect page-load dialect**: Detect initial `/graphql/query` responses, which use an older web dialect with flat `display_url` and `video_url` fields.
6. **Merge index**: Deduplicate and merge extracted records into `media_index.jsonl` keyed by `(code, image_url)`.
7. **Optional download**: Inside the logged-in page context, call `fetch(mediaUrl)` (signed CDN URLs are CORS-open), transfer the blob as base64 over CDP, and decode it to disk.

## Acceptance Criteria

- The logged-in profile URL and username are derived from the live browser session, never from strings inside GraphQL payloads.
- `raw_pages/` contains one JSON file per captured GraphQL response inside a timestamped session directory.
- `media_index.jsonl` is deduplicated by `(code, image_url)` with all eleven schema fields present.
- Zero requests are issued by the agent outside the attached browser context.
- Credentials and cookies are never written to repository or archive files.
- Temporary profile directories, listener processes, and Chrome instances are cleaned up after execution.

## Output Specification

### Archive Directory Layout

```text
<out>/<username>/
├── media_index.jsonl
├── raw_pages/
│   └── <session_timestamp>/
│       ├── page_0001.json
│       └── page_0002.json
└── media/                  # optional, created when --download is set
    └── C9xYz12AbCd_01.jpg
```

### Record Schema (`media_index.jsonl`)

Each record contains these exact fields: `username`, `code`, `permalink`, `type`, `taken_at`, `caption`, `image_url`, `video_url`, `carousel_media_count`, `first_seen`, `source_page`.

```json
{
  "username": "example_user",
  "code": "C9xYz12AbCd",
  "permalink": "https://www.instagram.com/p/C9xYz12AbCd/",
  "type": "carousel",
  "taken_at": 1729152000,
  "caption": "Autumn hike in the Cascades.",
  "image_url": "https://scontent.cdn-images.example/v/t51.29350-15/462000000_1440x1085.jpg?_nc_cat=101&ccb=1-7&oh=fake_sig&oe=00000000",
  "video_url": null,
  "carousel_media_count": 3,
  "first_seen": "2026-10-17T15:30:00Z",
  "source_page": "raw_pages/20261017T152950Z/page_0001.json"
}
```

## Known Pitfalls

1. **Silent pagination loss from content-type filtering**: *Symptom*: Zero pagination responses are saved while scrolling. *Cause*: Pagination responses from `/api/graphql` declare `content-type: text/javascript`, not JSON. *Fix*: Store all API responses regardless of content type.
2. **Parser failure across GraphQL dialects**: *Symptom*: Missing nodes or key errors on page load vs. scroll requests. *Cause*: Two GraphQL dialects coexist (`/api/graphql` with `xdt_api__v1__feed__user_timeline_graphql_connection` and page-load `/graphql/query` with flat `display_url` / `video_url`). *Fix*: Auto-detect the dialect per payload instead of assuming one shape.
3. **Lost hooks and stream read errors**: *Symptom*: Capture stops after a page reload or crashes while reading a body. *Cause*: A `window.fetch` monkey-patch dies on the first full page reload, and `resp.text()` can throw on streamed bodies. *Fix*: Capture at the protocol layer via `page.on("response")`, catch `resp.text()` exceptions, log the error, and keep going.
4. **Overwritten page files on listener restart**: *Symptom*: Previously captured files (`0001`–`0005`) are overwritten by a second session. *Cause*: A restarted capture listener reuses file counters in the same directory. *Fix*: Number persisted captures inside per-session directories stamped with timestamps.
5. **Misidentifying the logged-in user**: *Symptom*: Output is attributed to a suggested account instead of the profile owner. *Cause*: Suggested-account usernames appear inside payload JSON and look like the user's own handle. *Fix*: Derive identity strictly from the profile URL opened by the live session, never from payload strings.
6. **CDP port conflicts and SSO loops**: *Symptom*: Chrome fails to bind the port or loops during login. *Cause*: Concurrent CDP sessions collide on port `9222` or `9223`, or a stale profile directory causes SSO loops. *Fix*: Parameterize the port (default `9223`) and use a fresh temporary `user-data-dir` per session.
7. **Orphaned processes and temp files**: *Symptom*: Subsequent runs hit port conflicts or leave sensitive session files on disk. *Cause*: Incomplete cleanup on exit. *Fix*: Kill the listener and Chrome, remove the temp profile directory, and delete any credential-bearing temp files every time.

## Failure Behavior

- **Login wall, checkpoint, or 2FA**: Stop scrolling and capture immediately, and ask the user to complete authentication in the browser.
- **Dialect change or unrecognized schema**: Stop parsing, archive the raw payload in `raw_pages/`, and report a sample of the payload to the operator.
- **Stream read error (`resp.text()` failure)**: Log the error with request metadata and continue listening for subsequent responses.
- **Listener death or disconnect**: Restart the listener into a new timestamped session directory so existing raw page files are never overwritten.
