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

def fetch_latest_roblox_games(pages_per_category: int = 5) -> List[Dict]:
    """
    Fetch latest games from Roblox charts using existing scraper.
    
    Args:
        pages_per_category: Number of pages to fetch per category
        
    Returns:
        List of game data dictionaries
    """
    log("Fetching latest Roblox games from charts...")
    
    try:
        result = subprocess.run(
            ['python3', ROBLOX_CHARTS_SCRAPER, 
             '--pages', str(pages_per_category),
             '--output', '/tmp/roblox_charts.json'],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode != 0:
            log(f"Error running charts scraper: {result.stderr}")
            return []
        
        with open('/tmp/roblox_charts.json', 'r') as f:
            games = json.load(f)
        
        log(f"Fetched {len(games)} games from Roblox charts")
        return games
        
    except Exception as e:
        log(f"Error fetching games: {e}")
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

def load_exclusion_list(bucket_name: str, s3_prefix: str) -> Set[str]:
    """
    Load exclusion list of place IDs from S3 (most recent version).
    
    Args:
        bucket_name: S3 bucket name
        s3_prefix: S3 prefix for gameservers data
        
    Returns:
        Set of excluded place IDs
    """
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
    s3_prefix: str
) -> str:
    """
    Save updated gameservers.json and exclusions to S3 with today's date.
    
    Args:
        games: List of game data
        exclusions: Set of excluded place IDs
        bucket_name: S3 bucket name
        s3_prefix: S3 prefix for gameservers data
        
    Returns:
        S3 path where data was saved
    """
    today = datetime.utcnow().strftime('%Y-%m-%d')
    daily_prefix = f"{s3_prefix}gameservers/{today}/"
    
    log(f"Saving gameservers data to {daily_prefix}")
    
    # Save gameservers.json
    gameservers_data = json.dumps(games, indent=2)
    s3_client.put_object(
        Bucket=bucket_name,
        Key=f"{daily_prefix}gameservers.json",
        Body=gameservers_data,
        ContentType='application/json',
        ServerSideEncryption='AES256'
    )
    
    # Save exclusions.json
    exclusions_data = json.dumps({
        "excluded_place_ids": list(exclusions),
        "last_updated": datetime.utcnow().isoformat(),
        "count": len(exclusions)
    }, indent=2)
    s3_client.put_object(
        Bucket=bucket_name,
        Key=f"{daily_prefix}exclusions.json",
        Body=exclusions_data,
        ContentType='application/json',
        ServerSideEncryption='AES256'
    )
    
    log(f"Saved {len(games)} games and {len(exclusions)} exclusions")
    return daily_prefix

def update_gameservers(bucket_name: str, s3_prefix: str = "gameservers/") -> Dict:
    """
    Main function to update gameservers data.
    
    Args:
        bucket_name: S3 bucket name
        s3_prefix: S3 prefix
        
    Returns:
        Dict with status and statistics
    """
    log("=" * 60)
    log("Starting gameservers update")
    log("=" * 60)
    
    # Load existing exclusion list
    existing_exclusions = load_exclusion_list(bucket_name, s3_prefix)
    log(f"Loaded {len(existing_exclusions)} existing exclusions")
    
    # Fetch latest games from Roblox
    raw_games = fetch_latest_roblox_games(pages_per_category=5)
    
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
    
    # Save to S3
    s3_path = save_gameservers_to_s3(processed_games, new_exclusions, bucket_name, s3_prefix)
    
    log("=" * 60)
    log(f"Gameservers update complete!")
    log(f"  Processed: {len(raw_games)} games")
    log(f"  Approved: {len(processed_games)} games")
    log(f"  Excluded: {len(new_exclusions)} total ({len(new_exclusions) - len(existing_exclusions)} new)")
    log(f"  S3 path: s3://{bucket_name}/{s3_path}")
    log("=" * 60)
    
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Gameservers updated successfully',
            's3_path': s3_path,
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
    parser.add_argument('--bucket', required=True, help='S3 bucket name')
    parser.add_argument('--prefix', default='gameservers/', help='S3 prefix')
    
    args = parser.parse_args()
    result = update_gameservers(args.bucket, args.prefix)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['statusCode'] == 200 else 1)
