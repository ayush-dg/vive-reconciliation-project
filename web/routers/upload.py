"""
upload.py

Accepts a vendor statement PDF, saves it to sample_data/, and runs the
existing pipeline (scripts/run_full_pipeline.py) as a subprocess — the
same entry point used from the command line. This router never touches
pipeline internals directly, only shells out to it, per the "don't modify
the pipeline" constraint.
"""

import os
import re
import subprocess
import sys
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from web.deps import render, require_login, sidebar_context
from web import queries

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_DATA_DIR = os.path.join(PROJECT_ROOT, "sample_data")
VENV_PYTHON = os.path.join(PROJECT_ROOT, "venv", "Scripts", "python.exe")

STATEMENT_ID_RE = re.compile(r"Statement ID:\s*(\S+)")


@router.get("/upload")
def upload_form(request: Request, user: str = Depends(require_login)):
    ctx = {
        "active_page": "upload",
        "error": None,
        "uploaded_file": None,
        **sidebar_context(),
    }
    return render(request, "upload.html", ctx)


@router.post("/upload")
def upload_submit(request: Request, user: str = Depends(require_login),
                   file: UploadFile = File(...), period: str = Form(None),
                   notes: str = Form(None)):
    if not file.filename.lower().endswith(".pdf"):
        ctx = {
            "active_page": "upload",
            "error": "Only PDF files are accepted.",
            "uploaded_file": None,
            **sidebar_context(),
        }
        return render(request, "upload.html", ctx, status_code=400)

    os.makedirs(SAMPLE_DATA_DIR, exist_ok=True)
    safe_name = os.path.basename(file.filename)
    pdf_path = os.path.join(SAMPLE_DATA_DIR, safe_name)
    contents = file.file.read()
    with open(pdf_path, "wb") as f:
        f.write(contents)

    python_exe = VENV_PYTHON if os.path.exists(VENV_PYTHON) else sys.executable
    relative_pdf_path = os.path.join("sample_data", safe_name)

    result = subprocess.run(
        [python_exe, os.path.join("scripts", "run_full_pipeline.py"), "--pdf", relative_pdf_path],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    match = STATEMENT_ID_RE.search(output)

    if result.returncode != 0 or not match:
        ctx = {
            "active_page": "upload",
            "error": "The reconciliation pipeline failed to process this PDF.",
            "pipeline_output": output.strip()[-4000:],
            "uploaded_file": {"name": safe_name, "size": len(contents)},
            **sidebar_context(),
        }
        return render(request, "upload.html", ctx, status_code=500)

    statement_id = match.group(1)
    vendor_name = queries.get_vendor_name_for_statement(statement_id)

    if not vendor_name:
        ctx = {
            "active_page": "upload",
            "error": f"Pipeline completed ({statement_id}) but the vendor could not be determined.",
            "uploaded_file": {"name": safe_name, "size": len(contents)},
            **sidebar_context(),
        }
        return render(request, "upload.html", ctx, status_code=500)

    return RedirectResponse(f"/exceptions/{quote(vendor_name, safe='')}", status_code=303)
