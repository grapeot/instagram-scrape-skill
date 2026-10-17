# Design Document: instagram-scrape-skill

This document specifies the architecture, component boundaries, data contracts, operational limits, and failure handling for `instagram-scrape-skill` (v0), a personal-media archiving tool for a user's own Instagram account.

## 1. Design Overview

The system is structured into three sequential layers: **Capture**, **Parse**, and **Archive**. Each layer reads and writes explicit artifacts under `<out>/<username>/` so stages can be inspected or re-executed offline.

### Capture Layer
- **Responsibility**: Attach to a real Chrome browser over the Chrome DevTools Protocol (CDP), drive profile pagination at human pace, and persist raw GraphQL responses to disk.
- **Mechanism**: Chrome launches with `--remote-debugging-port=<port> --user-data-dir=<fresh-temp-dir> --no-first-run --no-default-browser-check` (validated on port `9223`) and opens `instagram.com`. The human user logs in manually and completes any checkpoint or 2FA challenge. A Python listener attaches via Playwright `chromium.connect_over_cdp("http://localhost:<port>")` and registers protocol-level `page.on("response")` and `page.on("request")` handlers. Protocol-level listeners survive full page reloads that wipe out injected `window.fetch` monkey-patches.
- **Pagination**: The driver scrolls the profile grid (`window.scrollBy` via `page.evaluate`), pacing ~2 seconds between scrolls. Each scroll threshold triggers the web app to send a `POST` request to `https://www.instagram.com/api/graphql` (~300 KB JSON per response). Analytics and static assets are filtered out. All GraphQL responses are stored regardless of MIME header because pagination responses declare `content-type: text/javascript` rather than `application/json`.
- **Artifact**: `<out>/<username>/raw_pages/`, containing one append-only JSON file per captured API response inside a per-session timestamped directory.

### Parse Layer
- **Responsibility**: Transform raw GraphQL payloads into normalized media records using pure, side-effect-free functions.
- **Mechanism**: Auto-detects between two coexisting Instagram GraphQL dialects:
  1. **Profile pagination dialect** (`/api/graphql`): reads `data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[].node`. Extracts `code`, `taken_at`, `caption.text`, and `media_type` (`1` = photo, `2` = video, `8` = carousel). Selects the maximum-width entry from `image_versions2.candidates[]` for images, the maximum-height entry from `video_versions[]` for videos, and expands `carousel_media[]` into individual slide records.
  2. **Page-load dialect** (`/graphql/query`): reads older web-style nodes containing flat `display_url` and `video_url` fields.
- **Identity Rule**: The archive `username` is derived from the profile URL opened by the session, never from payload JSON strings (which contain suggested-account usernames).
- **Artifact**: Normalized record dictionaries passed directly to the archive layer or produced offline via `ig-scrape parse --page FILE [--out DIR]`.

### Archive Layer
- **Responsibility**: Merge and deduplicate parsed records into a canonical index, project export formats, and optionally download media files.
- **Mechanism**: Merges records into `<out>/<username>/media_index.jsonl` keyed by `(code, image_url)`. When `--download` is passed, the tool executes `fetch(mediaUrl)` inside the logged-in page context (where signed CDN URLs are CORS-open), transfers the response blob as base64 over CDP, and decodes the file to disk.
- **Artifacts**: `<out>/<username>/media_index.jsonl`, optional downloaded files in `<out>/<username>/media/`, and formatted projections via `ig-scrape export --index FILE --format json|csv`.

### CLI Entrypoints
- `ig-scrape archive --username NAME --max-items N [--max-pages N] [--download] [--out DIR]` — executes session probe, scroll pagination, capture, parse, and index merge.
- `ig-scrape parse --page FILE [--out DIR]` — offline re-parse of one archived payload.
- `ig-scrape export --index FILE --format json|csv` — projects the JSONL index to JSON or CSV.

## 2. What Goes Where: LLM Judgment vs. Deterministic Code

Responsibilities are divided strictly between the AI coding agent and deterministic Python code:

- **AI Agent (Judgment)**:
  - Evaluates login state before capture starts and detects login walls, checkpoints, or 2FA screens.
  - Diagnoses dialect drift when an upstream payload change causes parsing to fail, inspecting the saved sample in `raw_pages/` to update parser logic.
  - Controls high-level stop conditions (`--max-items`, `--max-pages`, or halting on repeated session anomalies).
- **Deterministic Code (Execution)**:
  - Owns CDP event handlers, scroll pacing loops, file numbering, dialect auto-detection for known schemas, JSON extraction, `(code, image_url)` deduplication, and base64 decoding.

**Why this separation is required**:
1. **Long-run reliability**: A typical session captures dozens of ~300 KB payloads and 100+ media items. Running pagination, parsing, and deduplication in deterministic Python avoids LLM latency, token cost, context-window saturation, and transcription errors on signed URLs or timestamps.
2. **Unit-testability**: Pure parsing and merging functions are tested offline via `pytest` in GitHub Actions against static fixtures without a browser, credentials, or live network.

## 3. Key Decisions and Rejected Alternatives

### Browser-Native Capture Instead of HTTP Replay
- **Decision**: Drive a real Chrome instance and capture responses over CDP instead of replaying HTTP requests from Python with copied headers.
- **Why**: A real browser keeps TLS fingerprints, HTTP/2 framing, cookies, and session state coherent with the web app; nothing is forged.
- **Trade-off**: Requires a GUI browser and a human at login; cannot run headless in unattended cron jobs.

### No Cookie or Token Files
- **Decision**: Store no cookies, session tokens, or `.env` files on disk. Authentication lives only in the active browser session.
- **Why**: Prevents credential leakage into git trees or logs and avoids stale cookie invalidation.
- **Trade-off**: Each session requires manual login, mitigated by launching Chrome with a fresh temporary `--user-data-dir` per run.

