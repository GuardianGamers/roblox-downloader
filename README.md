# Roblox APK Downloader

This project uses Playwright with stealth mode to automatically download Roblox APK files from APKCombo.

## Quick Start with Docker (Recommended)

### Build and run:
```bash
make run
```

This will build the Docker image and download the latest Roblox APK to `./downloads/`

### Check version only:
```bash
make run-check
```

### Other Docker commands:
```bash
make build              # Build the Docker image
make run                # Download and extract Roblox APK
make run-check          # Check version without downloading
make run-custom ARGS="--force --extract"  # Run with custom arguments
make deploy STAGE=prod  # Deploy to AWS ECR
make build-info         # Show build information
make clean              # Remove local Docker images
make help               # Show all available commands
```

## Installation (Local Development)

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Install Playwright browsers:
```bash
playwright install chromium
```

## Usage

### Check current version without downloading:
```bash
python download_roblox.py --check-only
```

### Smart download (only downloads if new version available):
```bash
python download_roblox.py --extract
```
This will:
- Check the current Roblox version on APKCombo
- Compare with any locally downloaded version
- Only download if a newer version is available
- Skip download if you already have the latest version

### Force download even if same version:
```bash
python download_roblox.py --extract --force
```

### Specify custom output directory:
```bash
python download_roblox.py --output-dir ./my-downloads --extract
```

### Custom URL:
```bash
python download_roblox.py --url "https://apkcombo.com/downloader/#package=com.roblox.client&device=tablet&arches=x86_64"
```

## What it does

1. Opens the APKCombo download page using Playwright with stealth mode (undetectable browser)
2. Waits for the download link to appear (usually takes a few seconds)
3. Downloads the XAPK file using the browser (required for Cloudflare protection)
4. Optionally extracts and processes the XAPK file (if `--extract` is used):
   - Extracts the XAPK (which is a ZIP file)
   - Renames APK files to match expected format
   - Checks for x86_64 architecture support
   - Creates a manifest.json file

## Why use the browser for downloading?

APKCombo protects their download links with **Cloudflare** which requires JavaScript challenge solving. The download link itself (even after you get it from the page) is still protected and will return a Cloudflare challenge page if you try to access it with plain HTTP requests. Therefore, we need to use the browser (Playwright) for both finding AND downloading the file, as the browser automatically solves Cloudflare challenges.

## Features

- **Version Checking**: Automatically detects the current Roblox version and compares with local files
- **Smart Downloads**: Only downloads when a new version is available (use `--force` to override)
- **Undetectable Browser**: Uses Playwright with stealth techniques to avoid detection
- **Automatic Link Detection**: Waits for the download link to appear dynamically
- **Cloudflare Bypass**: Automatically handles Cloudflare protection
- **Error Handling**: Takes screenshots on errors for debugging
- **APK Processing**: Compatible with the parsing logic from `../game-assets/install-apkcombo.py`

## AWS Deployment (Automated Daily Downloads)

Deploy to AWS Lambda with scheduled daily downloads to S3:

### Prerequisites:
- AWS CLI configured
- AWS SAM CLI installed
- Docker running

### Deploy:
```bash
# Validate template
make sam-validate

# Deploy to dev environment
make sam-deploy STAGE=dev

# Deploy to production
make sam-deploy STAGE=prod
```

### What gets deployed:
- **S3 Bucket**: `roblox-{AccountId}-{Stage}` with `/apk` directory
- **Lambda Function**: Docker-based function with 15 minute timeout
- **EventBridge Rule**: Daily schedule (default: 12:00 UTC)
- **CloudWatch Logs**: 30-day retention
- **CloudWatch Alarm**: Alert on Lambda errors
- **IAM Roles**: Least-privilege access to S3, SSM, and CloudWatch
- **SSM Parameters**: Store bucket info and current version

### Manage deployment:
```bash
make sam-status STAGE=dev      # Check stack status
make sam-logs STAGE=dev        # Tail Lambda logs
make sam-invoke STAGE=dev      # Manually trigger download
make sam-delete STAGE=dev      # Delete stack
```

### Check downloaded files:
```bash
# List files in S3
aws s3 ls s3://roblox-{AccountId}-dev/apk/ --recursive

# Download latest APK
aws s3 cp s3://roblox-{AccountId}-dev/apk/Roblox_latest_apkcombo.com.xapk ./
```

## Notes

- The browser will open in visible mode (not headless) for local runs
- Lambda runs in headless mode automatically
- If the download link doesn't appear, a screenshot will be saved for debugging
- The script requires x86_64 architecture support in the downloaded APK
- Lambda function has 15-minute timeout and 2GB memory

