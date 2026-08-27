#!/bin/bash
# Start the SalesPilot data server (connects to Snowflake)
cd "$(dirname "$0")"
echo "Starting SalesPilot data server..."
echo "Connecting to Snowflake (will open browser for SSO if needed)..."
python3 app.py
