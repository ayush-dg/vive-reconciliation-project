"""
tests/test_rerun_in_place.py

src/rerun/in_place.py -- re-running one stored statement in place with a
deterministic extractor. Azure SQL is a real SQLite database built from
migrations/*.sql, so the intake's own writers (write_to_bronze,
normalize_to_silver, update_cache, ...) run for real; the Fabric Warehouse
and Lakehouse are in-memory fakes, and the extractor is a fake engine (the
real extractors are covered by their own tests and the offline replays).

Adversarial: every refusal (AI route, 0 rows, hash mismatch, non-OPEN
exception, duplicate intake rows, jobs in flight, changed state, no backup)
leaves every table untouched; a dry run writes nothing; the intake row is
UPDATEd, never deleted; old Lakehouse rows never survive next to new ones;
no other statement's rows change; undo restores everything.
"""

import contextlib
import copy
import datetime as dt
import decimal
import glob
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.lakehouse import connection  # noqa: E402
from src.lakehouse.bronze_unnest import _explode  # noqa: E402
from src.rerun import in_place  # noqa: E402
from test_oct1_intake_worker_web import load_intake  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
SID, OTHER, COPY = "STMT-AAAA0001", "STMT-BBBB0002", "STMT-CCCC0003"
HASH = "a" * 64
VENDOR = "Synthetic Parts - AUTOLY"
VENDOR_ID = "SYNTHETIC_PARTS_-_AUTOLY"


