# Roblox APK Downloader

This project uses Playwright with stealth mode to automatically download Roblox APK files from APKCombo.

## Quick Start

### AWS Deployment (Recommended):
```bash
# Deploy full stack to AWS
make deploy STAGE=dev
```

This deploys the complete infrastructure: Lambda, S3, EventBridge schedule, CloudWatch, etc.

### Local Docker Testing:
```bash
# Build and run locally
make local-run

# Check version only
make local-check
```

### All Commands:
```bash
# AWS ECS Fargate deployment
make validate           # Validate CloudFormation template
make build              # Build Docker image
make push               # Push image to ECR
make deploy             # Deploy to AWS (builds, pushes, deploys)
make logs               # View ECS task logs
make run-task           # Manually trigger download
make status             # Show stack status
make delete             # Delete stack

# Local Docker testing
make local-build        # Build Docker image locally
make local-run          # Run container locally
make local-check        # Check version without downloading
make local-info         # Show build information
make local-clean        # Remove local Docker images

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

Deploy to AWS ECS Fargate with scheduled daily downloads to S3:

### Prerequisites:
- AWS CLI configured
- Docker running (for building the image)

### Deploy:
```bash
# Validate template
make validate

# Build, push to ECR, and deploy to dev environment
make deploy STAGE=dev

# Deploy to production
make deploy STAGE=prod
```

### What gets deployed:
- **S3 Bucket**: `roblox-{AccountId}-{Stage}` with:
  - `/apk/{version}/` - Version-organized Roblox APKs
  - `/gameservers/{YYYY-MM-DD}/` - Daily gameservers.json snapshots
- **ECS Cluster & Task Definition**: Fargate task running:
  - Chromium + Playwright for APK downloads
  - Roblox Charts API scraper
  - AWS Bedrock Claude for AI content moderation
- **ECR Repository**: Stores Docker images for the downloader
- **VPC & Networking**: Public subnets for internet access
- **EventBridge Rule**: Daily schedule (default: 12:00 UTC)
- **CloudWatch Logs**: 30-day retention for ECS task logs
- **IAM Roles**: Least-privilege access to S3, SSM, ECR, CloudWatch, and Bedrock
- **SSM Parameters**: Store bucket info and current version
- **Version History**: Complete history of APK versions and daily gameserver snapshots

### Why ECS Fargate instead of Lambda?
Lambda has limitations for browser automation:
- Amazon Linux 2 has GLIBC 2.26, but Chromium requires GLIBC 2.27+
- Lambda has a 10GB image size limit (Chromium + dependencies are large)
- Lambda has stricter resource constraints for long-running browser operations

ECS Fargate provides:
- Full Debian/Ubuntu base images with modern GLIBC
- No image size limits
- More CPU/memory for Chromium
- Better suited for browser automation workloads

### Manage deployment:
```bash
make status STAGE=dev      # Check stack status
make logs STAGE=dev        # Tail ECS task logs
make run-task STAGE=dev    # Manually trigger download
make delete STAGE=dev      # Delete stack
```

### Check downloaded files:
```bash
# List all versions
aws s3 ls s3://roblox-{AccountId}-dev/apk/

# List files for a specific version
aws s3 ls s3://roblox-{AccountId}-dev/apk/2.692.843/ --recursive

# Download specific version
aws s3 cp s3://roblox-{AccountId}-dev/apk/2.692.843/Roblox_2.692.843_apkcombo.com.xapk ./

# Download extracted APKs for a version
aws s3 sync s3://roblox-{AccountId}-dev/apk/2.692.843/extracted/ ./roblox-apks/
```

### S3 Structure:
```
s3://roblox-{AccountId}-{Stage}/
└── apk/
    ├── 2.692.843/
    │   ├── Roblox_2.692.843_apkcombo.com.xapk
    │   └── extracted/
    │       ├── base.apk
    │       ├── split_config.x86_64.apk
    │       └── manifest.json
    ├── 2.693.100/
    │   ├── Roblox_2.693.100_apkcombo.com.xapk
    │   └── extracted/
    │       └── ...
    └── (each version in its own directory)
```

## Notes

- The browser will open in visible mode (not headless) for local runs
- ECS tasks run in headless mode automatically
- If the download link doesn't appear, a screenshot will be saved for debugging
- The script requires x86_64 architecture support in the downloaded APK
- ECS Fargate task has 2 vCPU and 4GB memory allocated

