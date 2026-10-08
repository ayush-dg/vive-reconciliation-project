"""
pipeline_markers.py

Plain-text markers notebooks/01_document_intake.py prints and
web/worker.py looks for in scripts/run_full_pipeline.py's captured output
(the same way the worker already parses "Statement ID:" and
"Document Hash:"), so a job's final status message can say what actually
happened instead of a generic "produced 0 rows".
"""

# The PDF is byte-identical to one already extracted; nothing new was
# written. Followed by the existing statement_id.
DUPLICATE_MARKER = "DUPLICATE_OF:"

# The extraction model found no line-item table at all (e.g. a printed
# email thread) -- the document isn't a vendor statement.
NOT_A_STATEMENT_MARKER = "NOT_A_STATEMENT:"

# The Silver build left this statement with no usable lines (none of its
# extracted fields matched the vendor's field mapping, or most lines lack an
# invoice number / amount) -- see src/lakehouse/silver_check.py. Followed by
# the problem description; the job fails instead of showing 0 / 0 / 0.
SILVER_CHECK_MARKER = "SILVER_CHECK_FAILED:"
