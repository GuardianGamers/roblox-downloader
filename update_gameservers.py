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
import zipfile
import tempfile
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

def fetch_latest_roblox_games(pages_per_category: int = 5, max_games: int = None, exclude_place_ids: Set[str] = None) -> List[Dict]:
    """
    Fetch latest games from Roblox charts using existing scraper.
    
    Args:
        pages_per_category: Number of pages to fetch per category
        max_games: Maximum number of games to process (for testing)
        exclude_place_ids: Set of place IDs to skip (already excluded games)
        
    Returns:
        List of game data dictionaries
    """
    log("Fetching latest Roblox games from charts...")
    
    if exclude_place_ids is None:
        exclude_place_ids = set()
    
    try:
        # Import the scraper as a module
        sys.path.insert(0, os.path.dirname(ROBLOX_CHARTS_SCRAPER))
        import roblox_charts_scraper
        
        # Create scraper instance
        scraper = roblox_charts_scraper.RobloxChartsScraper()
        
        # Fetch games from all categories
        log(f"Fetching {pages_per_category} pages per category...")
        all_games = scraper.fetch_all_categories(
            max_pages_per_category=pages_per_category
        )
        
        if not all_games:
            log("No games fetched from Roblox charts")
            return []
        
        log(f"Fetched {len(all_games)} raw games from Roblox API")
        
        # Filter out excluded games BEFORE fetching details
        if exclude_place_ids:
            filtered_games = []
            skipped_count = 0
            for game in all_games:
                place_id = str(game.get('rootPlaceId', ''))
                if place_id in exclude_place_ids:
                    skipped_count += 1
                else:
                    filtered_games.append(game)
            
            log(f"Filtered out {skipped_count} excluded games, {len(filtered_games)} remaining")
            all_games = filtered_games
        
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
            modelId='us.anthropic.claude-3-5-sonnet-20241022-v2:0',  # Using inference profile for on-demand access
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

def update_legacy_games(legacy_games: List[Dict]) -> List[Dict]:
    """
    Update legacy games with fresh data from Roblox API.
    
    Args:
        legacy_games: List of games from previous gameservers.json
        
    Returns:
        Updated list of games with fresh data
    """
    if not legacy_games:
        return []
    
    try:
        # Import the scraper to use its API functions
        sys.path.insert(0, os.path.dirname(ROBLOX_CHARTS_SCRAPER))
        import roblox_charts_scraper
        
        updated_games = []
        
        for i, game in enumerate(legacy_games):
            game_name = game.get('name', 'Unknown')
            place_id = game.get('place_id', '')
            universe_id = game.get('universe_id', '')
            
            log(f"  [{i+1}/{len(legacy_games)}] Updating legacy game: {game_name}")
            
            # Ensure access attribute exists (for older gameservers.json files)
            if 'access' not in game:
                game['access'] = 'public'
            
            if not universe_id:
                log(f"    ⚠️  No universe_id, keeping old data")
                updated_games.append(game)
                continue
            
            try:
                # Fetch fresh game details
                game_details = roblox_charts_scraper.fetch_game_details_v2(universe_id)
                
                if game_details:
                    # Update with fresh data while preserving sanitized description
                    game['playerCount'] = game_details.get('playing', game.get('playerCount', 0))
                    game['totalUpVotes'] = game_details.get('favoritedCount', game.get('totalUpVotes', 0))
                    
                    # Only update description if we don't have a sanitized one OR if API description changed
                    api_description = game_details.get('description', '').strip()
                    orig_description = game.get('orig_description', '')
                    
                    if api_description and api_description != orig_description:
                        # Description changed - needs re-sanitization (we'll handle this later)
                        log(f"    ⚠️  Description changed for {game_name}, needs AI re-sanitization")
                        game['orig_description'] = api_description
                        game['description'] = api_description  # Temporarily use raw description
                        game['needs_resanitization'] = True
                    
                    log(f"    ✓ Updated (players: {game['playerCount']}, votes: {game['totalUpVotes']})")
                else:
                    log(f"    ⚠️  Could not fetch details, keeping old data")
                
                updated_games.append(game)
                
                # Rate limiting
                import time
                time.sleep(0.6)  # ~100 requests per minute
                
            except Exception as e:
                log(f"    ❌ Error updating: {e}")
                updated_games.append(game)  # Keep old data on error
        
        return updated_games
        
    except Exception as e:
        log(f"Error updating legacy games: {e}")
        return legacy_games  # Return original on error

