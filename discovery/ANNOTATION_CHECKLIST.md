# ANNOTATION_CHECKLIST.md — VIVE Reconciliation

This is the BCE backlog — items surfaced during extraction that require an engineer decision, annotation, or judgment call before they can be considered resolved. Opened during Session F03 (Domain Model Synthesis) this pass, ahead of the formal Stage 3 cross-artifact review that will run after Sessions B/C/G/U complete. Per methodology, this file is never empty on a real system — new items accumulate here as extraction proceeds.

---

### P2-F03-001 · `silver_reconciliation_standard.statement_date` does not store a date ([DOMAIN_MODEL.json A-006])

**Severity:** P2
**Type:** OPEN_QUESTION
**Source:** CODE_EXTRACTION
**Surfaced by:** CC (Session F03, while extracting the `statement_date` attribute)
**Artifact:** `DOMAIN_MODEL.json` (A-006)
**Section:** Attribute A-006

**Observation:** `notebooks/01_document_intake.py`'s `normalize_to_silver()` writes `row.get("statement_period")` into the `statement_date` column, with its own inline comment confirming this is deliberate: `"# statement_date — use period as proxy"`. A column named for a specific date (e.g. the date printed on the statement) actually holds a `YYYY-MM` period string throughout the VENDOR_STATEMENT side of this table.

**Risk for planning:** Any future engineer, report, or AI-planning pass that reads `statement_date` expecting a real date (for aging calculations, date-range filtering, or display) will get a period string instead. This is exactly the class of naming-vs-content mismatch BCE annotation exists to catch before it causes a real bug — e.g., a future "statements older than N days" feature built directly against this column would silently misbehave.

**Recommended action:** Engineer decides: (a) rename the column to something accurate (e.g. `statement_period_proxy` or simply drop it in favor of `statement_period`, which already exists as its own column on this same table and holds the real value) in a future migration, or (b) confirm this is intentional and acceptable as-is, with the business meaning recorded here for future readers rather than fixed.

**Engineer action required:** A naming/schema decision, or an explicit acceptance with rationale.

**STATUS:** OPEN — not yet reviewed by the engineer.
