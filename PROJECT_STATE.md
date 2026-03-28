# Home Dashboard — Project State & Agent Handoff Guide
_Last updated: 2026-03-27_

> This document is the single source of truth for the Home Dashboard project.
> An agent reading this file should be able to understand the full system, make
> modifications, debug issues, or rebuild from scratch.

---

## What This Is

A personal home-management dashboard for Steve's house at 1950 Eucalyptus Ave,
San Carlos, CA 94070. It tracks:

- **Thermostat** — live Nest readings (temp, humidity, HVAC mode) for Downstairs
  and Upstairs units, polled every 15 minutes
- **Energy** — monthly PG&E electric (kWh) and gas (therms) usage with cost,
  imported from Green Button CSVs
- **Projects** — 6 active/planning home-improvement projects with tasks, quotes,
  and vendor contacts
- **Maintenance** — recurring items (e.g. air filter replacement) with schedules
  and inventory
- **Communications** — email thread log with vendors, showing direction, subject,
  and summary
- **Open Quotes** — pending/received quotes across all projects with days-since-sent

---

## Live URLs

| What | URL |
|---|---|
| **Dashboard (public)** | https://eucalyptus-home-dashboard.netlify.app/ |
| **Dashboard (direct file)** | https://eucalyptus-home-dashboard.netlify.app/home_dashboard.html |
| **GitHub repo** | https://github.com/stvmcclr/Home-dashboard |
| **Netlify admin** | https://app.netlify.com/projects/eucalyptus-home-dashboard |

The root URL (`/`) redirects to `home_dashboard.html` via a Netlify `_redirects` rule.

---

## Architecture

```
Google Nest SDM API
    └─▶  GitHub Actions (cron every 15 min, 24/7)
              └─▶  scripts/nest_monitor.py
                        ├─▶  Supabase: INSERT into thermostat_readings
                        └─▶  scripts/generate_dashboard_data.py
                                  ├─▶  reads ALL tables from Supabase
                                  └─▶  writes dashboard_data.json → git commit → push

PG&E Green Button CSVs  (manual, when new data available)
    └─▶  scripts/import_pge.py → Supabase: energy_data table

home_dashboard.html  (static, served by Netlify)
    └─▶  fetch("dashboard_data.json")   ← auto-refreshes every 5 min
    └─▶  renders all cards, charts, modals from JSON

Netlify
    └─▶  GitHub integration: auto-deploys on every push to main
    └─▶  _redirects: / → /home_dashboard.html 200
    └─▶  netlify.toml: command="", publish="."  (no build step)
```

**Key design decisions:**
- No build step. Netlify serves the repo root as-is.
- No Mac involvement. Everything runs in the cloud 24/7.
- `dashboard_data.json` is the bridge between backend (Python/Supabase) and
  frontend (HTML/JS). GitHub Actions regenerates and commits it every 15 min.
- `supabase_client.py` uses only Python stdlib (`urllib`) — no `pip install` needed,
  works in GitHub Actions without any dependency step.

---

## Repository Layout

```
Home Project Database/
├── home_dashboard.html          ← single-page dashboard UI
├── dashboard_data.json          ← auto-generated JSON snapshot (committed by CI)
├── PROJECT_STATE.md             ← this file
├── netlify.toml                 ← tells Netlify: no build, publish root
├── _redirects                   ← Netlify: redirect / → /home_dashboard.html
├── config.json                  ← LOCAL ONLY (gitignored). Credentials.
├── .gitignore                   ← excludes config.json, *.db, certs/, logs/
│
├── scripts/
│   ├── supabase_client.py       ← zero-dep Supabase REST wrapper
│   ├── nest_monitor.py          ← poll Nest API, write to Supabase
│   ├── generate_dashboard_data.py ← read Supabase → write dashboard_data.json
│   ├── import_pge.py            ← import PG&E Green Button CSVs into Supabase
│   ├── migrate_to_supabase.py   ← one-time SQLite → Supabase migration (done)
│   └── pge_poller.py            ← stub for future PG&E API polling (not active)
│
└── .github/
    └── workflows/
        └── monitor.yml          ← GitHub Actions: runs every 15 min
```

**Files that can be safely ignored/deleted:**
- `home_projects.db` — old SQLite database, superseded by Supabase
- `init_db.py` — SQLite init script, superseded
- `launchd/` — old macOS auto-start agents, superseded by GitHub Actions
- `scripts/test_sqlite.db`, `test_write.tmp` — scratch files

---

## Supabase Database

