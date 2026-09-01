# UI_SURFACE.md — VIVE Statement Reconciliation (Bounded First Build)
## Version: v1.5 · 2026-09-01

## Amendment Log
| Date | Screen/Section | Change | Reason |
|---|---|---|---|
| 2026-09-01 | Exceptions, Exception Detail | Full architectural rewrite — flat all-vendor list + separate `/exceptions/:id` detail page replaced with a vendor-grouped two-pane master-detail view; new resolution workflow (Mark resolved / Flag for vendor / Skip + note) | Engineer-supplied Figma mockups; see ARCHITECTURE.md D-A's 2026-09-01 amendment for the D-C tension this introduces |
| 2026-09-01 | Home | "Uploaded Statements panel" renamed "Most recent uploads"; status badge display softened (Success/Done) independent of the underlying badge; "Show exceptions →" link added for a reconciled-with-exceptions document | Engineer-directed UX simplification |
| 2026-09-01 | Upload | Legal Entity field removed — no longer TBD/user-selected, auto-assigned a single fixed default | Resolves the TBD gap this doc previously left open; ARCHITECTURE.md D-F's 2026-09-01 resolution note |
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
| Exceptions | List + inline Detail | `/exceptions` (vendor landing), `/exceptions/:vendorSlug` (two-pane detail) — **rewritten 2026-09-01**, replaces the prior separate List/Detail rows | Review unmatched/ambiguous lines, grouped by vendor; resolve, flag, or skip inline | All | Y |

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
| Uploaded Statements panel | Document[] (vendor, period, status, upload date) + status badge | `extracted.document` + extraction attempt state | **Amended 2026-09-01:** underlying badge values are now `Processing \| Extracted \| Reconciling \| Retrying \| Failed \| Reconciled` (see EXECUTION_PLAN.md Task 2.3's amendment). Home displays its own softened mapping, not the raw badge: "Success" once extraction succeeds, "Done" once reconciliation has run at all — including when it left open exceptions, alongside a "Show exceptions →" link to that vendor's Exceptions view — rather than the same "Failed — see Exceptions" wording a genuine extraction failure gets. Resolves Phase 2 Step 0 touch-point gap (retry/arithmetic-gate state). |

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
| Most recent uploads | `extracted.document` | "No statements uploaded yet" | Manual refresh only | Document Detail (`/documents/:id`) |

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
| Extract | Row | Click/Button | Document registered, not yet extracted (added 2026-08-26) | Triggers extraction service (Session 3) manually — see 2026-09-01 note below: extraction now also fires automatically on upload, so this manual path is a fallback, not the only trigger |

**Amended 2026-09-01:** Extract now also fires automatically, client-side, immediately
after a successful upload — the per-row Extract button above still exists (e.g. for a
document that failed auto-extraction) but is no longer the only path. See
ARCHITECTURE.md D-I's 2026-09-01 amendment.

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

**Vendor is not a form field (resolved 2026-08-27, per ARCHITECTURE.md D-L amendment):**
the app identifies the vendor during extraction, not the user at upload. The uploaded-
document list (below the drop-zone) and Home's Uploaded Statements panel show vendor as
"Identifying…" until extraction completes and populates it.

**Amended 2026-09-01:** Legal Entity is no longer a form field — the TBD gap noted above
is resolved by auto-assigning a single fixed default (`DEFAULT_LEGAL_ENTITY_ID`),
engineer-directed simplification, not a UI Discovery outcome. See ARCHITECTURE.md D-F's
2026-09-01 resolution note. Real multi-entity selection remains unbuilt and would need its
own decision if a second entity is ever onboarded.

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

## Exceptions [REWRITTEN 2026-09-01 — was two separate List/Detail screens]
**Type:** List + inline Detail (two-pane master-detail)
**Routes:** `/exceptions` (vendor-grouped landing), `/exceptions/:vendorSlug` (two-pane
detail view)
**Journey:** Review unmatched/ambiguous lines, grouped by vendor; resolve, flag, or skip
each one inline
**Roles:** All
**Trigger:** Nav item click (`/exceptions`); vendor row click (`/exceptions/:vendorSlug`)
**Auth required:** Y

**Why this replaced the original flat-list + separate-detail-page design:** engineer-
supplied Figma mockups specified a per-vendor two-pane master-detail layout instead.
Recorded as an engineer-directed architectural change, not a UI Discovery gap resolution.

### `/exceptions` — Vendor Landing

| Section | Entity / Field | Source | Notes |
|---|---|---|---|
| Vendor list | one row per vendor with ≥1 exception (vendor name, missing-in-ERP count, amount-mismatch count, resolve-progress bar) | `recon.exception` grouped by vendor | Vendors with all exceptions resolved sort after vendors with any still open |

**Actions:** Search (client-side, vendor name); Refresh (manual); click a vendor row →
navigate to that vendor's two-pane view.

**States:** Empty ("No exceptions — all statements reconciled cleanly"), Empty-filtered
("No matching vendors"), Loading (spinner), Error (inline + Retry), Populated.

**List Configuration:** no pagination (vendor count is naturally small); no column
sorting; search is vendor-name substring match only, client-side.

### `/exceptions/:vendorSlug` — Two-Pane Detail

| Section | Entity / Field | Source | Notes |
|---|---|---|---|
| Left panel — exception list | Exception[] for this vendor only (invoice #, date, category badge, amount), filter tabs (All/Missing/Mismatch), resolve-progress bar | `recon.exception` scoped to one vendor | Unpaginated — a single scrollable list; realistic per-vendor volume doesn't need paging |
| Right panel — detail | Selected exception's field-grid (invoice number, vendor, statement period, statement amount, and — `amount_mismatch` only — ERP amount + difference), a "why this is an exception" explanation, CCC corroborating-evidence box (unchanged from the original Exception Detail spec), collapsible NetSuite-record panel with a "show all N fields" raw dump (`amount_mismatch` only, when live Fabric data captured a record), a note field, action buttons, prev/next pager | `recon.exception` + `recon.exception.evidence` (captured at match time — unchanged provenance/never-a-live-re-query rule from the original spec) | Detail is inline, not a separate page navigation |

**Actions:**
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| Mark resolved | Selected exception | Button | Always | Sets `status = 'resolved'`, `resolved_at = now()`, saves the note field if present |
| Flag for vendor | Selected exception | Button | Always | Sets `status = 'flagged'`, same note-saving behavior |
| Skip | Selected exception | Button | Always | Sets `status = 'skipped'`, same note-saving behavior |
| Prev / Next | Selected exception | Button | Within the current filter tab's list | Moves the right-panel selection without leaving the screen |
| Back to Exceptions | Screen | Breadcrumb link | Always | Navigation to `/exceptions` |

**⚠️ Engineer-directed deviation, not a gap:** the three actions above are a narrow
resolution workflow, in tension with ARCHITECTURE.md's original D-A/D-C framing ("no
review/approval workspace"). See ARCHITECTURE.md D-A's 2026-09-01 amendment for the exact
boundary — no segregation of duties, no dollar-threshold approval, no audit ledger, no
reversibility (T2/T3/T4/T7 remain correctly un-built).

**States:** Loading (spinner, right panel only — left panel keeps showing while detail
loads), Error (inline + Retry), No corroborating evidence ("No CCC confirmation
available" — unchanged from original spec), No NetSuite record (panel simply doesn't
render — `not_posted` exceptions have nothing to show by definition), Populated.

**Async Behaviour:** Load-once per vendor; action buttons trigger an immediate
refetch of both the selected exception's detail and the left-panel list (so the
resolve-progress bar and filter-tab membership stay in sync).

---

## UNRESOLVED UI GAPS — carried to Interrogate Missing Information

10 of 14 original gaps resolved via engineer-supplied defaults (2026-08-17); gap #2
resolved 2026-08-26; gap #3 resolved 2026-08-27; gap #4 resolved by implementation
2026-09-01. One remains open — a real architectural question (data provenance), not a
styling choice, deliberately not defaulted:

1. Screen: Sign In — Is SSO actually offered, or ahead of the unresolved auth mechanism
   (still open from Interrogate)?
2. ~~Screen: Home — "View statement" action target~~ **RESOLVED 2026-08-26** — navigates
   to the new Document Detail screen.
3. ~~Screen: Upload — Vendor field: user-selected at upload, or auto-resolved during
   extraction?~~ **RESOLVED 2026-08-27** — auto-resolved during extraction, per
   ARCHITECTURE.md D-L amendment (PHASE4_GATE_RECORD.md Finding 2). Not a form field;
   shown as "Identifying…" until extraction populates it.
4. ~~Screen: Upload — Legal Entity field: user-selected, or inferred?~~ **RESOLVED BY
   IMPLEMENTATION 2026-09-01** — the field was removed entirely, auto-assigned a single
   fixed default (`DEFAULT_LEGAL_ENTITY_ID`), per ARCHITECTURE.md D-F's resolution note.
   Genuine multi-entity access scoping remains unbuilt if a second entity is ever
   onboarded.
- **NEW 2026-09-01, not carried from the original 14:** the Exceptions
  resolution workflow (Mark resolved/Flag for vendor/Skip) has no undo/reversal action and
  no record of *who* took the action beyond the single shared user role — if BCE's eventual
  segregation-of-duties requirement needs per-action attribution, this will need real
  per-user identity first (same gap OD5/D-F already note for multi-entity access).

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

---

## Sign-Off Currency Update (2026-09-01)

**Decision owner:** Vaishali
**Date:** 2026-09-01
**Status:** RATIFIED — the Final Sign-Off above (2026-08-27, through v1.2) is extended to
cover every amendment since, through the current v1.5 (see the Amendment Log at the top of
this document for the full list: v1.3 Extract action/Document Detail/reconcile counts,
v1.4 extracted-schema references + amount-mismatch resourcing, v1.5 Exceptions
vendor-grouped rewrite, Home softening, Upload Legal Entity field removed). Each amendment
was already attributed to engineer direction at the time it was made; this entry closes
the gap between that attribution and a renewed formal sign-off.

**Signature / confirmation:** [x] I confirm this UI surface, including all amendments
through v1.5, remains accurate to my decision and authorized for the current build.
