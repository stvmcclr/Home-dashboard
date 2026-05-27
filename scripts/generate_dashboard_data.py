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

    # ── Home Intelligence ──────────────────────────────────────────────────
    intelligence = {"observations": [], "insights": [], "state": {}}
    try:
        # Last 200 observations — dashboard activity feed uses all of them
        obs_rows = sb.select(
            "home_observations",
            order="timestamp.desc",
            limit=200
        )
        intelligence["observations"] = obs_rows

        # Open insights (last 10)
        insight_rows = sb.select(
            "home_insights",
            filters={"acted_on_at": "is.null"},
            order="timestamp.desc",
            limit=10
        )
        intelligence["insights"] = insight_rows

        # Current home state
        state_rows = sb.select(
            "home_state",
            filters={"id": "eq.current"},
            limit=1
        )
        if state_rows:
            state = state_rows[0]
            # Parse JSON strings back to lists/dicts if needed
            for key in ("who_is_home", "active_rooms", "lights_on", "music_playing", "last_motion"):
                if isinstance(state.get(key), str):
                    try:
                        state[key] = json.loads(state[key])
                    except Exception:
                        pass
            # If who_is_home is empty, derive from recent obs entities
            if not state.get("who_is_home"):
                try:
                    import sqlite3, time as _t2
                    _db2 = os.path.expanduser("~/.openclaw/home_intelligence.db")
                    if os.path.exists(_db2):
                        _c = sqlite3.connect(_db2)
                        _rows = _c.execute("""
                            SELECT DISTINCT oe.entity_name
                            FROM observation_entities oe
                            JOIN observations o ON o.id = oe.observation_id
                            WHERE oe.entity_type = 'person'
                              AND o.timestamp > ?
                            ORDER BY oe.entity_name
                        """, (int(_t2.time()) - 7200,)).fetchall()
                        _c.close()
                        _names = [r[0] for r in _rows if r[0] and r[0].lower() not in ('unknown','none','')]
                        if _names:
                            state["who_is_home"] = _names
                except Exception:
                    pass
            intelligence["state"] = state
    except Exception as e:
        # Supabase tables missing or unreachable — fall back to local SQLite
        intelligence["_supabase_error"] = str(e)
        try:
            import sqlite3, time as _time
            _db_path = os.path.expanduser("~/.openclaw/home_intelligence.db")
            if os.path.exists(_db_path):
                _db = sqlite3.connect(_db_path)
                _db.row_factory = sqlite3.Row
                # Observations
                _obs = _db.execute("""
                    SELECT id, datetime(timestamp,'unixepoch','localtime') as timestamp,
                           source, source_type, location, summary, confidence, model_version
                    FROM observations ORDER BY timestamp DESC LIMIT 60
                """).fetchall()
                intelligence["observations"] = [dict(r) for r in _obs]
                # Open insights
                _ins = _db.execute("""
                    SELECT id, datetime(timestamp,'unixepoch','localtime') as timestamp,
                           insight_type, severity, summary
                    FROM insights WHERE acted_on_at IS NULL
                    ORDER BY timestamp DESC LIMIT 10
                """).fetchall()
                intelligence["insights"] = [dict(r) for r in _ins]
                # Home state — build rich arrays the dashboard expects
                _cutoff_30 = int(_time.time()) - 1800   # 30 min
                _cutoff_2h = int(_time.time()) - 7200   # 2 hours

                # Who's home: person entities spotted by cameras in last 2h
                _person_rows = _db.execute("""
                    SELECT DISTINCT oe.entity_name
                    FROM observation_entities oe
                    JOIN observations o ON o.id = oe.observation_id
                    WHERE oe.entity_type = 'person'
                      AND o.timestamp > ?
                    ORDER BY oe.entity_name
                """, (_cutoff_2h,)).fetchall()
                _who_list = [
                    r[0] for r in _person_rows
                    if r[0] and r[0].lower() not in ('unknown', 'none', '')
                ]
                # Fallback: check device count from presence
                if not _who_list:
                    _pres = _db.execute(
                        "SELECT summary FROM observations WHERE source='unifi:presence' AND timestamp>? ORDER BY timestamp DESC LIMIT 1",
                        (_cutoff_30,)).fetchone()
                    if _pres and _pres[0]:
                        import re as _re
                        m = _re.search(r'(\d+) mobile', _pres[0])
                        if m and int(m.group(1)) > 0:
                            _who_list = [f"{m.group(1)} devices"]

                # Lights on: parse "Lights on: room1, room2" → list
                _lights_row = _db.execute(
                    "SELECT summary FROM observations WHERE source='ha:lights' AND timestamp>? ORDER BY timestamp DESC LIMIT 1",
                    (_cutoff_30,)).fetchone()
                _lights_list = []
                if _lights_row and _lights_row[0]:
                    txt = _lights_row[0]
                    if 'Lights on:' in txt:
                        lights_part = txt.split('Lights on:')[1].strip()
                        _lights_list = [l.strip().replace('_', ' ') for l in lights_part.split(',') if l.strip()]

                # Active rooms: locations with cam/audio obs in last 30 min
                _room_rows = _db.execute("""
                    SELECT DISTINCT location FROM observations
                    WHERE timestamp > ?
                      AND location NOT IN ('home', 'unknown', '')
                      AND source NOT IN ('unifi:presence', 'ha:lights', 'ha:audio', 'flume')
                    ORDER BY location
                """, (_cutoff_30,)).fetchall()
                _active_rooms = [r[0] for r in _room_rows if r[0]]

                # Music playing
                _music_row = _db.execute(
                    "SELECT summary FROM observations WHERE source='ha:audio' AND timestamp>? ORDER BY timestamp DESC LIMIT 1",
                    (_cutoff_30,)).fetchone()
                _music_list = []
                if _music_row and _music_row[0]:
                    _mtxt = _music_row[0].lower()
                    if any(w in _mtxt for w in ['playing', 'music', 'song', 'track']):
                        _music_list = ['playing']

                intelligence["state"] = {
                    "source": "sqlite_fallback",
                    "who_is_home":  _who_list,
                    "lights_on":    _lights_list,
                    "active_rooms": _active_rooms,
                    "music_playing": _music_list,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }
                _db.close()
                intelligence["_source"] = "sqlite_fallback"
        except Exception as e2:
            intelligence["_error"] = str(e2)

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
        "stats":        stats,
        "intelligence": intelligence,
        "pge":          _build_pge_section(),
    }


