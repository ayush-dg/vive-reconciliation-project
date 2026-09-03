# FEATURE_STATUS.md — VIVE Statement Reconciliation

Plain status table across everything discussed so far, checked against the repo
(not against tracker labels or memory). Last checked: 2026-09-03.

| Feature | Status | Depends On | Notes |
|---|---|---|---|
| Base reconciliation system | **Live** | — | Sessions 1-9 complete, Phase 8 system sign-off passed. |
| ENH-001 — UI clarity fixes + multi-PDF upload | **Planned, not built** | Base system | All planning docs (brief, scope, execution plan, design-gate review) exist and check out against real code. Build sessions S1/S2 haven't run yet. 3 setup items outstanding first: create the session branches, fix a stale Claude.md version reference in the session prompts, register the new session-prompt files in `PROJECT_MANIFEST.md`. |
| ENH-002 — Fabric SQL connection fix | **Scoped, blocked on a decision** | Base system | Root cause fully diagnosed (malformed connection string + a pool that permanently locks up after one failed connect). Blocked on choosing an auth method: SQL login, Azure Managed Identity, or the service-principal method already working elsewhere in the project. |
| Deploy to Azure Container Apps | **Not scoped — ambiguous** | — | Currently deployed on Azure App Service, not Container Apps. Unclear whether this is the same request as the existing "split front/back end, not two Container Apps" note (ENH-003) or a separate ask. Needs clarification before it can be scoped. |
| Vendor-specific invoice matching | **Not scoped — needs investigation** | Base system | No evidence yet that the generic matching rule actually fails for any vendor. Needs a real test run against live statements per vendor before any fix gets written (same discipline used for the 9 extraction parsers). |
| Rules Tab (edit recon logic from the web app) | **Idea only** | Likely builds on ENH-001's screens | Exists only as a one-line note. No write-up of what "editable" would mean or touch. |
| Scheduled jobs | **Idea only** | — | No write-up exists anywhere in the project yet. |
| CI/CD pipeline | **Idea only** | — | No write-up exists anywhere in the project yet. |
