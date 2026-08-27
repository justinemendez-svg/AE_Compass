#!/bin/bash
# SalesPilot v2 — Setup for App Foundry / Cloud Run deployment
# Prerequisites: Node.js 18+, Python 3.9+, PostgreSQL

set -e

echo "SalesPilot Setup"
echo "================"

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "Node.js not found. Install via: brew install node"
    exit 1
fi
echo "Node.js $(node --version)"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Python3 not found."
    exit 1
fi
echo "Python $(python3 --version)"

# Install Node dependencies
echo ""
echo "Installing Node.js dependencies..."
npm install --silent

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip3 install -q flask flask-cors psycopg2-binary python-dotenv gunicorn

# Check for .env
if [ ! -f "server/.env" ]; then
    echo ""
    echo "No server/.env found. Creating from example..."
    cp server/.env.example server/.env
    echo "  Edit server/.env with your PostgreSQL credentials and admin password."
fi

echo ""
echo "Setup complete!"
echo ""
echo "Local development:"
echo "  1. Start PostgreSQL (brew services start postgresql)"
echo "  2. Create database: createdb salespilot"
echo "  3. Edit server/.env with your DB credentials"
echo "  4. Terminal 1: cd server && python3 app.py"
echo "  5. Terminal 2: npm run dev"
echo "  6. Open http://localhost:5173"
echo ""
echo "The Vite dev server proxies /api to the Flask server on :8080."
echo ""
echo "Production build:"
echo "  docker build -t salespilot ."
echo "  docker run -p 8080:8080 --env-file server/.env salespilot"
