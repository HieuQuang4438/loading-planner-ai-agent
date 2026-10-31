"""Errors of the web, one body for every mode: `{code, message, details[]}`."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.formats import Issue


class WebError(Exception):
    code = "error"
    status = 500

    def __init__(self, message: str, details: list[Issue] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []

    def body(self) -> dict[str, Any]:
        return error_body(self.code, self.message, self.details)


class BadRequest(WebError):
    """Input the web cannot run: a bad lot, an engine the mode does not offer, a value out of range."""

    code = "invalid_input"
    status = 422


class LotNotFound(WebError):
    """No such lot, job, run or path."""

    code = "not_found"
    status = 404


class Conflict(WebError):
    """A write on an old revision of a lot: the client reads the lot again."""

    code = "conflict"
    status = 409


class NotReady(WebError):
    """A run asked for a lot with fields not confirmed yet; `details` names them (ADR-0001)."""

    code = "not_ready"
    status = 409


class QueueFull(WebError):
    code = "queue_full"
    status = 503


class Unauthorized(WebError):
    """No valid session, or a failed login (mode `service` with login, docs/product/architecture.md §5)."""

    code = "unauthorized"
    status = 401


class Forbidden(WebError):
    """A state-changing request from an origin not in `PLANNER_ORIGINS`, or with a body that is not JSON."""

    code = "forbidden"
    status = 403


def error_body(code: str, message: str, details: list[Issue] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": [asdict(d) for d in details or []]}
