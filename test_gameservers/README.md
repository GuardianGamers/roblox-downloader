# Test Gameservers Directory

This directory contains sample data for local testing of the gameservers update module.

## Structure

```
test_gameservers/
├── 2025-10-05/                    # Sample previous day
│   ├── gameservers.json           # Sample approved games
│   └── exclusions.json            # Sample excluded place IDs (3 games)
└── YYYY-MM-DD/                    # New directories created when tests run
    ├── gameservers.json
    └── exclusions.json
```

## Purpose

- **Local Testing**: Test gameservers update without AWS credentials
- **Exclusion History**: Verify that previous exclusions are carried forward
- **AI Testing**: Test AI moderation on real game data
- **Integration Testing**: Full end-to-end test without S3

## Sample Data

The `2025-10-05` directory contains:
- 1 approved game (99 Nights in the Forest)
- 3 excluded place IDs

When you run tests, the module will:
1. Load exclusions from `2025-10-05`
2. Fetch new games from Roblox
3. Skip the 3 already-excluded games
4. AI-review new games
5. Save results to a new date directory

## Usage

```bash
# Test with local directory (no AWS needed for scraper test)
python3 test_gameservers_local.py --test scraper --no-s3

# Test full flow with AI (requires AWS Bedrock)
python3 test_gameservers_local.py --test full

# Use S3 instead of local
python3 test_gameservers_local.py --test full --use-s3 --bucket my-test-bucket
```

## Cleanup

To reset test data:
```bash
# Keep only the sample data
rm -rf test_gameservers/2025-10-0[6-9] test_gameservers/2025-10-[1-3]*
```
