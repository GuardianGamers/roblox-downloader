#!/bin/bash
# Quick version check test (headless is fine for this)

set -e

echo "==================================="
echo "Roblox Version Check Test"
echo "==================================="

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -q -r requirements.txt
    playwright install chromium
else
    source venv/bin/activate
fi

mkdir -p ./downloads

echo ""
echo "Checking current Roblox version..."
echo ""

export PYTHONUNBUFFERED=1

python download_roblox.py --output-dir ./downloads --check-only

echo ""
echo "==================================="
