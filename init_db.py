#!/usr/bin/env python3
"""
init_db.py — One-time database initialization + data migration
==============================================================
Creates all missing tables and imports everything from dashboard_data.json.
Safe to re-run — uses INSERT OR IGNORE to avoid duplicates.

Run from the project root:
    python3 init_db.py
"""

import sqlite3, json, os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(PROJECT_DIR, "home_projects.db")
JSON_PATH   = os.path.join(PROJECT_DIR, "dashboard_data.json")


def create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            name           TEXT NOT NULL,
            category       TEXT,
            status         TEXT DEFAULT 'planning',
            priority       TEXT DEFAULT 'medium',
            description    TEXT,
            estimated_cost REAL,
            actual_cost    REAL,
            created_date   TEXT,
            target_date    TEXT,
            notes          TEXT
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id),
            title       TEXT NOT NULL,
            status      TEXT DEFAULT 'todo',
            assigned_to TEXT,
            due_date    TEXT,
            notes       TEXT
        );

        CREATE TABLE IF NOT EXISTS vendors (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            name    TEXT NOT NULL,
            contact TEXT
        );

        CREATE TABLE IF NOT EXISTS quotes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id     INTEGER NOT NULL REFERENCES projects(id),
            vendor_id      INTEGER REFERENCES vendors(id),
            amount         REAL,
            date_received  TEXT,
            sent_date      TEXT,
            valid_until    TEXT,
            status         TEXT DEFAULT 'pending',
            drive_file_url TEXT,
            notes          TEXT,
            contact        TEXT
        );

        CREATE TABLE IF NOT EXISTS maintenance_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            category        TEXT,
            frequency_days  INTEGER,
            last_completed  TEXT,
            next_due        TEXT,
            inventory_count INTEGER DEFAULT 0,
            inventory_unit  TEXT,
            notes           TEXT
        );

        CREATE TABLE IF NOT EXISTS communications (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id       INTEGER REFERENCES projects(id),
            type             TEXT DEFAULT 'email',
            direction        TEXT,
            subject          TEXT,
            summary          TEXT,
            date             TEXT,
            time             TEXT,
            vendor_name      TEXT,
            contact          TEXT,
            contact_name     TEXT,
            follow_up_needed INTEGER DEFAULT 0,
            follow_up_date   TEXT,
            notes            TEXT,
            gmail_id         TEXT,
            thread_id        TEXT
        );

        CREATE TABLE IF NOT EXISTS documents (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER REFERENCES projects(id),
            title       TEXT,
            url         TEXT,
            date_added  TEXT
        );

        CREATE TABLE IF NOT EXISTS thermostat_readings (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp       TEXT NOT NULL,
            location        TEXT,
            temp_f          REAL,
            humidity_pct    REAL,
            mode            TEXT,
            hvac_status     TEXT,
            heat_setpoint_f REAL,
            cool_setpoint_f REAL,
            eco_mode        TEXT,
            fan_mode        TEXT,
            connectivity    TEXT
        );

        CREATE TABLE IF NOT EXISTS energy_data (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT NOT NULL,
            provider     TEXT,
            utility_type TEXT,
            kwh_used     REAL,
            therms_used  REAL,
            cost         REAL,
            granularity  TEXT,
            notes        TEXT
        );
    """)
    conn.commit()
    print("✓ All tables created")


def migrate(conn, data):
    project_id_map = {}
    vendor_id_map  = {}

    # ── Projects, tasks, quotes ───────────────────────────────────────────────
    for p in data.get("projects", []):
        orig_id = p["id"]
        # Skip if already there
        existing = conn.execute("SELECT id FROM projects WHERE name=?", (p["name"],)).fetchone()
        if existing:
            project_id_map[orig_id] = existing[0]
            print(f"  (skip existing project: {p['name']})")
            continue

        cur = conn.execute("""
            INSERT INTO projects
                (name, category, status, priority, description,
                 estimated_cost, actual_cost, created_date, target_date, notes)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (p["name"], p.get("category"), p.get("status"), p.get("priority"),
              p.get("description"), p.get("estimated_cost"), p.get("actual_cost"),
              p.get("created_date"), p.get("target_date"), p.get("notes")))
        new_pid = cur.lastrowid
        project_id_map[orig_id] = new_pid

        for t in p.get("tasks", []):
            conn.execute("""
                INSERT INTO tasks (project_id, title, status, assigned_to, due_date, notes)
                VALUES (?,?,?,?,?,?)
            """, (new_pid, t["title"], t.get("status","todo"),
                  t.get("assigned_to"), t.get("due_date"), t.get("notes")))

        for q in p.get("quotes", []):
            vname = q.get("vendor_name") or "Unknown"
            if vname not in vendor_id_map:
                ex = conn.execute("SELECT id FROM vendors WHERE name=?", (vname,)).fetchone()
                if ex:
                    vendor_id_map[vname] = ex[0]
                else:
                    vc = conn.execute("INSERT INTO vendors (name, contact) VALUES (?,?)",
                                      (vname, q.get("contact")))
                    vendor_id_map[vname] = vc.lastrowid
            conn.execute("""
                INSERT INTO quotes
                    (project_id, vendor_id, amount, date_received, sent_date, status, notes, contact)
                VALUES (?,?,?,?,?,?,?,?)
            """, (new_pid, vendor_id_map[vname], q.get("amount"),
                  q.get("received_date"), q.get("sent_date"),
                  q.get("status","pending"), q.get("notes"), q.get("contact")))

    conn.commit()
    print(f"✓ {len(project_id_map)} projects (+ tasks + quotes) imported")

    # ── Maintenance ────────────────────────────────────────────────────────────
    count_m = 0
    for m in data.get("maintenance", []):
        ex = conn.execute("SELECT id FROM maintenance_items WHERE name=?", (m["name"],)).fetchone()
        if ex:
            continue
        conn.execute("""
            INSERT INTO maintenance_items
                (name, category, frequency_days, last_completed, next_due,
                 inventory_count, inventory_unit, notes)
            VALUES (?,?,?,?,?,?,?,?)
        """, (m["name"], m.get("category"), m.get("frequency_days"),
              m.get("last_completed"), m.get("next_due"),
              m.get("inventory_count", 0), m.get("inventory_unit"), m.get("notes")))
        count_m += 1
    conn.commit()
    print(f"✓ {count_m} maintenance items imported")

    # ── Communications ─────────────────────────────────────────────────────────
    count_c = 0
    for c in data.get("recent_communications", []):
        orig_pid = c.get("project_id")
        new_pid  = project_id_map.get(orig_pid)
        ex = conn.execute("SELECT id FROM communications WHERE gmail_id=?",
                          (c.get("gmail_id"),)).fetchone()
        if ex:
            continue
        conn.execute("""
            INSERT INTO communications
                (project_id, type, direction, subject, summary, date, time,
                 vendor_name, contact, gmail_id, thread_id)
            VALUES (?, 'email', ?,?,?,?,?,?,?,?,?)
        """, (new_pid, c.get("direction"), c.get("subject"), c.get("summary"),
              c.get("date"), c.get("time"), c.get("vendor_name"),
              c.get("contact"), c.get("gmail_id"), c.get("thread_id")))
        count_c += 1
    conn.commit()
    print(f"✓ {count_c} communications imported")


def main():
    print(f"DB: {DB_PATH}")
    with open(JSON_PATH) as f:
        data = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    create_tables(conn)
    migrate(conn, data)
    conn.close()
    print("\n✓ Done — run: python3 scripts/nest_monitor.py")


if __name__ == "__main__":
    main()
