# Gameservers Integration

## Overview
Added daily gameservers.json management to the roblox-downloader ECS task. Each day:
1. Fetches latest games from Roblox charts
2. Uses AWS Bedrock Claude to sanitize descriptions and flag inappropriate content
3. Maintains an exclusion list of inappropriate game place IDs
4. Saves to S3 with date-stamped directories

## New Files

### `update_gameservers.py`
Core module for gameservers management:
- `fetch_latest_roblox_games()` - Calls existing charts scraper from game-assets
- `sanitize_description_with_ai()` - Uses AWS Bedrock Claude Sonnet to:
  - Remove external links (Discord, YouTube, social media)
  - Flag horror, violence, dating, mature content
  - Determine age appropriateness for under-13 audience
- `load_exclusion_list()` - Loads previous exclusions from S3
- `save_gameservers_to_s3()` - Saves to daily directories
- `update_gameservers()` - Main orchestration function

## Integration Points

### 1. `ecs_task.py` Changes Needed
```python
# Add import
from update_gameservers import update_gameservers

# Add environment variable
update_games = os.environ.get('UPDATE_GAMESERVERS', 'true').lower() == 'true'

# After APK download, add:
if update_games and action in ['all', 'gameservers']:
    gameservers_result = update_gameservers(
        bucket_name=bucket_name,
        s3_prefix=""  # Store in root: gameservers/YYYY-MM-DD/
    )
```

### 2. `template.yaml` Changes Needed
```yaml
# In RobloxDownloaderTaskDefinition Environment:
- Name: ACTION
  Value: "all"  # Changed from "download"
- Name: UPDATE_GAMESERVERS
  Value: "true"

# In RobloxDownloaderTaskRole, add Bedrock policy:
- PolicyName: BedrockAccess
  PolicyDocument:
    Version: '2012-10-17'
    Statement:
      - Effect: Allow
        Action:
          - bedrock:InvokeModel
        Resource:
          - !Sub "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-3-5-sonnet-20241022-v2:0"

# In S3 policy, add:
- s3:ListObjectsV2  # For loading previous exclusions
```

### 3. `Dockerfile` - Already Updated ✓
Added: `COPY update_gameservers.py /app/update_gameservers.py`

## S3 Structure

```
s3://roblox-{AccountId}-{Stage}/
├── apk/
│   ├── 2.692.843/
│   │   ├── com.roblox.client_2.692.843.xapk
│   │   └── extracted/...
│   └── 2.693.001/
│       └── ...
└── gameservers/
    ├── 2025-10-06/
    │   ├── gameservers.json       # Approved games
    │   └── exclusions.json        # Excluded place IDs with AI reasoning
    ├── 2025-10-07/
    │   ├── gameservers.json
    │   └── exclusions.json
    └── ...
```

## AI Content Moderation

AWS Bedrock Claude reviews each game and returns:
```json
{
  "sanitized_description": "Cleaned description without external links",
  "is_appropriate_for_under13": true,
  "flags": ["horror", "violence"],  // or []
  "reasoning": "Game contains scary elements..."
}
```

Games flagged as inappropriate are:
- Added to `exclusions.json`
- NOT included in `gameservers.json`
- Carried forward to next day's exclusion list

## Deployment

After making the changes above:

```bash
# Build and deploy
DOCKER_BUILDKIT=0 make deploy STAGE=dev
```

## Testing Locally

```bash
# Test gameservers update only
python3 update_gameservers.py --bucket test-bucket --prefix gameservers/

# Test in Docker
docker run --rm \
  -e ACTION=gameservers \
  -e UPDATE_GAMESERVERS=true \
  -e BUCKET_NAME=test-bucket \
  -e AWS_REGION=us-east-1 \
  -v ~/.aws:/root/.aws:ro \
  roblox-downloader:latest
```

## Dependencies

- Existing `../game-assets/roblox_charts_scraper.py` must be accessible
- AWS Bedrock Claude Sonnet model access in us-east-1
- IAM permissions for Bedrock InvokeModel

## Benefits

1. **Daily Fresh Content**: Always up-to-date game list
2. **AI-Powered Safety**: Automated content moderation
3. **Version History**: Complete audit trail of all changes
4. **Efficiency**: Only processes new games, carries forward exclusions
5. **Single Task**: Combined with APK downloads for operational simplicity
