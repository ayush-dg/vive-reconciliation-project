# UI_SURFACE.md — VIVE Statement Reconciliation (Bounded First Build)
## Version: v1.4 · 2026-08-28

## Amendment Log
| Date | Screen/Section | Change | Reason |
|---|---|---|---|
| 2026-08-28 | Exception Detail | Amount-mismatch NetSuite value now sourced from `recon.exception.evidence` (captured at match time), not `silver.reference_snapshot` | EXECUTION_PLAN.md Session 4 removed — NetSuite/CCC ingestion is externally owned, no Silver snapshot layer is built by this project (ARCHITECTURE.md D-M) |
| 2026-08-27 | Upload | Vendor removed as a form field — app identifies vendor during extraction, not the user at upload; uploaded-document list shows "Identifying…" until extraction completes | Resolves gap #3, per ARCHITECTURE.md D-L amendment (PHASE4_GATE_RECORD.md Finding 2) |
| 2026-08-27 | Home, Document Detail | Data-source references updated `bronze.document`/`bronze.extraction_attempt` → `extracted.document`/`extracted.extraction_attempt` | ARCHITECTURE.md D-J — VIVE intake data relocated to new `extracted` schema, separate from `bronze` (which hosts live NetSuite data) |
| 2026-08-26 | Home | Added reconciled/not-reconciled counts to Summary stats; added Reconcile action per row | New requirement — manual reconcile trigger + outcome visibility |
| 2026-08-26 | Home | "View statement" now resolved — navigates to new Document Detail screen | Resolves prior gap #2 |
| 2026-08-26 | Upload | Added per-row Extract action, separate from Upload submit | D-I — upload and extraction are separate explicit acts |
| 2026-08-26 | Exceptions | Removed "possible duplicate/correction" exception type | D-H amended — re-uploads are version-chained automatically, never reach Exceptions |
| 2026-08-26 | Exception Detail | Added amount-mismatch drill-down (statement value vs. Fabric/NetSuite source value) | New requirement — visibility into source-system data for mismatches |
| 2026-08-26 | New screen: Document Detail | Added — extracted rows + extraction-method summary (OCR/Claude/pdfplumber counts) | Resolves prior gap #2; new reporting requirement |
| 2026-08-17 | Navigation | Sidebar confirmed from reference mockup; Schedule excluded, Home retained as landing/report | Scope resolution |
| 2026-08-17 | — | Initial draft | Phase 1 UI Discovery |
| 2026-08-17 | All screens | Finalized with TBD markers on unresolved gaps, deferred with engineer acknowledgement | Engineer requested finalization before full gap resolution |
| 2026-08-17 | Data baseline | Confirmed Migrated only, no Seeded component — all data in cloud | Engineer clarification; SEED_DATA.md production skipped per PBVI-011 conditional |
| 2026-08-17 | Home | Added status badge (Processing/Retrying/Failed/Reconciled) to Uploaded Statements panel | Resolved Phase 2 Step 0 touch-point gap — retry/arithmetic-gate state now has screen coverage |
| 2026-08-17 | All screens | Applied engineer-supplied defaults for 10 of 14 gaps (stats set, refresh pattern, save behavior, pagination, search, session expiry, error style, loading style, toast position) | Engineer opted for reasonable defaults rather than further discovery rounds |

---

## Global Elements

### Navigation
- Type: Sidebar
- Present on: All authenticated screens
- Items: Home, Upload, Exceptions (Admin group present but disabled/non-functional)
- Role-conditional items: NONE — single user type

### Authentication Shell
- Logout: Sidebar footer — user name/role block, click-to-logout
- Session expiry behaviour: Standard idle timeout (30 min) — redirect to login on expiry
- Post-login redirect: Home
- Post-logout redirect: Sign-in screen

### Back Navigation
- Mechanism: Browser back
- Screens with explicit back controls: Exception Detail has an explicit "Back to list" action

### Breadcrumbs
- Present: N

### Global Error Boundary
- Behaviour: Inline message, no full-page redirect
- User action available: Retry

### App-level Loading
- Behaviour: Simple spinner (skeleton loaders deferred as later-phase polish)
- Applies to: Initial load + route transitions

### Toast / Notification System
- Present: Y
- Position: Bottom-right (standard convention)
- Used for: Success confirmations (upload received) + error alerts (extraction failed, arithmetic gate failure)

---

## Screen Inventory

