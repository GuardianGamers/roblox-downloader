# Next Steps for Gameservers Integration

## ✅ Completed
1. Created `update_gameservers.py` module with AI moderation
2. Integrated with `ecs_task.py`
3. Updated `Dockerfile` to include new module
4. Updated `template.yaml` with:
   - Bedrock IAM permissions
   - S3 ListObjectsV2 permissions
   - UPDATE_GAMESERVERS environment variable
   - ACTION changed to "all"
5. Updated README with new features

## 🔧 Required Before Deployment

### 1. Copy Roblox Charts Scraper into This Repo
The `update_gameservers.py` module depends on `roblox_charts_scraper.py` from the `game-assets` repo.

**Option A: Copy the file (simple)**
```bash
cp ../game-assets/roblox_charts_scraper.py .
git add roblox_charts_scraper.py
```

**Option B: Use git submodule (advanced)**
```bash
git submodule add git@github.com:GuardianGamers/game-assets.git
```

**Option C: Inline the Roblox API calls (best for production)**
Extract just the API calls from `roblox_charts_scraper.py` and put them directly in `update_gameservers.py`. This removes the external dependency.

### 2. Update Dockerfile to Include Charts Scraper
```dockerfile
# Add after copying update_gameservers.py:
COPY roblox_charts_scraper.py /app/roblox_charts_scraper.py
# Or if using submodule:
COPY game-assets/roblox_charts_scraper.py /app/roblox_charts_scraper.py
```

### 3. Test Locally
```bash
# Build new Docker image
make docker-build STAGE=dev

# Test APK download + gameservers update
make docker-run STAGE=dev

# Or test gameservers only:
docker run --rm \
  -e ACTION=gameservers \
  -e UPDATE_GAMESERVERS=true \
  -e BUCKET_NAME=test-bucket \
  -e AWS_REGION=us-east-1 \
  -v ~/.aws:/root/.aws:ro \
  -v $(PWD)/downloads:/downloads \
  roblox-downloader-dev:latest
```

### 4. Deploy to AWS
```bash
DOCKER_BUILDKIT=0 make deploy STAGE=dev
```

## 📝 Configuration

### Environment Variables (already in template.yaml)
- `ACTION=all` - Runs both APK download and gameservers update
- `UPDATE_GAMESERVERS=true` - Enable gameservers update
- `BUCKET_NAME` - S3 bucket (auto-set by CloudFormation)

### Testing Different Actions
You can override the ACTION in CloudFormation by updating the parameter:
- `ACTION=download` - Only download Roblox APK
- `ACTION=gameservers` - Only update gameservers
- `ACTION=all` - Do both (default)

## 🎯 Expected Results

### S3 Structure After First Run
```
s3://roblox-{AccountId}-dev/
├── apk/
│   └── 2.692.843/
│       ├── com.roblox.client_2.692.843.xapk
│       └── extracted/...
└── gameservers/
    └── 2025-10-06/
        ├── gameservers.json      # ~100-200 approved games
        └── exclusions.json       # Excluded place IDs
```

### Daily Behavior
- **12:00 UTC**: EventBridge triggers ECS task
- **APK Check**: Checks if new Roblox version exists
  - If yes: Downloads and uploads to S3
  - If no: Skips download
- **Gameservers Update**: Always runs
  - Fetches latest Roblox games
  - AI reviews each game description
  - Creates new daily directory
  - Carries forward previous exclusions

## 🔍 Monitoring

### CloudWatch Logs
```bash
# View latest logs
aws logs tail /ecs/roblox-downloader-dev --follow
```

### Check Results in S3
```bash
# List recent gameservers snapshots
aws s3 ls s3://roblox-{AccountId}-dev/gameservers/ --recursive

# Download latest gameservers.json
aws s3 cp s3://roblox-{AccountId}-dev/gameservers/$(date +%Y-%m-%d)/gameservers.json .
```

## 💰 Cost Estimates

### AWS Bedrock Claude 3.5 Sonnet
- **Input**: ~200 games × 500 tokens = 100K tokens
- **Output**: ~200 games × 200 tokens = 40K tokens
- **Cost**: ~$0.30/day (~$9/month)

### ECS Fargate
- **Task**: 2 vCPU, 4 GB RAM
- **Duration**: ~10-15 minutes/day
- **Cost**: ~$0.05/day (~$1.50/month)

### Total Estimated Cost: ~$10.50/month

## ⚠️ Important Notes

1. **Bedrock Model Access**: Ensure you have access to Claude 3.5 Sonnet v2 in us-east-1
2. **First Run**: Will process all games (200+), subsequent runs only new games
3. **Exclusions**: Once a game is excluded, it stays excluded unless manually removed
4. **API Rate Limits**: Roblox API has rate limits, scraper includes delays

## 🐛 Troubleshooting

### "Module not found: roblox_charts_scraper"
→ Copy the file from game-assets repo (see step 1 above)

### "Access denied: bedrock:InvokeModel"
→ Request model access in AWS Console: Bedrock → Model access

### "No games fetched"
→ Check CloudWatch logs for Roblox API errors or rate limiting

### "KeyError: BUCKET_NAME"
→ Environment variable missing, check task definition in template.yaml
