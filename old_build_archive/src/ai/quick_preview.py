"""
quick_preview.py

A fast, vendor/statement-period-only read of a PDF, for the upload page's
live preview (fills in the Vendor/Statement period fields the moment a
file is picked, before the user queues it for the real extraction).
Deliberately separate from the full extraction chain
(document_understanding_engine.py) — that call reads every invoice line
and can take minutes on a large statement; this one asks for exactly
three fields, so it comes back in well under that even on the same model.

Uses the generic ClaudeClient (see src/ai/claude_client.py) pointed at the
Sonnet deployment via a locally-built config, rather than
ClaudeSonnetClient (src/ai/claude_sonnet_client.py) — that class's
generate_with_file() hardcodes and always sends its own full-extraction
prompt regardless of what's passed in (by design, for the real extraction
path), and its truncation-detection logic is keyed to the
{columns_found, rows} extraction schema, neither of which apply to this
three-field response. ClaudeClient has no such extraction-specific
logic and honors the prompt it's given, so it's reused here with Sonnet's
deployment name substituted in — same endpoint/API key (one Azure
resource hosts both deployments), just a different model, no changes to
either existing AI client needed.

Never blocks or fails the real upload — any error here just means the
preview fields stay blank; the user can still queue the file normally.
"""

from datetime import datetime

from src.ai.claude_client import ClaudeClient

_SONNET_PREVIEW_CONFIG = {
    "provider": "claude_sonnet",
    "api_key_env_var": "AZURE_CLAUDE_API_KEY",
    "endpoint_env_var": "AZURE_CLAUDE_ENDPOINT",
    "deployment_env_var": "AZURE_CLAUDE_SONNET_DEPLOYMENT",
    "model": "claude-sonnet-4-6",
    "temperature": 0.1,
    "max_output_tokens": 512,
    "retry_policy": {"max_retries": 2, "backoff_seconds": 2, "backoff_multiplier": 2},
}

PREVIEW_PROMPT = """Look at this vendor statement PDF. Return ONLY a JSON object with exactly these fields, no other text, no markdown fences:

{
  "vendor_name": "the vendor/company name printed on this statement, or null if you can't find one",
  "statement_period_start": "the earliest invoice/transaction date shown on the statement, as YYYY-MM-DD, or null",
  "statement_period_end": "the latest invoice/transaction date shown on the statement, as YYYY-MM-DD, or null"
}

Do not extract or list any invoice line items — only these three fields."""


def _format_period(start_str, end_str):
    """"MMM YYYY" if the range falls in one month, "MMM YYYY - MMM YYYY"
    if it spans more than one, or None if neither date parsed."""
    def parse(s):
        try:
            return datetime.strptime(s, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    start, end = parse(start_str), parse(end_str)
    if not start and not end:
        return None
    start = start or end
    end = end or start
    if (start.year, start.month) == (end.year, end.month):
        return start.strftime("%b %Y")
    return f"{start.strftime('%b %Y')} - {end.strftime('%b %Y')}"


def detect_vendor_and_period(pdf_path: str) -> dict:
    """Best-effort {"vendor_name": str|None, "statement_period": str|None}.
    Never raises — any failure (missing key, API error, bad response)
    just comes back as both fields None."""
    try:
        client = ClaudeClient(_SONNET_PREVIEW_CONFIG)
        response = client.generate_with_file(pdf_path, PREVIEW_PROMPT)
    except Exception:
        return {"vendor_name": None, "statement_period": None}

    if not response.success or not response.parsed_json:
        return {"vendor_name": None, "statement_period": None}

    data = response.parsed_json
    vendor_name = data.get("vendor_name") or None
    statement_period = _format_period(
        data.get("statement_period_start"), data.get("statement_period_end")
    )
    return {"vendor_name": vendor_name, "statement_period": statement_period}
