#!/bin/bash
# Local test script for roblox-downloader

set -e

echo "==================================="
echo "Roblox Downloader - Local Test"
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
echo "Running download with VISIBLE browser..."
echo "Watch the browser window to see what happens!"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run with visible browser
export HEADLESS=false
export PYTHONUNBUFFERED=1

python download_roblox.py --output-dir ./downloads --extract

echo ""
echo "==================================="
echo "Test complete!"
echo "Check ./downloads for results"
echo "==================================="
