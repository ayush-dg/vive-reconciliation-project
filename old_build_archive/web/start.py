"""
start.py

Launches the VIVE Reconciliation web app: uvicorn web.app:app --reload
--port 8000, run from the project root so the `web` package resolves.

Usage (from anywhere): python web/start.py
"""

import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    subprocess.run(
        [sys.executable, "-m", "uvicorn", "web.app:app", "--reload", "--port", "8000"],
        cwd=PROJECT_ROOT,
    )
