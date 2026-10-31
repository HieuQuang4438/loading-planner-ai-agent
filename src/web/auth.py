"""Login (docs/product/architecture.md §6): argon2id passwords, sessions kept in SQLite, lockout after repeated
failures, and one ASGI middleware in front of every route. Always on (`src.web.service.app`).

The middleware runs before routing, so it also covers the static mount and paths that do not exist (401, not 404).
Request order: session check (401, or 303 to `/login` for `GET /`), then for POST/PUT/PATCH/DELETE the `Origin`
check against `PLANNER_ORIGINS` and the JSON-only body check (both 403 `forbidden`)."""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from src.web.assets import VERSIONED_STYLE, shared_version, versioned_page
from src.web.db import connect, migrate
from src.web.errors import Forbidden, Unauthorized, WebError

log = logging.getLogger(__name__)

COOKIE = "planner_session"
SESSION_TTL = timedelta(hours=12)  # fixed from the login, not sliding
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)  # MAX_FAILURES within it lock the name for as long again
LOGIN_PAGE = Path(__file__).parent / "service" / "static" / "login.html"
PUBLIC = {("GET", "/login"), ("GET", "/healthz"), ("POST", "/api/login"),
          ("GET", "/static/shared/style.css")}  # the last is what the login page loads
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
LOGIN_FAILED = "Tên hoặc mật khẩu không đúng."
_STAMP = "%Y-%m-%dT%H:%M:%S.%fZ"
_hasher = PasswordHasher()  # argon2id
# Verified against when the name is unknown, so that an unknown name costs the same time as a wrong password.
_DUMMY_HASH = _hasher.hash("not-a-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def stamp(t: datetime) -> str:
    """Fixed-width UTC text, so that string order is time order in SQL."""
    return t.strftime(_STAMP)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AuthConfig:
    db_path: str
    origins: tuple[str, ...]  # the only origins a state-changing request may come from; never derived from Host

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> AuthConfig:
        origins = tuple(o.strip().rstrip("/") for o in env.get("PLANNER_ORIGINS", "").split(",") if o.strip())
        return cls(env.get("PLANNER_DB") or "/data/app.db", origins)


@dataclass(frozen=True)
class SessionUser:
    id: int
    name: str
    token_hash: str


class LoginRequest(BaseModel):
    name: str
    password: str


class _Closing:
    """A connection that closes at the end of `with` (sqlite3's own `with` only ends a transaction)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        return self.conn

    def __exit__(self, *exc: object) -> None:
        self.conn.close()


def _password_ok(pw_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(pw_hash, password)
    except (VerificationError, InvalidHashError):
        return False


class Auth:
    """The login state of one app: config, the clock, and the queries on `users`, `sessions`, `login_failures`.
    Opens the file and migrates it on creation; one connection per call after that."""

    def __init__(self, config: AuthConfig, now: Callable[[], datetime] = _now) -> None:
        self.config = config
        self.now = now
        with self.db() as conn:
            migrate(conn)
            if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None:
                log.warning("the users table is empty: nobody can log in (every login answers 401). "
                            "Create one: python -m src.web.users seed (PLANNER_ADMIN_NAME, PLANNER_ADMIN_PASSWORD) or add.")
        if not config.origins:
            log.warning("PLANNER_ORIGINS is empty: every POST/PUT/PATCH/DELETE will be refused with 403")

    def db(self) -> _Closing:
        return _Closing(connect(self.config.db_path))

    # ---- sessions -----------------------------------------------------------------------------------------------
    def create_session(self, conn: sqlite3.Connection, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        now = self.now()
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (stamp(now),))
        conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                     (token_hash(token), user_id, stamp(now + SESSION_TTL)))
        return token

    def session_user(self, token: str | None) -> SessionUser | None:
        """The active user of a live session, else None."""
        if not token:
            return None
        digest = token_hash(token)
        with self.db() as conn:
            row = conn.execute(
                "SELECT u.id, u.name FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = ? AND s.expires_at > ? AND u.active = 1", (digest, stamp(self.now()))).fetchone()
        return SessionUser(row["id"], row["name"], digest) if row else None

    # ---- lockout ------------------------------------------------------------------------------------------------
    def is_locked(self, conn: sqlite3.Connection, name: str) -> bool:
        """MAX_FAILURES failures within FAILURE_WINDOW of each other lock the name until FAILURE_WINDOW after the
        latest one. Attempts while locked are not recorded, so the lock does not extend itself."""
        rows = conn.execute("SELECT at FROM login_failures WHERE name = ? ORDER BY at DESC LIMIT ?",
                            (name, MAX_FAILURES)).fetchall()
        if len(rows) < MAX_FAILURES:
            return False
        newest, oldest = (datetime.strptime(rows[i]["at"], _STAMP).replace(tzinfo=timezone.utc) for i in (0, -1))
        return newest - oldest < FAILURE_WINDOW and self.now() < newest + FAILURE_WINDOW

    def record_failure(self, conn: sqlite3.Connection, name: str) -> None:
        now = self.now()
        conn.execute("DELETE FROM login_failures WHERE at < ?", (stamp(now - 2 * FAILURE_WINDOW),))
        conn.execute("INSERT INTO login_failures (name, at) VALUES (?, ?)", (name, stamp(now)))

    # ---- routes -------------------------------------------------------------------------------------------------
    def router(self) -> APIRouter:
        router = APIRouter()
        version = shared_version()

        @router.get("/login")
        def login_page() -> HTMLResponse:
            return versioned_page(LOGIN_PAGE, version)

        @router.get("/healthz")
        def healthz() -> JSONResponse:
            try:
                with self.db() as conn:
                    conn.execute("SELECT 1 FROM users LIMIT 1")
            except sqlite3.Error:
                return JSONResponse({"status": "error"}, status_code=503)
            return JSONResponse({"status": "ok"})

        @router.post("/api/login")
        def login(req: LoginRequest) -> JSONResponse:
            name = req.name.strip().lower()[:64]
            with self.db() as conn:
                if self.is_locked(conn, name):
                    raise Unauthorized(LOGIN_FAILED)
                row = conn.execute("SELECT id, name, pw_hash FROM users WHERE name = ? AND active = 1",
                                   (name,)).fetchone()
                ok = _password_ok(row["pw_hash"] if row else _DUMMY_HASH, req.password)
                if row is None or not ok:
                    self.record_failure(conn, name)
                    raise Unauthorized(LOGIN_FAILED)
                conn.execute("DELETE FROM login_failures WHERE name = ?", (name,))
                token = self.create_session(conn, row["id"])
            response = JSONResponse({"name": row["name"]})
            # Secure is configuration, not the request's scheme (architecture §5): behind a proxy uvicorn sees http.
            response.set_cookie(COOKIE, token, max_age=int(SESSION_TTL.total_seconds()), path="/",
                                httponly=True, secure=True, samesite="strict")
            return response

        @router.post("/api/logout")
        def logout(request: Request) -> JSONResponse:
            user: SessionUser = request.scope["planner.user"]
            with self.db() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (user.token_hash,))
            response = JSONResponse({"ok": True})
            response.delete_cookie(COOKIE, path="/", httponly=True, secure=True, samesite="strict")
            return response

        @router.get("/api/me")
        def me(request: Request) -> dict[str, Any]:
            return {"name": request.scope["planner.user"].name}

        return router


class AuthMiddleware:
    """Pure ASGI, so it sits in front of the router and the static mount alike."""

    def __init__(self, app: ASGIApp, auth: Auth) -> None:
        self.app = app
        self.auth = auth

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":  # the web has no websocket
            await send({"type": "websocket.close", "code": 1008})
            return
        refusal = await self._refusal(scope)
        if refusal is not None:
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _refusal(self, scope: Scope) -> Callable[[Scope, Receive, Send], Awaitable[None]] | None:
        """The response that stops this request, or None to let it through (a session is put in the scope)."""
        method, path = scope["method"], scope["path"]
        request = Request(scope)
        if (method, path) not in PUBLIC and not (method == "GET" and VERSIONED_STYLE.fullmatch(path)):
            user = await run_in_threadpool(self.auth.session_user, request.cookies.get(COOKIE))
            if user is None:
                if method == "GET" and path == "/":
                    return RedirectResponse("/login", status_code=303)
                return _error(Unauthorized("cần đăng nhập"))
            scope["planner.user"] = user
        if method in UNSAFE:
            if request.headers.get("origin", "").rstrip("/") not in self.auth.config.origins:
                return _error(Forbidden("nguồn gửi yêu cầu không được phép"))
            has_body = request.headers.get("content-length", "0") != "0" or "transfer-encoding" in request.headers
            media = request.headers.get("content-type", "").split(";")[0].strip().lower()
            if has_body and media != "application/json":
                return _error(Forbidden("nội dung yêu cầu phải là JSON"))
        return None


def _error(error: WebError) -> JSONResponse:
    return JSONResponse(error.body(), status_code=error.status)
