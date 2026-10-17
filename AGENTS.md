# Instagram Scrape Skill — Project Rules

## What this repo is

A public reference implementation of browser-native Instagram scraping: an agent
attach over CDP to a real Chrome session, capture the GraphQL payloads the
Instagram web app fetches itself, and archive a structured media index. It is
also the worked example for the AI Builders course practice project.

## Hard constraints

1. **Public repo.** English only in code, docs, skills, tests, and commit
   messages. No real usernames, user IDs, avatar URLs, signature-bearing CDN
   URLs, emails, or private paths in any committed file. Test fixtures must be
   sanitized (fake username `example_user`, fake CDN host). The real username
   and data live only in gitignored `data/` or outside the repo.
2. **No credentials.** The design uses no cookies, tokens, or `.env`. Auth
   always comes from a real human login in a CDP-attached Chrome. Never add a
   login-automation path; checkpoints and 2FA are a hard agent boundary.
3. **Own account only.** The tools are for archiving media from an account the
   operator has logged into. Do not add mass-crawl loops, username fan-out, or
   anonymous scraping modes.
4. **Offline-by-default tests.** `pytest tests/` must pass with no network and
   no browser. Live capture is a manual smoke test, never part of CI.
5. **Version control.** Default branch: `master`. Commit only when the task
   explicitly asks. Small, reversible commits; never `git add -A`.
6. After a substantive change, append a dated bullet under `docs/working.md` →
   Changelog and record real failures under Lessons Learned.

## Layout

```text
src/ig_scrape/    # library: parse (page payload -> records), merge, capture, cli
scripts/ig-scrape # CLI entrypoint
skills/instagram-scrape/SKILL.md  # the distilled agent skill
docs/             # prd / rfc / working / test
tests/            # offline unit tests + sanitized fixtures
data/             # gitignored local archive output
```

## Validation checklist

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest tests/ -v
```

Public hygiene scan before publishing anything:
`rg -n "cdninstagram|cdninstagram.com|[a-z0-9._]+@[a-z]+\.(com|net)|op://" .` must
return zero real matches in committed files (fixtures use `example.com` hosts).