#!/usr/bin/env python3
"""
home_db.py — Home Project Management Utility for Steve
=======================================================
This script provides a Python interface to the home_projects.db SQLite database.
It is designed to be:
  - Run interactively from the command line
  - Called by Claude to answer "what's the status?" or "what do you need from me?"
  - Extended for future integrations (PG&E API, Gmail parsing, Google Drive, etc.)

USAGE EXAMPLES
--------------
  python3 home_db.py dashboard
  python3 home_db.py project "Roof Replacement"
  python3 home_db.py needs_attention
  python3 home_db.py log_comm 1 "email" "outbound" "Fence quote request" "Emailed three fence contractors"
  python3 home_db.py add_quote 1 "ABC Fencing" 3500.00
  python3 home_db.py update_task 1 "done"
  python3 home_db.py energy 2026-03 PG&E 450.2 72.50

FUTURE INTEGRATIONS
-------------------
  - PG&E Share My Data API: pipe monthly kWh/cost into energy_data table
  - Gmail API: parse vendor emails → auto-create communications + quotes records
  - Google Drive API: attach file URLs to documents / quotes tables
  - Google Calendar API: mark maintenance_items.last_completed on completion events
"""

import sqlite3
import os
import sys
import json
from datetime import date, datetime

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

# The DB is in the same directory as this script.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_SCRIPT_DIR, "home_projects.db")


def _conn():
    """Return a SQLite connection with row_factory for dict-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ==================================================================
# READ / QUERY FUNCTIONS
# ==================================================================

def get_dashboard_data() -> dict:
    """
    Return a comprehensive snapshot of the home project system.

    Useful for Claude to answer "what's the status?" or "what's on my plate?"

    Returns a dict with:
      - projects: list of all projects with their task summaries
      - needs_attention: tasks with status 'waiting_on_steve'
      - upcoming_maintenance: maintenance items due within 30 days
      - overdue_maintenance: items past their next_due date
      - open_tasks_by_project: count of non-done tasks per project
      - stats: high-level counts and cost totals
    """
    with _conn() as conn:
        today = date.today().isoformat()

        # All projects
        projects = [dict(r) for r in conn.execute(
            "SELECT * FROM projects ORDER BY priority DESC, created_date"
        ).fetchall()]

        # Attach task summaries to each project
        for p in projects:
            tasks = conn.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY id",
                (p["id"],)
            ).fetchall()
            p["tasks"] = [dict(t) for t in tasks]
            p["task_counts"] = {
                "total": len(tasks),
                "done": sum(1 for t in tasks if t["status"] == "done"),
                "in_progress": sum(1 for t in tasks if t["status"] == "in_progress"),
                "waiting_on_steve": sum(1 for t in tasks if t["status"] == "waiting_on_steve"),
                "waiting_on_vendor": sum(1 for t in tasks if t["status"] == "waiting_on_vendor"),
                "todo": sum(1 for t in tasks if t["status"] == "todo"),
            }

        # Tasks waiting on Steve
        needs_attention = [dict(r) for r in conn.execute("""
            SELECT t.*, p.name AS project_name
            FROM tasks t
            JOIN projects p ON p.id = t.project_id
            WHERE t.status = 'waiting_on_steve'
            ORDER BY t.due_date ASC NULLS LAST
        """).fetchall()]

        # Upcoming maintenance (next 30 days + overdue)
        upcoming_maintenance = [dict(r) for r in conn.execute("""
            SELECT *,
                   CASE WHEN next_due < ? THEN 1 ELSE 0 END AS is_overdue
            FROM maintenance_items
            WHERE next_due <= date(?, '+30 days') OR next_due < ?
            ORDER BY next_due
        """, (today, today, today)).fetchall()]

        # Stats
        stats = {
            "total_projects": len(projects),
            "by_status": {},
            "by_priority": {},
            "estimated_total": 0.0,
            "actual_total": 0.0,
        }
        for p in projects:
            stats["by_status"][p["status"]] = stats["by_status"].get(p["status"], 0) + 1
            stats["by_priority"][p["priority"]] = stats["by_priority"].get(p["priority"], 0) + 1
            stats["estimated_total"] += p["estimated_cost"] or 0.0
            stats["actual_total"] += p["actual_cost"] or 0.0

        # Recent communications
        recent_comms = [dict(r) for r in conn.execute("""
            SELECT c.*, p.name AS project_name
            FROM communications c
            JOIN projects p ON p.id = c.project_id
            ORDER BY c.date DESC
            LIMIT 10
        """).fetchall()]

        # Quotes awaiting action
        open_quotes = [dict(r) for r in conn.execute("""
            SELECT q.*, p.name AS project_name, v.name AS vendor_name
            FROM quotes q
            JOIN projects p ON p.id = q.project_id
            LEFT JOIN vendors v ON v.id = q.vendor_id
            WHERE q.status IN ('pending', 'received')
            ORDER BY q.date_received DESC
        """).fetchall()]

        return {
            "as_of": today,
            "projects": projects,
            "needs_attention": needs_attention,
            "upcoming_maintenance": upcoming_maintenance,
            "stats": stats,
            "recent_communications": recent_comms,
            "open_quotes": open_quotes,
        }


def get_project_detail(project_name: str) -> dict | None:
    """
    Return full detail for a single project, including all tasks,
    vendors, quotes, documents, and communications.

    Args:
        project_name: Exact or partial project name (case-insensitive LIKE match).

    Returns:
        dict with project + related records, or None if not found.

    Example:
        detail = get_project_detail("Roof")
        print(detail["project"]["status"])
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE name LIKE ? LIMIT 1",
            (f"%{project_name}%",)
        ).fetchone()
        if not row:
            return None

        p = dict(row)
        pid = p["id"]

        p["tasks"] = [dict(r) for r in conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY id", (pid,)
        ).fetchall()]

        p["quotes"] = [dict(r) for r in conn.execute("""
            SELECT q.*, v.name AS vendor_name
            FROM quotes q LEFT JOIN vendors v ON v.id = q.vendor_id
            WHERE q.project_id = ?
            ORDER BY q.date_received DESC NULLS LAST
        """, (pid,)).fetchall()]

        p["documents"] = [dict(r) for r in conn.execute(
            "SELECT * FROM documents WHERE project_id = ? ORDER BY date_added DESC", (pid,)
        ).fetchall()]

        p["communications"] = [dict(r) for r in conn.execute(
            "SELECT * FROM communications WHERE project_id = ? ORDER BY date DESC", (pid,)
        ).fetchall()]

        return p


