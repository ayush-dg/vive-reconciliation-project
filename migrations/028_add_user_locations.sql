-- 028_add_user_locations.sql
--
-- The VIVE shops each user works (2026-11-09). Home, Statement Processing and
-- Exceptions open on "My locations" for a user with shops here; admins set
-- them on the Users page (web/user_locations.py). shop is a name from
-- config/vive_shops.json. A user with no rows sees every location.
-- (Azure SQL: src/lakehouse/azure_sql_migrations.py, TABLES["user_locations"].)

CREATE TABLE IF NOT EXISTS user_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    shop TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT,
    UNIQUE (email, shop)
);