def load_exclusion_list(bucket_name: str, s3_prefix: str, local_dir: str = None) -> Dict[str, Dict]:
    """
    Load exclusion list of place IDs from S3 or local directory (most recent version).
    
    Args:
        bucket_name: S3 bucket name
        s3_prefix: S3 prefix for gameservers data
        local_dir: Optional local directory path for testing (overrides S3)
        
    Returns:
        Dict mapping place_id -> {reason, timestamp}
    """
    # Use local directory if specified (for testing)
    if local_dir:
        try:
            gameservers_dir = Path(local_dir)
            if not gameservers_dir.exists():
                log(f"Local directory not found: {local_dir}")
                return {}
            
            # Find most recent date directory
            date_dirs = sorted([d for d in gameservers_dir.iterdir() if d.is_dir()], reverse=True)
            if not date_dirs:
                log("No previous gameservers data found in local directory")
                return {}
            
            latest_dir = date_dirs[0]
            exclusion_file = latest_dir / "exclusions.json"
            
            if not exclusion_file.exists():
                log(f"No exclusions file found in {latest_dir}")
                return {}
            
            log(f"Loading exclusion list from {exclusion_file}")
            with open(exclusion_file, 'r') as f:
                exclusions_data = json.load(f)
            
            # Handle both old format (list) and new format (dict)
            exclusions = exclusions_data.get('exclusions', {})
            if not exclusions:
                # Fallback to old format - convert list to dict
                old_list = exclusions_data.get('excluded_place_ids', [])
                exclusions = {place_id: {'reason': 'unknown', 'timestamp': exclusions_data.get('last_updated')} for place_id in old_list}
            
            return exclusions
            
        except Exception as e:
            log(f"Error loading local exclusion list: {e}")
            return {}
    
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
            return {}
        
        # Get most recent directory
        directories = sorted([p['Prefix'] for p in response['CommonPrefixes']], reverse=True)
        if not directories:
            return {}
        
        latest_dir = directories[0]
        exclusion_file = f"{latest_dir}exclusions.json"
        
        log(f"Loading exclusion list from {exclusion_file}")
        response = s3_client.get_object(Bucket=bucket_name, Key=exclusion_file)
        exclusions_data = json.loads(response['Body'].read())
        
        # Handle both old format (list) and new format (dict)
        exclusions = exclusions_data.get('exclusions', {})
        if not exclusions:
            # Fallback to old format - convert list to dict
            old_list = exclusions_data.get('excluded_place_ids', [])
            exclusions = {place_id: {'reason': 'unknown', 'timestamp': exclusions_data.get('last_updated')} for place_id in old_list}
        
        return exclusions
        
    except s3_client.exceptions.NoSuchKey:
        log("No previous exclusion list found, starting fresh")
        return {}
    except Exception as e:
        log(f"Error loading exclusion list: {e}")
        return {}

def create_gameservers_zip(games: List[Dict], output_path: Path) -> None:
    """
    Create a zip file with gameservers data structured as:
    /gameservers/gameservers.json
    /gameservers/roblox<id>.json (one file per gameserver)
    
    Args:
        games: List of game data
        output_path: Path where the zip file should be created
    """
    log(f"Creating gameservers.zip with {len(games)} individual game files...")
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add the main gameservers.json file
        gameservers_json = json.dumps(games, indent=2)
        zipf.writestr('gameservers/gameservers.json', gameservers_json)
        log(f"  Added gameservers/gameservers.json")
        
        # Add individual files for each gameserver
        for game in games:
            # Use the 'id' field which is in the format "roblox<place_id>"
            game_id = game.get('id', f"roblox{game.get('place_id', 'unknown')}")
            filename = f"gameservers/{game_id}.json"
            game_json = json.dumps(game, indent=2)
            zipf.writestr(filename, game_json)
        
        log(f"  Added {len(games)} individual game files")
    
    log(f"Gameservers.zip created successfully: {output_path}")

