"""
Tests for src/storage/sharepoint_client.py with a fake HTTP layer and a fake
token -- no network (tests/conftest.py blocks sockets anyway).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.storage import sharepoint_client as sp  # noqa: E402

SECRET = "s3cr3t-VALUE-never-shown"
TOKEN = "eyJ0eXAi.fake-token.never-shown"
DRIVE = "b!drive-id"
UPLOAD_URL = "https://tenant.sharepoint.com/upload-session/abc?tempauth=xyz"
HASH = "ab" * 32

SETTINGS = {
    "tenant_id": "tenant", "client_id": "client", "client_secret": SECRET,
    "site_hostname": "vivecollision.sharepoint.com", "site_path": "/sites/aivendorstatements",
    "library": "Documents", "base_folder": "General/Vendor Statements/_dev_test",
}

ENV_OK = {
    "SHAREPOINT_TENANT_ID": "tenant", "SHAREPOINT_CLIENT_ID": "client", "SHAREPOINT_CLIENT_SECRET": SECRET,
    "SHAREPOINT_SITE_HOSTNAME": "vivecollision.sharepoint.com", "SHAREPOINT_SITE_PATH": "/sites/aivendorstatements",
    "SHAREPOINT_LIBRARY": "Documents", "SHAREPOINT_BASE_FOLDER": "General/Vendor Statements/_dev_test",
}


class FakeResponse:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}
        self.text = str(body)

    def json(self):
        return self._body


class FakeHTTP:
    """Answers each request from the first matching (method, url fragment)
    rule; a rule's responses are used in order and the last one repeats."""

    def __init__(self, rules):
        self.rules = [(m, frag, list(resps)) for m, frag, resps in rules]
        self.calls = []

    def __call__(self, method, url, headers=None, data=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "data": data, "json": json})
        for m, frag, resps in self.rules:
            if m == method and frag in url:
                return resps.pop(0) if len(resps) > 1 else resps[0]
        raise AssertionError(f"unexpected request {method} {url}")


def _lookup_rules(base_status=200):
    return [
        ("GET", "/sites/vivecollision.sharepoint.com:", [FakeResponse(200, {"id": "site-1"})]),
        ("GET", "/sites/site-1/drives", [FakeResponse(200, {"value": [{"id": "other", "name": "Site Assets"},
                                                                    {"id": DRIVE, "name": "Documents"}]})]),
        ("GET", "/root:/General/Vendor%20Statements/_dev_test?", [
            FakeResponse(base_status, {"id": "f1", "folder": {"childCount": 0}} if base_status == 200 else
                         {"error": {"code": "itemNotFound"}})]),
    ]


def _item(path="x", size=None):
    body = {"id": "item-1", "webUrl": "https://vivecollision.sharepoint.com/sites/AIVendorStatements/" + path}
    if size is not None:
        body["size"] = size
    return body


class _PdfCase(unittest.TestCase):
    def make_pdf(self, size):
        fd, path = tempfile.mkstemp(suffix=".pdf")
        with os.fdopen(fd, "wb") as f:
            f.write(b"%PDF-1.4\n" + b"x" * (size - 9))
        self.addCleanup(os.remove, path)
        return path

    def client(self, http, token=TOKEN, clock=None):
        self.sleeps = []
        return sp.SharePointArchiveClient(SETTINGS, http=http, token_provider=lambda: token,
                                          sleep=self.sleeps.append, clock=clock or (lambda: 0.0))

    def upload(self, client, pdf, original="Fred Beans - Rockland.pdf"):
        return client.upload_statement_pdf(pdf, vendor_name="Fred Beans", year="2026", month="9",
                                           document_hash=HASH, original_filename=original)

    def assertNoSecrets(self, http, result):
        text = repr(result) + repr(http.calls if http else "")
        self.assertNotIn(SECRET, repr(result))
        self.assertNotIn(TOKEN, repr(result))
        for call in (http.calls if http else []):
            self.assertNotIn(SECRET, repr(call))

    def assertNeverDeletesFiles(self, http):
        for call in http.calls:
            if call["method"] == "DELETE":
                self.assertEqual(call["url"], UPLOAD_URL, "the only DELETE allowed is cancelling the upload session")


