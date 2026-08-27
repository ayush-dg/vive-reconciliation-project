## C21 — Invoice Number Normalization
ID: M-036
Layer: pipeline
Source file: `src/normalization.py`

**Module** — Invoice Number Normalization
**ID** — M-036
**Layer** — pipeline
**Primary Responsibility** — Whitespace-trims an invoice number with no other transformation, by explicit design (RULE-01).

**Inputs** — `invoice_number: str`.

**Outputs** — The same string, stripped (or the original falsy value unchanged if input is falsy).

**Public Interface** — `normalize_invoice_number(invoice_number: str) -> str`.

**Error Behaviour** — None possible — a pure, total function over its input type.

**Known Fragility** — The entire point of this module is what it deliberately does **not** do: no suffix/prefix stripping, no case normalization, no fuzzy matching. This was tried before and reverted (RULE-01) because it hid real discrepancies between vendor and ERP invoice-numbering formats. Any future "improvement" to add normalization logic here directly reintroduces a previously-identified, previously-fixed problem — this is the single highest-risk-of-well-intentioned-regression module in the codebase, precisely because its correctness is defined by restraint, not by capability.

**Change Impact** — Called by both sides of Silver normalization (M-017 for VENDOR_STATEMENT, M-035 for INTERNAL_ERP) — any change here affects every matching comparison system-wide, both retroactively (re-normalized data) and going forward.

**Callers** — M-017 (`normalize_to_silver()`), M-035 (`normalize_erp_to_silver()`)
**Calls** — none
**Integration Points Used** — none
