"""Where matching reads NetSuite from: the nightly Fabric copy or live
SuiteAnalytics Connect.

NETSUITE_SOURCE (environment):
  fabric   (default) -- bronze.netsuite_vendorbill / vendorcredit / vendor,
                        the Lakehouse copy refreshed nightly
  connect            -- live PRODUCTION NetSuite through
                        src/netsuite/connect_client.py (read-only)

The functions here return rows in exactly the shape the Fabric queries in
src/matching/fabric_matching.py and netsuite_vendor_resolver.py return, so
the matching rules don't change at all -- only where the rows come from.
Callers fall back to Fabric when a Connect read fails (see _note_fallback()),
so a NetSuite outage never fails a job.

Why live: measured 2026-10-23 on 16 dev statements, the copy missed bills
entered after the nightly refresh (+27 matches with live data), and it keeps
old versions of changed records as duplicate rows.
"""
import atexit
import logging
import os

logger = logging.getLogger(__name__)

SOURCE_FABRIC = "fabric"
SOURCE_CONNECT = "connect"

_used = set()   # sources actually used since the last reset_used()


def netsuite_source() -> str:
    """The configured source; anything unrecognised means fabric."""
    value = (os.getenv("NETSUITE_SOURCE") or SOURCE_FABRIC).strip().lower()
    if value not in (SOURCE_FABRIC, SOURCE_CONNECT):
        logger.warning("NETSUITE_SOURCE=%r is not 'fabric' or 'connect' -- using fabric", value)
        return SOURCE_FABRIC
    return value


def use_connect() -> bool:
    return netsuite_source() == SOURCE_CONNECT


def reset_used() -> None:
    _used.clear()


def note_used(source: str) -> None:
    _used.add(source)


def used_summary() -> str:
    """'connect', 'fabric', 'fabric (connect failed)' or a mix -- for the job log."""
    return " + ".join(sorted(_used)) or netsuite_source()


def _client():
    from src.netsuite.connect_client import get_shared_client
    return get_shared_client()


def _close_shared_client():
    try:
        from src.netsuite import connect_client
        if connect_client._shared is not None:
            connect_client._shared.close()
    except Exception:
        pass


atexit.register(_close_shared_client)


def _text(value):
    """Ids as text, like the Fabric copy holds them (Connect returns numbers)."""
    return None if value is None else str(value)


def _entity_list(entity_ids) -> str:
    """Inlined in the SQL, so digits only -- anything else is dropped."""
    ids = [str(e).strip() for e in entity_ids or [] if str(e).strip().isdigit()]
    return ",".join(ids)


_TYPE_BY_TABLE = {"netsuite_vendorbill": "VendBill", "netsuite_vendorcredit": "VendCred"}


def candidate_rows(entity_ids, table: str) -> list:
    """[(tranid, total, id, transactionnumber, entity, location), ...] -- the
    same columns, in the same order, as fabric_matching's Fabric query: every
    non-voided bill (or credit) of these vendors. total is positive (NetSuite
    stores bills negative)."""
    entities = _entity_list(entity_ids)
    if not entities:
        return []
    rows = _client().query(
        "SELECT t.tranid, ABS(t.foreigntotal) AS total, t.id, t.transactionnumber, t.entity, tl.location "
        "FROM transaction t LEFT JOIN transactionline tl ON tl.transaction = t.id AND tl.mainline = 'T' "
        f"WHERE t.type = '{_TYPE_BY_TABLE[table]}' AND t.voided = 'F' AND t.tranid IS NOT NULL "
        f"AND t.entity IN ({entities})"
    )
    return [(r["tranid"], r["total"], _text(r["id"]), r.get("transactionnumber"), _text(r["entity"]), _text(r.get("location")))
            for r in rows]


def credit_rows(entity_ids) -> list:
    """[(tranid, total), ...] -- every non-voided vendor credit of these vendors."""
    entities = _entity_list(entity_ids)
    if not entities:
        return []
    rows = _client().query(
        "SELECT t.tranid, ABS(t.foreigntotal) AS total FROM transaction t "
        f"WHERE t.type = 'VendCred' AND t.voided = 'F' AND t.tranid IS NOT NULL AND t.entity IN ({entities})"
    )
    return [(r["tranid"], r["total"]) for r in rows]


def active_vendor_rows() -> list:
    """[(id, companyname, entityid, altname), ...] for every active vendor."""
    rows = _client().query("SELECT id, companyname, entityid, altname FROM vendor WHERE isinactive = 'F'")
    return [(_text(r["id"]), r.get("companyname"), r.get("entityid"), r.get("altname")) for r in rows]


def active_vendor_ids_like(pattern: str) -> list:
    """Ids of active vendors whose companyname/entityid/altname contains
    `pattern` (already lowercased, with % wildcards), case-insensitive."""
    lit = "'" + str(pattern).replace("'", "''") + "'"
    rows = _client().query(
        "SELECT id FROM vendor WHERE isinactive = 'F' AND "
        f"(LOWER(companyname) LIKE {lit} OR LOWER(entityid) LIKE {lit} OR LOWER(altname) LIKE {lit})"
    )
    return [_text(r["id"]) for r in rows]


def note_fallback(what: str) -> None:
    """A Connect read failed and the caller used Fabric instead."""
    note_used("fabric (connect failed)")
    logger.warning("NetSuite Connect read failed for %s -- used the Fabric copy instead", what, exc_info=True)
