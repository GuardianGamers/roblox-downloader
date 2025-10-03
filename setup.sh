#!/bin/bash

# Setup script for Roblox APK Downloader

echo "Setting up Roblox APK Downloader..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed"
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
echo "Installing Playwright browsers..."
playwright install chromium

echo ""
echo "✅ Setup complete!"
echo ""
echo "To use the downloader:"
echo "  1. Activate the virtual environment: source venv/bin/activate"
echo "  2. Run the script: python download_roblox.py"
echo "  3. Or with extraction: python download_roblox.py --extract"
echo ""

