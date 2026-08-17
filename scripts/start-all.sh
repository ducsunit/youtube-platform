#!/usr/bin/env bash
# Start Full Stack - Backend + Frontend
# Usage: ./start-all.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🚀 Starting Full Stack Application"
echo "=================================="
echo ""

# Trap to kill all background processes on exit
trap 'kill $(jobs -p) 2>/dev/null' EXIT

# Start backend in background
echo "1️⃣  Starting Backend API Server..."
"$PROJECT_DIR/start-backend.sh" &
BACKEND_PID=$!

# Wait for backend to start
sleep 3

# Check if backend is running
if ! kill -0 $BACKEND_PID 2>/dev/null; then
  echo "❌ Backend failed to start"
  exit 1
fi

echo "✅ Backend running (PID: $BACKEND_PID)"
echo ""

# Start frontend in background
echo "2️⃣  Starting Frontend Dev Server..."
"$PROJECT_DIR/start-frontend.sh" &
FRONTEND_PID=$!

echo ""
echo "=================================="
echo "✅ Full Stack Running!"
echo ""
echo "🔧 Backend:  http://127.0.0.1:8787"
echo "🎨 Frontend: http://localhost:5173"
echo ""
echo "Open your browser: http://localhost:5173"
echo ""
echo "Press Ctrl+C to stop all services"
echo "=================================="
echo ""

# Wait for any process to exit
wait

# If we get here, both processes died
echo ""
echo "⚠️  Services stopped."
exit 0
