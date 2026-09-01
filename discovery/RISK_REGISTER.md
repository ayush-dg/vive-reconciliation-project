STAGE-1-DRAFT: DOCS-DERIVED — 2026-09-01 — Produced by BCE Adapter Pipeline Stage 1

# RISK_REGISTER.md — VIVE Statement Reconciliation

Seeded per BCE convention: one entry for each ACCEPT-disposed finding in
`docs/PHASE4_GATE_RECORD.md` Section D, plus a stub entry (severity NOT DETERMINABLE FROM
SOURCE) for each key risk in `docs/ARCHITECTURE.md` §4 that isn't already covered by a
PHASE4_GATE_RECORD.md disposition. Section D's own severity scale (BLOCKER/HIGH/MEDIUM/LOW)
is mapped to P1/P2/P3 as: BLOCKER→P1, HIGH→P2, MEDIUM/LOW→P3. Note: Section D's 5 BLOCKER
and 1 HIGH findings besides #7 are all disposed **RESOLVE**, not ACCEPT — closed by a
concrete doc/plan change, so they are not carried into this live risk register (their
resolution is recorded in `PHASE4_GATE_RECORD.md` itself, which remains the authoritative
history). Only genuinely still-open risk is catalogued here.

---

- **Risk ID:** R-001
- **Description:** Non-negotiable N2 ("never call NetSuite/CCC live from matching") has no
  enforcing invariant — the original GLOBAL invariant enforcing this was removed 2026-08-17.
  `EXECUTION_PLAN.md` Task 5.2 itself states this is "no longer an enforced invariant, only
  a design convention." A brief non-negotiable currently has no hard enforcement behind it.
- **Severity:** P2 (source: HIGH, `PHASE4_GATE_RECORD.md` Section D Finding #7)
- **Source artifact:** `docs/PHASE4_GATE_RECORD.md` Section D, Finding #7
- **Mitigation:** Engineer accepted rationale (verbatim intent): "still true but not needed
  to be defined." N2 remains true by construction — Task 5.2's matching only ever queries
  `silver.statement_line`/Silver reference data; no live-API code path exists anywhere in
  the current plan to guard against. Accepted as a documented convention, not re-promoted
  to an enforced/tested invariant.
- **Recommended action:** NOT DETERMINABLE FROM SOURCE (requires operational assessment).
  Docs do state a revisit trigger: re-evaluate if a future task ever introduces the "live
  NetSuite/CCC pull as an alternative matching mode" item already tracked in
  `ARCHITECTURE.md` §7's Parking Lot.

- **Risk ID:** R-002
- **Description:** Version-chaining (D-H, amended 2026-08-26) has no human checkpoint at
  all — a genuinely conflicting (not corrective) statement for the same vendor/period
  silently supersedes the prior one with no flag raised. `ARCHITECTURE.md` §4 itself
  describes this as "a real gap for BCE to close, and a sharper one than before the
  2026-08-26 amendment — worth explicit sign-off rather than treating as equivalent risk."
- **Severity:** NOT DETERMINABLE FROM SOURCE
- **Source artifact:** `docs/ARCHITECTURE.md` §4 Key Risks, item 1 (not covered by any
  `PHASE4_GATE_RECORD.md` Section D finding — no matching entry found there)
- **Mitigation:** none stated — this risk is recorded as currently unmitigated, not
  accepted-with-rationale like R-001.
- **Recommended action:** NOT DETERMINABLE FROM SOURCE (requires operational assessment;
  `ARCHITECTURE.md` frames this as BCE-scope to close, not a decision this bounded build
  has made).

- **Risk ID:** R-003
- **Description:** Access-scoping deferral (D-F) could surface a real architectural need
  late — if a future UI Discovery pass reveals users genuinely need entity-partitioned
  access, not just a screen filter, that would be a Phase 2 loop-back, not a cosmetic fix.
  Partially resolved 2026-09-01 by removing the Legal Entity picker (auto-assigned a single
  fixed default) — but this resolves the *symptom* (an unresolved UI field), not the
  underlying open question about whether real multi-entity access scoping is eventually
  needed.
- **Severity:** NOT DETERMINABLE FROM SOURCE
- **Source artifact:** `docs/ARCHITECTURE.md` §4 Key Risks, item 4 (not covered by any
  `PHASE4_GATE_RECORD.md` Section D finding — no matching entry found there); related to
  the still-open OD5/D-F item in `ARCHITECTURE.md` §6 Open Questions
- **Mitigation:** none stated.
- **Recommended action:** NOT DETERMINABLE FROM SOURCE (requires operational assessment).

---

## Not carried into this register (context, not omission)

- `PHASE4_GATE_RECORD.md` Section D findings #8–#12 (MEDIUM/LOW) remain
  `*(engineer to disposition)*` — neither RESOLVE nor ACCEPT. Per the seeding rule ("for
  each ACCEPT decision... produce one risk entry"), an undispositioned finding is not yet
  an ACCEPT and is not catalogued here. If the engineer later dispositions any of them
  ACCEPT, this register should be updated at that time — flagged, not silently pre-empted.
- The verification-tooling non-idempotency finding and the S7 status-badge bug (both from
  `verification/VERIFICATION_CHECKLIST.md`, 2026-09-01) are real, open issues but are not
  ARCHITECTURE.md key risks or PHASE4_GATE_RECORD.md dispositions — they belong to Phase 8
  Part 1's own record, already tracked there, not duplicated into this register.
