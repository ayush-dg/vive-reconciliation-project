"""Standalone smoke test — proves get_fabric_connection() can reach the
Fabric Warehouse. Not part of the main test suite. Read-only queries
only; does not touch Azure SQL or any existing logic."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.lakehouse.connection import get_fabric_connection

print("Connecting to Fabric Warehouse via get_fabric_connection() (Azure CLI token auth — reuses the existing az login session, no popup expected)...")
conn = get_fabric_connection()
print("Connected.")

cursor = conn.cursor()

cursor.execute("SELECT 1")
print("SELECT 1 ->", cursor.fetchone())

cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES")
tables = [row[0] for row in cursor.fetchall()]
print(f"INFORMATION_SCHEMA.TABLES -> {len(tables)} table(s):", tables)

conn.close()
print("Connection closed. Fabric Warehouse connection test succeeded.")
