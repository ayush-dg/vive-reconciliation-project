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

A statement with no archived copy (prod kept none before 2026-10-20) is
served from the mailbox raw blob it arrived as, when it came by mail.

PDF editing (PDF_EDIT_ENABLED=true, 2026-11-02): View PDF shows the
statement's SharePoint file first -- the copy people annotate -- and falls
back to the Azure copy above when there is none or SharePoint can't be
read; ?original=1 always gives the untouched Azure copy. ?edit=1 opens the
PDF.js editor (web/static/pdfjs/), whose Save posts the edited file to
POST /statements/<statement id>/pdf: it replaces the SharePoint file in place
(same item and link, so NetSuite's link opens the edited version), only if
nobody saved since it was opened, and records who saved it in
statement_pdf_edits. With the flag off nothing here changes.
"""

import hashlib
import os
import re
import tempfile
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from src.storage.blob_client import BlobStorageClient
from src.storage.sharepoint_client import SharePointArchiveClient, read_settings
from web import queries
from web.routers.mailbox_sync import MAILBOX_CONNECTION_STRING_ENV_VAR, MAILBOX_CONTAINER
from web.deps import require_login

router = APIRouter()

_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
# Statement ids look like STMT-60A970B4 (hyphenated tests/fixtures use longer ones).
_STATEMENT_ID = re.compile(r"^STMT-[0-9A-Za-z-]{1,40}$")

EDIT_FLAG = "PDF_EDIT_ENABLED"
MAX_EDIT_BYTES = 50 * 1024 * 1024
VIEWER_PATH = "/static/pdfjs/web/viewer.html"


def pdf_editing_enabled() -> bool:
    return os.getenv(EDIT_FLAG, "").strip().lower() == "true"


def _sharepoint_client():
    """A client for the archive library, or None when its settings are incomplete."""
    settings, _ = read_settings()
    return SharePointArchiveClient(settings) if settings else None


def _sharepoint_for(lookup, key):
    """The statement's SharePoint file record when editing is on, else None."""
    if not pdf_editing_enabled():
        return None
    try:
        return lookup(key)
    except Exception:
        return None


def _sharepoint_bytes(sharepoint):
    """The SharePoint file's current bytes, or None (no settings, gone, down)."""
    client = _sharepoint_client()
    if client is None:
        return None
    found = client.get_file(sharepoint["sharepoint_drive_id"], sharepoint["sharepoint_item_id"], with_content=True)
    return found.content if found else None


def _fetch_pdf_bytes(blob_url: str = None, mailbox_blob_path: str = None):
    """Downloads the archived blob (by URL), or else the mailbox raw blob (by
    name), to a temp file and returns its bytes -- None if that failed."""
    fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        if blob_url:
            ok = BlobStorageClient().download_pdf(blob_url, temp_path)
        else:
            ok = BlobStorageClient(
                container_name=MAILBOX_CONTAINER, connection_string_env_var=MAILBOX_CONNECTION_STRING_ENV_VAR,
            ).download_blob_by_name(mailbox_blob_path, temp_path)
        if not ok:
            return None
        with open(temp_path, "rb") as f:
            return f.read()
    finally:
        os.remove(temp_path)


def _inline_filename(original_filename) -> str:
    """A header-safe download name (no quotes or control characters)."""
    name = re.sub(r'[^A-Za-z0-9._ -]', "_", original_filename or "statement.pdf")
    return name if name.lower().endswith(".pdf") else f"{name}.pdf"


def _pdf_response(archived, fallback_name: str = None, sharepoint=None):
    """Streams the PDF inline: the SharePoint file when there is one and it
    can be read (it carries any edits), else the archived (or mailbox) copy;
    404s if neither can be fetched."""
    content = _sharepoint_bytes(sharepoint) if sharepoint else None
    headers = {}
    if content is not None:
        headers["Cache-Control"] = "no-store"   # an edit must show on the next open
    else:
        if not archived:
            raise HTTPException(status_code=404, detail="Statement not found")
        content = _fetch_pdf_bytes(archived.get("blob_storage_path"), archived.get("mailbox_blob_path"))
        if content is None:
            raise HTTPException(status_code=404, detail="Statement PDF is not available")
    name = (archived or {}).get("original_filename") or (sharepoint or {}).get("original_filename")
    headers["Content-Disposition"] = f'inline; filename="{_inline_filename(name or fallback_name)}"'
    return Response(content=content, media_type="application/pdf", headers=headers)


def _editor_redirect(statement_id: str, filename: str):
    """Opens the PDF.js editor on the statement's SharePoint file, at its
    current eTag (what Save is checked against). Without a SharePoint file --
    or if it can't be read -- the plain PDF opens instead, read-only."""
    plain = f"/statements/{statement_id}/{quote(filename)}"
    sharepoint = _sharepoint_for(queries.get_sharepoint_pdf_for_statement, statement_id)
    client = _sharepoint_client() if sharepoint else None
    found = client.get_file(sharepoint["sharepoint_drive_id"], sharepoint["sharepoint_item_id"]) if client else None
    if not found:
        return RedirectResponse(plain, status_code=303)
    source = f"{plain}?v={quote(found.etag, safe='')}"   # a new eTag is a new URL: no stale cache
    return RedirectResponse(
        f"{VIEWER_PATH}?file={quote(source, safe='')}&vive_sid={quote(statement_id)}"
        f"&vive_etag={quote(found.etag, safe='')}", status_code=303)


@router.get("/statements/{document_hash}/pdf")
def statement_pdf(document_hash: str, original: bool = False, user: str = Depends(require_login)):
    """The original link format, by the file's SHA-256. Kept so links already
    written to NetSuite keep working."""
    if not _SHA256_HEX.match(document_hash):
        raise HTTPException(status_code=404, detail="Statement not found")
    sharepoint = None if original else _sharepoint_for(queries.get_sharepoint_pdf_for_document_hash, document_hash)
    return _pdf_response(queries.get_statement_pdf_for_document_hash(document_hash), sharepoint=sharepoint)


@router.get("/statements/{statement_id}/{filename}")
def statement_pdf_by_id(statement_id: str, filename: str, original: bool = False, edit: bool = False,
                        user: str = Depends(require_login)):
    """The short link: /statements/STMT-60A970B4/BMW.pdf. The statement id
    picks the PDF; the file name is only for readability (and the download
    name), so a wrong or renamed one still opens the right file.
    ?original=1 skips the SharePoint copy; ?edit=1 opens the editor."""
    if not _STATEMENT_ID.match(statement_id) or not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=404, detail="Statement not found")
    if edit and pdf_editing_enabled():
        return _editor_redirect(statement_id, filename)
    sharepoint = None if original else _sharepoint_for(queries.get_sharepoint_pdf_for_statement, statement_id)
    return _pdf_response(queries.get_statement_pdf(statement_id), fallback_name=filename, sharepoint=sharepoint)


