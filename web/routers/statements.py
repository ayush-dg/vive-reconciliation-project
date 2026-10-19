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
# Statement ids look like STMT-60A970B4 (hyphenated tests/fixtures use longer ones).
_STATEMENT_ID = re.compile(r"^STMT-[0-9A-Za-z-]{1,40}$")


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


def _pdf_response(archived, fallback_name: str = None):
    """Streams an archived PDF inline, or 404s if it cannot be fetched."""
    if not archived:
        raise HTTPException(status_code=404, detail="Statement not found")
    content = _fetch_pdf_bytes(archived["blob_storage_path"])
    if content is None:
        raise HTTPException(status_code=404, detail="Statement PDF is not available")
    filename = _inline_filename(archived.get("original_filename") or fallback_name)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/statements/{document_hash}/pdf")
def statement_pdf(document_hash: str, user: str = Depends(require_login)):
    """The original link format, by the file's SHA-256. Kept so links already
    written to NetSuite keep working."""
    if not _SHA256_HEX.match(document_hash):
        raise HTTPException(status_code=404, detail="Statement not found")
    return _pdf_response(queries.get_archived_pdf_for_document_hash(document_hash))


@router.get("/statements/{statement_id}/{filename}")
def statement_pdf_by_id(statement_id: str, filename: str, user: str = Depends(require_login)):
    """The short link: /statements/STMT-60A970B4/BMW.pdf. The statement id
    picks the PDF; the file name is only for readability (and the download
    name), so a wrong or renamed one still opens the right file."""
    if not _STATEMENT_ID.match(statement_id) or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="Statement not found")
    return _pdf_response(queries.get_archived_pdf_for_statement(statement_id), fallback_name=filename)
