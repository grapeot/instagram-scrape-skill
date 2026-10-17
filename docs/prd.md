# Product Requirements Document: instagram-scrape-skill (v0)

## 1. Background

This project originated as a homework assignment in the AI Builders course, where
students opened browser DevTools, scrolled their own Instagram profile, saved the
network traffic as a HAR file, and asked an AI to extract image URLs and generate
threaded download code into a local folder. A later session in the AI Builders course
taught the core practice this repository embodies: when a task repeats for the second
time, distill its goal, acceptance criteria, and pitfalls into a provider-neutral
Markdown skill file so a fresh agent can re-run it with minimal prompting. This
repository is the agent-native upgrade of that homework paired with its distilled skill
(`skills/instagram-scrape/SKILL.md`). An AI coding agent attaches to a real Chrome
browser over the Chrome DevTools Protocol (CDP), the user logs in manually, and the
tool captures the structured GraphQL responses that the Instagram web app requests
while scrolling the profile, parsing them into a deduplicated media archive.

## 2. Goals

- **Archive own-account media with a structured index**:
  - Drive profile pagination via `window.scrollBy` (`~2 s` pacing) and capture raw API
    responses from `https://www.instagram.com/api/graphql` and `/graphql/query` into
    `<out>/<username>/raw_pages/` using per-session timestamped filenames.
  - Parse both GraphQL dialects (`xdt_api__v1__feed__user_timeline_graphql_connection`
    and flat `display_url` / `video_url` page-load payloads) into a deduplicated index
    at `<out>/<username>/media_index.jsonl` keyed by `(shortcode, image_url)`.
  - Extract max-width images from `image_versions2.candidates[]`, max-height videos
    from `video_versions[]`, and expanded album items from `carousel_media[]` alongside
    `code`, `taken_at`, `caption.text`, `media_type` (`1`=photo, `2`=video, `8`=carousel),
    capture timestamp, and post permalink (`https://www.instagram.com/p/<code>/`).
  - Support optional in-browser media downloads (`--download`) into `<out>/<username>/media/`
    by calling `fetch(mediaUrl)` in the logged-in page context and reading base64 over CDP.
- **Keep the browser as the only client (no credentials on disk)**:
  - Launch Chrome with `--remote-debugging-port=<port> --user-data-dir=<fresh temp dir>
    --no-first-run --no-default-browser-check` and attach via Playwright
    `chromium.connect_over_cdp("http://localhost:<port>")`.
  - Store no cookies, tokens, `.env` files, or signed-URL tricks on disk, and remove
    the temporary profile directory and Chrome/listener processes upon completion.
- **Make the method re-runnable by an agent via the skill file**:
  - Provide `skills/instagram-scrape/SKILL.md` and a small CLI (`ig-scrape archive`,
    `ig-scrape parse`, `ig-scrape export`) that encode the workflow and live pitfalls.

## 3. Non-Goals

- **Bulk crawling**: No unpaced scraping loops or mass collection. Meta's Terms of
  Service disallow unauthorized automated collection; this repo is limited to own-account
  archiving at human pace and makes no claim of broader legal clearance.
- **Other people's accounts**: No third-party profile scraping or username fan-out.
- **Anonymous access**: No unauthenticated scraping mode; a live logged-in session is required.
- **Login automation**: Password entry, checkpoints, and 2FA are strictly human-only;
  the tool refuses and stops if it detects a login wall.
- **Stories and DMs in v0**: Scope is restricted to main profile grid posts (photos,
  videos, and carousels); stories, direct messages, and other surfaces are out of scope.

## 4. Users

- **(a) Repository owner archiving personal media**: Uses `ig-scrape archive --username
  NAME --max-items N [--max-pages N] [--download] [--out DIR]` to back up personal posts
  before signed CDN URLs expire, and `ig-scrape export --index FILE --format json|csv`
  to project the index.
- **(b) AI Builders course students reproducing the homework natively**: Use and extend
  the codebase to practice agent-driven CDP capture, offline payload parsing, and skill
  distillation.
- **(c) Any AI coding agent reading the skill file**: Follows `skills/instagram-scrape/SKILL.md`
  to run the browser setup, human login handoff, capture, verification, and cleanup.

## 5. Success Criteria

- **Offline `pytest` passes**: The test suite runs offline in GitHub Actions CI (`master`/`main`)
  and validates both GraphQL dialects, carousel expansion, resolution selection, index
  deduplication, and `json`/`csv` export.
- **An agent with no prior context can archive a profile using only `SKILL.md`**: A fresh
  agent reading only `skills/instagram-scrape/SKILL.md` can complete an archive run while
  avoiding all known live pitfalls (storing `content-type: text/javascript` pagination
  payloads, capturing via protocol-level `page.on("response")` instead of `window.fetch`,
  handling `resp.text()` stream errors, and using isolated ports and temp profile dirs).
- **Every media record in the index can be traced back to an archived raw page**: Every
  item in `<out>/<username>/media_index.jsonl` maps to a preserved payload file in
  `<out>/<username>/raw_pages/` and can be reproduced offline via `ig-scrape parse --page FILE`.
- **Identity is always derived from the live session**: The active account username is
  taken from the authenticated profile URL opened in the browser session, never from
  payload JSON strings that include suggested-account usernames.
