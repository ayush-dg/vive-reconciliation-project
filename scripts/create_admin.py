"""
create_admin.py

One-off script to insert the first admin user into the deployed Azure SQL
Database's `users` table (schema: migrations/004_add_users_table.sql /
src/lakehouse/azure_sql_migrations.py), using the same bcrypt hashing and
query helpers web/routers/auth.py and web/queries.py use -- so the row this
writes is verified by _authenticate() exactly like any user created through
the app itself.

Deliberately does NOT load .env -- this repo's .env still points
AZURE_SQL_SERVER at an older database from a previous deployment, and
silently writing this user into the wrong server would be worse than
failing loudly. Pass the four AZURE_SQL_* values for the target deployment
explicitly as environment variables instead (see Usage).

Usage (from the repo root, so `src` and `web` are importable):
    pip install pyodbc bcrypt

    AZURE_SQL_SERVER=<terraform output -raw sql_server_fqdn> \
    AZURE_SQL_DATABASE=<terraform output -raw sql_database_name> \
    AZURE_SQL_USERNAME=<terraform output -raw sql_admin_username> \
    AZURE_SQL_PASSWORD=<terraform output -raw sql_admin_password> \
    python scripts/create_admin.py
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import bcrypt

from web import queries

EMAIL = "admin@vive-collision.com"
NAME = "Admin"
# Generated with `openssl rand` -- shown once here, not stored anywhere else.
# Rotate/change it after first login if this needs to be long-lived.
PASSWORD = os.environ.get("ADMIN_PASSWORD")

REQUIRED_ENV_VARS = ["AZURE_SQL_SERVER", "AZURE_SQL_DATABASE", "AZURE_SQL_USERNAME", "AZURE_SQL_PASSWORD"]


def main():
    missing = [v for v in REQUIRED_ENV_VARS if not os.environ.get(v)]
    if missing:
        sys.exit(
            f"Missing required environment variable(s): {', '.join(missing)}\n"
            "Set all four AZURE_SQL_* values for the target deployment before running -- "
            "see this script's docstring."
        )

    if queries.get_user_by_email(EMAIL):
        sys.exit(f"User {EMAIL} already exists -- not inserting. "
                  "Use web/queries.py's delete_user_by_email() first if you need to replace it.")

    password_hash = bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    queries.create_user(NAME, EMAIL, password_hash, created_by="create_admin.py")
    print(f"Created user {EMAIL} on {os.environ['AZURE_SQL_SERVER']}/{os.environ['AZURE_SQL_DATABASE']}")


if __name__ == "__main__":
    main()
