"""Shared routes: config, lot check, jobs, solution check. The app (`src.web.service.app`) adds its own routes and
page; `/static/shared` (and `/static/<version>/shared`) serves the viewer modules. Every error answers
`{code, message, details[]}`."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationInfo, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.bound import lower_bound
from src.checker import EPS, Violation, check, stack_measures
from src.formats import Issue, solution_from_dict
from src.model import ALL_ORIENTATIONS, Instance, Params, Solution, line_of
from src.web import mode as m
from src.web.assets import SHARED_STATIC, shared_version, versioned_page
from src.web.auth import Auth, AuthMiddleware
from src.web.errors import BadRequest, LotNotFound, WebError, error_body
from src.web.job_manager import JobManager
from src.web.lots import MAX_CLIENT_ITEMS, MAX_CLIENT_LINES, lot_from_client, read_client_lot
from src.web.view import build_view

_HTTP_CODES = {404: "not_found", 405: "not_found", 422: "invalid_input", 503: "queue_full"}


class RunRequest(BaseModel):
    """Every field but `lot` may be left out. `lot` is a lot as JSON, its container types and costs included.
    `engine` and `seed` are ignored: `orient` picks the engine, the seed is fixed."""

    engine: str = m.DEFAULT_ENGINE
    from_job: str | None = None  # continue from this earlier run of the user; it brings its own lot, δ, α and
    # orient flag, so those fields of the request are ignored
    lot: dict[str, Any] | None = Field(default=None, validate_default=True)  # may be left out only with `from_job`
    seed: int = m.DEFAULT_SEED
    time_limit: float | None = None  # None: the default by lot size
    delta: float = m.DEFAULT_DELTA
    alpha: float = m.DEFAULT_ALPHA
    orient: bool | None = None  # None: on

    @field_validator("lot")
    @classmethod
    def _lot_unless_from_job(cls, lot: Any, info: ValidationInfo) -> Any:
        if lot is None and info.data.get("from_job") is None:
            raise ValueError("Field required")
        return lot


def request_orient(req: RunRequest) -> bool:
    """The orient flag of a request: a missing one is `true`."""
    return req.orient if req.orient is not None else True


MAX_CHECK_VIOLATIONS = 2000  # `violations` of /api/check beyond this are counted, not listed


class CheckRequest(BaseModel):
    """A lot, a solution of it and the parameters to judge it with."""

    lot: dict[str, Any]
    solution: dict[str, Any]
    delta: float = m.DEFAULT_DELTA
    alpha: float = m.DEFAULT_ALPHA


def _solution_issues(instance: Instance, solution: Solution) -> list[Issue]:
    """Shape problems that make a solution undrawable (unknown item line, orientation code or container type, a
    non-numeric position). Rule violations (overlap, missing items, a disallowed orientation) are the checker's."""
    issues = []
    types = {t.id for t in instance.container_types}
    for used in solution.containers:
        if not isinstance(used.k, int) or isinstance(used.k, bool) or used.type not in types:
            issues.append(Issue(f"container {used.k!r}: k must be an integer and type one of {sorted(types)}",
                                field="containers"))
    for p in solution.placements:
        where = {"field": "placements"}
        if not isinstance(p.item, str) or instance.line(line_of(p.item)) is None:
            issues.append(Issue(f"{p.item!r}: not an item of the lot", **where))
        elif p.o not in ALL_ORIENTATIONS:
            issues.append(Issue(f"{p.item}: unknown orientation code {p.o!r}", **where))
        elif not isinstance(p.k, int) or isinstance(p.k, bool):
            issues.append(Issue(f"{p.item}: k must be an integer", **where))
        elif not all(isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) < 1e9
                     for v in (p.x, p.y, p.z)):
            issues.append(Issue(f"{p.item}: x, y, z must be finite numbers", **where))
    return issues


