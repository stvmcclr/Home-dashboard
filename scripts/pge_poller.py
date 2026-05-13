#!/usr/bin/env python3
"""
PGE Data Poller — polls Netlify Blobs for PGE callbacks, fetches actual
ESPI data from PGE API, stores energy usage in home_intelligence.db

PGE async flow:
  1. We (or PGE) trigger a Bulk data request → PGE queues it
  2. PGE POSTs a BatchList XML to our callback (roccoorsini.com/pge-notify)
  3. BatchList contains resource URLs for the actual ESPI data
  4. We fetch each resource URL using mTLS + OAuth Bearer token
  5. Parse ESPI IntervalBlock XML → store in pge_energy table

Runs every 30 min via launchd
"""

import os
import sys
import json
import base64
import sqlite3
import requests
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, date

# ── Config ────────────────────────────────────────────────────────────────────
DB          = os.path.expanduser("~/.openclaw/home_intelligence.db")
FETCH_URL   = "https://roccoorsini.com/.netlify/functions/pge-data"
FETCH_TOKEN = "pge-bd4d24e25d4e26078de87d96"
STATE_FILE  = os.path.expanduser("~/Desktop/pge_integration/poller_state.json")
LOG_FILE    = os.path.expanduser("~/.openclaw/logs/pge_poller.log")

# PGE OAuth2 / mTLS
CLIENT_ID     = "9a7269eca1d4400f80c043303c8ad145"
CLIENT_SECRET = "f6942d7c8a9c4ac8aa0653d5b092faee"
TOKEN_URL     = "https://api.pge.com/datacustodian/oauth/v2/token"

CERT_DIR    = os.path.expanduser("~/Desktop/pge_integration/certs")
CA_BUNDLE   = os.path.join(CERT_DIR, "pge_ca_bundle.pem")
CLIENT_CERT = os.path.expanduser("~/Desktop/pge_integration/roccoorsini.crt")
CLIENT_KEY  = os.path.expanduser("~/Desktop/pge_integration/roccoorsini.key")
MTLS        = (CLIENT_CERT, CLIENT_KEY)

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── State ─────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_key": None, "last_processed": None}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# ── Step 1: Fetch latest callback from Netlify Blobs ─────────────────────────
def fetch_latest_callback():
    try:
        r = requests.get(FETCH_URL, params={"token": FETCH_TOKEN}, timeout=30)
        if r.status_code == 200:
            return r.json()
        elif r.status_code == 404:
            log("No callback yet from PGE.")
            return None
        else:
            log(f"Fetch error: {r.status_code} {r.text[:100]}")
            return None
    except Exception as e:
        log(f"Fetch exception: {e}")
        return None

# ── Step 2: Parse BatchList XML to get resource URLs ─────────────────────────
def parse_batch_list(xml_str):
    """Extract resource URLs from PGE BatchList notification XML."""
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        log(f"BatchList XML parse error: {e}")
        return []

    urls = []
    # <ns0:BatchList xmlns:ns0="http://naesb.org/espi">
    #   <ns0:resources>https://api.pge.com/...</ns0:resources>
    # </ns0:BatchList>
    for el in root:
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "resources" and el.text:
            urls.append(el.text.strip())

    return urls

# ── Step 3: Get OAuth2 access token via mTLS ─────────────────────────────────
def get_oauth_token():
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    headers = {
        "Authorization": f"Basic {creds}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials"}
    try:
        r = requests.post(TOKEN_URL, headers=headers, data=data,
                          cert=MTLS, verify=CA_BUNDLE, timeout=30)
        if r.status_code == 200:
            td = r.json()
            token = td.get("client_access_token") or td.get("access_token")
            if token:
                log(f"OAuth token obtained (expires_in={td.get('expires_in')}s)")
                return token
        log(f"Token error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log(f"Token exception: {e}")
    return None

# ── Step 4: Fetch actual ESPI data from PGE API ──────────────────────────────
def fetch_espi_data(url, token):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers, cert=MTLS, verify=CA_BUNDLE, timeout=60)
        log(f"  Fetched {url[:80]}... → HTTP {r.status_code} ({len(r.content)}B)")
        if r.status_code == 200:
            return r.text
        else:
            log(f"  Error body: {r.text[:200]}")
    except Exception as e:
        log(f"  Fetch exception: {e}")
    return None

