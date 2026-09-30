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

# The reasons the Find button offers. "Vendor Not Resolved in NetSuite"
# and "Possible Duplicate in NetSuite" are deliberately NOT here -- see
# SEARCHABLE_REASONS in web/routers/exceptions.py for why the former is
# excluded (no entity ids to pre-fill, so it would open straight onto the
# guardrail message).
SEARCHABLE = ("Not Found in NetSuite", "Invoice Missing", "Amount Mismatch")
NOT_SEARCHABLE = ("Possible Duplicate in NetSuite", "Vendor Not Resolved in NetSuite",
                  "EXTRACTION_INCOMPLETE", "DUPLICATE_RECORD")


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

    def test_button_appears_for_each_searchable_reason(self):
        for reason in SEARCHABLE:
            with self.subTest(reason=reason):
                html = _render(reason)
                self.assertIn('id="nsFindBtn"', html)
                self.assertIn("Find in NetSuite", html)

    def test_searchable_reasons_is_exactly_these_three(self):
        self.assertEqual(tuple(SEARCHABLE_REASONS), SEARCHABLE)

    def test_button_and_modal_absent_for_every_other_reason(self):
        for reason in NOT_SEARCHABLE:
            with self.subTest(reason=reason):
                html = _render(reason)
                self.assertNotIn('id="nsFindBtn"', html)
                self.assertNotIn('id="nsModal"', html)


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

    def test_results_partial_has_no_checkbox(self):
        """Rows were selectable via a checkbox until 2026-09-30; that and
        the footer totals it drove are both gone."""
        rendered = templates.get_template(RESULTS_PARTIAL).render(
            result={"rows": [{
                "record_type": "Bill", "is_credit": False, "tranid": "1", "vendor_name": "V",
                "entity_id": "1", "total": 1.0, "trandate": "1/1/2026", "trandate_display": "Jan 1, 2026",
                "duedate": None, "duedate_display": "", "status_label": "Open",
                "ro_number": None, "location_code": "1", "transaction_number": "T",
            }], "row_count": 1, "truncated": False, "error": False, "needs_filter": False, "message": None},
            last_sync=None,
        )
        self.assertNotIn('type="checkbox"', rendered)

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
        """All four chips are popover triggers now (2026-09-30) -- Vendor
        and Status used to be plain on/off toggles (aria-pressed)."""
        html = _render("Not Found in NetSuite")
        self.assertRegex(html, r'id="nsChipVendor"[^>]*aria-expanded=')
        self.assertRegex(html, r'id="nsChipStatus"[^>]*aria-expanded=')
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
                      "nsModalTitle", "nsResults", "nsInvoice", "nsInvoiceHint",
                      "nsChipVendor", "nsChipVendorValue", "nsPopVendor",
                      "nsChipAmount", "nsChipAmountValue", "nsPopAmount", "nsAmountInput",
                      "nsChipDate", "nsChipDateValue", "nsPopDate",
                      "nsChipStatus", "nsChipStatusValue", "nsPopStatus",
                      "nsStatusOpen", "nsStatusPaid", "nsDateFrom",
                      "nsDateTo", "nsDateApply", "nsReset", "nsReload"):
            self.assertEqual(html.count(f'id="{el_id}"'), 1, el_id)

    def test_no_footer_summary_element_any_more(self):
        """Removed 2026-09-30 along with row selection/footer totals."""
        html = _render("Not Found in NetSuite")
        self.assertNotIn('id="nsFootSummary"', html)

    def test_modal_has_no_copy_or_export_control(self):
        """Dropped deliberately: the modal reports, the reviewer writes
        their own note."""
        html = _render("Not Found in NetSuite")
        self.assertNotIn("nsCopyNote", html)
        self.assertNotIn("Copy to note", html)

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


class TestReasonBasedOpeningDefaults(unittest.TestCase):
    """Amount Mismatch opens with no amount filter, both statuses ticked,
    and the invoice number prefilled when selective enough -- the
    statement amount is BY DEFINITION not the real NetSuite total for
    this reason (confirmed live 2026-09-30 against several real Amount
    Mismatch exceptions: the old Exact + statement-amount default missed
    every one of them). Not Found/Invoice Missing keep the original
    Exact + statement amount + Open defaults, where the amount IS
    expected to match once found.

    The actual default-selection logic lives in web/static/app.js's
    defaultState() (there is no JS test runner in this suite) -- these
    pin the data attributes app.js reads it from, plus a static check
    that the reason-based branch is still present in the source, so a
    regression that deletes it is caught even without executing JS.
    Verified behaviourally via Playwright screenshots (scratchpad/shots_c/),
    not by these tests alone."""

    def _app_js(self):
        path = os.path.join(os.path.dirname(__file__), "..", "web", "static", "app.js")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_default_state_branches_on_amount_mismatch(self):
        js = self._app_js()
        self.assertIn('ctx.reason === "Amount Mismatch"', js)
        self.assertIn("isAmountMismatch", js)

    def test_amount_mismatch_default_is_empty_amount_and_both_statuses(self):
        js = self._app_js()
        self.assertIn('amount: isAmountMismatch ? "" : (ctx.amount || "")', js)
        self.assertIn('statuses: isAmountMismatch ? ["open", "paid"] : ["open"]', js)

    def test_invoice_prefill_requires_four_non_space_characters(self):
        js = self._app_js()
        self.assertIn("MIN_INVOICE_CHARS = 4", js)
        self.assertIn("invoiceChars >= MIN_INVOICE_CHARS", js)

    def test_data_invoice_attribute_is_populated_for_amount_mismatch(self):
        """The prefill source: data-invoice, already on the button
        regardless of length -- app.js decides whether it's long enough
        to actually use."""
        html = _render("Amount Mismatch")
        self.assertIn('data-invoice="900CC752"', html)

    def test_data_invoice_short_case_still_renders_the_raw_value(self):
        """A 3-character invoice number is still written to data-invoice
        as-is -- app.js's own length check (not the template) is what
        decides not to prefill it."""
        html = _render("Amount Mismatch", selected={
            "exception_id": "exc-3", "statement_id": "STMT-TEST",
            "invoice_number": "123", "vendor_id": "KEYSTONE_AUTOMOTIVE_INDUSTRIES",
            "statement_amount": 158.55, "erp_amount": None,
            "exception_reason": "Amount Mismatch", "exception_status": "OPEN",
            "date_raised": "2026-09-21T16:45:51+00:00", "days_open": 7,
            "match_confidence": None, "escalation_status": None,
            "invoice_date": "2026-07-09", "ro_number": None,
        })
        self.assertIn('data-invoice="123"', html)


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

    def test_no_checkbox_anywhere_in_the_results_partial(self):
        """Rows are no longer selectable at all (removed 2026-09-30, along
        with the footer totals they used to drive)."""
        html = self._render_rows([dict(self.ROW)])
        self.assertNotIn("<input type=\"checkbox\"", html)
        self.assertNotIn("ns-row-check", html)
        self.assertNotIn("ns-col-check", html)

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