class TestSettings(unittest.TestCase):
    def test_flag_is_off_unless_literally_true(self):
        for value in ("", "false", "1", "yes", "TRUE "):
            with mock.patch.dict(os.environ, {"SHAREPOINT_ARCHIVE_ENABLED": value}):
                self.assertEqual(sp.sharepoint_enabled(), value.strip().lower() == "true")

    def test_missing_settings_are_named_without_values(self):
        env = dict(ENV_OK, SHAREPOINT_CLIENT_SECRET="", SHAREPOINT_LIBRARY="")
        with mock.patch.dict(os.environ, env):
            settings, reason = sp.read_settings()
        self.assertIsNone(settings)
        self.assertEqual(reason, "missing setting(s): SHAREPOINT_CLIENT_SECRET, SHAREPOINT_LIBRARY")

    def test_complete_settings(self):
        with mock.patch.dict(os.environ, ENV_OK):
            settings, reason = sp.read_settings()
        self.assertIsNone(reason)
        self.assertEqual(settings["base_folder"], "General/Vendor Statements/_dev_test")
        self.assertEqual(settings["site_path"], "/sites/aivendorstatements")

    def test_live_folder_is_refused_unless_allowed(self):
        env = dict(ENV_OK, SHAREPOINT_BASE_FOLDER="General/Vendor Statements", SHAREPOINT_ALLOW_LIVE_FOLDER="")
        with mock.patch.dict(os.environ, env):
            settings, reason = sp.read_settings()
        self.assertIsNone(settings)
        self.assertIn("_dev_test", reason)
        self.assertNotIn(SECRET, reason)
        with mock.patch.dict(os.environ, dict(env, SHAREPOINT_ALLOW_LIVE_FOLDER="true")):
            settings, reason = sp.read_settings()
        self.assertIsNone(reason)
        self.assertEqual(settings["base_folder"], "General/Vendor Statements")

    def test_dev_folder_must_be_the_last_segment(self):
        env = dict(ENV_OK, SHAREPOINT_BASE_FOLDER="General/_dev_test/Vendor Statements")
        with mock.patch.dict(os.environ, env):
            self.assertIsNone(sp.read_settings()[0])


class TestNaming(unittest.TestCase):
    def test_path_shape(self):
        path = sp.build_path("General/Vendor Statements/_dev_test", "Fred Beans", "2026", "9",
                             "Fred Beans- Rockland.pdf", HASH)
        self.assertEqual(path, "General/Vendor Statements/_dev_test/fred_beans/2026/09/"
                               "Fred Beans- Rockland__abababababab.pdf")

    def test_illegal_characters_and_trimming(self):
        self.assertEqual(sp.safe_stem(' .a"b*c:d<e>f?g|h#i%j\x01k. .pdf'), "a_b_c_d_e_f_g_h_i_j_k")
        self.assertEqual(sp.safe_stem("..."), "statement")
        self.assertEqual(sp.safe_stem(None), "statement")

    def test_stem_is_cut_to_80(self):
        self.assertEqual(len(sp.safe_stem("x" * 200 + ".pdf")), 80)

    def test_long_base_folder_shortens_the_stem_to_fit_400(self):
        base = "B" * 300 + "/_dev_test"
        path = sp.build_path(base, "v", "2026", "1", "y" * 200 + ".pdf", HASH)
        self.assertLessEqual(len(path), 400)
        self.assertTrue(path.endswith("__abababababab.pdf"))

    def test_path_that_cannot_fit_fails(self):
        with self.assertRaises(sp.SharePointUploadError):
            sp.build_path("B" * 390 + "/_dev_test", "v", "2026", "1", "a.pdf", HASH)


