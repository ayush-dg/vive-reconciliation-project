"""
tests/test_mailbox_sync_function.py

Tests for the mailbox-sync Azure Function's lock and timer logic
(azure-functions/mailbox-sync/function_app.py). azure-functions isn't part
of the web app's venv, so a minimal stand-in module is registered before
import -- only the plain-Python logic is exercised; no real Azure, Graph
or HTTP calls are made.
"""

import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

from azure.core.exceptions import HttpResponseError

FUNCTION_APP_PATH = os.path.join(
    os.path.dirname(__file__), "..", "azure-functions", "mailbox-sync", "function_app.py"
)


def _install_azure_functions_stub():
    if "azure.functions" in sys.modules:
        return

    class _FunctionApp:
        def route(self, **kwargs):
            return lambda f: f

        def timer_trigger(self, **kwargs):
            return lambda f: f

    stub = types.ModuleType("azure.functions")
    stub.FunctionApp = _FunctionApp
    stub.AuthLevel = types.SimpleNamespace(FUNCTION="function")
    stub.HttpRequest = object
    stub.HttpResponse = lambda body, mimetype=None, status_code=200: types.SimpleNamespace(
        body=body, status_code=status_code)
    stub.TimerRequest = object
    sys.modules["azure.functions"] = stub


def _load_function_app():
    _install_azure_functions_stub()
    spec = importlib.util.spec_from_file_location("mailbox_sync_function_app", FUNCTION_APP_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


function_app = _load_function_app()


def _lease_conflict():
    error = HttpResponseError(message="LeaseAlreadyPresent")
    error.status_code = 409
    return error


class TestAcquireSyncLock(unittest.TestCase):

    def test_returns_lease_when_free(self):
        container = mock.MagicMock()
        lock_blob = container.get_blob_client.return_value
        lock_blob.exists.return_value = True
        self.assertIs(function_app.acquire_sync_lock(container), lock_blob.acquire_lease.return_value)
        lock_blob.acquire_lease.assert_called_once_with(lease_duration=function_app.LOCK_LEASE_SECONDS)

    def test_returns_none_when_another_run_holds_it(self):
        container = mock.MagicMock()
        lock_blob = container.get_blob_client.return_value
        lock_blob.exists.return_value = True
        lock_blob.acquire_lease.side_effect = _lease_conflict()
        self.assertIsNone(function_app.acquire_sync_lock(container))

    def test_creates_lock_blob_on_first_use(self):
        container = mock.MagicMock()
        lock_blob = container.get_blob_client.return_value
        lock_blob.exists.return_value = False
        function_app.acquire_sync_lock(container)
        lock_blob.upload_blob.assert_called_once_with(b"", overwrite=False)


class TestRunSync(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"AzureWebJobsStorage": "UseDevelopmentStorage=true"})
        patcher.start()
        self.addCleanup(patcher.stop)
        bsc = mock.patch.object(function_app, "BlobServiceClient")
        bsc.start()
        self.addCleanup(bsc.stop)

    def test_skips_pull_when_locked(self):
        with mock.patch.object(function_app, "acquire_sync_lock", return_value=None), \
             mock.patch.object(function_app, "pull_new_pdfs") as pull:
            self.assertIsNone(function_app.run_sync())
        pull.assert_not_called()

    def test_releases_lock_even_when_pull_fails(self):
        lease = mock.MagicMock()
        with mock.patch.object(function_app, "acquire_sync_lock", return_value=lease), \
             mock.patch.object(function_app, "pull_new_pdfs", side_effect=RuntimeError("graph down")):
            with self.assertRaises(RuntimeError):
                function_app.run_sync()
        lease.release.assert_called_once()


class TestScheduledSync(unittest.TestCase):

    def test_disabled_by_default_does_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=False), \
             mock.patch.object(function_app, "run_sync") as run_sync, \
             mock.patch.object(function_app, "notify_webapp") as notify:
            os.environ.pop(function_app.AUTO_SYNC_ENABLED_ENV_VAR, None)
            function_app.scheduled_sync(None)
        run_sync.assert_not_called()
        notify.assert_not_called()

    def test_enabled_pulls_then_notifies_webapp(self):
        result = {"new_blob_paths": ["mailbox/a.pdf"], "messages_processed": 1}
        with mock.patch.dict(os.environ, {function_app.AUTO_SYNC_ENABLED_ENV_VAR: "true"}), \
             mock.patch.object(function_app, "run_sync", return_value=result), \
             mock.patch.object(function_app, "notify_webapp") as notify:
            function_app.scheduled_sync(None)
        notify.assert_called_once()

    def test_notifies_webapp_on_every_tick_even_when_nothing_new_or_locked(self):
        with mock.patch.dict(os.environ, {function_app.AUTO_SYNC_ENABLED_ENV_VAR: "true"}), \
             mock.patch.object(function_app, "run_sync", return_value=None), \
             mock.patch.object(function_app, "notify_webapp") as notify:
            function_app.scheduled_sync(None)
        notify.assert_called_once()

    def test_notifies_webapp_even_when_graph_pull_fails(self):
        with mock.patch.dict(os.environ, {function_app.AUTO_SYNC_ENABLED_ENV_VAR: "true"}), \
             mock.patch.object(function_app, "run_sync", side_effect=RuntimeError("graph down")), \
             mock.patch.object(function_app, "notify_webapp") as notify:
            with self.assertRaises(RuntimeError):
                function_app.scheduled_sync(None)
        notify.assert_called_once()


class TestNotifyWebapp(unittest.TestCase):

    def test_sends_secret_header(self):
        env = {function_app.WEBAPP_AUTOSYNC_URL_ENV_VAR: "https://example.test/mailbox-sync/auto",
               function_app.AUTOSYNC_SECRET_ENV_VAR: "s3cret"}
        with mock.patch.dict(os.environ, env), mock.patch.object(function_app.requests, "post") as post:
            function_app.notify_webapp()
        post.assert_called_once_with(env[function_app.WEBAPP_AUTOSYNC_URL_ENV_VAR],
                                     headers={function_app.AUTOSYNC_SECRET_HEADER: "s3cret"}, timeout=30)

    def test_network_failure_never_raises(self):
        env = {function_app.WEBAPP_AUTOSYNC_URL_ENV_VAR: "https://example.test/mailbox-sync/auto",
               function_app.AUTOSYNC_SECRET_ENV_VAR: "s3cret"}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(function_app.requests, "post",
                               side_effect=function_app.requests.ConnectionError("down")):
            function_app.notify_webapp()

    def test_unconfigured_skips_call(self):
        with mock.patch.dict(os.environ, {}), mock.patch.object(function_app.requests, "post") as post:
            os.environ.pop(function_app.WEBAPP_AUTOSYNC_URL_ENV_VAR, None)
            os.environ.pop(function_app.AUTOSYNC_SECRET_ENV_VAR, None)
            function_app.notify_webapp()
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
