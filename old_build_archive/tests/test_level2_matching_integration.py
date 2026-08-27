"""
tests/test_level2_matching_integration.py

End-to-end integration test: run_intake() -> generate_mock_erp() ->
run_matching(), proving Level 2 (RO number + amount) matching fires
correctly through the REAL pipeline chain -- not just via classify_match()
called directly in isolation (see tests/test_matching_engine.py). The only
thing faked is the AI network call (client_factory.get_ai_client(),
monkeypatched to a scripted FakeVisionClient) -- run_intake(),
generate_mock_erp(), and run_matching() are the real production functions,
run against a real (temporary file) SQLite database with the full
migration history applied.

See PIPELINE_VERIFICATION_REPORT.md Finding 4: Level 2 and tolerance-based
matching had never been exercised through a real pipeline run to date --
only provable in isolation, because src/mock_erp/generator.py's controlled
exceptions (before the "renumbered_invoices" addition in this same commit)
never varied invoice_number between the vendor-statement and ERP sides.
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse.migrations import apply_pending_migrations

SAMPLE_PDF = os.path.join(
    os.path.dirname(__file__), "..", "sample_data", "Synthetic_Reconciliation_Test_Document.pdf"
)


class FakeVisionClient:
    """Stands in for the active AI provider -- generate_with_file() returns
    a scripted Universal Financial Document Schema result instead of
    calling any real API."""

    def __init__(self, response):
        self._response = response
        self.model = "fake-model"
        self.config = {"model": "fake-model"}

    def generate_with_file(self, pdf_path, prompt):
        return self._response


def _make_response(invoices):
    from src.ai.base_client import AIResponse

    parsed = {
        "document_metadata": {
            "document_type": "VENDOR_STATEMENT", "source_file": "test.pdf",
            "page_count": 1, "document_type_confidence": 0.95,
        },
        "vendor_metadata": {
            "vendor_name": "Level2 Test Vendor", "vendor_address": None,
            "shop_or_entity": [], "vendor_confidence": 0.9,
        },
        "statement_metadata": {
            "statement_date": "2026-07-01", "statement_period_start": "2026-07-01",
            "statement_period_end": "2026-07-31", "currency": "USD",
            "statement_total_as_printed": None, "statement_confidence": 0.9,
        },
        "invoices": invoices,
        "extraction_confidence": {
            "overall": 0.95, "table_detection_confidence": 0.95, "column_mapping_confidence": 0.95,
        },
        "warnings": [],
    }
    return AIResponse(
        success=True, text=json.dumps(parsed), parsed_json=parsed,
        model="fake-model", provider="fake", latency_ms=10.0, attempt_count=1,
    )


# STMT-100's invoice_number is renumbered on the ERP side (see setUp's temp
# scenario config) so Level 1 (exact invoice_number) genuinely cannot match
# it -- only Level 2 (RO + amount) can. STMT-200 has no ro_number and is
# left alone, so it can only match via Level 1 -- a control proving the
# pipeline still works normally alongside the Level 2 case, not that
# everything falls through to it.
INVOICES = [
    {
        "invoice_number": "STMT-100", "invoice_date": "2026-07-01", "due_date": None,
        "amount": 500.00, "outstanding_amount": 500.00, "ro_number": "RO-777",
        "po_number": None, "work_order_number": None, "description": "Level 2 candidate",
        "credit": None, "shop": None, "page_number": 1, "row_number": 1, "line_confidence": 0.95,
    },
    {
        "invoice_number": "STMT-200", "invoice_date": "2026-07-02", "due_date": None,
        "amount": 300.00, "outstanding_amount": 300.00, "ro_number": None,
        "po_number": None, "work_order_number": None, "description": "Level 1 control",
        "credit": None, "shop": None, "page_number": 1, "row_number": 2, "line_confidence": 0.95,
    },
]


class TestLevel2MatchingFiresThroughRealPipeline(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        conn = sqlite3.connect(self.tmp_db.name)
        apply_pending_migrations(conn)
        conn.close()
        self.addCleanup(os.remove, self.tmp_db.name)

        db_patcher = mock.patch("src.lakehouse.connection.DB_PATH", self.tmp_db.name)
        db_patcher.start()
        self.addCleanup(db_patcher.stop)

        # Defensive: guarantee SQLite is used regardless of the invoking
        # shell's environment (this repo's real pipeline scripts pick Azure
        # SQL whenever AZURE_SQL_SERVER is set -- see src/lakehouse/connection.py).
        azure_patcher = mock.patch.dict(os.environ, {"AZURE_SQL_SERVER": ""})
        azure_patcher.start()
        self.addCleanup(azure_patcher.stop)

        self.tmp_scenario = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({
            "default_erp_status": "POSTED",
            "posting_date_lag_days": {"min": 1, "max": 1},
            "controlled_exceptions": {
                "missing_invoices": [],
                "amount_mismatches": {},
                "duplicate_invoices": [],
                "pending_posting": [],
                "renumbered_invoices": {"STMT-100": "ERP-999"},
            },
        }, self.tmp_scenario)
        self.tmp_scenario.close()
        self.addCleanup(os.remove, self.tmp_scenario.name)

        import src.ai.client_factory as factory
        original_get_client = factory.get_ai_client
        fake_response = _make_response(INVOICES)
        factory.get_ai_client = lambda provider_name=None: FakeVisionClient(fake_response)
        self.addCleanup(setattr, factory, "get_ai_client", original_get_client)

    @staticmethod
    def _load_intake_module():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "intake_level2_test",
            os.path.join(os.path.dirname(__file__), "..", "notebooks", "01_document_intake.py"),
        )
        intake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(intake)
        return intake

    def test_level2_ro_and_amount_match_fires_when_invoice_numbers_differ(self):
        intake = self._load_intake_module()
        intake_result = intake.run_intake(pdf_path=SAMPLE_PDF, statement_id="STMT-LEVEL2-TEST")
        self.assertEqual(intake_result["bronze_count"], 2)

        from src.mock_erp.generator import generate_mock_erp, normalize_erp_to_silver
        counts = generate_mock_erp("STMT-LEVEL2-TEST", config_path=self.tmp_scenario.name)
        self.assertEqual(counts["renumbered"], 1)
        normalize_erp_to_silver("STMT-LEVEL2-TEST")

        from src.lakehouse.connection import execute_query
        erp_rows = execute_query(
            "SELECT invoice_number FROM silver_reconciliation_standard "
            "WHERE statement_id = ? AND record_source = 'INTERNAL_ERP'",
            ["STMT-LEVEL2-TEST"],
        )
        erp_invoice_numbers = [r["invoice_number"] for r in erp_rows]
        # Confirm the ERP side genuinely has a DIFFERENT invoice_number for
        # the renumbered row -- Level 1 has no way to match this by
        # invoice_number alone.
        self.assertNotIn("STMT-100", erp_invoice_numbers)
        self.assertIn("ERP-999", erp_invoice_numbers)

        from src.matching.engine import run_matching
        summary = run_matching("STMT-LEVEL2-TEST")
        self.assertEqual(summary["matched_count"], 2)
        self.assertEqual(summary["exception_count"], 0)

        matches = execute_query(
            "SELECT invoice_number, match_level, match_confidence FROM gold_matched_invoices "
            "WHERE statement_id = ?",
            ["STMT-LEVEL2-TEST"],
        )
        by_invoice = {m["invoice_number"]: m for m in matches}

        # STMT-100: invoice numbers differ (STMT-100 vs ERP-999) -- only
        # resolvable via Level 2 (RO-777 + $500.00 agree on both sides).
        self.assertEqual(by_invoice["STMT-100"]["match_level"], 2)
        self.assertEqual(by_invoice["STMT-100"]["match_confidence"], 0.80)

        # STMT-200: control -- no ro_number, matches normally via Level 1,
        # proving this run doesn't just fall through everything to Level 2.
        self.assertEqual(by_invoice["STMT-200"]["match_level"], 1)
        self.assertEqual(by_invoice["STMT-200"]["match_confidence"], 1.00)


if __name__ == "__main__":
    unittest.main(verbosity=2)