def create_metadata_zip(games: List[Dict], output_path: Path, gamecategories_path: str) -> None:
    """
    Create a metadata.zip file for public consumption with:
    - gameservers.json (cleaned up - without internal fields like serverFiles, orig_description, etc.)
    - gamecategories.json
    
    Args:
        games: List of game data
        output_path: Path where the zip file should be created
        gamecategories_path: Path to gamecategories.json file
    """
    log(f"Creating metadata.zip for public distribution...")
    
    # Clean up games data by removing internal fields
    # Important: Ensure 'access' appears early in JSON for client parsing
    excluded_fields = ['orig_description', 'ai_flags', 'ai_reasoning', 'needs_resanitization', 'serverFiles']
    
    cleaned_games = []
    for game in games:
        # Create new dict with 'access' first, then other fields in order
        cleaned_game = {}
        
        # Add 'access' first if it exists
        if 'access' in game:
            cleaned_game['access'] = game['access']
        
        # Add all other fields (except excluded ones)
        for k, v in game.items():
            if k not in excluded_fields and k != 'access':  # Skip 'access' since we already added it
                cleaned_game[k] = v
        
        cleaned_games.append(cleaned_game)
    
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add cleaned gameservers.json
        gameservers_json = json.dumps(cleaned_games, indent=2)
        zipf.writestr('gameservers.json', gameservers_json)
        log(f"  Added gameservers.json ({len(cleaned_games)} games)")
        
        # Add gamecategories.json if it exists
        gamecategories_file = Path(gamecategories_path)
        if gamecategories_file.exists():
            with open(gamecategories_file, 'r') as f:
                gamecategories_data = f.read()
            zipf.writestr('gamecategories.json', gamecategories_data)
            log(f"  Added gamecategories.json")
        else:
            log(f"  Warning: gamecategories.json not found at {gamecategories_path}")
    
    log(f"Metadata.zip created successfully: {output_path}")

