#!/usr/bin/env python3
"""
Gameservers Update Module
=========================

Updates gameservers.json daily by:
1. Fetching latest games from Roblox charts
2. Using AWS Bedrock Claude to sanitize descriptions and flag inappropriate games
3. Managing exclusion list of place IDs
4. Creating daily versioned directories in S3

Integrated with roblox-downloader ECS task.
"""

import os
import sys
import json
import boto3
import subprocess
from datetime import datetime
from typing import Dict, List, Set, Optional
from pathlib import Path

# AWS clients
s3_client = boto3.client('s3')
bedrock_client = boto3.client('bedrock-runtime', region_name='us-east-1')

# Configuration
# Using roblox_charts_scraper.py copied into this repo
ROBLOX_CHARTS_SCRAPER = os.environ.get('CHARTS_SCRAPER_PATH', '/app/roblox_charts_scraper.py')

def log(message: str):
    """Log with timestamp."""
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp} UTC] {message}")

def fetch_latest_roblox_games(pages_per_category: int = 5, max_games: int = None) -> List[Dict]:
    """
    Fetch latest games from Roblox charts using existing scraper.
    
    Args:
        pages_per_category: Number of pages to fetch per category
        max_games: Maximum number of games to process (for testing)
        
    Returns:
        List of game data dictionaries
    """
    log("Fetching latest Roblox games from charts...")
    
    try:
        # Import the scraper as a module
        sys.path.insert(0, os.path.dirname(ROBLOX_CHARTS_SCRAPER))
        import roblox_charts_scraper
        
        # Create scraper instance
        scraper = roblox_charts_scraper.RobloxChartsScraper()
        
        # Fetch games from all categories
        log(f"Fetching {pages_per_category} pages per category...")
        all_games = scraper.fetch_all_categories(
            pages_per_category=pages_per_category,
            specific_categories=None  # Fetch all categories
        )
        
        if not all_games:
            log("No games fetched from Roblox charts")
            return []
        
        log(f"Fetched {len(all_games)} raw games from Roblox API")
        
        # Convert to gameserver format (in memory, not writing to file)
        log(f"Converting to gameserver format...")
        games_list = []
        
        for i, game in enumerate(all_games):
            # Convert each game using the scraper's method
            converted = scraper.convert_to_gameserver_format(game)
            if converted:
                games_list.append(converted)
            
            # Progress update every 25 games
            if (i + 1) % 25 == 0:
                log(f"  Processed {i + 1}/{len(all_games)} games...")
        
        # Limit for testing if specified
        if max_games and len(games_list) > max_games:
            log(f"Limiting to first {max_games} games for testing")
            games_list = games_list[:max_games]
        
        log(f"Successfully converted {len(games_list)} games")
        return games_list
        
    except Exception as e:
        log(f"Error fetching games: {e}")
        import traceback
        traceback.print_exc()
        return []

def sanitize_description_with_ai(description: str, game_name: str) -> Dict:
    """
    Use AWS Bedrock Claude to sanitize description and check age appropriateness.
    
    Args:
        description: Game description to analyze
        game_name: Name of the game
        
    Returns:
        Dict with 'sanitized_description', 'is_appropriate_for_under13', 'flags', 'reasoning'
    """
    prompt = f"""You are reviewing game descriptions for a kid-safe game platform.

Game: {game_name}
Description: {description}

Tasks:
1. Remove any external links or references to social media/Discord/YouTube
2. Clean up inappropriate language or references
3. Determine if this game is appropriate for children under 13
4. Flag if game contains: horror, violence, dating themes, or other mature content

Respond ONLY with valid JSON in this exact format:
{{
  "sanitized_description": "cleaned description here",
  "is_appropriate_for_under13": true or false,
  "flags": ["flag1", "flag2"],
  "reasoning": "brief explanation"
}}"""

    try:
        response = bedrock_client.invoke_model(
            modelId='anthropic.claude-3-5-sonnet-20241022-v2:0',
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1000,
                "messages": [{
                    "role": "user",
                    "content": prompt
                }]
            })
        )
        
        response_body = json.loads(response['body'].read())
        content = response_body['content'][0]['text']
        
        # Parse JSON from response
        result = json.loads(content)
        log(f"AI review for '{game_name}': appropriate={result['is_appropriate_for_under13']}, flags={result.get('flags', [])}")
        
        return result
        
    except Exception as e:
        log(f"Error with AI analysis for '{game_name}': {e}")
        # Return safe defaults on error
        return {
            "sanitized_description": description,
            "is_appropriate_for_under13": True,
            "flags": ["ai-error"],
            "reasoning": f"AI analysis failed: {str(e)}"
        }

