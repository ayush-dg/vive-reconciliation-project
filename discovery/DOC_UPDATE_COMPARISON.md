# DOC_UPDATE_COMPARISON.md — VIVE Reconciliation

## Retroactive-production note

This artifact is being produced **retroactively**. In the normal sequence, this
doc-vs-artifact comparison would run before updating `docs/INVARIANTS.md` and
`docs/ARCHITECTURE.md` — but Phase 0's findings (Sprint 1 already open, ENH-001
already built) made the situation clear enough to act on directly, so this
comparison step was skipped in the moment. The doc edits (INV-06 addition, the
match-confidence caveat, the Engineer Sign-Off revert) and the reconciliation
commit (`a3359f0`) already happened. This file is backfilled now for the record —
it documents what those actions changed, not what they should be.

**Note on methodology fit:** this project runs BCE Path A (Custodian-Led — see
`discovery/TOPOLOGY.md`'s header). Path A has no native Stage 1 (docs-derived
draft) step; that step exists only on Path C. The "claim form" shape used below
is borrowed from `BCE/bce_core.md` §10's Stage 1 draft template (claims sourced
from docs/, marked against what discovery/ can or cannot confirm) because it is
the right shape for *this* retroactive comparison, not because a Stage 1 draft
was actually run here.

---

## Baseline definition

**"Before" state — the five living artifacts as they stood at commit `027f5d2`**
(the last commit that touched any of the five before the scoped refresh landed):
`discovery/TOPOLOGY.md`, `discovery/MODULE_CONTRACTS.md`,
`discovery/INTEGRATION_CONTRACTS.md`, `discovery/INVARIANT_CATALOGUE.md`,
`discovery/RISK_REGISTER.md` (per `BCE/bce_core.md`'s Role 2 definition, Section
99–107).

**"After" state — the same five artifacts at `a3359f0`** ("BCE reconciliation:
close out ENH-001 doc/code drift" — the commit that finally landed the
2026-07-25 scoped-refresh edits into git, three of the underlying code commits
for which had landed as early as `6685969`/`4537ca5`/`1fd1b6e`/`280d706` between
2026-07-24 and 2026-07-25).

Diff `027f5d2..a3359f0`: `INTEGRATION_CONTRACTS.md` — **no change** (not touched
by the scoped refresh). `TOPOLOGY.md`, `MODULE_CONTRACTS.md`,
`INVARIANT_CATALOGUE.md`, `RISK_REGISTER.md` — all four changed (Scoped Refresh
Addendum, IC-19 rewrite + IC-21 addition, M-045–M-048 contracts, R-004 update +
R-009/R-010 additions, respectively — already fully catalogued in those files'
own addenda; not re-litigated here).

**Docs compared (current state, as of this writing):** `docs/ARCHITECTURE.md`,
`docs/INVARIANTS.md`, `docs/Claude.md`, and — see note below —
`docs/VIVE_Implementation_Context.md`.

**Filesystem note on the fourth doc:** `docs/VIVE_Implementation_Context.md`
(the exact path requested) does not exist on disk. `git status` shows it as
deleted from the working tree (`D`); a different, updated file — `docs/VIVE_
Implementation_Context (1).md` — exists untracked alongside it. The two are not
the same document: the git-history version is a stale, pre-web-app draft
(references a Streamlit dashboard, predates the FastAPI app entirely); the `(1)`
file is current and describes the FastAPI/Jinja2 system with match confidence,
routing/aging, etc. This comparison uses the `(1)` file's content as "current,"
since it is the only version actually reflecting the present system — but the
rename/duplication itself is a finding, not something resolved here (no file
was modified or renamed as part of producing this artifact).

---

## Claims — docs/ARCHITECTURE.md

**CLAIM-ARCH-01.** "Three concurrent worker threads start when the app starts...
Each worker polls Azure SQL atomically every 30 seconds... At most 2 concurrent
Claude Sonnet calls... Graceful shutdown." (§2.6)
— *Old baseline (027f5d2):* NOT DETERMINABLE FROM the old TOPOLOGY.md/
MODULE_CONTRACTS.md — the worker pool, `stop_workers()`, and the concurrency
limiter did not exist as documented modules at that commit (M-013 was a single
thread; M-047 did not exist).
— *Current baseline (a3359f0):* CONFIRMED — matches the rewritten C01
contract and the new IC-21/G18 entry exactly.
— *Change:* net-new claim, added to reflect real, already-shipped work.

**CLAIM-ARCH-02.** Match-confidence table (§2.5) lists `PO`/`RO`/`Fuzzy` rows
alongside `INVOICE`, with the caveat line (added this session) that `PO` and
`Fuzzy` are placeholder entries `classify_match()` cannot currently produce.
— *Old baseline:* NOT DETERMINABLE — `score_match_confidence()`/
`score_exception_confidence()` did not exist at `027f5d2`.
— *Current baseline:* CONFIRMED, including the caveat — matches C17's rewritten
contract and MODULE_CONTRACTS.md cross-cutting finding #9 verbatim (unreachable
match types, deterministic scoring).
— *Change:* net-new claim; the caveat line closes a gap this same reconciliation
found two turns ago (docs presented unreachable match types as live).

