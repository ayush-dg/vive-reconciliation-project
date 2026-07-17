"""
gemini_client.py

Gemini 2.5 Flash implementation of AIClient, via the google-genai SDK
(Files API + generate_content). The ONLY file that knows Gemini's SDK/wire
format.

Registered in client_factory.py as "gemini" and set as the active primary
provider in active_provider.json.

Sends the whole PDF as ONE file upload + ONE generate_content call — no
page splitting. Diagnostic testing validated this is reliable across all
four sample vendor statements (69-602 rows extracted, 65-245s per document,
no truncation at max_tokens), unlike Claude/Mistral, which needed either
streaming+a large token budget or per-page splitting to cover a whole
multi-page document in one provider call.

Column-agnostic mapping (RULE-07 spirit — no per-vendor config): the
extraction prompt returns each row as a flat dict keyed by whatever text
actually appears in the PDF's header row (varies per vendor — "Invoice #",
"Document No.", "INVOICE NUMBER", etc., and sometimes the model normalizes
to snake_case keys like "invoice_number" instead). This client derives a
field mapping once per document from `columns_found` using keyword
matching (same general approach as pdfplumber_fallback._map_columns(), but
self-contained here — same precedent as MistralClient), with one addition
found necessary during diagnostic testing:

  - Some vendors' statements (e.g. Fred_Beans_MidNJ_053126.pdf) print BOTH
    a route/account-code-prefixed reference number and a clean invoice
    number in separate columns ("INVOICE NUMBER" = "60 35 8923821" vs.
    "INVOICE NO." = "8923821"). Relying on header text or column order
    alone to pick between them is fragile. Instead, when multiple
    invoice-number-like columns are found, this client samples each
    candidate's actual values and picks whichever has the fewest values
    matching an account/route-code prefix pattern — a direct, content-
    based signal instead of a positional guess.

This client never raises out of generate_with_file()/generate() — any
upload, API, or parsing failure is converted into a clean AIResponse
failure so a bad extraction never crashes the pipeline; the fallback chain
(pdfplumber) takes over instead.

Two additional behaviors, added after real-world testing surfaced gaps:

  - 503 UNAVAILABLE retry: Gemini's backend occasionally returns a
    transient 503. Unlike a genuine extraction failure, this is worth
    retrying before giving up — generate_with_file() retries up to 2 times
    with a 60s wait between attempts, specifically for 503/UNAVAILABLE.
    Any other error (bad JSON, auth, 4xx, etc.) fails immediately with no
    retry, same as before.

  - Tolerant column mapping: the keyword-based field mapping (above) can
    fail to recognize a column on some rows (inconsistent per-row keys,
    an unfamiliar header, etc.). Rather than silently leaving
    invoice_number/outstanding_amount null (which routes the row to the
    review queue as MISSING_MANDATORY_FIELD), _row_to_invoice() falls back
    to scanning the row's own values directly: for invoice_number, the
    first value that looks alphanumeric and isn't a date or a currency
    figure; for outstanding_amount, the first remaining numeric value.
    Each fallback use is logged (stdout + an aggregated schema warning) so
    it stays visible rather than silently degrading data quality.
"""

import json
import os
import re
import time
from typing import Callable, Optional

from .base_client import AIClient, AIResponse

ROW_CONFIDENCE = 0.75

EXTRACTION_PROMPT = """You are extracting data from a vendor statement PDF for an accounts payable system. This is critical financial data — accuracy is essential.

STEP 1: Look at the table headers and identify all columns.

STEP 2: Extract every single data row exactly as printed. For each row:
- Use exact column header names as keys
- invoice_number: use the CLEANEST invoice number column available —
  if there are multiple invoice number columns, prefer the one WITHOUT
  account codes or route codes (usually a shorter, rightmost column).
  The invoice number is typically just digits or alphanumeric like
  8923821, SIN12200241, CM8923821, 366377-1.
  NEVER include account codes like '60 35' or '99 57' before the number.
- If a cell is blank return null
- Do NOT skip any rows
- Do NOT merge rows
- Do NOT calculate anything

Also extract document-level metadata at the top of the JSON response:
- vendor_name: the vendor/supplier company name as printed on the
  document (e.g. 'Fred Beans Parts Inc', 'asTech', 'KSI')
- statement_date: the statement date if visible

Return JSON:
{
  vendor_name: '...',
  statement_date: '...',
  columns_found: [exact column names from header],
  rows: [{col1: val, col2: val, ...}]
}"""

