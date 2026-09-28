"""
tests/test_netsuite_modal.py

Render-level tests for the "Find in NetSuite" modal on the exception
review page.

The load-bearing assertion here is that the modal is LOOK-ONLY: it must
never grow a form, an action, a method or a POST. Closing an exception
stays with the existing Accept/Dispute/Escalate forms, and a regression
that quietly added a resolve button to this modal would be a financial-
consequence bug, not a UI one -- so it is pinned by test rather than by
convention.

Renders the templates directly through the app's own Jinja environment
(web.deps.templates) rather than going through a route, so nothing here
touches Fabric, Azure SQL or SQLite -- these do not overlap with the
database-backed tests that already fail in this local environment.
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web.deps import templates
from web.routers.exceptions import REASON_BADGE, SEARCHABLE_REASONS

TEMPLATE = "exceptions_review.html"
RESULTS_PARTIAL = "_netsuite_search_results.html"

# Every reason the matching engine can write (src/matching/fabric_matching.py)
# plus the legacy gold_exceptions spelling.
ENGINE_REASONS = (
    "Not Found in NetSuite",
    "Amount Mismatch",
    "Possible Duplicate in NetSuite",
    "Vendor Not Resolved in NetSuite",
    "Invoice Missing",
)


def _render(reason, **overrides):
    ctx = {
        "active_page": "exceptions",
        "vendor_name": "Keystone Automotive Industries",
        "vendor_display_name": "Keystone Automotive Industries",
        "vendor_url_name": "Keystone%20Automotive%20Industries",
        "not_found": False,
        "statement": {"statement_id": "STMT-TEST"},
        "exceptions": [],
        "selected": {
            "exception_id": "exc-1", "statement_id": "STMT-TEST",
            "invoice_number": "900CC752", "vendor_id": "KEYSTONE_AUTOMOTIVE_INDUSTRIES",
            "statement_amount": 158.55, "erp_amount": None,
            "exception_reason": reason, "exception_status": "OPEN",
            "date_raised": "2026-09-21T16:45:51+00:00", "days_open": 7,
            "match_confidence": None, "escalation_status": None,
            "invoice_date": "2026-07-09", "ro_number": None,
        },
        "total": 1, "resolved": 0, "progress_pct": 0, "filter": "all",
        "reason_badge": REASON_BADGE,
        "high_confidence_count": 0, "bulk_approve_threshold": 0.99,
        "netsuite_record": None,
        "searchable_reasons": SEARCHABLE_REASONS,
        "open_exception_count": 1, "user": "tester",
    }
    ctx.update(overrides)
    return templates.get_template(TEMPLATE).render(**ctx)


class TestFindButtonVisibility(unittest.TestCase):

    def test_button_appears_for_every_engine_written_reason(self):
        for reason in ENGINE_REASONS:
            with self.subTest(reason=reason):
                html = _render(reason)
                self.assertIn('id="nsFindBtn"', html)
                self.assertIn("Find in NetSuite", html)

    def test_every_engine_reason_is_in_searchable_reasons(self):
        """Guards against the engine gaining a reason the modal forgets."""
        for reason in ENGINE_REASONS:
            self.assertIn(reason, SEARCHABLE_REASONS)

    def test_button_absent_for_an_unrelated_reason(self):
        html = _render("EXTRACTION_INCOMPLETE")
        self.assertNotIn('id="nsFindBtn"', html)
        self.assertNotIn('id="nsModal"', html)

    def test_button_absent_for_duplicate_record(self):
        html = _render("DUPLICATE_RECORD")
        self.assertNotIn('id="nsFindBtn"', html)


class TestModalIsLookOnly(unittest.TestCase):
    """The whole point of the feature: it researches, it never resolves."""

    def _modal_markup(self, html):
        start = html.index('<dialog class="ns-modal"')
        return html[start:html.index("</dialog>", start)]

    def test_modal_contains_no_form(self):
        modal = self._modal_markup(_render("Not Found in NetSuite"))
        self.assertNotIn("<form", modal.lower())

    def test_modal_contains_no_action_or_method(self):
        modal = self._modal_markup(_render("Not Found in NetSuite"))
        self.assertNotRegex(modal, r"\baction\s*=")
        self.assertNotRegex(modal, r"\bmethod\s*=")

    def test_every_modal_button_is_type_button(self):
        """A bare <button> inside a form defaults to type=submit."""
        modal = self._modal_markup(_render("Not Found in NetSuite"))
        for tag in re.findall(r"<button[^>]*>", modal):
            self.assertIn('type="button"', tag, tag)

    def test_modal_has_no_resolve_or_match_control(self):
        modal = self._modal_markup(_render("Not Found in NetSuite")).lower()
        for word in ("accept", "dispute", "resolve", "write off", "writeoff"):
            self.assertNotIn(word, modal, f"{word!r} must not appear in a look-only modal")

    def test_results_partial_has_no_form_or_action(self):
        rendered = templates.get_template(RESULTS_PARTIAL).render(
            result={"rows": [], "row_count": 0, "truncated": False,
                    "error": False, "needs_filter": False, "message": None},
            last_sync=None,
        )
        self.assertNotIn("<form", rendered.lower())
        self.assertNotRegex(rendered, r"\baction\s*=")

    def test_modal_is_outside_the_action_form(self):
        """The page's Accept/Dispute <form> must close before the dialog
        opens -- a dialog nested in that form would submit it."""
        html = _render("Not Found in NetSuite")
        self.assertIn('id="action-form"', html)
        self.assertLess(html.index("</form>"), html.index("<dialog"))


class TestModalMarkup(unittest.TestCase):

    def test_dialog_is_labelled(self):
        html = _render("Not Found in NetSuite")
        self.assertIn('aria-labelledby="nsModalTitle"', html)
        self.assertIn('id="nsModalTitle"', html)

    def test_chips_expose_state_to_assistive_tech(self):
        html = _render("Not Found in NetSuite")
        self.assertRegex(html, r'id="nsChipVendor"[^>]*aria-pressed=')
        self.assertRegex(html, r'id="nsChipStatus"[^>]*aria-pressed=')
        self.assertRegex(html, r'id="nsChipAmount"[^>]*aria-expanded=')
        self.assertRegex(html, r'id="nsChipDate"[^>]*aria-expanded=')

    def test_context_the_javascript_reads_is_populated(self):
        html = _render("Not Found in NetSuite")
        for attr, expected in (
            ("data-vendor-id", "KEYSTONE_AUTOMOTIVE_INDUSTRIES"),
            ("data-invoice", "900CC752"),
            ("data-amount", "158.55"),
            ("data-reason", "Not Found in NetSuite"),
        ):
            self.assertIn(f'{attr}="{expected}"', html)

    def test_amount_is_passed_as_absolute_value(self):
        """A statement credit line carries a negative amount, while
        NetSuite stores every total positive."""
        html = _render("Amount Mismatch", selected={
            "exception_id": "exc-2", "statement_id": "STMT-TEST",
            "invoice_number": "CM900CC752",
            "vendor_id": "KEYSTONE_AUTOMOTIVE_INDUSTRIES",
            "statement_amount": -158.55, "erp_amount": None,
            "exception_reason": "Amount Mismatch", "exception_status": "OPEN",
            "date_raised": "2026-09-21T16:45:51+00:00", "days_open": 7,
            "match_confidence": None, "escalation_status": None,
            "invoice_date": "2026-07-09", "ro_number": None,
        })
        self.assertIn('data-amount="158.55"', html)
        self.assertNotIn('data-amount="-158.55"', html)

    def test_every_id_the_javascript_looks_up_exists_exactly_once(self):
        html = _render("Not Found in NetSuite")
        for el_id in ("nsFindBtn", "nsModal", "nsModalClose", "nsModalDone",
                      "nsModalTitle", "nsResults", "nsInvoice", "nsFootSummary",
                      "nsCopyNote", "nsChipVendor", "nsChipVendorValue",
                      "nsChipAmount", "nsChipAmountValue", "nsPopAmount",
                      "nsChipDate", "nsChipDateValue", "nsPopDate",
                      "nsChipStatus", "nsChipStatusValue", "nsDateFrom",
                      "nsDateTo", "nsDateApply", "nsReset", "nsReload"):
            self.assertEqual(html.count(f'id="{el_id}"'), 1, el_id)

    def test_note_textarea_the_copy_button_targets_still_exists(self):
        html = _render("Not Found in NetSuite")
        self.assertIn('class="note-field"', html)
        self.assertIn("<textarea", html)

    def test_existing_netsuite_preview_is_untouched(self):
        """The separate Amount-Mismatch record preview must still render."""
        html = _render("Amount Mismatch", netsuite_record={
            "tranid": "900CC752", "transactionnumber": "VENDBILL1",
            "trandate": "7/9/2026", "status_label": "Paid In Full",
            "total": "158.55", "postingperiod": "95", "duedate": "8/9/2026",
            "location": "10", "custbody_cgh_ro": "3104605", "memo": "x",
            "custbody_kesapt_approvalstatus": None,
            "_source_table": "netsuite_vendorbill",
        })
        self.assertIn("NetSuite record", html)
        self.assertIn("ns-panel", html)
        # ...and the modal sits after it, not instead of it.
        self.assertLess(html.index("NetSuite record"), html.index("<dialog"))


class TestResultsPartialRendering(unittest.TestCase):

    ROW = {
        "record_type": "Bill", "is_credit": False, "tranid": "900CC752",
        "vendor_name": "AUTO DATA LABELS INC", "entity_id": "12203",
        "total": 158.55, "trandate": "7/9/2026", "trandate_display": "Jul 9, 2026",
        "duedate": "8/9/2026", "duedate_display": "Aug 9, 2026",
        "status_label": "Paid In Full", "ro_number": "3104605",
        "location_code": "10", "transaction_number": "VENDBILL1",
    }

    def _render_rows(self, rows, **kw):
        result = {"rows": rows, "row_count": len(rows), "truncated": False,
                  "error": False, "needs_filter": False, "message": None}
        result.update(kw)
        return templates.get_template(RESULTS_PARTIAL).render(
            result=result, last_sync=None)

    def test_row_shows_dates_and_status_pill(self):
        html = self._render_rows([dict(self.ROW)])
        self.assertIn("Jul 9, 2026", html)
        self.assertIn("Due Aug 9, 2026", html)
        self.assertIn("ns-pill-paid", html)

    def test_credit_row_gets_a_credit_tag(self):
        html = self._render_rows([dict(self.ROW, is_credit=True, record_type="Credit")])
        self.assertIn("ns-tag-credit", html)

    def test_missing_duedate_omits_the_due_clause(self):
        """Credits carry a duedate on 0.03% of rows -- a bare "Due" label
        would be noise on every one of the rest."""
        html = self._render_rows([dict(self.ROW, duedate_display="", duedate=None)])
        self.assertNotIn("Due ", html)
        self.assertIn("Jul 9, 2026", html)

    def test_open_status_uses_the_open_pill(self):
        html = self._render_rows([dict(self.ROW, status_label="Open")])
        self.assertIn("ns-pill-open", html)

    def test_details_row_carries_ro_location_and_transaction(self):
        html = self._render_rows([dict(self.ROW)])
        self.assertIn("3104605", html)
        self.assertIn("Location (code)", html)
        self.assertIn("VENDBILL1", html)

    def test_row_carries_the_data_the_footer_maths_needs(self):
        html = self._render_rows([dict(self.ROW)])
        self.assertIn('data-amount="158.55"', html)
        self.assertIn("data-summary=", html)

    def test_truncation_notice(self):
        html = self._render_rows([dict(self.ROW)], truncated=True)
        self.assertIn("narrow your filters", html)

    def test_empty_state(self):
        html = self._render_rows([])
        self.assertIn("No matching bills", html)

    def test_error_message_is_shown_verbatim(self):
        html = self._render_rows([], error=True, message="Date from must look like 2026-09-28.")
        self.assertIn("2026-09-28", html)


if __name__ == "__main__":
    unittest.main()
