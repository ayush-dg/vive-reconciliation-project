"""Build-time check (Dockerfile): every ODBC driver the app needs can be LOADED.

Listing a driver in odbcinst.ini proves nothing -- a driver whose shared
library or dependencies are missing is still listed. So each driver is asked
to connect to a closed local port: a loadable driver fails with a connection
error, an unloadable one with "Can't open lib" / "file not found". Exits 1 on
the latter. The NetSuite driver is only checked when it was installed (it is
optional in the build context). Makes no network calls beyond localhost.
"""
import os
import sys

import pyodbc

SQL_SERVER = "ODBC Driver 18 for SQL Server"
NETSUITE = "NetSuite ODBC Drivers 9.0"
LOAD_FAILURES = ("can't open lib", "cannot open shared object", "file not found", "data source name not found")


def load_error(conn_str: str):
    """None if the driver loaded (whatever else went wrong), else the error."""
    try:
        pyodbc.connect(conn_str, timeout=3)
    except pyodbc.Error as e:
        text = str(e)
        return text if any(marker in text.lower() for marker in LOAD_FAILURES) else None
    return None


def main() -> int:
    drivers = pyodbc.drivers()
    print("ODBC drivers:", drivers)
    checks = {SQL_SERVER: f"DRIVER={{{SQL_SERVER}}};SERVER=127.0.0.1,1;TrustServerCertificate=yes"}
    if os.path.exists("/opt/netsuite/odbcclient/lib64/ivoa27.so"):
        checks[NETSUITE] = (f"DRIVER={{{NETSUITE}}};Host=127.0.0.1;Port=1;Encrypted=1;"
                            "Truststore=/opt/netsuite/odbcclient/cert/ca4.cer;SDSN=NetSuite2.com;UID=x;PWD=x")
    failed = False
    for name, conn_str in checks.items():
        if name not in drivers:
            print(f"FAIL {name}: not registered"); failed = True; continue
        err = load_error(conn_str)
        print(f"{'FAIL' if err else 'OK  '} {name}" + (f": {err}" if err else ": loads"))
        failed = failed or bool(err)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
