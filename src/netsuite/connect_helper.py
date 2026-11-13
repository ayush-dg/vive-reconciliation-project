"""
connect_helper.py

Live NetSuite (SuiteAnalytics Connect) for the web app, in a helper process
(2026-11-13).

Why: the web app used to hold ONE Connect connection behind a lock, inside
its own process. Fifteen people searching at once queued on it (dev, 15
simultaneous Find in NetSuite searches: median 26 s, 6 of 15 past the 25 s
limit), and the NetSuite ODBC driver is native code -- a query abandoned
after a timeout kept running on a background thread, and on 2026-11-11 20:59
UTC prod's web app died with exit code 139 (a native crash), taking the job
queue with it.

Now:
- The web app starts ONE helper process (multiprocessing, spawn) and sends it
  every live NetSuite read. Only the helper loads the NetSuite driver; a hang
  or crash there never takes the web app down.
- The helper runs a pool of NETSUITE_CONNECT_POOL_SIZE (default 4)
  connections, one per worker thread, so searches run side by side. Each
  connection has the driver's own query timeout
  (NETSUITE_CONNECT_QUERY_TIMEOUT_SECONDS, default 60).
- A request that waits more than NETSUITE_CONNECT_QUEUE_WAIT_SECONDS (default
  3) for a free connection is answered "busy" (a QueryTimeout, so the search
  shows the Fabric copy) instead of piling up. The web side keeps one ticket
  per connection, so this takes the queue wait, not as long as the query
  holding the pool.
- If the helper dies, waiting requests fail at once (ConnectionError) and the
  next request starts a new helper. If it stops answering -- pool-size
  requests in a row get no reply at all -- it is killed and restarted.

Pipeline processes (matching, one per job) don't use this: each keeps its own
in-process client (connect_client.use_helper() is only turned on by the web
app).
"""

import importlib
import itertools
import logging
import multiprocessing
import os
import queue
import threading
import time

from src.netsuite.connect_client import QueryTimeout, check_read_only

logger = logging.getLogger(__name__)

DEFAULT_POOL_SIZE = 4
DEFAULT_QUEUE_WAIT_SECONDS = 3.0
DEFAULT_QUERY_TIMEOUT_SECONDS = 60
# A read sent without a time limit (e.g. the vendor list) still gets one here,
# so a dead helper can never block a web request for good.
UNTIMED_LIMIT_SECONDS = 120
# How much longer than its own timeout the web app waits for the helper's reply.
REPLY_GRACE_SECONDS = 3.0


def _env_number(name, default, cast=float):
    try:
        value = cast(os.getenv(name) or default)
    except ValueError:
        return default
    return value if value > 0 else default


def pool_size() -> int:
    return _env_number("NETSUITE_CONNECT_POOL_SIZE", DEFAULT_POOL_SIZE, int)


def queue_wait_seconds() -> float:
    return _env_number("NETSUITE_CONNECT_QUEUE_WAIT_SECONDS", DEFAULT_QUEUE_WAIT_SECONDS)


def query_timeout_seconds() -> int:
    return _env_number("NETSUITE_CONNECT_QUERY_TIMEOUT_SECONDS", DEFAULT_QUERY_TIMEOUT_SECONDS, int)


class HelperBusy(QueryTimeout):
    """Every pooled connection stayed busy longer than the queue wait."""


class HelperUnavailable(ConnectionError):
    """The helper died or was restarted while the request waited."""


# -- the helper process ------------------------------------------------------

def _default_client_factory(query_timeout):
    from src.netsuite.connect_client import ConnectClient
    return ConnectClient(query_timeout=query_timeout)


def _load_factory(path):
    if not path:
        return _default_client_factory
    module, name = path.split(":")
    return getattr(importlib.import_module(module), name)


