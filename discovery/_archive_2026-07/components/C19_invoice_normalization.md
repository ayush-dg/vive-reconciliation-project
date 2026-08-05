## C19 — invoice normalization
ID: M-038
Layer: pipeline
Source file: src/normalization.py

**Module** — invoice normalization
**ID** — M-038
**Layer** — pipeline
**Primary Responsibility** — Single function: returns an invoice number exactly as provided, whitespace-trimmed only. No suffix/prefix stripping (RULE-01) — divergent vendor/ERP formatting is a real discrepancy to surface, never papered over.

**Inputs** — `normalize_invoice_number(invoice_number: str) -> str`.

**Outputs** — The trimmed string, or the input unchanged if falsy (`if not invoice_number: return invoice_number`).

**Public Interface**
- `normalize_invoice_number(invoice_number: str) -> str` — the entire module's exported surface.

**Error Behaviour** — None needed — a pure, side-effect-free string function; cannot raise given its own falsy-input guard.

**Known Fragility** — **This function currently does nothing beyond `.strip()`** — confirmed by direct source read (the entire body is a null-check and a `.strip()` call). This is precisely why DOMAIN_MODEL.json's `invoice_number_normalized` attribute (A-010) is annotated as "currently identical to invoice_number in every observed case" — not a bug, a deliberate, minimal-by-design implementation of RULE-01, but worth remembering this field currently carries zero additional normalization value.

**Change Impact** — If a future vendor-specific normalization profile is ever introduced (per A-010's disambiguation_note), it would live here — this is the one, correctly-isolated place such logic should go, confirmed by its use in exactly two call sites (both Silver-writing paths).

**Callers** — M-014 (`notebooks/01_document_intake.py`, `normalize_to_silver()`), M-037 (`src/mock_erp/generator.py`, `normalize_erp_to_silver()`)
**Calls** — none
**Integration Points Used** — none
