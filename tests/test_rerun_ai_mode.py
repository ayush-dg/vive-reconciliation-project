"""
tests/test_rerun_ai_mode.py

scripts/rerun_in_place.py --allow-ai (src/rerun/in_place.py "AI mode",
2026-10-12): extract-only -> dry run from the saved file -> apply.

The model is never called: ClaudeSonnetClient._real_file_call is a fake that
returns a fixed JSON body and token usage. Azure SQL is the same SQLite world
as tests/test_rerun_in_place.py, so "nothing written" is checked against
every table. SYNTHETIC data only.
"""

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.ai.claude_sonnet_client import ClaudeSonnetClient  # noqa: E402
from src.lakehouse import connection  # noqa: E402
from src.rerun import in_place  # noqa: E402
from test_rerun_in_place import HASH, SID, RerunTestCase, seed  # noqa: E402

ROWS = [{"Date": "08/01/26", "Invoice": "INV0001", "Amount": 100.0, "Due": 100.0, "confidence": 0.95},
        {"Date": "08/02/26", "Invoice": "INV0002", "Amount": 250.5, "Due": 250.5, "confidence": 0.95},
        {"Date": "08/03/26", "Invoice": "INV0003", "Amount": 49.5, "Due": 49.5, "confidence": 0.95}]
USAGE = {"input_tokens": 12000, "output_tokens": 3000}
COST = round(12000 / 1e6 * 3 + 3000 / 1e6 * 15, 4)


def fake_call(calls):
    def call(self, pdf_b64, temperature, max_tokens):
        calls.append(len(pdf_b64))
        self._last_stop_reason = "end_turn"
        self._usage_log.append({**USAGE, "stop_reason": "end_turn"})
        body = {"vendor_name": "Synthetic Parts - AUTOLY", "statement_date": "08/31/2026",
                "statement_total_as_printed": 400.0, "columns_found": ["Date", "Invoice", "Amount", "Due"], "rows": ROWS}
        return True, json.dumps(body), None
    return call


class AiModeCase(RerunTestCase):
    route = "ai"

    def setUp(self):
        super().setUp()
        seed(self.world)
        self.ai_dir = os.path.join(self.world.dir, "ai")
        self.calls = []
        env = {"AZURE_CLAUDE_API_KEY": "test-key", "AZURE_CLAUDE_SONNET_DEPLOYMENT": "claude-sonnet-4-6"}
        config = {"api_key_env_var": "AZURE_CLAUDE_API_KEY", "deployment_env_var": "AZURE_CLAUDE_SONNET_DEPLOYMENT",
                  "retry_policy": {"max_retries": 0, "backoff_seconds": 0}}
        with mock.patch.dict(os.environ, env):
            self.client = ClaudeSonnetClient(config)
        for target, value in (("src.ai.client_factory.get_ai_client", lambda *a, **k: self.client),
                              ("src.ai.document_understanding_engine.upright_copy", lambda p: (p, [])),
                              ("src.ai.claude_sonnet_client.ClaudeSonnetClient._real_file_call", fake_call(self.calls))):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def extract(self, sha=HASH):
        with mock.patch("builtins.print"):
            return in_place.extract_only(self.intake, SID, self.pdf, sha, self.ai_dir)

    def dry_run_from(self, path):
        state = in_place.load_state(self.io, SID)
        doc = in_place.load_extraction(path, state)
        new = in_place.new_from_extraction(self.io, self.intake, state, self.pdf, doc)
        decision = in_place.silver_matching_decision(self.io, state, new)
        return state, new, decision, in_place.plan(state, new, decision)


class TestExtractOnly(AiModeCase):

    def test_extract_only_writes_nothing_and_records_usage_and_cost(self):
        before = self.world.snapshot()
        out = self.extract()
        self.assertEqual(self.world.snapshot(), before)          # every Azure SQL / Fabric table unchanged
        self.assertEqual(self.calls and len(self.calls), 1)
        doc = json.load(open(out["path"], encoding="utf-8"))
        self.assertEqual((doc["statement_id"], doc["document_hash"]), (SID, HASH))
        self.assertEqual(len(doc["schema_result"]["invoices"]), 3)
        self.assertEqual(doc["usage"], [{**USAGE, "stop_reason": "end_turn"}])
        self.assertEqual(doc["cost_usd"], COST)
        self.assertEqual(doc["upload_plan"]["path"], "as_is")
        ledger = in_place.read_ledger(os.path.join(self.ai_dir, in_place.AI_LEDGER_NAME))
        self.assertEqual(ledger["total_usd"], COST)

    def test_database_is_blocked_while_extracting(self):
        with in_place._NoDatabase():
            with self.assertRaisesRegex(RuntimeError, "blocked"):
                connection.execute_query("SELECT 1", [])
        self.assertEqual(connection.execute_query("SELECT 1 AS one", []), [{"one": 1}])  # restored afterwards

    def test_ai_audit_row_is_held_back_not_written(self):
        out = self.extract()
        self.assertEqual(self.world.sql("SELECT COUNT(*) AS n FROM ai_audit_log")[0]["n"], 0)
        self.assertEqual(json.load(open(out["path"]))["ai_audit"]["provider"], "claude_sonnet")

    def test_hash_mismatch_is_refused_before_any_request(self):
        with self.assertRaisesRegex(in_place.RefusedError, "SHA-256"):
            self.extract(sha="b" * 64)
        self.assertEqual(self.calls, [])

    def test_cost_cap_refuses_before_any_request(self):
        os.makedirs(self.ai_dir, exist_ok=True)
        ledger = {"cap_usd": 3.0, "runs": [{"statement_id": "earlier", "usd": 2.99}], "total_usd": 2.99}
        json.dump(ledger, open(os.path.join(self.ai_dir, in_place.AI_LEDGER_NAME), "w"))
        with self.assertRaisesRegex(in_place.RefusedError, "cost cap"):
            self.extract()
        self.assertEqual(self.calls, [])

    def test_a_deterministic_route_is_refused(self):
        self.route = "python_library"
        with self.assertRaisesRegex(in_place.RefusedError, "deterministic"):
            self.extract()
        self.assertEqual(self.calls, [])