ACCOUNT_CODE_PREFIX_RE = re.compile(r'^\s*\d{2}[\s.]?\d{2}\b')

# Fallback-mapping heuristics (see module docstring "Tolerant column mapping").
# A currency figure has $-signs, thousands commas, or 2-digit decimal cents —
# that's what disqualifies a value from being treated as a bare invoice
# number (a bare invoice number like "8923821" would otherwise also parse
# as a float, so this can't just be "does it parse as a number").
CURRENCY_LIKE_RE = re.compile(r'^\(?-?\$?\s*\d[\d,]*\.\d{2}\)?-?$')
DATE_LIKE_RE = re.compile(
    r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$'          # 05/01/2026, 04/01/26
    r'|^\d{1,2}[A-Za-z]{3}\d{2,4}$',            # 12DEC25
)
ALPHANUMERIC_TOKEN_RE = re.compile(r'^[A-Za-z0-9\-]+$')

INVOICE_NUMBER_KEYWORDS = (
    "invoice #", "invoice no", "invoice number", "invoice#", "inv #", "inv no",
    "document no", "sin", "reference",
)
DUE_DATE_KEYWORDS = ("due date",)
DATE_KEYWORDS = ("invoice date", "posting date", "transaction date", "date")
OUTSTANDING_KEYWORDS = ("amount due", "balance", "outstanding", "remaining", "net amount", "unpaid")
CREDIT_KEYWORDS = ("credits", "payments", "credit memo", "credit")
CHARGE_KEYWORDS = ("charges", "purchases", "amount charged", "invoice amt", "debit", "gross amount")
RO_KEYWORDS = ("ro #", "ro no", "repair order")
PO_KEYWORDS = ("po #", "po no", "purchase order")
WORK_ORDER_KEYWORDS = ("work order", "wo #", "wo no")
DESCRIPTION_KEYWORDS = ("description", "desc", "notes")
SHOP_KEYWORDS = ("shop", "location", "store", "branch", "entity")