class TestSimpleUpload(_PdfCase):
    def test_small_file_one_put_with_conflict_fail(self):
        pdf = self.make_pdf(300 * 1024)
        http = FakeHTTP(_lookup_rules() + [("PUT", ":/content", [FakeResponse(201, _item("a.pdf"))])])
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "uploaded")
        self.assertEqual(result.item_id, "item-1")
        self.assertEqual(result.drive_id, DRIVE)
        self.assertTrue(result.path.endswith("/fred_beans/2026/09/Fred Beans - Rockland__abababababab.pdf"))
        puts = [c for c in http.calls if c["method"] == "PUT"]
        self.assertEqual(len(puts), 1)
        self.assertIn("@microsoft.graph.conflictBehavior=fail", puts[0]["url"])
        self.assertIn("/root:/General/Vendor%20Statements/_dev_test/fred_beans/2026/09/", puts[0]["url"])
        self.assertEqual(puts[0]["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertNoSecrets(http, result)
        self.assertNeverDeletesFiles(http)

    def test_exactly_4_mib_is_still_a_simple_upload(self):
        pdf = self.make_pdf(sp.SIMPLE_UPLOAD_MAX_BYTES)
        http = FakeHTTP(_lookup_rules() + [("PUT", ":/content", [FakeResponse(200, _item())])])
        self.assertEqual(self.upload(self.client(http), pdf).status, "uploaded")
        self.assertFalse([c for c in http.calls if "createUploadSession" in c["url"]])


class TestBaseFolder(_PdfCase):
    def test_missing_base_folder_fails_and_creates_nothing(self):
        pdf = self.make_pdf(1000)
        http = FakeHTTP(_lookup_rules(base_status=404))
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "failed")
        self.assertIn("base folder missing", result.error)
        writes = [c for c in http.calls if c["method"] != "GET"]
        self.assertEqual(writes, [], "no upload and no folder creation")

    def test_library_not_found(self):
        pdf = self.make_pdf(1000)
        rules = _lookup_rules()
        rules[1] = ("GET", "/sites/site-1/drives", [FakeResponse(200, {"value": [{"id": "x", "name": "Other"}]})])
        result = self.upload(self.client(FakeHTTP(rules)), pdf)
        self.assertEqual((result.status, result.error), ("failed", "library not found on the site"))


class TestConflict(_PdfCase):
    def test_409_reuses_existing_file_of_same_size(self):
        pdf = self.make_pdf(5000)
        http = FakeHTTP(_lookup_rules() + [
            ("PUT", ":/content", [FakeResponse(409, {"error": {"code": "nameAlreadyExists"}})]),
            ("GET", "Rockland__abababababab.pdf?$select=id,webUrl,size", [FakeResponse(200, _item("b.pdf", 5000))]),
        ])
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "existing")
        self.assertEqual(result.web_url, _item("b.pdf")["webUrl"])
        self.assertNeverDeletesFiles(http)
        self.assertEqual(len([c for c in http.calls if c["method"] == "PUT"]), 1, "never overwritten")

    def test_409_with_different_size_fails(self):
        pdf = self.make_pdf(5000)
        http = FakeHTTP(_lookup_rules() + [
            ("PUT", ":/content", [FakeResponse(409, {"error": {"code": "nameAlreadyExists"}})]),
            ("GET", "?$select=id,webUrl,size", [FakeResponse(200, _item("b.pdf", 4999))]),
        ])
        result = self.upload(self.client(http), pdf)
        self.assertEqual((result.status, result.error), ("failed", "name exists with different size"))


