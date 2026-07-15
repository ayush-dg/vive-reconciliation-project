"""
tests/test_blob_client.py

Tests for BlobStorageClient using an injected fake transport.
No real Azure calls made -- tests run fully offline.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["AZURE_BLOB_TEST_CONNECTION_STRING"] = "AccountName=test;AccountKey=test;EndpointSuffix=core.windows.net"

from src.storage.blob_client import BlobStorageClient, _slugify_vendor_name


def _make_client(transport=None):
    return BlobStorageClient(
        container_name="vendor-statements",
        connection_string_env_var="AZURE_BLOB_TEST_CONNECTION_STRING",
        transport=transport,
    )


class TestSlugifyVendorName(unittest.TestCase):

    def test_lowercases_and_replaces_non_alphanumeric(self):
        self.assertEqual(_slugify_vendor_name("ABC Auto Parts, Inc."), "abc_auto_parts_inc")

    def test_none_or_empty_falls_back_to_unknown_vendor(self):
        self.assertEqual(_slugify_vendor_name(None), "unknown_vendor")
        self.assertEqual(_slugify_vendor_name(""), "unknown_vendor")


class TestBlobStorageClientUploadPdf(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        self.tmp.write(b"%PDF-1.4 fake content")
        self.tmp.close()
        self.pdf_path = self.tmp.name

    def tearDown(self):
        os.unlink(self.pdf_path)

    def test_successful_upload_returns_blob_url_with_expected_path(self):
        captured = {}

        def fake_transport(blob_path, pdf_path, metadata, container_name, connection_string):
            captured["blob_path"] = blob_path
            captured["metadata"] = metadata
            captured["container_name"] = container_name
            return True, f"https://test.blob.core.windows.net/{container_name}/{blob_path}", None

        client = _make_client(transport=fake_transport)
        url = client.upload_pdf(
            self.pdf_path,
            vendor_name="ABC Auto Parts",
            year=2026,
            month=7,
            document_hash="abc123hash",
            original_filename="statement.pdf",
            uploaded_by="jdoe",
        )

        self.assertEqual(captured["blob_path"], "abc_auto_parts/2026/07/abc123hash.pdf")
        self.assertEqual(captured["container_name"], "vendor-statements")
        self.assertEqual(captured["metadata"]["original_filename"], "statement.pdf")
        self.assertEqual(captured["metadata"]["vendor_name"], "ABC Auto Parts")
        self.assertEqual(captured["metadata"]["uploaded_by"], "jdoe")
        self.assertEqual(url, f"https://test.blob.core.windows.net/vendor-statements/abc_auto_parts/2026/07/abc123hash.pdf")

    def test_month_and_year_are_zero_padded(self):
        captured = {}

        def fake_transport(blob_path, pdf_path, metadata, container_name, connection_string):
            captured["blob_path"] = blob_path
            return True, "https://test/blob", None

        client = _make_client(transport=fake_transport)
        client.upload_pdf(self.pdf_path, "Vendor", year=2026, month=3, document_hash="h1")

        self.assertEqual(captured["blob_path"], "vendor/2026/03/h1.pdf")

    def test_transport_failure_returns_none_not_raise(self):
        def fake_transport(blob_path, pdf_path, metadata, container_name, connection_string):
            return False, None, "simulated network error"

        client = _make_client(transport=fake_transport)
        url = client.upload_pdf(self.pdf_path, "Vendor", 2026, 7, "h1")

        self.assertIsNone(url)

    def test_transport_raising_exception_returns_none_not_raise(self):
        def fake_transport(blob_path, pdf_path, metadata, container_name, connection_string):
            raise RuntimeError("boom")

        client = _make_client(transport=fake_transport)
        url = client.upload_pdf(self.pdf_path, "Vendor", 2026, 7, "h1")

        self.assertIsNone(url)

    def test_missing_connection_string_returns_none(self):
        client = BlobStorageClient(
            container_name="vendor-statements",
            connection_string_env_var="AZURE_BLOB_TEST_CONNECTION_STRING_UNSET",
        )
        url = client.upload_pdf(self.pdf_path, "Vendor", 2026, 7, "h1")

        self.assertIsNone(url)

    def test_missing_document_hash_returns_none(self):
        client = _make_client(transport=lambda *a: (True, "https://test/blob", None))
        url = client.upload_pdf(self.pdf_path, "Vendor", 2026, 7, document_hash="")

        self.assertIsNone(url)

    def test_missing_file_returns_none(self):
        client = _make_client(transport=lambda *a: (True, "https://test/blob", None))
        url = client.upload_pdf("does/not/exist.pdf", "Vendor", 2026, 7, "h1")

        self.assertIsNone(url)

    def test_invalid_year_or_month_returns_none(self):
        client = _make_client(transport=lambda *a: (True, "https://test/blob", None))
        url = client.upload_pdf(self.pdf_path, "Vendor", year="not-a-year", month=7, document_hash="h1")

        self.assertIsNone(url)

    def test_no_original_filename_falls_back_to_basename(self):
        captured = {}

        def fake_transport(blob_path, pdf_path, metadata, container_name, connection_string):
            captured["metadata"] = metadata
            return True, "https://test/blob", None

        client = _make_client(transport=fake_transport)
        client.upload_pdf(self.pdf_path, "Vendor", 2026, 7, "h1")

        self.assertEqual(captured["metadata"]["original_filename"], os.path.basename(self.pdf_path))


if __name__ == "__main__":
    unittest.main()