# ── DB setup ─────────────────────────────────────────────────────────────────
def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pge_energy (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at   TEXT NOT NULL,
            interval_ts  TEXT,
            duration_s   INTEGER,
            kwh          REAL,
            cost_cents   REAL,
            quality      TEXT,
            raw_key      TEXT,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(interval_ts, duration_s)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pge_accounts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            fetched_at   TEXT NOT NULL,
            account_id   TEXT,
            customer_name TEXT,
            service_address TEXT,
            raw_xml      TEXT,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

# ── Step 5: Parse ESPI interval data ─────────────────────────────────────────
def parse_espi_usage(xml_str, raw_key, conn, fetched_at):
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        log(f"  ESPI XML parse error: {e}")
        return 0

    # Extract unit metadata from ReadingType
    # powerOfTenMultiplier: -3 means values are in milli-units
    # uom 72 = Wh (watt-hours)
    p10 = 0   # default: no scaling
    uom = 72  # default: Wh
    for rt in root.iter('{http://naesb.org/espi}ReadingType'):
        p10_el = rt.find('{http://naesb.org/espi}powerOfTenMultiplier')
        uom_el = rt.find('{http://naesb.org/espi}uom')
        if p10_el is not None:
            p10 = int(p10_el.text)
        if uom_el is not None:
            uom = int(uom_el.text)
        break  # use first ReadingType found

    # scale factor: raw_value * 10^p10 = actual value in base unit (Wh)
    scale = 10 ** p10   # e.g. p10=-3 → 0.001

    inserted = 0
    for ib in root.iter('{http://naesb.org/espi}IntervalBlock'):
        for ir in ib.iter('{http://naesb.org/espi}IntervalReading'):
            ts_el   = ir.find('{http://naesb.org/espi}timePeriod/{http://naesb.org/espi}start')
            dur_el  = ir.find('{http://naesb.org/espi}timePeriod/{http://naesb.org/espi}duration')
            val_el  = ir.find('{http://naesb.org/espi}value')
            qual_el = ir.find('{http://naesb.org/espi}ReadingQuality/{http://naesb.org/espi}quality')

            if ts_el is None or val_el is None:
                continue

            ts_unix  = int(ts_el.text)
            dur_s    = int(dur_el.text) if dur_el is not None else 900
            raw_val  = int(val_el.text)
            wh       = raw_val * scale   # actual Wh (for uom=72)
            kwh      = wh / 1000.0       # convert Wh → kWh
            quality  = qual_el.text if qual_el is not None else None
            dt       = datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat()

            try:
                conn.execute("""
                    INSERT OR IGNORE INTO pge_energy
                      (fetched_at, interval_ts, duration_s, kwh, raw_key, quality)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (fetched_at, dt, dur_s, kwh, raw_key, quality))
                inserted += 1
            except Exception as e:
                log(f"  DB insert error: {e}")

    conn.commit()
    return inserted

def parse_customer_info(xml_str, conn, fetched_at):
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return

    for entry in root.iter('{http://www.w3.org/2005/Atom}entry'):
        cust = entry.find('.//{http://naesb.org/espi/customer}Customer')
        if cust is None:
            continue
        name_el = cust.find('{http://naesb.org/espi/customer}name')
        acct_el = cust.find('.//{http://naesb.org/espi/customer}accountId')
        addr_el = cust.find('.//{http://naesb.org/espi/customer}mainAddress/{http://naesb.org/espi/customer}streetDetail/{http://naesb.org/espi/customer}name')

        conn.execute("""
            INSERT INTO pge_accounts (fetched_at, customer_name, account_id, service_address, raw_xml)
            VALUES (?, ?, ?, ?, ?)
        """, (
            fetched_at,
            name_el.text if name_el is not None else None,
            acct_el.text if acct_el is not None else None,
            addr_el.text if addr_el is not None else None,
            xml_str[:2000],
        ))
    conn.commit()

def detect_and_parse(xml_str, raw_key, conn, fetched_at):
    if "IntervalBlock" in xml_str or "IntervalReading" in xml_str:
        log("  Detected: usage/interval data")
        n = parse_espi_usage(xml_str, raw_key, conn, fetched_at)
        log(f"  Inserted {n} interval readings into pge_energy")
        return n
    elif "Customer" in xml_str or "RetailCustomer" in xml_str:
        log("  Detected: customer info data")
        parse_customer_info(xml_str, conn, fetched_at)
        log("  Customer info stored in pge_accounts")
        return 1
    else:
        log(f"  Unknown payload type. Preview: {xml_str[:200]}")
        return 0

# ── Supabase sync ────────────────────────────────────────────────────────────
SUPABASE_URL = "https://pfmmkyoygialzysjqksp.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBmbW1reW95Z2lhbHp5c2pxa3NwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ1NTM4NzIsImV4cCI6MjA5MDEyOTg3Mn0.mXqHhLCN20mlt3xMwugp6SHMAdWTYnXLAyMu1wiNpRM"

def supabase_upsert(rows: list):
    """Upsert rows into Supabase energy_data table."""
    if not rows:
        return
    url  = f"{SUPABASE_URL}/rest/v1/energy_data?on_conflict=date,utility_type"
    data = json.dumps(rows).encode()
    req  = urllib.request.Request(
        url, data=data,
        headers={
            "apikey":        SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type":  "application/json",
            "Prefer":        "resolution=merge-duplicates,return=minimal",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            log(f"Supabase upsert: {len(rows)} rows → HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        log(f"Supabase upsert error {e.code}: {err[:200]}")


# ── E-1 tiered rate estimation ───────────────────────────────────────────────
# Derived from actual PG&E billing history (effective blended $/kWh per month).
# These are observed effective rates (Tier 1 + Tier 2 blended at actual usage),
# not the raw tariff rates. Using prior-year same-month as the best proxy.
# Plan: E-1 (tiered, non-TOU). Tier 1 baseline ~350 kWh/mo in PG&E Zone X.
MONTHLY_EFFECTIVE_RATE = {
    "2025-03": 0.4478,
    "2025-04": 0.4476,
    "2025-05": 0.4471,
    "2025-06": 0.4493,
    "2025-07": 0.4521,
    "2025-08": 0.4529,
    "2025-09": 0.4422,
    "2025-10": 0.4186,
    "2025-11": 0.3823,
    "2025-12": 0.3897,
    "2026-01": 0.3618,
    "2026-02": 0.3616,
    "2026-03": 0.3108,
}

def estimate_rate(day_str):
    """Return $/kWh estimate for a given date (YYYY-MM-DD).
    Uses same month prior year if available; falls back to season average."""
    month = day_str[:7]         # "2026-05"
    # Try exact month
    if month in MONTHLY_EFFECTIVE_RATE:
        return MONTHLY_EFFECTIVE_RATE[month]
    # Try same month prior year
    year  = int(month[:4])
    mm    = month[5:]
    prior = f"{year - 1}-{mm}"
    if prior in MONTHLY_EFFECTIVE_RATE:
        return MONTHLY_EFFECTIVE_RATE[prior]
    # Seasonal fallback
    m_num = int(mm)
    if m_num in (6, 7, 8, 9):    # summer
        return 0.448
    elif m_num in (12, 1, 2):    # winter
        return 0.370
    else:
        return 0.410


def sync_pge_to_supabase():
    """Aggregate pge_energy hourly rows → daily totals → upsert to Supabase."""
    conn = sqlite3.connect(DB)
    cur  = conn.execute("""
        SELECT
            date(interval_ts) AS day,
            SUM(kwh)          AS kwh_total
        FROM pge_energy
        WHERE duration_s = 3600
        GROUP BY date(interval_ts)
        ORDER BY day
    """)
    daily = cur.fetchall()
    conn.close()

    if not daily:
        log("sync_pge_to_supabase: no data to sync")
        return

    rows = []
    for day_str, kwh in daily:
        rate = estimate_rate(day_str)
        cost = round(kwh * rate, 2)
        rows.append({
            "date":         day_str,
            "provider":     "PG&E",
            "utility_type": "electric",
            "kwh_used":     round(kwh, 3),
            "cost":         cost,
            "granularity":  "daily",
            "notes":        f"PGE Share My Data live API (E-1 rate ~${rate:.4f}/kWh est.)",
        })

    log(f"Syncing {len(rows)} daily PGE rows to Supabase (with estimated E-1 costs)...")
    supabase_upsert(rows)


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    log("PGE poller starting...")
    state = load_state()
    data  = fetch_latest_callback()

    if not data:
        log("Nothing to process.")
        return

    key       = data.get("key", "latest")
    timestamp = data.get("timestamp", "")
    body      = data.get("body", "")

    if key == state.get("last_key"):
        log(f"Already processed key={key}, nothing new.")
        return

    if not body or len(body) < 20:
        log(f"Empty body on key={key}")
        return

    log(f"New callback: key={key} ts={timestamp} size={len(body)}B")

    fetched_at = datetime.now(tz=timezone.utc).isoformat()
    conn = sqlite3.connect(DB)
    ensure_table(conn)
    total_inserted = 0

    # Check if this is a BatchList (pointer to real data) or raw ESPI data
    if "BatchList" in body or "<resources>" in body or ":resources>" in body:
        log("Detected: BatchList notification — fetching resource URLs...")
        urls = parse_batch_list(body)
        log(f"Found {len(urls)} resource URL(s)")

        if not urls:
            log("No URLs found in BatchList — skipping")
        else:
            token = get_oauth_token()
            if not token:
                log("❌ Could not get OAuth token — will retry next cycle")
                conn.close()
                return  # Don't advance state; retry next time

            for i, url in enumerate(urls):
                log(f"Fetching resource {i+1}/{len(urls)}: {url[:80]}...")
                xml_str = fetch_espi_data(url, token)
                if xml_str:
                    n = detect_and_parse(xml_str, key, conn, fetched_at)
                    total_inserted += n

        log(f"BatchList processing complete. Total readings inserted: {total_inserted}")
    else:
        # Direct ESPI payload (legacy / test)
        total_inserted = detect_and_parse(body, key, conn, fetched_at)

    conn.close()

    # Advance state only after successful processing
    state["last_key"]       = key
    state["last_processed"] = fetched_at
    save_state(state)

    # Sync to Supabase so dashboard picks it up
    sync_pge_to_supabase()

    # Regenerate dashboard_data.json
    dashboard_script = os.path.expanduser("~/Desktop/home-dashboard/scripts/generate_dashboard_data.py")
    if os.path.exists(dashboard_script):
        import subprocess
        result = subprocess.run([sys.executable, dashboard_script], capture_output=True, text=True)
        if result.returncode == 0:
            log(f"Dashboard regenerated: {result.stdout.strip()}")
        else:
            log(f"Dashboard regen error: {result.stderr.strip()[:200]}")

    log("Done.")

if __name__ == "__main__":
    main()
