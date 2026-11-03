"""
tests/test_connect_exit_close.py

The pipeline's exit-time close of the NetSuite Connect connection
(src/netsuite/connect_source.py _close_shared_client) never blocks the exit
for more than a few seconds: prod 2026-11-03, a Keystone statement finished
its work, then its process hung on closing a dead connection until the
worker's 30-minute limit marked it Failed.
"""

import os
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.netsuite import connect_client, connect_source


class ExitCloseTests(unittest.TestCase):
    def setUp(self):
        saved = connect_client._shared
        self.addCleanup(lambda: setattr(connect_client, "_shared", saved))
        self.release = threading.Event()
        self.addCleanup(self.release.set)

    def test_a_hanging_close_does_not_hold_up_the_exit(self):
        hung = mock.Mock()
        hung.close.side_effect = lambda: self.release.wait(10)   # a dead socket
        connect_client._shared = hung
        started = time.monotonic()
        connect_source._close_shared_client(wait_seconds=0.3)
        self.assertLess(time.monotonic() - started, 2)
        hung.close.assert_called_once()

    def test_a_normal_close_still_happens(self):
        client = mock.Mock()
        connect_client._shared = client
        connect_source._close_shared_client(wait_seconds=2)
        client.close.assert_called_once()

    def test_no_client_is_fine(self):
        connect_client._shared = None
        connect_source._close_shared_client(wait_seconds=0.1)


if __name__ == "__main__":
    unittest.main()
