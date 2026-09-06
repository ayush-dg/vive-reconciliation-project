STAGE-3-STATUS: PRODUCED — 2026-09-02, BCE Adapter Pipeline Stage 3 (CD). CHECK 0
(schema validation) initially found 2 P1 SCHEMA_VIOLATIONs in RISK_REGISTER.md
(R-001–R-003 missing Affected-module fields; R-001's "N2" reference not in the
catalogued ID namespace) — both fixed 2026-09-02 (commit `5204e1a`), re-verified clean.
Checks 1–6 then run against all six artifacts plus docs/INVARIANTS.md and
docs/ARCHITECTURE.md as cross-check sources. **Correction (2026-09-02, CC):** P1-S3-002's
original text below cited "Task 4.0 (Fabric migration...)" — no such task exists in
`docs/EXECUTION_PLAN.md` (only Task 4.1/4.2, removed, and 4.3, moved to Session 5).
Corrected in place below; the underlying finding (IP-002's auth mechanism is genuinely
undetermined) was verified accurate and is unaffected by this correction.

# ANNOTATION_CHECKLIST.md — VIVE Statement Reconciliation

The BCE backlog. Produced at Stage 3 (this document), updated at every future
enhancement close-out. Item IDs use the `P[N]-S3-NNN` / `CON-S3-NNN` convention for
items surfaced at Stage 3.

---

## P1 Items

## P1-S3-001 · M-005's unvalidated content-hash undermines G4, with no catalogue cross-reference (MODULE_CONTRACTS / INVARIANT_CATALOGUE)

**Severity:** P1
**Type:** CONTRADICTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** CROSS_ARTIFACT
**Section:** MODULE_CONTRACTS.md M-005 (storage.ts) vs. INVARIANT_CATALOGUE.md G4

