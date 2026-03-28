#!/usr/bin/env python3
"""
generate_dashboard_data.py — Build dashboard_data.json from Supabase
=====================================================================
Reads all tables and produces a single JSON snapshot at:
    <project_root>/dashboard_data.json

Called automatically by nest_monitor.py after each poll.
Also call manually:
    python3 scripts/generate_dashboard_data.py
"""

import json
import os
import sys
from datetime import date, datetime, timezone

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
OUTPUT_PATH = os.path.join(PROJECT_DIR, "dashboard_data.json")

sys.path.insert(0, SCRIPT_DIR)
from supabase_client import get_client


def build_data():
    sb    = get_client()
    today = date.today().isoformat()
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── Projects ─────────────────────────────────────────────────────────────
    projects = sb.select("projects", order="created_at.asc")

    for p in projects:
        tasks  = sb.select("tasks", filters={"project_id": f"eq.{p['id']}"}, order="id.asc")
        p["tasks"] = tasks
        p["task_counts"] = {
            "total":             len(tasks),
            "done":              sum(1 for t in tasks if t["status"] == "done"),
            "in_progress":       sum(1 for t in tasks if t["status"] == "in_progress"),
            "waiting_on_steve":  sum(1 for t in tasks if t["status"] == "waiting_on_steve"),
            "waiting_on_vendor": sum(1 for t in tasks if t["status"] == "waiting_on_vendor"),
            "todo":              sum(1 for t in tasks if t["status"] == "todo"),
        }
        quotes = sb.select(
            "quotes",
            query="*, vendors(name)",
            filters={"project_id": f"eq.{p['id']}"},
            order="id.desc"
        )
        # Flatten vendor name
        for q in quotes:
            if isinstance(q.get("vendors"), dict):
                q["vendor_name"] = q["vendors"].get("name")
            del q["vendors"]
        p["quotes"] = quotes

    # ── Maintenance ───────────────────────────────────────────────────────────
    raw_maint = sb.select("maintenance_items", order="next_due.asc.nullslast")
    maintenance = []
    for m in raw_maint:
        nd = m.get("next_due")
        if nd:
            days = (date.fromisoformat(nd) - date.today()).days
            m["days_until_due"] = days
            m["is_overdue"]     = 1 if days < 0 else 0
        else:
            m["days_until_due"] = None
            m["is_overdue"]     = 0
        maintenance.append(m)

    # ── Needs attention ───────────────────────────────────────────────────────
    waiting_tasks = sb.select("tasks", query="*, projects(name)", filters={"status": "eq.waiting_on_steve"})
    needs_attention = []
    for t in waiting_tasks:
        if isinstance(t.get("projects"), dict):
            t["project_name"] = t["projects"].get("name")
        t.pop("projects", None)
        needs_attention.append(t)

    # ── Open quotes ───────────────────────────────────────────────────────────
    open_quotes_raw = sb.select(
        "quotes",
        query="*, projects(name), vendors(name)",
        filters={"status": "in.(pending,received)"},
        order="id.desc"
    )
    open_quotes = []
    for q in open_quotes_raw:
        if isinstance(q.get("projects"), dict):
            q["project_name"] = q["projects"].get("name")
        if isinstance(q.get("vendors"), dict):
            q["vendor_name"] = q["vendors"].get("name")
        q.pop("projects", None)
        q.pop("vendors", None)
        open_quotes.append(q)

    # ── Recent communications ─────────────────────────────────────────────────
    comms_raw = sb.select(
        "communications",
        query="*, projects(name)",
        order="id.desc",
        limit=15
    )
    recent_comms = []
    for c in comms_raw:
        if isinstance(c.get("projects"), dict):
            c["project_name"] = c["projects"].get("name")
        c.pop("projects", None)
        recent_comms.append(c)

    # ── Thermostat: latest per location ───────────────────────────────────────
    all_recent = sb.select(
        "thermostat_readings",
        order="timestamp.desc",
        limit=100
    )
    seen_locations = set()
    thermostat_latest = []
    for r in all_recent:
        loc = r.get("location")
        if loc not in seen_locations:
            seen_locations.add(loc)
            thermostat_latest.append(r)

    # Last 24h history
    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    thermostat_history = sb.select(
        "thermostat_readings",
        filters={"timestamp": f"gte.{cutoff[:10]}T00:00:00"},
        order="timestamp.asc",
        limit=200
    )

    # ── Energy: monthly aggregates ─────────────────────────────────────────
    elec_rows = sb.select("energy_data", filters={"utility_type": "eq.electric"}, order="date.asc")
    gas_rows  = sb.select("energy_data", filters={"utility_type": "eq.gas"},      order="date.asc")

    def monthly_agg(rows, value_key):
        months = {}
        for r in rows:
            d = r.get("date", "")[:7]  # "YYYY-MM"
            if not d:
                continue
            if d not in months:
                months[d] = {"month": d, value_key: 0.0, "cost": 0.0}
            months[d][value_key] = round(months[d][value_key] + (r.get(value_key) or 0), 3)
            months[d]["cost"]    = round(months[d]["cost"]    + (r.get("cost") or 0), 2)
        return sorted(months.values(), key=lambda x: x["month"])

    monthly_electric = monthly_agg(elec_rows, "kwh_used")
    monthly_gas      = monthly_agg(gas_rows,  "therms_used")

    elec_kwh   = sum(r.get("kwh_used")    or 0 for r in elec_rows)
    elec_cost  = sum(r.get("cost")        or 0 for r in elec_rows)
    gas_therms = sum(r.get("therms_used") or 0 for r in gas_rows)
    gas_cost   = sum(r.get("cost")        or 0 for r in gas_rows)

    # ── Stats ─────────────────────────────────────────────────────────────────
    stats = {"total_projects": len(projects), "by_status": {}, "by_priority": {},
             "estimated_total": 0.0, "actual_total": 0.0}
    for p in projects:
        stats["by_status"][p["status"]]     = stats["by_status"].get(p["status"], 0) + 1
        stats["by_priority"][p["priority"]] = stats["by_priority"].get(p["priority"], 0) + 1
        stats["estimated_total"] += p.get("estimated_cost") or 0.0
        stats["actual_total"]    += p.get("actual_cost")    or 0.0

    return {
        "generated_at":          now,
        "as_of":                  today,
        "projects":               projects,
        "needs_attention":        needs_attention,
        "maintenance":            maintenance,
        "open_quotes":            open_quotes,
        "recent_communications":  recent_comms,
        "thermostat": {
            "latest":  thermostat_latest,
            "history": thermostat_history,
        },
        "energy": {
            "monthly_electric": monthly_electric,
            "monthly_gas":      monthly_gas,
            "totals": {
                "electric_kwh":  round(elec_kwh, 1),
                "electric_cost": round(elec_cost, 2),
                "gas_therms":    round(gas_therms, 2),
                "gas_cost":      round(gas_cost, 2),
            }
        },
        "stats": stats,
    }


def main():
    data = build_data()
    with open(OUTPUT_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)

    n_projects    = len(data["projects"])
    n_therm       = len(data["thermostat"]["latest"])
    n_elec_months = len(data["energy"]["monthly_electric"])
    print(f"✓ dashboard_data.json written  ({n_projects} projects, {n_therm} thermostats, {n_elec_months} months energy)")


if __name__ == "__main__":
    main()
