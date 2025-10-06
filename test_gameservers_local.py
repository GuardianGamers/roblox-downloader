#!/usr/bin/env python3
"""
Local test script for gameservers update module.
Allows testing the full flow without deploying to AWS.
"""

import os
import sys
import json
from datetime import datetime

# Set up local testing environment
os.environ['BUCKET_NAME'] = os.environ.get('TEST_BUCKET_NAME', 'test-roblox-local')
os.environ['AWS_REGION'] = os.environ.get('AWS_REGION', 'us-east-1')
os.environ['CHARTS_SCRAPER_PATH'] = './roblox_charts_scraper.py'

from update_gameservers import (
    update_gameservers,
    fetch_latest_roblox_games,
    sanitize_description_with_ai,
    load_exclusion_list,
    save_gameservers_to_s3,
    log
)

def test_chart_scraper():
    """Test 1: Fetch games from Roblox charts."""
    print("\n" + "="*60)
    print("TEST 1: Fetching games from Roblox charts")
    print("="*60)
    
    games = fetch_latest_roblox_games(pages_per_category=1)  # Just 1 page for testing
    
    if games:
        print(f"✅ Successfully fetched {len(games)} games")
        print(f"\nSample game:")
        sample = games[0]
        print(f"  Name: {sample.get('name', 'N/A')}")
        print(f"  Place ID: {sample.get('place_id', 'N/A')}")
        print(f"  Description: {sample.get('description', 'N/A')[:100]}...")
        print(f"  Categories: {sample.get('categories', [])}")
        return games[:5]  # Return first 5 for AI testing
    else:
        print("❌ Failed to fetch games")
        return []

def test_ai_moderation(games):
    """Test 2: Test AI moderation on sample games."""
    print("\n" + "="*60)
    print("TEST 2: Testing AI moderation on sample games")
    print("="*60)
    
    if not games:
        print("⚠️  No games to test")
        return
    
    for i, game in enumerate(games[:3], 1):  # Test first 3 games
        print(f"\n--- Game {i}: {game.get('name', 'Unknown')} ---")
        print(f"Original description: {game.get('description', 'N/A')[:150]}...")
        
        try:
            result = sanitize_description_with_ai(
                game.get('description', ''),
                game.get('name', 'Unknown')
            )
            
            print(f"\n✅ AI Result:")
            print(f"  Appropriate for <13: {result['is_appropriate_for_under13']}")
            print(f"  Flags: {result.get('flags', [])}")
            print(f"  Reasoning: {result.get('reasoning', 'N/A')}")
            print(f"  Sanitized desc: {result['sanitized_description'][:150]}...")
            
        except Exception as e:
            print(f"❌ AI moderation failed: {e}")

def test_s3_operations(use_s3=True):
    """Test 3: Test S3 operations (load/save exclusions)."""
    print("\n" + "="*60)
    print("TEST 3: Testing S3 operations")
    print("="*60)
    
    bucket_name = os.environ.get('BUCKET_NAME')
    
    if not use_s3:
        print("⚠️  Skipping S3 operations (use_s3=False)")
        return
    
    try:
        # Try to load existing exclusions
        print(f"\nAttempting to load exclusions from s3://{bucket_name}/gameservers/")
        exclusions = load_exclusion_list(bucket_name, "")
        print(f"✅ Loaded {len(exclusions)} existing exclusions")
        if exclusions:
            print(f"  Sample exclusions: {list(exclusions)[:5]}")
    except Exception as e:
        print(f"⚠️  Could not load exclusions (likely first run): {e}")

def test_full_flow(dry_run=True):
    """Test 4: Run the full update flow."""
    print("\n" + "="*60)
    print("TEST 4: Full gameservers update flow")
    print("="*60)
    
    bucket_name = os.environ.get('BUCKET_NAME')
    
    if dry_run:
        print("\n⚠️  DRY RUN MODE - No data will be saved to S3")
        print("Set dry_run=False to actually save to S3\n")
    
    try:
        result = update_gameservers(
            bucket_name=bucket_name,
            s3_prefix=""
        )
        
        print("\n✅ Full flow completed!")
        print(json.dumps(json.loads(result['body']), indent=2))
        
    except Exception as e:
        print(f"❌ Full flow failed: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Main test runner."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Test gameservers update locally')
    parser.add_argument('--test', choices=['scraper', 'ai', 's3', 'full', 'all'], 
                       default='all', help='Which test to run')
    parser.add_argument('--bucket', help='S3 bucket name (default: test-roblox-local)')
    parser.add_argument('--no-s3', action='store_true', help='Skip S3 operations')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no S3 writes)', default=True)
    parser.add_argument('--live', action='store_true', help='Actually write to S3 (disables dry-run)')
    
    args = parser.parse_args()
    
    if args.bucket:
        os.environ['BUCKET_NAME'] = args.bucket
    
    dry_run = not args.live
    use_s3 = not args.no_s3
    
    print("="*60)
    print("GAMESERVERS LOCAL TEST")
    print("="*60)
    print(f"Bucket: {os.environ.get('BUCKET_NAME')}")
    print(f"AWS Region: {os.environ.get('AWS_REGION')}")
    print(f"Charts Scraper: {os.environ.get('CHARTS_SCRAPER_PATH')}")
    print(f"S3 Operations: {'Enabled' if use_s3 else 'Disabled'}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE (will write to S3)'}")
    print("="*60)
    
    # Run tests based on selection
    games = []
    
    if args.test in ['scraper', 'all']:
        games = test_chart_scraper()
    
    if args.test in ['ai', 'all']:
        if not games:
            print("\n⚠️  Fetching sample games for AI test...")
            games = fetch_latest_roblox_games(pages_per_category=1)
        test_ai_moderation(games)
    
    if args.test in ['s3', 'all'] and use_s3:
        test_s3_operations(use_s3=True)
    
    if args.test in ['full', 'all']:
        if not use_s3:
            print("\n⚠️  Full flow test requires S3, skipping")
        else:
            test_full_flow(dry_run=dry_run)
    
    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60)

if __name__ == "__main__":
    main()