**Project URL:** stored in `config.json` as `supabase.url`
**Auth:** anon key in `config.json` as `supabase.anon_key`

### Tables and Their Contents

| Table | Rows (approx) | Source | Notes |
|---|---|---|---|
| `projects` | 6 | Manual / legacy | id, name, status, priority, description, estimated_cost, actual_cost, notes, created_date |
| `tasks` | ~45 | Manual / legacy | id, project_id (FK), description, status, notes |
| `vendors` | ~20 | Manual / legacy | id, name, contact_name, email, phone |
| `quotes` | ~4 | Manual | id, project_id, vendor_id, amount, status (pending/received/rejected/accepted), date_received, notes |
| `communications` | ~17 | Manual | id, project_id, vendor_id, date, direction (inbound/outbound), subject, summary |
| `documents` | 0 | Schema only | id, project_id, name, url, uploaded_at |
| `maintenance_items` | ~3 | Migrated from SQLite | id, name, category, interval_days, last_done, next_due, inventory_count, notes |
| `thermostat_readings` | growing | nest_monitor.py every 15 min | id, timestamp, location, temp_f, humidity_pct, mode, hvac_status, heat_setpoint_f, cool_setpoint_f, eco_mode, fan_mode, connectivity |
| `energy_data` | ~380 | import_pge.py | id, date, utility_type (electric/gas), kwh_used, therms_used, cost, provider, granularity; UNIQUE(date, utility_type) |

### Task Status Values
`todo` | `in_progress` | `waiting_on_steve` | `waiting_on_vendor` | `done`

### Quote Status Values
`pending` | `received` | `rejected` | `accepted`

---

## GitHub Actions Workflow (`.github/workflows/monitor.yml`)

Runs on: cron `*/15 * * * *` (every 15 min) + manual `workflow_dispatch`

Steps:
1. Checkout repo
2. Set up Python 3.11
3. Write `config.json` from secrets (see below)
4. Run `python3 scripts/nest_monitor.py` → polls Nest, writes to Supabase
5. Run `python3 scripts/generate_dashboard_data.py` → writes `dashboard_data.json`
6. Commit `dashboard_data.json` and push (only if changed)

Netlify detects the push and auto-deploys within ~30 seconds.

### GitHub Secrets Required

Navigate to: https://github.com/stvmcclr/Home-dashboard/settings/secrets/actions

| Secret Name | What it is |
|---|---|
| `NEST_CLIENT_ID` | Google Cloud OAuth2 client ID |
| `NEST_CLIENT_SECRET` | Google Cloud OAuth2 client secret |
| `NEST_REFRESH_TOKEN` | Long-lived OAuth2 refresh token for Nest access |
| `NEST_PROJECT_ID` | Google SDM project ID (format: `enterprises/xxxx`) |
| `SUPABASE_URL` | Supabase project URL (e.g. `https://xxxx.supabase.co`) |
| `SUPABASE_ANON_KEY` | Supabase anon/public key |

---

## config.json (local only, gitignored)

Must exist on any machine running scripts directly (Mac or local dev):

```json
{
  "nest": {
    "client_id":     "...",
    "client_secret": "...",
    "refresh_token": "...",
    "project_id":    "enterprises/..."
  },
  "supabase": {
    "url":      "https://xxxx.supabase.co",
    "anon_key": "eyJ..."
  },
  "poll_interval_minutes": 15,
  "netlify": { "enabled": false }
}
```

---

## Frontend: home_dashboard.html

Single HTML file. No framework, no build step. Uses:
- **Chart.js** (CDN) for energy bar charts and thermostat history line charts
- **Vanilla JS** for modal system, card click handlers, fetch + render
- **Inline CSS** — no external stylesheet

### Key JS Sections

| Section | What it does |
|---|---|
| `fetch('dashboard_data.json')` | Loads data on page load and every 5 min |
| `renderThermostat()` | Shows current temp/humidity/mode cards + 24h history chart |
| `renderEnergy()` | Monthly bar charts + annual totals from `data.energy` |
| `renderProjects()` | Clickable project cards → detail modals |
| `renderOpenQuotes()` | Live quote feed with days-since-sent |
| `renderCommunications()` | Recent email log |
| `openModal(project)` | Overlay with full project detail: tasks, quotes, vendor contacts |

### Adding New Dashboard Sections

1. Add the data to `generate_dashboard_data.py` (pull from Supabase, add to the
   returned dict)
2. Add a render function in `home_dashboard.html` that reads the new key from
   the fetched JSON
3. Call your render function inside the main `render(data)` function

---

## Scripts

