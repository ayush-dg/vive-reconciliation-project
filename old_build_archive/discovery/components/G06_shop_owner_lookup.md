## G06 — Shop Owner Routing Lookup
ID: M-042
Layer: infra
Source file: `src/shop_owners.py`

**Module** — Shop Owner Routing Lookup
**ID** — M-042
**Layer** — infra
**Primary Responsibility** — `vendor_id → shop owner` lookup for `gold_exceptions.shop_owner`, read from a placeholder config file, called at every exception-write site so a new exception always gets a routing owner at write time.

**Inputs** — `vendor_id`; `config/shop_owners.json` (loaded once, cached module-globally).

**Outputs** — A `"Name <email>"` display string, or `None` on any miss (unset vendor_id, or vendor_id not in the config).

**Public Interface** — `get_shop_owner(vendor_id) -> str | None`.

**Error Behaviour** — `_load_shop_owners()` catches `FileNotFoundError`/`json.JSONDecodeError` and falls back to an empty dict — a missing or malformed config file degrades to "every lookup misses," never a crash.

**Known Fragility**
- The config is loaded once into a module-level `_cache` and never refreshed — if `config/shop_owners.json` is edited while the app is running (e.g. a hot-reload dev workflow), the running process keeps using the stale in-memory copy until restarted.
- Explicitly a placeholder mapping — most vendor_ids are expected to miss today (config docstring, confirmed this session), so a high `None` rate is normal, not a defect — but this also means the feature is not yet operationally useful for most vendors, a state a future engineer might mistake for a bug when in fact it's the documented current state.

**Change Impact** — Called from three separate write sites across two different modules (M-017, M-034, M-003) — any signature change requires updating all three; a behavior change (e.g. caching refresh) affects routing consistency across the whole exception-write surface.

**Callers** — M-003, M-017, M-034
**Calls** — none
**Integration Points Used** — none