def _violation_params(instance: Instance, solution: Solution, params: Params, violations: list[Violation]):
    """A function giving the measured values behind a violation (`params` of `/api/check`),
    so a page can word it without parsing `message`. Computed here from the placements and `stack_measures`; the
    checker's rules are untouched. Keys by constraint:
    1 `orientation`; 2 `reason` (`unplaced`, `duplicate`, `unknown_item`); 3 none; 4 `box` {x, y, z, l, w, h} and
    `container` {type, L, W, H}; 5 `kind` (`overlap`, `gap`), `delta`; 6 `mass`, `max_mass`, `type`;
    7 `supported`, `supported_area`, `base_area`, `alpha`; 8 `on_top`, `load`, `stack`, `tiers`;
    9 `w`, `h` (item, m), `door_w`, `door_h`."""
    placed = {p.item: p for p in solution.placements}
    count: dict[str, int] = {}
    for p in solution.placements:
        count[p.item] = count.get(p.item, 0) + 1
    type_of = {u.k: instance.container_type(u.type) for u in solution.containers}
    measures = stack_measures(instance, solution) if any(v.constraint in (7, 8) for v in violations) else {}

    def box(item: str) -> dict[str, float] | None:
        p, line = placed.get(item), instance.line(line_of(item))
        if p is None or line is None or p.o not in line.allowed:
            return None
        l, w, h = line.dims(p.o)
        return {"x": p.x, "y": p.y, "z": p.z, "l": l, "w": w, "h": h}

    def of(v: Violation) -> dict[str, Any]:
        item = v.items[0] if v.items else None
        line = instance.line(line_of(item)) if item else None
        ctype = type_of.get(v.k)
        b = box(item) if item else None
        if v.constraint == 1 and item in placed:
            return {"orientation": placed[item].o}
        if v.constraint == 2 and item is not None:
            if line is None:
                return {"reason": "unknown_item"}
            return {"reason": "duplicate" if count.get(item, 0) > 1 else "unplaced"}
        if v.constraint == 4 and b and ctype:
            return {"box": b, "container": {"type": ctype.id, "L": ctype.L, "W": ctype.W, "H": ctype.H}}
        if v.constraint == 5 and len(v.items) == 2:
            a, c = box(v.items[0]), box(v.items[1])
            if a and c:
                meet = all(a[p] < c[p] + c[d] - EPS and c[p] < a[p] + a[d] - EPS
                           for p, d in (("x", "l"), ("y", "w"), ("z", "h")))
                return {"kind": "overlap" if meet else "gap", "delta": params.delta}
        if v.constraint == 6 and ctype:
            mass = sum(instance.line(line_of(p.item)).mass for p in solution.placements
                       if p.k == v.k and instance.line(line_of(p.item)) is not None)
            return {"mass": mass, "max_mass": ctype.max_mass, "type": ctype.id}
        if v.constraint == 7 and item in measures:
            m = measures[item]
            return {"supported": m.supported, "supported_area": m.supported_area, "base_area": m.base_area,
                    "alpha": params.alpha}
        if v.constraint == 8 and item in measures and line is not None:
            m = measures[item]
            return {"on_top": m.on_top, "load": line.load, "stack": m.stack, "tiers": line.tiers}
        if v.constraint == 9 and b and ctype:
            return {"w": b["w"], "h": b["h"], "door_w": ctype.door_w, "door_h": ctype.door_h}
        return {}

    return of


def check_view(req: CheckRequest) -> dict[str, Any]:
    """The payload of `/api/check`: `build_view` of the solution, plus every violation (`violations`, capped at
    `MAX_CHECK_VIOLATIONS`; `build_view` lists only the first 200). Nothing is stored."""
    if not req.delta >= 0 or not 0 <= req.alpha <= 1:
        raise BadRequest("δ phải >= 0, α phải trong [0, 1]")
    instance = lot_from_client(req.lot)
    try:
        solution = solution_from_dict({**req.solution, "params": {"delta": req.delta, "alpha": req.alpha}})
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BadRequest(f"lời giải sai định dạng: {type(exc).__name__}: {exc}") from exc
    if not isinstance(solution.containers, list) or not isinstance(solution.placements, list):
        raise BadRequest("lời giải sai định dạng: containers và placements phải là danh sách")
    issues = _solution_issues(instance, solution)
    if issues:
        raise BadRequest(f"lời giải có {len(issues)} lỗi", issues)
    params = Params(req.delta, req.alpha)
    result = check(instance, solution, params)
    view = build_view(instance, solution, {"source": "manual", "delta": req.delta, "alpha": req.alpha}, params)
    shown = result.violations[:MAX_CHECK_VIOLATIONS]
    params_of = _violation_params(instance, solution, params, shown)
    view["violations"] = [
        {"constraint": v.constraint, "k": v.k, "items": list(v.items), "message": v.message, "params": params_of(v)}
        for v in shown
    ]
    view["violations_truncated"] = len(result.violations) > MAX_CHECK_VIOLATIONS
    return view


def check_routes() -> APIRouter:
    router = APIRouter()

    @router.post("/api/check")
    def check_solution(req: CheckRequest) -> dict[str, Any]:
        """Judge a solution made by hand: no job, nothing written."""
        return check_view(req)

    return router


def base_config(mode: m.Mode) -> dict[str, Any]:
    return {
        "mode": mode.name,
        "defaults": {
            "engine": m.DEFAULT_ENGINE,
            "time_limit": mode.default_time_limit,
            "delta": m.DEFAULT_DELTA,
            "alpha": m.DEFAULT_ALPHA,
            "seed": m.DEFAULT_SEED,
        },
        "time_range": list(mode.time_range),
        # default time limit by lot size; the page picks by the container count of the bound's fleet
        "size_time_limits": [{"name": n, "max_containers": top, "seconds": sec} for n, top, sec in mode.size_limits],
        "max_items": MAX_CLIENT_ITEMS,
        "max_lines": MAX_CLIENT_LINES,
        "engines": m.engine_entries(mode),
    }


