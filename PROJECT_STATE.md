# Home Dashboard — Project State
_Last updated: 2026-03-27_

---

## Live URLs
| Where | URL | Status |
|---|---|---|
| Local (always current) | http://localhost:8080/home_dashboard.html | Requires HTTP server running |
| Netlify (public) | https://eucalyptus-home-dashboard.netlify.app | Stale — needs redeploy |

---

## Architecture Overview

```
Nest API (every 15 min)
    └─▶ nest_monitor.py
            ├─▶ thermostat_readings table (SQLite — permanent history)
            ├─▶ generate_dashboard_data.py → dashboard_data.json (snapshot)
            └─▶ netlify deploy --prod  (auto-push to public URL)

PG&E Green Button CSVs (manual import)
    └─▶ import_pge.py → energy_data table (Mar 2025–Mar 2026)

home_dashboard.html
    └─▶ reads dashboard_data.json via fetch()
    └─▶ auto-refreshes every 5 min
```

---

## Database: home_projects.db

Located at: `~/Claude_Projects/Home Project Database/home_projects.db`

| Table | Contents | Source |
|---|---|---|
| `projects` | 6 projects with status/priority | Migrated from dashboard_data.json |
| `tasks` | Tasks per project with status | Migrated from dashboard_data.json |
| `vendors` | Vendor names and contacts | Auto-created from quotes |
| `quotes` | Quotes per project with status | Migrated from dashboard_data.json |
| `maintenance_items` | Maintenance schedule | Migrated from dashboard_data.json |
| `communications` | 17 email records | Migrated from dashboard_data.json |
| `documents` | Document links (empty) | Schema only |
| `thermostat_readings` | Temp/humidity/HVAC every 15 min | nest_monitor.py live polling |
| `energy_data` | Daily kWh and therms | PG&E Green Button CSV import |

---

## Dashboard Features (home_dashboard.html)

All implemented and working locally:
- **Thermostat cards** — live temp, humidity, HVAC status, 24h history chart
- **Maintenance items** — clickable, shows schedule + inventory in modal
- **Needs Attention** — tasks with `waiting_on_steve` status
- **Energy charts** — monthly kWh and therms bar charts, annual totals
- **Projects grid** — clickable cards → modal with all tasks + quotes + contacts
- **Open Quotes** — live feed of pending/received quotes with days-since-sent
- **Recent Communications** — last 15 emails with direction, subject, summary

---

## Scripts

| Script | Purpose | Run |
|---|---|---|
| `scripts/nest_monitor.py` | Poll Nest API, save readings, regen JSON, deploy | Auto via launchd every 15 min |
| `scripts/generate_dashboard_data.py` | Rebuild dashboard_data.json from DB | Called by nest_monitor |
| `scripts/import_pge.py` | Import PG&E Green Button CSVs | Manual when new CSVs downloaded |
| `init_db.py` | Create all DB tables + migrate from JSON | Run once (already done) |
| `launchd/install.sh` | Install macOS auto-start agents | Run once (NOT YET DONE) |

---

## Pending Setup Steps (must complete)

### 1. Install launchd agents (makes everything auto-start on login)
```bash
cd ~/Claude_Projects/"Home Project Database" && bash launchd/install.sh
```

### 2. Set up Netlify CLI auto-deploy
```bash
# Fix permissions (needed once)
sudo chown -R $USER ~/Library/Preferences/netlify

# Login (opens browser)
netlify login

# Link to existing site
cd ~/Claude_Projects/"Home Project Database" && netlify link --name eucalyptus-home-dashboard
```
After linking, every `nest_monitor.py` poll auto-deploys to Netlify.

### 3. Deploy current HTML to Netlify NOW (quick fix while CLI setup pending)
Drag the `Home Project Database` folder to https://app.netlify.com/drop
→ Picks up eucalyptus-home-dashboard automatically

---

## Data Gaps / Known Issues

| Issue | Status |
|---|---|
| PG&E data only through Mar 22, 2026 | Download fresh CSVs from PGE.com, re-run `import_pge.py` |
| PG&E auto-polling (pge_poller.py) | NOT SET UP — requires formal PG&E developer registration (weeks) |
| Netlify site stale | Needs redeploy (see step 3 above) |
| launchd agents not installed | See step 1 above |
| Thermostat history < 1 day old | Will accumulate — building dataset over time |

---

## Active Projects (summary)

| Project | Status | Next Action |
|---|---|---|
| Pest Inspection | Active | Find 1-2 more companies (Mike Amdal out, Omega no reply) |
| Roof | Active | Signature Roofing (William) promised rough quote EOD Mar 27 |
| Window Washing | Active | Gary's Cleaning quote in — review and schedule |
| Others | Planning/Active | See dashboard for full task lists |

---

## Config Files

- `config.json` — Nest API credentials, Netlify site ID, DB path
- `launchd/com.steve.homeserver.plist` — HTTP server on port 8080
- `launchd/com.steve.homemonitor.plist` — Nest poll every 15 min
- `certs/` — Namecheap/Sectigo cert for roccoorsini.com (Netlify manages this automatically — no action needed)
