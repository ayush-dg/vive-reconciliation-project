"""
tests/test_pdf_editing.py

In-app PDF editing (PDF_EDIT_ENABLED, 2026-11-02): View PDF shows the
statement's SharePoint file, the PDF.js editor saves back into it in place,
saves over a newer version are refused, each save is logged, and intake treats
an edited copy as a duplicate of its statement. SharePoint, the database and
the blob store are all faked -- nothing here touches the network.
"""

import hashlib
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.lakehouse import azure_sql_migrations as azure
from src.lakehouse.migrations import apply_pending_migrations
from src.storage import sharepoint_client as sp
from web.deps import LoginRequired
from web.routers import auth, exceptions, statements

from tests.test_sharepoint_client import SETTINGS, TOKEN, FakeHTTP, FakeResponse

DRIVE = "b!drive-id"
ITEM = "ITEM01"
ETAG = '"{ABC},1"'
NEW_ETAG = '"{ABC},2"'
SHAREPOINT = {"statement_id": "STMT-60A970B4", "sharepoint_drive_id": DRIVE, "sharepoint_item_id": ITEM,
              "sharepoint_web_url": "https://vivecollision.sharepoint.com/sites/x/BMW__abc.pdf",
              "original_filename": "BMW 0926.pdf"}
ARCHIVED = {"blob_storage_path": "https://acct.blob.core.windows.net/vendor-statements/x.pdf",
            "original_filename": "BMW 0926.pdf"}
EDIT_ON = {"PDF_EDIT_ENABLED": "true"}


def _pdf(pages=1, text="statement"):
    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


class BinaryResponse(FakeResponse):
    def __init__(self, status_code, content):
        super().__init__(status_code, None)
        self.content = content


def _client(rules):
    http = FakeHTTP(rules)
    return sp.SharePointArchiveClient(SETTINGS, http=http, token_provider=lambda: TOKEN,
                                      sleep=lambda s: None), http


def _info(etag=ETAG, size=100):
    return FakeResponse(200, {"id": ITEM, "eTag": etag, "size": size, "webUrl": SHAREPOINT["sharepoint_web_url"]})


# ---------------------------------------------------------------------------
# SharePoint client: read by id, replace in place
# ---------------------------------------------------------------------------

class GetFileTests(unittest.TestCase):
    def test_reads_the_etag_and_the_bytes(self):
        client, http = _client([("GET", "/content", [BinaryResponse(200, b"%PDF-bytes")]),
                                ("GET", f"/items/{ITEM}?", [_info()])])
        found = client.get_file(DRIVE, ITEM, with_content=True)
        self.assertEqual((found.etag, found.size, found.content), (ETAG, 100, b"%PDF-bytes"))
        self.assertEqual({c["method"] for c in http.calls}, {"GET"})

    def test_without_content_only_the_metadata_is_read(self):
        client, http = _client([("GET", f"/items/{ITEM}?", [_info()])])
        self.assertIsNone(client.get_file(DRIVE, ITEM).content)
        self.assertEqual(len(http.calls), 1)

    def test_a_missing_file_gives_none(self):
        client, _ = _client([("GET", f"/items/{ITEM}?", [FakeResponse(404, {"error": {"code": "itemNotFound"}})])])
        self.assertIsNone(client.get_file(DRIVE, ITEM, with_content=True))

    def test_an_auth_failure_gives_none(self):
        client = sp.SharePointArchiveClient(SETTINGS, http=FakeHTTP([]), token_provider=mock.Mock(side_effect=RuntimeError))
        self.assertIsNone(client.get_file(DRIVE, ITEM))


