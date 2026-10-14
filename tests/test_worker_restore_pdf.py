"""
tests/test_worker_restore_pdf.py

web/worker._restore_missing_pdf() re-downloads a queued mailbox job's PDF from
its source blob when the local copy is gone (added 2026-10-13, after an App
Service restart wiped prod's queued PDFs: "PDF not found"). The blob client
is mocked; nothing touches Azure.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from web import worker


class TestRestoreMissingPdf(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "abc123", "KSI (Noakers).pdf")

    def _job(self, **over):
        job = {"job_id": "J1", "pdf_path": self.path, "pdf_filename": "KSI (Noakers).pdf",
               "source_blob_path": "mailbox/2026/10/13/raw_statement/x__KSI (Noakers).pdf"}
        job.update(over)
        return job

    def test_missing_file_is_downloaded_from_its_blob(self):
        client = mock.Mock()
        client.download_blob_by_name.return_value = True
        with mock.patch("src.storage.blob_client.BlobStorageClient", return_value=client) as cls:
            worker._restore_missing_pdf(self._job())
        cls.assert_called_once_with(container_name="raw", connection_string_env_var="AZURE_BLOB_MAILBOX_CONNECTION_STRING")
        client.download_blob_by_name.assert_called_once_with(self._job()["source_blob_path"], self.path)
        self.assertTrue(os.path.isdir(os.path.dirname(self.path)))

    def test_existing_file_is_left_alone(self):
        os.makedirs(os.path.dirname(self.path))
        open(self.path, "wb").close()
        with mock.patch("src.storage.blob_client.BlobStorageClient") as cls:
            worker._restore_missing_pdf(self._job())
        cls.assert_not_called()

    def test_manual_upload_without_blob_is_left_alone(self):
        with mock.patch("src.storage.blob_client.BlobStorageClient") as cls:
            worker._restore_missing_pdf(self._job(source_blob_path=None))
        cls.assert_not_called()

    def test_download_errors_never_raise(self):
        with mock.patch("src.storage.blob_client.BlobStorageClient", side_effect=RuntimeError("no storage")):
            worker._restore_missing_pdf(self._job())


if __name__ == "__main__":
    unittest.main()