### `scripts/supabase_client.py`
Zero-dependency Supabase REST wrapper. Reads `config.json` automatically.

```python
from supabase_client import get_client
sb = get_client()

sb.select("projects", order="created_date.asc")
sb.select("tasks", query="*, projects(name)", filters={"status": "eq.waiting_on_steve"})
sb.insert("thermostat_readings", [{"timestamp": ..., "location": ..., ...}])
sb.upsert("energy_data", rows)   # ON CONFLICT DO UPDATE
sb.count("thermostat_readings")  # returns int
```

### `scripts/nest_monitor.py`
- Exchanges refresh token for access token via `oauth2.googleapis.com/token`
- Lists devices via `smartdevicemanagement.googleapis.com/v1/enterprises/{pid}/devices`
- Filters to THERMOSTAT type, parses all traits (temp, humidity, mode, setpoints, etc.)
- Converts °C to °F
- Writes rows to Supabase `thermostat_readings`
- Calls `generate_dashboard_data.py` as subprocess
- Has stub support for Netlify CLI deploy (disabled: `"netlify": {"enabled": false}`)
- Has stub support for PGE polling (disabled until `pge_api` key added to config)

### `scripts/generate_dashboard_data.py`
Reads all Supabase tables, assembles one JSON blob, writes to `dashboard_data.json`.
No side effects beyond that file write.

### `scripts/import_pge.py`
Imports PG&E Green Button CSV exports into `energy_data` table.
To refresh energy data:
1. Log in to pge.com → Energy Usage → Download Green Button data
2. Save CSVs locally
3. Run: `python3 scripts/import_pge.py path/to/electric.csv path/to/gas.csv`

---

## Netlify Configuration

**Site name:** `eucalyptus-home-dashboard`
**GitHub integration:** `stvmcclr/Home-dashboard`, branch `main`
**Auto-publish:** ON (every push to main triggers a deploy)
**Build command:** _(empty — no build step)_
**Publish directory:** `.` (repo root)

`netlify.toml`:
```toml
[build]
  publish = "."
  command = ""
```

`_redirects`:
```
/  /home_dashboard.html  200
```

---

## Active Projects (as of 2026-03-27)

| Project | Status | Next Action |
|---|---|---|
| Window Washing | Active | Gary's Cleaning quote received — review & schedule |
| Front Yard Fence Replacement | Planning | Research HOA requirements |
| Roof Replacement | Active | Awaiting rough quote from Signature Roofing (William) EOD Mar 27 |
| Solar + Energy Storage on Garage | Planning | Research NEM 3.0, get quotes |
| Pest Inspection | Active | Mike Amdal out (no termites), Omega pending; need 1-2 more companies |
| Air Filter Maintenance | Planning | Confirm filter sizes, order inventory |

---

## Known Data Gaps & Future Improvements

| Item | Notes |
|---|---|
| PG&E auto-polling | `pge_poller.py` is a stub. Requires formal PG&E developer API access (multi-week approval). For now: manual CSV import. |
| Energy data freshness | Current data goes through ~Mar 22, 2026. Download fresh Green Button CSVs from pge.com and re-run `import_pge.py` to update. |
| Thermostat history depth | Readings only go back to when the GitHub Actions workflow was first triggered. History accumulates over time. |
| Quotes amounts | Most quotes show "TBD" — update Supabase `quotes` table when actual amounts are received. |
| Communications | Manually entered. No email integration. A future Gmail MCP integration could auto-sync threads. |

---

## How to Make Common Changes

### Add a new project
Insert into Supabase `projects` table. Tasks go in `tasks` with the matching `project_id`.

### Add a vendor / quote
Insert vendor into `vendors`, then insert quote into `quotes` with `project_id` and `vendor_id`.

### Log a communication
Insert into `communications` with `project_id`, `vendor_id`, `date`, `direction` (inbound/outbound), `subject`, `summary`.

### Update a task status
Update `tasks.status` in Supabase. Valid values: `todo`, `in_progress`, `waiting_on_steve`, `waiting_on_vendor`, `done`.

### Manually trigger a dashboard refresh
Go to https://github.com/stvmcclr/Home-dashboard/actions → "Home Monitor" → "Run workflow".

### Run scripts locally (Mac)
Ensure `config.json` exists at repo root with Nest and Supabase credentials, then:
```bash
cd ~/path/to/Home\ Project\ Database
python3 scripts/nest_monitor.py          # poll + update JSON
python3 scripts/generate_dashboard_data.py  # just regenerate JSON
python3 scripts/import_pge.py electric.csv gas.csv  # import PG&E data
```
