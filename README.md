# Roblox APK Downloader

This project uses Playwright with stealth mode to automatically download Roblox APK files from APKCombo.

## Installation

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

## Notes

- The browser will open in visible mode (not headless) to better avoid detection
- If the download link doesn't appear, a screenshot will be saved for debugging
- The script requires x86_64 architecture support in the downloaded APK