class TestUploadSession(_PdfCase):
    def session_rules(self, chunk_responses, create=None):
        return _lookup_rules() + [
            ("POST", ":/createUploadSession", [create or FakeResponse(200, {"uploadUrl": UPLOAD_URL})]),
            ("PUT", "upload-session/abc", chunk_responses),
            ("DELETE", "upload-session/abc", [FakeResponse(204)]),
        ]

    def test_7mb_file_goes_in_3_chunks_of_10x320kib(self):
        size = 7 * 1024 * 1024 + 123
        pdf = self.make_pdf(size)
        http = FakeHTTP(self.session_rules([FakeResponse(202, {}), FakeResponse(202, {}),
                                            FakeResponse(201, _item("big.pdf"))]))
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "uploaded")
        create = [c for c in http.calls if c["method"] == "POST"][0]
        self.assertEqual(create["json"], {"item": {"@microsoft.graph.conflictBehavior": "fail"}})
        chunks = [c for c in http.calls if c["method"] == "PUT"]
        self.assertEqual(len(chunks), 3)
        self.assertEqual(sp.CHUNK_BYTES, 3_276_800)
        self.assertEqual(sp.CHUNK_BYTES % (320 * 1024), 0)
        self.assertEqual([len(c["data"]) for c in chunks[:2]], [3_276_800, 3_276_800])
        self.assertEqual(chunks[0]["headers"]["Content-Range"], f"bytes 0-3276799/{size}")
        self.assertEqual(chunks[1]["headers"]["Content-Range"], f"bytes 3276800-6553599/{size}")
        self.assertEqual(chunks[2]["headers"]["Content-Range"], f"bytes 6553600-{size - 1}/{size}")
        for c in chunks:
            self.assertNotIn("Authorization", c["headers"], "uploadUrl is pre-authenticated")
        self.assertFalse([c for c in http.calls if c["method"] == "DELETE"])
        self.assertNoSecrets(http, result)

    def test_409_at_create_reuses_existing(self):
        size = 5 * 1024 * 1024
        pdf = self.make_pdf(size)
        rules = self.session_rules([FakeResponse(202, {})], create=FakeResponse(409, {}))
        rules.append(("GET", "?$select=id,webUrl,size", [FakeResponse(200, _item("c.pdf", size))]))
        result = self.upload(self.client(FakeHTTP(rules)), pdf)
        self.assertEqual(result.status, "existing")

    def test_409_on_last_chunk_reuses_existing(self):
        size = 5 * 1024 * 1024
        pdf = self.make_pdf(size)
        rules = self.session_rules([FakeResponse(202, {}), FakeResponse(409, {"error": {"code": "nameAlreadyExists"}})])
        rules.append(("GET", "?$select=id,webUrl,size", [FakeResponse(200, _item("c.pdf", size))]))
        http = FakeHTTP(rules)
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "existing")
        self.assertNeverDeletesFiles(http)

    def test_chunk_failure_cancels_the_session_and_fails(self):
        pdf = self.make_pdf(5 * 1024 * 1024)
        http = FakeHTTP(self.session_rules([FakeResponse(202, {}), FakeResponse(400, {"error": {"code": "invalidRange"}})]))
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "failed")
        self.assertIn("HTTP 400 invalidRange", result.error)
        deletes = [c for c in http.calls if c["method"] == "DELETE"]
        self.assertEqual([d["url"] for d in deletes], [UPLOAD_URL])
        self.assertNotIn("tempauth", result.error)

    def test_time_budget_overrun_cancels_and_fails(self):
        pdf = self.make_pdf(5 * 1024 * 1024)
        # deadline + site, drives, base folder, createUploadSession, chunk 1 -> on time;
        # chunk 2 -> over budget
        ticks = iter([0.0] * 6 + [sp.UPLOAD_BUDGET_SECONDS + 1] * 20)
        http = FakeHTTP(self.session_rules([FakeResponse(202, {})]))
        result = self.upload(self.client(http, clock=lambda: next(ticks)), pdf)
        self.assertEqual(result.status, "failed")
        self.assertIn("timeout", result.error)
        self.assertEqual([c["url"] for c in http.calls if c["method"] == "DELETE"], [UPLOAD_URL])


