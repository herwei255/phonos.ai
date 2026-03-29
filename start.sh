#!/bin/bash
# ── Meeting Notes Tool – Start Script ─────────────────────────────────────────

echo ""
echo "🎙️  Meeting Notes Tool – Setup Check"
echo "─────────────────────────────────────"

# 1. Check .env exists
if [ ! -f ".env" ]; then
  echo "⚠️  No .env file found. Creating one from .env.example..."
  cp .env.example .env
  echo ""
  echo "👉  ACTION REQUIRED: Open .env and add your API keys, then run this script again."
  echo "    nano .env"
  echo ""
  exit 1
fi

# 2. Check API keys are filled in
if grep -qE "\.\.\." .env; then
  echo "⚠️  Your .env still has placeholder keys."
  echo "    Open .env, replace the placeholders with your real API keys, and run again."
  exit 1
fi

# 3. Install dependencies
echo "📦  Installing Python dependencies..."
pip3 install -r requirements.txt -q

echo ""
echo "✅  All set! Starting the app..."
echo ""
python3 run.py