**Observation:** M-005's own stated fragility is "No validation that `contentSha256`
actually matches `bytes` — a caller can silently corrupt the content-addressing
invariant" — its own wording names the invariant it threatens. That invariant is G4
("Byte-identical documents, identified by the same content hash, are never
independently re-extracted or re-matched"), a GLOBAL invariant. G4's own catalogue
entry lists its enforcing modules as M-011 (`registerDocument`'s pre-check) and the DB
`UNIQUE` constraint on `content_sha256` — both of which trust that the hash passed in
is correct. Neither G4's Enforcing modules field nor any IC-CANDIDATE mentions M-005 at
all. If a caller ever computed or passed a mismatched hash, G4's uniqueness guarantee
would silently protect the wrong thing — two genuinely different documents could share
a hash-collision-adjacent failure mode with no detection anywhere in the chain M-005 →
M-011 → DB constraint.

**Risk for planning:** A future engineer reading G4's catalogue entry in isolation
would reasonably believe the content-hash guarantee is fully closed (M-011 + DB
constraint = enforced). It isn't — the value being uniqued is never independently
verified against the bytes it claims to represent.

**Recommended action:** Either add M-005 to G4's Enforcing modules field with a note
that it's an unverified precondition, or promote this as a fourth IC-CANDIDATE
("content-hash values must be verified against their claimed bytes before being relied
on for identity/dedup decisions").

**Engineer action required:** Confirm whether this is worth a new IC-CANDIDATE or a
lighter G4 cross-reference update, and whether it's realistic for a caller to ever pass
a wrong hash given the current call sites.

**STATUS:** RESOLVED — engineer chose the lighter cross-reference option, 2026-09-02.
`INVARIANT_CATALOGUE.md` G4's Enforcing modules field now names M-005 explicitly as an
unverified precondition (`[STAGE-3-UPDATE]` tag), not promoted to a separate
IC-CANDIDATE.

---

## P1-S3-002 · IP-002 auth mechanism is genuinely undetermined, and IP-002 is the primary transactional store this build depends on (TOPOLOGY / INTEGRATION_CONTRACTS)

**Severity:** P1
**Type:** NOT_DETERMINABLE
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** INTEGRATION_CONTRACTS
**Section:** IP-002 — Auth mechanism

**Observation:** Unlike IP-003 (fully documented AAD `ClientSecretCredential` flow,
recovered from `G08_fabricLakehouse.md`), no component file read at Stage 2 adds any
detail for IP-002's auth beyond "an endpoint string." Both `TOPOLOGY.md` and
`INTEGRATION_CONTRACTS.md` agree this is genuinely undetermined, not merely stale — so
this isn't a contradiction, but it is a real gap on the one integration point every
`recon` read/write and every `silver` write depends on (R-004's connection-pool bug
already flags this same pool as a single point of failure).

**Risk for planning:** Live Fabric access for this build's own `recon` database is
already a known precondition for several deferred/Fabric-gated build steps (per prior
session records — Sessions 1–3 built and tested against local SQLite, with Fabric
becoming required starting Session 4's original scope). Migrating to live Fabric
without knowing the auth mechanism `db.ts` actually requires is a real blocker,
independent of which specific future task first needs it.

**Recommended action:** Confirm with whoever owns the Fabric SQL Database resource
what auth `FABRIC_SQL_ENDPOINT` actually requires — connection-string-embedded
credentials, managed identity, or something else — before any live-Fabric work begins.

**Engineer action required:** Resolve before live Fabric access is next needed.

**STATUS:** RESOLVED — 2026-09-02. Engineer checked `.env` directly: `FABRIC_SQL_ENDPOINT`
is a bare hostname, not an ADO-style connection string `db.ts`'s `mssql.ConnectionPool`
requires. CC verified this directly against the real parser
(`@tediousjs/connection-string`'s `parseSqlConnectionString()` returns `{}` for a bare
hostname — no server, no auth, nothing). This is now a confirmed root-cause finding, not
an open auth question — see `RISK_REGISTER.md` R-008, `TOPOLOGY.md`/
`INTEGRATION_CONTRACTS.md` IP-002. The *fix* (reformat the connection string once a real
auth scheme — SQL auth vs. Managed Identity vs. AAD service principal — is chosen) remains
a follow-up task, not blocked on further discovery.

---

## P1-S3-003 · R-002's severity is NOT DETERMINABLE, but the underlying gap is already flagged in INVARIANTS.md as needing Vartan's explicit sign-off (RISK_REGISTER / docs/INVARIANTS.md)

**Severity:** P1
**Type:** NOT_DETERMINABLE
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** CROSS_ARTIFACT
**Section:** RISK_REGISTER.md R-002 vs. docs/INVARIANTS.md OD4

**Observation:** R-002 (version-chaining has no human checkpoint) carries severity
`NOT DETERMINABLE FROM SOURCE`. `docs/INVARIANTS.md`'s OD4 entry states this exact gap
was "raised for Vaishali/Vartan to confirm this trade is intentional before build" —
confirmed verbatim against source. This isn't just an unscored risk, it's a named item
already waiting on a specific person's sign-off.

**Risk for planning:** Leaving R-002 at NOT DETERMINABLE understates that this has an
actual owner and a specific ask attached to it, elsewhere in the artifact set.

**Recommended action:** Cross-reference OD4 directly in R-002's Source artifact field.

**Engineer action required:** Confirm with Vartan; update both R-002 and OD4 together
when resolved.

**STATUS:** RESOLVED — see Resolution Log.

---

## CON-S3-001 · INTAKE_SUMMARY.md's Session F disposition ("FULL EXTRACTION expected") was contradicted by Session F never having run (INTAKE_SUMMARY / TOPOLOGY)

**Severity:** P1
**Type:** CONTRADICTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** CROSS_ARTIFACT
**Section:** INTAKE_SUMMARY.md "Session F disposition" field vs. TOPOLOGY.md Stage 2
Completeness Summary

**Observation:** `INTAKE_SUMMARY.md` stated: "**Session F disposition:** FULL
EXTRACTION expected at Stage 2." `TOPOLOGY.md`'s Stage 2 Completeness Summary listed
Sessions A0, A, B/C/G/U, D, E as complete — Session F (and F01/F02/F03, and
`DOMAIN_MODEL.json`) was absent entirely, with no stub, no sparse marker, and no note
explaining why. Confirmed via direct file search: no `F0*`/`domain*` file existed
anywhere in `discovery/` at Stage 3 review time. A genuine gap in Stage 2 execution,
not a documentation-only issue.

**Risk for planning:** Without `DOMAIN_MODEL.json`, `SYSTEM_GRAPH.json`'s cross-graph
edges (OWNS_ENTITY, READS_ENTITY, etc.) can't be built at Stage 3 close-out.

**Recommended action:** Run Session F (F01→F02→F03) before Stage 3 close-out.

**Engineer action required:** Decide whether Session F runs now or is formally
deferred with rationale recorded.

**STATUS:** RESOLVED — Session F complete, 2026-09-02. `discovery/F01_structural_inventory.md`
(13 entities, 12 relationships, zero divergence flags), `discovery/F02_vocabulary_extraction.md`,
and `discovery/DOMAIN_MODEL.json` (6 promoted Entities, 38 Attributes, 6 StatusVocabularies,
19 StatusValues, 6 Relationships — entity-promotion judgment call documented in the JSON's
own `entity_promotion_notes` field) all committed. Ran out of the methodology's preferred
order (after B/C/G/U/D/E rather than before) — acknowledged as a genuine Stage 2 process
gap, caught up rather than redone.

---

## P1-S3-004 · OD6 (exception-resolution workflow invariant question) has no corresponding entry anywhere in INVARIANT_CATALOGUE.md (docs/INVARIANTS.md / INVARIANT_CATALOGUE)

**Severity:** P1
**Type:** NOT_DETERMINABLE
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** INVARIANT_CATALOGUE
**Section:** (absent — should exist alongside S1–S12 / IC-CANDIDATE-01–03)

**Observation:** `docs/INVARIANTS.md` v1.7 (and `INTAKE_SUMMARY.md`, which explicitly
carries it forward as an open question) both flag OD6: whether "a resolved/flagged/
skipped exception is never silently reset back to open by an automated process"
warrants a real S-tier invariant. `INVARIANT_CATALOGUE.md`, produced the same day by
the session that walked every data-mutation touchpoint against the existing 16
entries, does not mention OD6, M-018 (`exceptionDetail.ts`, the resolution-write path),
or this question anywhere — including in its "considered and not elevated" section,
which explicitly documents two other candidates it chose not to promote. Confirmed via
direct search: OD6 appears only in `INTAKE_SUMMARY.md` within `discovery/`, nowhere
else. Appears to have been missed rather than deliberately declined.

**Risk for planning:** This is exactly the kind of gap Stage 3's cross-artifact review
exists to catch — an open question tracked in one artifact with no corresponding
disposition in the sibling artifact whose job is to catalogue exactly this kind of
candidate.

**Recommended action:** Run OD6 through the same evaluation Session D used for
IC-CANDIDATE-01–03 (walk M-018's actual write path, decide enforced/not, decide
Global-cap-respecting scope) and either add it as a new S-item or explicitly document
why it doesn't rise to invariant status.

**Engineer action required:** Decide OD6, same as the other open decisions.

**STATUS:** RESOLVED — see Resolution Log. Added as `INVARIANT_CATALOGUE.md`
IC-CANDIDATE-04, confirmed enforced by direct source read
(`matchingPipeline.ts:39-56`'s eligibility query permanently excludes any line with an
existing exception from re-matching, so `status` can only ever change via the manual
resolution endpoint, M-018).

---

## P2 Items

## P2-S3-005 · NULL `vendor_slug` silently hides exceptions in two independent modules — candidate for a new implicit invariant (MODULE_CONTRACTS)

**Severity:** P2
**Type:** NOT_DETERMINABLE
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** MODULE_CONTRACTS
**Section:** M-019 (exceptionsList.ts), M-048 (api/exceptions/route.ts)

**Observation:** M-019's fragility: "Vendors with NULL `vendor_slug` are silently
invisible." M-048's fragility, independently: "Vendors with NULL `vendor_slug`
silently excluded, no signal." Same pattern, two independently-maintained code paths —
structurally identical to how IC-CANDIDATE-02 was created for the array-order pattern
recurring in `knownVendorExtractors.ts` and `UploadForm.tsx`. This one wasn't caught
by Session D's own candidate walk.

**Risk for planning:** An exception tied to a vendor with a NULL slug is currently
invisible to AP end-to-end (list view and API both silently drop it) — a real business
risk (an unreconciled statement disappears from the workflow with no error), not just
a code-quality note.

**Recommended action:** Promote to IC-CANDIDATE-04: "An exception must never be
silently excluded from every list/API surface due to a missing grouping key; NULL
`vendor_slug` requires an explicit fallback bucket, not silent exclusion."

**Engineer action required:** Confirm whether NULL `vendor_slug` is even reachable in
practice (does every real vendor get a slug assigned?) before deciding this is worth
fixing versus just documenting as a known, unreachable edge case.

**STATUS:** OPEN

---

## P2-S3-006 · R-003 severity NOT DETERMINABLE, ties to OD5's still-open entity-access-scoping question (RISK_REGISTER / docs/INVARIANTS.md)

**Severity:** P2
**Type:** NOT_DETERMINABLE
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** CROSS_ARTIFACT
**Section:** RISK_REGISTER.md R-003 vs. docs/INVARIANTS.md OD5

**Observation:** Same pattern as P1-S3-003 but lower urgency — R-003 (access-scoping
deferral) is genuinely open per OD5 ("partially resolved... entity-scoped access model
remains genuinely open"), not pending a specific named approval the way R-002/OD4 is.

**Risk for planning:** Lower urgency than R-002, but same cross-reference gap — R-003
doesn't point back to OD5 explicitly.

**Recommended action:** Cross-reference OD5 in R-003's Source artifact field.

**Engineer action required:** None until a future UI Discovery pass surfaces a real
need, per OD5's own text — just record the cross-reference now.

**STATUS:** RESOLVED — see Resolution Log.

---

## P2-S3-007 · S12 (row-level duplicate detection) — formally flagging as the OPEN_QUESTION the artifact itself requested (INVARIANT_CATALOGUE)

**Severity:** P2
**Type:** OPEN_QUESTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** INVARIANT_CATALOGUE
**Section:** S12 (candidate)

**Observation:** `INVARIANT_CATALOGUE.md`'s own S12 entry explicitly requests this:
"Listed here as an open engineer decision, not a confirmed invariant — flagged for the
Stage 3 Annotation Checklist as an OPEN_QUESTION." Detection exists and is wired in
(`isDuplicateLine`), but whether the eventual formal S12 statement requires "detect"
or "prevent" is undecided, and the statement itself doesn't exist yet.

**Risk for planning:** A future enhancement touching Silver normalization could
reasonably assume duplicate lines are either blocked or merely flagged — without a
finalized statement, either assumption is currently defensible, which is itself the
risk.

**Recommended action:** Decide detect-vs-prevent, then write S12's actual Statement
field in `docs/INVARIANTS.md` and mirror it here.

**Engineer action required:** Make the detect-vs-prevent call.

**STATUS:** OPEN

---

## P2-S3-008 · IP-005's "outbound" direction (n8n notifications) is unconfirmed — may describe n8n's own behavior, not this app's (INTEGRATION_CONTRACTS)

**Severity:** P2
**Type:** OPEN_QUESTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** INTEGRATION_CONTRACTS
**Section:** IP-005 — Known divergences

**Observation:** `TOPOLOGY.md` A03 states IP-005's purpose includes this app sending
completion notifications to n8n. `INTEGRATION_CONTRACTS.md`'s own Session E pass
already noticed no artifact shows this app making any outbound call to n8n — M-053
only returns a synchronous HTTP response — and explicitly left this "flagged as
unresolved rather than asserted as a defect, since Session E does not read source
directly." This is Session E correctly identifying its own limitation; Stage 3 is
promoting it to a tracked item rather than letting it sit as a prose aside.

**Risk for planning:** If n8n itself originates the notification by reading M-053's
response (plausible per Session E's own note), TOPOLOGY.md's "outbound" framing is
misleading — it implies this codebase owns a notification call that doesn't exist
anywhere in `src/`.

**Recommended action:** A direct source read (grep for any outbound HTTP client call
to an n8n-shaped endpoint) would settle this definitively — cheaper than another full
session.

**Engineer action required:** Confirm or have this checked directly against source.

**STATUS:** OPEN

---

## P2-S3-009 · IC-CANDIDATE-01's "Owning module: M-017" names the side that already works, not the side with the gap — inconsistent with sibling candidates' convention (INVARIANT_CATALOGUE)

**Severity:** P2
**Type:** OPEN_QUESTION → **RESOLVED 2026-09-06 (SPRINT-001 BCE refresh, ENH-001 Task 2.1)**
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** INVARIANT_CATALOGUE
**Section:** IC-CANDIDATE-01

**Observation (historical, pre-fix):** IC-CANDIDATE-03 names M-043 as Owning module — the
module that *should* exclude the route but doesn't, i.e., the module where the gap lives.
IC-CANDIDATE-02 uses "Owning module: none (a cross-cutting gap, not one module's
responsibility)" for a gap spanning two modules. IC-CANDIDATE-01 instead named only M-017 —
the matching-side lock, which already worked correctly — as Owning module, while the actual
gap (no crash-recovery) lived on the extraction side (M-015/M-046), appearing only under
Enforcing modules with "None on the extraction side." This was a labeling inconsistency
across the three candidates the same session produced, not a factual error.

**Resolution:** ENH-001 Task 2.1 (2026-09-04) fixed the extraction-side gap for the
in-process-exception case, which required rewriting IC-CANDIDATE-01's Owning
module/Enforcement point/Rationale fields anyway (see `INVARIANT_CATALOGUE.md`, updated
2026-09-06). The rewrite now names BOTH sides under Owning module — "M-017 (matching side,
unchanged). M-015 (extraction side, now partially enforcing — see above)" — matching
IC-CANDIDATE-02/03's convention of naming the module where the gap (or its owner) actually
lives, not just the side that already worked. The residual gap (OS-level process crash,
not a JS exception) is now correctly attributed to M-015/M-046 under Enforcing modules.
Resolving this alongside the substantive fix, rather than as an independent relabeling
against now-superseded facts, avoided doing the same rewrite twice.

**Recommended action:** Either change Owning module to "none (gap is on the extraction
side, M-015/M-046; M-017 is the working counterpart cited for contrast)" to match
IC-CANDIDATE-02's convention, or add a one-line note clarifying M-017 is cited as the
reference implementation, not the module needing the fix.

**Engineer action required:** Pick a convention and apply it consistently across all
three candidates.

**STATUS:** OPEN

---

## P3 Items

## P3-S3-010 · R-004's P2 severity may understate a full-application blast radius (RISK_REGISTER)

**Severity:** P3
**Type:** OPEN_QUESTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** RISK_REGISTER
**Section:** R-004 — Severity

**Observation:** R-004 is P2, reasoned as "no data corruption... self-inflicted,
non-self-healing outage." But its own Description says the poisoned pool affects "M-003
(all 20 of its callers transitively)" and serves both `recon` and `silver` writes —
meaning a single transient connectivity blip at startup can silently and permanently
(until process restart) break nearly every write path in the application, with zero
operator-facing signal. That reads closer to a full-application outage than a scoped
P2, even without data corruption.

**Risk for planning:** Worth a second look, not an automatic reclassification —
severity should weigh blast radius as well as corruption risk.

**Recommended action:** Reconsider P1 given the 20-caller blast radius and total
absence of automated recovery or alerting, or state explicitly why P2 is still right
(e.g., if Fabric connectivity is judged very unlikely to fail at startup in practice).

**Engineer action required:** Confirm severity.

**STATUS:** OPEN

---

## P3-S3-011 · IP-005 protocol/mechanism remains NOT DETERMINABLE FROM SOURCE (INTEGRATION_CONTRACTS)

**Severity:** P3
**Type:** NOT_DETERMINABLE
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** INTEGRATION_CONTRACTS
**Section:** IP-005 — Protocol/mechanism

**Observation:** Docs state n8n's role (trigger + notifications) but not the transport
(webhook, polling, message queue). Informational — doesn't block current work.

**Recommended action:** Confirm with whoever configured the n8n workflow (not urgent).

**STATUS:** OPEN

---

## P3-S3-012 · Minor known fragilities not yet evaluated as invariant candidates (MODULE_CONTRACTS)

**Severity:** P3
**Type:** OPEN_QUESTION
**Source:** STAGE3_REVIEW
**Surfaced by:** CD
**Artifact:** MODULE_CONTRACTS
**Section:** M-001, M-004, M-006, M-009, M-011

**Observation:** Several module-level fragilities are real but lower-consequence,
bundled here rather than as individual items: M-001 (dual-dialect row-mapping drift
risk on migration), M-004 (misconfigured `SESSION_SECRET` indistinguishable from a
tampered cookie), M-006 (`qualifiedTableName` has no validation outside the
vendor-slug path), M-009 (toast store has no server/client isolation guard), M-011
(UNIQUE-violation detection via error-string matching; unbatched N+1 in
`listDocumentsWithStatusBadge`).

**Recommended action:** No immediate action — track as backlog awareness. Worth a
second pass if any future enhancement touches auth, multi-tenant DDL, or the documents
list endpoint specifically.

**STATUS:** OPEN

---

## Resolution Log

| Item ID | Resolution type | Resolved by | Date | Evidence |
|---|---|---|---|---|
| (CHECK 0 fixes) | RESOLVED-CODE | Vaishali | 2026-09-02 | RISK_REGISTER.md R-001–R-003 Affected-modules fields added; N2 framing corrected — see STAGE-3-STATUS header of RISK_REGISTER.md (commit `5204e1a`) |
| P1-S3-003 | RESOLVED-DOC | CC | 2026-09-02 | RISK_REGISTER.md R-002 now cross-references OD4 directly in its Source artifact field |
| P2-S3-006 | RESOLVED-DOC | CC | 2026-09-02 | RISK_REGISTER.md R-003 now cross-references OD5 directly in its Source artifact field |
| CON-S3-001 | RESOLVED-CODE | Vaishali (decision), CC (execution) | 2026-09-02 | Session F run in full — `discovery/F01_structural_inventory.md`, `discovery/F02_vocabulary_extraction.md`, `discovery/DOMAIN_MODEL.json` all committed |
| P1-S3-004 | RESOLVED-CODE | CC | 2026-09-02 | `INVARIANT_CATALOGUE.md` IC-CANDIDATE-04 added, confirmed enforced by direct read of `matchingPipeline.ts:39-56` |
| P1-S3-001 | RESOLVED-DOC | Vaishali (decision), CC (execution) | 2026-09-02 | `INVARIANT_CATALOGUE.md` G4's Enforcing modules field now names M-005 as an unverified precondition (lighter cross-reference chosen over a new IC-CANDIDATE) |
| P1-S3-002 | RESOLVED-CODE | Vaishali (found it in `.env`), CC (verified against real parser) | 2026-09-02 | `RISK_REGISTER.md` R-008 added — `FABRIC_SQL_ENDPOINT` is a bare hostname, not a valid connection string; confirmed root cause of Fabric never connecting, not merely an open auth question |

*(All 5 P1 items are now RESOLVED. Remaining P2/P3 items below have no entries yet — OPEN
as of this Stage 3 pass, lower urgency, not blocking Stage 3 close-out.)*

---

## Cross-Artifact Consistency Check
Last run: 2026-09-02 By: CD (external Stage 3 review), corrected/re-verified by CC

| Check | Status | Notes |
|---|---|---|
| All invariants in INVARIANT_CATALOGUE.md match INVARIANTS.md | PASS | G1–G5, S1–S8/S10–S12, T1–T7-excluded all consistent; S9 correctly omitted (promoted to G1) |
| All module names in MODULE_CONTRACTS.md match TOPOLOGY.md | PASS as of 2026-09-02; **stale as of 2026-09-06** | Layer counts (infra 12, serving 10, pipeline 20, route 12, UI 24 = 78) as of Stage 3. SPRINT-001 BCE refresh (2026-09-06, ENH-001 Task 2.2) added M-084 (UI layer, 24→25, total 78→79) — see SPRINT-001-BCE-001 below, not yet re-verified as a fresh consistency pass |
| All external systems in INTEGRATION_CONTRACTS.md match TOPOLOGY.md A03 | PASS | 5 IP-NNN consistent post-backport; see P2-S3-008 for one residual open question on IP-005 direction |
| All risks in RISK_REGISTER.md reference correct source artifacts | PASS | — |
| INTAKE_SUMMARY.md open questions accounted for in artifacts | **PASS (was FAIL)** | OD6 now has IC-CANDIDATE-04 (P1-S3-004 resolved); Session F disposition confirmed complete, no longer contradicted (CON-S3-001 resolved) |
| Entity names in DOMAIN_MODEL.json consistent with domain terminology | PASS | `DOMAIN_MODEL.json` produced; 6 entities (Document, Vendor, StatementLine, Match, Exception, AppUser) match the nouns used throughout MODULE_CONTRACTS.md/INVARIANT_CATALOGUE.md/RISK_REGISTER.md |

---

## SPRINT-001-BCE-001 · SYSTEM_GRAPH.json node/edge counts stale after M-084's addition (SYSTEM_GRAPH.json)

**Severity:** P2
**Type:** NOT_DETERMINABLE (graph regeneration not attempted this pass)
**Source:** SPRINT-001 BCE refresh
**Surfaced by:** CC
**Artifact:** SYSTEM_GRAPH.json / TOPOLOGY.md / MODULE_CONTRACTS.md
**Section:** Module Roster, Graph Construction

**Observation:** ENH-001 Task 2.2 added a new module, `src/lib/batchUploadSequencing.ts`
(M-084), recorded in `MODULE_CONTRACTS.md` and `TOPOLOGY.md`'s A02 roster at this refresh
(2026-09-06). `SYSTEM_GRAPH.json` (committed 2026-09-02, Stage 3 close-out) still reflects
the pre-M-084 state: 111 nodes (78 Module + 5 IntegrationPoint + 20 Invariant + 8
RiskItem), 190 edges. Adding M-084 needs at minimum one new Module node and at least one
new CALLS edge (M-070 --[CALLS]--> M-084, per the roster entry added at this refresh) —
not attempted in this pass, since regenerating/hand-editing a validated graph JSON
correctly (without introducing a dangling reference) is a larger, more error-prone task
than the prose-artifact edits this refresh otherwise made.

**Risk for planning:** Low urgency on its own (the graph is a derived/query convenience,
not a source of truth — `MODULE_CONTRACTS.md`/`TOPOLOGY.md` are authoritative and are both
current as of this refresh), but should be regenerated or hand-extended before the graph
is relied on for any future collision-surface analysis (Prompt 2's graph-derived pass) —
a stale graph could produce a false GRAPH-DEFINITE "no collision" finding by simply not
knowing M-084 exists.

---

## Stage 3 Completeness Summary — 2026-09-02
Produced by: BCE Adapter Pipeline Stage 3 (CD), updated by CC

P1 items: 5 total — **all 5 RESOLVED** (P1-S3-001, P1-S3-002, P1-S3-003, P1-S3-004,
CON-S3-001)
P2 items: 5 total — 2 RESOLVED (P2-S3-006; P2-S3-009 resolved 2026-09-06, SPRINT-001 BCE
refresh, ENH-001 Task 2.1), 3 OPEN (lower urgency, non-blocking)
P3 items: 3 — informational backlog
Total items: 13

**Addendum, 2026-09-06 (SPRINT-001 BCE refresh):** one new P2 item added below
(SPRINT-001-BCE-001, `SYSTEM_GRAPH.json` node/edge counts now stale after M-084's
addition) — counts above reflect Stage 3's own original state plus this one refresh-time
change; not a full Stage 3 re-run.

Consistency check: **PASS** (was FAIL) — the one failing row (OD6/Session F) is now
resolved on both counts.

Stage 3 is complete when all P1 items are SIGNED-OFF or RESOLVED by the engineer — **all
5 now are:** P1-S3-001 (M-005/G4 gap) — RESOLVED; P1-S3-002 (IP-002 auth) — RESOLVED
(engineer found the actual malformed value in `.env` directly; the *fix* to that value is
a separate follow-up task, not a discovery gap); P1-S3-003 (R-002/OD4/Vartan) — RESOLVED;
CON-S3-001 (Session F contradiction) — RESOLVED; P1-S3-004 (OD6 uncatalogued) — RESOLVED.

**No P1 items remain open. Stage 3's own completion condition is met.**

**Stage 3 Close-Out Step — Graph Construction (mandatory, all paths):** **COMPLETE —
2026-09-02.** `discovery/SYSTEM_GRAPH.json` committed. 111 nodes (78 Module, 5
IntegrationPoint, 20 Invariant, 8 RiskItem); 190 edges (95 CALLS, 19 OWNS, 32 ENFORCES, 5
CALLS_INTEGRATION, 13 AFFECTS, 3 THREATENS, 6 OWNS_ENTITY, 5 READS_ENTITY, 6
ENFORCES_ENTITY_INVARIANT, 6 ENFORCES_ATTRIBUTE_INVARIANT). Validated: zero dangling
references (every edge's `from`/`to` resolves to a real node, checked against both this
file and `DOMAIN_MODEL.json`). CAN_VIOLATE (IntegrationPoint→Invariant) edges deliberately
omitted — no explicit, evidenced link between a specific IP-NNN gap and a specific named
invariant was found in any committed artifact; fabricating one would violate this
project's own established discipline.

**Per BCE §12: "Stage 3 is not complete until SYSTEM_GRAPH.json is committed to
discovery/." — Stage 3 is now complete.**

**Human gate required before Stage 3 closes.**
**Engineer sign-off:** Vaishali
**Date:** 02-09-2026
