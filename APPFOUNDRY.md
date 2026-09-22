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

The app starts safely with snapshot data and no live-source credentials. Live
Salesforce/Snowflake/Gong access should be added only through approved,
read-only runtime connections; no secrets or private extracts belong in Git.

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
