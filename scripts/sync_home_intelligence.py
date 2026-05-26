#!/usr/bin/env python3
"""
sync_home_intelligence.py — Sync local home_intelligence.db → Supabase
=======================================================================
Reads recent observations, insights, and builds a home_state snapshot,
then upserts into Supabase tables:
  - home_observations  (last 50 camera/sensor observations)
  - home_insights      (open/unacted insights)
  - home_state         (single-row current state)

Run manually:
    python3 scripts/sync_home_intelligence.py

Or via LaunchAgent every 3 minutes.
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DB_PATH     = os.path.expanduser("~/.openclaw/home_intelligence.db")

sys.path.insert(0, SCRIPT_DIR)
from supabase_client import get_client


def ts_to_iso(ts):
    """Convert unix timestamp (int) to ISO8601 string."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def fetch_observations(db: sqlite3.Connection, limit=50):
    """Fetch last N observations, excluding blob columns."""
    cur = db.execute("""
        SELECT id, timestamp, source, source_type, location, summary, confidence, model_version
        FROM observations
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    cols = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        r["timestamp"] = ts_to_iso(r["timestamp"])
        # Fetch entities for this observation
        ecur = db.execute("""
            SELECT entity_type, entity_name, entity_state, confidence
            FROM observation_entities
            WHERE observation_id = ?
        """, (r["id"],))
        r["entities"] = [dict(zip([d[0] for d in ecur.description], erow)) for erow in ecur.fetchall()]
        rows.append(r)
    return rows


def fetch_insights(db: sqlite3.Connection, limit=20):
    """Fetch open (unacted) insights."""
    cur = db.execute("""
        SELECT id, timestamp, insight_type, severity, summary, acted_on_at
        FROM insights
        WHERE acted_on_at IS NULL OR acted_on_at = 0
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    cols = [d[0] for d in cur.description]
    rows = []
    for row in cur.fetchall():
        r = dict(zip(cols, row))
        r["timestamp"]   = ts_to_iso(r["timestamp"])
        r["acted_on_at"] = ts_to_iso(r["acted_on_at"]) if r["acted_on_at"] else None
        rows.append(r)
    return rows


def build_home_state(db: sqlite3.Connection):
    """
    Derive current home state from recent observations.
    Looks at last ~30 minutes of signal-aggregator data.
    """
    cutoff = int(time.time()) - 1800  # 30 min window

    # Who's home — from unifi:presence
    who_home = []
    cur = db.execute("""
        SELECT summary FROM observations
        WHERE source = 'unifi:presence' AND timestamp > ?
        ORDER BY timestamp DESC LIMIT 1
    """, (cutoff,))
    row = cur.fetchone()
    if row:
        summary = row[0] or ""
        # Format 1: "Home: Miller, Penelope." → extract names
        if "Home:" in summary:
            names_part = summary.split("Home:", 1)[1].strip().rstrip(".")
            if names_part and names_part.lower() not in ("", "nobody", "none"):
                who_home = [n.strip() for n in names_part.split(",") if n.strip()]
        # Format 2: "11 mobile devices home. Cameras recently show: Miller, Penelope."
        elif "Cameras recently show:" in summary:
            names_part = summary.split("Cameras recently show:", 1)[1].strip().rstrip(".")
            if names_part and names_part.lower() not in ("", "nobody", "none"):
                who_home = [n.strip() for n in names_part.split(",") if n.strip()]
        # Format 3: "House appears empty" → nobody home
        elif "empty" in summary.lower() or "no mobile" in summary.lower():
            who_home = []

    # Supplement who_home with names from recent vision observations (entity table)
    KNOWN_FAMILY = {"Steve", "Roxanne", "Miller", "Penelope"}
    if not who_home:
        vision_cutoff = int(time.time()) - 3600  # last hour
        cur = db.execute("""
            SELECT DISTINCT oe.entity_name
            FROM observation_entities oe
            JOIN observations o ON oe.observation_id = o.id
            WHERE oe.entity_type = 'person'
              AND o.source_type = 'vision'
              AND o.timestamp > ?
              AND oe.entity_name != 'unknown'
        """, (vision_cutoff,))
        vision_names = [r[0] for r in cur.fetchall() if r[0] in KNOWN_FAMILY]
        if vision_names:
            who_home = sorted(set(vision_names))

    # Active lights — from ha:lights
    lights_on = []
    cur = db.execute("""
        SELECT summary FROM observations
        WHERE source = 'ha:lights' AND timestamp > ?
        ORDER BY timestamp DESC LIMIT 1
    """, (cutoff,))
    row = cur.fetchone()
    if row:
        summary = row[0] or ""
        if "Lights on:" in summary:
            lights_part = summary.split("Lights on:", 1)[1].strip().rstrip(".")
            if lights_part and lights_part.lower() != "none":
                lights_on = [l.strip() for l in lights_part.split(",") if l.strip()]

    # Music / audio — from ha:audio
    music_playing = []
    cur = db.execute("""
        SELECT summary FROM observations
        WHERE source = 'ha:audio' AND timestamp > ?
        ORDER BY timestamp DESC LIMIT 1
    """, (cutoff,))
    row = cur.fetchone()
    if row:
        summary = row[0] or ""
        if "playing" in summary.lower():
            music_playing = [summary]

    # Active rooms — union of lights + recent camera activity
    active_rooms = set(lights_on)
    cur = db.execute("""
        SELECT DISTINCT location FROM observations
        WHERE source_type = 'vision' AND timestamp > ?
        AND location NOT IN ('home', 'unknown', '')
    """, (cutoff,))
    for row in cur.fetchall():
        if row[0]:
            active_rooms.add(row[0])

    # Last motion per camera location
    cur = db.execute("""
        SELECT location, MAX(timestamp) as last_ts
        FROM observations
        WHERE source_type = 'vision'
        GROUP BY location
    """)
    last_motion = {}
    for loc, ts in cur.fetchall():
        if loc:
            last_motion[loc] = ts_to_iso(ts)

    now_iso = datetime.now(tz=timezone.utc).isoformat()

    return {
        "id":           "current",
        "who_is_home":  who_home,
        "active_rooms": sorted(active_rooms),
        "lights_on":    lights_on,
        "music_playing": music_playing,
        "last_motion":  last_motion,
        "last_updated": now_iso,
    }


def ensure_tables(sb):
    """
    Try a lightweight select on each table to see if it exists.
    Returns dict of {table: exists_bool}.
    Print guidance if missing.
    """
    tables = ["home_observations", "home_insights", "home_state"]
    status = {}
    for t in tables:
        try:
            sb.select(t, query="id", limit=1)
            status[t] = True
        except RuntimeError as e:
            if "42P01" in str(e) or "does not exist" in str(e) or "relation" in str(e).lower():
                status[t] = False
            else:
                status[t] = True  # Other error — assume exists, let upsert fail
    return status


def main():
    if not os.path.exists(DB_PATH):
        print(f"✗ home_intelligence.db not found at {DB_PATH}")
        sys.exit(1)

    db = sqlite3.connect(DB_PATH)
    sb = get_client()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting home intelligence sync...")

    # Check tables exist
    table_status = ensure_tables(sb)
    missing = [t for t, ok in table_status.items() if not ok]
    if missing:
        print(f"\n⚠️  Missing Supabase tables: {', '.join(missing)}")
        sql_path = os.path.join(PROJECT_DIR, "create_tables.sql")
        print(f"   Run the SQL in {sql_path} in your Supabase dashboard (SQL Editor).\n")
        # Still try to upsert — if table creation happened since check, it'll work

    # Fetch data
    observations = fetch_observations(db, limit=50)
    insights     = fetch_insights(db, limit=20)
    home_state   = build_home_state(db)
    db.close()

    print(f"  Fetched: {len(observations)} observations, {len(insights)} insights")
    print(f"  Home state: who_home={home_state['who_is_home']}, lights={home_state['lights_on']}")

    errors = []

    # Upsert observations
    if observations:
        try:
            # Flatten entities to JSON string for Supabase
            obs_rows = []
            for o in observations:
                row = dict(o)
                row["entities"] = json.dumps(row.get("entities", []))
                obs_rows.append(row)
            sb.upsert("home_observations", obs_rows)
            print(f"  ✓ Upserted {len(obs_rows)} observations")
        except Exception as e:
            errors.append(f"home_observations: {e}")
            print(f"  ✗ home_observations: {e}")

    # Upsert insights
    if insights:
        try:
            sb.upsert("home_insights", insights)
            print(f"  ✓ Upserted {len(insights)} insights")
        except Exception as e:
            errors.append(f"home_insights: {e}")
            print(f"  ✗ home_insights: {e}")

    # Upsert home_state (single row keyed on id='current')
    try:
        state_row = dict(home_state)
        state_row["who_is_home"]   = json.dumps(state_row.get("who_is_home", []))
        state_row["active_rooms"]  = json.dumps(state_row.get("active_rooms", []))
        state_row["lights_on"]     = json.dumps(state_row.get("lights_on", []))
        state_row["music_playing"] = json.dumps(state_row.get("music_playing", []))
        state_row["last_motion"]   = json.dumps(state_row.get("last_motion", {}))
        sb.upsert("home_state", [state_row])
        print(f"  ✓ Upserted home_state")
    except Exception as e:
        errors.append(f"home_state: {e}")
        print(f"  ✗ home_state: {e}")

    if errors:
        print(f"\n⚠️  Completed with {len(errors)} error(s). Check create_tables.sql if tables are missing.")
        sys.exit(1)
    else:
        print(f"  ✓ Sync complete")


if __name__ == "__main__":
    main()