class ReplaceFileTests(unittest.TestCase):
    def test_a_small_file_is_put_with_if_match(self):
        client, http = _client([("PUT", f"/items/{ITEM}/content", [FakeResponse(200, {"eTag": NEW_ETAG, "size": 5})])])
        result = client.replace_file(DRIVE, ITEM, b"%PDF-", ETAG)
        self.assertEqual((result.status, result.etag, result.size), ("saved", NEW_ETAG, 5))
        self.assertEqual(http.calls[0]["headers"]["If-Match"], ETAG)
        self.assertNotIn("conflictBehavior", http.calls[0]["url"])  # replaces this item; never creates a new one

    def test_a_newer_version_is_a_conflict(self):
        client, _ = _client([("PUT", f"/items/{ITEM}/content", [FakeResponse(412, {"error": {"code": "notAllowed"}})])])
        self.assertEqual(client.replace_file(DRIVE, ITEM, b"%PDF-", ETAG).status, "conflict")

    def test_a_large_file_goes_through_an_upload_session_with_if_match(self):
        upload = "https://tenant.sharepoint.com/upload/xyz"
        data = b"x" * (sp.SIMPLE_UPLOAD_MAX_BYTES + 10)
        client, http = _client([
            ("POST", f"/items/{ITEM}/createUploadSession", [FakeResponse(200, {"uploadUrl": upload})]),
            ("PUT", upload, [FakeResponse(202, {}), FakeResponse(200, {"eTag": NEW_ETAG, "size": len(data)})]),
        ])
        result = client.replace_file(DRIVE, ITEM, data, ETAG)
        self.assertEqual((result.status, result.etag), ("saved", NEW_ETAG))
        self.assertEqual(http.calls[0]["headers"]["If-Match"], ETAG)
        self.assertEqual(sum(len(c["data"]) for c in http.calls[1:]), len(data))
        self.assertNotIn("Authorization", http.calls[1]["headers"])  # the session URL is pre-authenticated

    def test_a_large_file_conflict_is_reported(self):
        client, _ = _client([("POST", "/createUploadSession", [FakeResponse(412, {})])])
        self.assertEqual(client.replace_file(DRIVE, ITEM, b"x" * (sp.SIMPLE_UPLOAD_MAX_BYTES + 1), ETAG).status,
                         "conflict")

    def test_no_etag_or_no_data_sends_nothing(self):
        client, http = _client([])
        self.assertEqual(client.replace_file(DRIVE, ITEM, b"%PDF-", "").status, "failed")
        self.assertEqual(client.replace_file(DRIVE, ITEM, b"", ETAG).status, "failed")
        self.assertEqual(http.calls, [])

    def test_never_deletes_and_never_leaks_the_token(self):
        client, http = _client([("PUT", "/content", [FakeResponse(403, {"error": {"code": "accessDenied " + TOKEN}})])])
        result = client.replace_file(DRIVE, ITEM, b"%PDF-", ETAG)
        self.assertEqual(result.status, "failed")
        self.assertNotIn(TOKEN, result.error)
        self.assertNotIn("DELETE", {c["method"] for c in http.calls})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _app():
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test")

    @app.exception_handler(LoginRequired)
    async def _handler(request, exc):
        return RedirectResponse("/login", status_code=303)

    app.include_router(statements.router)
    app.include_router(auth.router)
    return app


def _logged_in():
    client = TestClient(_app())
    with mock.patch.object(auth, "_authenticate", return_value="Tester"):
        client.post("/login", data={"email": "t@example.com", "password": "x"}, follow_redirects=False)
    return client


class FakeSharePoint:
    """Stands in for SharePointArchiveClient in the routes."""

    def __init__(self, current=b"", etag=ETAG, readable=True, replace_status="saved"):
        self.current, self.etag, self.readable, self.replace_status = current, etag, readable, replace_status
        self.replaced = []

    def get_file(self, drive_id, item_id, with_content=False):
        if not self.readable:
            return None
        return sp.SharePointFile(etag=self.etag, size=len(self.current), content=self.current if with_content else None)

    def replace_file(self, drive_id, item_id, data, if_match):
        self.replaced.append((drive_id, item_id, data, if_match))
        if self.replace_status == "saved":
            return sp.SharePointReplaceResult("saved", etag=NEW_ETAG, size=len(data))
        return sp.SharePointReplaceResult(self.replace_status, error="x")


