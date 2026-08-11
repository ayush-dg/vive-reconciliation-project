# VIVE Statement Reconciliation — Service Provisioning Order

This is the build sequence for the Azure and Microsoft Fabric services in the architecture, ordered by dependency — each phase needs the ones before it to exist first.

---

## Phase 1 — Foundation and identity

Nothing else can be built without this. Every other service authenticates against what's set up here.

- Resource Group / subscription structure
- Microsoft Entra ID app registrations (the managed identities every later service will use)
- Azure Key Vault
- VNet + private endpoints

---

## Phase 2 — Fabric data platform

Needs identity and networking from Phase 1 before Fabric items can be provisioned with private access.

- Fabric capacity (F-SKU) + workspaces (dev / test / prod)
- Fabric Lakehouse — Bronze
- Fabric Warehouse — Silver
- Fabric Warehouse — Gold
- SQL database in Fabric — Recon

---

## Phase 3 — Compute and AI foundation

Needs Key Vault (for secrets) and the Fabric workspace (for later integration) from Phases 1–2.

- Azure Blob Storage (raw PDFs)
- Azure Container Registry
- Azure Container Apps environment
- Azure App Service plan
- Azure AI Foundry + Claude model deployment

---

## Phase 4 — Core application services

Needs the compute environments, storage, and Fabric items from Phases 2–3 to deploy into.

- **Document Intake Service** — Blob Storage + Azure SQL Database (document registry)
- **Extraction Worker** — Container Apps, calls Claude via Azure Foundry
- **Run Management Service** — App Service (Statement Inbox, Create Run, Capture Run Context, Work Items)
- **Reconciliation Service** — Container Apps (Processing Worker + Reconciliation Engine), reads Silver, writes Recon
- **Review Service** — App Service (Human Review UI, Audit Ledger)

---

## Phase 5 — Orchestration layer

Needs the application's API surface (Phase 4) to exist before it has anything to call — n8n is orchestration only, no business logic.

- n8n deployment (VM or Container Apps)
- Wire n8n workflows to the Run Management API endpoints

---

## Phase 6 — Ingestion pipelines

Needs Bronze (Phase 2) as a landing target and source credentials already in Key Vault (Phase 1).

- Fabric Data Pipeline — NetSuite pull (read-only)
- Fabric Data Pipeline — CCC pull

---

## Phase 7 — Monitoring, backup, exports

Wired in last since these observe or consume services that already need to be running.

- Azure Monitor + Log Analytics workspace, wired to every service above
- Azure Backup (Blob, SQL databases, Fabric items)
- Power BI (connected to Gold)
- SharePoint / Files export
- Email / Teams notification connectors

---

## Why this order

1. **Identity and secrets first** — nothing else can authenticate without Entra ID and Key Vault in place.
2. **Storage and Fabric items before compute** — a service can't read or write to a Lakehouse, Warehouse, or SQL database that doesn't exist yet.
3. **Compute environments before individual services** — the Container Apps environment and App Service plan are the hosting shells; individual services deploy into them, not the other way around.
4. **The application's APIs before orchestration** — n8n has nothing to trigger until the Run Management API exists to call.
5. **Monitoring, backup, and exports last** — these instrument or consume things that already need to be live; standing them up earlier would mean pointing them at nothing.