# ==================================================================
# WRITE / UPDATE FUNCTIONS
# ==================================================================

def log_communication(
    project_id: int,
    comm_type: str,         # email | call | text | meeting
    direction: str,         # inbound | outbound
    subject: str,
    summary: str,
    contact_name: str = None,
    follow_up_needed: bool = False,
    follow_up_date: str = None,
    notes: str = None,
    comm_date: str = None,
) -> int:
    """
    Log a communication (email, call, text, meeting) related to a project.

    Args:
        project_id:       ID of the associated project.
        comm_type:        One of 'email', 'call', 'text', 'meeting'.
        direction:        'inbound' (vendor contacted us) or 'outbound' (we initiated).
        subject:          Short subject/title of the communication.
        summary:          Detailed summary of what was discussed.
        contact_name:     Name of the vendor/contact involved.
        follow_up_needed: True if a follow-up action is required.
        follow_up_date:   ISO date string for when to follow up (YYYY-MM-DD).
        notes:            Any additional notes.
        comm_date:        Date of communication (defaults to today).

    Returns:
        The new communication record ID.

    Future integration note:
        Gmail parsing could call this function automatically when
        vendor emails are detected in the inbox.
    """
    if comm_date is None:
        comm_date = date.today().isoformat()

    with _conn() as conn:
        cur = conn.execute("""
            INSERT INTO communications
                (project_id, type, direction, subject, summary, date,
                 contact_name, follow_up_needed, follow_up_date, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id, comm_type, direction, subject, summary,
            comm_date, contact_name, int(follow_up_needed), follow_up_date, notes
        ))
        conn.commit()
        new_id = cur.lastrowid
        print(f"✓ Communication logged (id={new_id}) for project {project_id}")
        return new_id


def add_quote(
    project_id: int,
    vendor_name: str,
    amount: float,
    date_received: str = None,
    valid_until: str = None,
    status: str = "received",
    drive_file_url: str = None,
    notes: str = None,
) -> int:
    """
    Add a quote from a vendor to a project.
    Creates the vendor record if it doesn't already exist.

    Args:
        project_id:      ID of the associated project.
        vendor_name:     Name of the vendor (looked up or auto-created).
        amount:          Dollar amount of the quote.
        date_received:   ISO date string (defaults to today).
        valid_until:     ISO date string when quote expires.
        status:          One of 'pending', 'received', 'accepted', 'rejected'.
        drive_file_url:  Link to PDF in Google Drive.
        notes:           Any additional notes about this quote.

    Returns:
        The new quote record ID.

    Future integration note:
        Gmail/Drive integration could parse PDF attachments and
        call this automatically when a quote email arrives.
    """
    if date_received is None:
        date_received = date.today().isoformat()

    with _conn() as conn:
        # Upsert vendor
        row = conn.execute(
            "SELECT id FROM vendors WHERE name LIKE ?", (vendor_name,)
        ).fetchone()
        if row:
            vendor_id = row["id"]
        else:
            cur = conn.execute(
                "INSERT INTO vendors (name) VALUES (?)", (vendor_name,)
            )
            vendor_id = cur.lastrowid
            print(f"  + Created new vendor '{vendor_name}' (id={vendor_id})")

        # Insert quote
        cur = conn.execute("""
            INSERT INTO quotes
                (project_id, vendor_id, amount, date_received, valid_until,
                 status, drive_file_url, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id, vendor_id, amount, date_received,
            valid_until, status, drive_file_url, notes
        ))
        conn.commit()
        new_id = cur.lastrowid
        print(f"✓ Quote added (id={new_id}): ${amount:,.2f} from '{vendor_name}' for project {project_id}")
        return new_id


