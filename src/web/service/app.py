"""The web app: login always on (accounts made by an admin, docs/product/brief.md §3), the user's lots with their
documents, chat and runs kept in `app.db`, jobs on lots sent as JSON."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from src.llm.client import LLM, ChatLLM, Gemini
from src.web.api import base_config, job_routes, new_app
from src.web.auth import Auth, AuthConfig
from src.web.job_manager import JobManager
from src.web.lotstore import LotStore
from src.web.memguard import job_limit_mb
from src.web.mode import SERVICE
from src.web.runstore import KEEP_DAYS, SqliteStore
from src.web.service.chat import chat_routes
from src.web.service.lots import Reader, lot_routes
from src.web.service.runs import run_routes

PAGE = Path(__file__).parent / "static" / "index.html"


def chat_model() -> ChatLLM:
    """The chat's model: `GEMINI_CHAT_MODEL`, else the one that reads documents (choice 6A)."""
    return Gemini(model=os.environ.get("GEMINI_CHAT_MODEL") or None)


def create_app(auth_config: AuthConfig | None = None, llm: Callable[[], LLM] = Gemini,
               chat_llm: Callable[[], ChatLLM] = chat_model) -> FastAPI:
    """`auth_config`: None reads it from the environment (`PLANNER_DB`, `PLANNER_ORIGINS`), once, here. `llm` / `chat_llm`
    make the model clients, on the first document read / chat turn (the keys are read then)."""
    auth = Auth(auth_config or AuthConfig.from_env())
    store = SqliteStore(auth.config.db_path, int(os.environ.get("PLANNER_RUN_DAYS") or KEEP_DAYS))
    jobs = JobManager(store, SERVICE, mem_limit_mb=job_limit_mb())  # read once, here
    app = new_app("Loading AI Planner", PAGE, auth)
    app.include_router(job_routes(jobs))
    app.include_router(run_routes(store))
    lots = LotStore(auth.config.db_path)
    app.include_router(lot_routes(lots, store, jobs, Reader(lots, llm)))
    app.include_router(chat_routes(lots, store, jobs, chat_llm))

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return base_config(SERVICE)

    return app