| Screen | Type | Route | Journey | Roles | Auth Required |
|---|---|---|---|---|---|
| Sign In | Form | `/login` (TBD) | Authentication | All | N |
| Home (Reports) | Dashboard | `/home` (TBD) | Landing + view uploaded statements and results | All | Y |
| Upload | Form | `/upload` (TBD) | Statement intake | All | Y |
| Document Detail | Detail | `/documents/:id` (TBD) | Drill into a document's extracted rows + extraction-method summary | All | Y |
| Exceptions | List | `/exceptions` (TBD) | Review unmatched/ambiguous lines | All | Y |
| Exception Detail | Detail | `/exceptions/:id` (TBD) | Drill into a single exception's evidence | All | Y |

**Known limitation (acknowledged, not a gap to close):** No screen surface exists for matched (non-exception) StatementLines or Matches. A user can see that a statement was processed and see what didn't match, but cannot confirm what did match or why. Parking-lot item for BCE.

---

## Screen Specifications

## Sign In
**Type:** Form
**Route:** `/login` (TBD)
**Journey:** Authentication
**Roles:** All (unauthenticated)
**Trigger:** Direct navigation (unauthenticated root)
**Auth required:** N

### Data Displayed
None.

### Actions
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| Sign in | Screen | Form submit | Always | API call → Home on success |
| Sign in with company SSO | Screen | Button | TBD — is SSO actually offered, or ahead of the unresolved auth mechanism? | Navigation to SSO flow (TBD) |

### States
| State | Trigger | What Renders |
|---|---|---|
| Loading | Auth request in progress | Button disabled, simple spinner (per global default) |
| Error | Invalid credentials / auth failure | Inline error message under form |
| Populated | Default | Standard sign-in form |

### Form Fields
| Field | Type | Required | Conditional On | Validation Message |
|---|---|---|---|---|
| Username/Email | Text | Y | NONE | "Enter your username" |
| Password | Password | Y | NONE | "Enter your password" |

- Save behaviour: Navigate to Home on success
- Cancel behaviour: N/A

### Async Behaviour
- Pattern: Load-once
- Scope: Whole screen

---

## Home (Reports)
**Type:** Dashboard
**Route:** `/home` (TBD)
**Journey:** Landing + view uploaded statements and their results
**Roles:** All
**Trigger:** Post-login redirect, or nav item click
**Auth required:** Y

### Data Displayed
| Section | Entity / Field | Source | Notes |
|---|---|---|---|
| Summary stats | Documents processed, open exceptions, extraction failures, **reconciled count, not-reconciled count** (added 2026-08-26) | Computed from `recon`/bronze records | Reconciled/not-reconciled counts added per new reporting requirement |
| Uploaded Statements panel | Document[] (vendor, period, status, upload date) + status badge | `extracted.document` + extraction attempt state | Status badge: "Processing" / "Retrying (N/2)" / "Failed — see Exceptions" / "Reconciled". Resolves Phase 2 Step 0 touch-point gap (retry/arithmetic-gate state) |

### Actions
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| View statement | Row | Click/Link | Always | **Resolved 2026-08-26** — navigates to Document Detail (`/documents/:id`) |
| Extract | Row | Click/Button | Document registered, not yet extracted (D-I) | Triggers extraction service for that document; status moves to "Processing" |
| Reconcile | Row | Click/Button | Document extracted, not yet reconciled | Triggers manual matching invocation (OD1) for that document; status updates to "Reconciled" or exceptions appear |

### States
| State | Trigger | What Renders |
|---|---|---|
| Empty (no data) | No statements uploaded yet | "No statements uploaded yet" + link to Upload |
| Loading | Data fetch in progress | Simple spinner (per global default) |
| Error | API failure | Inline message, Retry action (per global default) |
| Populated | Statements exist | Stat cards + statement list |

### Panels
| Panel Name | Data Source | Empty State | Refresh | Drill-down Target |
|---|---|---|---|---|
| Summary stats | Computed | "No data yet" | Manual refresh only | NONE |
| Uploaded Statements | `extracted.document` | "No statements uploaded yet" | TBD — polling vs. manual | Document Detail (`/documents/:id`, resolved 2026-08-26) |

### Async Behaviour
- Pattern: Load-once — manual refresh only, no polling infra for this build
- Scope: Whole screen

---

## Upload
**Type:** Form
**Route:** `/upload` (TBD)
**Journey:** Statement intake
**Roles:** All
**Trigger:** Nav item click
**Auth required:** Y

### Data Displayed
None for the drop-zone form itself. **Added 2026-08-26:** an uploaded-but-not-yet-extracted
list below the drop-zone, showing each registered document with a per-row Extract action
(D-I — upload and extraction are separate acts).