def _helper_main(requests, replies, size, max_wait, odbc_timeout, factory_path=None):
    """Runs in the helper process: `size` worker threads, each with its own
    client (connection), taking requests off one queue."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [connect-helper] %(message)s")
    factory = _load_factory(factory_path)

    def worker(number):
        client = factory(odbc_timeout)
        while True:
            item = requests.get()
            if item is None:  # shutdown: pass it on to the next worker
                requests.put(None)
                return
            req_id, sql, params, timeout, sent_at = item
            # "Busy" is decided on the web side (ConnectHelper.query()); here a
            # request only has to still be within its own time limit -- the
            # wait includes the helper starting up, which is not "busy".
            remaining = timeout - (time.time() - sent_at)
            if remaining <= 0:
                replies.put((req_id, "timeout", f"waited past its {timeout:g}s limit before a connection was free"))
                continue
            try:
                replies.put((req_id, "ok", client.query(sql, params, timeout=remaining)))
            except QueryTimeout as exc:
                replies.put((req_id, "timeout", str(exc)[:300]))
            except Exception as exc:  # noqa: BLE001 -- reported to the waiting request
                replies.put((req_id, "error", f"{type(exc).__name__}: {str(exc)[:300]}"))

    threads = [threading.Thread(target=worker, args=(n,), daemon=True, name=f"connect-{n}") for n in range(size)]
    for t in threads:
        t.start()
    logging.getLogger(__name__).info("NetSuite Connect helper ready: %d connections", size)
    for t in threads:
        t.join()


# -- the web app's side ------------------------------------------------------

class ConnectHelper:
    """What the web app calls: query() like ConnectClient.query(), answered
    by the helper process's pool."""

    def __init__(self, size=None, max_wait=None, odbc_timeout=None, factory_path=None):
        self.size = size or pool_size()
        self.max_wait = max_wait or queue_wait_seconds()
        self.odbc_timeout = odbc_timeout or query_timeout_seconds()
        self.factory_path = factory_path
        self._ctx = multiprocessing.get_context("spawn")
        self._lock = threading.Lock()
        self._ids = itertools.count(1)
        self._pending = {}  # req_id -> [event, reply, generation]
        self._process = None
        self._requests = None
        self._generation = 0
        self._slots = None  # one ticket per pooled connection (see query())
        self._silent_in_a_row = 0
        self.restarts = 0

    # process lifecycle
    def _start_locked(self):
        self._generation += 1
        generation = self._generation
        self._slots = threading.BoundedSemaphore(self.size)
        self._requests, replies = self._ctx.Queue(), self._ctx.Queue()
        self._process = self._ctx.Process(
            target=_helper_main, name="netsuite-connect-helper", daemon=True,
            args=(self._requests, replies, self.size, self.max_wait, self.odbc_timeout, self.factory_path))
        self._process.start()
        threading.Thread(target=self._dispatch, args=(replies, self._process, generation),
                         daemon=True, name=f"connect-helper-replies-{generation}").start()
        logger.info("NetSuite Connect helper started (pid %s, %d connections)", self._process.pid, self.size)

    def _ensure_running(self):
        with self._lock:
            if self._process is None or not self._process.is_alive():
                if self._process is not None:
                    logger.warning("NetSuite Connect helper had exited (code %s) -- starting a new one",
                                   self._process.exitcode)
                    self.restarts += 1
                self._start_locked()
            return self._generation, self._slots

    def _dispatch(self, replies, process, generation):
        """Hands replies to the waiting requests; when the helper dies, fails
        every request still waiting on it at once."""
        while True:
            try:
                req_id, status, payload = replies.get(timeout=1.0)
            except queue.Empty:
                if not process.is_alive() or generation != self._generation:
                    self._fail_generation(generation, f"NetSuite helper stopped (exit code {process.exitcode})")
                    return
                continue
            except (EOFError, OSError):
                self._fail_generation(generation, "NetSuite helper connection closed")
                return
            with self._lock:
                slot = self._pending.get(req_id)
            if slot is not None:
                slot[1] = (status, payload)
                slot[0].set()

    def _fail_generation(self, generation, message):
        with self._lock:
            slots = [slot for slot in self._pending.values() if slot[2] == generation]
        for slot in slots:
            if slot[1] is None:
                slot[1] = ("dead", message)
                slot[0].set()

    def restart(self, reason: str):
        with self._lock:
            process = self._process
            self._process = None
            self.restarts += 1
            self._generation += 1  # the old dispatcher fails its waiters and stops
        logger.warning("NetSuite Connect helper restarted: %s", reason)
        if process is not None:
            process.terminate()
            process.join(3)
            if process.is_alive():
                process.kill()

    def stop(self):
        with self._lock:
            process, self._process = self._process, None
            self._generation += 1
        if process is not None:
            process.terminate()
            process.join(3)

    # the call everyone uses
    def query(self, sql: str, params=None, timeout: float = None) -> list:
        check_read_only(sql)
        limit = timeout if timeout and timeout > 0 else UNTIMED_LIMIT_SECONDS
        generation, slots = self._ensure_running()
        # "Busy" is decided here, on the web side: a ticket per pooled
        # connection, given back when the helper answers. If none frees up
        # within the queue wait, answer at once (the search shows the Fabric
        # copy) -- not after whatever query is holding the pool finishes.
        if not slots.acquire(timeout=self.max_wait):
            raise HelperBusy(f"all {self.size} NetSuite connections were busy for {self.max_wait:g}s")
        answered = False
        req_id = next(self._ids)
        slot = [threading.Event(), None, generation]
        with self._lock:
            self._pending[req_id] = slot
            requests = self._requests
        try:
            requests.put((req_id, sql, list(params or []), limit, time.time()))
            answered = slot[0].wait(limit + REPLY_GRACE_SECONDS)
            if not answered:
                # No answer: its connection is probably stuck, so its ticket
                # stays taken until the helper is replaced.
                self._no_reply()
                raise QueryTimeout(f"NetSuite helper gave no answer within {limit:g}s")
        finally:
            with self._lock:
                self._pending.pop(req_id, None)
            if answered:
                slots.release()
        self._silent_in_a_row = 0
        status, payload = slot[1]
        if status == "ok":
            return payload
        if status == "busy":
            raise HelperBusy(payload)
        if status == "timeout":
            raise QueryTimeout(payload)
        if status == "dead":
            raise HelperUnavailable(payload)
        raise ConnectionError(payload)

    def _no_reply(self):
        """No reply at all (not even a timeout from the helper's own clock):
        after pool-size such requests in a row, the helper is stuck."""
        self._silent_in_a_row += 1
        if self._silent_in_a_row >= self.size:
            self._silent_in_a_row = 0
            self.restart(f"{self.size} requests in a row got no answer")

    # ConnectClient compatibility (callers sometimes close/retire the shared client)
    def close(self):
        pass

    def retire(self):
        pass


_helper = None
_helper_lock = threading.Lock()


def get_helper() -> ConnectHelper:
    global _helper
    with _helper_lock:
        if _helper is None:
            _helper = ConnectHelper()
        return _helper


def stop_helper() -> None:
    """At web app shutdown."""
    global _helper
    with _helper_lock:
        helper, _helper = _helper, None
    if helper is not None:
        helper.stop()
