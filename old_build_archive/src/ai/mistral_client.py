"""
mistral_client.py

Mistral Medium implementation of AIClient, via the direct Mistral API
(OpenAI-compatible chat completions format). The ONLY file that knows
Mistral's SDK/wire format.

Registered in client_factory.py as "mistral" — not part of the default
active_provider.json chain (claude_sonnet is primary — see RULES.md
RULE-04), but available for direct get_ai_client("mistral") access or a
deliberate provider swap, same pattern as the azure_gpt5_* configs.
[Corrected 2026-07-24, BCE Stage 3 documentation sweep follow-up — this
comment previously said "azure_doc_intel remains primary," stale relative
to active_provider.json's provider_chain; never part of any prior
documentation-sweep fix list.]

Unlike ClaudeClient/DocumentIntelligenceClient, this client cannot send the
PDF natively — validated during diagnostic testing that Mistral's
chat-completions image_url content part rejects application/pdf data URIs
outright ("Unsupported image url scheme"). So each page is rasterized to a
PNG (via pdf2image, same tool azure_openai_client.py already uses for
scanned pages) and sent as a separate image_url call — one call per PDF
page, aggregated into the Universal Financial Document Schema, same
per-page retry-once-then-record-failure shape as AzureOpenAIClient's
generate_with_file().

This client's extraction prompt intentionally does NOT ask for per-row
confidence or document/vendor/statement metadata — diagnostic testing
found the model's self-reported confidence and row counts were not
reliable signals (100% "HIGH" confidence regardless of known transcription
errors, and the model's own row count disagreeing with its own output on
12 of 14 test pages). So every row gets a fixed placeholder confidence
(ROW_CONFIDENCE), and document/vendor/statement metadata are left as
defaults — same spirit as DocumentIntelligenceClient's ROW_CONFIDENCE
constant for a layout-only extraction with no semantic classification.

The prompt asks for both a raw column-name-keyed dict AND a mapped
standard-fields dict per row (column-agnostic — works on any vendor's
header names, not a fixed list), so _row_to_invoice() reads from
row["mapped"] with a fallback to row["raw"] if a page response is missing
the "mapped" key. The raw dict is also stashed (as JSON) into the
Universal Financial Document Schema's `description` field — TEMPORARY,
so the full per-vendor column set is visible/queryable in bronze/silver
after a real pipeline run, not because `description` is the right home
for it long-term.
"""

import base64
import io
import json
import os
import re
import time
from typing import Callable, Optional

from .base_client import AIClient, AIResponse

ROW_CONFIDENCE = 0.75

EXTRACTION_PROMPT = """You are extracting data from a vendor statement PDF for an accounts payable system.
This is critical financial data — accuracy is essential.

STEP 1 — Identify all columns:
Look at the table header row and list every column name exactly as printed.

STEP 2 — Extract every row:
Extract every single data row from the table. For each row return:
- One entry per column exactly as printed in the PDF
- Use the exact column name from the header as the key
- If a cell is blank/empty return null
- Do NOT skip any rows
- Do NOT merge rows
- Do NOT calculate anything
- Do NOT include currency symbols in amounts

STEP 3 — Map to standard fields:
Also map the columns to these standard fields where you can identify them
(leave null if you cannot find a matching column):
- date: transaction or invoice date
- invoice_number: invoice or document reference number ONLY
  (ignore any account codes, route codes, store codes before the invoice number)
- charges: amount charged (may be called Amount, Charges, Invoice Amt, Debit etc)
- credits: credit or payment applied (may be called Credits, Payments, Credit Memo etc)
- amount_due: net balance or outstanding amount (may be called Amount Due,
  Balance, Outstanding, Net etc)
- due_date: payment due date if present
- ro_number: repair order number if present
- po_number: purchase order number if present
- description: any description or notes column if present
- shop: store, shop, or location name if present

Return JSON:
{
  columns_found: [list of all column names exactly as in PDF header],
  rows: [
    {
      raw: {column_name: value, ...},
      mapped: {date, invoice_number, charges, credits, amount_due,
               due_date, ro_number, po_number, description, shop}
    }
  ]
}"""


