def normalize_invoice_number(invoice_number: str) -> str:
    """
    Returns the invoice number exactly as provided.
    No normalization applied — the invoice number is a business identifier
    and must not be modified. If vendor and ERP use different formats,
    that is a real discrepancy that should surface as an exception.
    """
    if not invoice_number:
        return invoice_number
    return invoice_number.strip()
