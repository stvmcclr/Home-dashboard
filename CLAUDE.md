# Claude Instructions — Home Dashboard Project

This is Steve's personal home-management dashboard for 1950 Eucalyptus Ave,
San Carlos, CA 94070. When Steve asks about "the dashboard", "projects",
"quotes", "the thermostat", "energy data", or anything home-related, this is
the context you're working in.

---

## How to Access Live Data

The dashboard is live at: **https://eucalyptus-home-dashboard.netlify.app/**

The underlying data is in two places:

1. **`dashboard_data.json`** (in this repo) — a JSON snapshot rebuilt every
   15 minutes by GitHub Actions. This is the fastest way to read current state:
   ```bash
   cat dashboard_data.json | python3 -m json.tool | head -100
   ```
   Or read it with Python:
   ```python
   import json
   data = json.load(open("dashboard_data.json"))
   # keys: projects, thermostat, energy, maintenance, open_quotes,
   #        recent_communications, needs_attention, stats
   ```

2. **Supabase** — the live database. Use `scripts/supabase_client.py` to query:
   ```python
   import sys; sys.path.insert(0, "scripts")
   from supabase_client import get_client
   sb = get_client()  # reads credentials from config.json
   projects = sb.select("projects")
   tasks    = sb.select("tasks", filters={"project_id": "eq.3"})
   ```
   Requires `config.json` to be present locally (it's gitignored).

---

## What Data Is Available

| Topic | Where to find it | Notes |
|---|---|---|
| **Projects** | `data["projects"]` | 6 projects; each has tasks[], quotes[], task_counts |
| **Tasks** | `data["projects"][i]["tasks"]` | status: todo / in_progress / waiting_on_steve / waiting_on_vendor / done |
| **Quotes** | `data["projects"][i]["quotes"]` | status: pending / received / rejected / accepted |
| **Vendors** | Supabase `vendors` table | name, contact_name, email, phone |
| **Thermostat** | `data["thermostat"]["latest"]` | Downstairs + Upstairs: temp_f, humidity_pct, mode, hvac_status, setpoints |
| **Thermostat history** | `data["thermostat"]["history"]` | Last 24h readings, polled every 15 min |
| **Energy** | `data["energy"]` | monthly_electric (kwh_used), monthly_gas (therms_used), annual totals |
| **Maintenance** | `data["maintenance"]` | items with next_due, days_until_due, inventory_count |
| **Open quotes** | `data["open_quotes"]` | All pending/received quotes with vendor, project, days-since-sent |
| **Communications** | `data["recent_communications"]` | Last 15 email records: direction, subject, summary, date |
| **Needs attention** | `data["needs_attention"]` | Tasks with status = waiting_on_steve |

---

## Active Projects (summary)

| Project | Status | Key vendors |
|---|---|---|
| Window Washing | Active | Gary's Cleaning (garyscleaning@gmail.com) |
| Front Yard Fence Replacement | Planning | TBD |
| Roof Replacement | Active | Signature Roofing / William (william@signatureroofing.com), Cal-Pac Roofing |
| Solar + Energy Storage on Garage | Planning | TBD |
| Pest Inspection | Active | Omega Home Services (pending); Mike Amdal (rejected — no termites) |
| Air Filter Maintenance | Planning | TBD |

---

## How to Make Changes

All data lives in Supabase. Steve never edits JSON directly.

**Add / update a task:**
```python
sb.insert("tasks", [{"project_id": 3, "description": "...", "status": "todo"}])
sb.update("tasks", {"status": "done"}, {"id": "eq.42"})
```

**Log a communication (email record):**
```python
sb.insert("communications", [{
    "project_id": 3,
    "vendor_id": 7,
    "date": "2026-03-27",
    "direction": "inbound",   # or "outbound"
    "subject": "Re: Roof quote",
    "summary": "William confirmed quote by EOD."
}])
```

**Add a quote:**
```python
sb.insert("quotes", [{
    "project_id": 3,
    "vendor_id": 7,
    "amount": 18500,
    "status": "received",
    "date_received": "2026-03-27",
    "notes": "Includes detached garage"
}])
```

**After any Supabase change, regenerate the dashboard:**
```bash
python3 scripts/generate_dashboard_data.py
```
Then commit and push `dashboard_data.json` to deploy it live.

Or just wait — GitHub Actions does this automatically every 15 minutes.

---

## Architecture in One Paragraph

GitHub Actions runs every 15 minutes: it polls the Google Nest SDM API
(`nest_monitor.py`), writes thermostat readings to Supabase, then rebuilds
`dashboard_data.json` from all Supabase tables (`generate_dashboard_data.py`),
commits the file, and pushes. Netlify detects the push and re-deploys the
static site within ~30 seconds. `home_dashboard.html` fetches
`dashboard_data.json` and re-renders every 5 minutes. No Mac required —
the whole pipeline runs in the cloud 24/7.

---

## Key Files

| File | Purpose |
|---|---|
| `home_dashboard.html` | The dashboard UI (single HTML file, no build step) |
| `dashboard_data.json` | Auto-generated JSON snapshot — source of truth for the frontend |
| `scripts/supabase_client.py` | Zero-dependency Supabase REST client (stdlib only) |
| `scripts/nest_monitor.py` | Polls Nest API, writes to Supabase |
| `scripts/generate_dashboard_data.py` | Reads Supabase → writes dashboard_data.json |
| `scripts/import_pge.py` | Imports PG&E Green Button CSVs into energy_data table |
| `.github/workflows/monitor.yml` | GitHub Actions cron (every 15 min) |
| `config.json` | Local credentials (gitignored — never commit this) |
| `PROJECT_STATE.md` | Full architecture reference for agents |

---

## Things to Know About Steve's Preferences

- Don't make changes one file/error at a time — read all relevant files first,
  then fix everything in one pass.
- Don't summarize what you just did at the end of a response.
- The source of truth for project data is Supabase, not dashboard_data.json
  (the JSON is a read-only snapshot).
- Credentials are never in the repo. Always use config.json locally or
  GitHub Secrets in CI.
