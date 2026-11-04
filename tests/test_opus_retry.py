"""Opus re-extraction after a validation failure (src/ai/opus_retry.py, 2026-11-04):
Sonnet's read fails validation -> up to two Claude Opus reads, each validated;
the first pass is kept, else the statement fails with the last read."""
import json
import os

import pytest

from src.ai import client_factory, opus_retry
from src.ai.base_client import AIResponse
from src.ai.claude_sonnet_client import ClaudeSonnetClient
from src.ai.document_understanding_engine import DocumentUnderstandingEngine


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("EXTRACTION_OPUS_RETRY_ENABLED", "true")


def _schema(model, status, difference=None):
    return {"_model_used": model, "_provider_used": "claude_sonnet", "invoices": [{"invoice_number": "1"}],
            "validation": {"status": status, "difference": difference}}


class _Reads:
    """extract() returning the given Opus reads in order; validate() sets each
    read's status from the matching entry in `statuses`."""

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.extract_calls = 0
        self.validated = []

    def extract(self):
        self.extract_calls += 1
        status = self.statuses[self.extract_calls - 1]
        if status is None:
            return None
        return {"_model_used": "claude-opus-5-5", "_provider_used": "claude_sonnet", "invoices": [{"n": 1}],
                "_planned": status}

    def validate(self, s):
        self.validated.append(s)
        s["validation"] = {"status": s["_planned"], "difference": 0.0 if s["_planned"] == "matches" else 12.5}
        return s["validation"]


def _run(first, reads, **kw):
    return opus_retry.retry_on_validation_failure(first, reads.extract, reads.validate, **kw)


def test_switched_off_leaves_a_failure_alone(monkeypatch):
    monkeypatch.delenv("EXTRACTION_OPUS_RETRY_ENABLED")
    first, reads = _schema("claude-sonnet-4-6", "mismatch", -7096.25), _Reads([])
    assert _run(first, reads) is first
    assert reads.extract_calls == 0
    assert "detail" not in first["validation"]


@pytest.mark.parametrize("status", ["matches", "not_a_statement"])
def test_pass_or_not_a_statement_is_not_retried(status):
    first, reads = _schema("claude-sonnet-4-6", status), _Reads([])
    assert _run(first, reads) is first
    assert reads.extract_calls == 0


def test_first_opus_read_passes():
    first, reads = _schema("claude-sonnet-4-6", "mismatch", -7096.25), _Reads(["matches"])
    kept = _run(first, reads)
    assert reads.extract_calls == 1
    assert kept["_model_used"] == "claude-opus-5-5" and kept["validation"]["status"] == "matches"
    assert kept["validation"]["detail"]["extraction_attempts"] == [
        {"attempt": 1, "model": "claude-sonnet-4-6", "status": "mismatch", "difference": -7096.25},
        {"attempt": 2, "model": "claude-opus-5-5", "status": "matches", "difference": 0.0},
    ]


def test_second_opus_read_passes():
    first, reads = _schema("claude-sonnet-4-6", "mismatch", 46.5), _Reads(["mismatch", "matches"])
    kept = _run(first, reads)
    assert reads.extract_calls == 2
    assert kept is reads.validated[1] and kept["validation"]["status"] == "matches"
    assert [a["status"] for a in kept["validation"]["detail"]["extraction_attempts"]] == ["mismatch", "mismatch", "matches"]


def test_all_three_fail_keeps_the_last_read_and_fails():
    first, reads = _schema("claude-sonnet-4-6", "mismatch", 46.5), _Reads(["mismatch", "total_not_found"])
    kept = _run(first, reads)
    assert reads.extract_calls == 2  # exactly two Opus tries, never a third
    assert kept is reads.validated[1]
    assert kept["validation"]["status"] == "total_not_found"
    assert len(kept["validation"]["detail"]["extraction_attempts"]) == 3


def test_opus_reading_nothing_never_replaces_the_first_read():
    first, reads = _schema("claude-sonnet-4-6", "mismatch", 46.5), _Reads([None, None])
    kept = _run(first, reads)
    assert reads.extract_calls == 2
    assert kept is first and kept["validation"]["status"] == "mismatch"
    assert [a["status"] for a in kept["validation"]["detail"]["extraction_attempts"]] == ["mismatch", "no_rows", "no_rows"]


def test_a_read_with_rows_replaces_an_earlier_one_even_after_a_no_rows_try():
    first, reads = _schema("claude-sonnet-4-6", "mismatch", 46.5), _Reads([None, "mismatch"])
    kept = _run(first, reads)
    assert kept is reads.validated[0] and kept["_model_used"] == "claude-opus-5-5"


