## B04 — Uvicorn Launcher
ID: M-004
Layer: serving
Source file: `web/start.py`

**Module** — Uvicorn Launcher
**ID** — M-004
**Layer** — serving
**Primary Responsibility** — CLI entry point that launches `uvicorn web.app:app --reload --port 8000` from the project root.

**Inputs** — None (no arguments; hardcoded command).

**Outputs** — A running uvicorn process serving M-001's `app`.

**Public Interface** — None exported; `if __name__ == "__main__":` script only, invoked as `python web/start.py`.

**Error Behaviour** — Any failure (port in use, import error in M-001) propagates as the subprocess's own non-zero exit and stderr output; this script itself has no error handling.

**Known Fragility** — `--reload` is hardcoded on — appropriate for dev, not verified as guarded for a production launch path (production per `startup.sh` instead invokes uvicorn directly without this script, so the risk is contained to whoever runs this file specifically).

**Change Impact** — Isolated; nothing else calls this module. Changing the port/reload flag only affects local dev workflow, not `startup.sh`'s production path.

**Callers** — none (developer-invoked CLI entry point)
**Calls** — M-001 (indirectly, via uvicorn's own import of `web.app:app`)
**Integration Points Used** — none