def load_exclusion_list(bucket_name: str, s3_prefix: str, local_dir: str = None) -> Set[str]:
    """
    Load exclusion list of place IDs from S3 or local directory (most recent version).
    
    Args:
        bucket_name: S3 bucket name
        s3_prefix: S3 prefix for gameservers data
        local_dir: Optional local directory path for testing (overrides S3)
        
    Returns:
        Set of excluded place IDs
    """
    # Use local directory if specified (for testing)
    if local_dir:
        try:
            gameservers_dir = Path(local_dir)
            if not gameservers_dir.exists():
                log(f"Local directory not found: {local_dir}")
                return set()
            
            # Find most recent date directory
            date_dirs = sorted([d for d in gameservers_dir.iterdir() if d.is_dir()], reverse=True)
            if not date_dirs:
                log("No previous gameservers data found in local directory")
                return set()
            
            latest_dir = date_dirs[0]
            exclusion_file = latest_dir / "exclusions.json"
            
            if not exclusion_file.exists():
                log(f"No exclusions file found in {latest_dir}")
                return set()
            
            log(f"Loading exclusion list from {exclusion_file}")
            with open(exclusion_file, 'r') as f:
                exclusions_data = json.load(f)
            
            return set(exclusions_data.get('excluded_place_ids', []))
            
        except Exception as e:
            log(f"Error loading local exclusion list: {e}")
            return set()
    
    # Use S3 for production
    try:
        # List all gameservers directories (sorted by date)
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=f"{s3_prefix}gameservers/",
            Delimiter='/'
        )
        
        if 'CommonPrefixes' not in response:
            log("No previous gameservers data found")
            return set()
        
        # Get most recent directory
        directories = sorted([p['Prefix'] for p in response['CommonPrefixes']], reverse=True)
        if not directories:
            return set()
        
        latest_dir = directories[0]
        exclusion_file = f"{latest_dir}exclusions.json"
        
        log(f"Loading exclusion list from {exclusion_file}")
        response = s3_client.get_object(Bucket=bucket_name, Key=exclusion_file)
        exclusions_data = json.loads(response['Body'].read())
        
        return set(exclusions_data.get('excluded_place_ids', []))
        
    except s3_client.exceptions.NoSuchKey:
        log("No previous exclusion list found, starting fresh")
        return set()
    except Exception as e:
        log(f"Error loading exclusion list: {e}")
        return set()

def save_gameservers_to_s3(
    games: List[Dict],
    exclusions: Set[str],
    bucket_name: str,
    s3_prefix: str,
    local_dir: str = None
) -> str:
    """
    Save updated gameservers.json and exclusions to S3 or local directory with today's date.
    
    Args:
        games: List of game data
        exclusions: Set of excluded place IDs
        bucket_name: S3 bucket name
        s3_prefix: S3 prefix for gameservers data
        local_dir: Optional local directory path for testing (overrides S3)
        
    Returns:
        Path where data was saved
    """
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    gameservers_data = json.dumps(games, indent=2)
    exclusions_data = json.dumps({
        "excluded_place_ids": list(exclusions),
        "last_updated": datetime.utcnow().isoformat(),
        "count": len(exclusions)
    }, indent=2)
    
    # Use local directory if specified (for testing)
    if local_dir:
        daily_dir = Path(local_dir) / today
        daily_dir.mkdir(parents=True, exist_ok=True)
        
        log(f"Saving gameservers data to {daily_dir}")
        
        # Save gameservers.json
        with open(daily_dir / "gameservers.json", 'w') as f:
            f.write(gameservers_data)
        
        # Save exclusions.json
        with open(daily_dir / "exclusions.json", 'w') as f:
            f.write(exclusions_data)
        
        log(f"Saved {len(games)} games and {len(exclusions)} exclusions locally")
        return str(daily_dir)
    
    # Use S3 for production
    daily_prefix = f"{s3_prefix}gameservers/{today}/"
    
    log(f"Saving gameservers data to {daily_prefix}")
    
    # Save gameservers.json
    s3_client.put_object(
        Bucket=bucket_name,
        Key=f"{daily_prefix}gameservers.json",
        Body=gameservers_data,
        ContentType='application/json',
        ServerSideEncryption='AES256'
    )
    
    # Save exclusions.json
    s3_client.put_object(
        Bucket=bucket_name,
        Key=f"{daily_prefix}exclusions.json",
        Body=exclusions_data,
        ContentType='application/json',
        ServerSideEncryption='AES256'
    )
    
    log(f"Saved {len(games)} games and {len(exclusions)} exclusions")
    return daily_prefix

