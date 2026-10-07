"""
tests/test_mailbox_autosync.py

Tests for the timer-driven half of mailbox sync (web/routers/mailbox_sync.py's
/mailbox-sync/auto route and its new_only eligibility rule) using a fake
blob client and a fake queries.create_job -- no real Azure or database
calls made, tests run fully offline.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routers import mailbox_sync

TEST_SECRET = "test-autosync-secret-abc123"
AUTH_HEADERS = {mailbox_sync.AUTOSYNC_SECRET_HEADER: TEST_SECRET}


class FakeBlobStorageClient:
    """Stand-in for BlobStorageClient -- serves a scripted blob listing and
    records which blobs were claimed."""

    blobs = {}
    claimed = []

    def __init__(self, container_name=None, connection_string_env_var=None):
        pass

    def get_blob_metadata_map(self, prefix=None):
        return {name: {"metadata": dict(md), "etag": "etag-" + name} for name, md in FakeBlobStorageClient.blobs.items()}

    def try_claim_blob_for_processing(self, blob_path, etag, metadata):
        FakeBlobStorageClient.claimed.append(blob_path)
        return True

    def download_blob_by_name(self, blob_name, dest_path):
        with open(dest_path, "wb") as f:
            f.write(b"%PDF-1.4 fake content")
        return True

    def set_blob_extraction_outcome(self, blob_name, status, last_error=None):
        return True


class SynchronousThread:
    """Runs the target on start() so the route's background work finishes
    before the test asserts on it."""

    def __init__(self, target=None, name=None, daemon=None):
        self._target = target

    def start(self):
        self._target()


class _FakeBlobsTestCase(unittest.TestCase):

    def setUp(self):
        FakeBlobStorageClient.blobs = {}
        FakeBlobStorageClient.claimed = []
        self._real_blob_client = mailbox_sync.BlobStorageClient
        mailbox_sync.BlobStorageClient = FakeBlobStorageClient

        self.created_jobs = []
        self._real_create_job = mailbox_sync.queries.create_job
        mailbox_sync.queries.create_job = lambda **kwargs: self.created_jobs.append(kwargs)

        self._real_sample_dir = mailbox_sync.SAMPLE_DATA_DIR
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        mailbox_sync.SAMPLE_DATA_DIR = self._tmp.name

    def tearDown(self):
        mailbox_sync.BlobStorageClient = self._real_blob_client
        mailbox_sync.queries.create_job = self._real_create_job
        mailbox_sync.SAMPLE_DATA_DIR = self._real_sample_dir
        self._tmp.cleanup()


class TestQueueEligibleBlobsNewOnly(_FakeBlobsTestCase):

    def setUp(self):
        super().setUp()
        FakeBlobStorageClient.blobs = {
            "mailbox/2026/10/07/raw_statement/u1__New_20261007T100000Z.pdf": {},
            "mailbox/2026/10/07/raw_statement/u2__Failed_20261007T100000Z.pdf": {"extraction_status": "failed", "attempt_count": "1"},
            "mailbox/2026/10/07/raw_statement/u3__Done_20261007T100000Z.pdf": {"extraction_status": "completed", "attempt_count": "1"},
            "mailbox/2026/10/07/raw_statement/u4__Busy_20261007T100000Z.pdf": {"extraction_status": "processing"},
        }

    def test_new_only_queues_only_never_attempted_blobs(self):
        queued = mailbox_sync._queue_eligible_blobs(submitted_by="mailbox-auto-sync", new_only=True)
        self.assertEqual(queued, ["New.pdf"])
        self.assertEqual(self.created_jobs[0]["submitted_by"], "mailbox-auto-sync")

    def test_default_still_retries_failed_blobs_for_the_button(self):
        queued = mailbox_sync._queue_eligible_blobs(submitted_by="someone")
        self.assertEqual(sorted(queued), ["Failed.pdf", "New.pdf"])

    def test_failed_at_retry_cap_is_never_requeued(self):
        self.assertFalse(mailbox_sync._is_eligible(
            {"extraction_status": "failed", "attempt_count": str(mailbox_sync.RETRY_CAP)}, new_only=False))


class TestAutoSyncRoute(_FakeBlobsTestCase):

    def setUp(self):
        super().setUp()
        FakeBlobStorageClient.blobs = {
            "mailbox/2026/10/07/raw_statement/u1__New_20261007T100000Z.pdf": {},
            "mailbox/2026/10/07/raw_statement/u2__Failed_20261007T100000Z.pdf": {"extraction_status": "failed", "attempt_count": "1"},
        }
        self._real_secret_env = os.environ.get(mailbox_sync.AUTOSYNC_SECRET_ENV_VAR)
        os.environ[mailbox_sync.AUTOSYNC_SECRET_ENV_VAR] = TEST_SECRET

        self._real_thread = mailbox_sync.threading.Thread
        mailbox_sync.threading.Thread = SynchronousThread

        app = FastAPI()
        app.include_router(mailbox_sync.router)
        self.client = TestClient(app)

    def tearDown(self):
        mailbox_sync.threading.Thread = self._real_thread
        if self._real_secret_env is None:
            os.environ.pop(mailbox_sync.AUTOSYNC_SECRET_ENV_VAR, None)
        else:
            os.environ[mailbox_sync.AUTOSYNC_SECRET_ENV_VAR] = self._real_secret_env
        if mailbox_sync._webapp_sync_lock.locked():
            mailbox_sync._webapp_sync_lock.release()
        super().tearDown()

    def test_valid_secret_queues_new_blobs_only_and_releases_lock(self):
        response = self.client.post("/mailbox-sync/auto", headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 202)
        self.assertEqual([j["pdf_filename"] for j in self.created_jobs], ["New.pdf"])
        self.assertEqual(self.created_jobs[0]["submitted_by"], mailbox_sync.AUTOSYNC_SUBMITTED_BY)
        self.assertFalse(mailbox_sync._webapp_sync_lock.locked())

    def test_missing_secret_header_is_rejected(self):
        response = self.client.post("/mailbox-sync/auto")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.created_jobs, [])

    def test_wrong_secret_is_rejected(self):
        response = self.client.post("/mailbox-sync/auto", headers={mailbox_sync.AUTOSYNC_SECRET_HEADER: "nope"})
        self.assertEqual(response.status_code, 401)

    def test_unconfigured_secret_rejects_everything(self):
        os.environ.pop(mailbox_sync.AUTOSYNC_SECRET_ENV_VAR, None)
        response = self.client.post("/mailbox-sync/auto", headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 401)

    def test_skips_with_409_while_sync_to_webapp_is_running(self):
        mailbox_sync._webapp_sync_lock.acquire()
        response = self.client.post("/mailbox-sync/auto", headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.created_jobs, [])

    def test_lock_is_released_even_when_queueing_fails(self):
        def boom(**kwargs):
            raise RuntimeError("db down")
        mailbox_sync.queries.create_job = boom
        response = self.client.post("/mailbox-sync/auto", headers=AUTH_HEADERS)
        self.assertEqual(response.status_code, 202)
        self.assertFalse(mailbox_sync._webapp_sync_lock.locked())


if __name__ == "__main__":
    unittest.main()