### Actions
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| Upload | Screen | Form submit / drop | Always | API call → document registered, content-hash checked. Vendor is not known yet at this point (identified during extraction, per ARCHITECTURE.md D-L amendment) — the vendor/period version-chaining check (D-H) runs post-extraction, not here |
| Extract | Row | Click/Button | Document registered, not yet extracted (added 2026-08-26) | Triggers extraction service (Session 3); does NOT happen automatically on upload |

### States
| State | Trigger | What Renders |
|---|---|---|
| Loading | Upload in progress | Simple spinner (per global default) |
| Error | Upload failed, or identical-hash reject | Inline error |
| Populated | Default drop-zone | Drop target + browse button + uploaded-document list with Extract actions |

### Form Fields
| Field | Type | Required | Conditional On | Validation Message |
|---|---|---|---|---|
| Statement PDF | File | Y | NONE | "Select a PDF statement" |
| Legal Entity | Dropdown | TBD — real architectural gap: v3.3 tags `legal_entity_id` at document level but doesn't specify who/what sets it | NONE | — |

**Vendor is not a form field (resolved 2026-08-27, per ARCHITECTURE.md D-L amendment):**
the app identifies the vendor during extraction, not the user at upload. The uploaded-
document list (below the drop-zone) and Home's Uploaded Statements panel show vendor as
"Identifying…" until extraction completes and populates it.

- Save behaviour: Stay on page with confirmation toast (safer than silent navigate-away for financial-data upload)
- Cancel behaviour: N/A

### Async Behaviour
- Pattern: Load-once for upload action; extraction/matching happen out-of-band
- Scope: Whole screen

---

## Document Detail [NEW 2026-08-26]
**Type:** Detail
**Route:** `/documents/:id` (TBD)
**Journey:** Drill into a document's extracted rows + extraction-method summary
**Roles:** All
**Trigger:** Home's "View statement" row click
**Auth required:** Y

