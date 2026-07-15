"""
claude_sonnet_client.py

Claude Sonnet 4.6 implementation of AIClient, via Azure Foundry
(anthropic.AnthropicFoundry — same routing as claude_client.py). Registered
in client_factory.py as "claude_sonnet" — an alternate extraction provider,
NOT part of the active provider chain (gemini remains primary; see
active_provider.json).

Sends the whole PDF as ONE base64 document block + ONE streaming
messages call — no page splitting, same whole-document approach as
GeminiClient. Streaming (client.messages.stream() + get_final_message())
is required here rather than a plain messages.create() call: a single
whole-document extraction call on a multi-page statement can run long
enough that a non-streaming request risks tripping a read timeout before
the full response arrives.

Column-agnostic mapping (RULE-07 spirit — no per-vendor config) and the
tolerant fallback mapping are the same logic as GeminiClient's
(self-contained here, same precedent as MistralClient/GeminiClient not
sharing a utils module) — including the amount-fallback currency-shape
guard: a fallback amount candidate must look like a currency figure
(decimal cents, optional $/commas), not just "parses as a number". That
guard exists because validating GeminiClient against a real vendor
statement (Fred_Beans_MidNJ_053126.pdf) surfaced a duplicate unmapped
column repeating the bare invoice number, which an "any numeric value"
fallback wrongly accepted as the amount and inflated a statement total to
~$90M. Baking the same guard in here from the start avoids re-discovering
that bug in a second provider.

This client never raises out of generate_with_file()/generate() — any
file-read, API, or parsing failure is converted into a clean AIResponse
failure so a bad extraction never crashes the pipeline.
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
  account codes or route codes.
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

# Fallback-mapping heuristics (see module docstring). A currency figure has
# $-signs, thousands commas, or 2-digit decimal cents — that positively
# identifies a dollar amount and, just as importantly, disqualifies a bare
# invoice-number-shaped value (e.g. "8923821") from being mistaken for one.
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


class ClaudeSonnetClient(AIClient):
    def __init__(self, config: dict, transport: Optional[Callable] = None):
        """
        config   : parsed config/ai/claude_sonnet_extraction.json
        transport: optional injectable callable for testing.
                   generate_with_file(): (pdf_path, config) -> (success, schema_dict, error)
                   generate():           (prompt, config) -> (success, text, error)
                   If None, uses the real anthropic SDK via Azure Foundry.
        """
        self.config = config
        self._transport = transport

        self.api_key = os.environ.get(config.get("api_key_env_var", "AZURE_CLAUDE_API_KEY"))
        self.endpoint = os.environ.get(config.get("endpoint_env_var", "AZURE_CLAUDE_ENDPOINT"))
        self.deployment = os.environ.get(config.get("deployment_env_var", "AZURE_CLAUDE_SONNET_DEPLOYMENT"))
        self.model = self.deployment or config.get("model")

    def _missing_config_error(self) -> Optional[str]:
        if not self.api_key:
            return f"Missing API key — env var '{self.config.get('api_key_env_var')}' not set"
        if not self.model:
            return f"Missing model — env var '{self.config.get('deployment_env_var')}' not set"
        return None

    def _build_client(self):
        """Anthropic client — routed via Azure Foundry when self.endpoint is set
        (same pattern as claude_client.py)."""
        import anthropic

        if self.endpoint:
            return anthropic.AnthropicFoundry(api_key=self.api_key, base_url=self.endpoint)
        return anthropic.Anthropic(api_key=self.api_key)

    def generate(self, prompt: str, *, temperature=None, max_output_tokens=None) -> AIResponse:
        """Plain text-only completion — exists for AIClient interface parity.
        document_understanding_engine.py's primary path uses generate_with_file()
        instead; this is not exercised by the extraction pipeline."""
        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="claude_sonnet", model=self.model or "", error=missing)

        temperature = temperature if temperature is not None else self.config.get("temperature", 0.1)
        max_tokens = max_output_tokens or self.config.get("max_output_tokens", 64000)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 2)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        start = time.monotonic()
        last_error = None

        for attempt in range(1, max_retries + 2):
            try:
                if self._transport:
                    success, text, error = self._transport(prompt, self.config)
                else:
                    success, text, error = self._real_text_call(prompt, temperature, max_tokens)

                latency_ms = (time.monotonic() - start) * 1000
                if success:
                    return AIResponse(
                        success=True, text=text, parsed_json=self._try_parse_json(text),
                        model=self.model, provider="claude_sonnet",
                        latency_ms=latency_ms, attempt_count=attempt,
                    )
                last_error = error
                if attempt <= max_retries:
                    time.sleep(backoff * (multiplier ** (attempt - 1)))
            except Exception as e:
                last_error = self._clean_error(str(e))
                if attempt <= max_retries:
                    time.sleep(backoff * (multiplier ** (attempt - 1)))

        latency_ms = (time.monotonic() - start) * 1000
        return AIResponse(
            success=False, provider="claude_sonnet", model=self.model,
            latency_ms=latency_ms, attempt_count=max_retries + 1, error=last_error,
        )

    def _real_text_call(self, prompt, temperature, max_tokens):
        try:
            client = self._build_client()
            with client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=self.config.get("timeout_seconds", 600),
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                message = stream.get_final_message()
            return True, message.content[0].text, None
        except Exception as e:
            return False, "", self._clean_error(str(e))

    def generate_with_file(self, pdf_path: str, prompt: str) -> AIResponse:
        """
        Send the whole PDF once as a base64 document block, via ONE
        streaming messages call — no page splitting (see module docstring).
        `prompt` is accepted for AIClient interface parity but unused — this
        client always sends its own EXTRACTION_PROMPT (same convention as
        GeminiClient/MistralClient).
        """
        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="claude_sonnet", model=self.model or "", error=missing)

        temperature = self.config.get("temperature", 0.1)
        max_tokens = self.config.get("max_output_tokens", 64000)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 2)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        start = time.monotonic()

        if self._transport:
            success, result, error = self._transport(pdf_path, self.config)
            latency_ms = (time.monotonic() - start) * 1000
            if success:
                text_out = json.dumps(result)
                return AIResponse(
                    success=True, text=text_out, parsed_json=result,
                    model=self.model, provider="claude_sonnet",
                    latency_ms=latency_ms, attempt_count=1,
                )
            return AIResponse(
                success=False, provider="claude_sonnet", model=self.model,
                latency_ms=latency_ms, attempt_count=1, error=error,
            )

        try:
            import base64
            with open(pdf_path, "rb") as f:
                pdf_b64 = base64.standard_b64encode(f.read()).decode("utf-8")
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return AIResponse(
                success=False, provider="claude_sonnet", model=self.model,
                latency_ms=latency_ms, attempt_count=1, error=self._clean_error(str(e)),
            )

        last_error = None
        for attempt in range(1, max_retries + 2):
            try:
                success, text, error = self._real_file_call(pdf_b64, temperature, max_tokens)
                if not success:
                    raise RuntimeError(error)

                parsed = self._try_parse_json(text)
                if parsed is None:
                    raise ValueError("response did not contain parseable JSON")

                rows = parsed.get("rows", []) or []
                columns_found = parsed.get("columns_found", []) or []
                vendor_name = parsed.get("vendor_name") or None
                statement_date = parsed.get("statement_date") or None
                print(f"  [ClaudeSonnetClient] Columns found: {columns_found}")

                invoices, fallback_warnings = self._rows_to_invoices(rows, columns_found)
                result = self._build_schema(
                    pdf_path, invoices, columns_found,
                    bool(parsed.get("_salvaged")), fallback_warnings,
                    vendor_name=vendor_name, statement_date=statement_date,
                )

                latency_ms = (time.monotonic() - start) * 1000
                text_out = json.dumps(result)
                return AIResponse(
                    success=True, text=text_out, parsed_json=result,
                    model=self.model, provider="claude_sonnet",
                    latency_ms=latency_ms, attempt_count=attempt,
                )
            except Exception as e:
                last_error = self._clean_error(str(e))
                if attempt <= max_retries:
                    time.sleep(backoff * (multiplier ** (attempt - 1)))

        latency_ms = (time.monotonic() - start) * 1000
        return AIResponse(
            success=False, provider="claude_sonnet", model=self.model,
            latency_ms=latency_ms, attempt_count=max_retries + 1, error=last_error,
        )

    def _real_file_call(self, pdf_b64: str, temperature, max_tokens):
        """Real Claude API call via Azure Foundry, with an inline base64 PDF
        document block — STREAMING (client.messages.stream() +
        get_final_message()), required for a single whole-document
        extraction call that can run long (see module docstring)."""
        try:
            client = self._build_client()
            with client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=self.config.get("timeout_seconds", 600),
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": EXTRACTION_PROMPT,
                        },
                    ],
                }],
            ) as stream:
                message = stream.get_final_message()
            return True, message.content[0].text, None
        except Exception as e:
            return False, "", self._clean_error(str(e))

    # ---- column-agnostic mapping (same logic as GeminiClient) ----

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
        (e.g. '60 35 8923821') — a content-based signal, not header order."""
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

        # Tolerant fallback mapping — standard keyword-based mapping missed
        # this field for this row. Scan the row's raw values directly rather
        # than leaving the field null and letting the row silently fail
        # validation downstream.
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
            print(f"  [ClaudeSonnetClient] {msg}")
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
        (letters/digits/hyphens), not a date, not a currency figure."""
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
        field. Returns (key, value) or (None, None)."""
        for key, val in row.items():
            if val in exclude:
                continue
            if cls._looks_like_invoice_number(val):
                return key, val
        return None, None

    @classmethod
    def _fallback_amount(cls, row: dict, exclude=frozenset()):
        """Scan all values in `row` for the first one that looks like a
        currency figure (CURRENCY_LIKE_RE), skipping any value already
        claimed by another field. Requiring the currency shape — not just
        "parses as a number" — is deliberate: a bare invoice-number-shaped
        duplicate column (e.g. "8923821") parses as a float just as easily
        as "706.29" does, so accepting any numeric value would reintroduce
        invoice-number-as-amount cross-contamination (see module docstring).
        Returns (key, parsed_float) or (None, None)."""
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
            warnings.append(
                f"{len(fallback_warnings)} row(s) required value-based fallback column "
                f"mapping (standard header-keyword mapping didn't recognize a column for "
                f"invoice_number and/or outstanding_amount on those rows)."
            )

        return {
            "document_metadata": {
                "document_type": "VENDOR_STATEMENT",
                "source_file": os.path.basename(pdf_path),
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
            "columns_found": columns_found or [],
        }

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """Parse the {columns_found, rows} JSON a call returns. If truncated
        (max_tokens cut it off mid-object), salvage whatever complete row
        objects were written before the cutoff — same brace-counting
        strategy ClaudeClient/MistralClient/GeminiClient use for their own
        row shapes."""
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

        if "rate_limit" in raw_lower or "429" in raw:
            return "rate limited — try again shortly"

        if "overloaded_error" in raw_lower or "529" in raw:
            return "Claude API overloaded — try again shortly"

        if ("authentication_error" in raw_lower or "401" in raw
                or "invalid x-api-key" in raw_lower):
            return "invalid API key"

        if "permission_error" in raw_lower or "403" in raw:
            return "permission denied — check API key"

        if "timeout" in raw_lower or "timed out" in raw_lower:
            return "request timed out"

        if "connection" in raw_lower or "network" in raw_lower:
            return "network error"

        first_line = raw.split("\n")[0][:150]
        return first_line
