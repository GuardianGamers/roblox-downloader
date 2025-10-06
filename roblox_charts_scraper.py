#!/usr/bin/env python3

"""
Roblox Charts API Scraper
========================

Official Roblox Charts API scraper that fetches games from Roblox's explore API.
This provides access to Roblox's official game rankings and discovery data.

API Endpoint: https://apis.roblox.com/explore-api/v1/get-sorts

Features:
- Fetches games from official Roblox charts/sorts
- Drills down into individual categories using sortId
- Handles pagination with nextSortsPageToken
- Rich game data (player counts, votes, age ratings)
- Converts to gameserver-details.json format
- Rate limiting and error handling
- Deduplication by universe ID
- Fetches real game descriptions using Roblox API

Usage:
    scraper = RobloxChartsScraper()
    games = scraper.fetch_all_categories(pages_per_category=5)
    scraper.export_to_gameserver_format(games, "roblox_charts_games.json")
"""

import requests
import json
import time
import os
from datetime import datetime
from typing import Dict, List, Optional, Set
import sys
import uuid
import argparse
import urllib.parse
import re

# Import Roblox API functions for fetching game details
# Implemented directly to avoid selenium dependency
def load_blacklist_from_file(filename: str) -> List[str]:
    """
    Load blacklisted categories from a JSON file.
    
    Args:
        filename: Path to the JSON file containing blacklisted categories
        
    Returns:
        List of blacklisted category names, or empty list if file doesn't exist or is invalid
    """
    if not os.path.exists(filename):
        print(f"📄 No blacklist file found at {filename}")
        return []
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Handle different JSON formats
        if isinstance(data, list):
            # Simple list format: ["category1", "category2"]
            blacklist = data
        elif isinstance(data, dict):
            # Object format with blacklist key: {"blacklist": ["category1", "category2"]}
            blacklist = data.get('blacklist', data.get('categories', []))
        else:
            print(f"⚠️  Invalid format in {filename}, expected list or object")
            return []
        
        if blacklist:
            print(f"🚫 Loaded {len(blacklist)} blacklisted categories from {filename}")
            print(f"🚫 Blacklisted: {', '.join(blacklist)}")
        else:
            print(f"📄 No blacklisted categories found in {filename}")
        
        return blacklist
        
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️  Error reading blacklist file {filename}: {e}")
        return []

def fetch_game_details_v2(universe_id):
    """Fetch details for a specific game by universe ID using the Roblox API"""
    url = f"https://games.roblox.com/v1/games?universeIds={universe_id}"
    
    max_retries = 3
    base_delay = .2  # Base delay for rate limiting
    
    for attempt in range(max_retries):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                data = response.json().get("data", [])
                if data:
                    game_info = data[0]
                    return game_info
                else:
                    return None
                    
            elif response.status_code == 429:
                # Rate limited - retry with exponential backoff
                retry_delay = base_delay * (2 ** attempt)
                print(f"        ⏳ Rate limited! Waiting {retry_delay:.1f}s before retry {attempt + 1}/{max_retries}")
                time.sleep(retry_delay)
                continue
                
            else:
                print(f"        ❌ HTTP Error {response.status_code} for universe_id {universe_id}")
                return None
                
        except Exception as e:
            print(f"        💥 Exception for universe_id {universe_id}: {e}")
            if attempt < max_retries - 1:
                time.sleep(base_delay)
                continue
            return None
    
    print(f"        ❌ Failed after {max_retries} attempts for universe_id {universe_id}")
    return None

