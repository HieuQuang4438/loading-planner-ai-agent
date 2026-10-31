"""Versioned URLs of the shared viewer files (#100). The version is a hash of their content, so a deploy that changes
a file changes the URL and a browser can cache the old URL forever (`immutable`)."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from fastapi.responses import HTMLResponse

SHARED_STATIC = Path(__file__).parent / "static" / "shared"
VERSION_LENGTH = 12
UNVERSIONED = "/static/shared/"
VERSIONED_STYLE = re.compile(rf"/static/[0-9a-f]{{{VERSION_LENGTH}}}/shared/style\.css")  # what the login page loads


def shared_version(directory: Path = SHARED_STATIC) -> str:
    """First 12 hex of sha256 over the sorted relative paths and bytes of every file under `directory`."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:VERSION_LENGTH]


def versioned_page(page: Path, version: str) -> HTMLResponse:
    """The HTML of `page` with every shared path pointing at the versioned copy."""
    text = page.read_text(encoding="utf-8").replace(UNVERSIONED, f"/static/{version}/shared/")
    return HTMLResponse(text)