class ViewTests(unittest.TestCase):
    def _get(self, path, env=EDIT_ON, fake=None, sharepoint=SHAREPOINT):
        fake = fake or FakeSharePoint(current=b"%PDF-sharepoint")
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(statements.queries, "get_statement_pdf", return_value=ARCHIVED), \
             mock.patch.object(statements.queries, "get_sharepoint_pdf_for_statement", return_value=sharepoint) as lookup, \
             mock.patch.object(statements, "_sharepoint_client", return_value=fake), \
             mock.patch.object(statements, "_fetch_pdf_bytes", return_value=b"%PDF-azure"):
            return _logged_in().get(path, follow_redirects=False), lookup

    def test_with_editing_off_nothing_changes(self):
        with mock.patch.dict(os.environ, {"PDF_EDIT_ENABLED": ""}):
            resp, lookup = self._get("/statements/STMT-60A970B4/BMW.pdf", env={"PDF_EDIT_ENABLED": ""})
        self.assertEqual(resp.content, b"%PDF-azure")
        lookup.assert_not_called()

    def test_the_sharepoint_copy_is_shown_first_and_not_cached(self):
        resp, _ = self._get("/statements/STMT-60A970B4/BMW.pdf")
        self.assertEqual(resp.content, b"%PDF-sharepoint")
        self.assertEqual(resp.headers["cache-control"], "no-store")

    def test_sharepoint_down_falls_back_to_the_azure_copy(self):
        resp, _ = self._get("/statements/STMT-60A970B4/BMW.pdf", fake=FakeSharePoint(readable=False))
        self.assertEqual((resp.status_code, resp.content), (200, b"%PDF-azure"))

    def test_original_skips_sharepoint(self):
        resp, lookup = self._get("/statements/STMT-60A970B4/BMW.pdf?original=1")
        self.assertEqual(resp.content, b"%PDF-azure")
        lookup.assert_not_called()

    def test_a_statement_only_in_sharepoint_still_opens(self):
        fake = FakeSharePoint(current=b"%PDF-sharepoint")
        with mock.patch.dict(os.environ, EDIT_ON), \
             mock.patch.object(statements.queries, "get_statement_pdf", return_value=None), \
             mock.patch.object(statements.queries, "get_sharepoint_pdf_for_statement", return_value=SHAREPOINT), \
             mock.patch.object(statements, "_sharepoint_client", return_value=fake):
            resp = _logged_in().get("/statements/STMT-60A970B4/BMW.pdf")
        self.assertEqual((resp.status_code, resp.content), (200, b"%PDF-sharepoint"))
        self.assertIn('filename="BMW 0926.pdf"', resp.headers["content-disposition"])

    def test_edit_opens_the_viewer_at_the_current_etag(self):
        resp, _ = self._get("/statements/STMT-60A970B4/BMW.pdf?edit=1")
        self.assertEqual(resp.status_code, 303)
        location = resp.headers["location"]
        # The file URL carries no query string: PDF.js 5.x would keep it in the path and 404.
        self.assertTrue(location.startswith(statements.VIEWER_PATH + "?file=%2Fstatements%2FSTMT-60A970B4%2FBMW.pdf&"))
        self.assertIn("vive_sid=STMT-60A970B4", location)
        self.assertIn("vive_etag=%22%7BABC%7D%2C1%22", location)

    def test_the_viewer_gets_the_plain_file_path(self):
        # PDF.js 5.x encodes it itself: a space must reach it as "%20" once, never "%2520".
        resp, _ = self._get("/statements/STMT-60A970B4/BMW%200926.pdf?edit=1")
        self.assertIn("?file=%2Fstatements%2FSTMT-60A970B4%2FBMW%200926.pdf&", resp.headers["location"])

    def test_edit_without_a_sharepoint_copy_opens_the_plain_pdf(self):
        resp, _ = self._get("/statements/STMT-60A970B4/BMW.pdf?edit=1", sharepoint=None)
        self.assertEqual((resp.status_code, resp.headers["location"]), (303, "/statements/STMT-60A970B4/BMW.pdf"))

    def test_edit_with_sharepoint_unreadable_opens_the_plain_pdf(self):
        resp, _ = self._get("/statements/STMT-60A970B4/BMW.pdf?edit=1", fake=FakeSharePoint(readable=False))
        self.assertEqual(resp.headers["location"], "/statements/STMT-60A970B4/BMW.pdf")


