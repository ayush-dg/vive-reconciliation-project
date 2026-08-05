## G04 — web launcher
ID: M-012
Layer: infra
Source file: web/start.py

**Module** — web launcher
**ID** — M-012
**Layer** — infra
**Primary Responsibility** — Local dev convenience script: launches `uvicorn web.app:app --reload --port 8000` from the project root.

**Inputs** — None (no CLI args parsed).

**Outputs** — Spawns a `uvicorn` subprocess; no return value used (script is a thin `if __name__ == "__main__"` wrapper).

**Public Interface** — None exported; script-only, not imported by any other module.

**Error Behaviour** — None — a `subprocess.run()` failure (e.g. `uvicorn` not installed) would raise `FileNotFoundError`/`CalledProcessError` uncaught, printing a Python traceback to the console. Acceptable for a local dev launcher.

**Known Fragility** — Not used in production (per `startup.sh`, which invokes `uvicorn` directly rather than through this script) — this module exists purely for local development convenience.

**Change Impact** — None beyond itself; not imported anywhere.

**Callers** — none (invoked directly by a developer, `python web/start.py`)
**Calls** — none (spawns `uvicorn` as an external subprocess, not a Python import)
**Integration Points Used** — none