def test_no_opus_try_starts_after_the_deadline():
    first, reads = _schema("claude-sonnet-4-6", "mismatch", 46.5), _Reads(["matches"])
    kept = _run(first, reads, started=0.0, clock=lambda: opus_retry.OPUS_START_DEADLINE_SECONDS + 1)
    assert reads.extract_calls == 0
    assert kept is first
    assert kept["validation"]["detail"]["extraction_attempts"][-1]["status"] == "skipped_time_limit"


def test_deadline_reached_between_tries_stops_the_second():
    now = {"t": 0.0}
    first = _schema("claude-sonnet-4-6", "mismatch", 46.5)
    reads = _Reads(["mismatch", "matches"])
    extract = reads.extract

    def slow_extract():
        now["t"] += opus_retry.OPUS_START_DEADLINE_SECONDS + 1
        return extract()

    kept = opus_retry.retry_on_validation_failure(first, slow_extract, reads.validate, started=0.0,
                                                  clock=lambda: now["t"])
    assert reads.extract_calls == 1
    assert kept["validation"]["status"] == "mismatch"


def test_existing_validation_detail_is_kept():
    first, reads = _schema("claude-sonnet-4-6", "mismatch", 1.0), _Reads(["mismatch", "mismatch"])
    reads_validate = reads.validate

    def validate(s):
        v = reads_validate(s)
        v["detail"] = {"attempts": ["primary"]}
        return v

    kept = opus_retry.retry_on_validation_failure(first, reads.extract, validate)
    assert kept["validation"]["detail"]["attempts"] == ["primary"]
    assert len(kept["validation"]["detail"]["extraction_attempts"]) == 3


# --- the Opus client -------------------------------------------------------

@pytest.fixture
def opus_env(monkeypatch):
    monkeypatch.setenv("AZURE_CLAUDE_OPUS_API_KEY", "k")
    monkeypatch.setenv("AZURE_CLAUDE_OPUS_ENDPOINT", "https://sonnet-5-5.services.ai.azure.com/anthropic")
    monkeypatch.setenv("AZURE_CLAUDE_OPUS_DEPLOYMENT", "claude-opus-5-5")


def test_factory_builds_the_opus_client(opus_env):
    client = client_factory.get_ai_client("claude_opus")
    assert isinstance(client, ClaudeSonnetClient)
    assert client.model == "claude-opus-5-5"
    assert client.endpoint == "https://sonnet-5-5.services.ai.azure.com/anthropic"


def test_opus_request_sends_effort_and_no_temperature(opus_env, monkeypatch):
    sent = {}

    class _Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"stop_reason": "end_turn", "usage": {},
                    "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": "{}"}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, payload=json)
        return _Resp()

    monkeypatch.setattr("src.ai.claude_sonnet_client.requests.post", fake_post)
    client = client_factory.get_ai_client("claude_opus")
    ok, text, err = client._real_file_call("AAAA", client.config.get("temperature", 0.1), 64000)
    assert ok and text == "{}" and err is None
    assert sent["url"] == "https://sonnet-5-5.services.ai.azure.com/anthropic/v1/messages"
    assert sent["payload"]["model"] == "claude-opus-5-5"
    assert "temperature" not in sent["payload"]
    assert sent["payload"]["output_config"] == {"effort": "high"}


def test_sonnet_request_unchanged(monkeypatch):
    monkeypatch.setenv("AZURE_CLAUDE_API_KEY", "k")
    monkeypatch.setenv("AZURE_CLAUDE_SONNET_DEPLOYMENT", "claude-sonnet-4-6")
    sent = {}

    class _Resp:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"content": [{"type": "text", "text": "{}"}]}

    monkeypatch.setattr("src.ai.claude_sonnet_client.requests.post",
                        lambda url, headers=None, json=None, timeout=None: sent.update(payload=json) or _Resp())
    client = client_factory.get_ai_client("claude_sonnet")
    client._real_file_call("AAAA", 0.1, 64000)
    assert sent["payload"]["temperature"] == 0.1
    assert "output_config" not in sent["payload"]


# --- the engine's single read ---------------------------------------------

class _FakeClient:
    model = "claude-opus-5-5"

    def __init__(self, response):
        self.response = response

    def generate_with_file(self, path, prompt):
        return self.response


def _engine_read(monkeypatch, response, tmp_path):
    pdf = tmp_path / "s.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(client_factory, "get_ai_client", lambda name: _FakeClient(response))
    monkeypatch.setattr("src.ai.document_understanding_engine.upright_copy", lambda p: (p, 0))
    monkeypatch.setattr("src.ai.document_understanding_engine.log_ai_call", lambda *a, **k: None)
    return DocumentUnderstandingEngine().understand_with("claude_opus", str(pdf), statement_id="STMT-1")


