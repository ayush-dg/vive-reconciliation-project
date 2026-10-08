"""
statements.py

GET /statements/{document_hash}/pdf -- serves the archived statement PDF
inline, behind the normal login. This is the target of the link the
NetSuite write-back (src/netsuite/writeback.py) puts on every bill and
Statement Line, so AP can open the source statement straight from NetSuite.

The hash is the file's SHA-256, the same document_hash intake already
computes and archives the PDF under (see
notebooks/01_document_intake.py): it is stable across re-runs and cannot be
guessed or enumerated. The blob itself stays private -- the app downloads
it server-side and streams the bytes, so no blob URL or key reaches the
browser.
"""

import os
import re
import tempfile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from src.storage.blob_client import BlobStorageClient
from web import queries
from web.deps import require_login

router = APIRouter()

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _fetch_pdf_bytes(blob_url: str):
    """Downloads the archived blob to a temp file and returns its bytes, or
    None if the download failed."""
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        if not BlobStorageClient().download_pdf(blob_url, temp_path):
            return None
        with open(temp_path, "rb") as f:
            return f.read()
    finally:
        os.remove(temp_path)


def _inline_filename(original_filename) -> str:
    """A header-safe download name (no quotes or control characters)."""
    name = re.sub(r'[^A-Za-z0-9._ -]', "_", original_filename or "statement.pdf")
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


@router.get("/statements/{document_hash}/pdf")
def statement_pdf(document_hash: str, user: str = Depends(require_login)):
    if not _SHA256_HEX.match(document_hash):
        raise HTTPException(status_code=404, detail="Statement not found")
    archived = queries.get_archived_pdf_for_document_hash(document_hash)
    if not archived:
        raise HTTPException(status_code=404, detail="Statement not found")
    content = _fetch_pdf_bytes(archived["blob_storage_path"])
    if content is None:
        raise HTTPException(status_code=404, detail="Statement PDF is not available")
    filename = _inline_filename(archived.get("original_filename"))
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