**CLAIM-ARCH-03.** §5 "Auto-Intake (Blob Drop Zone) — Partial": webhook built
(validation handshake, BlobCreated handling, `batch_id`), blocked on Event Grid
System Topic / RBAC, reported to Ashrith.
— *Old baseline:* NOT DETERMINABLE — M-046 did not exist.
— *Current baseline:* PARTIALLY CONFIRMED. The "built"/"blocked" framing matches
TOPOLOGY.md's IP-010 entry and RISK_REGISTER R-009, but §5 still does not mention
that the webhook was unauthenticated end-to-end until 2026-07-25, that a
container-pinning security gap existed alongside it, or that both are now fixed
in code — a finding already raised in this reconciliation's earlier turn and
still not corrected in ARCHITECTURE.md (out of scope for this file to fix; noted
for completeness).
— *Change:* net-new claim; omission persists.

**CLAIM-ARCH-04.** Known Gaps table: "Stale job requeue... Now narrower — only
stalls that one filename, not the whole queue."
— *Old baseline:* the risk existed (R-004) but was system-wide in scope.
— *Current baseline:* CONFIRMED — matches RISK_REGISTER's 2026-07-25 update note
on R-004 exactly (narrowed blast radius, gap itself not closed).
— *Change:* claim's *severity framing* changed to track the real narrowing;
correct.

---

## Claims — docs/INVARIANTS.md

**CLAIM-INV-01.** INV-05: per-`pdf_filename` scope (not system-wide), enables
worker pool up to `WORKER_POOL_SIZE` (default 3).
— *Old baseline:* the pre-refresh INVARIANT_CATALOGUE.md's IC-19 already carried
the *system-wide* wording (this amendment predates the 027f5d2 baseline per its
own "Amended 2026-07-24" note — INV-05 in docs/INVARIANTS.md already reflected
the narrowed scope before this reconciliation began).
— *Current baseline:* CONFIRMED — matches IC-19's rewritten text.
— *Change:* none from this reconciliation; pre-existing and consistent both
before and after.

**CLAIM-INV-02.** INV-06 (added this reconciliation): `VIVE_MAX_CONCURRENT_AI_CALLS`
concurrency cap, sourced verbatim from IC-21.
— *Old baseline:* NOT PRESENT — IC-21 itself did not exist at `027f5d2` (added
2026-07-25); docs/INVARIANTS.md had no INV-06 at any point before this
reconciliation.
— *Current baseline:* CONFIRMED — added verbatim from IC-21 two turns ago in
this same reconciliation.
— *Change:* **the fix.** This is the specific gap Phase 0/this reconciliation
exists to close: IC-21 existed in discovery/ since 2026-07-25 with an explicit
self-flag ("not documented anywhere in RULES.md or docs/INVARIANTS.md"); it
took until this reconciliation for docs/INVARIANTS.md to catch up.

**CLAIM-INV-03.** Engineer Sign-Off: now "DRAFT — NOT YET REVIEWED" with a note
that v1.2's "REVIEWED AND CONFIRMED" claim had no corresponding review record.
— *Old baseline:* N/A — this is a claim about the doc's own review status, not
a claim discovery/ can confirm or deny.
— *Current baseline:* N/A, same reason.
— *Change:* corrected from an unverifiable "confirmed" claim to an honest draft
state, per direct instruction two turns ago. Included here for completeness of
the record, not because discovery/ has a position on it.

---

## Claims — docs/Claude.md

