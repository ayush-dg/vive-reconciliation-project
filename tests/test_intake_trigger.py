"""
tests/test_intake_trigger.py

Tests for the Event Grid auto-intake webhook (web/routers/intake_trigger.py)
using a fake blob client and a fake queries.create_job -- no real Azure or
database calls made, tests run fully offline.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from web.routers import intake_trigger


VALIDATION_EVENT = [{
    "id": "2d1781af-3a4c-4d7c-bd0c-e34b19da4e66",
    "topic": "/subscriptions/id/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/viverecondropzone",
    "subject": "",
    "data": {
        "validationCode": "512d38b6-c7b8-40c8-89fe-f46f9e9622b6",
        "validationUrl": "https://rp-eastus2.eventgrid.azure.net/eventsubscriptions/validate",
    },
    "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
    "eventTime": "2026-07-24T22:12:19.4556811Z",
    "dataVersion": "1",
    "metadataVersion": "1",
}]


def _blob_created_event(filename: str) -> dict:
    return {
        "id": "id-" + filename,
        "topic": "/subscriptions/id/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/viverecondropzone",
        "subject": f"/blobServices/default/containers/incoming-statements/blobs/{filename}",
        "data": {
            "api": "PutBlob",
            "contentType": "application/pdf",
            "contentLength": 12345,
            "blobType": "BlockBlob",
            "url": f"https://viverecondropzone.blob.core.windows.net/incoming-statements/{filename}",
        },
        "eventType": "Microsoft.Storage.BlobCreated",
        "eventTime": "2026-07-24T22:13:00.0000000Z",
        "dataVersion": "",
        "metadataVersion": "1",
    }


class FakeBlobStorageClient:
    """Stand-in for src.storage.blob_client.BlobStorageClient -- records
    every download_pdf call and returns a scripted result per call."""

    calls = []
    should_succeed = True

    def __init__(self, container_name=None, connection_string_env_var=None):
        self.container_name = container_name
        self.connection_string_env_var = connection_string_env_var

    def download_pdf(self, blob_url, dest_path):
        FakeBlobStorageClient.calls.append((blob_url, dest_path))
        if FakeBlobStorageClient.should_succeed:
            with open(dest_path, "wb") as f:
                f.write(b"%PDF-1.4 fake content")
        return FakeBlobStorageClient.should_succeed


class TestIntakeTriggerWebhook(unittest.TestCase):

    def setUp(self):
        FakeBlobStorageClient.calls = []
        FakeBlobStorageClient.should_succeed = True

        self._real_blob_client = intake_trigger.BlobStorageClient
        intake_trigger.BlobStorageClient = FakeBlobStorageClient

        self.created_jobs = []

        def fake_create_job(job_id, pdf_filename, pdf_path, submitted_by, batch_id=None):
            self.created_jobs.append({
                "job_id": job_id,
                "pdf_filename": pdf_filename,
                "pdf_path": pdf_path,
                "submitted_by": submitted_by,
                "batch_id": batch_id,
            })

        self._real_create_job = intake_trigger.queries.create_job
        intake_trigger.queries.create_job = fake_create_job

        self._real_sample_data_dir = intake_trigger.SAMPLE_DATA_DIR
        self.tmp_dir_for_downloads = os.path.join(os.path.dirname(__file__), "_tmp_sample_data")
        intake_trigger.SAMPLE_DATA_DIR = self.tmp_dir_for_downloads

        app = FastAPI()
        app.include_router(intake_trigger.router)
        self.client = TestClient(app)

    def tearDown(self):
        intake_trigger.BlobStorageClient = self._real_blob_client
        intake_trigger.queries.create_job = self._real_create_job
        intake_trigger.SAMPLE_DATA_DIR = self._real_sample_data_dir

        if os.path.isdir(self.tmp_dir_for_downloads):
            for name in os.listdir(self.tmp_dir_for_downloads):
                os.remove(os.path.join(self.tmp_dir_for_downloads, name))
            os.rmdir(self.tmp_dir_for_downloads)

    def test_validation_event_returns_validation_response(self):
        resp = self.client.post("/api/intake-trigger", json=VALIDATION_EVENT)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"validationResponse": "512d38b6-c7b8-40c8-89fe-f46f9e9622b6"})
        self.assertEqual(self.created_jobs, [])

    def test_blob_created_pdf_downloads_and_queues_job(self):
        resp = self.client.post("/api/intake-trigger", json=[_blob_created_event("statement.pdf")])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        self.assertEqual(len(FakeBlobStorageClient.calls), 1)
        self.assertEqual(
            FakeBlobStorageClient.calls[0][0],
            "https://viverecondropzone.blob.core.windows.net/incoming-statements/statement.pdf",
        )
        self.assertEqual(len(self.created_jobs), 1)
        self.assertEqual(self.created_jobs[0]["pdf_filename"], "statement.pdf")
        self.assertEqual(self.created_jobs[0]["submitted_by"], "event-grid")
        self.assertIsNotNone(self.created_jobs[0]["batch_id"])

    def test_non_pdf_blob_is_ignored(self):
        resp = self.client.post("/api/intake-trigger", json=[_blob_created_event("readme.txt")])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(FakeBlobStorageClient.calls, [])
        self.assertEqual(self.created_jobs, [])

    def test_download_failure_does_not_queue_job_but_still_returns_ok(self):
        FakeBlobStorageClient.should_succeed = False

        resp = self.client.post("/api/intake-trigger", json=[_blob_created_event("statement.pdf")])

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        self.assertEqual(self.created_jobs, [])

    def test_multiple_blobs_in_one_batch_share_the_same_batch_id(self):
        events = [_blob_created_event("a.pdf"), _blob_created_event("b.pdf")]

        resp = self.client.post("/api/intake-trigger", json=events)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.created_jobs), 2)
        self.assertEqual(self.created_jobs[0]["batch_id"], self.created_jobs[1]["batch_id"])

    def test_single_event_dict_payload_is_handled_like_a_one_item_batch(self):
        resp = self.client.post("/api/intake-trigger", json=_blob_created_event("solo.pdf"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.created_jobs), 1)
        self.assertEqual(self.created_jobs[0]["pdf_filename"], "solo.pdf")


if __name__ == "__main__":
    unittest.main()
