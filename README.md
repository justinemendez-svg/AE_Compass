# AE Compass

Live sales performance dashboard powered by Snowflake data from the [gtm-ops-claude](https://github.com/zendesk/gtm-ops-claude) pipeline.

---

## Quick Start (5 minutes)

### Prerequisites

- **Node.js 18+** — `brew install node` or [nvm](https://github.com/nvm-sh/nvm)
- **Python 3.9+** — comes with macOS
- **[gtm-ops-claude](https://github.com/zendesk/gtm-ops-claude)** repo cloned with `.env` configured (Snowflake credentials)

### Setup

```bash
# 1. Clone this repo
git clone git@github.com:yelhay-zendesk/salespilot-dashboard.git
cd salespilot-dashboard

# 2. Run setup (installs all dependencies)
./setup.sh

# 3. Start the app
npm run dev
```

That's it. On first launch, a browser tab opens for Snowflake SSO (Okta) — authenticate once and the session stays alive.

---

## How It Works

```
┌─────────────────────┐         ┌──────────────────────┐
│  Electron + React   │ ──────→ │  Python Flask Server  │ ──────→ Snowflake (ZENDESK-GLOBAL)
│  (localhost:5173)   │  HTTP   │  (localhost:4400)     │         GTMSI Pipeline Table
└─────────────────────┘         └──────────────────────┘
```

The Python server reads Snowflake credentials from your `gtm-ops-claude/.env` and queries the GTMSI consolidated pipeline table for live data. The Electron/React frontend displays it.

### gtm-ops-claude Location

The server auto-discovers `gtm-ops-claude` by checking:
1. `GTM_REPO` environment variable (if set)
2. `../gtm-ops-claude` (sibling directory)
3. `~/Desktop/gtm-ops-claude`
4. `~/gtm-ops-claude`

Or set it explicitly: `export GTM_REPO=/path/to/gtm-ops-claude`

---

## Features

### Performance Dashboard
- **Cascading filters:** Region → Dir Team → Mgr Team → AE → Fiscal Quarter
- **Workday hierarchy** loaded from the filtered Chris Donato roster export
- Bookings (Estimated Won): Total, New Business, Expansion, AI Products
- Open Pipeline with 3x coverage tracking
- AI product breakdown (Copilot, Ultimate, WEM, QA, AR, Forethought)
- Stage distribution computed from live deals
- Top deals table with VP Forecast, GTM Team, close dates
- Quarterly bookings history (FY27 Q1–Q4)

### Development & Coaching
- Pipeline health metrics (deal count, ARR, avg deal size)
- Coaching logs with categories and search
- Action items with status tracking

---

## Running Individually

If `npm run dev` doesn't work, run each component separately:

```bash
# Terminal 1: Data server
cd server && python3 app.py

# Terminal 2: Frontend dev server
npm run dev:renderer

# Terminal 3: Electron app (optional — browser works too)
npm run dev:main
```

Or just use the browser at **http://localhost:5173** after starting the server + renderer.

---

## Data Sources

All data comes from **`functional.gtm_sales_ops.gtmsi_consolidated_pipeline_bookings`** (Snowflake):

| Endpoint | What it queries |
|----------|----------------|
| `/api/roster` | All active AEs with open pipeline (owner + hierarchy) |
| `/api/pipeline` | Open deals (stages 02-06) for an AE |
| `/api/metrics/summary` | Aggregated bookings + pipeline by quarter |
| `/api/stage_distribution` | Deal count by stage |
| `/api/pipeline_by_product` | Product-level ARR (17 products) |
| `/api/historical` | Bookings across FY27 Q1-Q4 |

---

## Fiscal Calendar

Zendesk uses a February-start fiscal year:

| Quarter | Dates |
|---------|-------|
| FY27 Q1 | Feb 1 – Apr 30, 2026 |
| FY27 Q2 | May 1 – Jul 31, 2026 |
| FY27 Q3 | Aug 1 – Oct 31, 2026 |
| FY27 Q4 | Nov 1 – Jan 31, 2027 |

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| "Data Server Offline" in UI | Start the server: `cd server && python3 app.py` |
| No AEs showing | Check server logs — Snowflake SSO may need re-auth (browser popup) |
| Portuguese/foreign language page | That's Okta SSO — just authenticate and close the tab |
| `GTM_REPO not found` | Set `export GTM_REPO=/path/to/gtm-ops-claude` or clone it as a sibling |
| `ModuleNotFoundError: flask` | Run `pip3 install flask flask-cors snowflake-connector-python pandas python-dotenv` |
