#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "=========================================================="
echo "⚡ Starting ICT Predictive Signals Engine (Real-Time)"
echo "=========================================================="

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

export PYTHONPATH="$DIR:$PYTHONPATH"

echo "🚀 Opening Live Dashboard at http://localhost:8000"
echo "Press Ctrl+C to stop."

exec .venv/bin/python3 -m uvicorn src.server.app:app --host 0.0.0.0 --port 8000 --reload
