#!/usr/bin/env python3
"""
import_pge.py — One-time PGE Green Button CSV importer
=======================================================
Reads the two PGE CSV exports from the data/ folder and imports them
into the energy_data table as daily totals.

  Electric: aggregates hourly kWh to daily totals
  Gas:      already daily therms

Run once from the project root:
    python3 scripts/import_pge.py

Safe to re-run: existing rows for the same date+type are skipped (no duplicates).
"""

import csv
import sqlite3
import os
import glob
from datetime import datetime

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR    = os.path.join(PROJECT_DIR, "data")
DB_PATH     = os.path.join(PROJECT_DIR, "home_projects.db")


def find_csv(pattern):
    matches = glob.glob(os.path.join(DATA_DIR, pattern))
    return matches[0] if matches else None


def parse_electric(filepath):
    """Parse hourly electric CSV → daily totals {date: (kwh, cost)}"""
    daily = {}
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        # Skip header rows until we hit the column header row
        for row in reader:
            if row and row[0].strip() == "TYPE":
                break
        for row in reader:
            if len(row) < 6:
                continue
            date_str = row[1].strip()
            try:
                kwh  = float(row[4].strip())
                cost = float(row[5].strip().replace("$", "").replace(",", ""))
            except (ValueError, IndexError):
                continue
            if date_str not in daily:
                daily[date_str] = [0.0, 0.0]
            daily[date_str][0] += kwh
            daily[date_str][1] += cost
    return daily


def parse_gas(filepath):
    """Parse daily gas CSV → {date: (therms, cost)}"""
    daily = {}
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if row and row[0].strip() == "TYPE":
                break
        for row in reader:
            if len(row) < 6:
                continue
            date_str = row[1].strip()
            try:
                therms = float(row[4].strip())
                cost   = float(row[5].strip().replace("$", "").replace(",", ""))
            except (ValueError, IndexError):
                continue
            daily[date_str] = (therms, cost)
    return daily


def import_to_db(electric_daily, gas_daily):
    conn = sqlite3.connect(DB_PATH)

    # Get existing dates to avoid duplicates
    existing_electric = set(r[0] for r in conn.execute(
        "SELECT date FROM energy_data WHERE utility_type='electric'"))
    existing_gas = set(r[0] for r in conn.execute(
        "SELECT date FROM energy_data WHERE utility_type='gas'"))

    elec_rows = []
    for date_str, (kwh, cost) in sorted(electric_daily.items()):
        if date_str not in existing_electric:
            elec_rows.append((date_str, "PG&E", "electric", round(kwh, 3), None, round(cost, 2), "daily", "PGE Green Button import"))

    gas_rows = []
    for date_str, (therms, cost) in sorted(gas_daily.items()):
        if date_str not in existing_gas:
            gas_rows.append((date_str, "PG&E", "gas", None, round(therms, 3), round(cost, 2), "daily", "PGE Green Button import"))

    conn.executemany(
        "INSERT INTO energy_data (date,provider,utility_type,kwh_used,therms_used,cost,granularity,notes) VALUES (?,?,?,?,?,?,?,?)",
        elec_rows
    )
    conn.executemany(
        "INSERT INTO energy_data (date,provider,utility_type,kwh_used,therms_used,cost,granularity,notes) VALUES (?,?,?,?,?,?,?,?)",
        gas_rows
    )
    conn.commit()

    print(f"  Electric: {len(elec_rows)} new daily rows imported ({len(existing_electric)} already existed)")
    print(f"  Gas:      {len(gas_rows)} new daily rows imported ({len(existing_gas)} already existed)")

    # Summary
    elec_total = conn.execute("SELECT SUM(kwh_used), SUM(cost) FROM energy_data WHERE utility_type='electric'").fetchone()
    gas_total  = conn.execute("SELECT SUM(therms_used), SUM(cost) FROM energy_data WHERE utility_type='gas'").fetchone()
    print(f"\n  Total electric in DB: {elec_total[0]:,.0f} kWh / ${elec_total[1]:,.2f}")
    print(f"  Total gas in DB:      {gas_total[0]:,.0f} therms / ${gas_total[1]:,.2f}")
    conn.close()


def main():
    print("Importing PGE data...")

    elec_file = find_csv("pge_electric*.csv")
    gas_file  = find_csv("pge_natural_gas*.csv")

    if not elec_file:
        print("  ✗ Electric CSV not found in data/")
        return
    if not gas_file:
        print("  ✗ Gas CSV not found in data/")
        return

    print(f"  Electric: {os.path.basename(elec_file)}")
    print(f"  Gas:      {os.path.basename(gas_file)}")

    electric_daily = parse_electric(elec_file)
    gas_daily      = parse_gas(gas_file)

    print(f"  Parsed {len(electric_daily)} electric days, {len(gas_daily)} gas days")

    import_to_db(electric_daily, gas_daily)
    print("\n✓ PGE import complete")


if __name__ == "__main__":
    main()