def _request_time_limit(mode: m.Mode, req: RunRequest) -> float:
    """The limit of a request: its own, else the mode's default, which in `service` follows the lot's size."""
    if req.time_limit is not None:
        return req.time_limit
    if not isinstance(req.lot, dict) or req.from_job is not None:
        return mode.default_time_limit
    fleet = lower_bound(lot_from_client(req.lot)).fleet  # the same bound `/api/lots/validate` returns
    return m.default_time_limit(sum(fleet.values()), mode)


def session_owner(request: Request) -> int | None:
    """The id of the logged-in user (`src.web.auth` puts the session in the scope), None when login is off: a job
    is then nobody's and every request sees every job."""
    user = request.scope.get("planner.user")
    return user.id if user is not None else None


def job_routes(jobs: JobManager) -> APIRouter:
    router = APIRouter()

    @router.post("/api/lots/validate")
    def validate_lot(lot: Any = Body(None)) -> dict[str, Any]:
        """Problems of a lot sent as JSON, without running it; `ok` when there are none."""
        instance, issues = read_client_lot(lot)
        out: dict[str, Any] = {"ok": not issues, "details": error_body("", "", issues)["details"],
                               "bound": None, "summary": None}
        if instance is not None and not issues:
            bound = lower_bound(instance)
            out["bound"] = {"cost": bound.cost, "binding": bound.binding, "fleet": bound.fleet}
            out["summary"] = {
                "lines": len(instance.items), "items": instance.n_items,
                "mass": sum(i.qty * i.mass for i in instance.items),
                "volume": sum(i.qty * i.volume for i in instance.items),
            }
        return out

    @router.post("/api/jobs", status_code=202)
    def start_job(req: RunRequest, request: Request) -> dict[str, Any]:
        time_limit = _request_time_limit(jobs.mode, req)
        owner = session_owner(request)
        job = jobs.start(req.engine, req.lot, req.seed, time_limit, req.delta, req.alpha, request_orient(req), owner,
                         req.from_job)
        return jobs.state(job.id, owner)

    @router.get("/api/jobs/{job_id}")
    def job_state(job_id: str, request: Request) -> dict[str, Any]:
        return jobs.state(job_id, session_owner(request))

    @router.post("/api/jobs/{job_id}/stop")
    def stop_job(job_id: str, request: Request) -> dict[str, Any]:
        owner = session_owner(request)
        return jobs.state(jobs.stop(job_id, owner).id, owner)

    @router.get("/api/jobs/{job_id}/result")
    def job_result(job_id: str, request: Request) -> dict[str, Any]:
        job = jobs.get(job_id, session_owner(request))
        if job.view is None:
            raise LotNotFound(job.error or f"lần chạy {job.status}, chưa có lời giải")
        return job.view

    @router.get("/api/jobs/{job_id}/lot.json")
    def job_lot(job_id: str, request: Request) -> dict[str, Any]:
        return jobs.lot_dict(job_id, session_owner(request))

    @router.get("/api/jobs/{job_id}/solution.json")
    def job_solution(job_id: str, request: Request) -> dict[str, Any]:
        return jobs.solution_dict(job_id, session_owner(request))

    return router


def new_app(title: str, page: Path, auth: Auth | None = None) -> FastAPI:
    """An app serving `page` at `/`, the shared viewer modules at `/static/shared`, and the one error body. With
    `auth` every request needs a login first (`src.web.auth`)."""
    app = FastAPI(title=title)
    version = shared_version()
    versioned = f"/static/{version}/shared/"
    if auth is not None:
        app.include_router(auth.router())
        app.add_middleware(AuthMiddleware, auth=auth)

    # Added after AuthMiddleware so it is the outer one: a 401 or a redirect carries the header too. `no-cache` keeps
    # ETag/Last-Modified revalidation (304) but stops a browser running old JS after a deploy.
    @app.middleware("http")
    async def revalidate_assets(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith(versioned) and response.status_code in (200, 304):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # the URL changes with the content (#100)
        elif path in ("/", "/login") or path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    app.mount("/static/shared", StaticFiles(directory=SHARED_STATIC), name="shared")
    app.mount(versioned.rstrip("/"), StaticFiles(directory=SHARED_STATIC), name="shared-versioned")
    app.include_router(check_routes())

    @app.exception_handler(WebError)
    def web_error(request: Request, error: WebError) -> JSONResponse:
        return JSONResponse(error.body(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    def bad_body(request: Request, error: RequestValidationError) -> JSONResponse:
        details = [Issue(e["msg"], field=".".join(str(p) for p in e["loc"] if p != "body")) for e in error.errors()]
        return JSONResponse(error_body("invalid_input", "yêu cầu sai định dạng", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(error.status_code, "error")
        return JSONResponse(error_body(code, str(error.detail)), status_code=error.status_code)

    @app.get("/")
    def index() -> HTMLResponse:
        return versioned_page(page, version)

    return app