def update_task_status(task_id: int, new_status: str, notes: str = None) -> bool:
    """
    Update the status of a task.

    Args:
        task_id:    ID of the task to update.
        new_status: One of 'todo', 'in_progress', 'waiting_on_vendor',
                    'waiting_on_steve', 'done'.
        notes:      Optional notes to append to the task.

    Returns:
        True if the task was found and updated, False otherwise.

    Example:
        update_task_status(3, 'done')
        update_task_status(5, 'waiting_on_vendor', 'Awaiting quote from ABC Fencing')
    """
    valid = {"todo", "in_progress", "waiting_on_vendor", "waiting_on_steve", "done"}
    if new_status not in valid:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of: {valid}")

    with _conn() as conn:
        kwargs = {"status": new_status}
        if notes:
            conn.execute(
                "UPDATE tasks SET status = ?, notes = ? WHERE id = ?",
                (new_status, notes, task_id)
            )
        else:
            conn.execute(
                "UPDATE tasks SET status = ? WHERE id = ?",
                (new_status, task_id)
            )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row:
            print(f"✓ Task {task_id} ('{row['title']}') updated to '{new_status}'")
            return True
        else:
            print(f"⚠ Task {task_id} not found.")
            return False


def add_energy_reading(
    kwh_used: float,
    cost: float,
    provider: str = "PG&E",
    reading_date: str = None,
    notes: str = None,
) -> int:
    """
    Log a monthly energy reading.

    Future integration note:
        PG&E Share My Data API (OAuth 2.0, Green Button format) can provide
        daily/hourly interval data. Call this function after parsing the
        ESPI XML or JSON export. Endpoint: https://api.pge.com/GreenButtonConnect/espi/
    """
    if reading_date is None:
        reading_date = date.today().isoformat()

    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO energy_data (date, provider, kwh_used, cost, notes) VALUES (?, ?, ?, ?, ?)",
            (reading_date, provider, kwh_used, cost, notes)
        )
        conn.commit()
        print(f"✓ Energy reading logged: {kwh_used} kWh / ${cost:.2f} on {reading_date}")
        return cur.lastrowid