class MistralClient(AIClient):
    def __init__(self, config: dict, transport: Optional[Callable] = None):
        """
        config   : parsed config/ai/mistral.json
        transport: optional injectable callable for testing.
                   Signature: (pdf_path, config) -> (success, schema_dict, error)
                   Stands in for the entire real call (rasterization +
                   per-page requests), same convention as AzureOpenAIClient's
                   generate_with_file() transport injection point.
                   If None, uses the real Mistral API call.
        """
        self.config = config
        self._transport = transport

        self.api_key = os.environ.get(config.get("api_key_env_var", "MISTRAL_API_KEY"))
        self.endpoint = os.environ.get(config.get("endpoint_env_var", "MISTRAL_ENDPOINT"))
        self.model = (
            os.environ.get(config.get("deployment_env_var", "MISTRAL_DEPLOYMENT"))
            or config.get("model")
        )
        self.dpi = config.get("dpi", 300)

    def _missing_config_error(self) -> Optional[str]:
        if not self.api_key:
            return f"Missing API key — env var '{self.config.get('api_key_env_var')}' not set"
        if not self.endpoint:
            return f"Missing endpoint — env var '{self.config.get('endpoint_env_var')}' not set"
        if not self.model:
            return f"Missing model/deployment — env var '{self.config.get('deployment_env_var')}' not set"
        return None

    def generate(self, prompt: str, *, temperature=None, max_output_tokens=None) -> AIResponse:
        """Plain text-only completion — exists for AIClient interface parity.
        document_understanding_engine.py's primary path uses generate_with_file()
        instead; this is not exercised by the extraction pipeline."""
        temperature = temperature if temperature is not None else self.config.get("temperature", 0.1)
        max_tokens = max_output_tokens or self.config.get("max_output_tokens", 32000)
        retry_policy = self.config.get("retry_policy", {})
        max_retries = retry_policy.get("max_retries", 1)
        backoff = retry_policy.get("backoff_seconds", 2)
        multiplier = retry_policy.get("backoff_multiplier", 2)

        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="mistral", model=self.model or "", error=missing)

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
                        model=self.model, provider="mistral",
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
            success=False, provider="mistral", model=self.model,
            latency_ms=latency_ms, attempt_count=max_retries + 1, error=last_error,
        )

    def _real_text_call(self, prompt, temperature, max_tokens):
        try:
            import openai
            client = openai.OpenAI(base_url=self.endpoint, api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=self.config.get("timeout_seconds", 300),
                messages=[{"role": "user", "content": prompt}],
            )
            return True, response.choices[0].message.content, None
        except Exception as e:
            return False, "", self._clean_error(str(e))

    def generate_with_file(self, pdf_path: str, prompt: str) -> AIResponse:
        """
        Rasterize every page to a PNG and send one chat-completions call per
        page (Mistral rejects raw PDF data URIs — see module docstring).
        `prompt` is accepted for AIClient interface parity but unused — this
        client always sends its own EXTRACTION_PROMPT, validated during
        diagnostic testing; VISION_PROMPT is written for direct-PDF-native
        readers (Claude/Document Intelligence), not per-page raster images.
        """
        missing = self._missing_config_error()
        if missing:
            return AIResponse(success=False, provider="mistral", model=self.model or "", error=missing)

        start = time.monotonic()

        if self._transport:
            success, result, error = self._transport(pdf_path, self.config)
            latency_ms = (time.monotonic() - start) * 1000
            if success:
                text_out = json.dumps(result)
                return AIResponse(
                    success=True, text=text_out, parsed_json=result,
                    model=self.model, provider="mistral",
                    latency_ms=latency_ms, attempt_count=1,
                )
            return AIResponse(
                success=False, provider="mistral", model=self.model,
                latency_ms=latency_ms, attempt_count=1, error=error,
            )

        try:
            from pdf2image import convert_from_path
            images = convert_from_path(pdf_path, dpi=self.dpi)
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return AIResponse(
                success=False, provider="mistral", model=self.model,
                latency_ms=latency_ms, attempt_count=1,
                error=f"failed to rasterize PDF: {e}",
            )

        all_invoices = []
        warnings = []
        failed_pages = []
        total_attempts = 0
        all_columns_found = []  # ordered union across pages, dedup preserving first-seen order

        for page_num, img in enumerate(images, start=1):
            success, rows, columns_found, error, attempts_used = self._process_single_page(img, page_num)
            total_attempts += attempts_used

            if not success:
                failed_pages.append(page_num)
                warnings.append(f"Page {page_num} failed after retry: {error}")
                continue

            print(f"  [MistralClient] Page {page_num} columns_found: {columns_found}")
            for col in columns_found or []:
                if col not in all_columns_found:
                    all_columns_found.append(col)

            for row_num, row in enumerate(rows, start=1):
                all_invoices.append(self._row_to_invoice(row, page_num, row_num))

        print(f"  [MistralClient] All columns found across document: {all_columns_found}")

        latency_ms = (time.monotonic() - start) * 1000

        if not all_invoices and len(failed_pages) == len(images):
            return AIResponse(
                success=False, provider="mistral", model=self.model,
                latency_ms=latency_ms, attempt_count=total_attempts,
                error=f"all {len(images)} page(s) failed: {'; '.join(warnings) or 'unknown error'}",
            )

        if failed_pages:
            warnings.append(
                f"Page(s) {failed_pages} could not be extracted after retry and are "
                f"missing from this result — {len(all_invoices)} invoices recovered from "
                f"the remaining {len(images) - len(failed_pages)} page(s)."
            )

        result = self._build_schema(pdf_path, images, all_invoices, warnings, all_columns_found)
        text_out = json.dumps(result)
        return AIResponse(
            success=True, text=text_out, parsed_json=result,
            model=self.model, provider="mistral",
            latency_ms=latency_ms, attempt_count=total_attempts,
        )

    def _process_single_page(self, img, page_num):
        """Retry once per page (fresh call, no retry_policy backoff/multiplier —
        matching AzureOpenAIClient's per-page retry-once mechanism, distinct
        from generate()'s own outer retry loop)."""
        error = None
        for attempt in (1, 2):
            success, rows, columns_found, error = self._real_page_call(img)
            if success:
                return True, rows, columns_found, None, attempt
            if attempt == 1:
                backoff = self.config.get("retry_policy", {}).get("backoff_seconds", 2)
                time.sleep(backoff)
        return False, None, None, error, 2

    def _real_page_call(self, img):
        """One chat-completions call for a single rasterized page image.
        Returns (success, rows, columns_found, error)."""
        try:
            import openai
            client = openai.OpenAI(base_url=self.endpoint, api_key=self.api_key)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

            response = client.chat.completions.create(
                model=self.model,
                max_tokens=self.config.get("max_output_tokens", 32000),
                temperature=self.config.get("temperature", 0.1),
                timeout=self.config.get("timeout_seconds", 300),
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }],
            )
            text = response.choices[0].message.content
            parsed = self._try_parse_json(text)
            if parsed is None:
                return False, None, None, "response did not contain parseable JSON"
            return True, parsed.get("rows", []) or [], parsed.get("columns_found", []) or [], None
        except Exception as e:
            return False, None, None, self._clean_error(str(e))

    def _row_to_invoice(self, row: dict, page_num: int, row_num: int) -> dict:
        """Map this client's {raw: {...}, mapped: {...}} row shape onto the
        Universal Financial Document Schema invoice fields. Falls back to
        treating the row itself as the mapped dict if "mapped" is missing
        (e.g. an older cached/salvaged response). The raw per-column dict is
        stashed into `description` as JSON — TEMPORARY, purely so the full
        column set survives into bronze/silver for inspection (see module
        docstring); it is not a real description."""
        raw = row.get("raw") if isinstance(row, dict) else None
        mapped = row.get("mapped") if isinstance(row, dict) else None
        if not mapped:
            mapped = raw if raw else (row if isinstance(row, dict) else {})

        return {
            "invoice_number": mapped.get("invoice_number"),
            "invoice_date": mapped.get("date"),
            "due_date": mapped.get("due_date"),
            "amount": self._to_float(mapped.get("charges")),
            "outstanding_amount": self._to_float(mapped.get("amount_due")),
            "ro_number": mapped.get("ro_number"),
            "po_number": mapped.get("po_number"),
            "work_order_number": None,
            "description": json.dumps(raw) if raw else mapped.get("description"),
            "credit": self._to_float(mapped.get("credits")),
            "shop": mapped.get("shop"),
            "page_number": page_num,
            "row_number": row_num,
            "line_confidence": ROW_CONFIDENCE,
        }

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

    def _build_schema(self, pdf_path: str, images: list, invoices: list, warnings: list,
                       columns_found: Optional[list] = None) -> dict:
        statement_total = sum(
            inv.get("outstanding_amount", 0) or 0
            for inv in invoices
            if inv.get("outstanding_amount") is not None
        )
        confidence = ROW_CONFIDENCE if invoices else 0.20

        return {
            "document_metadata": {
                "document_type": "VENDOR_STATEMENT",
                "source_file": os.path.basename(pdf_path),
                "page_count": len(images),
                # not classified — this client's prompt doesn't ask Mistral
                # to identify document type at all (see module docstring)
                "document_type_confidence": 0.60,
            },
            "vendor_metadata": {
                "vendor_name": None,
                "vendor_address": None,
                "shop_or_entity": [],
                "vendor_confidence": 0.10,
            },
            "statement_metadata": {
                "statement_date": None,
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
            # TEMPORARY diagnostic field — the union of column headers seen
            # across all pages, for inspecting column-agnostic mapping
            # quality. Not part of the standard Universal Financial Document
            # Schema; downstream consumers (write_to_bronze etc.) ignore
            # unknown top-level keys, so this rides along harmlessly.
            "columns_found": columns_found or [],
        }

    def _try_parse_json(self, text: str) -> Optional[dict]:
        """Parse the {rows: [...]} JSON a page call returns. If truncated
        (max_tokens cut it off mid-object), salvage whatever complete row
        objects were written before the cutoff — same brace-counting
        strategy ClaudeClient/AzureOpenAIClient use for their {invoices:...}
        shape, adapted to this client's {rows:...} shape."""
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
                                    # A valid row is {"raw": {...}, "mapped": {...}} —
                                    # accept it if either half parsed cleanly.
                                    if isinstance(obj, dict) and (obj.get('raw') or obj.get('mapped')):
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
        return {"rows": salvaged, "_salvaged": True}

    def _clean_error(self, raw_error: str) -> str:
        if not raw_error:
            return "unknown error"

        raw = str(raw_error)
        raw_lower = raw.lower()

        if "rate_limit" in raw_lower or "429" in raw:
            return "rate limited — try again shortly"

        if "authentication" in raw_lower or "401" in raw or "invalid api key" in raw_lower:
            return "invalid API key"

        if "permission" in raw_lower or "403" in raw:
            return "permission denied — check API key"

        if "unsupported image url scheme" in raw_lower:
            return "endpoint rejected the image payload — check content type / DPI"

        if "timeout" in raw_lower or "timed out" in raw_lower:
            return "request timed out"

        if "connection" in raw_lower or "network" in raw_lower:
            return "network error"

        first_line = raw.split("\n")[0][:150]
        return first_line
