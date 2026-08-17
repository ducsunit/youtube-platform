#!/usr/bin/env bash
# Start Frontend Dev Server
# Usage: ./start-frontend.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_DIR/apps/web"

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "❌ Frontend directory not found: $FRONTEND_DIR"
  exit 1
fi

cd "$FRONTEND_DIR"

echo "🎨 Starting Frontend Dev Server..."
echo "📍 Port: 5173"
echo "🔗 Proxy: /api → http://127.0.0.1:8787"
echo ""

# Check if node_modules exists
if [[ ! -d "node_modules" ]]; then
  echo "⚠️  node_modules not found, installing dependencies..."
  npm install
  echo ""
fi

echo "🚀 Frontend running at http://localhost:5173"
echo ""
echo "Pages:"
echo "  /              - Runs list & create new run"
echo "  /runs/{id}     - Run detail with live logs"
echo "  /data          - Pull YouTube data"
echo ""
echo "Press Ctrl+C to stop"
echo ""

exec npm run dev