### Raw Pages Stored Forever (Append-Only), Index Rebuildable
- **Decision**: Write every raw API payload to `raw_pages/` before parsing and keep `media_index.jsonl` rebuildable via `ig-scrape parse`.
- **Why**: Scraping endpoints historically break silently when upstream schemas shift. Archiving raw responses ensures captured payloads can be re-parsed offline after updating parser code without re-hitting the network.

### URL-Only Index by Default, Explicit `--download` Flag
- **Decision**: Output `media_index.jsonl` by default and require `--download` to save binary media via in-page `fetch(mediaUrl)`.
- **Why**: Signed CDN media URLs expire within days, while post permalinks (`https://www.instagram.com/p/<code>/`) and `taken_at` timestamps are durable. Defaulting to a metadata index keeps runs fast while supporting in-session downloads when durable local media files are wanted.

### `master` Branch with Zero-Required-Reviews Branch Protection
- **Decision**: Use `master` as the default branch with required CI checks (`pytest`) and administrative enforcement, but zero required pull-request reviews.
- **Why**: In a solo-maintainer repo, mandatory approval counts block merges or force artificial self-approvals, while admin-enforced branch protection still prevents force-pushes and broken CI merges.

## 4. Data Schema

`<out>/<username>/media_index.jsonl` stores one UTF-8 JSON object per line, deduplicated by `(code, image_url)`. A carousel post (`media_type == 8`) produces one parent record with `type: "carousel"` plus one record per slide (the slide records share the parent `code` and `permalink`).

```json
{"username": "example_user", "code": "CLPf-i2Pb0k", "permalink": "https://www.instagram.com/p/CLPf-i2Pb0k/", "type": "photo", "taken_at": 1690000000, "caption": "Sample caption text", "image_url": "https://cdn-images.example/...fake-signed...", "video_url": null, "carousel_media_count": null, "first_seen": "2026-10-17T08:30:12Z", "source_page": "raw_pages/20261017T083012Z/page_0001.json"}
```

- `username` (`string`): Account handle from the session profile URL.
- `code` (`string`): Instagram post shortcode.
- `permalink` (`string`): Durable post URL (`https://www.instagram.com/p/<code>/`).
- `image_url` (`string`): Ephemeral signed CDN URL (max-width candidate from `image_versions2.candidates[]` or flat `display_url`).
- `video_url` (`string | null`): Ephemeral signed CDN URL for videos (max-height entry from `video_versions[]`, or the flat `video_url` in the page-load dialect); `null` for photos.
- `type` (`string`): `"photo"` or `"video"` mapped from `media_type` (`1` or `2`, or per-slide `media_type` inside `carousel_media[]`); `"carousel"` for the parent record of an album (`media_type == 8`).
- `taken_at` (`integer`): Unix epoch timestamp in seconds; slide records inherit the parent value.
- `caption` (`string | null`): Post caption from `caption.text`, or `null` if empty.
- `carousel_media_count` (`integer | null`): Slide count on the parent record of a carousel post (`media_type == 8`); `null` on everything else.
- `first_seen` (`string`): ISO-8601 capture timestamp of the session that produced the record.
- `source_page` (`string`): Path, relative to `<out>/<username>/`, of the archived raw payload the record was parsed from — this is what makes every index row traceable and offline-reparsable.

## 5. Boundaries and Compliance

- **Own account only**: Restricted to archiving the authenticated user's own account. The tool includes no username fan-out, no graph crawling, and no anonymous scraping mode.
- **Human pace**: Scroll pagination waits ~2 seconds between steps and honors `--max-items` and `--max-pages`. No bulk collection modes exist.
- **Terms of Service**: Meta's Terms of Service disallow unauthorized automated collection. Own-account archiving in a real browser session at human pace is the lowest-risk use case; this repository claims no broader legal clearance, stores no offline fingerprint or signed-URL tricks, and ships no bulk-scraping affordances.
- **Agent hard-line**: Never automate login, password entry, security checkpoints, or 2FA.

## 6. Failure Modes and Handling

- **Login wall detected**:
  - *Trigger*: Navigation redirects to `/accounts/login/`, `/challenge/`, or displays an authentication prompt.
  - *Handling*: Stop immediately, do not enter credentials, and ask the human user to complete login in Chrome.
- **Payload dialect change**:
  - *Trigger*: A captured GraphQL payload matches neither `xdt_api__v1__feed__user_timeline_graphql_connection` nor the `/graphql/query` shape.
  - *Handling*: Stop parsing, preserve the raw payload in `raw_pages/`, and surface a sample to the agent for parser updates. Never filter responses by JSON MIME type because pagination responses declare `content-type: text/javascript`.
- **Stream read errors**:
  - *Trigger*: `resp.text()` raises an error on an aborted or chunked CDP stream.
  - *Handling*: Log the error and continue listening for subsequent responses.
- **Listener restart collisions**:
  - *Trigger*: Restarting a listener with a static `0001` counter overwrites existing `0001`–`0005` files in `raw_pages/`.
  - *Handling*: Isolate captured files into per-session directories with timestamps.
- **Port conflicts and stale profiles**:
  - *Trigger*: Concurrent sessions collide on port `9222`/`9223`, or a reused profile directory triggers SSO redirect loops.
  - *Handling*: Parameterize `--remote-debugging-port`, allocate a fresh temporary `--user-data-dir` per session, and enforce the cleanup contract after every run: kill the listener and Chrome, remove the temporary profile directory, and delete any credential-bearing temporary files.