def fetch_game_thumbnail(universe_id, place_id):
    """Fetch game thumbnail using the Roblox API endpoints"""
    try:
        # Method 1: Try to get image IDs from the games media API and use batch API for thumbnails
        media_url = f"https://games.roblox.com/v2/games/{universe_id}/media"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(media_url, headers=headers)
        
        if response.status_code == 200:
            media_data = response.json()
            if 'data' in media_data and media_data['data']:
                # Look for approved images
                approved_images = [item for item in media_data['data'] 
                                 if item.get('assetType') == 'Image' and item.get('approved')]
                
                if approved_images:
                    # Use the first approved image ID for thumbnail
                    image_id = approved_images[0]['imageId']
                    
                    # Use the batch thumbnail API with Asset type and the actual image ID
                    batch_url = "https://thumbnails.roblox.com/v1/batch"
                    batch_data = [{
                        "requestId": f"{image_id}::Asset:768x432:webp:regular:",
                        "type": "Asset",
                        "targetId": image_id,
                        "format": "webp",
                        "size": "768x432"
                    }]
                    
                    response = requests.post(batch_url, json=batch_data)
                    if response.status_code == 200:
                        thumbnail_data = response.json()
                        if 'data' in thumbnail_data and thumbnail_data['data']:
                            # Check if we got a valid thumbnail
                            for item in thumbnail_data['data']:
                                if item.get('state') == 'Completed' and item.get('imageUrl'):
                                    return thumbnail_data
                            # If we get here, no completed thumbnails - show debug
                            print(f"    ❌ Batch API returned no completed thumbnails for image {image_id}")
                            print(f"    🔍 Batch API response: {thumbnail_data}")
                        else:
                            print(f"    ❌ Batch API returned no data for image {image_id}")
                    else:
                        print(f"    ❌ Batch API request failed with status {response.status_code} for image {image_id}")
                else:
                    print(f"    ❌ No approved images found in media API for universe {universe_id}")
                    print(f"    🔍 Media API response: {media_data}")
            else:
                print(f"    ❌ No data in games media API for universe {universe_id}")
        else:
            print(f"    ❌ Games media API failed with status {response.status_code} for universe {universe_id}")
        
        # Method 2: Try the batch thumbnail API with universe ID as fallback
        batch_url = "https://thumbnails.roblox.com/v1/batch"
        batch_data = [{
            "requestId": f"{universe_id}::GameIcon:768x432:webp:regular:",
            "type": "GameIcon",
            "targetId": universe_id,
            "format": "webp",
            "size": "768x432"
        }]
        
        response = requests.post(batch_url, json=batch_data)
        if response.status_code == 200:
            thumbnail_data = response.json()
            if 'data' in thumbnail_data and thumbnail_data['data']:
                # Check if we got a valid thumbnail
                for item in thumbnail_data['data']:
                    if item.get('state') == 'Completed' and item.get('imageUrl'):
                        return thumbnail_data
                # If we get here, no completed thumbnails - show debug
                print(f"    ❌ Batch API fallback returned no completed thumbnails for universe {universe_id}")
                print(f"    🔍 Batch API fallback response: {thumbnail_data}")
            else:
                print(f"    ❌ Batch API fallback returned no data for universe {universe_id}")
        else:
            print(f"    ❌ Batch API fallback failed with status {response.status_code} for universe {universe_id}")
        
        return None
    except Exception as e:
        print(f"    ❌ Error fetching thumbnail for universe {universe_id}: {e}")
        return None



ROBLOX_API_AVAILABLE = True
print("✅ Roblox API functions implemented directly")


def format_description_to_markdown(raw_text: str) -> str:
    """Convert a plain text description into lightweight Markdown.

    Rules applied:
    - Normalize newlines to \n
    - Convert runs of 2+ spaces used as separators into double newlines
    - Convert common inline list separators " - " and bullets "•" into Markdown list items
    - Collapse any 3+ newlines into exactly two
    - Trim leading and trailing whitespace
    """
    if not raw_text:
        return raw_text

    text = raw_text.replace("\r\n", "\n").replace("\r", "\n")

    # Replace sequences of 2+ spaces (often used as separators in scraped text) with paragraph breaks
    text = re.sub(r" {2,}", "\n\n", text)

    # Normalize bullet-like patterns to Markdown list items
    # Convert middle-of-line separators like " - " into list items
    text = re.sub(r"\s-\s", "\n- ", text)
    # Convert Unicode bullets to Markdown dashes
    text = re.sub(r" *• *", "\n- ", text)

    # Collapse excessive blank lines to exactly two
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