class GeminiClient(AIClient):
    def __init__(self, config: dict, transport: Optional[Callable] = None):
        """
        config   : parsed config/ai/gemini.json
        transport: optional injectable callable for testing.
                   Signature: (pdf_path, config) -> (success, schema_dict, error)
                   Stands in for the entire real call (upload + generate_content
                   + mapping), same convention as MistralClient's
                   generate_with_file() transport injection point.
                   If None, uses the real Gemini API call.
        """
        self.config = config
        self._transport = transport

        self.api_key = os.environ.get(config.get("api_key_env_var", "GEMINI_API_KEY"))
        self.model = (
            os.environ.get(config.get("model_env_var", "GEMINI_MODEL"))
            or config.get("model")
        )

    def _missing_config_error(self) -> Optional[str]:
        if not self.api_key:
            return f"Missing API key — env var '{self.config.get('api_key_env_var')}' not set"
        if not self.model:
            return f"Missing model — env var '{self.config.get('model_env_var')}' not set"
        return None

    def generate(self, prompt: str, *, temperature=None, max_output_tokens=None) -> AIResponse:
        """Plain text-only completion — exists for AIClient interface parity.
        document_understanding_engine.py's primary path uses generate_with_file()
        instead; this is not exercised by the extraction pipeline."""
        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="gemini", model=self.model or "", error=missing)

        temperature = temperature if temperature is not None else self.config.get("temperature", 0.1)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 1)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        start = time.monotonic()
        last_error = None

        for attempt in range(1, max_retries + 2):
            try:
                if self._transport:
                    success, text, error = self._transport(prompt, self.config)
                else:
                    success, text, error = self._real_text_call(prompt, temperature, max_output_tokens)

                latency_ms = (time.monotonic() - start) * 1000
                if success:
                    return AIResponse(
                        success=True, text=text, parsed_json=self._try_parse_json(text),
                        model=self.model, provider="gemini",
                        latency_ms=latency_ms, attempt_count=attempt,
                    )
                last_error = error
                if attempt <= max_retries:
                    time.sleep(backoff * (multiplier ** (attempt - 1)))
            except Exception as e:
                last_error = str(e)
                if attempt <= max_retries:
                    time.sleep(backoff * (multiplier ** (attempt - 1)))

        latency_ms = (time.monotonic() - start) * 1000
        return AIResponse(
            success=False, provider="gemini", model=self.model,
            latency_ms=latency_ms, attempt_count=max_retries + 1, error=last_error,
        )

    def _real_text_call(self, prompt, temperature, max_output_tokens):
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            config_kwargs = {
                "http_options": types.HttpOptions(
                    timeout=self.config.get("timeout_seconds", 600) * 1000
                ),
            }
            if temperature is not None:
                config_kwargs["temperature"] = temperature
            if max_output_tokens is not None:
                config_kwargs["max_output_tokens"] = max_output_tokens

            response = client.models.generate_content(
                model=self.model,
                contents=[prompt],
                config=types.GenerateContentConfig(**config_kwargs),
            )
            return True, response.text, None
        except Exception as e:
            return False, "", self._clean_error(str(e))

    def generate_with_file(self, pdf_path: str, prompt: str) -> AIResponse:
        """
        Upload the whole PDF once and send ONE generate_content call — no
        page splitting (see module docstring). `prompt` is accepted for
        AIClient interface parity but unused — this client always sends its
        own EXTRACTION_PROMPT.

        Retries up to retry_policy.max_retries times (config/ai/gemini.json,
        default 2), waiting a flat retry_policy.backoff_seconds (default 60)
        between attempts, specifically for a 503 UNAVAILABLE response —
        transient and worth retrying, unlike a genuine extraction failure.
        Any other error (bad JSON, auth, 4xx, upload failure, ...) returns
        a clean AIResponse(success=False, ...) immediately, with no retry,
        so it falls through to the next provider in the chain (pdfplumber)
        rather than crashing the pipeline or looping needlessly.
        """
        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="gemini", model=self.model or "", error=missing)

        start = time.monotonic()

        if self._transport:
            success, result, error = self._transport(pdf_path, self.config)
            latency_ms = (time.monotonic() - start) * 1000
            if success:
                text_out = json.dumps(result)
                return AIResponse(
                    success=True, text=text_out, parsed_json=result,
                    model=self.model, provider="gemini",
                    latency_ms=latency_ms, attempt_count=1,
                )
            return AIResponse(
                success=False, provider="gemini", model=self.model,
                latency_ms=latency_ms, attempt_count=1, error=error,
            )

        retry_policy = self.config.get("retry_policy", {})
        max_503_retries = retry_policy.get("max_retries", 2)
        backoff_503_seconds = retry_policy.get("backoff_seconds", 60)

        last_error = None
        for attempt in range(1, max_503_retries + 2):
            uploaded_name = None
            try:
                from google import genai
                from google.genai import types

                client = genai.Client(api_key=self.api_key)

                uploaded = client.files.upload(file=pdf_path)
                uploaded_name = uploaded.name

                wait_start = time.monotonic()
                while uploaded.state == types.FileState.PROCESSING and time.monotonic() - wait_start < 60:
                    time.sleep(1)
                    uploaded = client.files.get(name=uploaded.name)

                if uploaded.state != types.FileState.ACTIVE:
                    raise RuntimeError(f"uploaded file never became ACTIVE (state={uploaded.state})")

                response = client.models.generate_content(
                    model=self.model,
                    contents=[uploaded, EXTRACTION_PROMPT],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        http_options=types.HttpOptions(
                            timeout=self.config.get("timeout_seconds", 600) * 1000
                        ),
                    ),
                )
                text = response.text
                usage = response.usage_metadata

                parsed = self._try_parse_json(text)
                if parsed is None:
                    raise ValueError("response did not contain parseable JSON")

                rows = parsed.get("rows", []) or []
                columns_found = parsed.get("columns_found", []) or []
                vendor_name = parsed.get("vendor_name") or None
                statement_date = parsed.get("statement_date") or None
                print(f"  [GeminiClient] Columns found: {columns_found}")

                truncation_reason = self._detect_truncation(parsed, rows, columns_found, pdf_path)
                if truncation_reason:
                    print(f"  [GeminiClient] Truncation detected — {truncation_reason}")
                    self._cleanup_file(uploaded_name)
                    latency_ms = (time.monotonic() - start) * 1000
                    return AIResponse(
                        success=False, provider="gemini", model=self.model,
                        latency_ms=latency_ms, attempt_count=attempt,
                        error="Response appears truncated — falling back",
                    )

                invoices, fallback_warnings = self._rows_to_invoices(rows, columns_found)

                result = self._build_schema(
                    pdf_path, invoices, columns_found,
                    bool(parsed.get("_salvaged")), fallback_warnings,
                    vendor_name=vendor_name, statement_date=statement_date,
                )

                if usage:
                    print(f"  [GeminiClient] Tokens — input: {usage.prompt_token_count}, "
                          f"output: {usage.candidates_token_count}, total: {usage.total_token_count}")

                self._cleanup_file(uploaded_name)
                latency_ms = (time.monotonic() - start) * 1000
                text_out = json.dumps(result)
                return AIResponse(
                    success=True, text=text_out, parsed_json=result,
                    model=self.model, provider="gemini",
                    latency_ms=latency_ms, attempt_count=attempt,
                )

            except Exception as e:
                self._cleanup_file(uploaded_name)
                last_error = self._clean_error(str(e))

                if self._is_retryable_503(e) and attempt <= max_503_retries:
                    print(f"  [GeminiClient] 503 UNAVAILABLE — retrying in {backoff_503_seconds}s "
                          f"(attempt {attempt}/{max_503_retries + 1})")
                    time.sleep(backoff_503_seconds)
                    continue

                latency_ms = (time.monotonic() - start) * 1000
                return AIResponse(
                    success=False, provider="gemini", model=self.model,
                    latency_ms=latency_ms, attempt_count=attempt,
                    error=last_error,
                )

        # Unreachable — the loop always returns on its last iteration.
        latency_ms = (time.monotonic() - start) * 1000
        return AIResponse(
            success=False, provider="gemini", model=self.model,
            latency_ms=latency_ms, attempt_count=max_503_retries + 1, error=last_error,
        )

    @staticmethod
    def _is_retryable_503(e: Exception) -> bool:
        """True if `e` represents a 503 UNAVAILABLE from the Gemini API —
        transient and worth retrying, unlike a genuine extraction failure."""
        try:
            from google.genai import errors
            if isinstance(e, errors.APIError):
                if getattr(e, "code", None) == 503:
                    return True
                status = str(getattr(e, "status", "") or "").upper()
                if "UNAVAILABLE" in status:
                    return True
        except Exception:
            pass
        # Fallback string match, in case some path raises a differently
        # shaped exception (e.g. an unwrapped transport-level error).
        msg = str(e)
        return "503" in msg and "UNAVAILABLE" in msg.upper()

    # ---- truncation detection ----

    TRUNCATION_ROW_RATIO = 0.10

    def _detect_truncation(self, parsed: dict, rows: list, columns_found: list, pdf_path: str) -> Optional[str]:
        """
        Returns a human-readable reason if the parsed response looks
        truncated, or None if it looks complete. Two independent signals:

        1. rows is empty but columns_found is not — the model found a table
           but the response was cut off before any row was written.
        2. The JSON itself was salvaged from a truncated response (see
           _try_parse_json/_salvage_rows_from_truncated_json) AND the
           salvaged row count is under 10% of what deterministic pdfplumber
           extraction finds in the same document — a real truncation, not
           just a document with few rows.

        On a truncation, generate_with_file() returns a failed AIResponse
        immediately rather than retrying — a truncated response is a
        systematic issue (hit the token budget), not a transient one, so
        retrying the same model would very likely truncate again. The
        caller (DocumentUnderstandingEngine) falls back to pdfplumber.
        """
        if not rows and columns_found:
            return "rows list is empty but columns_found is not"

        if parsed.get("_salvaged"):
            pdfplumber_row_count = self._pdfplumber_row_count(pdf_path)
            if pdfplumber_row_count and len(rows) < self.TRUNCATION_ROW_RATIO * pdfplumber_row_count:
                return (f"JSON was truncated and salvaged only {len(rows)} row(s), but "
                        f"pdfplumber found {pdfplumber_row_count} row(s) in the same document")

        return None

    @staticmethod
    def _pdfplumber_row_count(pdf_path: str) -> int:
        """Deterministic row count for the same document, used only to
        judge whether a salvaged (truncated) response is suspiciously
        short. Never raises — a failure here just disables signal 2."""
        try:
            from src.ai.pdfplumber_fallback import extract_with_pdfplumber
            result = extract_with_pdfplumber(pdf_path)
            return len(result.get("invoices", []) or [])
        except Exception:
            return 0

    def _cleanup_file(self, uploaded_name):
        """Best-effort delete of the uploaded file — never lets cleanup
        failure affect the extraction result."""
        if not uploaded_name:
            return
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            client.files.delete(name=uploaded_name)
        except Exception:
            pass

    # ---- column-agnostic mapping ----

    def _rows_to_invoices(self, rows: list, columns_found: list):
        """Returns (invoices, fallback_warning_messages)."""
        if not rows:
            return [], []

        field_map = self._map_columns(columns_found, rows)

        invoices = []
        fallback_warnings = []
        for row_num, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            invoices.append(self._row_to_invoice(row, field_map, row_num, fallback_warnings))
        return invoices, fallback_warnings

    @staticmethod
    def _normalize_header(header) -> str:
        return str(header).lower().strip().replace("_", " ")

    @staticmethod
    def _match_any(header_norm: str, keywords: tuple) -> bool:
        return any(kw in header_norm for kw in keywords)

    def _map_columns(self, columns_found: list, rows: list) -> dict:
        """
        Map this document's actual header names to standard schema fields,
        once per document. Returns {field_name: original_header_key}.
        """
        field_map = {}
        invoice_candidates = []

        headers = columns_found or (list(rows[0].keys()) if rows and isinstance(rows[0], dict) else [])

        for header in headers:
            h = self._normalize_header(header)
            if self._match_any(h, INVOICE_NUMBER_KEYWORDS):
                invoice_candidates.append(header)
            elif self._match_any(h, DUE_DATE_KEYWORDS):
                field_map.setdefault("due_date", header)
            elif self._match_any(h, DATE_KEYWORDS):
                field_map.setdefault("invoice_date", header)
            elif self._match_any(h, OUTSTANDING_KEYWORDS):
                field_map.setdefault("outstanding_amount", header)
            elif self._match_any(h, CREDIT_KEYWORDS):
                field_map.setdefault("credit", header)
            elif self._match_any(h, CHARGE_KEYWORDS) or h == "amount":
                field_map.setdefault("amount", header)
            elif self._match_any(h, RO_KEYWORDS):
                field_map.setdefault("ro_number", header)
            elif self._match_any(h, PO_KEYWORDS):
                field_map.setdefault("po_number", header)
            elif self._match_any(h, WORK_ORDER_KEYWORDS):
                field_map.setdefault("work_order_number", header)
            elif self._match_any(h, DESCRIPTION_KEYWORDS):
                field_map.setdefault("description", header)
            elif self._match_any(h, SHOP_KEYWORDS):
                field_map.setdefault("shop", header)

        if invoice_candidates:
            field_map["invoice_number"] = self._pick_cleanest_column(invoice_candidates, rows)

        return field_map

    @staticmethod
    def _pick_cleanest_column(candidates: list, rows: list) -> str:
        """Among several invoice-number-like columns, prefer whichever has
        the fewest values matching an account/route-code prefix pattern
        (e.g. '60 35 8923821') — a content-based signal, not header order
        (see module docstring)."""
        if len(candidates) == 1:
            return candidates[0]

        best = candidates[0]
        best_score = None
        for col in candidates:
            values = [row.get(col) for row in rows if isinstance(row, dict)]
            sampled = [v for v in values if v is not None][:200]
            if not sampled:
                continue
            prefixed = sum(1 for v in sampled if ACCOUNT_CODE_PREFIX_RE.match(str(v)))
            score = prefixed / len(sampled)
            if best_score is None or score < best_score:
                best_score = score
                best = col
        return best

    def _row_to_invoice(self, row: dict, field_map: dict, row_num: int, fallback_log: list) -> dict:
        def get(field):
            key = field_map.get(field)
            return row.get(key) if key else None

        raw_invoice_number = get("invoice_number")
        raw_outstanding = get("outstanding_amount")
        raw_amount = get("amount")

        invoice_number = raw_invoice_number
        outstanding = self._to_float(raw_outstanding)
        amount = self._to_float(raw_amount)
        if amount is None:
            amount = outstanding

        # Tolerant fallback mapping (see module docstring) — standard
        # keyword-based mapping missed this field for this row (either no
        # column was ever recognized for it, or this row's own key set
        # doesn't match the rest of the document). Scan the row's raw
        # values directly rather than leaving the field null and letting
        # the row silently fail validation downstream.
        used_fallback = []
        already_used = {v for v in (raw_invoice_number, raw_outstanding, raw_amount) if v is not None}

        if not invoice_number:
            _, candidate = self._fallback_invoice_number(row, exclude=already_used)
            if candidate is not None:
                invoice_number = candidate
                already_used.add(candidate)
                used_fallback.append("invoice_number")

        if outstanding is None:
            _, candidate = self._fallback_amount(row, exclude=already_used)
            if candidate is not None:
                outstanding = candidate
                if amount is None:
                    amount = candidate
                used_fallback.append("outstanding_amount")

        if used_fallback:
            msg = (f"Row {row_num}: standard column mapping missing {used_fallback} — "
                   f"used value-based fallback instead of dropping the row")
            print(f"  [GeminiClient] {msg}")
            fallback_log.append(msg)

        return {
            "invoice_number": invoice_number,
            "invoice_date": get("invoice_date"),
            "due_date": get("due_date"),
            "amount": amount,
            "outstanding_amount": outstanding,
            "ro_number": get("ro_number"),
            "po_number": get("po_number"),
            "work_order_number": get("work_order_number"),
            "description": get("description"),
            "credit": self._to_float(get("credit")),
            "shop": get("shop"),
            "page_number": 1,  # single whole-document call — no per-page split to track
            "row_number": row_num,
            "line_confidence": ROW_CONFIDENCE,
        }

    @staticmethod
    def _looks_like_invoice_number(value) -> bool:
        """True if `value` looks like a plausible invoice number: alphanumeric
        (letters/digits/hyphens), not a date, not a currency figure. A bare
        digit string (e.g. "8923821") passes — that's a legitimate invoice
        number shape — but "$48.75" / "1,234.56" / "48.75" (2-decimal cents,
        the currency tell) do not."""
        if value is None:
            return False
        s = str(value).strip()
        if not s or len(s) < 3:
            return False
        if DATE_LIKE_RE.match(s):
            return False
        if CURRENCY_LIKE_RE.match(s):
            return False
        if not ALPHANUMERIC_TOKEN_RE.match(s):
            return False
        return True

    @classmethod
    def _fallback_invoice_number(cls, row: dict, exclude=frozenset()):
        """Scan all values in `row` for the first one that looks like an
        invoice number, skipping any value already claimed by another
        field (so the same cell can't become both the invoice number and
        the amount — see module docstring / the earlier cross-contamination
        bug this guards against). Returns (key, value) or (None, None)."""
        for key, val in row.items():
            if val in exclude:
                continue
            if cls._looks_like_invoice_number(val):
                return key, val
        return None, None

    @classmethod
    def _fallback_amount(cls, row: dict, exclude=frozenset()):
        """Scan all values in `row` for the first one that looks like a
        currency figure (CURRENCY_LIKE_RE — decimal cents, optional $/commas),
        skipping any value already claimed by another field. Requiring the
        currency shape (not just "parses as a number") is deliberate: vendor
        statements with dual invoice-number-like columns (see module
        docstring / _pick_cleanest_column) can leave a second, unmapped copy
        of the bare invoice number sitting in the row — a value like
        "8923821" parses as a float just as easily as "706.29" does, so
        accepting any numeric value would silently reintroduce the invoice-
        number-as-amount cross-contamination this fallback is supposed to
        prevent. Returns (key, parsed_float) or (None, None)."""
        for key, val in row.items():
            if val in exclude or val is None:
                continue
            if not CURRENCY_LIKE_RE.match(str(val).strip()):
                continue
            parsed = cls._to_float(val)
            if parsed is not None:
                return key, parsed
        return None, None

    @staticmethod
    def _to_float(val) -> Optional[float]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace(",", "").replace("$", "")
        if not s:
            return None
        negative = s.endswith("-") or (s.startswith("(") and s.endswith(")"))
        s = s.strip("()").rstrip("-")
        try:
            v = float(s)
            return -v if negative else v
        except ValueError:
            return None

    def _build_schema(self, pdf_path: str, invoices: list, columns_found: list, salvaged: bool,
                       fallback_warnings: Optional[list] = None, vendor_name: Optional[str] = None,
                       statement_date: Optional[str] = None) -> dict:
        statement_total = sum(
            inv.get("outstanding_amount", 0) or 0
            for inv in invoices
            if inv.get("outstanding_amount") is not None
        )
        confidence = ROW_CONFIDENCE if invoices else 0.20

        warnings = []
        if salvaged:
            warnings.append(f"Response was truncated — {len(invoices)} rows salvaged from partial JSON.")
        if fallback_warnings:
            # Aggregate rather than including every per-row message here —
            # each one was already printed individually during extraction
            # (see _row_to_invoice); this just keeps a persisted, visible
            # record that fallback mapping happened without bloating
            # document_intake_log.warnings for a document with many rows.
            warnings.append(
                f"{len(fallback_warnings)} row(s) required value-based fallback column "
                f"mapping (standard header-keyword mapping didn't recognize a column for "
                f"invoice_number and/or outstanding_amount on those rows)."
            )

        return {
            "document_metadata": {
                "document_type": "VENDOR_STATEMENT",
                "source_file": os.path.basename(pdf_path),
                # not tracked — single whole-document call, no per-page split
                "page_count": None,
                "document_type_confidence": 0.60,
            },
            "vendor_metadata": {
                "vendor_name": vendor_name,
                "vendor_address": None,
                "shop_or_entity": [],
                "vendor_confidence": 0.50 if vendor_name else 0.10,
            },
            "statement_metadata": {
                "statement_date": statement_date,
                "statement_period_start": None,
                "statement_period_end": None,
                "currency": "USD",
                "statement_total_as_printed": statement_total if invoices else None,
                "statement_confidence": 0.30,
            },
            "invoices": invoices,
            "extraction_confidence": {
                "overall": confidence,
                "table_detection_confidence": 0.80 if invoices else 0.20,
                "column_mapping_confidence": 0.80 if invoices else 0.10,
            },
            "warnings": [{"code": "OTHER", "message": w, "severity": "MEDIUM"} for w in warnings],
            # TEMPORARY diagnostic field — see MistralClient for the same
            # convention. Downstream consumers ignore unknown top-level keys.
            "columns_found": columns_found or [],
        }

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """Parse the {columns_found, rows} JSON a call returns. If truncated
        (max_tokens cut it off mid-object), salvage whatever complete row
        objects were written before the cutoff — same brace-counting
        strategy ClaudeClient/MistralClient use for their own row shapes."""
        if not text:
            return None

        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        return self._salvage_rows_from_truncated_json(text)

    @staticmethod
    def _salvage_rows_from_truncated_json(text: str) -> Optional[dict]:
        if '"rows"' not in text:
            return None

        rows_start = text.find('"rows"')
        array_start = text.find('[', rows_start)
        if array_start == -1:
            return None

        columns_found = []
        cols_start = text.find('"columns_found"')
        if cols_start != -1 and cols_start < rows_start:
            cols_array_start = text.find('[', cols_start)
            cols_array_end = text.find(']', cols_array_start) if cols_array_start != -1 else -1
            if cols_array_start != -1 and cols_array_end != -1:
                try:
                    columns_found = json.loads(text[cols_array_start:cols_array_end + 1])
                except Exception:
                    columns_found = []

        # vendor_name/statement_date are written before columns_found/rows in
        # the prompted response shape, so they're recoverable even when
        # truncation cuts off partway through the rows array.
        header_text = text[:rows_start]
        vendor_name_match = re.search(r'"vendor_name"\s*:\s*"([^"]*)"', header_text)
        vendor_name = vendor_name_match.group(1) if vendor_name_match else None
        statement_date_match = re.search(r'"statement_date"\s*:\s*"([^"]*)"', header_text)
        statement_date = statement_date_match.group(1) if statement_date_match else None

        rows_text = text[array_start:]
        salvaged = []
        i = 0
        while i < len(rows_text):
            if rows_text[i] == '{':
                depth = 0
                start = i
                in_string = False
                escape_next = False
                j = i
                while j < len(rows_text):
                    c = rows_text[j]
                    if escape_next:
                        escape_next = False
                    elif c == '\\' and in_string:
                        escape_next = True
                    elif c == '"':
                        in_string = not in_string
                    elif not in_string:
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                obj_text = rows_text[start:j + 1]
                                try:
                                    obj = json.loads(obj_text)
                                    if isinstance(obj, dict):
                                        salvaged.append(obj)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                                i = j + 1
                                break
                    j += 1
                else:
                    break
            elif rows_text[i] == ']':
                break
            i += 1

        if not salvaged:
            return None
        return {
            "rows": salvaged, "columns_found": columns_found,
            "vendor_name": vendor_name, "statement_date": statement_date,
            "_salvaged": True,
        }

    def _clean_error(self, raw_error: str) -> str:
        if not raw_error:
            return "unknown error"

        raw = str(raw_error)
        raw_lower = raw.lower()

        if "rate_limit" in raw_lower or "429" in raw or "resource_exhausted" in raw_lower:
            return "rate limited — try again shortly"

        if ("authentication" in raw_lower or "401" in raw or "api key" in raw_lower
                or "permission_denied" in raw_lower or "403" in raw):
            return "invalid API key or permission denied"

        if "404" in raw or "not_found" in raw_lower:
            return "resource not found — check model name / uploaded file"

        if "timeout" in raw_lower or "timed out" in raw_lower or "deadline" in raw_lower:
            return "request timed out"

        if "connection" in raw_lower or "network" in raw_lower:
            return "network error"

        first_line = raw.split("\n")[0][:150]
        return first_line
