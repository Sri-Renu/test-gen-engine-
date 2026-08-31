#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# start.sh — launch the Intelligent Test Generation Engine
#
# Usage:
#   chmod +x start.sh && ./start.sh
#
# Setup (first time):
#   pip install -r requirements.txt
#   cp .env.example .env          # add your ANTHROPIC_API_KEY
#   docker build -t test-gen-sandbox ./sandbox/   # only needed for mutation testing
# ─────────────────────────────────────────────────────────────────────────────

set -e

# Load .env if present
if [ -f .env ]; then
    set -a; source .env; set +a
    echo "✓ Loaded .env"
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo "✗  ANTHROPIC_API_KEY not set."
    echo "   Run:  export ANTHROPIC_API_KEY=sk-ant-..."
    echo "   Or:   cp .env.example .env  and fill it in"
    exit 1
fi

echo ""
echo "  🧬  Intelligent Test Generation Engine"
echo "  ──────────────────────────────────────"
echo "  Backend  →  http://localhost:8000"
echo "  Frontend →  http://localhost:8501"
echo "  API docs →  http://localhost:8000/docs"
echo ""

# Free up ports if already in use
kill $(lsof -ti:8000) 2>/dev/null && echo "  Freed port 8000" || true
kill $(lsof -ti:8501) 2>/dev/null && echo "  Freed port 8501" || true
sleep 1

# Start FastAPI backend
echo "  Starting backend..."
uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# Wait until backend is actually ready (up to 15s)
echo "  Waiting for backend..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "  ✓ Backend ready"
        break
    fi
    sleep 1
done

# Start Streamlit frontend
echo "  Starting frontend..."
streamlit run frontend/app.py \
    --server.port 8501 \
    --server.headless true \
    --browser.gatherUsageStats false \
    --theme.base dark &
FRONTEND_PID=$!

echo ""
echo "  ✓ Both services running."
echo "  Open http://localhost:8501 in your browser."
echo "  Press Ctrl+C to stop."
echo ""

# Wait and clean up on exit
trap "echo ''; echo 'Shutting down...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait $BACKEND_PID $FRONTEND_PID