class TestRetriesAndErrors(_PdfCase):
    def test_429_honours_retry_after_capped(self):
        pdf = self.make_pdf(1000)
        http = FakeHTTP(_lookup_rules() + [("PUT", ":/content", [
            FakeResponse(429, {}, {"Retry-After": "5"}), FakeResponse(503, {}, {"Retry-After": "999"}),
            FakeResponse(201, _item())])])
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "uploaded")
        self.assertEqual(self.sleeps, [5.0, float(sp.MAX_RETRY_AFTER)])

    def test_retries_run_out(self):
        pdf = self.make_pdf(1000)
        http = FakeHTTP(_lookup_rules() + [("PUT", ":/content", [FakeResponse(503, {})])])
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "failed")
        self.assertIn("HTTP 503", result.error)
        self.assertEqual(len([c for c in http.calls if c["method"] == "PUT"]), sp.MAX_RETRIES + 1)

    def test_transport_errors_never_raise_or_leak(self):
        pdf = self.make_pdf(1000)

        def boom(method, url, **kwargs):
            raise ConnectionError(f"failed to reach {UPLOAD_URL} with {TOKEN}")
        result = self.upload(self.client(boom), pdf)
        self.assertEqual(result.status, "failed")
        self.assertNotIn("tempauth", result.error)
        self.assertNotIn(TOKEN, result.error)

    def test_auth_failure_is_failed_without_details(self):
        pdf = self.make_pdf(1000)

        def bad_token():
            raise RuntimeError(f"AADSTS7000215 invalid client secret {SECRET}")
        http = FakeHTTP([])
        client = sp.SharePointArchiveClient(SETTINGS, http=http, token_provider=bad_token,
                                            sleep=lambda s: None, clock=lambda: 0.0)
        result = client.upload_statement_pdf(pdf, vendor_name="v", year="2026", month="1",
                                             document_hash=HASH, original_filename="a.pdf")
        self.assertEqual((result.status, result.error), ("failed", "authentication failed (RuntimeError)"))
        self.assertEqual(http.calls, [])

    def test_secret_in_an_error_body_is_redacted(self):
        pdf = self.make_pdf(1000)
        http = FakeHTTP(_lookup_rules() + [("PUT", ":/content", [FakeResponse(400, {"error": {"code": SECRET}})])])
        result = self.upload(self.client(http), pdf)
        self.assertEqual(result.status, "failed")
        self.assertNotIn(SECRET, result.error)
        self.assertIn("[REDACTED]", result.error)

    def test_bad_inputs_fail_before_any_request(self):
        http = FakeHTTP([])
        client = self.client(http)
        missing = client.upload_statement_pdf("no/such.pdf", vendor_name="v", year="2026", month="1",
                                              document_hash=HASH, original_filename="a.pdf")
        self.assertEqual((missing.status, missing.error), ("failed", "PDF file not found"))
        pdf = self.make_pdf(100)
        for kwargs, error in (({"document_hash": ""}, "document hash is empty"),
                              ({"month": "xx"}, "invalid year/month")):
            args = dict(vendor_name="v", year="2026", month="1", document_hash=HASH, original_filename="a.pdf")
            args.update(kwargs)
            self.assertEqual(client.upload_statement_pdf(pdf, **args).error, error)
        self.assertEqual(http.calls, [])


class TestCredential(unittest.TestCase):
    def test_uses_an_explicit_client_secret_credential(self):
        sp._CREDENTIALS.clear()
        self.addCleanup(sp._CREDENTIALS.clear)
        fake_token = mock.Mock(token="tok")
        with mock.patch("azure.identity.ClientSecretCredential") as csc:
            csc.return_value.get_token.return_value = fake_token
            provide = sp._default_token_provider(SETTINGS)
            self.assertEqual(provide(), "tok")
            self.assertEqual(provide(), "tok")
        csc.assert_called_once_with(tenant_id="tenant", client_id="client", client_secret=SECRET)
        csc.return_value.get_token.assert_called_with("https://graph.microsoft.com/.default")

    def test_module_never_uses_ambient_credentials_or_other_settings_names(self):
        with open(sp.__file__, encoding="utf-8") as f:
            source = f.read()
        code = source.split('"""', 2)[2]          # skip the module docstring
        for banned in ("DefaultAzureCredential", "EnvironmentCredential", "AZURE_", "FABRIC_", "print("):
            self.assertNotIn(banned, code)


if __name__ == "__main__":
    unittest.main()
