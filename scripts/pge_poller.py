#!/usr/bin/env python3
"""
pge_poller.py — PG&E Share My Data API poller
==============================================
Fetches electric and gas interval data via the Green Button Connect (ESPI)
API and writes daily totals into the energy_data table.

SETUP REQUIRED (one-time, done by you):
----------------------------------------
1. Get an X.509 SSL certificate from a recognized CA (DigiCert, GlobalSign,
   etc.). A cheap domain cert (~$10-50/yr from Namecheap/Sectigo works fine.
   Self-signed certs are NOT accepted by PGE.)

2. Register at https://sharemydata.pge.com as a "Self Access" user.
   - Upload your certificate's public key
   - PGE will email you a Client ID and Client Secret
   - You'll also need to complete their API Connectivity Test

3. Authorize your own account:
   - Log in to pge.com, go to Energy Usage > Share My Data
   - Authorize your third-party app (the one you registered)
   - This gives you a Subscription ID and Resource IDs

4. Add these to config.json under a "pge_api" key:
   {
     "pge_api": {
       "client_id": "your_client_id",
       "client_secret": "your_client_secret",
       "cert_path": "/path/to/your/cert.pem",
       "key_path": "/path/to/your/key.pem",
       "subscription_id": "your_subscription_id",
       "resource_id_electric": "your_electric_resource_id",
       "resource_id_gas": "your_gas_resource_id"
     }
   }

5. Run once manually to test:
       python3 scripts/pge_poller.py --test

6. It will then be called automatically by nest_monitor.py (daily is enough
   since PGE data lags by ~24h anyway).

DATA FLOW:
   PGE API → ESPI XML → parse to daily totals → energy_data table
   → generate_dashboard_data.py → dashboard_data.json

API REFERENCE:
   Base URL: https://api.pge.com/GreenButtonConnect/espi/1_1/resource
   Auth:     https://api.pge.com/datacustodian/oauth/v2/token
   Docs:     https://www.pge.com/en/save-energy-and-money/energy-saving-programs/smartmeter/third-party-companies.html
"""

import json
import os
import sys
import sqlite3
import urllib.request
import urllib.parse
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(PROJECT_DIR, "config.json")
DB_PATH     = os.path.join(PROJECT_DIR, "home_projects.db")

# ESPI XML namespace
ESPI_NS = {
    "espi": "http://naesb.org/espi",
    "atom": "http://www.w3.org/2005/Atom",
}

# ── Config loading ────────────────────────────────────────────────────────────

def load_pge_config():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    pge = cfg.get("pge_api")
    if not pge:
        raise RuntimeError(
            "No 'pge_api' section in config.json. "
            "See the setup instructions at the top of this file."
        )
    required = ["client_id", "client_secret", "cert_path", "key_path",
                "subscription_id", "resource_id_electric"]
    missing = [k for k in required if not pge.get(k)]
    if missing:
        raise RuntimeError(f"Missing pge_api config keys: {missing}")
    return pge


# ── SSL context (mutual TLS) ───────────────────────────────────────────────────

def make_ssl_context(cert_path, key_path):
    """Build an SSL context with the client certificate for mutual TLS."""
    ctx = ssl.create_default_context()
    ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)
    return ctx


# ── OAuth token ───────────────────────────────────────────────────────────────

def get_access_token(cfg):
    """Exchange client credentials for a bearer token."""
    token_url = "https://api.pge.com/datacustodian/oauth/v2/token"
    data = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     cfg["client_id"],
        "client_secret": cfg["client_secret"],
    }).encode()
    ctx = make_ssl_context(cfg["cert_path"], cfg["key_path"])
    req = urllib.request.Request(token_url, data=data, method="POST")
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read())["access_token"]


# ── Fetch interval data ───────────────────────────────────────────────────────

def fetch_interval_data(cfg, ssl_ctx, access_token, resource_id, start_dt, end_dt):
    """
    Fetch ESPI interval data for a resource between start_dt and end_dt.

    Returns raw XML bytes.
    """
    base = "https://api.pge.com/GreenButtonConnect/espi/1_1/resource"
    start_epoch = int(start_dt.timestamp())
    end_epoch   = int(end_dt.timestamp())

    url = (
        f"{base}/Subscription/{cfg['subscription_id']}"
        f"/UsagePoint/{resource_id}/MeterReading/IntervalBlock"
        f"?published-min={start_epoch}&published-max={end_epoch}"
    )

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept":        "application/atom+xml",
        }
    )
    with urllib.request.urlopen(req, context=ssl_ctx) as resp:
        return resp.read()


# ── ESPI XML parsing ──────────────────────────────────────────────────────────

