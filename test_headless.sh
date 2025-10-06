#!/bin/bash
# Headless test script for roblox-downloader

set -e

echo "==================================="
echo "Roblox Downloader - Headless Test"
echo "==================================="
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "Installing dependencies..."
    pip install -q -r requirements.txt
    playwright install chromium
else
    source venv/bin/activate
fi

# Create downloads directory
mkdir -p ./downloads

echo ""
echo "Running download in HEADLESS mode..."
echo ""

# Run with headless browser
export HEADLESS=true
export PYTHONUNBUFFERED=1

python download_roblox.py --output-dir ./downloads --extract

echo ""
echo "==================================="
echo "Test complete!"
echo "Check ./downloads for results"
echo "==================================="