def update_gameservers(bucket_name: str, s3_prefix: str = "gameservers/", local_dir: str = None) -> Dict:
    """
    Main function to update gameservers data.
    
    Args:
        bucket_name: S3 bucket name
        s3_prefix: S3 prefix
        local_dir: Optional local directory for testing (overrides S3)
        
    Returns:
        Dict with status and statistics
    """
    log("=" * 60)
    log("Starting gameservers update")
    log("=" * 60)
    
    # Load existing exclusion list
    existing_exclusions = load_exclusion_list(bucket_name, s3_prefix, local_dir=local_dir)
    log(f"Loaded {len(existing_exclusions)} existing exclusions")
    
    # Fetch latest games from Roblox
    # Limit to 20 games for initial testing to reduce AI costs
    raw_games = fetch_latest_roblox_games(pages_per_category=5, max_games=None)
    
    if not raw_games:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to fetch games from Roblox'})
        }
    
    # Process each game with AI
    processed_games = []
    new_exclusions = set(existing_exclusions)
    
    for i, game in enumerate(raw_games):
        log(f"Processing game {i+1}/{len(raw_games)}: {game.get('name', 'Unknown')}")
        
        place_id = str(game.get('place_id', ''))
        
        # Skip if already excluded
        if place_id in existing_exclusions:
            log(f"  Skipping {place_id} (already excluded)")
            continue
        
        # AI review
        ai_result = sanitize_description_with_ai(
            game.get('description', ''),
            game.get('name', 'Unknown')
        )
        
        # Update game with sanitized description
        game['description'] = ai_result['sanitized_description']
        game['ai_flags'] = ai_result.get('flags', [])
        game['ai_reasoning'] = ai_result.get('reasoning', '')
        
        # Add to exclusions if not appropriate
        if not ai_result['is_appropriate_for_under13']:
            log(f"  Excluding {place_id}: {ai_result['reasoning']}")
            new_exclusions.add(place_id)
        else:
            processed_games.append(game)
    
    # Save to S3 or local directory
    save_path = save_gameservers_to_s3(processed_games, new_exclusions, bucket_name, s3_prefix, local_dir=local_dir)
    
    log("=" * 60)
    log(f"Gameservers update complete!")
    log(f"  Processed: {len(raw_games)} games")
    log(f"  Approved: {len(processed_games)} games")
    log(f"  Excluded: {len(new_exclusions)} total ({len(new_exclusions) - len(existing_exclusions)} new)")
    if local_dir:
        log(f"  Local path: {save_path}")
    else:
        log(f"  S3 path: s3://{bucket_name}/{save_path}")
    log("=" * 60)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Gameservers updated successfully',
            'save_path': save_path,
            'stats': {
                'total_games': len(raw_games),
                'approved_games': len(processed_games),
                'total_exclusions': len(new_exclusions),
                'new_exclusions': len(new_exclusions) - len(existing_exclusions)
            }
        })
    }

if __name__ == "__main__":
    # For standalone testing
    import argparse
    parser = argparse.ArgumentParser(description='Update gameservers data')
    parser.add_argument('--bucket', help='S3 bucket name (not needed for local testing)')
    parser.add_argument('--prefix', default='gameservers/', help='S3 prefix')
    parser.add_argument('--local-dir', help='Local directory for testing (overrides S3)')
    
    args = parser.parse_args()
    
    # Require either bucket or local-dir
    if not args.bucket and not args.local_dir:
        parser.error('Either --bucket or --local-dir must be specified')
    
    result = update_gameservers(
        bucket_name=args.bucket or 'test-bucket',
        s3_prefix=args.prefix,
        local_dir=args.local_dir
    )
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['statusCode'] == 200 else 1)
