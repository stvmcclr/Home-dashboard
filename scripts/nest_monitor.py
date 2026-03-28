#!/usr/bin/env python3
"""
nest_monitor.py — Nest Thermostat Poller
=========================================
Polls both thermostats via Google SDM API, writes readings to SQLite,
then regenerates the dashboard data JSON.

Run directly:
    python3 scripts/nest_monitor.py

Called automatically every 15 min by launchd.
"""

import json
import os
import sys
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime

# ── Locate config relative to this script's parent (project root) ────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

NEST_CFG     = CONFIG["nest"]
DB_PATH      = os.path.join(PROJECT_DIR, CONFIG.get("db_path", "home_projects.db"))
REGEN_SCRIPT  = os.path.join(SCRIPT_DIR, "generate_dashboard_data.py")
PGE_SCRIPT    = os.path.join(SCRIPT_DIR, "pge_poller.py")
NETLIFY_CFG   = CONFIG.get("netlify", {})
LAST_PGE_POLL_FILE = os.path.join(PROJECT_DIR, "logs", ".last_pge_poll")

sys.path.insert(0, SCRIPT_DIR)
from supabase_client import get_client


# ── Helpers ───────────────────────────────────────────────────────────────────
def c_to_f(c):
    return round(c * 9 / 5 + 32, 1) if c is not None else None


def get_access_token():
    data = urllib.parse.urlencode({
        "client_id":     NEST_CFG["client_id"],
        "client_secret": NEST_CFG["client_secret"],
        "refresh_token": NEST_CFG["refresh_token"],
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]


def get_devices(access_token):
    pid = NEST_CFG["project_id"]
    url = f"https://smartdevicemanagement.googleapis.com/v1/enterprises/{pid}/devices"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["devices"]


def parse_thermostat(device):
    t = device["traits"]
    location = (device.get("parentRelations") or [{}])[0].get("displayName", "Unknown")

    temp_c   = t.get("sdm.devices.traits.Temperature", {}).get("ambientTemperatureCelsius")
    humidity = t.get("sdm.devices.traits.Humidity", {}).get("ambientHumidityPercent")
    mode     = t.get("sdm.devices.traits.ThermostatMode", {}).get("mode")
    hvac     = t.get("sdm.devices.traits.ThermostatHvac", {}).get("status")
    eco      = t.get("sdm.devices.traits.ThermostatEco", {}).get("mode")
    fan      = t.get("sdm.devices.traits.Fan", {}).get("timerMode")
    conn_status = t.get("sdm.devices.traits.Connectivity", {}).get("status")

    setpoints  = t.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})
    heat_sp_c  = setpoints.get("heatCelsius")
    cool_sp_c  = setpoints.get("coolCelsius")

    return {
        "timestamp":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "location":        location,
        "temp_f":          c_to_f(temp_c),
        "humidity_pct":    humidity,
        "mode":            mode,
        "hvac_status":     hvac,
        "heat_setpoint_f": c_to_f(heat_sp_c),
        "cool_setpoint_f": c_to_f(cool_sp_c),
        "eco_mode":        eco,
        "fan_mode":        fan,
        "connectivity":    conn_status,
    }


def write_to_db(rows):
    sb = get_client()
    sb.insert("thermostat_readings", rows)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Polling Nest thermostats...")

    try:
        token   = get_access_token()
        devices = get_devices(token)
    except Exception as e:
        print(f"  ✗ API error: {e}", file=sys.stderr)
        sys.exit(1)

    rows = []
    for device in devices:
        if "THERMOSTAT" not in device.get("type", ""):
            continue
        row = parse_thermostat(device)
        rows.append(row)
        heat = f" heat→{row['heat_setpoint_f']}°F" if row.get("heat_setpoint_f") else ""
        cool = f" cool→{row['cool_setpoint_f']}°F" if row.get("cool_setpoint_f") else ""
        print(f"  {row['location']:12s} | {row['temp_f']}°F | {row['humidity_pct']}% RH | "
              f"Mode: {row['mode']:8s} | HVAC: {row['hvac_status']}{heat}{cool}")

    if rows:
        write_to_db(rows)
        print(f"  ✓ Saved {len(rows)} readings to DB")

    # PGE poller — run once per day if credentials are configured
    _maybe_poll_pge()

    # Regenerate dashboard data
    print(f"  Regenerating dashboard data...")
    try:
        subprocess.run([sys.executable, REGEN_SCRIPT], check=True, capture_output=True)
        print(f"  ✓ dashboard_data.json updated")
        _deploy_to_netlify()
    except subprocess.CalledProcessError as e:
        print(f"  ✗ Dashboard regen failed: {e.stderr.decode()}", file=sys.stderr)


def _deploy_to_netlify():
    """Push updated dashboard_data.json to Netlify (if configured and CLI is available)."""
    if not NETLIFY_CFG.get("enabled"):
        return

    site_id = NETLIFY_CFG.get("site_id", "")
    netlify_bin = NETLIFY_CFG.get("cli_path", "netlify")

    try:
        result = subprocess.run(
            [netlify_bin, "deploy", "--prod", "--dir", PROJECT_DIR,
             "--site", site_id, "--message", f"Auto-deploy {datetime.now().strftime('%Y-%m-%d %H:%M')}"],
            check=True, capture_output=True, text=True, cwd=PROJECT_DIR
        )
        print(f"  ✓ Netlify deploy complete")
    except FileNotFoundError:
        print(f"  ✗ Netlify CLI not found — run: npm install -g netlify-cli", file=sys.stderr)
    except subprocess.CalledProcessError as e:
        print(f"  ✗ Netlify deploy failed: {e.stderr}", file=sys.stderr)


def _maybe_poll_pge():
    """Run pge_poller.py at most once per day, and only if pge_api is configured."""
    if not CONFIG.get("pge_api"):
        return  # PGE not configured yet

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        if os.path.exists(LAST_PGE_POLL_FILE):
            with open(LAST_PGE_POLL_FILE) as f:
                if f.read().strip() == today:
                    return  # Already ran today
    except OSError:
        pass

    print(f"  Running PGE poller (daily)...")
    try:
        result = subprocess.run(
            [sys.executable, PGE_SCRIPT, "--days", "3"],
            check=True, capture_output=True, text=True
        )
        print(f"  ✓ PGE poll complete")
        os.makedirs(os.path.dirname(LAST_PGE_POLL_FILE), exist_ok=True)
        with open(LAST_PGE_POLL_FILE, "w") as f:
            f.write(today)
    except subprocess.CalledProcessError as e:
        print(f"  ✗ PGE poll failed: {e.stderr}", file=sys.stderr)


if __name__ == "__main__":
    main()