def update_maintenance_completed(item_id: int) -> bool:
    """
    Mark a maintenance item as completed today, and advance next_due by frequency_days.

    Example:
        update_maintenance_completed(1)  # Air filter replaced today
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM maintenance_items WHERE id = ?", (item_id,)
        ).fetchone()
        if not row:
            print(f"⚠ Maintenance item {item_id} not found.")
            return False

        today = date.today().isoformat()
        freq = row["frequency_days"] or 90
        next_due = date.today().replace(
            day=date.today().day
        )
        # Simple date arithmetic via SQL
        conn.execute("""
            UPDATE maintenance_items
            SET last_completed = ?, next_due = date(?, '+' || ? || ' days')
            WHERE id = ?
        """, (today, today, freq, item_id))
        conn.commit()
        updated = conn.execute(
            "SELECT next_due FROM maintenance_items WHERE id = ?", (item_id,)
        ).fetchone()
        print(f"✓ '{row['name']}' marked complete. Next due: {updated['next_due']}")
        return True


def update_maintenance_inventory(item_id: int, count: int) -> bool:
    """Update the inventory count for a maintenance item."""
    with _conn() as conn:
        conn.execute(
            "UPDATE maintenance_items SET inventory_count = ? WHERE id = ?",
            (count, item_id)
        )
        conn.commit()
        print(f"✓ Inventory updated to {count} for item {item_id}")
        return True


# ==================================================================
# PRETTY-PRINT HELPERS (for CLI use)
# ==================================================================

def print_dashboard():
    """Print a human-readable dashboard to stdout."""
    data = get_dashboard_data()
    today = data["as_of"]
    stats = data["stats"]

    print("\n" + "="*65)
    print(f"  🏠  HOME PROJECT DASHBOARD  —  {today}")
    print("="*65)

    print(f"\n📊 OVERVIEW")
    print(f"   Total projects  : {stats['total_projects']}")
    for status, count in sorted(stats["by_status"].items()):
        print(f"   {status:<18}: {count}")
    if stats["estimated_total"]:
        print(f"   Est. total spend: ${stats['estimated_total']:,.0f}")

    if data["needs_attention"]:
        print(f"\n🚨 NEEDS YOUR ATTENTION ({len(data['needs_attention'])} tasks)")
        for t in data["needs_attention"]:
            due = f" — due {t['due_date']}" if t.get("due_date") else ""
            print(f"   [{t['id']}] {t['project_name']}: {t['title']}{due}")
    else:
        print(f"\n✅ Nothing is waiting on you right now.")

    if data["upcoming_maintenance"]:
        print(f"\n🔧 UPCOMING MAINTENANCE")
        for m in data["upcoming_maintenance"]:
            overdue = " ⚠ OVERDUE" if m.get("is_overdue") else ""
            inv = f"  (inventory: {m['inventory_count']} {m['inventory_unit'] or ''})" if m.get('inventory_unit') else ""
            print(f"   [{m['id']}] {m['name']} — due {m['next_due']}{overdue}{inv}")

    print(f"\n📋 PROJECTS")
    for p in data["projects"]:
        tc = p["task_counts"]
        pct = int(tc["done"] / tc["total"] * 100) if tc["total"] else 0
        print(f"\n   {p['name']}  [{p['status'].upper()} / {p['priority']} priority]")
        print(f"   Tasks: {tc['done']}/{tc['total']} done ({pct}%)")
        todo_tasks = [t for t in p["tasks"] if t["status"] not in ("done",)]
        for t in todo_tasks[:3]:
            flag = "⚠ " if t["status"] == "waiting_on_steve" else "  "
            print(f"   {flag}› [{t['status']}] {t['title']}")
        if len(todo_tasks) > 3:
            print(f"     … and {len(todo_tasks)-3} more")

    if data["open_quotes"]:
        print(f"\n💰 OPEN QUOTES")
        for q in data["open_quotes"]:
            amt = f"${q['amount']:,.0f}" if q.get("amount") else "TBD"
            print(f"   {q['project_name']} — {q.get('vendor_name','Unknown vendor')} — {amt} [{q['status']}]")

    print("\n" + "="*65 + "\n")


# ==================================================================
# CLI ENTRY POINT
# ==================================================================

if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "dashboard"

    if cmd in ("dashboard", "status", "d"):
        print_dashboard()

    elif cmd in ("project", "p") and len(args) >= 2:
        name = " ".join(args[1:])
        detail = get_project_detail(name)
        if detail:
            print(json.dumps(detail, indent=2, default=str))
        else:
            print(f"Project '{name}' not found.")

    elif cmd == "needs_attention":
        data = get_dashboard_data()
        tasks = data["needs_attention"]
        if tasks:
            print(f"\n🚨 {len(tasks)} task(s) waiting on Steve:\n")
            for t in tasks:
                print(f"  [{t['id']}] {t['project_name']}: {t['title']}")
        else:
            print("✅ Nothing is waiting on you right now.")

    elif cmd == "update_task" and len(args) >= 3:
        task_id = int(args[1])
        new_status = args[2]
        notes = args[3] if len(args) > 3 else None
        update_task_status(task_id, new_status, notes)

    elif cmd == "log_comm" and len(args) >= 6:
        # log_comm <project_id> <type> <direction> <subject> <summary> [contact]
        project_id = int(args[1])
        comm_type  = args[2]
        direction  = args[3]
        subject    = args[4]
        summary    = args[5]
        contact    = args[6] if len(args) > 6 else None
        log_communication(project_id, comm_type, direction, subject, summary, contact)

    elif cmd == "add_quote" and len(args) >= 4:
        # add_quote <project_id> <vendor_name> <amount> [notes]
        project_id  = int(args[1])
        vendor_name = args[2]
        amount      = float(args[3])
        notes       = args[4] if len(args) > 4 else None
        add_quote(project_id, vendor_name, amount, notes=notes)

    elif cmd == "energy" and len(args) >= 5:
        # energy <date> <provider> <kwh> <cost>
        add_energy_reading(
            kwh_used=float(args[3]),
            cost=float(args[4]),
            provider=args[2],
            reading_date=args[1],
        )

    elif cmd == "maintenance_done" and len(args) >= 2:
        update_maintenance_completed(int(args[1]))

    else:
        print(__doc__)
        print("Commands: dashboard | project <name> | needs_attention | update_task <id> <status>")
        print("          log_comm <proj_id> <type> <dir> <subject> <summary>")
        print("          add_quote <proj_id> <vendor> <amount>")
        print("          energy <date> <provider> <kwh> <cost>")
        print("          maintenance_done <item_id>")