class SaveTests(unittest.TestCase):
    def _post(self, body, etag=ETAG, fake=None, env=EDIT_ON, sharepoint=SHAREPOINT, client=None):
        fake = fake if fake is not None else FakeSharePoint(current=_pdf(2))
        headers = {"Content-Type": "application/pdf"}
        if etag:
            headers["If-Match"] = etag
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(statements.queries, "get_sharepoint_pdf_for_statement", return_value=sharepoint), \
             mock.patch.object(statements.queries, "record_pdf_edit") as record, \
             mock.patch.object(statements, "_sharepoint_client", return_value=fake):
            resp = (client or _logged_in()).post("/statements/STMT-60A970B4/pdf", content=body, headers=headers,
                                                 follow_redirects=False)
        return resp, fake, record

    def test_a_good_save_replaces_the_file_and_is_logged(self):
        edited = _pdf(2, "edited")
        resp, fake, record = self._post(edited)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"saved": True, "etag": NEW_ETAG})
        self.assertEqual(fake.replaced, [(DRIVE, ITEM, edited, ETAG)])
        args = record.call_args[0]
        self.assertEqual(args[:3], ("STMT-60A970B4", "t@example.com", DRIVE))  # the logged-in user
        self.assertEqual(args[-1], hashlib.sha256(edited).hexdigest())

    def test_editing_off_is_404(self):
        resp, fake, _ = self._post(_pdf(2), env={"PDF_EDIT_ENABLED": "false"})
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(fake.replaced, [])

    def test_a_save_over_a_newer_version_is_refused(self):
        resp, fake, record = self._post(_pdf(2), etag='"{ABC},0"')
        self.assertEqual(resp.status_code, 409)
        self.assertIn("Someone else saved", resp.json()["error"])
        self.assertEqual(fake.replaced, [])
        record.assert_not_called()

    def test_sharepoints_own_conflict_is_refused_too(self):
        resp, _, record = self._post(_pdf(2), fake=FakeSharePoint(current=_pdf(2), replace_status="conflict"))
        self.assertEqual(resp.status_code, 409)
        record.assert_not_called()

    def test_not_a_pdf_or_a_different_page_count_is_refused(self):
        for body, why in ((b"hello", "not a PDF"), (b"%PDF-garbage", "not a readable PDF"),
                          (_pdf(3), "different number of pages")):
            with self.subTest(why=why):
                resp, fake, _ = self._post(body)
                self.assertEqual(resp.status_code, 400)
                self.assertEqual(fake.replaced, [])

    def test_no_if_match_is_refused(self):
        resp, fake, _ = self._post(_pdf(2), etag=None)
        self.assertEqual(resp.status_code, 428)
        self.assertEqual(fake.replaced, [])

    def test_too_large_is_refused(self):
        with mock.patch.object(statements, "MAX_EDIT_BYTES", 10):
            resp, fake, _ = self._post(_pdf(2))
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(fake.replaced, [])

    def test_no_sharepoint_copy_is_404(self):
        resp, _, _ = self._post(_pdf(2), sharepoint=None)
        self.assertEqual(resp.status_code, 404)

    def test_sharepoint_unreachable_saves_nothing(self):
        resp, _, _ = self._post(_pdf(2), fake=FakeSharePoint(readable=False))
        self.assertEqual(resp.status_code, 502)

    def test_a_failed_log_row_does_not_fail_the_save(self):
        with mock.patch.dict(os.environ, EDIT_ON), \
             mock.patch.object(statements.queries, "get_sharepoint_pdf_for_statement", return_value=SHAREPOINT), \
             mock.patch.object(statements.queries, "record_pdf_edit", side_effect=RuntimeError("db down")), \
             mock.patch.object(statements, "_sharepoint_client", return_value=FakeSharePoint(current=_pdf(2))):
            resp = _logged_in().post("/statements/STMT-60A970B4/pdf", content=_pdf(2),
                                     headers={"If-Match": ETAG})
        self.assertEqual(resp.json()["saved"], True)

    def test_logged_out_cannot_save(self):
        resp, fake, _ = self._post(_pdf(2), client=TestClient(_app()))
        self.assertEqual((resp.status_code, resp.headers["location"]), (303, "/login"))
        self.assertEqual(fake.replaced, [])


