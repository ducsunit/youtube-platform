#!/usr/bin/env bash
# Start Backend API Server
# Usage: ./start-backend.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "🔧 Starting Backend API Server..."
echo "📍 Port: 8787"
echo "📂 Working dir: $PROJECT_DIR"
echo ""

# Check if venv exists
if [[ ! -f ".venv/bin/python" ]]; then
  echo "❌ Virtual environment not found!"
  echo "   Run: python3 -m venv .venv && .venv/bin/pip install -e ."
  exit 1
fi

# Start API server
echo "🚀 Backend running at http://127.0.0.1:8787"
echo ""
echo "API Endpoints:"
echo "  GET  /api/runs              - List all runs"
echo "  POST /api/runs              - Create new run"
echo "  GET  /api/runs/{id}/status  - Get run status"
echo "  GET  /api/runs/{id}/logs    - Get run logs"
echo "  POST /api/runs/{id}/resume  - Resume run"
echo ""
echo "Press Ctrl+C to stop"
echo ""

exec .venv/bin/python -m youtube_pipeline
