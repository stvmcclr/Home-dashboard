#!/usr/bin/env python3
"""
Nest Thermostat Monitor
Polls both thermostats via Google SDM API and logs to CSV.
Handles token refresh automatically.
"""

import json
import csv
import os
import urllib.request
import urllib.parse
from datetime import datetime

# ── Credentials ──────────────────────────────────────────────────────────────
CLIENT_ID     = "814260674634-2susvqkeoib1j2pmpavhjtg5ljhbtc8b.apps.googleusercontent.com"
CLIENT_SECRET = "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"
REFRESH_TOKEN = "1//06IZkBBC0zsxOCgYIARAAGAYSNwF-L9IrYgAei1Aw0yPayu5mOBjHiVJKbC47WGn5kAQeRIRPreZEIzFh71-7QFg3G8_lV1mNpLo"
PROJECT_ID    = "95909dd8-c49a-4eb0-9c30-ab8ee43a123c"

# ── Config ────────────────────────────────────────────────────────────────────
LOG_FILE = os.path.join(os.path.dirname(__file__), "nest_log.csv")
CSV_HEADERS = [
    "timestamp", "location",
    "temp_f", "humidity_pct",
    "mode", "hvac_status",
    "heat_setpoint_f", "cool_setpoint_f",
    "eco_mode", "fan_mode", "connectivity"
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def c_to_f(c):
    """Convert Celsius to Fahrenheit, rounded to 1 decimal."""
    return round(c * 9 / 5 + 32, 1) if c is not None else None

def get_access_token():
    """Exchange refresh token for a fresh access token."""
    data = urllib.parse.urlencode({
        "client_id":     CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": REFRESH_TOKEN,
        "grant_type":    "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["access_token"]

def get_devices(access_token):
    """Fetch all devices from the SDM API."""
    url = f"https://smartdevicemanagement.googleapis.com/v1/enterprises/{PROJECT_ID}/devices"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())["devices"]

def parse_thermostat(device):
    """Extract a flat dict of thermostat readings from a device object."""
    t = device["traits"]
    location = device["parentRelations"][0]["displayName"] if device.get("parentRelations") else "Unknown"

    temp_c  = t.get("sdm.devices.traits.Temperature", {}).get("ambientTemperatureCelsius")
    humidity = t.get("sdm.devices.traits.Humidity", {}).get("ambientHumidityPercent")
    mode    = t.get("sdm.devices.traits.ThermostatMode", {}).get("mode")
    hvac    = t.get("sdm.devices.traits.ThermostatHvac", {}).get("status")
    eco     = t.get("sdm.devices.traits.ThermostatEco", {}).get("mode")
    fan     = t.get("sdm.devices.traits.Fan", {}).get("timerMode")
    conn    = t.get("sdm.devices.traits.Connectivity", {}).get("status")

    setpoints = t.get("sdm.devices.traits.ThermostatTemperatureSetpoint", {})
    heat_sp_c = setpoints.get("heatCelsius")
    cool_sp_c = setpoints.get("coolCelsius")

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
        "connectivity":    conn,
    }

def append_to_csv(rows):
    """Append rows to the log CSV, creating it with headers if needed."""
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Polling Nest thermostats...")

    token   = get_access_token()
    devices = get_devices(token)

    rows = []
    for device in devices:
        if "THERMOSTAT" not in device.get("type", ""):
            continue
        row = parse_thermostat(device)
        rows.append(row)
        print(f"  {row['location']:12s} | {row['temp_f']}°F | {row['humidity_pct']}% RH | "
              f"Mode: {row['mode']:8s} | HVAC: {row['hvac_status']}")

    append_to_csv(rows)
    print(f"  ✓ Logged {len(rows)} thermostats to {LOG_FILE}")

if __name__ == "__main__":
    main()
