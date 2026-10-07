"""
tests/test_exceptions_reject_button.py

The exception review page's second action button reads "Reject" (was
"Dispute with vendor" until 2026-10-06). Label only: the form still
submits action=DISPUTED, which exceptions_action() passes straight
through as exception_dispositions.disposition_status -- the value the
table's CHECK constraint allows and existing rows already hold -- so no
stored value, query or report changes.

Template-level tests render exceptions_review.html through the app's own
Jinja environment; the route test mocks queries.resolve_exception(), so
nothing here touches SQLite, Azure SQL or Fabric.
"""

import os
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web.deps import require_login, templates
from web.routers import exceptions
from web.routers.exceptions import REASON_BADGE, SEARCHABLE_REASONS


def _render(reason="Not Found in NetSuite"):
    return templates.get_template("exceptions_review.html").render(
        active_page="exceptions",
        vendor_name="Keystone Automotive Industries",
        vendor_display_name="Keystone Automotive Industries",
        vendor_url_name="Keystone%20Automotive%20Industries",
        not_found=False,
        statement={"statement_id": "STMT-TEST"},
        exceptions=[],
        selected={
            "exception_id": "exc-1", "statement_id": "STMT-TEST", "invoice_number": "900CC752",
            "vendor_id": "KEYSTONE_AUTOMOTIVE_INDUSTRIES", "statement_amount": 158.55, "erp_amount": None,
            "exception_reason": reason, "exception_status": "OPEN",
            "date_raised": "2026-09-21T16:45:51+00:00", "days_open": 7, "match_confidence": None,
            "escalation_status": None, "invoice_date": "2026-07-09", "ro_number": None,
        },
        total=1, resolved=0, progress_pct=0, filter="all",
        reason_badge=REASON_BADGE, high_confidence_count=0, bulk_approve_threshold=0.99,
        netsuite_record=None, searchable_reasons=SEARCHABLE_REASONS,
        open_exception_count=1, user="tester",
    )


def _visible_text(html):
    """Rendered page minus tags and attribute values -- what a user can read."""
    return re.sub(r"<[^>]+>", " ", html)


class TestRejectButton(unittest.TestCase):

    def _button(self, html):
        return re.search(r'<button[^>]*value="DISPUTED"[^>]*>.*?</button>', html, re.S).group(0)

    def test_label_is_reject_and_value_stays_disputed(self):
        for reason in ("Not Found in NetSuite", "Amount Mismatch", "Invoice Missing", "EXTRACTION_INCOMPLETE"):
            with self.subTest(reason=reason):
                button = self._button(_render(reason))
                self.assertIn('name="action" value="DISPUTED"', button)
                self.assertEqual(_visible_text(button).strip(), "Reject")

    def test_styling_and_icon_are_unchanged(self):
        button = self._button(_render())
        self.assertIn('class="btn btn-dispute"', button)
        self.assertIn('type="submit"', button)
        self.assertIn('<use href="#i-x-circle"/>', button)

    def test_no_visible_dispute_wording_left_on_the_page(self):
        text = _visible_text(_render()).lower()
        self.assertNotIn("disput", text)
        self.assertIn("reject", text)

    def test_accept_button_is_unchanged(self):
        html = _render()
        accept = re.search(r'<button[^>]*value="ACCEPTED"[^>]*>.*?</button>', html, re.S).group(0)
        self.assertEqual(_visible_text(accept).strip(), "Accept")


class TestRejectStillStoresDisputed(unittest.TestCase):
    """POSTing the Reject button records DISPUTED, exactly as before."""

    def test_reject_posts_disputed_to_resolve_exception(self):
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key="test-secret")
        app.include_router(exceptions.router)
        app.dependency_overrides[require_login] = lambda: "tester"
        with mock.patch("web.queries.resolve_exception") as resolve:
            resp = TestClient(app).post(
                "/exceptions/Keystone%20Automotive%20Industries",
                data={"exception_id": "exc-1", "statement_id": "STMT-TEST", "invoice_number": "900CC752",
                      "reason_code": "Not Found in NetSuite", "action": "DISPUTED", "note": ""},
                follow_redirects=False,
            )
        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resolve.call_args.kwargs["disposition_status"], "DISPUTED")


if __name__ == "__main__":
    unittest.main()
