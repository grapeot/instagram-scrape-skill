# Working Notes

## Changelog

### 2026-10-17

- Validated the archive methodology end-to-end on a live account using scroll-driven Playwright CDP capture, archiving 132 deduplicated media items (photos, videos, and expanded carousel items) from the owner's profile.
- Identified and implemented support for two GraphQL payload dialects: `/api/graphql` (`data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[].node`) for profile pagination and `/graphql/query` (flat `display_url` and `video_url` fields) for initial page loads.
- Verified optional browser-context media download over CDP (`fetch(mediaUrl)` to base64 blob), producing a valid 1440x1085 JFIF JPEG (181 KB).
- Scaffolded the `instagram-scrape-skill` v0 repository with the `ig-scrape` CLI (`archive`, `parse`, `export`), MIT license, and GitHub Actions offline pytest CI workflow.
- Drafted and reviewed the repository documentation and `skills/instagram-scrape/SKILL.md` agent skill via a drafting agent.
- Published the repository (public GitHub, `master` with required-PR branch protection, zero required reviews, admin-enforced); landed the CLI implementation and offline suite via PR #1 (17 tests green), and a follow-up PR #2 wiring the `ig-scrape` console script.
- Published `README.zh-CN.md`: drafted from the settled English README via the drafting agent, then processed with the voice-rewrite model; five surgical fact fixes applied (invented first-person attribution in the course-lesson paragraph, tool-vs-"we" attribution in the capture paragraph, prose paragraph restored from a stray list bullet, lowercase `chrome`/`2fa`/`graphql` casing). Style unchanged per the voice-rewrite contract.

## Lessons Learned

1. Pagination payloads are silently dropped during capture -> Instagram returns `/api/graphql` pagination responses with `content-type: text/javascript` instead of `application/json`, causing JSON content-type filters to ignore them -> Persist all matching API responses regardless of their `content-type` header.
2. Parsing fails or misses items on initial page-load responses -> Two GraphQL schemas coexist: profile pagination at `/api/graphql` nests nodes under `data.xdt_api__v1__feed__user_timeline_graphql_connection.edges[].node` (`image_versions2.candidates[]`, `video_versions[]`, `carousel_media[]`), whereas initial queries to `/graphql/query` expose flat `display_url` and `video_url` fields -> Auto-detect the payload dialect before extracting media records instead of assuming a single schema.
3. Capture stops working after a page refresh or crashes on in-flight responses -> Monkey-patching `window.fetch` inside the page context is wiped on full page reloads, and `resp.text()` can throw on streamed response bodies -> Attach listeners at the CDP protocol layer via `page.on("response")`, catch `resp.text()` exceptions, log them, and continue capturing.
4. Previously saved raw page files (`0001`–`0005`) are overwritten when a capture listener restarts -> Restarting the listener resets the sequential counter while targeting the same output folder -> Write captures into per-session directories and include timestamps in saved filenames.
5. Unrelated usernames are misidentified as the logged-in account owner -> GraphQL payloads include suggested-account metadata whose username fields look like profile identifiers -> Read the target username from the profile URL opened by the browser session, never from strings inside payload JSON.
6. CDP connection fails with port conflicts (`9222` vs. `9223`) or gets stuck in SSO redirect loops -> Hardcoded debugging ports collide across concurrent sessions, and reusing a Chrome profile directory carries over stale authentication state -> Pass `--remote-debugging-port` as a configurable parameter and create a fresh temporary `--user-data-dir` for each session.
7. Stray Chrome processes and session artifacts persist on disk after archiving finishes -> Exiting the script without teardown leaves the browser, background listener, and temporary profile directory behind -> Run a mandatory cleanup step after every session that terminates the listener and Chrome processes, deletes the temporary `--user-data-dir`, and removes any credential-bearing temporary files.
