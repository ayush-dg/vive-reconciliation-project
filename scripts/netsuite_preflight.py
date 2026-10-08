"""Read-only preflight for the NetSuite write-back. Makes NO writes.

1. Resolves the sandbox account and prints the derived domain/realm.
2. Proves the TBA credentials work with a harmless SuiteQL read.
3. Confirms every custom field / record the write-back depends on still
   exists (a sandbox refresh wipes anything not deployed via SDF/bundle).

Exit code 0 only if everything is present.
Run:  python scripts/netsuite_preflight.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from src.netsuite.client import NetSuiteAPIError, NetSuiteClient, NetSuiteConfigError
from src.netsuite.fields import (
    BODY_FIELDS,
    BODY_RECORD_TYPES,
    STATEMENT_LINE_FIELDS,
    STATEMENT_LINE_RECORD,
)

_NEAR_MISS_WORDS = ("statement", "reconcil", "link", "sl_")


def _check_fields(client, record_type, expected) -> list:
    """Returns the expected fields missing from record_type, printing
    near-miss candidates so a typo'd field id is easy to spot."""
    try:
        present = set(client.get_record_schema(record_type).get("properties", {}))
    except NetSuiteAPIError as exc:
        print(f"  {record_type}: could not read schema ({exc}); body: {exc.body}")
        return list(expected)
    missing = [f for f in expected if f not in present]
    for field in expected:
        print(f"  {record_type}.{field}: {'MISSING' if field in missing else 'OK'}")
    if missing:
        prefix = "custrecord" if record_type.startswith("customrecord") else "custbody"
        near = sorted(
            p for p in present
            if p.startswith(prefix) and any(word in p for word in _NEAR_MISS_WORDS)
        )
        if near:
            print(f"  {record_type}: similar custom fields that DO exist: {near}")
    return missing


def main() -> int:
    try:
        client = NetSuiteClient()
    except NetSuiteConfigError as exc:
        print(f"REFUSING TO RUN: {exc}")
        return 2

    print(f"Account domain : {client.domain_id}")
    print(f"OAuth1 realm   : {client.realm}")
    print(f"Base URL       : {client.base_url}")

    try:
        rows = client.suiteql("SELECT id FROM vendor FETCH FIRST 1 ROWS ONLY")
    except NetSuiteAPIError as exc:
        print(f"Auth/read check FAILED: {exc}\n{exc.body}")
        return 1
    print(f"Auth/read check: OK ({len(rows)} row returned)")

    missing_by_type = {
        record_type: _check_fields(client, record_type, BODY_FIELDS)
        for record_type in BODY_RECORD_TYPES
    }
    missing_by_type[STATEMENT_LINE_RECORD] = _check_fields(
        client, STATEMENT_LINE_RECORD, STATEMENT_LINE_FIELDS)

    problems = {k: v for k, v in missing_by_type.items() if v}
    if problems:
        print("\nPREFLIGHT FAILED -- missing:")
        for record_type, fields in problems.items():
            print(f"  {record_type}: {', '.join(fields)}")
        return 1
    print("\nPREFLIGHT PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
