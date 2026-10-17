"""Live capture: CDP-attached Chrome, wire listener, scroll pagination.

Everything in this module requires a real browser and a human at login;
it must never be imported or executed by offline tests or CI.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

NOISE_MARKERS = (
    "segment", "sentry", "amplitude", "google-analytics", "googletagmanager",
    "pendo", "vwo", "facebook.com", "doubleclick", "hotjar", "bugsnag",
    "static.cdninstagram.com", "static.xx.fbcdn", "connect.facebook.net",
    "/favicon", ".woff", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".mp4",
)

API_HINTS = ("/graphql", "/api/")

DEFAULT_PORT = 9223
DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SCROLL_PAUSE_SECONDS = 2.0
IDLE_ROUNDS_BEFORE_STOP = 3


def launch_chrome(port: int, profile_dir: str, start_url: str = "https://www.instagram.com/",
                  chrome_bin: str = DEFAULT_CHROME) -> subprocess.Popen:
    cmd = [
        chrome_bin,
        "--remote-debugging-port=%d" % port,
        "--user-data-dir=%s" % profile_dir,
        "--no-first-run",
        "--no-default-browser-check",
        "--window-size=1400,1000",
        start_url,
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_cdp(port: int, timeout: float = 20.0) -> None:
    import urllib.request

    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:%d/json/version" % port, timeout=2) as resp:
                resp.read()
                return
        except Exception as exc:  # noqa: BLE001 - port not ready yet
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError("CDP endpoint did not come up on port %d: %s" % (port, last_error))


def _is_noise(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in NOISE_MARKERS)


def _is_api(url: str) -> bool:
    return any(hint in url for hint in API_HINTS)


class CaptureSession:
    """Attach to a running Chrome over CDP and archive API responses."""

    def __init__(self, port: int, out_dir: str):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp("http://localhost:%d" % port)
        self.out_dir = os.path.abspath(out_dir)
        self.session_dir = os.path.join(
            self.out_dir, "raw_pages", datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        )
        os.makedirs(self.session_dir, exist_ok=True)
        self._counter = 0
        self._pending_bodies: dict[str, str] = {}
        self._install_listener()

    # -- page / identity --------------------------------------------------
    def instagram_pages(self):
        pages = []
        for context in self._browser.contexts:
            for page in context.pages:
                if "instagram.com" in page.url:
                    pages.append(page)
        return pages

    def active_profile_url(self) -> str | None:
        """Derive the logged-in identity from the live session URL.

        Never trust username strings inside payloads: suggested accounts
        appear there and are easy to mistake for the profile owner.
        """
        for page in self.instagram_pages():
            path = urlparse(page.url).path
            if "/" in path[1:]:
                candidate = path[1:].strip("/")
                if candidate and candidate not in ("p", "reel", "explore", "accounts"):
                    return "https://www.instagram.com/%s/" % candidate
        return None

    def login_wall(self) -> bool:
        for page in self.instagram_pages():
            if "/accounts/login" in page.url or "/challenge" in page.url:
                return True
        return False

    # -- capture ----------------------------------------------------------
    def _install_listener(self) -> None:
        for page in self.instagram_pages():
            self._attach(page)
        for context in self._browser.contexts:
            context.on("page", self._attach)

    def _attach(self, page) -> None:
        def on_response(response):
            try:
                url = response.url
                if not _is_api(url) or _is_noise(url):
                    return
                try:
                    body = response.text()
                except Exception as exc:  # noqa: BLE001 - streamed bodies can fail
                    print("[capture] body read failed for %s: %s" % (url[:120], exc), file=sys.stderr)
                    return
                if body is not None and len(body) < 5_000_000:
                    self._counter += 1
                    name = "page_%04d.json" % self._counter
                    path = os.path.join(self.session_dir, name)
                    with open(path, "w", encoding="utf-8") as fh:
                        fh.write(body)
                    self._pending_bodies[path] = name
            except Exception as exc:  # noqa: BLE001 - never kill the listener
                print("[capture] listener error: %s" % exc, file=sys.stderr)

        page.on("response", on_response)

    def new_page_count(self) -> int:
        return len(self._pending_bodies)

    def consume_page_paths(self) -> list[str]:
        paths = sorted(self._pending_bodies)
        self._pending_bodies.clear()
        return paths

    # -- pagination -------------------------------------------------------
    def scroll_profile(self, rounds: int, max_pages: int | None = None) -> list[str]:
        """Scroll the profile grid until idle or page budget reached.

        Returns the list of captured page file paths.
        """
        pages = self.instagram_pages()
        if not pages:
            raise RuntimeError("no instagram tab found in the attached browser")
        page = pages[0]
        seen_paths: list[str] = []
        idle = 0
        for _ in range(rounds):
            if max_pages is not None and self._counter >= max_pages:
                break
            before = self.new_page_count()
            page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            time.sleep(SCROLL_PAUSE_SECONDS)
            after = self.new_page_count()
            if after > before:
                idle = 0
            else:
                idle += 1
                if idle >= IDLE_ROUNDS_BEFORE_STOP:
                    break
        seen_paths.extend(self.consume_page_paths())
        return seen_paths

    # -- download ---------------------------------------------------------
    def download_media(self, url: str, out_dir: str, name: str) -> str:
        pages = self.instagram_pages()
        if not pages:
            raise RuntimeError("no instagram tab found; cannot download in page context")
        page = pages[0]
        result = page.evaluate(
            """async (u) => {
                const r = await fetch(u);
                const blob = await r.blob();
                const buf = await blob.arrayBuffer();
                let bin = '';
                const bytes = new Uint8Array(buf);
                const chunk = 0x8000;
                for (let i = 0; i < bytes.length; i += chunk) {
                    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
                }
                return {mime: blob.type, ok: r.ok, status: r.status, b64: btoa(bin)};
            }""",
            url,
        )
        if not result.get("ok"):
            raise RuntimeError("download failed for %s: HTTP %s" % (url[:120], result.get("status")))
        ext = "jpg"
        if "video" in (result.get("mime") or ""):
            ext = "mp4"
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "%s.%s" % (name, ext))
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(result["b64"]))
        return path

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()


def cleanup_chrome(profile_dir: str, port: int, chrome_proc: subprocess.Popen | None) -> None:
    """Enforce the cleanup contract: kill processes, remove temp profile."""
    if chrome_proc is not None:
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            chrome_proc.kill()
    subprocess.run(["/usr/bin/pkill", "-f", "user-data-dir=%s" % profile_dir], check=False)
    shutil.rmtree(profile_dir, ignore_errors=True)