class RobloxChartsScraper:
    """Scraper for Roblox's official charts/explore API"""
    
    def __init__(self, rate_limit_delay: float = 1.0):
        """
        Initialize the Roblox Charts scraper.
        
        Args:
            rate_limit_delay: Delay between requests in seconds to avoid rate limiting
        """
        self.session_id = "57ac3f13-670d-4dbc-bb97-8df080f955fc"
        self.base_url = "https://apis.roblox.com/explore-api/v1"

        self.rate_limit_delay = rate_limit_delay
        
        # Browser-like headers to avoid bot detection
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Origin': 'https://www.roblox.com',
            'Referer': 'https://www.roblox.com/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-site'
        }
        
        # Default parameters for tablet resolution (matching working API calls)
        self.default_params = {
            'cpuCores': '4',
            'maxResolution': '1280x800',  # Tablet resolution
            'maxMemory': '8192',
            'networkType': '4g',
            'sessionId': self.session_id
        }
        
        print(f"🎮 Roblox Charts API Scraper initialized")
        print(f"📊 Base URL: {self.base_url}/get-sorts")

        print(f"⏱️  Rate limit: {rate_limit_delay}s between requests")

    def _make_request_with_retry(self, url: str, params: Dict) -> Optional[Dict]:
        """Make API request with retry logic."""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                print(f"  Making API request (attempt {attempt + 1}/{max_retries})...")
                
                # Build full URL for debugging
                query_string = urllib.parse.urlencode(params)
                full_url = f"{url}?{query_string}"
                print(f"  🔗 DEBUG URL: {full_url[:100]}...")
                
                response = requests.get(url, params=params, headers=self.headers)
                
                if response.status_code == 200:
                    print(f"  ✅ API request successful")
                    return response.json()
                    
                elif response.status_code == 429:
                    retry_delay = 2 ** attempt
                    print(f"  ⏳ Rate limited! Waiting {retry_delay}s before retry...")
                    time.sleep(retry_delay)
                    continue
                    
                else:
                    print(f"  ❌ API request failed with status {response.status_code}")
                    return None
                    
            except Exception as e:
                print(f"  💥 Request exception: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None
        
        print(f"  ❌ Failed after {max_retries} attempts")
        return None

    def discover_sort_ids(self) -> List[Dict[str, str]]:
        """
        Discover available sort IDs from the main API.
        
        Returns:
            List of dictionaries with sortId and sortDisplayName
        """
        print("🔍 Discovering available sort categories...")
        
        data = self._make_request_with_retry(f"{self.base_url}/get-sorts", self.default_params)
        if not data:
            print("❌ Failed to fetch sort categories")
            return []
        
        sort_ids = []
        sorts_data = data.get('sorts', [])
        
        for sort_info in sorts_data:
            sort_id = sort_info.get('sortId')
            sort_display_name = sort_info.get('sortDisplayName', 'Unknown Sort')
            games = sort_info.get('games', [])
            
            # Only include sorts that have games (skip filters)
            if sort_id and games:
                sort_ids.append({
                    'sortId': sort_id,
                    'sortDisplayName': sort_display_name,
                    'gameCount': len(games)
                })
                print(f"  ✅ Found sort: '{sort_display_name}' ({sort_id}) - {len(games)} games")
        
        print(f"🎯 Discovered {len(sort_ids)} game categories")
        return sort_ids
    
    def fetch_category_games(self, sort_id: str, sort_name: str, max_pages: int = 5) -> List[Dict]:
        """
        Fetch games from a specific category using sortId.
        
        Args:
            sort_id: The sortId to fetch (e.g., 'top-trending')
            sort_name: Display name for the sort
            max_pages: Maximum number of pages to fetch for this category
            
        Returns:
            List of games from this category
        """
        print(f"\n📂 Fetching category: '{sort_name}' ({sort_id})")
        
        category_games = []
        page_token = None
        page_count = 0
        
        while page_count < max_pages:
            page_count += 1
            print(f"  📄 Page {page_count}/{max_pages}...")
            
            # Build parameters for this specific category
            params = {
                'sortId': sort_id,
                'age': 'all'
            }
            if page_token:
                params['sortsPageToken'] = page_token  # Fixed: was 'pageToken'
            
            # Fetch page data
            page_data = self._make_request_with_retry(f"{self.base_url}/get-sorts", params)
            if not page_data:
                print(f"    ❌ Failed to fetch page {page_count}")
                break
            
            # Extract games from this category page
            page_games = 0
            new_games = 0
            
            sorts_data = page_data.get('sorts', [])
            if not sorts_data:
                print(f"    ℹ️  No sorts data on page {page_count}")
                break
            
            # Process games from all sorts (should mainly be the requested sort)
            for sort_info in sorts_data:
                sort_games = sort_info.get('games', [])
                
                for game in sort_games:
                    page_games += 1
                    universe_id = game.get('universeId')
                    
                    if universe_id:
                        # Add sort information to game data
                        game['roblox_sort_id'] = sort_id
                        game['roblox_sort_name'] = sort_name
                        
                        # Check if this game already exists in this category
                        existing_game = next((g for g in category_games if g.get('universeId') == universe_id), None)
                        if existing_game:
                            # Game already exists in this category - merge chart info
                            existing_categories = existing_game.get('categories', [])
                            if sort_id not in existing_categories:
                                existing_categories.append(sort_id)
                                existing_game['categories'] = existing_categories
                                print(f"      🔄 Merged chart '{sort_id}' for existing game '{game.get('name', 'Unknown')}'")
                        else:
                            # New game for this category
                            category_games.append(game)
                            new_games += 1
            
            print(f"    📊 {page_games} total games, {new_games} new unique games")
            
            # Check for next page token
            page_token = page_data.get('nextSortsPageToken')
            if not page_token:
                print(f"    ℹ️  No more pages available")
                break
        
        print(f"  ✅ Category complete: {len(category_games)} unique games from {page_count} pages")
        return category_games
    
    def fetch_all_categories(self, max_pages_per_category: int = 5) -> List[Dict]:
        """
        Fetch games from all available categories.
        
        The 2024 API returns ALL categories in a SINGLE response, with pagination support!
        
        Args:
            max_pages_per_category: Maximum number of pages to fetch
            
        Returns:
            List of all unique games across categories
        """
        print(f"🚀 COMPREHENSIVE CATEGORY SCRAPING (2024 API Format)")
        print(f"📊 Fetching up to {max_pages_per_category} pages")
        print("=" * 60)
        
        all_games = []
        games_by_universe_id = {}  # Track games by universe_id for deduplication
        page_count = 0
        page_token = None
        
        # Fetch pages until we hit the limit or run out of data
        while page_count < max_pages_per_category:
            page_count += 1
            print(f"\n📄 Fetching page {page_count}/{max_pages_per_category}...")
            
            # Build parameters
            params = self.default_params.copy()
            if page_token:
                params['sortsPageToken'] = page_token
            
            # Make the API request
            data = self._make_request_with_retry(f"{self.base_url}/get-sorts", params)
            if not data:
                print(f"❌ Failed to fetch page {page_count}")
                break
            
            # Extract all sorts from this page
            sorts_data = data.get('sorts', [])
            if not sorts_data:
                print(f"ℹ️  No sorts data on page {page_count}")
                break
            
            print(f"  📊 Found {len(sorts_data)} sorts/categories on this page")
            
            # Process each sort (category)
            for sort_info in sorts_data:
                sort_id = sort_info.get('sortId')
                sort_name = sort_info.get('sortDisplayName', 'Unknown')
                content_type = sort_info.get('contentType')
                
                # Skip non-game sorts (like "Filters")
                if content_type != 'Games':
                    continue
                
                games = sort_info.get('games', [])
                if not games:
                    continue
                
                print(f"    • {sort_name} ({sort_id}): {len(games)} games")
                
                # Add games to our collection (with deduplication and category tracking)
                new_games = 0
                updated_games = 0
                for game in games:
                    universe_id = game.get('universeId')
                    if not universe_id:
                        continue
                    
                    if universe_id in games_by_universe_id:
                        # Game already exists - add this category to its list
                        existing_game = games_by_universe_id[universe_id]
                        existing_categories = existing_game.get('categories', [])
                        
                        if sort_id not in existing_categories:
                            existing_categories.append(sort_id)
                            existing_game['categories'] = existing_categories
                            updated_games += 1
                    else:
                        # New game - add to collection with initial category
                        game['categories'] = [sort_id]
                        game['roblox_sort_id'] = sort_id  # Primary category
                        game['roblox_sort_name'] = sort_name
                        all_games.append(game)
                        games_by_universe_id[universe_id] = game
                        new_games += 1
                
                if new_games > 0 or updated_games > 0:
                    print(f"      + {new_games} new | {updated_games} updated")
            
            print(f"  ✅ Total unique games so far: {len(all_games)}")
            
            # Check for next page token
            page_token = data.get('nextSortsPageToken')
            if not page_token:
                print(f"  ℹ️  No more pages available")
                break
            
            # Rate limiting between pages
            if page_count < max_pages_per_category:
                time.sleep(self.rate_limit_delay)
        
        print(f"\n🎉 CATEGORY SCRAPING COMPLETE!")
        print(f"  📄 Pages fetched: {page_count}")
        print(f"  🎮 Total unique games collected: {len(all_games)}")
        print("=" * 60)
        
        # Now enrich games with additional details (descriptions, thumbnails)
        if all_games:
            print(f"\n🔍 PHASE 2: Fetching additional details for {len(all_games)} games...")
            print("=" * 60)
            self._enrich_games_with_details(all_games)
        
        return all_games
    
    def _enrich_games_with_details(self, games: List[Dict]) -> None:
        """
        Enrich games with additional details (descriptions, thumbnails) from Roblox API.
        Modifies the games list in-place.
        
        Args:
            games: List of games to enrich
        """
        if not ROBLOX_API_AVAILABLE:
            print("  ℹ️  Roblox API not available, skipping detail fetching")
            return
        
        total = len(games)
        for i, game in enumerate(games, 1):
            universe_id = game.get('universeId')
            place_id = game.get('rootPlaceId')
            game_name = game.get('name', 'Unknown')
            
            if not universe_id:
                print(f"  [{i}/{total}] ⚠️  {game_name}: No universe_id, skipping")
                continue
            
            try:
                print(f"  [{i}/{total}] 📝 Fetching details: {game_name}")
                
                # Fetch detailed game info
                game_details = fetch_game_details_v2(universe_id)
                if game_details:
                    description = game_details.get('description', '').replace('\r\n', '\n').replace('\r', '\n').strip()
                    if description:
                        game['_enriched_description'] = description
                
                # Fetch thumbnail
                thumbnail_data = fetch_game_thumbnail(universe_id, place_id)
                if thumbnail_data and 'data' in thumbnail_data and thumbnail_data['data']:
                    for item in thumbnail_data['data']:
                        if item.get('state') == 'Completed' and item.get('imageUrl'):
                            game['_enriched_thumbnail'] = item['imageUrl']
                            break
                
                # Progress updates every 10 games
                if i % 10 == 0:
                    print(f"    Progress: {i}/{total} games enriched ({(i/total)*100:.1f}%)")
                
                # Rate limiting (reduced to be faster while still respectful)
                time.sleep(0.5)
                
            except Exception as e:
                print(f"  [{i}/{total}] ❌ {game_name}: {e}")
        
        print(f"\n  ✅ Detail fetching complete!")
        print("=" * 60)
    
    def fetch_games_page(self, page_token: str = None) -> Optional[Dict]:
        """Fetch a single page of games from the charts API."""
        params = self.default_params.copy()
        
        if page_token:
            params['sortsPageToken'] = page_token
        
        return self._make_request_with_retry(f"{self.base_url}/get-sorts", params)
    
    def fetch_all_games(self, max_pages: int = 10, blacklist: List[str] = None) -> List[Dict]:
        """
        Fetch games from multiple pages of the charts API (basic method).
        
        Args:
            max_pages: Maximum number of pages to fetch
            
        Returns:
            List of all unique games found
        """
        if blacklist is None:
            blacklist = []
        
        print(f"🔍 Fetching games from Roblox Charts API (up to {max_pages} pages)")
        print("ℹ️  Note: Use fetch_all_categories() for comprehensive data collection")
        
        if blacklist:
            print(f"🚫 Blacklisted categories: {', '.join(blacklist)}")
        
        all_games = []
        page_token = None
        page_count = 0
        
        while page_count < max_pages:
            page_count += 1
            print(f"\n📄 Fetching page {page_count}/{max_pages}...")
            
            # Fetch page data
            page_data = self.fetch_games_page(page_token)
            if not page_data:
                print(f"❌ Failed to fetch page {page_count}")
                break
            
            # Extract games from all sorts in this page
            page_games = 0
            new_games = 0
            
            sorts_data = page_data.get('sorts', [])
            print(f"  Found {len(sorts_data)} sorts on this page")
            
            for sort_info in sorts_data:
                sort_id = sort_info.get('sortId')
                sort_display_name = sort_info.get('sortDisplayName', 'Unknown Sort')
                sort_games = sort_info.get('games', [])  # Changed from 'data' to 'games'
                
                # Skip blacklisted categories
                if sort_id in blacklist:
                    print(f"    🚫 Skipped '{sort_display_name}' ({sort_id}): {len(sort_games)} games (blacklisted)")
                    continue
                
                print(f"    Sort '{sort_display_name}' ({sort_id}): {len(sort_games)} games")
                
                for game in sort_games:
                    page_games += 1
                    universe_id = game.get('universeId')
                    
                    if universe_id:
                        # Add sort information to game data
                        game['roblox_sort_id'] = sort_id
                        game['roblox_sort_name'] = sort_display_name
                        
                        # Check if this game already exists
                        existing_game = next((g for g in all_games if g.get('universeId') == universe_id), None)
                        if existing_game:
                            # Game already exists - merge chart info
                            existing_categories = existing_game.get('categories', [])
                            if sort_id not in existing_categories:
                                existing_categories.append(sort_id)
                                existing_game['categories'] = existing_categories
                                print(f"      🔄 Merged chart '{sort_id}' for existing game '{game.get('name', 'Unknown')}'")
                        else:
                            # New game
                            all_games.append(game)
                            new_games += 1
            
            print(f"  📊 Page {page_count}: {page_games} total games, {new_games} new unique games")
            print(f"  📈 Total unique games so far: {len(all_games)}")
            
            # Check for next page token
            page_token = page_data.get('nextSortsPageToken')
            if not page_token:
                print(f"  ℹ️  No more pages available (no nextSortsPageToken)")
                break
        
        print(f"\n✅ Fetching complete! Found {len(all_games)} unique games across {page_count} pages")
        return all_games
    
    def convert_to_gameserver_format(self, game: Dict) -> Dict:
        """
        Convert a Roblox Charts API game to gameserver-details.json format.
        
        Args:
            game: Game data from Roblox Charts API
            
        Returns:
            Game in gameserver-details.json format
        """
        game_data = game.copy() # Work on a copy to avoid modifying the original game object
        
        # Extract universe_id and place_id
        universe_id = game_data.get('universeId')
        place_id = game_data.get('rootPlaceId')
        game_name = game_data.get('name', 'Unknown Game')
        
        # Extract basic game stats
        playing_count = game_data.get('playerCount', 0)
        like_ratio = round(game_data.get('likeRatio', 0) * 100, 1) if game_data.get('likeRatio') else 0
        total_up_votes = game_data.get('totalUpVotes', 0)
        total_down_votes = game_data.get('totalDownVotes', 0)
        
        # Use enriched data if available (from _enrich_games_with_details)
        real_description = game_data.get('_enriched_description')
        thumbnail_url = game_data.get('_enriched_thumbnail')
        
        # Use real description if available, otherwise fall back to generic
        if real_description:
            description = real_description
        else:
            # Fallback to generic description
            description = f"A popular Roblox game with {playing_count:,} players. Rating: {like_ratio}% ({total_up_votes:,} 👍 / {total_down_votes:,} 👎)"
        
        # Format description to lightweight Markdown with double newlines
        description = format_description_to_markdown(description)
        
        # Use real thumbnail if available
        img_url = thumbnail_url if thumbnail_url else None
        
        # Determine categories based on sort and player count
        categories = []
        
        sort_name = game_data.get('roblox_sort_name', '')
        sort_id = game_data.get('roblox_sort_id', '')
        
        # Check if game already has categories from previous chart appearances
        existing_categories = game_data.get('categories', [])
        if existing_categories:
            categories = existing_categories.copy()
        
        # Add the current Roblox chart ID as a category (for UI filtering)
        if sort_id and sort_id not in categories:
            categories.append(sort_id)
        
        # Create game entry
        game_entry = {
            "id": f"roblox{place_id}",
            "name": game_name,
            "description": description,
            "url": f"{place_id}",
            "categories": categories,
            "serverFiles": [],
            "game": "roblox",
            "version": "latest",
            "stages": ["dev", "test", "prod"],  # Include all stages
            "universe_id": universe_id,
            "place_id": place_id,
            "player_count": playing_count,
            "rating_percentage": like_ratio,
            "total_votes": total_up_votes + total_down_votes,
            "minimum_age": game_data.get('minimumAge', 0),
            "age_display": game_data.get('ageRecommendationDisplayName', 'Unknown'),
            "is_sponsored": game_data.get('isSponsored', False),
            "roblox_sort": sort_name,  # Primary chart name
            "roblox_sort_id": sort_id,  # Primary chart ID
        }
        
        # Only add img field if we have a valid thumbnail URL
        if img_url:
            game_entry["img"] = img_url
        
        return game_entry

    def convert_to_gameserver_format_simple(self, game: Dict) -> Optional[Dict]:
        """
        Convert a single game to gameserver-details.json format WITHOUT fetching detailed descriptions.
        Used for performance when processing many games.
        
        Args:
            game: Game data from Roblox Charts API
            
        Returns:
            Game in gameserver-details.json format with generic description
        """
        game_data = game.copy()
        
        # Extract universe_id and place_id
        universe_id = game_data.get('universeId')
        place_id = game_data.get('rootPlaceId')
        game_name = game_data.get('name', 'Unknown Game')
        
        # Extract basic game stats
        playing_count = game_data.get('playerCount', 0)
        like_ratio = round(game_data.get('likeRatio', 0) * 100, 1) if game_data.get('likeRatio') else 0
        total_up_votes = game_data.get('totalUpVotes', 0)
        total_down_votes = game_data.get('totalDownVotes', 0)
        
        # Create generic description without API call
        description = f"A popular Roblox game with {playing_count:,} players. Rating: {like_ratio}% ({total_up_votes:,} 👍 / {total_down_votes:,} 👎)"
        
        # No thumbnail available in simple mode
        img_url = None
        
        # Determine categories based on sort and player count
        categories = []
        
        sort_name = game_data.get('roblox_sort_name', '')
        sort_id = game_data.get('roblox_sort_id', '')
        
        # Check if game already has categories from previous chart appearances
        existing_categories = game_data.get('categories', [])
        if existing_categories:
            categories = existing_categories.copy()
        
        # Add the current Roblox chart ID as a category (for UI filtering)
        if sort_id and sort_id not in categories:
            categories.append(sort_id)
        
        game_entry = {
            "id": f"roblox{place_id}",
            "name": game_name,
            "description": description,
            "url": f"{place_id}",
            "categories": categories,
            "serverFiles": [],
            "game": "roblox",
            "version": "latest",
            "stages": ["dev", "test", "prod"],  # Include all stages
            "universe_id": universe_id,
            "place_id": place_id,
            "player_count": playing_count,
            "rating_percentage": like_ratio,
            "total_votes": total_up_votes + total_down_votes,
            "minimum_age": game_data.get('minimumAge', 0),
            "age_display": game_data.get('ageRecommendationDisplayName', 'Unknown'),
            "is_sponsored": game_data.get('isSponsored', False),
            "roblox_sort": sort_name,  # Primary chart name
            "roblox_sort_id": sort_id,  # Primary chart ID
        }
        
        # No img field in simple mode since we don't fetch thumbnails
        
        return game_entry
    
    def load_existing_games(self, filename: str) -> Dict[str, Dict]:
        """
        Load existing games from the output file to avoid re-fetching.
        
        Args:
            filename: Path to the existing games JSON file
            
        Returns:
            Dictionary of existing games keyed by game ID, or empty dict if file doesn't exist
        """
        if not os.path.exists(filename):
            print(f"📄 No existing games file found at {filename}")
            return {}
        
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
            
            # Handle both old format (with metadata) and new format (without metadata)
            if isinstance(existing_data, dict):
                # Remove metadata if it exists (old format compatibility)
                if 'metadata' in existing_data:
                    existing_data.pop('metadata')
                
                print(f"📚 Loaded {len(existing_data)} existing games from {filename}")
                return existing_data
            else:
                print(f"⚠️  Invalid format in {filename}, starting fresh")
                return {}
                
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  Error reading {filename}: {e}")
            print("📄 Starting with empty games collection")
            return {}
    
    def export_to_gameserver_format(self, games: List[Dict], filename: str = "roblox_charts_games.json", max_details_games: Optional[int] = None) -> bool:
        """
        Export games to gameserver-details.json compatible format.
        
        Args:
            games: List of games from Roblox Charts API
            filename: Output filename
            
        Returns:
            True if successful, False otherwise
        """
        print("🔄 Converting games to gameserver format...")
        
        # Load existing games first
        existing_games = self.load_existing_games(filename)
        
        # Filter out games that already exist
        new_games = []
        existing_game_ids = set(existing_games.keys())
        
        for game in games:
            game_id = f"roblox{game.get('rootPlaceId', '')}"
            if game_id not in existing_game_ids:
                new_games.append(game)
        
        print(f"🔍 Found {len(games)} total games from API")
        print(f"📚 Already have {len(existing_games)} games in collection")
        print(f"🆕 Need to fetch {len(new_games)} new games")
        
        if not new_games:
            print("✅ No new games to fetch - collection is up to date!")
            return True
        
        if max_details_games is not None:
            print(f"📝 Fetching real descriptions for first {max_details_games} new games only...")
            print(f"⚡ Remaining {len(new_games) - max_details_games if len(new_games) > max_details_games else 0} games will use generic descriptions")
        else:
            print(f"📝 Fetching real game descriptions and thumbnails...")
        
        print("⏱️  This may take a while due to API rate limiting...")
        
        converted_games = existing_games.copy()  # Start with existing games
        failed_conversions = 0
        
        for i, game in enumerate(new_games):
            if (i + 1) % 25 == 0:
                print(f"  📊 Processing {i + 1}/{len(new_games)} new games...")
            
            # Determine if we should fetch detailed description for this game
            fetch_details = max_details_games is None or i < max_details_games
            
            if fetch_details:
                converted_game = self.convert_to_gameserver_format(game)
            else:
                # Use a simpler conversion without API calls
                converted_game = self.convert_to_gameserver_format_simple(game)
            
            if converted_game:
                converted_games[converted_game["id"]] = converted_game
            else:
                failed_conversions += 1
        
        new_games_added = len(new_games) - failed_conversions
        total_games_count = len(converted_games)
        success_rate = (new_games_added / len(new_games) * 100) if new_games else 100
        
        print(f"  ✅ Successfully converted new games: {new_games_added}")
        print(f"  ❌ Failed conversions: {failed_conversions}")
        print(f"  📊 New games success rate: {success_rate:.1f}%")
        print(f"  📚 Total games in collection: {total_games_count}")
        
        if not converted_games:
            print("❌ No games were successfully converted")
            return False
        
        # Calculate statistics by category
        category_stats = {}
        total_players = 0
        for game in converted_games.values():
            player_count = game.get('player_count', 0)
            total_players += player_count
            sort_name = game.get('roblox_sort', 'Unknown')
            
            if sort_name not in category_stats:
                category_stats[sort_name] = {'count': 0, 'players': 0}
            category_stats[sort_name]['count'] += 1
            category_stats[sort_name]['players'] += player_count
        
        # Create export data in gameserver-details.json format (without metadata)
        export_data = converted_games
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            print(f"💾 Successfully saved {total_games_count} games to {filename}")
            
            # Show summary stats
            if converted_games:
                games_list = list(converted_games.values())
                
                # Calculate stats
                avg_players = total_players / len(games_list) if games_list else 0
                max_players = max((game.get('player_count', 0) for game in games_list), default=0)
                
                all_categories = set()
                for game in games_list:
                    all_categories.update(game.get('categories', []))
                
                print(f"\n📊 Collection Summary:")
                print(f"  • Total games: {len(games_list)}")
                print(f"  • Total active players: {total_players:,}")
                print(f"  • Average players per game: {avg_players:,.0f}")
                print(f"  • Most popular game: {max_players:,} players")
                print(f"  • Categories assigned: {len(all_categories)}")
                print(f"  • Roblox sorts covered: {len(category_stats)}")
                print(f"  • Data source: Roblox Official Charts API")
                print(f"  • Format: gameserver-details.json compatible")
                
                # Show category breakdown
                print(f"\n📈 Category Breakdown:")
                for sort_name, stats in category_stats.items():
                    print(f"  • {sort_name}: {stats['count']} games ({stats['players']:,} players)")
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to save file: {e}")
            return False
    
    def get_summary_stats(self, games: List[Dict]) -> Dict:
        """Get summary statistics about the collected games."""
        if not games:
            return {}
        
        total_players = sum(game.get('playerCount', 0) for game in games)
        total_votes = sum(game.get('totalUpVotes', 0) + game.get('totalDownVotes', 0) for game in games)
        
        sorts = set(game.get('roblox_sort_name', 'Unknown') for game in games)
        age_ratings = set(game.get('ageRecommendationDisplayName', 'Unknown') for game in games)
        
        return {
            'total_games': len(games),
            'total_active_players': total_players,
            'average_players_per_game': total_players / len(games),
            'total_votes_cast': total_votes,
            'unique_sorts': list(sorts),
            'age_ratings': list(age_ratings),
            'games_with_high_player_count': len([g for g in games if g.get('playerCount', 0) > 10000])
        }








def main():
    """Example usage of the Roblox Charts scraper with enhanced descriptions"""
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Roblox Charts API Scraper')
    parser.add_argument('--max-details', type=int, default=None, 
                       help='Maximum number of games to fetch detailed descriptions for (default: all games)')
    parser.add_argument('--max-pages', type=int, default=3,
                       help='Maximum number of pages to fetch (default: 3)')
    parser.add_argument('--categories', nargs='+', 
                       help='Specific categories to fetch (default: discover all categories)')
    parser.add_argument('--blacklist', nargs='+', default=[],
                       help='Categories to exclude from collection (e.g., --blacklist "top-paid-access" "more-when-you-subscribe")')
    parser.add_argument('--blacklist-file', default='blacklist.json',
                       help='JSON file containing blacklisted categories (default: blacklist.json)')
    
    args = parser.parse_args()
    
    print("🎮 ROBLOX CHARTS API SCRAPER - ENHANCED DESCRIPTIONS")
    print("=" * 60)
    print("Fetching games from Roblox's official charts/explore API...")
    print("Now with real game descriptions and thumbnails!")
    
    print(f"📄 Pagination mode: {args.max_pages} pages")
    
    if args.max_details:
        print(f"⚡ TESTING MODE: Only fetching detailed descriptions for first {args.max_details} games")
    
    print()
    
    # Load blacklist from file and combine with command line arguments
    file_blacklist = load_blacklist_from_file(args.blacklist_file)
    combined_blacklist = list(set(args.blacklist + file_blacklist))  # Combine and deduplicate
    
    if combined_blacklist:
        print(f"🚫 Total blacklisted categories: {len(combined_blacklist)}")
        print(f"🚫 From command line: {len(args.blacklist)}")
        print(f"🚫 From file: {len(file_blacklist)}")
    
    # Initialize scraper
    scraper = RobloxChartsScraper(rate_limit_delay=1.5)  # Increased delay to prevent rate limiting
    
    # Use basic pagination with category merging
    games = scraper.fetch_all_games(max_pages=args.max_pages, blacklist=combined_blacklist)
    
    if not games:
        print("❌ No games were fetched")
        return
    
    print(f"📊 Fetched {len(games)} games total")
    
    # Show summary
    stats = scraper.get_summary_stats(games)
    print(f"\n📈 Collection Statistics:")
    for key, value in stats.items():
        if isinstance(value, list):
            print(f"  • {key}: {len(value)} items")
        elif isinstance(value, (int, float)):
            print(f"  • {key}: {value:,}" if isinstance(value, int) else f"  • {key}: {value:.1f}")
    
    # Export to gameserver format
    filename = "roblox_charts_games.json"
    success = scraper.export_to_gameserver_format(games, filename, max_details_games=args.max_details)
    
    if success:
        print(f"\n✅ Enhanced scraping complete! Data saved to {filename}")
        
        if args.max_details:
            detailed_count = min(args.max_details, len(games))
            generic_count = len(games) - detailed_count
            print(f"📝 {detailed_count} games with real descriptions, {generic_count} games with generic descriptions")
        else:
            print("📝 All games include real descriptions and thumbnails!")
        
        # Show thumbnail statistics
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            games_with_thumbnails = 0
            games_without_thumbnails = 0
            for key, game in data.items():
                if key == 'metadata':
                    continue
                if game.get('img'):
                    games_with_thumbnails += 1
                else:
                    games_without_thumbnails += 1
            
            print(f"🖼️  Thumbnail coverage: {games_with_thumbnails} games with thumbnails, {games_without_thumbnails} games without thumbnails")
            if games_without_thumbnails > 0:
                print(f"   ⚠️  {games_without_thumbnails} games missing thumbnails - check API responses above")
                
        except Exception as e:
            print(f"❌ Could not analyze thumbnail coverage: {e}")
        
        # Show category summary from the converted data
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            print(f"\n🏷️  Category Summary:")
            print(f"  🔍 Debug: File loaded, data type: {type(data)}")
            print(f"  🔍 Debug: Data keys: {list(data.keys())[:5]}...")  # Show first 5 keys
            
            all_categories = set()
            category_counts = {}
            total_games = 0
            
            for key, game in data.items():
                if key == 'metadata':
                    continue
                total_games += 1
                
                # Get all categories for this game (including merged categories from multiple charts)
                categories = game.get('categories', [])
                if categories:
                    for category in categories:
                        all_categories.add(category)
                        category_counts[category] = category_counts.get(category, 0) + 1
            
            print(f"  🔍 Debug: Processed {total_games} games")
            print(f"  🔍 Debug: Found categories: {list(all_categories)[:5]}...")  # Show first 5 categories
            
            if all_categories:
                print(f"  📊 Found {len(all_categories)} unique Roblox chart categories:")
                # Sort categories by count (descending)
                sorted_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
                for category, count in sorted_categories:
                    print(f"    • {category}: {count} games")
                
                total_category_entries = sum(category_counts.values())
                print(f"  📝 Total category entries: {total_category_entries:,}")
                print(f"  📝 Unique games: {total_games:,}")
                print(f"  📝 Average categories per game: {total_category_entries/total_games:.1f}")
            else:
                print("  ❌ No categories found in the data")
                print("  🔍 Debug: Sample game data:")
                if total_games > 0:
                    sample_key = next(k for k in data.keys() if k != 'metadata')
                    sample_game = data[sample_key]
                    print(f"    Sample game: {sample_game.get('name', 'Unknown')}")
                    print(f"    Sample categories: {sample_game.get('categories', 'None')}")
                
        except Exception as e:
            print(f"❌ Could not analyze category coverage: {e}")
            import traceback
            traceback.print_exc()
        
        # Quick check for age-restricted games
        try:
            with open(filename, 'r') as f:
                data = json.load(f)
            
            age_restricted_count = 0
            for key, game in data.items():
                if key == 'metadata':
                    continue
                if game.get('minimum_age', 0) > 13:
                    age_restricted_count += 1
            
            if age_restricted_count > 0:
                print(f"🔞 Found {age_restricted_count} age-restricted games (13+)")
                print("   Run 'python3 analyze_age_restricted_games.py' to see details!")
            else:
                print("ℹ️  No age-restricted games found in this sample")
                
        except Exception as e:
            print(f"❌ Could not analyze age restrictions: {e}")
        
    else:
        print(f"\n❌ Failed to save data")


if __name__ == "__main__":
    main() 