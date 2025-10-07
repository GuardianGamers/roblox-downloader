#!/usr/bin/env python3
"""
Test AI moderation on existing gameservers.json data.
This bypasses the Roblox API fetching and focuses on testing AI moderation.
"""

import json
import os
import sys
from pathlib import Path

# Set up environment
os.environ['AWS_REGION'] = os.environ.get('AWS_REGION', 'us-east-1')

from update_gameservers import sanitize_description_with_ai, log

def test_ai_on_sample_games(num_games=5):
    """Test AI moderation on sample games from existing data."""
    
    # Load existing gameservers.json
    gameservers_file = Path("test_gameservers/2025-10-05/gameservers.json")
    
    if not gameservers_file.exists():
        print(f"❌ File not found: {gameservers_file}")
        return
    
    print("="*60)
    print("AI MODERATION TEST")
    print("="*60)
    print(f"Loading games from: {gameservers_file}")
    
    with open(gameservers_file, 'r') as f:
        games = json.load(f)
    
    print(f"✅ Loaded {len(games)} games")
    print(f"Testing AI moderation on first {num_games} games...\n")
    
    results = []
    
    for i, game in enumerate(games[:num_games], 1):
        name = game.get('name', 'Unknown')
        description = game.get('description', '')
        place_id = game.get('place_id', 'N/A')
        
        print(f"\n{'='*60}")
        print(f"Game {i}/{num_games}: {name}")
        print(f"Place ID: {place_id}")
        print(f"{'='*60}")
        print(f"Original Description ({len(description)} chars):")
        print(f"  {description[:200]}{'...' if len(description) > 200 else ''}\n")
        
        try:
            result = sanitize_description_with_ai(description, name)
            
            print(f"✅ AI Analysis Complete:")
            print(f"  ✓ Appropriate for <13: {result['is_appropriate_for_under13']}")
            print(f"  ✓ Flags: {result.get('flags', [])}")
            print(f"  ✓ Reasoning: {result.get('reasoning', 'N/A')}")
            print(f"\n  Sanitized Description ({len(result['sanitized_description'])} chars):")
            print(f"  {result['sanitized_description'][:200]}{'...' if len(result['sanitized_description']) > 200 else ''}")
            
            if not result['is_appropriate_for_under13']:
                print(f"\n  ⚠️  EXCLUDED: {result.get('reasoning', 'N/A')}")
            
            results.append({
                'game': name,
                'place_id': place_id,
                'appropriate': result['is_appropriate_for_under13'],
                'flags': result.get('flags', []),
                'reasoning': result.get('reasoning', '')
            })
            
        except Exception as e:
            print(f"❌ AI moderation failed: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    approved = sum(1 for r in results if r['appropriate'])
    excluded = len(results) - approved
    
    print(f"Total tested: {len(results)}")
    print(f"✅ Approved: {approved}")
    print(f"❌ Excluded: {excluded}")
    
    if excluded > 0:
        print(f"\nExcluded games:")
        for r in results:
            if not r['appropriate']:
                print(f"  - {r['game']} (place_id: {r['place_id']})")
                print(f"    Reason: {r['reasoning']}")
                print(f"    Flags: {r['flags']}")
    
    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("="*60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Test AI moderation on existing games')
    parser.add_argument('--num-games', type=int, default=10, 
                       help='Number of games to test (default: 10)')
    
    args = parser.parse_args()
    
    try:
        test_ai_on_sample_games(num_games=args.num_games)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
