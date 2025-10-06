#!/bin/bash
# Quick test script for gameservers update

set -e

echo "================================================"
echo "Testing Gameservers Update Locally"
echo "================================================"

# Ensure virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
fi

# Activate venv
source venv/bin/activate

# Install dependencies if needed
echo "Installing dependencies..."
pip install -q boto3 requests

echo ""
echo "================================================"
echo "Available test modes:"
echo "================================================"
echo "1. Test Roblox charts scraper only"
echo "2. Test AI moderation (requires Bedrock access)"
echo "3. Test full flow (DRY RUN - no S3 writes)"
echo "4. Test full flow (LIVE - writes to S3)"
echo ""

read -p "Select test mode (1-4): " choice

case $choice in
    1)
        echo "Testing Roblox charts scraper..."
        python3 test_gameservers_local.py --test scraper --no-s3
        ;;
    2)
        echo "Testing AI moderation..."
        python3 test_gameservers_local.py --test ai --no-s3
        ;;
    3)
        echo "Testing full flow (DRY RUN)..."
        python3 test_gameservers_local.py --test full --dry-run
        ;;
    4)
        read -p "Enter S3 bucket name (or press Enter for default): " bucket
        if [ -n "$bucket" ]; then
            echo "Testing full flow (LIVE) with bucket: $bucket"
            python3 test_gameservers_local.py --test full --live --bucket "$bucket"
        else
            echo "Testing full flow (LIVE) with default bucket"
            python3 test_gameservers_local.py --test full --live
        fi
        ;;
    *)
        echo "Invalid choice. Running all tests (DRY RUN)..."
        python3 test_gameservers_local.py --test all --dry-run
        ;;
esac

echo ""
echo "================================================"
echo "Test complete!"
echo "================================================"
