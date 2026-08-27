# VIVE Reconciliation — Rebuild Plan (Business Overview)

**Prepared:** 2026-08-17
**Timeline:** 8-week dev build (2026-08-17 → 2026-10-09)
**Team:** 2 engineers
**Companion doc:** a more technical version of this same plan exists for the engineering team — same weeks, more implementation detail.



---

## 1. This 8-week plan builds the application — it doesn't by itself reach go-live

Two things sit outside these 8 weeks, on their own separate clock:

1. **Some decisions aren't ours to make.** A handful of open business questions (exactly how NetSuite write-back should work, what data volume to plan for, how strict the monthly cutoff is) need sign-off from the client side. We're sending these over immediately so that clock starts now, in parallel with the build — not after it.
2. **A trial period is required before the system can act on its own.** Once matching is built (around Week 5), it needs to run side-by-side with the team's current manual process for **3–4 full monthly reconciliation cycles** before anyone trusts it to auto-approve anything or write information back into NetSuite. That's roughly a 3–4 month window that starts mid-build and continues well past Week 8 — a calendar requirement, not something more engineers can speed up.

By the end of Week 8, the application is fully built and working end to end. Go-live follows once the trial above finishes and the open questions are closed.

---

## 2. The build, week by week

### Week 1 — Sign-in, home, upload
A secure company login (single sign-on, no more shared passwords), a home dashboard, and the ability to upload vendor statements. Documents are tracked from the moment they're uploaded — received, checked, ready — so nothing is ever "lost in a folder."

### Week 2 — Extraction
Reading each PDF statement and pulling out the line-item data automatically, with a built-in check that the extracted numbers actually add up to the statement's total before anything moves forward. If they don't, the document is automatically re-read rather than silently passed through.

### Week 3 — Extraction hardening + connecting to NetSuite and CCC data
A daily automatic data feed pulling open invoices from NetSuite and repair-order data from CCC into the system, so reconciliation always works from a snapshot of yesterday's real numbers. Extraction also gets a permanent record of its raw output and an automated check that catches problems the moment a change breaks something.

### Week 4 — Reconciliation logic
The core matching logic: comparing statement lines against NetSuite invoices automatically, using the data synced in Week 3.

### Week 5 — Trial period begins + monthly runs
This is where the trial period from §2 begins — the system runs and scores matches, the team keeps working as they do today, and the two are compared until we can prove the automated matching is trustworthy. In the same week, "start this month's reconciliation" becomes a real, trackable thing with its own status and history, rather than statements just being processed one at a time with no grouping.

### Week 6 — Exceptions and the reviewer workspace
Anything that doesn't match automatically becomes a tracked exception with an owner and an aging clock, and every decision made is recorded permanently. The review experience: approving matches individually or in bulk, seeing exactly why the system made a suggestion.

### Week 7 — Reviewer permissions + reporting
Reviewer permissions that fit how the AP team actually works, plus the first version of a management-facing dashboard showing reconciliation results and exception trends.

### Week 8 — Reporting costs + wrap-up
Processing-cost visibility added to the dashboard, secondary features (scheduling automation, notifications, exports) as capacity allows, and a full check across everything built so far. The trial that began in Week 5 is now about three weeks into its 3–4 month run.

---

## 3. What's on hold, and why

| Item | Status |
|---|---|
| AI-assisted matching for the hardest cases | On hold — needs a sign-off unrelated to engineering |
| Writing back to NetSuite | On hold — open question on the client side, intentionally not in the current design |
| Scheduling/retry automation, exports, email alerts | Secondary features — built alongside weeks 6–8 as capacity allows, not blocking anything above |

---

## 4. What "ready" looks like

The application is feature-complete at the end of Week 8. It is **not** ready to go live yet — that needs:
- The 3–4 month trial (started Week 5) complete, with measured accuracy — not just "it looks right"
- All open business questions from §2 answered, not left implicit
- A named owner on the client side for approval thresholds and who's responsible for the system day-to-day
- The two on-hold items (AI-assisted matching, NetSuite write-back) either resolved and scheduled, or confirmed as staying out of scope

This is a longer, more deliberate path than a quick feature rollout — but it means what ships is trustworthy from day one, not something that needs to be re-earned later.