def _page_count(data: bytes):
    """Pages in a PDF, or None when it does not open as one."""
    try:
        import pymupdf
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception:
        return None


def _save_error(status: int, message: str):
    return JSONResponse({"saved": False, "error": message}, status_code=status)


def _save_edited_pdf(statement_id: str, data: bytes, if_match: str, user: str):
    """The blocking part of a save (Graph calls, PDF parsing), off the event loop."""
    sharepoint = _sharepoint_for(queries.get_sharepoint_pdf_for_statement, statement_id)
    if not sharepoint:
        return _save_error(404, "This statement has no SharePoint copy to save to.")
    client = _sharepoint_client()
    if client is None:
        return _save_error(503, "SharePoint is not configured.")
    drive_id, item_id = sharepoint["sharepoint_drive_id"], sharepoint["sharepoint_item_id"]
    current = client.get_file(drive_id, item_id, with_content=True)
    if current is None:
        return _save_error(502, "SharePoint could not be reached. Nothing was saved; try again.")
    if current.etag != if_match:
        return _save_error(409, "Someone else saved this PDF after you opened it. Nothing was saved -- "
                                "reload to see their changes, then make yours again.")
    edited_pages = _page_count(data)
    if edited_pages is None:
        return _save_error(400, "The edited file is not a readable PDF. Nothing was saved.")
    if edited_pages != _page_count(current.content):
        return _save_error(400, "The edited PDF has a different number of pages from the statement. Nothing was saved.")
    result = client.replace_file(drive_id, item_id, data, if_match)
    if result.status == "conflict":
        return _save_error(409, "Someone else saved this PDF after you opened it. Nothing was saved -- "
                                "reload to see their changes, then make yours again.")
    if result.status != "saved":
        return _save_error(502, f"SharePoint did not accept the save ({result.error}). Nothing was saved.")
    try:
        queries.record_pdf_edit(statement_id, user, drive_id, item_id, current.etag, result.etag,
                                current.size, result.size or len(data), hashlib.sha256(data).hexdigest())
    except Exception:
        pass  # the save itself succeeded; a missing log row must not report it as failed
    return JSONResponse({"saved": True, "etag": result.etag})


@router.post("/statements/{statement_id}/pdf")
async def save_statement_pdf(statement_id: str, request: Request, user: str = Depends(require_login)):
    """Save from the PDF editor: the request body is the edited PDF, If-Match
    the eTag the editor opened. Replaces the statement's SharePoint file only
    if it is still that version, has the same number of pages and is a real
    PDF; answers JSON {"saved": true, "etag"} or {"saved": false, "error"}."""
    if not pdf_editing_enabled() or not _STATEMENT_ID.match(statement_id):
        raise HTTPException(status_code=404, detail="Statement not found")
    data = await request.body()
    if not data:
        return _save_error(400, "Nothing to save.")
    if len(data) > MAX_EDIT_BYTES:
        return _save_error(413, f"The edited PDF is larger than {MAX_EDIT_BYTES // (1024 * 1024)} MB. Nothing was saved.")
    if not data.startswith(b"%PDF-"):
        return _save_error(400, "The edited file is not a PDF. Nothing was saved.")
    if_match = request.headers.get("if-match", "")
    if not if_match:
        return _save_error(428, "The editor did not say which version it opened. Reload and try again.")
    return await run_in_threadpool(_save_edited_pdf, statement_id, data, if_match, user)
