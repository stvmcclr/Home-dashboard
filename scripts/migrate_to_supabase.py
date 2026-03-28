#!/usr/bin/env python3
"""
migrate_to_supabase.py — One-time migration from SQLite → Supabase
===================================================================
Pushes energy_data and maintenance_items from local SQLite DB into Supabase.
Projects/tasks/vendors/quotes/communications already exist in Supabase.

Run once from project root:
    python3 scripts/migrate_to_supabase.py
"""

import sqlite3
import os
import sys

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DB_PATH     = os.path.join(PROJECT_DIR, "home_projects.db")

sys.path.insert(0, SCRIPT_DIR)
from supabase_client import get_client


def migrate_energy(sb, conn):
    rows = [dict(r) for r in conn.execute("SELECT * FROM energy_data ORDER BY date").fetchall()]
    if not rows:
        print("  energy_data: no rows in SQLite, skipping")
        return

    # Strip SQLite id so Supabase auto-assigns
    for r in rows:
        r.pop("id", None)

    # Batch upsert in chunks of 500
    chunk_size = 500
    inserted = 0
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i+chunk_size]
        sb.upsert("energy_data", chunk)
        inserted += len(chunk)

    print(f"  ✓ energy_data: {inserted} rows upserted")


def migrate_maintenance(sb, conn):
    rows = [dict(r) for r in conn.execute("SELECT * FROM maintenance_items ORDER BY id").fetchall()]
    if not rows:
        print("  maintenance_items: no rows in SQLite, skipping")
        return

    for r in rows:
        r.pop("id", None)

    sb.upsert("maintenance_items", rows)
    print(f"  ✓ maintenance_items: {len(rows)} rows upserted")


def migrate_thermostat(sb, conn):
    rows = [dict(r) for r in conn.execute("SELECT * FROM thermostat_readings ORDER BY timestamp").fetchall()]
    if not rows:
        print("  thermostat_readings: no rows in SQLite, skipping")
        return

    for r in rows:
        r.pop("id", None)

    chunk_size = 500
    inserted = 0
    for i in range(0, len(rows), chunk_size):
        sb.insert("thermostat_readings", rows[i:i+chunk_size])
        inserted += len(rows[i:i+chunk_size])

    print(f"  ✓ thermostat_readings: {inserted} rows inserted")


def main():
    if not os.path.exists(DB_PATH):
        print(f"✗ SQLite DB not found at {DB_PATH}")
        sys.exit(1)

    print(f"Migrating from: {DB_PATH}")
    sb   = get_client()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    migrate_energy(sb, conn)
    migrate_maintenance(sb, conn)
    migrate_thermostat(sb, conn)

    conn.close()
    print("\n✓ Migration complete. You can now run everything from GitHub Actions.")


if __name__ == "__main__":
    main()