class TestDryRunAndApply(AiModeCase):

    def test_dry_run_reads_the_saved_file_and_never_calls_the_ai(self):
        out = self.extract()
        self.calls.clear()
        before = self.world.snapshot()
        state, new, decision, the_plan = self.dry_run_from(out["path"])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(the_plan["fingerprint"], in_place.ai_fingerprint(state, out["sha256"]))
        self.assertNotEqual(the_plan["fingerprint"], in_place.fingerprint(state))
        self.assertEqual(the_plan["validation"]["to"]["status"], "matches")

    def test_same_file_gives_the_same_plan_twice(self):
        out = self.extract()
        self.assertEqual(self.dry_run_from(out["path"])[3]["fingerprint"], self.dry_run_from(out["path"])[3]["fingerprint"])

    def test_apply_refuses_without_the_saved_file(self):
        state = in_place.load_state(self.io, SID)
        with self.assertRaisesRegex(in_place.RefusedError, "no saved AI extraction"):
            in_place.load_extraction(os.path.join(self.ai_dir, "missing.json"), state)

    def test_apply_refuses_when_the_saved_file_changed_after_the_dry_run(self):
        out = self.extract()
        state, new, decision, the_plan = self.dry_run_from(out["path"])
        doc = json.load(open(out["path"]))
        doc["schema_result"]["invoices"][0]["outstanding_amount"] = 1000.0
        json.dump(doc, open(out["path"], "w"))
        _, new2, decision2, _ = self.dry_run_from(out["path"])
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b")], the_plan)
        before = self.world.snapshot()
        with self.assertRaisesRegex(in_place.RefusedError, "changed since the dry run"):
            in_place.apply(self.io, self.intake, state, new2, decision2, expected_fingerprint=the_plan["fingerprint"],
                           backup_paths=paths)
        self.assertEqual(self.world.snapshot(), before)

    def test_apply_writes_the_rows_and_the_held_back_audit_row(self):
        out = self.extract()
        state, new, decision, the_plan = self.dry_run_from(out["path"])
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b")], the_plan)
        with mock.patch("builtins.print"):
            in_place.apply(self.io, self.intake, state, new, decision, expected_fingerprint=the_plan["fingerprint"],
                           backup_paths=paths)
        rows = self.world.sql("SELECT raw_invoice_number FROM bronze_vendor_statement_raw WHERE statement_id = ? ORDER BY id", [SID])
        self.assertEqual([r["raw_invoice_number"] for r in rows], ["INV0001", "INV0002", "INV0003"])
        self.assertEqual(self.world.sql("SELECT COUNT(*) AS n FROM ai_audit_log WHERE statement_id = ?", [SID])[0]["n"], 1)


class TestCli(AiModeCase):

    def run_cli(self, *argv):
        from scripts import rerun_in_place as cli
        with mock.patch("builtins.print"):
            return cli.main(list(argv), io=self.io, intake=self.intake)

    def test_allow_ai_requires_a_statement_id(self):
        with self.assertRaises(SystemExit):
            self.run_cli("--allow-ai", "--extract-only", "--pdf", self.pdf, "--expected-sha256", HASH)
        self.assertEqual(self.calls, [])

    def test_ai_steps_require_allow_ai(self):
        for argv in (("--statement-id", SID, "--extract-only", "--pdf", self.pdf, "--expected-sha256", HASH),
                     ("--statement-id", SID, "--from-extraction", "x.json")):
            with self.subTest(argv=argv), self.assertRaises(SystemExit):
                self.run_cli(*argv)
        self.assertEqual(self.calls, [])

    def test_allow_ai_apply_without_a_saved_file_is_refused(self):
        before = self.world.snapshot()
        code = self.run_cli("--allow-ai", "--statement-id", SID, "--from-extraction", os.path.join(self.ai_dir, "none.json"),
                            "--pdf", self.pdf, "--apply", "--confirm", "0" * 16)
        self.assertEqual(code, 2)
        self.assertEqual(self.world.snapshot(), before)

    def test_extract_only_through_the_cli(self):
        before = self.world.snapshot()
        code = self.run_cli("--allow-ai", "--statement-id", SID, "--extract-only", "--pdf", self.pdf,
                            "--expected-sha256", HASH, "--ai-dir", self.ai_dir)
        self.assertEqual(code, 0)
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(len([f for f in os.listdir(self.ai_dir) if f.startswith("ai_extraction_")]), 1)


if __name__ == "__main__":
    unittest.main()