**CLAIM-CLAUDE-01.** Section 2 Hard Invariants lists INV-01 through INV-05 (with
INV-05's amendment) and CQ-001. No INV-06 equivalent.
— *Old baseline:* consistent with old IC catalogue (no concurrency-limiter
invariant existed yet).
— *Current baseline:* **NOT CONFIRMED — same gap as docs/INVARIANTS.md before
this reconciliation's INV-06 fix, but here it is still open.** `docs/Claude.md`
was not in scope for any edit made so far; it still has no equivalent of IC-21.
— *Change:* **none — this is an unresolved carry-over.** Flagging it explicitly:
whoever closes this out should decide whether `docs/Claude.md`'s five-invariant
ceiling (stated explicitly in the pre-migration draft of INVARIANTS.md as a
hard PBVI schema cap) permits a sixth, or whether IC-21 belongs there under a
different mechanism.

**CLAIM-CLAUDE-02.** Section 4 Fixed Stack: "Worker: 3-thread pool, configurable
via `VIVE_WORKER_POOL_SIZE`. AI rate limit via `VIVE_MAX_CONCURRENT_AI_CALLS`
(default 2)."
— *Old baseline:* NOT DETERMINABLE — neither existed.
— *Current baseline:* CONFIRMED — matches C01/G18 exactly.
— *Change:* net-new claim, correctly reflects shipped work (unlike Claim-01
above, this part of Claude.md *was* updated to v2.0).

**CLAIM-CLAUDE-03.** Section 3 Scope Boundary: "Fault isolation per file in a
batch (Step 6) — not yet built."
— *Old baseline:* consistent (not built then either).
— *Current baseline:* CONFIRMED — still not built; no discovery/ module or risk
entry contradicts this.
— *Change:* none — stable claim, correctly still true.

---

## Claims — docs/VIVE_Implementation_Context (1).md

**CLAIM-VIC-01.** Section 5, "Final Plan — Steps 1-11 Status": Steps 1
(drop zone), 3 (batch_id), 5 (parallel workers), 7 (match confidence), 8
(routing/aging), 10 (bulk approve), 11 (batch summary) all marked Done; Step 2
(Event Grid trigger) Blocked; Step 4 (jobs from Event Grid) "Code done...
untestable until Step 2 unblocked"; Step 6 (fault isolation) Not built; Step 9
(email alerts) Deferred.
— *Old baseline:* NOT DETERMINABLE for Steps 1, 3, 5, 7, 8, 10, 11 — none of
M-045 through M-048 or the worker-pool/match-confidence/aging code existed.
— *Current baseline:* CONFIRMED for all eleven — this table's Done/Blocked/
Not-built/Deferred split matches discovery/'s current state claim-for-claim,
including the code-done-but-untestable nuance for Step 4, which is actually
*more* precise than ARCHITECTURE.md's framing of the same fact.
— *Change:* net-new claims, and internally consistent with discovery/.

**CLAIM-VIC-02.** Section 8, "Key Bugs Fixed (Session Jul 22-27, 2026)" — ten
entries, none referencing the Event Grid webhook authentication gap or its fix.
— *Old baseline:* N/A (R-009 did not exist).
— *Current baseline:* **NOT CONFIRMED — omission.** RISK_REGISTER's R-009 (no
auth at all until 2026-07-25, container-pinning gap, both fixed in code) is
arguably the most severe item that landed in this window — a real,
externally-reachable security gap — and it is absent from a table whose whole
purpose is tracking exactly this kind of fix. Same blind spot already flagged
against ARCHITECTURE.md (CLAIM-ARCH-03) and Claude.md; this is the third of the
four docs reviewed to omit the security angle of the Event Grid work entirely.

**CLAIM-VIC-03.** Section 10, "Progress Log" — dates the worker pool, Blob drop
zone, `/api/intake-trigger`, match confidence scoring, routing/aging, and bulk
approve all to **2026-07-23**.
— *Old baseline:* N/A (dating claim, not a feature claim).
— *Current baseline:* **CONTRADICTED.** `discovery/TOPOLOGY.md`'s Scoped Refresh
Addendum and `discovery/MODULE_CONTRACTS.md`'s refresh note both date the same
work to **2026-07-24** ("8 commits" landing that day, discovered and written up
2026-07-25), and the actual commit trail (`6685969`, `4537ca5`, `1fd1b6e`,
`280d706`) is dated within that later window, not 2026-07-23. This is a
one-day-off discrepancy across every Progress Log row for this batch of work —
worth a correction pass on this doc, though out of scope to fix here.

---

## Summary

| Source doc | Claims checked | Confirmed | Net-new (correctly added) | Unresolved / contradicted |
|---|---|---|---|---|
| ARCHITECTURE.md | 4 | 3 | 3 | 1 (CLAIM-ARCH-03, auth omission) |
| INVARIANTS.md | 3 | 2 | 1 (the INV-06 fix itself) | 0 |
| Claude.md | 3 | 2 | 1 | 1 (CLAIM-CLAUDE-01, INV-06 gap not carried here) |
| VIVE_Implementation_Context (1).md | 3 | 1 | 1 | 2 (security omission, date discrepancy) |

`INTEGRATION_CONTRACTS.md` was not a source of any claim above because none of
the four docs make integration-contract-level assertions (external system
promises vs. application assumptions) distinct from what's already covered
under the other four artifacts — consistent with it being unchanged between
`027f5d2` and `a3359f0`.

**Net position:** this reconciliation (across this session) closed the one gap
it set out to close — INV-06 now exists in `docs/INVARIANTS.md`, sourced
verbatim from IC-21. Three gaps remain open and are not addressed by this
artifact: `docs/Claude.md` still has no IC-21 equivalent; three of the four
docs (ARCHITECTURE.md, Claude.md, and the Implementation Context doc) omit the
Event Grid webhook's authentication history entirely; and the Implementation
Context doc's Progress Log misdates the whole 2026-07-24 batch of work by one
day. None of these were touched — per instruction, this file only reports.
