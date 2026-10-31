"""Routes of the runs kept in `app.db` (docs/reference/api.md, "Chạy"). Every
query is the session user's: another user's run and a missing one answer the same 404."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request

from src.web.api import session_owner
from src.web.runstore import SqliteStore


def run_routes(store: SqliteStore) -> APIRouter:
    router = APIRouter()

    def owner(request: Request) -> int:
        user_id = session_owner(request)
        assert user_id is not None  # the login middleware is in front of every route
        return user_id

    @router.get("/api/runs")
    def list_runs(request: Request) -> list[dict[str, Any]]:
        """The user's runs, newest first, as one line each (no lot or solution)."""
        return [asdict(r) for r in store.list_runs(owner(request))]

    @router.get("/api/runs/{job_id}")
    def run_result(job_id: str, request: Request) -> dict[str, Any]:
        """Same JSON as `/api/jobs/{id}/result`, for a run kept earlier (also before a restart)."""
        return store.view(owner(request), job_id)

    @router.get("/api/runs/{job_id}/lot.json")
    def run_lot(job_id: str, request: Request) -> dict[str, Any]:
        return store.lot_dict(owner(request), job_id)

    @router.get("/api/runs/{job_id}/solution.json")
    def run_solution(job_id: str, request: Request) -> dict[str, Any]:
        return store.solution_dict(owner(request), job_id)

    @router.delete("/api/runs/{job_id}")
    def delete_run(job_id: str, request: Request) -> dict[str, bool]:
        store.delete(owner(request), job_id)
        return {"ok": True}

    return router
