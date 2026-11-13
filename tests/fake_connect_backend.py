"""A stand-in for the NetSuite Connect client, loaded INSIDE the helper process
by tests/test_connect_helper.py (connect_helper's factory_path). It acts on a
marker in the SQL:
  'hang'  -- never returns, ignoring its timeout (a stuck ODBC driver)
  'crash' -- kills the whole process, like the native crash on 2026-11-11
  'slow'  -- takes 1.5 s, then answers
  anything else -- answers at once with the process id
"""

import os
import time


class FakeClient:
    def __init__(self, query_timeout):
        self.query_timeout = query_timeout

    def query(self, sql, params=None, timeout=None):
        if "'hang'" in sql:
            time.sleep(3600)
        if "'crash'" in sql:
            os._exit(139)
        if "'slow'" in sql:
            time.sleep(1.5)
        return [{"pid": os.getpid(), "params": list(params or []), "odbc_timeout": self.query_timeout}]


def make_client(query_timeout):
    return FakeClient(query_timeout)
