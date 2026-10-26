"""Serving the P9 web UI (a static React build) from the same origin as the API.

* Same origin means no CORS configuration and no cross-origin token exposure.
* The assets contain no data and no secret; every API call still needs a bearer token held in browser memory only.
* The UI responses carry a strict Content-Security-Policy. The interactive API docs (development only) are not served
  under ``/ui`` and keep their own looser needs, so the policy applies to the UI path alone.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

UI_MOUNT_PATH = "/ui"
DEFAULT_UI_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"

# Scripts, styles, images and API calls may only come from this origin. No inline script, no eval, no framing, no
# <base>/<form> hijacking, no plugins. React escapes all rendered text, so no HTML from incident or AI content is rendered.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
    "connect-src 'self'; manifest-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'"
)

BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


def is_ui_path(path: str) -> bool:
    return path == UI_MOUNT_PATH or path.startswith(UI_MOUNT_PATH + "/")


def security_headers_for(path: str) -> dict[str, str]:
    """Headers added to a response for ``path``: baseline hardening everywhere, the CSP on UI responses."""
    headers = dict(BASE_SECURITY_HEADERS)
    if is_ui_path(path):
        headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        headers["Cache-Control"] = "no-cache"
    return headers


def ui_directory() -> Path:
    configured = os.getenv("PULSEOPS_UI_DIR")
    return Path(configured) if configured else DEFAULT_UI_DIR


def mount_ui(app: FastAPI, directory: Path | None = None) -> bool:
    """Mount the built UI at ``/ui`` if a build exists. Returns whether it was mounted (the API works without it)."""
    directory = directory or ui_directory()
    if not (directory / "index.html").is_file():
        return False
    app.mount(UI_MOUNT_PATH, StaticFiles(directory=directory, html=True), name="ui")
    return True