def _build_pge_section() -> dict:
    """Return structured PGE hourly data for the dashboard.

    Strategy:
      1. Try local SQLite (~/.openclaw/home_intelligence.db) — fast, works on Mac.
      2. If not available (e.g. GitHub Actions), fall back to Supabase
         energy_data rows with utility_type='electric_hourly', synced by
         pge_poller.py every 30 min.
    """
    result = {"hourly": [], "daily": [], "latest_kwh": None,
              "avg_per_hour": None, "evening_peak_kwh": None, "data_through": None}
    try:
        import sqlite3 as _sq
        _db_path = os.path.expanduser("~/.openclaw/home_intelligence.db")
        if os.path.exists(_db_path):
            # ── Local SQLite path (Mac) ───────────────────────────────────────
            _db = _sq.connect(_db_path)
            _db.row_factory = _sq.Row

            # Hourly readings: last 72h converted to local PDT (UTC-7)
            _rows = _db.execute("""
                SELECT
                  strftime('%Y-%m-%dT%H:00', datetime(interval_ts, '-7 hours')) as ts,
                  kwh
                FROM pge_energy
                WHERE kwh > 0 AND duration_s = 3600
                  AND interval_ts >= datetime('now', '-79 hours')
                GROUP BY ts
                ORDER BY ts ASC
            """).fetchall()
            result["hourly"] = [{"ts": r["ts"], "kwh": round(r["kwh"], 3)} for r in _rows]

            # Daily totals: last 7 days
            _daily = _db.execute("""
                SELECT
                  date(datetime(interval_ts, '-7 hours')) as local_date,
                  SUM(kwh)  as total_kwh,
                  MAX(kwh)  as peak_kwh,
                  COUNT(*)  as hours
                FROM pge_energy
                WHERE kwh > 0 AND duration_s = 3600
                GROUP BY local_date
                ORDER BY local_date DESC
                LIMIT 7
            """).fetchall()
            result["daily"] = [
                {"date": r["local_date"], "total_kwh": round(r["total_kwh"], 2),
                 "peak_kwh": round(r["peak_kwh"], 3), "hours": r["hours"]}
                for r in _daily
            ]
            _db.close()
        else:
            # ── JSON file fallback (GitHub Actions / cloud) ───────────────────
            # pge_poller.py writes data/pge_hourly.json and pushes to GitHub
            # every 30 min, so this file is available when Actions checks out.
            _json_path = os.path.join(PROJECT_DIR, "data", "pge_hourly.json")
            if os.path.exists(_json_path):
                import json as _json
                with open(_json_path) as _f:
                    _pge = _json.load(_f)
                result["hourly"]          = _pge.get("hourly", [])
                result["daily"]           = _pge.get("daily", [])
                result["latest_kwh"]      = _pge.get("latest_kwh")
                result["data_through"]    = _pge.get("data_through")
                result["avg_per_hour"]    = _pge.get("avg_per_hour")
                result["evening_peak_kwh"]= _pge.get("evening_peak_kwh")
                result["_source"]         = "pge_hourly.json"
                # Skip the shared summary stats block below (already computed)
                return result

        # ── Summary stats (shared) ────────────────────────────────────────────
        if result["hourly"]:
            result["latest_kwh"]   = result["hourly"][-1]["kwh"]
            result["data_through"] = result["hourly"][-1]["ts"]
            all_kwh = [r["kwh"] for r in result["hourly"]]
            result["avg_per_hour"] = round(sum(all_kwh) / len(all_kwh), 2)
            evening = [r["kwh"] for r in result["hourly"]
                       if 17 <= int(r["ts"][11:13]) <= 22]
            if evening:
                result["evening_peak_kwh"] = round(max(evening), 2)
    except Exception as _e:
        result["_error"] = str(_e)
    return result


def main():
    data = build_data()
    with open(OUTPUT_PATH, "w") as f:
        json.dump(data, f, indent=2, default=str)

    n_projects    = len(data["projects"])
    n_therm       = len(data["thermostat"]["latest"])
    n_elec_months = len(data["energy"]["monthly_electric"])
    n_obs         = len(data["intelligence"]["observations"])
    n_insights    = len(data["intelligence"]["insights"])
    print(f"✓ dashboard_data.json written  ({n_projects} projects, {n_therm} thermostats, {n_elec_months} months energy, {n_obs} observations, {n_insights} insights)")


if __name__ == "__main__":
    main()
