"""Start the web: `python -m src.web [--host H] [--port 8000]`, then open http://127.0.0.1:8000. Login is always on:
create an account first with `python -m src.web.users seed` (docs: README)."""
from __future__ import annotations

import argparse

import uvicorn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Loading AI Planner web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    from src.llm.client import load_env
    from src.web.service.app import create_app

    load_env()  # .env: Gemini keys and model; variables already set win

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
