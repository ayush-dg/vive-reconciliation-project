"""
netsuite_connect.py

GET /admin/netsuite-connect-check -- proves SuiteAnalytics Connect works from
wherever the app runs (the deployed container has no shell to test from):
lists the registered ODBC drivers, opens a NEW Connect connection (so the
login time is real), runs one read-only count, closes it, and returns the
timings as JSON. Behind the normal login; reads only; no NetSuite record data
is returned, just a count.
"""

import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.netsuite.connect_client import ConnectClient, ConnectConfigError, installed_drivers, load_config
from web.deps import require_login

router = APIRouter()


@router.get("/admin/netsuite-connect-check")
def netsuite_connect_check(user: str = Depends(require_login)):
    drivers = installed_drivers()
    result = {"drivers": drivers}
    try:
        config = load_config()
    except ConnectConfigError as e:
        return JSONResponse({**result, "ok": False, "error": f"not configured: {e}"}, status_code=200)
    result.update(driver=config["driver"], driver_installed=config["driver"] in drivers, host=config["host"])
    client = ConnectClient(config)
    try:
        started = time.monotonic()
        rows = client.query("SELECT COUNT(*) AS n FROM vendor")
        total = time.monotonic() - started
        result.update(ok=True, vendors=int(rows[0]["n"]), login_seconds=client.last_login_seconds,
                      query_seconds=round(total - (client.last_login_seconds or 0), 2))
    except Exception as e:
        result.update(ok=False, error=f"{type(e).__name__}: {str(e)[:400]}")
    finally:
        client.close()
    return JSONResponse(result)
