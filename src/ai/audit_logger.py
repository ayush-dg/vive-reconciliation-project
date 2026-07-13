"""
audit_logger.py

Logs every AI interaction to ai_audit_log.
Called by ExtractionService, ExplanationService, etc.
Never called directly by notebooks or scripts.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from .base_client import AIResponse
from src.lakehouse.connection import execute_sql


def log_ai_call(
    response: AIResponse,
    *,
    interaction_type: str,
    prompt_version: str = "v1",
    source_file: Optional[str] = None,
    vendor_id: Optional[str] = None,
    statement_id: Optional[str] = None,
    validation_result: Optional[str] = None,
    extraction_confidence: Optional[float] = None,
) -> str:
    """
    Write one row to ai_audit_log for an AI call.
    Returns the audit_id for cross-referencing.
    """
    audit_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    response_status = _classify_status(response)

    execute_sql(
        """
        INSERT INTO ai_audit_log (
            audit_id, source_file, vendor_id, statement_id,
            interaction_type, ai_provider, model, prompt_version,
            request_timestamp, latency_ms, attempt_count, success,
            response_status, error_message, extraction_confidence, validation_result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            audit_id,
            source_file,
            vendor_id,
            statement_id,
            interaction_type,
            response.provider,
            response.model,
            prompt_version,
            now,
            response.latency_ms,
            response.attempt_count,
            1 if response.success else 0,
            response_status,
            response.error,
            extraction_confidence,
            validation_result,
        ],
    )
    return audit_id


def _classify_status(response: AIResponse) -> str:
    if response.success:
        return "SUCCESS"
    if not response.error:
        return "UNKNOWN_ERROR"
    msg = response.error.lower()
    if "api key" in msg or "env var" in msg:
        return "MISSING_API_KEY"
    if "timeout" in msg or "transport" in msg or "connection" in msg:
        return "TRANSPORT_ERROR"
    if "json" in msg or "parse" in msg:
        return "PARSE_ERROR"
    if "429" in msg or "quota" in msg or "rate" in msg:
        return "RATE_LIMITED"
    return "UNKNOWN_ERROR"
