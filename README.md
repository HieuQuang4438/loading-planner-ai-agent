# Loading AI Planner

A web app that plans how to load cargo into shipping containers. An AI agent (Gemini) reads the messy documents a shipment comes with — Excel packing lists, PDF specs, photos of carton labels — and turns them into one confirmed shipment, with the source of every value; an optimisation engine then lays the cargo out in 3D, either at the lowest freight cost or as much cargo as a given set of containers holds.

Live demo: <https://loading-ai-planner.duckdns.org> (accounts are made by an admin; ask for one).

## Why

Shipment data is scattered and inconsistent: the same SKU has two heights in two files, a net mass in one and a gross mass in another, a quantity counted in pallets but sized as cartons. Tools that use AI to read documents tend to pick one value silently or fill a missing mass with a guess, and a solver fed wrong data returns a plan that looks valid and cannot be loaded.

## How it works

- **The agent never guesses.** It extracts every field with its source (file, sheet and row, page), flags what is missing or contradicts another document, and asks. A field the user has not confirmed stays `needs_review`, and the engine does not run until none is left.
- **The LLM does not decide what is valid.** Units, types and required fields are checked in the backend, not in the prompt; every plan goes through an independent checker (geometry, support, weight, stacking) before it is shown.
- **Two questions, two modes.**
  - *A — lowest cost:* the shipment is fixed; the engine picks the container types and counts with the lowest total freight (set cover over single-container packings, column generation, ALNS).
  - *B — most cargo:* the containers are fixed; the engine loads as much as fits in the user's priority order and reports what is left.
  Both are compared with a simple baseline, and mode A with a lower bound on the cost.
- **Chat with controlled actions.** The user asks in Vietnamese ("what if we drop SKU-B?", "add 50 cartons"); the agent proposes a change, the user confirms it with a button, and the engine reruns.

## Stack

Python 3.12, FastAPI, SQLite; Gemini through the Google GenAI SDK (structured output, function calling); vanilla JavaScript and three.js for the UI and the 3D viewer; Docker Compose behind Caddy for the deployment. The packing engine, the checker, the login and the 3D viewer come from an earlier project of the author; the agent, mode B and the shipment UI are new here.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate                # Windows; source .venv/bin/activate elsewhere
pip install -r requirements-dev.txt   # the app alone needs requirements.txt
python -m pytest                      # about 3 minutes: many tests solve for real under a time limit
```

The web app always asks for a login. Put this in `.env` (see `.env.example` for the Gemini settings):

```
PLANNER_DB=data/app.db
PLANNER_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
PLANNER_ADMIN_NAME=admin
PLANNER_ADMIN_PASSWORD=<a password>
GOOGLE_API_KEY=<a Google AI Studio key>
```

Then `.\scripts\run_web.ps1` (PowerShell), or `docker compose up -d --build`, and open <http://localhost:8000>. More users: `python -m src.web.users add <name>`. The session cookie is `Secure`, so use `http://localhost` or HTTPS.

The demo documents in `data/probe/` are simulated (made-up company, products and freight rates) and hide eight traps the agent must catch; `python -m scripts.gen_demo` regenerates them.

## Documentation

In Vietnamese, under [`docs/`](docs/):

- [Product brief](docs/product/brief.md): problem, solution, principles, scope.
- [Architecture](docs/product/architecture.md), [agent](docs/product/agent.md), [UI](docs/product/ux.md).
- [Engine](docs/product/engine/README.md): mode A, the baseline, the measurements, the algorithm specs.
- [Evaluation](docs/product/eval.md) of the agent and the engine, bad results included.
- [Decisions](docs/adr/), [API](docs/reference/api.md), [data model](docs/reference/data-model.md), [constraints](docs/reference/constraints.md).

## License

[MIT](LICENSE).