def test_understand_with_returns_rows(monkeypatch, tmp_path):
    response = AIResponse(success=True, provider="claude_sonnet", model="claude-opus-5-5",
                          parsed_json={"invoices": [{"invoice_number": "26204"}]})
    result = _engine_read(monkeypatch, response, tmp_path)
    assert result["_model_used"] == "claude-opus-5-5"
    assert result["_provider_used"] == "claude_sonnet"  # same client: re-run tools keep working
    assert len(result["invoices"]) == 1


@pytest.mark.parametrize("response", [
    AIResponse(success=False, provider="claude_sonnet", model="claude-opus-5-5", error="HTTP 400"),
    AIResponse(success=True, provider="claude_sonnet", model="claude-opus-5-5", parsed_json={"invoices": []}),
])
def test_understand_with_failure_is_none_with_no_fallback(monkeypatch, tmp_path, response):
    called = []
    monkeypatch.setattr("src.ai.document_understanding_engine.extract_with_pdfplumber",
                        lambda p: called.append(p) or {})
    assert _engine_read(monkeypatch, response, tmp_path) is None
    assert called == []


def test_opus_config_is_valid_json():
    with open(os.path.join("config", "ai", "claude_opus_extraction.json"), encoding="utf-8") as f:
        config = json.load(f)
    assert config["temperature"] is None and config["model"] == "claude-opus-5-5"


def test_no_validation_status_is_not_retried():
    first, reads = {"invoices": [{"n": 1}]}, _Reads([])
    assert _run(first, reads) is first
    assert reads.extract_calls == 0


# --- wiring: run_intake() and the statement page -------------------------

import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
from test_intake_sharepoint_hook import TestBothStep8SitesCallTheHook  # noqa: E402


class TestRunIntakeUsesOpusRetry(TestBothStep8SitesCallTheHook):
    """run_intake() hands a failed read to the Opus retry and keeps what it returns."""

    def test_cache_hit_site(self):
        pass

    def test_normal_site_passes_parked_through(self):
        pass

    def test_normal_site(self):
        opus_read = {"document_metadata": {"document_type": "VENDOR_STATEMENT"},
                     "vendor_metadata": {"vendor_name": "Opus Vendor"},
                     "statement_metadata": {"statement_date": "09/30/2026"}, "invoices": [],
                     "_provider_used": "claude_sonnet", "_model_used": "claude-opus-5-5",
                     "validation": {"status": "matches"}}
        seen = {}

        def fake_retry(schema_result, extract, validate, started=None):
            seen["first"] = schema_result
            return opus_read

        self.patch(self.intake.opus_retry, "retry_on_validation_failure", fake_retry)
        self.run_normal_path()
        self.assertEqual(seen["first"]["vendor_metadata"]["vendor_name"], "Synthetic Vendor")
        self.assertEqual(self.hook_args()["vendor_name"], "Opus Vendor")
        stored = self.intake.write_intake_log.call_args
        self.assertIn(opus_read, list(stored.args) + list(stored.kwargs.values()))


class TestDetailPageReadBy(unittest.TestCase):

    def render(self, **extra):
        import test_pdf_row_match as prm_tests
        page = prm_tests.TestValidationPageBadge(methodName="test_method_labels")
        intake = {"statement_id": "F", "source_file": "f.pdf", "vendor_name": "Nashua Kia", "statement_period": "2026-10",
                  "statement_total_as_printed": 662.90, "validation_status": "matches", "validation_difference": 0.0,
                  "validation_method": "primary", "previous_balance": None, "previous_balance_source": None,
                  "ingestion_timestamp": "2026-11-04T12:39:00+00:00", "passed": True, "primary_computed": None,
                  "validation_attempts": [], **extra}
        page._patch(get_extraction_validation_detail=lambda sid: {"intake": intake, "computed_total": 662.90, "lines": []})
        try:
            return page._client().get("/validation/F").text
        finally:
            page.doCleanups()

    def test_reads_are_listed(self):
        html = self.render(extraction_model="claude-opus-5-5", extraction_attempts=[
            {"attempt": 1, "model": "claude-sonnet-4-6", "status": "mismatch", "difference": -7096.25},
            {"attempt": 2, "model": "claude-opus-5-5", "status": "no_rows", "difference": None},
            {"attempt": 3, "model": "claude-opus-5-5", "status": "matches", "difference": 0.0}])
        self.assertIn("Read by", html)
        self.assertIn("3 reads:", html)
        self.assertIn("claude-sonnet-4-6", html)
        self.assertIn("read no rows", html)
        self.assertIn("passed", html)

    def test_single_read_shows_only_the_model(self):
        html = self.render(extraction_model="claude-sonnet-4-6")
        self.assertIn("claude-sonnet-4-6", html)
        self.assertNotIn("extraction-attempts", html)