def save_gameservers_to_s3(
    games: List[Dict],
    exclusions: Dict[str, Dict],
    bucket_name: str,
    s3_prefix: str,
    local_dir: str = None,
    gamecategories_path: str = None
) -> str:
    """
    Save updated gameservers.json and exclusions to S3 or local directory with today's date.
    Also creates gameservers.zip and metadata.zip files.
    
    Args:
        games: List of game data
        exclusions: Dict mapping place_id -> {reason, timestamp}
        bucket_name: S3 bucket name
        s3_prefix: S3 prefix for gameservers data
        local_dir: Optional local directory path for testing (overrides S3)
        gamecategories_path: Path to gamecategories.json file (defaults to ./gamecategories.json)
        
    Returns:
        Path where data was saved
    """
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    # Default gamecategories path if not specified
    if gamecategories_path is None:
        gamecategories_path = os.path.join(os.path.dirname(__file__), 'gamecategories.json')
    
    gameservers_data = json.dumps(games, indent=2)
    exclusions_data = json.dumps({
        "exclusions": exclusions,
        "excluded_place_ids": list(exclusions.keys()),  # Keep for backward compatibility
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
        
        # Create gameservers.zip
        zip_path = daily_dir / "gameservers.zip"
        create_gameservers_zip(games, zip_path)
        
        # Create metadata.zip
        metadata_zip_path = daily_dir / "metadata.zip"
        create_metadata_zip(games, metadata_zip_path, gamecategories_path)
        
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
    
    # Create and save gameservers.zip
    with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.zip') as tmp_zip:
        tmp_zip_path = Path(tmp_zip.name)
    
    try:
        create_gameservers_zip(games, tmp_zip_path)
        
        # Upload to S3
        with open(tmp_zip_path, 'rb') as f:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=f"{daily_prefix}gameservers.zip",
                Body=f.read(),
                ContentType='application/zip',
                ServerSideEncryption='AES256'
            )
        log(f"Uploaded gameservers.zip to S3")
    finally:
        # Clean up temp file
        if tmp_zip_path.exists():
            tmp_zip_path.unlink()
    
    # Create and save metadata.zip
    with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.zip') as tmp_metadata:
        tmp_metadata_path = Path(tmp_metadata.name)
    
    try:
        create_metadata_zip(games, tmp_metadata_path, gamecategories_path)
        
        # Upload to S3
        with open(tmp_metadata_path, 'rb') as f:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=f"{daily_prefix}metadata.zip",
                Body=f.read(),
                ContentType='application/zip',
                ServerSideEncryption='AES256'
            )
        log(f"Uploaded metadata.zip to S3")
    finally:
        # Clean up temp file
        if tmp_metadata_path.exists():
            tmp_metadata_path.unlink()
    
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
    
    # Load existing gameservers to preserve legacy games
    existing_games = {}
    try:
        if local_dir:
            # Load from local directory
            gameservers_dir = Path(local_dir)
            date_dirs = sorted([d for d in gameservers_dir.iterdir() if d.is_dir()], reverse=True)
            if date_dirs:
                latest_dir = date_dirs[0]
                gameservers_file = latest_dir / "gameservers.json"
                if gameservers_file.exists():
                    log(f"Loading existing gameservers from {gameservers_file}")
                    with open(gameservers_file, 'r') as f:
                        old_games = json.load(f)
                        for game in old_games:
                            place_id = str(game.get('place_id', ''))
                            if place_id:
                                # Ensure access attribute exists (for older gameservers.json files)
                                if 'access' not in game:
                                    game['access'] = 'public'
                                existing_games[place_id] = game
                    log(f"Loaded {len(existing_games)} existing games")
        else:
            # Load from S3
            response = s3_client.list_objects_v2(
                Bucket=bucket_name,
                Prefix=f"{s3_prefix}gameservers/",
                Delimiter='/'
            )
            
            if 'CommonPrefixes' in response:
                directories = sorted([p['Prefix'] for p in response['CommonPrefixes']], reverse=True)
                if directories:
                    latest_dir = directories[0]
                    gameservers_file = f"{latest_dir}gameservers.json"
                    log(f"Loading existing gameservers from S3: {gameservers_file}")
                    response = s3_client.get_object(Bucket=bucket_name, Key=gameservers_file)
                    old_games = json.loads(response['Body'].read())
                    for game in old_games:
                        place_id = str(game.get('place_id', ''))
                        if place_id:
                            # Ensure access attribute exists (for older gameservers.json files)
                            if 'access' not in game:
                                game['access'] = 'public'
                            existing_games[place_id] = game
                    log(f"Loaded {len(existing_games)} existing games from S3")
    except Exception as e:
        log(f"Could not load existing gameservers: {e}")
    
    # Fetch latest games from Roblox (exclude already-excluded games to save API calls)
    raw_games = fetch_latest_roblox_games(
        pages_per_category=5,
        max_games=None,
        exclude_place_ids=set(existing_exclusions.keys())
    )
    
    if not raw_games:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Failed to fetch games from Roblox'})
        }
    
    # Process each game with AI
    processed_games = []
    new_exclusions = dict(existing_exclusions)  # Copy existing exclusions
    processed_place_ids = set()  # Track which games we've processed from API
    ai_calls_made = 0  # Track how many AI calls we made
    ai_calls_saved = 0  # Track how many we skipped by reusing
    
    for i, game in enumerate(raw_games):
        log(f"Processing game {i+1}/{len(raw_games)}: {game.get('name', 'Unknown')}")
        
        place_id = str(game.get('place_id', ''))
        processed_place_ids.add(place_id)  # Track that we've seen this game
        
        # Note: Already-excluded games were filtered out during fetch, so we don't need to check again
        
        # Get current description from API
        current_description = game.get('description', '')
        
        # Check if we can reuse existing sanitized description
        existing_game = existing_games.get(place_id)
        if existing_game and existing_game.get('orig_description') == current_description:
            # Description unchanged - reuse existing sanitized version
            log(f"  Description unchanged, reusing sanitized version (skipping AI)")
            game['description'] = existing_game.get('description', current_description)
            game['orig_description'] = current_description
            game['ai_flags'] = existing_game.get('ai_flags', [])
            game['ai_reasoning'] = existing_game.get('ai_reasoning', '')
            processed_games.append(game)
            ai_calls_saved += 1
            continue
        
        # Description is new or changed - run AI sanitization
        log(f"  New/changed description, running AI sanitization...")
        ai_result = sanitize_description_with_ai(
            current_description,
            game.get('name', 'Unknown')
        )
        ai_calls_made += 1
        
        # Update game with sanitized description and save original
        game['description'] = ai_result['sanitized_description']
        game['orig_description'] = current_description  # Save original for future comparison
        game['ai_flags'] = ai_result.get('flags', [])
        game['ai_reasoning'] = ai_result.get('reasoning', '')
        
        # Add to exclusions if not appropriate
        if not ai_result['is_appropriate_for_under13']:
            flags = ai_result.get('flags', [])
            # Determine primary reason from first flag
            reason = flags[0].lower().replace(' ', '-').replace('_', '-') if flags else 'inappropriate'
            
            log(f"  Excluding {place_id} (reason: {reason}): {ai_result['reasoning']}")
            new_exclusions[place_id] = {
                'reason': reason,
                'timestamp': datetime.utcnow().isoformat(),
                'flags': flags,
                'reasoning': ai_result.get('reasoning', '')
            }
        else:
            processed_games.append(game)
    
    # Update legacy games (games that exist in old gameservers but not in new API results)
    legacy_games = []
    legacy_place_ids = []
    for place_id, game in existing_games.items():
        if place_id not in processed_place_ids and place_id not in new_exclusions:
            legacy_place_ids.append(place_id)
            legacy_games.append(game)
    
    if legacy_games:
        log(f"\n{'='*60}")
        log(f"Updating {len(legacy_games)} legacy games (no longer in charts but still active)")
        log(f"{'='*60}")
        updated_legacy_games = update_legacy_games(legacy_games)
        
        # Check for games that need re-sanitization
        needs_resanitization = [g for g in updated_legacy_games if g.get('needs_resanitization')]
        if needs_resanitization:
            log(f"\n⚠️  {len(needs_resanitization)} legacy games have changed descriptions and need AI re-sanitization")
            log(f"Re-sanitizing descriptions...")
            
            for game in needs_resanitization:
                ai_result = sanitize_description_with_ai(
                    game['description'],
                    game.get('name', 'Unknown')
                )
                ai_calls_made += 1
                
                game['description'] = ai_result['sanitized_description']
                game['ai_flags'] = ai_result.get('flags', [])
                game['ai_reasoning'] = ai_result.get('reasoning', '')
                game.pop('needs_resanitization', None)  # Remove flag
                
                # Check if now inappropriate
                if not ai_result['is_appropriate_for_under13']:
                    place_id = str(game.get('place_id', ''))
                    flags = ai_result.get('flags', [])
                    reason = flags[0].lower().replace(' ', '-').replace('_', '-') if flags else 'inappropriate'
                    
                    log(f"  ⚠️  Legacy game {game['name']} now inappropriate, moving to exclusions")
                    new_exclusions[place_id] = {
                        'reason': reason,
                        'timestamp': datetime.utcnow().isoformat(),
                        'flags': flags,
                        'reasoning': ai_result.get('reasoning', '')
                    }
                    # Don't add to processed_games
                    updated_legacy_games.remove(game)
        
        processed_games.extend(updated_legacy_games)
    
    # Save to S3 or local directory
    # Default gamecategories path (in Docker it's /app/, locally it's in project root)
    default_gamecategories_path = '/app/gamecategories.json' if os.path.exists('/app/gamecategories.json') else './gamecategories.json'
    save_path = save_gameservers_to_s3(
        processed_games, 
        new_exclusions, 
        bucket_name, 
        s3_prefix, 
        local_dir=local_dir,
        gamecategories_path=default_gamecategories_path
    )
    
    log("=" * 60)
    log(f"Gameservers update complete!")
    log(f"  API Games Processed: {len(raw_games)} (excluded games filtered out)")
    log(f"  Legacy Games Updated: {len(legacy_games)} (no longer in charts)")
    log(f"  Total Games: {len(processed_games)}")
    log(f"  Total Exclusions: {len(new_exclusions)} ({len(new_exclusions) - len(existing_exclusions)} new)")
    log(f"  AI Calls Made: {ai_calls_made}")
    log(f"  AI Calls Saved: {ai_calls_saved} (reused existing sanitization)")
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
                'api_games_processed': len(raw_games),
                'legacy_games_updated': len(legacy_games),
                'total_games': len(processed_games),
                'total_exclusions': len(new_exclusions),
                'new_exclusions': len(new_exclusions) - len(existing_exclusions),
                'ai_calls_made': ai_calls_made,
                'ai_calls_saved': ai_calls_saved
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