class ViewPdfLinkTests(unittest.TestCase):
    def _url(self, env, archived=ARCHIVED, sharepoint=SHAREPOINT):
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(exceptions.queries, "get_statement_pdf", return_value=archived), \
             mock.patch.object(exceptions.queries, "get_sharepoint_pdf_for_statement", return_value=sharepoint):
            return exceptions._statement_pdf_url("STMT-60A970B4")

    def test_editing_off_is_the_plain_link(self):
        self.assertEqual(self._url({"PDF_EDIT_ENABLED": ""}), "/statements/STMT-60A970B4/BMW%200926.pdf")

    def test_editing_on_with_a_sharepoint_copy_opens_the_editor(self):
        self.assertEqual(self._url(EDIT_ON), "/statements/STMT-60A970B4/BMW%200926.pdf?edit=1")

    def test_editing_on_without_a_sharepoint_copy_stays_plain(self):
        self.assertEqual(self._url(EDIT_ON, sharepoint=None), "/statements/STMT-60A970B4/BMW%200926.pdf")

    def test_a_sharepoint_only_statement_gets_a_link(self):
        self.assertEqual(self._url(EDIT_ON, archived=None), "/statements/STMT-60A970B4/BMW%200926.pdf?edit=1")
        self.assertIsNone(self._url({"PDF_EDIT_ENABLED": ""}, archived=None))


# ---------------------------------------------------------------------------
# Edit log table and intake
# ---------------------------------------------------------------------------

class EditLogSchemaTests(unittest.TestCase):
    def test_sqlite_and_azure_describe_the_same_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = sqlite3.connect(os.path.join(tmp, "t.db"))
            apply_pending_migrations(conn)
            sqlite_cols = [row[1] for row in conn.execute("PRAGMA table_info(statement_pdf_edits)")]
            conn.close()
        azure_cols = re.findall(r"^\s+(\w+)\s+(?:INT|BIGINT|NVARCHAR)", azure.TABLES["statement_pdf_edits"], re.M)
        self.assertEqual(azure_cols, sqlite_cols)

    def test_it_is_the_newest_table(self):
        self.assertEqual(list(azure.TABLES)[-1], "statement_pdf_edits")


class IntakeEditedCopyTests(unittest.TestCase):
    def setUp(self):
        from tests.test_intake_sharepoint_hook import load_intake
        self.intake = load_intake()

    def test_an_edited_copy_is_found_by_its_hash(self):
        with mock.patch.object(self.intake, "execute_query", return_value=[{"statement_id": "STMT-60A970B4"}]) as q:
            self.assertEqual(self.intake.find_edited_copy("c" * 64), {"statement_id": "STMT-60A970B4"})
        self.assertEqual(q.call_args[0][1], ["c" * 64])

    def test_an_unknown_file_or_a_lookup_problem_is_not_an_edit(self):
        with mock.patch.object(self.intake, "execute_query", return_value=[]):
            self.assertIsNone(self.intake.find_edited_copy("c" * 64))
        with mock.patch.object(self.intake, "execute_query", side_effect=RuntimeError("no such table")):
            self.assertIsNone(self.intake.find_edited_copy("c" * 64))

    def test_intake_reports_an_edited_copy_as_a_duplicate_of_its_statement(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(_pdf(1))
        try:
            with mock.patch.object(self.intake, "check_cache", return_value=None), \
                 mock.patch.object(self.intake, "find_edited_copy", return_value={"statement_id": "STMT-60A970B4"}), \
                 mock.patch.object(self.intake, "execute_query", return_value=[{"cnt": 12}]):
                result = self.intake.run_intake(f.name)
        finally:
            os.remove(f.name)
        self.assertEqual((result["duplicate_of"], result["bronze_count"]), ("STMT-60A970B4", 12))


if __name__ == "__main__":
    unittest.main()
