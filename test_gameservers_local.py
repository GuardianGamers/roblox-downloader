#!/usr/bin/env python3
"""
Local test script for gameservers update module.
Allows testing the full flow without deploying to AWS.
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path

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

def test_chart_scraper(pages=1, local_dir='./test_gameservers'):
    """Test 1: Fetch games from Roblox charts."""
    print("\n" + "="*60)
    print("TEST 1: Fetching games from Roblox charts")
    print("="*60)
    
    # Check if we already have today's gameservers.json
    today = datetime.utcnow().strftime('%Y-%m-%d')
    today_dir = Path(local_dir) / today
    gameservers_file = today_dir / 'gameservers.json'
    
    if gameservers_file.exists():
        print(f"📦 Loading existing games from {gameservers_file}")
        try:
            with open(gameservers_file, 'r') as f:
                games = json.load(f)
            print(f"✅ Loaded {len(games)} games from today's gameservers.json")
            print(f"\nSample game:")
            if games:
                sample = games[0]
                print(f"  Name: {sample.get('name', 'N/A')}")
                print(f"  Place ID: {sample.get('place_id', 'N/A')}")
            return games[:5]  # Return first 5 for AI testing
        except Exception as e:
            print(f"⚠️  Failed to load gameservers.json: {e}, fetching fresh...")
    
    # Fetch fresh games
    print(f"ℹ️  No gameservers.json found for {today}, fetching fresh...")
    games = fetch_latest_roblox_games(pages_per_category=pages)
    
    if games:
        print(f"✅ Successfully fetched {len(games)} games")
        
        # Save to today's gameservers.json
        today_dir.mkdir(parents=True, exist_ok=True)
        with open(gameservers_file, 'w') as f:
            json.dump(games, f, indent=2)
        print(f"💾 Saved games to: {gameservers_file}")
        
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

def test_full_flow(use_local=True):
    """Test 4: Run the full update flow."""
    print("\n" + "="*60)
    print("TEST 4: Full gameservers update flow")
    print("="*60)
    
    bucket_name = os.environ.get('BUCKET_NAME')
    local_dir = './test_gameservers' if use_local else None
    
    if use_local:
        print(f"\n✅ LOCAL MODE - Using directory: {local_dir}")
        print("Previous data will be loaded from test_gameservers/2025-10-05/")
        print("New data will be saved to test_gameservers/{today}/\n")
    else:
        print(f"\n⚠️  S3 MODE - Will write to S3 bucket: {bucket_name}\n")
    
    try:
        result = update_gameservers(
            bucket_name=bucket_name,
            s3_prefix="",
            local_dir=local_dir
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
    parser.add_argument('--use-s3', action='store_true', help='Use S3 instead of local directory')
    parser.add_argument('--local-dir', default='./test_gameservers', help='Local directory for testing (default: ./test_gameservers)')
    parser.add_argument('--pages', type=int, default=10, help='Number of pages to fetch per category (default: 10)')
    
    args = parser.parse_args()
    
    if args.bucket:
        os.environ['BUCKET_NAME'] = args.bucket
    
    use_local = not args.use_s3
    use_s3 = not args.no_s3 and args.use_s3
    
    print("="*60)
    print("GAMESERVERS LOCAL TEST")
    print("="*60)
    print(f"Bucket: {os.environ.get('BUCKET_NAME')}")
    print(f"AWS Region: {os.environ.get('AWS_REGION')}")
    print(f"Charts Scraper: {os.environ.get('CHARTS_SCRAPER_PATH')}")
    print(f"Local Dir: {args.local_dir}")
    print(f"Pages per category: {args.pages}")
    print(f"Mode: {'LOCAL' if use_local else 'S3'}")
    print("="*60)
    
    # Run tests based on selection
    games = []
    
    if args.test in ['scraper', 'all']:
        games = test_chart_scraper(pages=args.pages, local_dir=args.local_dir)
    
    if args.test in ['ai', 'all']:
        if not games:
            # Try to load from today's gameservers.json first
            today = datetime.utcnow().strftime('%Y-%m-%d')
            gameservers_file = Path(args.local_dir) / today / 'gameservers.json'
            
            if gameservers_file.exists():
                print(f"\n📦 Loading games from {gameservers_file} for AI test...")
                try:
                    with open(gameservers_file, 'r') as f:
                        games = json.load(f)[:5]  # First 5 for AI testing
                except Exception as e:
                    print(f"⚠️  Failed to load gameservers.json: {e}, fetching fresh...")
                    games = fetch_latest_roblox_games(pages_per_category=1)
            else:
                print(f"\n⚠️  No gameservers.json found for {today}, fetching sample games for AI test...")
                games = fetch_latest_roblox_games(pages_per_category=1)
        test_ai_moderation(games)
    
    if args.test in ['s3', 'all'] and use_s3:
        test_s3_operations(use_s3=True)
    
    if args.test in ['full', 'all']:
        test_full_flow(use_local=use_local)
    
    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60)

if __name__ == "__main__":
    main()
