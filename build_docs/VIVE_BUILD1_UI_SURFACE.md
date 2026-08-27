# UI_SURFACE.md — VIVE Statement Reconciliation (Bounded First Build)
## Version: v1.0 · 2026-08-17

## Amendment Log
| Date | Screen/Section | Change | Reason |
|---|---|---|---|
| 2026-08-17 | Navigation | Sidebar confirmed from reference mockup; Schedule excluded, Home retained as landing/report | Scope resolution |
| 2026-08-17 | — | Initial draft | Phase 1 UI Discovery |
| 2026-08-17 | All screens | Finalized with TBD markers on unresolved gaps, deferred with engineer acknowledgement | Engineer requested finalization before full gap resolution |
| 2026-08-17 | Data baseline | Confirmed Migrated only, no Seeded component — all data in cloud | Engineer clarification; SEED_DATA.md production skipped per PBVI-011 conditional |
| 2026-08-17 | Home | Added status badge (Processing/Retrying/Failed/Reconciled) to Uploaded Statements panel | Resolved Phase 2 Step 0 touch-point gap — retry/arithmetic-gate state now has screen coverage |
| 2026-08-17 | All screens | Applied engineer-supplied defaults for 10 of 14 gaps (stats set, refresh pattern, save behavior, pagination, search, session expiry, error style, loading style, toast position) | Engineer opted for reasonable defaults rather than further discovery rounds |
| 2026-08-17 | Upload | Removed Vendor field from pre-upload form; added Detected Statement Info panel showing auto-detected vendor/period post-extraction | Engineer direction: vendor/period auto-detected during extraction, not user-selected; part of upload+extract logic (EXECUTION_PLAN.md Task 3.5) |

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
| Summary stats | Documents processed, open exceptions, extraction failures | Computed from `recon`/bronze records | Default applied: three counts every other screen already implies |
| Uploaded Statements panel | Document[] (vendor, period, status, upload date) + status badge | `bronze.document` + extraction attempt state | Status badge: "Processing" / "Retrying (N/2)" / "Failed — see Exceptions" / "Reconciled". Resolves Phase 2 Step 0 touch-point gap (retry/arithmetic-gate state) |

### Actions
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| View statement | Row | Click/Link | Always | TBD — target screen undefined; no Document Detail screen exists in inventory |

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
| Uploaded Statements | `bronze.document` | "No statements uploaded yet" | TBD — polling vs. manual | TBD |

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
| Section | Entity / Field | Source | Notes |
|---|---|---|---|
| Detected Statement Info panel (added 2026-08-17) | Document status badge + detected vendor name + detected statement period | `bronze.document` (status computation from Task 2.3, detected fields from Task 3.5) | Appears per-document after upload, once extraction completes; shows "Failed — see Exceptions" with no vendor/period if extraction fails after 2 attempts |

### Actions
| Label | Scope | Trigger | Condition | Outcome |
|---|---|---|---|---|
| Upload | Screen | Form submit / drop | Always | API call → document registered, content-hash checked (D-H) |

### States
| State | Trigger | What Renders |
|---|---|---|
| Loading | Upload in progress | Simple spinner (per global default) |
| Error | Upload failed, or duplicate-hash reject | Inline error |
| Populated | Default drop-zone | Drop target + browse button |
| Processing (added 2026-08-17) | Extraction in progress for an uploaded document | Status badge "Processing" or "Retrying (N/2)", no vendor/period yet |
| Detected (added 2026-08-17) | Extraction succeeded | Status badge "Reconciled" or similar, with detected vendor name and statement period shown |
| Detection failed (added 2026-08-17) | Extraction failed after 2 attempts | "Failed — see Exceptions" badge, no vendor/period |

### Form Fields
| Field | Type | Required | Conditional On | Validation Message |
|---|---|---|---|---|
| Statement PDF | File | Y | NONE | "Select a PDF statement" |
| Legal Entity | Dropdown | TBD — real architectural gap: v3.3 tags `legal_entity_id` at document level but doesn't specify who/what sets it | NONE | — |

**Removed 2026-08-17:** Vendor field is no longer collected at upload time — vendor name
is auto-detected from the document during extraction and displayed back on this same
page (see Data Displayed above and EXECUTION_PLAN.md Task 3.5). Legal Entity's provenance
remains a separate, still-open question, not resolved by this change.

- Save behaviour: Stay on page with confirmation toast (safer than silent navigate-away for financial-data upload)
- Cancel behaviour: N/A

### Async Behaviour
- Pattern: Load-once for upload action; extraction happens out-of-band, with the Upload
  page reflecting status/detection results once available (manual refresh, per resolved
  global default — no polling infra yet)
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
| Main list | Exception[] (vendor, invoice ref, amount, exception type, date) | `recon.exception` | Includes D-H's "possible duplicate/correction" as one exception type |

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

### Async Behaviour
- Pattern: Load-once
- Scope: Whole screen

---

## UNRESOLVED UI GAPS — carried to Interrogate Missing Information

11 of 14 original gaps resolved. Gap #3 (Vendor field) resolved 2026-08-17 — auto-detected
during extraction, not user-selected (see EXECUTION_PLAN.md Task 3.5). Three remain open:

1. Screen: Sign In — Is SSO actually offered, or ahead of the unresolved auth mechanism
   (still open from Interrogate)?
2. Screen: Home — "View statement" action target: no Document Detail screen currently
   exists in inventory. Navigates where?
3. Screen: Upload — Legal Entity field: user-selected, or inferred? Real architectural
   gap — v3.3 tags `legal_entity_id` at the document level but doesn't specify who/what
   sets it. Note: this is NOT resolved by the vendor/period auto-detection change —
   deliberately kept separate, not conflated.

## Engineer Sign-Off

**Decision owner:** Vaishali
**Date:** 2026-08-17
**Signature / confirmation:** [x] I confirm this UI surface is accurate to my decision, with unresolved gaps above explicitly deferred and acknowledged.

**Data baseline confirmed:** Migrated only — no Seeded component. All data resides in cloud (Azure/Fabric). SEED_DATA.md production is skipped per the PBVI-011 conditional ("[Run only if data baseline = Seeded]").
