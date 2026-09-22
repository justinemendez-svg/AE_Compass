# AE Compass — new AppFoundry app

This is a new deployment package for AE Compass. It is independent from the
existing Vision app and does not modify or import Vision code.

## What is included

- React/Vite dashboard, built into `dist/renderer`.
- Flask/Gunicorn API in `server/app.py`.
- Existing AE Compass API contract, including dashboard tabs, account
  landscape, Gong lookup, notes/actions, and Ask Compass.
- Runtime data directory (`AE_COMPASS_DATA_DIR`) and runtime state directory
  (`AE_COMPASS_STATE_DIR`) are explicit deployment inputs.

## AppFoundry setup

1. Create a new application/repository named `ae-compass` in AppFoundry. Do
   not select or edit the existing `vision` component.
2. Point the source at this repository and build with the included `Dockerfile`.
3. Provide the verified CSV extracts in the configured data directory:
   `workday_hierarchy_chris_donato.csv`,
   `clari_forecast_current_quarter.csv`,
   `gtmsi_pipeline_current_quarter.csv`, and
   `salesforce_opportunities_current_quarter.csv`.
4. Add `OPENAI_API_KEY` as an AppFoundry secret and set
   `OPENAI_BASE_URL=https://ai-gateway.zende.sk/v1` for Ask Compass.
5. Set the signed-in identity header mapping to `X-Forwarded-Email` if the
   platform does not inject it automatically.
6. Health check: `GET /api/health`. The container listens on `$PORT`.

### Uploading the complete app, including Ask Compass

Use the AppFoundry **Docker App (Bring Your Own Container)** template:

1. Create a new app named `AE Compass` (or `ae-compass`) in the AppFoundry
   environment where you want the app to live.
2. Upload/attach the repository contents from this folder. Keep the included
   `Dockerfile`; do not upload only `dist/` because the API and Ask Compass
   live under `server/`.
3. Confirm the container command uses the included Gunicorn entrypoint:
   `server.app:app`.
4. Add the AI Agent secret/configuration: `OPENAI_API_KEY` as a secret,
   `OPENAI_BASE_URL=https://ai-gateway.zende.sk/v1`, and
   `OPENAI_ASSISTANT_MODEL=gpt-5.5`.
5. Deploy, open `/api/health`, then test Ask Compass from the floating bot.

The bot is part of this repository; it is not a separate frontend upload. It
uses the same server-side, scoped data adapters as the dashboard. If the
AppFoundry environment does not authorize the AI Gateway or the data sources,
the dashboard can still deploy, but Ask Compass/live data will report a clear
connection error rather than inventing data.

The app starts safely with snapshot data and no live-source credentials. Live
Salesforce/Snowflake/Gong access should be added only through approved,
read-only runtime connections; no secrets or private extracts belong in Git.

## Local AE Compass data folder

The local adapter already defaults to:

`/Users/justine.mendez/Library/CloudStorage/GoogleDrive-justine.mendez@zendesk.com/Shared drives/GTM Ops/APAC/AE Compass`

Set `AE_COMPASS_DATA_DIR` explicitly in other environments. The Admin → Data
Management tab now reads this folder and shows the source files, modification
times, and download links. It does not expose arbitrary filesystem paths or
allow path traversal.

To refresh the folder and generate the compact AppFoundry bundle after the
approved source pulls are available:

```bash
python3 server/refresh_appfoundry_data.py --pull-live
```

When you message “update AE Compass data,” I can run this refresh workflow in
the local repository, verify the output, and report exactly which files and
timestamps changed. A deployed AppFoundry container cannot directly read a
personal Google Drive path; it needs an approved mount, sync job, or live
read-only connector.

## Local verification

```bash
npm ci
npm run build
AE_COMPASS_DATA_DIR=/path/to/verified/exports \
AE_COMPASS_STATE_DIR=/tmp/ae-compass-state \
gunicorn --bind=127.0.0.1:8080 server.app:app
```

The portal creation step itself requires an authenticated AppFoundry session.
This repository is the clean, new app source that can be selected there.
