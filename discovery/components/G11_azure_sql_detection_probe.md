## G11 — Azure SQL Detection Probe
ID: M-047
Layer: infra
Source file: `check_subprocess.py`

**Module** — Azure SQL Detection Probe
**ID** — M-047
**Layer** — infra
**Primary Responsibility** — Ad hoc debugging script: spawns a subprocess that imports `_using_azure_sql()` (M-037) and prints whether it resolves true/false, plus whether `AZURE_SQL_SERVER` is actually set in that subprocess's environment.

**Inputs** — None beyond the ambient environment `.env`/`AZURE_SQL_SERVER` state.

**Outputs** — Stdout/stderr from the spawned subprocess, printed by the parent script.

**Public Interface** — None exported; script-only.

**Error Behaviour** — None — a direct `subprocess.run()` call with no timeout or error branch; the parent script always prints whatever stdout/stderr came back, truncating stderr to 300 characters.

**Known Fragility** — Exists specifically to answer "does a subprocess actually see the same `AZURE_SQL_SERVER` env var the parent process does" — the same class of environment-propagation question `Rule 4`'s explicit-`.env`-path discipline (see `docs/Claude.md`) was written to prevent from silently going wrong. A genuinely useful diagnostic, but its no-timeout `subprocess.run()` call could hang indefinitely if the spawned Python process ever blocked.

**Change Impact** — None — diagnostic-only.

**Callers** — none (developer-invoked)
**Calls** — M-037 (`_using_azure_sql`, imported inside a spawned subprocess, not an in-process call)
**Integration Points Used** — none directly
