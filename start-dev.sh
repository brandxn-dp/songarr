#!/usr/bin/env bash
# Songarr development startup script
set -e

echo "==> Starting Songarr in dev mode..."

# Start backend
echo "==> Starting FastAPI backend on :8000"
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
cd ..

# Start frontend
echo "==> Starting Vite frontend on :3000"
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "  Songarr running:"
echo "    Frontend: http://localhost:3000"
echo "    Backend:  http://localhost:8000"
echo "    API docs: http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