def parse_espi_to_daily(xml_bytes, utility_type="electric"):
    """
    Parse ESPI XML interval data into daily totals.

    Returns list of dicts: {date, utility_type, kwh_used OR therms_used, cost}

    ESPI stores readings as interval blocks with epoch timestamps and values
    in the base unit (Wh for electric, CCF or therms for gas). We aggregate
    to daily totals.
    """
    root = ET.fromstring(xml_bytes)
    daily = {}  # date_str → {"value": float, "cost": float}

    for entry in root.findall(".//atom:entry", ESPI_NS):
        block = entry.find(".//espi:IntervalBlock", ESPI_NS)
        if block is None:
            continue

        for reading in block.findall("espi:IntervalReading", ESPI_NS):
            # Timestamp
            time_period = reading.find("espi:timePeriod", ESPI_NS)
            if time_period is None:
                continue
            start_epoch = int(time_period.find("espi:start", ESPI_NS).text)
            dt = datetime.utcfromtimestamp(start_epoch)
            date_str = dt.strftime("%Y-%m-%d")

            # Value (in Wh for electric; convert to kWh)
            value_el = reading.find("espi:value", ESPI_NS)
            if value_el is None:
                continue
            raw_value = int(value_el.text)

            # Power of 10 multiplier from ReadingType (usually -3 for Wh→kWh)
            # We look for it on the parent IntervalBlock's ReadingType link.
            # Simplified: assume Wh for electric (divide by 1000), therms as-is.
            if utility_type == "electric":
                value = raw_value / 1000.0  # Wh → kWh
            else:
                value = raw_value / 100000.0  # typical CCF scaling → therms

            # Cost (in cents, if present)
            cost_el = reading.find("espi:cost", ESPI_NS)
            cost = (int(cost_el.text) / 100000.0) if cost_el is not None else 0.0

            if date_str not in daily:
                daily[date_str] = {"value": 0.0, "cost": 0.0}
            daily[date_str]["value"] += value
            daily[date_str]["cost"]  += cost

    results = []
    for date_str, totals in sorted(daily.items()):
        row = {
            "date":         date_str,
            "utility_type": utility_type,
            "cost":         round(totals["cost"], 4),
        }
        if utility_type == "electric":
            row["kwh_used"]    = round(totals["value"], 3)
            row["therms_used"] = None
        else:
            row["kwh_used"]    = None
            row["therms_used"] = round(totals["value"], 3)
        results.append(row)
    return results


# ── DB write ──────────────────────────────────────────────────────────────────

def upsert_energy_rows(rows):
    """
    Insert new daily energy rows, skipping dates already in the DB.
    Returns count of new rows inserted.
    """
    conn = sqlite3.connect(DB_PATH)
    existing = set(
        f"{r[0]}:{r[1]}" for r in conn.execute(
            "SELECT date, utility_type FROM energy_data"
        ).fetchall()
    )

    new_rows = [r for r in rows if f"{r['date']}:{r['utility_type']}" not in existing]

    conn.executemany("""
        INSERT INTO energy_data
            (date, provider, utility_type, kwh_used, therms_used, cost, granularity, notes)
        VALUES
            (:date, 'PG&E', :utility_type, :kwh_used, :therms_used, :cost, 'daily', 'PGE API')
    """, new_rows)
    conn.commit()
    conn.close()
    return len(new_rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def poll(days_back=7):
    """
    Fetch the last N days of data from PGE and write to DB.
    Default 7 days covers typical PGE data latency (~24-48h lag).
    """
    cfg    = load_pge_config()
    ctx    = make_ssl_context(cfg["cert_path"], cfg["key_path"])
    token  = get_access_token(cfg)

    end_dt   = datetime.now()
    start_dt = end_dt - timedelta(days=days_back)

    total_new = 0

    # Electric
    print(f"  Fetching electric data ({days_back}d)...")
    xml_bytes = fetch_interval_data(cfg, ctx, token, cfg["resource_id_electric"], start_dt, end_dt)
    rows = parse_espi_to_daily(xml_bytes, utility_type="electric")
    n = upsert_energy_rows(rows)
    print(f"    → {n} new electric days inserted ({len(rows)} fetched)")
    total_new += n

    # Gas (optional — not all accounts have a gas resource ID)
    if cfg.get("resource_id_gas"):
        print(f"  Fetching gas data ({days_back}d)...")
        xml_bytes = fetch_interval_data(cfg, ctx, token, cfg["resource_id_gas"], start_dt, end_dt)
        rows = parse_espi_to_daily(xml_bytes, utility_type="gas")
        n = upsert_energy_rows(rows)
        print(f"    → {n} new gas days inserted ({len(rows)} fetched)")
        total_new += n

    return total_new


def test_connection():
    """Quick connectivity test — just fetches an access token and prints it."""
    print("Testing PGE API connection...")
    cfg   = load_pge_config()
    token = get_access_token(cfg)
    print(f"  ✓ Access token obtained: {token[:20]}...")
    print("  Connection successful. PGE registration is working.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PGE Share My Data poller")
    parser.add_argument("--test",     action="store_true", help="Test connection only (no DB writes)")
    parser.add_argument("--days",     type=int, default=7, help="Days of history to fetch (default: 7)")
    parser.add_argument("--backfill", type=int, default=None, help="Backfill N days of history")
    args = parser.parse_args()

    if args.test:
        test_connection()
        return

    days = args.backfill or args.days
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Polling PGE Share My Data ({days}d lookback)...")

    try:
        n = poll(days_back=days)
        print(f"  ✓ {n} new rows written to energy_data")
    except RuntimeError as e:
        print(f"  ✗ Config error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"  ✗ API error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
