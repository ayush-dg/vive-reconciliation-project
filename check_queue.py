import os, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv()
from src.lakehouse.connection import execute_sql_fabric, execute_query_fabric

# validation_document_review_queue is cut over to Fabric Warehouse — see
# get_fabric_connection() in src/lakehouse/connection.py.

# Delete stale review queue entries
execute_sql_fabric("DELETE FROM validation_document_review_queue WHERE source_file = 'Very_Dirty_Scanned_Reconciliation.pdf'")
print('stale rows deleted')

# Verify
remaining = execute_query_fabric("SELECT COUNT(*) c FROM validation_document_review_queue")
print('remaining review queue rows:', remaining[0]['c'])