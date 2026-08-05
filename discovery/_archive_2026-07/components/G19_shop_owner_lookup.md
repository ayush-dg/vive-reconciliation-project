## G19 — shop owner routing lookup
ID: M-048
Layer: infra
Source file: src/shop_owners.py
Added: 2026-07-25 scoped BCE refresh (module built 2026-07-24, Step 8, routing/aging)

**Module** — shop owner routing lookup
**ID** — M-048
**Layer** — infra
**Primary Responsibility** — `vendor_id -> shop owner` display-string lookup for `gold_exceptions.shop_owner` (migration `009_add_routing_aging.sql`), backed by a placeholder config file (`config/shop_owners.json`) pending VIVE's real vendor→shop-owner mapping.

**Inputs** — `get_shop_owner(vendor_id) -> str | None` — a single `vendor_id` (or falsy value).

**Outputs** — `"Name <email>"` if both fields are present in the config for that `vendor_id`; just the name or just the email if only one is present; `None` if `vendor_id` is falsy or has no entry in `config/shop_owners.json` at all. No side effects — this module never writes anything, only reads its own config file (lazily, cached module-globally after first load).

**Public Interface**
- `get_shop_owner(vendor_id) -> str | None` — the only public function.
- `_load_shop_owners() -> dict` (private) — lazy, process-lifetime-cached load of `config/shop_owners.json`.

**Error Behaviour** — `_load_shop_owners()` catches both `FileNotFoundError` and `json.JSONDecodeError`, falling back to an empty dict — a missing or malformed config file degrades to "every lookup returns `None`," never a crash. Every call site (see Callers) already treats a `None` shop_owner as an expected, valid outcome (most `vendor_id`s are not yet in the placeholder mapping), so this failure mode is indistinguishable from the normal "not yet mapped" case at every current call site.

**Known Fragility**
- **`config/shop_owners.json` is explicitly a placeholder — most `vendor_id`s are expected to miss** — this is stated directly in the module's own docstring, not inferred. `get_shop_owner()` returning `None` for a given vendor today is the expected common case, not evidence of a bug; this will change in behavior (more hits) as VIVE provides the real mapping, with no code change required on this module's side.
- **The config is cached at first load and never refreshed** (`_cache` is a module-global, set once) — updating `config/shop_owners.json` on disk while the web app or a pipeline subprocess is already running would not take effect until that process restarts. Each pipeline run is its own subprocess (see M-013), so in practice this mostly self-resolves per-job; the long-lived web app process (M-009) would need an explicit restart to pick up a config change, which is not documented anywhere as an operational requirement.
- **No validation of the config file's shape** — a `config/shop_owners.json` entry missing both `name` and `email` keys (rather than being absent from the file entirely) silently returns `None` from the final `return name or email or None` line, the same as a genuinely-missing vendor_id. Not a defect given the placeholder's current informal shape, but worth noting if this config is ever machine-generated rather than hand-maintained.

**Change Impact** — Called from three independent Gold-write sites (`src/matching/engine.py:run_matching()`, `notebooks/01_document_intake.py:write_skip_exception()`, `web/queries.py:action_review_item()`) specifically so a new `gold_exceptions` row always gets a `shop_owner` looked up at write time, not backfilled later — adding a fourth `gold_exceptions` write site anywhere in the codebase would need to call this too, or that row would permanently lack routing information (nothing backfills it after the fact).

**Callers** — M-036 (`src/matching/engine.py:run_matching()`), M-014 (`notebooks/01_document_intake.py:write_skip_exception()`), M-011 (`web/queries.py:action_review_item()`)
**Calls** — none (pure file read, no DB/network access)
**Integration Points Used** — none directly