class World:
    """Azure SQL (SQLite, real intake writers) + Fabric fakes."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="rerun_test_")
        self.db = os.path.join(self.dir, "recon.db")
        conn = sqlite3.connect(self.db)
        for f in sorted(glob.glob(os.path.join(ROOT, "migrations", "*.sql"))):
            conn.executescript(open(f, encoding="utf-8").read())
        conn.commit()
        conn.close()
        self.wh = {t: [] for t in in_place.SILVER_TABLES + in_place.RECON_TABLES + ("silver.vendor_field_mapping",)}
        self.lh = {t: [] for t in in_place.LAKEHOUSE_TABLES}
        self.calls = []
        self.visible_fields = None  # None = the endpoint shows what's in self.lh
        self.fail_append = set()

    def sql(self, sql, params=()):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.commit()
        conn.close()
        return rows

    def insert(self, table, **row):
        self.sql(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))

    def snapshot(self):
        az = {t: self.sql(f"SELECT * FROM {t} ORDER BY id") for t in (
            "document_intake_log", "bronze_vendor_statement_raw", "silver_reconciliation_standard", "gold_exceptions",
            "validation_document_review_queue", "ai_audit_log", "extraction_cache", "jobs")}
        return json.dumps({"az": az, "wh": self.wh, "lh": self.lh}, sort_keys=True, default=str)


class FakeIO:
    def __init__(self, world):
        self.w = world

    def az_query(self, sql, params=()):
        return connection.execute_query(sql, list(params))

    def az_exec(self, sql, params=()):
        connection.execute_sql(sql, list(params))

    def wh_query(self, sql, params=()):
        m = re.match(r"SELECT \* FROM (\S+) WHERE statement_id = \?", sql)
        if m:
            return [dict(r) for r in self.w.wh[m.group(1)] if r["statement_id"] == params[0]]
        if sql.startswith("SELECT statement_id FROM silver.recon_summary WHERE statement_id IN"):
            return [{"statement_id": r["statement_id"]} for r in self.w.wh["silver.recon_summary"] if r["statement_id"] in params]
        if "FROM silver.vendor_field_mapping" in sql:
            return [{"raw_field_name": r["raw_field_name"], "canonical_field_name": r["canonical_field_name"]}
                    for r in self.w.wh["silver.vendor_field_mapping"] if r["vendor_id"] == params[0] and r["raw_field_name"] in params[1:]]
        raise AssertionError(f"unexpected warehouse query: {sql}")

    def wh_restore(self, table, statement_id, rows):
        self.w.wh[table] = [r for r in self.w.wh[table] if r["statement_id"] != statement_id] + [dict(r) for r in rows]

    def lh_query(self, sql, params=()):
        if "FROM bronze.unnested_statement_fields" in sql:
            rows = self.w.visible_fields if self.w.visible_fields is not None else self.w.lh["unnested_statement_fields"]
            return [dict(r) for r in rows if r["statement_id"] == params[0]]
        if "FROM bronze.raw_statement" in sql:
            return [{"n": sum(1 for r in self.w.lh["raw_statement"] if r["statement_id"] == params[0])}]
        raise AssertionError(f"unexpected lakehouse query: {sql}")

    def delta_read(self, table, statement_id):
        return [dict(r) for r in self.w.lh[table] if r["statement_id"] == statement_id], 7

    def delta_delete(self, table, statement_id):
        self.w.calls.append(("delta_delete", table))
        self.w.lh[table] = [r for r in self.w.lh[table] if r["statement_id"] != statement_id]

    def delta_append(self, table, rows):
        if table in self.w.fail_append:
            raise OSError(f"simulated write failure on {table}")
        self.w.lh[table] += [dict(r) for r in rows]

    def delta_columns(self, table):
        return ["statement_id", "raw_payload", "ingestion_timestamp"] if table.startswith("raw_statement") else []

    def download_pdf(self, url, dest):
        raise AssertionError("tests pass --pdf")


def raw_row(n, due, unalloc=0.0):
    return {"Date": f"08/{n:02d}/26", "Invoice": f"INV{n:04d}", "Amount": f"{due + unalloc:.2f}",
            "Due": f"{due:.2f}", "Unalloc.": f"{unalloc:.2f}"}


def new_invoices():
    rows = [(1, 100.0), (2, 250.5), (3, 49.5)]
    return [{"invoice_number": f"INV{n:04d}", "invoice_date": f"2026-08-{n:02d}", "outstanding_amount": due,
             "amount_due": due, "line_confidence": 1.0, "_raw_row": raw_row(n, due)} for n, due in rows]


class FakeEngine:
    invoices = None

    def understand(self, pdf_text, pdf_path, statement_id=None):
        invoices = copy.deepcopy(self.invoices if self.invoices is not None else new_invoices())
        return {"document_metadata": {"document_type": "VENDOR_STATEMENT"},
                "vendor_metadata": {"vendor_name": VENDOR, "shop_or_entity": ["Vive Collision Bow"]},
                "statement_metadata": {"statement_total_as_printed": 400.0, "statement_date": "08/31/2026",
                                       "statement_total_computed": round(sum(i.get("outstanding_amount") or 0 for i in invoices), 2)},
                "extraction_confidence": {"overall": 1.0}, "invoices": invoices, "warnings": [],
                "_provider_used": "python_library_pdfplumber", "_model_used": "extract_autoly"}


def seed(world, *, exception_status="OPEN", escalation=None, intake_rows=1, job_status="COMPLETED", cache=True,
         summary=True, mapping=True):
    old_ts = "2026-10-05T16:43:00+00:00"
    for i in range(intake_rows):
        world.insert("document_intake_log", document_id=f"doc-{i + 1}", document_hash=HASH, source_file="BOW SEB 0926.pdf",
                     ingestion_timestamp=old_ts, document_type="VENDOR_STATEMENT", vendor_name=VENDOR,
                     statement_period="2026-09", statement_id=SID, invoice_count=3, validation_status="mismatch",
                     validation_difference=8100.0, validation_method=None, statement_total_as_printed=400.0,
                     extraction_method="claude_sonnet", extraction_model="claude-sonnet-4-6",
                     blob_storage_path="https://example.invalid/vendor-statements/x.pdf")
    for n in range(1, 4):
        world.insert("bronze_vendor_statement_raw", vendor_id=VENDOR_ID, vendor_name=VENDOR, source_file="BOW SEB 0926.pdf",
                     statement_id=SID, statement_period="2026-09", row_number=n, raw_invoice_number=f"INV{n:04d}",
                     raw_outstanding_amount="2800.0", ingestion_timestamp=old_ts, version_number=2, previous_statement_id="STMT-PREV0000",
                     is_latest_version=1, raw_ai_response=json.dumps({"Inv Amount": "2800.00"}))
        world.insert("silver_reconciliation_standard", record_id=f"r{n}", record_source="VENDOR_STATEMENT", statement_id=SID,
                     vendor_id=VENDOR_ID, statement_period="2026-09", invoice_number=f"INV{n:04d}", outstanding_amount=2800.0,
                     version_number=2, is_latest_version=1)
    # Another statement for the same vendor + period: must never be touched.
    world.insert("silver_reconciliation_standard", record_id="other", record_source="VENDOR_STATEMENT", statement_id=OTHER,
                 vendor_id=VENDOR_ID, statement_period="2026-09", invoice_number="X1", outstanding_amount=1.0,
                 version_number=1, is_latest_version=1)
    world.insert("gold_exceptions", exception_id="legacy-1", statement_id=SID, vendor_id=VENDOR_ID, exception_status="OPEN")
    if cache:
        world.insert("extraction_cache", document_hash=HASH, statement_id=SID, source_file="BOW SEB 0926.pdf",
                     extraction_method="claude_sonnet", row_count=3, ingestion_timestamp=old_ts)
    world.insert("jobs", job_id="job-1", pdf_filename="BOW SEB 0926.pdf", pdf_path="x.pdf", submitted_at=old_ts,
                 statement_id=SID, status=job_status)
    world.lh["raw_statement"].append({"statement_id": SID, "raw_payload": json.dumps([{"Inv Amount": "2800.00"}] * 3),
                                      "ingestion_timestamp": dt.datetime(2026, 10, 5, 16, 43)})
    for n in range(3):
        world.lh["unnested_statement_lines"].append({"statement_id": SID, "line_number": n, "extraction_confidence": 0.9, "shop_name": None})
        world.lh["unnested_statement_fields"].append({"statement_id": SID, "line_number": n, "raw_field_name": "Inv Amount",
                                                      "raw_field_value": "2800.00"})
    world.lh["unnested_statement_fields"].append({"statement_id": OTHER, "line_number": 0, "raw_field_name": "Inv Amount",
                                                  "raw_field_value": "1.00"})
    world.wh["silver.statement"].append({"statement_id": SID, "vendor_id": VENDOR_ID, "statement_total": decimal.Decimal("8500.00")})
    world.wh["silver.statement_line"] += [{"statement_id": SID, "line_number": n, "charge_amount": decimal.Decimal("2800.00")} for n in range(3)]
    if summary:
        world.wh["silver.recon_summary"].append({"statement_id": SID, "total_invoice_count": 3, "exception_count": 1,
                                                 "reconciliation_timestamp": dt.datetime(2026, 10, 5, 17, 0)})
    world.wh["silver.recon_exceptions"].append({"statement_id": SID, "exception_id": "e1", "exception_status": exception_status,
                                                "escalation_status": escalation})
    world.wh["silver.recon_matched_invoices"] += [{"statement_id": SID, "match_id": "m1"}, {"statement_id": SID, "match_id": "m2"}]
    world.wh["silver.recon_summary"].append({"statement_id": OTHER, "total_invoice_count": 1, "exception_count": 0,
                                             "reconciliation_timestamp": dt.datetime(2026, 10, 1)})
    if mapping:
        world.wh["silver.vendor_field_mapping"] += [
            {"vendor_id": VENDOR_ID, "raw_field_name": "Invoice", "canonical_field_name": "invoice_number_ref"},
            {"vendor_id": VENDOR_ID, "raw_field_name": "Amount", "canonical_field_name": "charge_amount"},
            {"vendor_id": VENDOR_ID, "raw_field_name": "Due", "canonical_field_name": "amount_remaining"}]


class RerunTestCase(unittest.TestCase):
    route = "python_library"

    def setUp(self):
        self.world = World()
        self.addCleanup(shutil.rmtree, self.world.dir, ignore_errors=True)
        self.intake = load_intake()
        self.io = FakeIO(self.world)
        self.pdf = os.path.join(self.world.dir, "BOW SEB 0926.pdf")
        open(self.pdf, "wb").write(b"%PDF-1.4 synthetic")
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("AZURE_SQL", "FABRIC_"))}
        stack.enter_context(mock.patch.dict(os.environ, env, clear=True))
        stack.enter_context(mock.patch.object(connection, "DB_PATH", self.world.db))
        stack.enter_context(mock.patch.object(self.intake, "compute_file_hash", lambda p: HASH))
        stack.enter_context(mock.patch.object(self.intake, "_determine_extraction_route",
                                              lambda p: {"engine": self.route, "matched_vendor": "Autoly", "reason": "test",
                                                         "new_vendor_warning": None, "pdf_type": "text_embedded"}))
        stack.enter_context(mock.patch.object(self.intake, "extract_pdf_text", lambda p: ("synthetic text", 1)))
        stack.enter_context(mock.patch.object(self.intake, "PythonLibraryExtractionEngine", FakeEngine))
        FakeEngine.invoices = None
        stack.enter_context(mock.patch.object(in_place.time, "sleep", lambda s: None))
        # Fabric writers / builders used by apply()
        w = self.world

        def write_raw(invoices, vendor_id, statement_id, source_file, engine, vendor_display_name=None, version_number=None):
            w.lh["raw_statement_staging"].append({"statement_id": statement_id, "raw_payload": json.dumps([i.get("_raw_row") for i in invoices]),
                                                  "ingestion_timestamp": dt.datetime(2026, 10, 7, 9, 0)})
            return 1

        def promote(statement_id):
            moved = [r for r in w.lh["raw_statement_staging"] if r["statement_id"] == statement_id]
            w.lh["raw_statement"] += moved
            w.lh["raw_statement_staging"] = [r for r in w.lh["raw_statement_staging"] if r["statement_id"] != statement_id]
            return bool(moved)

        def unnest(invoices, statement_id):
            lines, fields = _explode([{"_raw_row": i.get("_raw_row"), "_extraction_confidence": i.get("line_confidence"),
                                       "_shop_name": i.get("shop")} for i in invoices], statement_id)
            w.lh["unnested_statement_lines"] += lines
            w.lh["unnested_statement_fields"] += fields
            return len(lines), len(fields)

        def build_silver(statement_id):
            w.calls.append(("build_silver", statement_id))
            return True

        def match(statement_id):
            w.calls.append(("match", statement_id))
            w.wh["silver.recon_exceptions"] = [r for r in w.wh["silver.recon_exceptions"] if r["statement_id"] != statement_id]
            return {"matched": 3, "exceptions": 0}

        for target, fake in (("src.lakehouse.bronze_raw.write_raw_statement", write_raw),
                             ("src.lakehouse.bronze_raw.promote_staged_raw_statement", promote),
                             ("src.lakehouse.bronze_raw._refresh_sql_endpoint_metadata", lambda: None),
                             ("src.lakehouse.bronze_unnest.write_unnested_from_invoices", unnest),
                             ("src.lakehouse.fabric_dbt_runner.fabric_pipeline_lock", contextlib.nullcontext),
                             ("src.lakehouse.silver_build.build_silver_direct", build_silver),
                             ("src.matching.fabric_matching.run_fabric_matching", match)):
            stack.enter_context(mock.patch(target, fake))

    # helpers
    def dry_run(self):
        state = in_place.load_state(self.io, SID)
        self.assertEqual(in_place.refusals(state), [])
        new = in_place.reextract(self.io, self.intake, state, self.pdf)
        decision = in_place.silver_matching_decision(self.io, state, new)
        return state, new, decision, in_place.plan(state, new, decision)

    def run_apply(self):
        state, new, decision, the_plan = self.dry_run()
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b1"), os.path.join(self.world.dir, "b2")], the_plan)
        result = in_place.apply(self.io, self.intake, state, new, decision,
                                expected_fingerprint=the_plan["fingerprint"], backup_paths=paths)
        return state, new, decision, the_plan, paths, result


class TestRefusals(RerunTestCase):

    def assert_refused_untouched(self, fn, message):
        before = self.world.snapshot()
        with self.assertRaisesRegex(in_place.RefusedError, message):
            fn()
        self.assertEqual(self.world.snapshot(), before)

    def test_ai_route_is_refused(self):
        seed(self.world)
        self.route = "ai"
        state = in_place.load_state(self.io, SID)
        self.assert_refused_untouched(lambda: in_place.reextract(self.io, self.intake, state, self.pdf), "never calls AI")

    def test_zero_rows_is_refused_not_sent_to_ai(self):
        seed(self.world)
        FakeEngine.invoices = []
        state = in_place.load_state(self.io, SID)
        self.assert_refused_untouched(lambda: in_place.reextract(self.io, self.intake, state, self.pdf), "0 rows")

    def test_pdf_hash_mismatch_is_refused(self):
        seed(self.world)
        state = in_place.load_state(self.io, SID)
        with mock.patch.object(self.intake, "compute_file_hash", lambda p: "b" * 64):
            self.assert_refused_untouched(lambda: in_place.reextract(self.io, self.intake, state, self.pdf), "SHA-256")

    def test_resolved_or_escalated_exception_is_refused(self):
        for status, escalation in (("RESOLVED", None), ("OPEN", "ESCALATED"), ("ACCEPTED", None)):
            with self.subTest(status=status, escalation=escalation):
                self.world.__init__()
                seed(self.world, exception_status=status, escalation=escalation)
                problems = in_place.refusals(in_place.load_state(self.io, SID))
                self.assertTrue(any("not OPEN" in p for p in problems), problems)

    def test_duplicate_or_missing_intake_row_is_refused(self):
        seed(self.world, intake_rows=2)
        self.assertTrue(any("2 document_intake_log rows" in p for p in in_place.refusals(in_place.load_state(self.io, SID))))
        self.assertTrue(any("0 document_intake_log rows" in p for p in in_place.refusals(in_place.load_state(self.io, "STMT-NONE0000"))))

    def test_jobs_in_flight_are_refused(self):
        seed(self.world, job_status="PROCESSING")
        self.assertTrue(any("in flight" in p for p in in_place.refusals(in_place.load_state(self.io, SID))))

    def test_jobs_in_flight_only_warn_in_a_dry_run(self):
        seed(self.world, job_status="PENDING")
        before = self.world.snapshot()
        state = in_place.load_state(self.io, SID)
        self.assertEqual(in_place.refusals(state, dry_run=True), [])
        new = in_place.reextract(self.io, self.intake, state, self.pdf)
        the_plan = in_place.plan(state, new, in_place.silver_matching_decision(self.io, state, new))
        self.assertEqual(the_plan["jobs_in_flight"], 1)
        self.assertTrue(any("--apply will refuse" in w for w in the_plan["warnings"]))
        self.assertEqual(the_plan["validation"]["to"]["status"], "matches")
        self.assertEqual(self.world.snapshot(), before)

    def test_apply_still_refuses_while_a_job_is_in_flight(self):
        seed(self.world, job_status="PROCESSING")
        state = in_place.load_state(self.io, SID)
        new = in_place.reextract(self.io, self.intake, state, self.pdf)
        decision = in_place.silver_matching_decision(self.io, state, new)
        the_plan = in_place.plan(state, new, decision)
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b1")], the_plan)
        self.assert_refused_untouched(lambda: in_place.apply(self.io, self.intake, state, new, decision,
                                                             expected_fingerprint=the_plan["fingerprint"], backup_paths=paths),
                                      "in flight")

    def cli(self, *argv):
        import importlib.util
        import io as io_module
        with mock.patch("dotenv.load_dotenv", lambda *a, **k: None):
            spec = importlib.util.spec_from_file_location("rerun_cli", os.path.join(ROOT, "scripts", "rerun_in_place.py"))
            cli = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cli)
        out = io_module.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(list(argv), io=self.io, intake=self.intake)
        return code, out.getvalue()

    def test_cli_dry_run_warns_and_apply_refuses_while_jobs_are_in_flight(self):
        seed(self.world, job_status="PROCESSING")
        before = self.world.snapshot()
        code, out = self.cli("--statement-id", SID, "--pdf", self.pdf)
        self.assertEqual(code, 0)
        self.assertIn("WARNING: 1 job(s) in flight", out)
        self.assertIn("DRY RUN -- nothing written", out)
        fp = re.search(r"--confirm (\w+)", out).group(1)
        code, out = self.cli("--statement-id", SID, "--pdf", self.pdf, "--apply", "--confirm", fp,
                             "--backup-dir", os.path.join(self.world.dir, "cli"))
        self.assertEqual(code, 2)
        self.assertIn("REFUSED: 1 job(s) in flight", out)
        self.assertEqual(self.world.snapshot(), before)
        self.assertFalse(os.path.exists(os.path.join(self.world.dir, "cli")))

    def test_apply_refuses_when_state_changed_since_the_dry_run(self):
        seed(self.world)
        state, new, decision, the_plan = self.dry_run()
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b1")], the_plan)
        self.world.sql("UPDATE bronze_vendor_statement_raw SET raw_outstanding_amount = '1.0' WHERE row_number = 1")
        self.assert_refused_untouched(lambda: in_place.apply(self.io, self.intake, state, new, decision,
                                                             expected_fingerprint=the_plan["fingerprint"], backup_paths=paths),
                                      "changed since the dry run")

    def test_apply_refuses_without_a_backup(self):
        seed(self.world)
        state, new, decision, the_plan = self.dry_run()
        self.assert_refused_untouched(lambda: in_place.apply(self.io, self.intake, state, new, decision,
                                                             expected_fingerprint=the_plan["fingerprint"], backup_paths=[]),
                                      "no backup")

    def test_apply_refuses_an_exception_resolved_after_the_dry_run(self):
        seed(self.world)
        state, new, decision, the_plan = self.dry_run()
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b1")], the_plan)
        self.world.wh["silver.recon_exceptions"][0]["exception_status"] = "RESOLVED"
        self.assert_refused_untouched(lambda: in_place.apply(self.io, self.intake, state, new, decision,
                                                             expected_fingerprint=the_plan["fingerprint"], backup_paths=paths),
                                      "changed since the dry run")


class TestDryRun(RerunTestCase):

    def test_dry_run_writes_nothing_and_shows_from_to(self):
        seed(self.world)
        before = self.world.snapshot()
        state, new, decision, the_plan = self.dry_run()
        self.assertEqual(self.world.snapshot(), before)
        self.assertEqual(the_plan["validation"]["from"]["status"], "mismatch")
        self.assertEqual(the_plan["validation"]["to"]["status"], "matches")
        intake_changes = the_plan["document_intake_log (UPDATE, 1 row)"]
        self.assertEqual(intake_changes["validation_status"], {"from": "mismatch", "to": "matches"})
        self.assertEqual(intake_changes["extraction_method"]["to"], "python_library_pdfplumber")
        self.assertNotIn("ingestion_timestamp", intake_changes)
        fields = the_plan["bronze.unnested_statement_fields (Lakehouse; delete + write)"]
        self.assertEqual((fields["from"], fields["to"]), (3, 15))
        self.assertEqual(fields["field names from"], ["Inv Amount"])
        self.assertEqual(the_plan["version fields"], {"version_number": 2, "previous_statement_id": "STMT-PREV0000",
                                                      "is_latest_version": 1})
        self.assertTrue(decision["run"])

    def billing_change(self, stored, extracted):
        self.world.sql("UPDATE document_intake_log SET billing_location = ?, billing_location_source = 'printed' "
                       "WHERE statement_id = ?", [stored, SID])
        state = in_place.load_state(self.io, SID)
        with mock.patch.object(self.intake, "resolve_billing_location", lambda loc, shops: (extracted, "printed_new")):
            new = in_place.reextract(self.io, self.intake, state, self.pdf)
        return new["intake_update"]

    def test_billing_location_formatting_only_keeps_the_stored_value(self):
        seed(self.world)
        for extracted in ("MECHANIC FALLS ME", "mechanic falls, me", "Mechanic  Falls ,ME"):
            with self.subTest(extracted=extracted):
                update = self.billing_change("Mechanic Falls, ME", extracted)
                self.assertEqual((update["billing_location"], update["billing_location_source"]),
                                 ("Mechanic Falls, ME", "printed"))

    def test_adversarial_a_different_place_still_updates(self):
        seed(self.world)
        for stored, extracted in (("Mechanic Falls, ME", "AUBURN ME"), ("Mechanic Falls, ME", "MECHANIC FALLS NH"),
                                  (None, "MECHANIC FALLS ME"), ("", "MECHANIC FALLS ME")):
            with self.subTest(stored=stored, extracted=extracted):
                update = self.billing_change(stored, extracted)
                self.assertEqual((update["billing_location"], update["billing_location_source"]), (extracted, "printed_new"))

    def test_fingerprint_ignores_other_statements_delta_versions_but_not_own_rows(self):
        seed(self.world)
        state = in_place.load_state(self.io, SID)
        moved = dict(state, lakehouse_versions={t: 99 for t in state["lakehouse_versions"]})
        self.assertEqual(in_place.fingerprint(moved), in_place.fingerprint(state))
        changed = copy.deepcopy(state)
        changed["lakehouse"]["unnested_statement_fields"][0]["raw_field_value"] = "2900.00"
        self.assertNotEqual(in_place.fingerprint(changed), in_place.fingerprint(state))


class TestDecision(RerunTestCase):

    def decide(self, **seed_args):
        seed(self.world, **seed_args)
        state = in_place.load_state(self.io, SID)
        new = in_place.reextract(self.io, self.intake, state, self.pdf)
        return in_place.silver_matching_decision(self.io, state, new)

    def test_no_fabric_mapping_skips_silver_and_matching(self):
        decision = self.decide(mapping=False)
        self.assertFalse(decision["run"])
        self.assertIn("no Fabric field mapping", decision["reason"])

    def add_copy(self, ts, with_summary):
        self.world.insert("document_intake_log", document_id="doc-2", document_hash=HASH, source_file="BOW SEB 0926.pdf",
                          ingestion_timestamp=ts, statement_id=COPY, validation_status="mismatch")
        if with_summary:
            self.world.wh["silver.recon_summary"].append({"statement_id": COPY, "total_invoice_count": 3})

    def test_same_pdf_copy_already_matched_skips_this_copy(self):
        seed(self.world, summary=False)
        self.add_copy("2026-10-01T10:00:00+00:00", with_summary=True)
        state = in_place.load_state(self.io, SID)
        decision = in_place.silver_matching_decision(self.io, state, in_place.reextract(self.io, self.intake, state, self.pdf))
        self.assertFalse(decision["run"])
        self.assertIn(COPY, decision["reason"])

    def test_same_pdf_later_copy_already_matched_skips_this_earlier_copy(self):
        # This copy is the earliest, but a later copy is the one already
        # matched (Bow/Fenix as today) -- this one must not be matched too.
        seed(self.world, summary=False)
        self.add_copy("2026-10-06T10:00:00+00:00", with_summary=True)
        state = in_place.load_state(self.io, SID)
        decision = in_place.silver_matching_decision(self.io, state, in_place.reextract(self.io, self.intake, state, self.pdf))
        self.assertFalse(decision["run"])
        self.assertIn("already matched", decision["reason"])

    def test_same_pdf_no_copy_matched_only_the_earliest_runs(self):
        seed(self.world, summary=False)
        self.add_copy("2026-10-01T10:00:00+00:00", with_summary=False)  # earlier than SID
        state = in_place.load_state(self.io, SID)
        decision = in_place.silver_matching_decision(self.io, state, in_place.reextract(self.io, self.intake, state, self.pdf))
        self.assertFalse(decision["run"])
        self.assertIn("earlier copy", decision["reason"])

    def test_same_pdf_this_copy_is_the_earliest(self):
        seed(self.world, summary=False)
        self.add_copy("2026-10-06T10:00:00+00:00", with_summary=False)  # later than SID
        state = in_place.load_state(self.io, SID)
        self.assertTrue(in_place.silver_matching_decision(self.io, state, in_place.reextract(self.io, self.intake, state, self.pdf))["run"])

    def test_same_pdf_this_copy_has_the_summary(self):
        seed(self.world, summary=True)
        self.add_copy("2026-10-01T10:00:00+00:00", with_summary=False)
        state = in_place.load_state(self.io, SID)
        self.assertTrue(in_place.silver_matching_decision(self.io, state, in_place.reextract(self.io, self.intake, state, self.pdf))["run"])


class TestApply(RerunTestCase):

    def test_intake_row_is_updated_in_place_never_deleted(self):
        seed(self.world)
        old = self.world.sql("SELECT * FROM document_intake_log WHERE statement_id = ?", [SID])
        self.run_apply()
        now = self.world.sql("SELECT * FROM document_intake_log WHERE statement_id = ?", [SID])
        self.assertEqual(len(now), 1)
        for kept in ("id", "document_id", "document_hash", "source_file", "ingestion_timestamp", "blob_storage_path"):
            self.assertEqual(now[0][kept], old[0][kept], kept)
        self.assertEqual((now[0]["validation_status"], now[0]["validation_method"]), ("matches", "primary"))
        self.assertEqual(now[0]["extraction_method"], "python_library_pdfplumber")

    def test_old_lakehouse_rows_never_survive_next_to_new_ones(self):
        seed(self.world)
        self.world.lh["raw_statement_staging"].append({"statement_id": SID, "raw_payload": "leftover", "ingestion_timestamp": None})
        self.run_apply()
        mine = [r for r in self.world.lh["unnested_statement_fields"] if r["statement_id"] == SID]
        self.assertEqual(len(mine), 15)
        self.assertNotIn("Inv Amount", {r["raw_field_name"] for r in mine})
        self.assertEqual(len([r for r in self.world.lh["unnested_statement_lines"] if r["statement_id"] == SID]), 3)
        raws = [r for r in self.world.lh["raw_statement"] if r["statement_id"] == SID]
        self.assertEqual(len(raws), 1)
        self.assertNotIn("leftover", raws[0]["raw_payload"])
        self.assertEqual(self.world.lh["raw_statement_staging"], [])
        # deletes happen before the new rows are written
        self.assertEqual([c for c in self.world.calls if c[0] == "delta_delete"][:4],
                         [("delta_delete", t) for t in in_place.LAKEHOUSE_TABLES])

    def test_bronze_versions_kept_and_no_other_statement_changes(self):
        seed(self.world)
        other_before = (self.world.sql("SELECT * FROM silver_reconciliation_standard WHERE statement_id = ?", [OTHER]),
                        [r for r in self.world.lh["unnested_statement_fields"] if r["statement_id"] == OTHER],
                        [r for r in self.world.wh["silver.recon_summary"] if r["statement_id"] == OTHER])
        self.run_apply()
        bronze = self.world.sql("SELECT * FROM bronze_vendor_statement_raw WHERE statement_id = ?", [SID])
        self.assertEqual(len(bronze), 3)
        self.assertEqual({(r["version_number"], r["previous_statement_id"], r["is_latest_version"]) for r in bronze},
                         {(2, "STMT-PREV0000", 1)})
        self.assertEqual(sorted(r["raw_outstanding_amount"] for r in bronze), ["100.0", "250.5", "49.5"])
        other_after = (self.world.sql("SELECT * FROM silver_reconciliation_standard WHERE statement_id = ?", [OTHER]),
                       [r for r in self.world.lh["unnested_statement_fields"] if r["statement_id"] == OTHER],
                       [r for r in self.world.wh["silver.recon_summary"] if r["statement_id"] == OTHER])
        self.assertEqual(other_after, other_before)

    def test_cache_row_updated_only_when_it_exists(self):
        seed(self.world)
        self.run_apply()
        cache = self.world.sql("SELECT * FROM extraction_cache")
        self.assertEqual(len(cache), 1)
        self.assertEqual((cache[0]["statement_id"], cache[0]["row_count"], cache[0]["extraction_method"]),
                         (SID, 3, "python_library_pdfplumber"))

    def test_no_cache_row_none_inserted(self):
        seed(self.world, cache=False)
        self.run_apply()
        self.assertEqual(self.world.sql("SELECT * FROM extraction_cache"), [])

    def test_silver_and_matching_run_only_when_decided(self):
        seed(self.world)
        self.run_apply()
        self.assertEqual([c for c in self.world.calls if c[0] in ("build_silver", "match")], [("build_silver", SID), ("match", SID)])
        self.world.__init__()
        seed(self.world, mapping=False)
        result = self.run_apply()[-1]
        self.assertEqual([c for c in self.world.calls if c[0] in ("build_silver", "match")], [])
        self.assertIn("no Fabric field mapping", result["silver_and_matching"])

    def test_stale_endpoint_with_the_same_row_count_is_not_taken_as_visible(self):
        seed(self.world)
        # The SQL endpoint still shows 15 field rows -- but the OLD values.
        self.world.visible_fields = [{"statement_id": SID, "line_number": n // 5, "raw_field_name": "Inv Amount",
                                      "raw_field_value": str(n)} for n in range(15)]
        real_wait = in_place._wait_exact_visibility
        with mock.patch.object(in_place, "_wait_exact_visibility",
                               lambda io, sid, fields, **k: real_wait(io, sid, fields, timeout_seconds=0)):
            result = self.run_apply()[-1]
        self.assertFalse(result["silver_built"])
        self.assertEqual([c for c in self.world.calls if c[0] in ("build_silver", "match")], [])

    def test_exact_visibility_wait_compares_values_not_counts(self):
        seed(self.world)
        expected = [{"line_number": 0, "raw_field_name": "Due", "raw_field_value": "100.00"}]
        self.world.visible_fields = [{"statement_id": SID, "line_number": 0, "raw_field_name": "Due", "raw_field_value": "99.00"}]
        self.assertFalse(in_place._wait_exact_visibility(self.io, SID, expected, timeout_seconds=0))
        self.world.visible_fields = [{"statement_id": SID, "line_number": 0, "raw_field_name": "Due", "raw_field_value": "100.00"}]
        self.assertTrue(in_place._wait_exact_visibility(self.io, SID, expected, timeout_seconds=0))


class TestPromoteAndStop(RerunTestCase):

    def az_and_wh(self):
        snap = json.loads(self.world.snapshot())
        return json.dumps({"az": snap["az"], "wh": snap["wh"]}, sort_keys=True)

    def test_promote_moves_the_staged_row_through_io_and_clears_staging(self):
        seed(self.world)
        self.world.lh["raw_statement"] = []
        self.world.lh["raw_statement_staging"] = [{"statement_id": SID, "raw_payload": "new", "ingestion_timestamp": None}]
        self.assertEqual(in_place.promote_raw(self.io, SID), 1)
        self.assertEqual([r["raw_payload"] for r in self.world.lh["raw_statement"]], ["new"])
        self.assertEqual(self.world.lh["raw_statement_staging"], [])

    def test_adversarial_promote_refuses_an_unknown_column_and_a_missing_row(self):
        seed(self.world)
        self.world.lh["raw_statement_staging"] = [{"statement_id": SID, "raw_payload": "new", "surprise": 1}]
        with self.assertRaisesRegex(in_place.RefusedError, "surprise"):
            in_place.promote_raw(self.io, SID)
        self.world.lh["raw_statement_staging"] = []
        with self.assertRaisesRegex(in_place.RefusedError, "no staged"):
            in_place.promote_raw(self.io, SID)

    def test_apply_stops_before_any_azure_sql_write_when_the_raw_row_cannot_be_promoted(self):
        seed(self.world)
        state, new, decision, the_plan = self.dry_run()
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b1")], the_plan)
        before = self.az_and_wh()
        self.world.fail_append = {"raw_statement"}
        with self.assertRaisesRegex(in_place.RefusedError, "promoting the raw row failed.*stopped before any Azure SQL write"):
            in_place.apply(self.io, self.intake, state, new, decision, expected_fingerprint=the_plan["fingerprint"], backup_paths=paths)
        self.assertEqual(self.az_and_wh(), before)

    def test_apply_stops_before_any_azure_sql_write_when_the_lakehouse_counts_are_wrong(self):
        seed(self.world)
        state, new, decision, the_plan = self.dry_run()
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b1")], the_plan)
        before = self.az_and_wh()
        real_unnest = sys.modules["src.lakehouse.bronze_unnest"].write_unnested_from_invoices
        with mock.patch("src.lakehouse.bronze_unnest.write_unnested_from_invoices",
                        lambda invoices, sid: real_unnest(invoices[:-1], sid)):  # one line short
            with self.assertRaisesRegex(in_place.RefusedError, "unnested_statement_lines: 2 row"):
                in_place.apply(self.io, self.intake, state, new, decision, expected_fingerprint=the_plan["fingerprint"], backup_paths=paths)
        self.assertEqual(self.az_and_wh(), before)


class TestResume(RerunTestCase):

    def half_apply(self):
        """The real 2026-10-07 STMT-004FB9CA state: Azure SQL written, raw row
        left in staging, Silver + matching not run."""
        seed(self.world)
        state, new, decision, the_plan = self.dry_run()
        paths = in_place.backup(state, [os.path.join(self.world.dir, "b1")], the_plan)
        real_wait = in_place._wait_exact_visibility
        with mock.patch.object(in_place, "promote_raw", lambda io, sid: 0), \
                mock.patch.object(in_place, "_lakehouse_problems", lambda *a: []), \
                mock.patch.object(in_place, "_wait_exact_visibility", lambda io, sid, f, **k: real_wait(io, sid, f, timeout_seconds=0)):
            result = in_place.apply(self.io, self.intake, state, new, decision, expected_fingerprint=the_plan["fingerprint"], backup_paths=paths)
        self.assertFalse(result["silver_built"])
        self.assertEqual(len(self.world.lh["raw_statement_staging"]), 1)
        self.assertEqual([r for r in self.world.lh["raw_statement"] if r["statement_id"] == SID], [])
        self.world.calls.clear()
        return json.load(open(paths[0], encoding="utf-8"))

    def test_resume_dry_run_passes_and_writes_nothing(self):
        doc = self.half_apply()
        before = self.world.snapshot()
        out = in_place.resume(self.io, doc)
        self.assertTrue(out["dry_run"])
        self.assertEqual((out["now"]["raw_statement"], out["now"]["raw_statement_staging"]), (0, 1))
        self.assertEqual(self.world.snapshot(), before)

    def test_resume_apply_promotes_then_builds_silver_and_matches(self):
        doc = self.half_apply()
        fp = in_place.resume(self.io, doc)["fingerprint"]
        result = in_place.resume(self.io, doc, apply_changes=True, expected_fingerprint=fp)
        self.assertEqual(result["raw_promoted"], 1)
        self.assertEqual(len([r for r in self.world.lh["raw_statement"] if r["statement_id"] == SID]), 1)
        self.assertEqual(self.world.lh["raw_statement_staging"], [])
        self.assertTrue(result["silver_built"])
        self.assertEqual([c for c in self.world.calls if c[0] in ("build_silver", "match")], [("build_silver", SID), ("match", SID)])

    def assert_resume_refused(self, doc, message, **kw):
        before = self.world.snapshot()
        with self.assertRaisesRegex(in_place.RefusedError, message):
            in_place.resume(self.io, doc, **kw)
        self.assertEqual(self.world.snapshot(), before)

    def test_adversarial_intake_row_not_as_planned(self):
        doc = self.half_apply()
        self.world.sql("UPDATE document_intake_log SET validation_status = 'mismatch' WHERE statement_id = ?", [SID])
        self.assert_resume_refused(doc, "validation_status")

    def test_adversarial_bronze_count_not_as_planned(self):
        doc = self.half_apply()
        self.world.sql("DELETE FROM bronze_vendor_statement_raw WHERE id = (SELECT MIN(id) FROM bronze_vendor_statement_raw WHERE statement_id = ?)", [SID])
        self.assert_resume_refused(doc, "bronze_vendor_statement_raw: 2 rows")

    def test_adversarial_no_staged_row_or_already_promoted(self):
        doc = self.half_apply()
        staged = self.world.lh["raw_statement_staging"]
        self.world.lh["raw_statement_staging"] = []
        self.assert_resume_refused(doc, "staging only")
        self.world.lh["raw_statement"] += staged
        self.assert_resume_refused(doc, "staging only")

    def test_adversarial_new_lines_or_fields_missing(self):
        doc = self.half_apply()
        self.world.lh["unnested_statement_fields"] = [r for r in self.world.lh["unnested_statement_fields"]
                                                     if not (r["statement_id"] == SID and r["line_number"] == 2)]
        self.assert_resume_refused(doc, "unnested_statement_fields")

    def test_adversarial_silver_or_recon_changed_since_the_backup(self):
        doc = self.half_apply()
        self.world.wh["silver.recon_matched_invoices"].append({"statement_id": SID, "match_id": "m9"})
        self.assert_resume_refused(doc, "recon_matched_invoices changed")

    def test_adversarial_wrong_backup_or_fingerprint_or_jobs_in_flight(self):
        doc = self.half_apply()
        other = dict(doc, statement_id="STMT-ZZZZ9999")
        self.assert_resume_refused(other, "0 document_intake_log rows")  # resume only ever loads the backup's own statement
        self.assert_resume_refused(doc, "changed since the resume dry run", apply_changes=True, expected_fingerprint="0" * 16)
        self.world.insert("jobs", job_id="job-2", pdf_filename="x.pdf", pdf_path="x.pdf", submitted_at="2026-10-07T16:00:00",
                          statement_id="STMT-NEW00001", status="PENDING")
        self.assertTrue(in_place.resume(self.io, doc)["warnings"])  # dry run only warns
        fp = in_place.resume(self.io, doc)["fingerprint"]
        self.assert_resume_refused(doc, "in flight", apply_changes=True, expected_fingerprint=fp)


class TestBackupAndUndo(RerunTestCase):

    def test_backup_written_to_every_dir_with_exact_types(self):
        seed(self.world)
        state, new, decision, the_plan, paths, _ = self.run_apply()
        self.assertEqual(len(paths), 2)
        doc = json.load(open(paths[1], encoding="utf-8"))
        rows = in_place._decode_rows(doc["warehouse"]["silver.statement"])
        self.assertEqual(rows[0]["statement_total"], decimal.Decimal("8500.00"))
        self.assertEqual(in_place._decode_rows(doc["lakehouse"]["raw_statement"])[0]["ingestion_timestamp"],
                         dt.datetime(2026, 10, 5, 16, 43))
        self.assertEqual(doc["fingerprint"], the_plan["fingerprint"])

    def strip_ids(self, rows):
        return sorted((json.dumps({k: v for k, v in r.items() if k != "id"}, sort_keys=True, default=str) for r in rows))

    def test_undo_restores_every_table(self):
        seed(self.world)
        before_az = {t: self.strip_ids(self.world.sql(f"SELECT * FROM {t}")) for t in (
            "bronze_vendor_statement_raw", "silver_reconciliation_standard", "gold_exceptions", "validation_document_review_queue")}
        before_intake = self.world.sql("SELECT * FROM document_intake_log")
        before_cache = self.world.sql("SELECT * FROM extraction_cache")
        before_fabric = json.dumps({"wh": self.world.wh, "lh": {t: sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)
                                                                for t, rows in self.world.lh.items()}}, sort_keys=True, default=str)
        paths = self.run_apply()[4]
        doc = json.load(open(paths[0], encoding="utf-8"))
        dry = in_place.undo(self.io, doc)
        self.assertTrue(dry["dry_run"])
        in_place.undo(self.io, doc, apply_changes=True)
        self.assertEqual({t: self.strip_ids(self.world.sql(f"SELECT * FROM {t}")) for t in before_az}, before_az)
        self.assertEqual(self.world.sql("SELECT * FROM document_intake_log"), before_intake)
        self.assertEqual(self.world.sql("SELECT * FROM extraction_cache"), before_cache)
        after_fabric = json.dumps({"wh": self.world.wh, "lh": {t: sorted(json.dumps(r, sort_keys=True, default=str) for r in rows)
                                                               for t, rows in self.world.lh.items()}}, sort_keys=True, default=str)
        self.assertEqual(json.loads(after_fabric)["lh"], json.loads(before_fabric)["lh"])
        for t in in_place.SILVER_TABLES + in_place.RECON_TABLES:
            key = lambda r: json.dumps(r, sort_keys=True, default=str)
            self.assertEqual(sorted(map(key, self.world.wh[t])), sorted(map(key, json.loads(before_fabric)["wh"][t])), t)

    def test_undo_removes_rows_the_rerun_added_and_keeps_older_ones(self):
        # One extracted row with no identifier and no content: the intake
        # logs it to ai_audit_log and gold_exceptions. Undo removes exactly
        # those, keeping the statement's older legacy exception.
        seed(self.world)
        FakeEngine.invoices = new_invoices() + [{"line_confidence": 1.0, "_raw_row": {"Date": "08/31/26"}}]
        paths = self.run_apply()[4]
        self.assertEqual(len(self.world.sql("SELECT * FROM gold_exceptions WHERE statement_id = ?", [SID])), 2)
        self.assertEqual(len(self.world.sql("SELECT * FROM ai_audit_log WHERE statement_id = ?", [SID])), 1)
        in_place.undo(self.io, json.load(open(paths[0], encoding="utf-8")), apply_changes=True)
        self.assertEqual([r["exception_id"] for r in self.world.sql("SELECT * FROM gold_exceptions WHERE statement_id = ?", [SID])],
                         ["legacy-1"])
        self.assertEqual(self.world.sql("SELECT * FROM ai_audit_log WHERE statement_id = ?", [SID]), [])

    def test_undo_dry_run_writes_nothing(self):
        seed(self.world)
        paths = self.run_apply()[4]
        before = self.world.snapshot()
        in_place.undo(self.io, json.load(open(paths[0], encoding="utf-8")))
        self.assertEqual(self.world.snapshot(), before)


class TestIntakeLogValues(unittest.TestCase):

    def test_write_intake_log_writes_exactly_the_shared_values(self):
        intake = load_intake()
        schema = FakeEngine().understand("", "x.pdf")
        schema["validation"] = {"status": "matches", "difference": 0.0, "method": "primary", "detail": None}
        values = intake.intake_log_values("doc-9", "x.pdf", HASH, schema, SID, "2026-09", 3, "RECONCILIATION")
        captured = []
        with mock.patch.object(intake, "execute_sql", lambda sql, params=None: captured.append((sql, params))):
            intake.write_intake_log("doc-9", "x.pdf", HASH, schema, SID, "2026-09", 3, "RECONCILIATION")
        self.assertTrue(captured[0][0].startswith("DELETE FROM document_intake_log"))
        cols = re.search(r"\((.*?)\) VALUES", captured[1][0]).group(1).split(", ")
        written = dict(zip(cols, captured[1][1]))
        self.assertEqual(set(written), set(values))
        for k in values:
            if k != "ingestion_timestamp":
                self.assertEqual(written[k], values[k], k)


if __name__ == "__main__":
    unittest.main()
