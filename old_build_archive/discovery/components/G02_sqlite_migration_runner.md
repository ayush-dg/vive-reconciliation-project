## G02 — SQLite Migration Runner
ID: M-038
Layer: infra
Source file: `src/lakehouse/migrations.py`

**Module** — SQLite Migration Runner
**ID** — M-038
**Layer** — infra
**Primary Responsibility** — Applies numbered SQL migration files from `migrations/` in ascending order, tracking applied state in `schema_version`, one transaction per file.

**Inputs** — A live SQLite connection (`conn`); the `migrations/` directory's `NNN_description.sql` files.

**Outputs** — Schema changes applied to the connected database; one row per applied migration in `schema_version`.

**Public Interface** — `apply_pending_migrations(conn) -> list[(version_str, filename)]`, `MigrationError` (exception class).

**Error Behaviour** — Raises `MigrationError` on the first failing migration — wraps the original exception, rolls back that migration's transaction, and does not attempt any later migration in the same call. Also raises `MigrationError` if two files share the same numeric prefix (duplicate migration number).

**Known Fragility**
- `_split_statements()`'s comment-stripping (`_strip_line_comments()`) is explicitly "not string-literal-aware" — safe only because this project's actual migration files never put `--` inside a string literal. A future migration file that did (e.g. a default value containing `--`) would have part of its SQL silently truncated as a "comment."
- Statement splitting is a naive `;`-split with no awareness of trigger bodies, stored procedures, or any construct containing an embedded semicolon — explicitly documented as "not a general-purpose SQL parser," fine for this project's plain CREATE/ALTER TABLE migrations, but a hard ceiling on what kind of migration this runner could ever safely apply.
- Migration discovery sorts by the *numeric* prefix value, not lexicographic filename order — this is the correct choice (prevents `010` sorting before `002`) but means a hand-renamed file that shifts a number could reorder migration application relative to what a naive directory listing would suggest.

**Change Impact** — The sole schema-evolution mechanism for the SQLite backend — any bug here risks either a partially-applied migration (mitigated by the per-file transaction) or migrations applying out of order relative to their intended dependency sequence.

**Callers** — M-016, M-050
**Calls** — none (operates directly on the connection object passed in)
**Integration Points Used** — none directly (caller supplies the connection)