### Data Displayed
| Section | Entity / Field | Source | Notes |
|---|---|---|---|
| Header | Vendor, period, status badge | `extracted.document` + Task 2.3's status computation | Same status badge values as Home |
| Extraction summary strip | Counts by extraction provider (`python_library_pdfplumber`, `claude_sonnet`, `pdfplumber_fallback`) | `extracted.extraction_attempt` (Task 3.5's summary endpoint) | pdfplumber_fallback labeled plainly as "via OCR fallback" for the AP user |
| Extracted rows table | StatementLine[] (invoice ref, amount, confidence, provider) | Silver | Confidence shown as informational metadata only — no pass/fail styling, since it's no longer a gate (G2 amended) |

### Actions
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| Extract | Screen | Click/Button | Document registered, not yet extracted | Same action as Upload/Home's Extract (Task 2.4) |
| Reconcile | Screen | Click/Button | Document extracted, not yet reconciled | Same action as Home's Reconcile |
| Back to Home | Screen | Link/button | Always | Navigation to Home |

### States
| State | Trigger | What Renders |
|---|---|---|
| Loading | Data fetch in progress | Simple spinner (per global default) |
| Error | Document not found / API failure | Inline message, Retry action (per global default) |
| Not yet extracted | Document registered only | Extraction summary strip and rows table empty; Extract action prominent |
| Populated | Extraction complete | Summary strip + rows table |

### Async Behaviour
- Pattern: Load-once
- Scope: Whole screen

---

## Exceptions
**Type:** List
**Route:** `/exceptions` (TBD)
**Journey:** Review unmatched/ambiguous lines
**Roles:** All
**Trigger:** Nav item click
**Auth required:** Y

### Data Displayed
| Section | Entity / Field | Source | Notes |
|---|---|---|---|
| Main list | Exception[] (vendor, invoice ref, amount, exception type, date) | `recon.exception` | **Amended 2026-08-26:** "possible duplicate/correction" removed as an exception type — D-H's amended version-chaining resolves re-uploads automatically, before they ever reach Exceptions |

### Actions
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| View detail | Row | Link | Always | Navigation to Exception Detail |

### States
| State | Trigger | What Renders |
|---|---|---|
| Empty (no data) | No exceptions exist | "No exceptions — all statements reconciled cleanly" |
| Empty (filtered) | Filter/search returns zero | "No matching exceptions" |
| Loading | Data fetch in progress | Simple spinner (per global default) |
| Error | API failure | Inline message, Retry action (per global default) |
| Populated | Exceptions exist | Table/list rendering |

### Async Behaviour
- Pattern: Load-once — manual refresh only
- Scope: Whole screen

### List Configuration
| Column | Field | Sortable | Filterable | Default Sort |
|---|---|---|---|---|
| Vendor | vendor_name | Y | Y | — |
| Statement | document_id / period | Y | Y | — |
| Invoice Ref | invoice_number | Y | N | — |
| Amount | amount | Y | N | DESC |
| Exception Type | exception_type | N | Y | — |
| Date | created_at | Y | N | DESC |

- Pagination: Paginated, page size 50
- Search: Y — fields: Vendor, Invoice Ref (matches D-A's flat-list scope; richer search is BCE-scope)
- Bulk selection: N — confirmed, no bulk actions in this build

---

## Exception Detail
**Type:** Detail
**Route:** `/exceptions/:id` (TBD)
**Journey:** Drill into a single exception's evidence
**Roles:** All
**Trigger:** Exceptions list row click
**Auth required:** Y

### Data Displayed
| Section | Entity / Field | Source | Notes |
|---|---|---|---|
| Main | Exception full record | `recon.exception` | — |
| Related | Corroborating evidence (CCC RO confirmation, v3.3 §11.4) | `silver.ccc_ro` | Present only when CCC evidence exists |
| Related | Source statement line / extraction record | Bronze/Silver | Raw extracted line this exception traces to |
| Related — **amount-mismatch only (added 2026-08-26)** | Expandable/dropdown: statement value vs. NetSuite/Fabric source value for the invoice | `recon.exception.evidence` (captured at match time, per EXECUTION_PLAN.md Task 5.2 amended 2026-08-28 — never a live re-query) | Collapsed by default; shown only when `exception.category = amount_mismatch` |

### Actions
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| Back to list | Screen | Link/button | Always | Navigation to Exceptions |

No approve/dispute actions — correctly absent, per D-C.

### States
| State | Trigger | What Renders |
|---|---|---|
| Loading | Data fetch in progress | Simple spinner (per global default) |
| Error | Exception not found / API failure | Inline message, Retry action (per global default) |
| Populated | Default | Full detail view |
| No corroborating evidence | CCC evidence absent | Related panel shows "No CCC confirmation available" |
| Amount-mismatch drill-down (added 2026-08-26) | `exception.category = amount_mismatch` | Expandable section showing statement value alongside the Fabric/NetSuite source value |

### Async Behaviour
- Pattern: Load-once
- Scope: Whole screen

---

## UNRESOLVED UI GAPS — carried to Interrogate Missing Information

10 of 14 original gaps resolved via engineer-supplied defaults (2026-08-17); gap #2
resolved 2026-08-26; gap #3 resolved 2026-08-27. Two remain open — real architectural
questions (data provenance), not styling choices, deliberately not defaulted:

1. Screen: Sign In — Is SSO actually offered, or ahead of the unresolved auth mechanism
   (still open from Interrogate)?
2. ~~Screen: Home — "View statement" action target~~ **RESOLVED 2026-08-26** — navigates
   to the new Document Detail screen.
3. ~~Screen: Upload — Vendor field: user-selected at upload, or auto-resolved during
   extraction?~~ **RESOLVED 2026-08-27** — auto-resolved during extraction, per
   ARCHITECTURE.md D-L amendment (PHASE4_GATE_RECORD.md Finding 2). Not a form field;
   shown as "Identifying…" until extraction populates it.
4. Screen: Upload — Legal Entity field: user-selected, or inferred? Real architectural
   gap — v3.3 tags `legal_entity_id` at the document level but doesn't specify who/what
   sets it.

## Engineer Sign-Off

**Decision owner:** Vaishali
**Date:** 2026-08-17
**Signature / confirmation:** [x] I confirm this UI surface is accurate to my decision, with unresolved gaps above explicitly deferred and acknowledged.

**Data baseline confirmed:** Migrated only — no Seeded component. All data resides in cloud (Azure/Fabric). SEED_DATA.md production is skipped per the PBVI-011 conditional ("[Run only if data baseline = Seeded]").

---

## Final Sign-Off (2026-08-27)

**Decision owner:** Vaishali
**Date:** 2026-08-27
**Status:** SIGNED OFF.

Changes across v1.0–v1.2 confirmed: Document Detail screen added (resolves gap #2); Home
gains Reconcile action + reconciled/not-reconciled counts; Upload gains a separate Extract
action (D-I); Exceptions/Exception Detail updated for D-H's version-chaining (duplicate
exception type removed) and the amount-mismatch drill-down; data-source references
updated for the `extracted` schema (D-J).

**Signature / confirmation:** [x] I confirm this UI surface, including all amendments
through v1.2, is accurate to my decision and I authorize proceeding to Phase 6.
