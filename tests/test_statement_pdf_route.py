"""
tests/test_statement_pdf_route.py

GET /statements/{document_hash}/pdf -- the target of the link the NetSuite
write-back puts on bills -- and the login redirect that gets a user from
that link to the PDF. The DB lookup and blob download are mocked, so
nothing here touches SQLite, Azure or Fabric.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from web.deps import LoginRequired
from web.routers import auth, statements

HASH = "a" * 64
PDF_BYTES = b"%PDF-1.4 fake statement"
ARCHIVED = {"blob_storage_path": "https://acct.blob.core.windows.net/raw/v/2026/09/x.pdf",
            "original_filename": "Gates GMC New Britain 0826.pdf"}


def _app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")

    @app.exception_handler(LoginRequired)
    async def _handler(request, exc):
        # Same behaviour as web/app.py's handler.
        if request.method == "GET":
            request.session["next"] = request.url.path
        return RedirectResponse("/login", status_code=303)

    app.include_router(statements.router)
    app.include_router(auth.router)
    return app


def _logged_in_client():
    client = TestClient(_app())
    with mock.patch.object(auth, "_authenticate", return_value="Tester"):
        client.post("/login", data={"email": "t@example.com", "password": "x"}, follow_redirects=False)
    return client


class StatementPdfRouteTests(unittest.TestCase):
    def test_serves_the_archived_pdf_inline(self):
        client = _logged_in_client()
        with mock.patch.object(statements.queries, "get_archived_pdf_for_document_hash", return_value=ARCHIVED), \
             mock.patch.object(statements, "_fetch_pdf_bytes", return_value=PDF_BYTES) as fetch:
            resp = client.get(f"/statements/{HASH}/pdf")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "application/pdf")
        self.assertTrue(resp.headers["content-disposition"].startswith("inline;"))
        self.assertIn("Gates GMC New Britain 0826.pdf", resp.headers["content-disposition"])
        self.assertEqual(resp.content, PDF_BYTES)
        fetch.assert_called_once_with(ARCHIVED["blob_storage_path"])

    def test_malformed_hash_is_404_without_touching_the_db(self):
        client = _logged_in_client()
        with mock.patch.object(statements.queries, "get_archived_pdf_for_document_hash") as lookup:
            for bad in ("abc", "A" * 64, "g" * 64, "../etc/passwd", "a" * 65):
                with self.subTest(bad=bad):
                    self.assertEqual(client.get(f"/statements/{bad}/pdf").status_code, 404)
        lookup.assert_not_called()

    def test_unknown_hash_is_404(self):
        client = _logged_in_client()
        with mock.patch.object(statements.queries, "get_archived_pdf_for_document_hash", return_value=None):
            self.assertEqual(client.get(f"/statements/{HASH}/pdf").status_code, 404)

    def test_blob_download_failure_is_404(self):
        client = _logged_in_client()
        with mock.patch.object(statements.queries, "get_archived_pdf_for_document_hash", return_value=ARCHIVED), \
             mock.patch.object(statements, "_fetch_pdf_bytes", return_value=None):
            self.assertEqual(client.get(f"/statements/{HASH}/pdf").status_code, 404)

    def test_filename_cannot_break_out_of_the_header(self):
        self.assertEqual(statements._inline_filename('a"b\r\nX: y.pdf'), "a_b__X_ y.pdf")
        self.assertEqual(statements._inline_filename(None), "statement.pdf")
        self.assertEqual(statements._inline_filename("no_extension"), "no_extension.pdf")


class ShortLinkRouteTests(unittest.TestCase):
    """/statements/<statement id>/<name>.pdf -- the link the write-back stores."""

    def _get(self, path, archived=ARCHIVED):
        client = _logged_in_client()
        with mock.patch.object(statements.queries, "get_archived_pdf_for_statement", return_value=archived) as by_id, \
             mock.patch.object(statements.queries, "get_archived_pdf_for_document_hash", return_value=ARCHIVED) as by_hash, \
             mock.patch.object(statements, "_fetch_pdf_bytes", return_value=PDF_BYTES):
            return client.get(path), by_id, by_hash

    def test_serves_the_pdf_found_by_statement_id(self):
        resp, by_id, by_hash = self._get("/statements/STMT-60A970B4/BMW.pdf")
        self.assertEqual((resp.status_code, resp.headers["content-type"]), (200, "application/pdf"))
        self.assertEqual(resp.content, PDF_BYTES)
        by_id.assert_called_once_with("STMT-60A970B4")
        by_hash.assert_not_called()

    def test_the_name_in_the_link_is_only_cosmetic(self):
        resp, by_id, _ = self._get("/statements/STMT-60A970B4/some-other-name.pdf")
        self.assertEqual(resp.status_code, 200)
        by_id.assert_called_once_with("STMT-60A970B4")

    def test_the_name_is_used_for_the_download_when_the_archive_has_none(self):
        resp, _, _ = self._get("/statements/STMT-60A970B4/BMW.pdf",
                               archived={"blob_storage_path": "https://x/y.pdf", "original_filename": None})
        self.assertIn('filename="BMW.pdf"', resp.headers["content-disposition"])

    def test_a_name_that_is_not_a_pdf_or_a_malformed_id_is_404_without_a_lookup(self):
        client = _logged_in_client()
        with mock.patch.object(statements.queries, "get_archived_pdf_for_statement") as by_id:
            for path in ("/statements/STMT-60A970B4/BMW.txt", "/statements/STMT-60A970B4/BMW",
                         "/statements/NOTANID/BMW.pdf", "/statements/STMT-%27%3B--/BMW.pdf"):
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 404)
        by_id.assert_not_called()

    def test_an_unknown_statement_is_404(self):
        resp, _, _ = self._get("/statements/STMT-00000000/BMW.pdf", archived=None)
        self.assertEqual(resp.status_code, 404)

    def test_the_old_hash_link_still_goes_to_the_hash_lookup(self):
        resp, by_id, by_hash = self._get(f"/statements/{HASH}/pdf")
        self.assertEqual(resp.status_code, 200)
        by_hash.assert_called_once_with(HASH)
        by_id.assert_not_called()

    def test_logged_out_visitors_are_sent_to_login(self):
        client = TestClient(_app())
        resp = client.get("/statements/STMT-60A970B4/BMW.pdf", follow_redirects=False)
        self.assertEqual((resp.status_code, resp.headers["location"]), (303, "/login"))


class StatementLookupTests(unittest.TestCase):
    def test_the_intake_row_is_used_when_there_is_one(self):
        with mock.patch.object(statements.queries, "execute_query", return_value=[ARCHIVED]) as q:
            self.assertEqual(statements.queries.get_archived_pdf_for_statement("STMT-1"), ARCHIVED)
        self.assertEqual(q.call_count, 1)

    def test_it_falls_back_to_the_jobs_document_hash(self):
        with mock.patch.object(statements.queries, "execute_query",
                               side_effect=[[], [{"document_hash": HASH}]]), \
             mock.patch.object(statements.queries, "get_archived_pdf_for_document_hash",
                               return_value=ARCHIVED) as by_hash:
            self.assertEqual(statements.queries.get_archived_pdf_for_statement("STMT-1"), ARCHIVED)
        by_hash.assert_called_once_with(HASH)

    def test_nothing_known_gives_none(self):
        with mock.patch.object(statements.queries, "execute_query", side_effect=[[], []]):
            self.assertIsNone(statements.queries.get_archived_pdf_for_statement("STMT-1"))


class LoginRedirectTests(unittest.TestCase):
    def test_logged_out_user_is_sent_to_login_then_back_to_the_pdf(self):
        client = TestClient(_app())
        first = client.get(f"/statements/{HASH}/pdf", follow_redirects=False)
        self.assertEqual((first.status_code, first.headers["location"]), (303, "/login"))
        with mock.patch.object(auth, "_authenticate", return_value="Tester"):
            login = client.post("/login", data={"email": "t@example.com", "password": "x"},
                                follow_redirects=False)
        self.assertEqual(login.headers["location"], f"/statements/{HASH}/pdf")

    def test_plain_login_still_goes_to_the_dashboard(self):
        client = TestClient(_app())
        with mock.patch.object(auth, "_authenticate", return_value="Tester"):
            login = client.post("/login", data={"email": "t@example.com", "password": "x"},
                                follow_redirects=False)
        self.assertEqual(login.headers["location"], "/")

    def test_the_stored_target_is_used_only_once(self):
        client = TestClient(_app())
        client.get(f"/statements/{HASH}/pdf", follow_redirects=False)
        with mock.patch.object(auth, "_authenticate", return_value="Tester"):
            client.post("/login", data={"email": "t@example.com", "password": "x"}, follow_redirects=False)
            client.get("/logout", follow_redirects=False)
            again = client.post("/login", data={"email": "t@example.com", "password": "x"},
                                follow_redirects=False)
        self.assertEqual(again.headers["location"], "/")

    def test_off_site_targets_are_never_followed(self):
        for target in ("//evil.example/x", "https://evil.example", "evil"):
            with self.subTest(target=target):
                request = mock.Mock()
                request.session = {"next": target}
                self.assertEqual(auth._post_login_destination(request), "/")


if __name__ == "__main__":
    unittest.main()
