#!/usr/bin/env python3

import os
import sys
import json
import zipfile
import shutil
import argparse
import re
import time
import hashlib
from pathlib import Path
from typing import Optional, List
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

def log(message):
    """Log a message to stdout with timestamp."""
    from datetime import datetime
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    print(f"[{timestamp} UTC] {message}")

def get_current_version(url: str, output_dir: Optional[str] = None) -> Optional[str]:
    """
    Get the current Roblox version from APKCombo page.
    
    Args:
        url: APKCombo URL to check
        output_dir: Optional directory to save debug files (screenshots, HTML) on error
    
    Returns:
        Version string like "2.692.843" or None if not found.
    """
    log("Checking current Roblox version on APKCombo...")
    
    # Always use headless for version checking
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox'
            ]
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        
        try:
            page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Look for version in the page content
            # Try to find it in the download link that appears
            time.sleep(3)  # Wait a bit for dynamic content
            
            # Check if there's a version in the generated download link
            links = page.query_selector_all('a[href^="https://apkcombo.com/d?u="]')
            if links:
                href = links[0].get_attribute('href')
                if href and 'name=' in href:
                    import base64
                    import urllib.parse
                    # Decode the base64 URL parameter
                    if 'u=' in href:
                        encoded = href.split('u=')[1].split('&')[0]
                        try:
                            decoded = base64.b64decode(encoded).decode('utf-8')
                            # Extract version from filename like "Roblox_2.692.843_apkcombo.com.xapk"
                            version_match = re.search(r'Roblox[_-](\d+\.\d+\.\d+)', decoded)
                            if version_match:
                                version = version_match.group(1)
                                log(f"Found version: {version}")
                                return version
                        except:
                            pass
            
            # Fallback: Look for version in page text
            page_content = page.content()
            version_match = re.search(r'(\d+\.\d+\.\d+)', page_content)
            if version_match:
                version = version_match.group(1)
                log(f"Found version from page: {version}")
                return version
            
            # Could not find version - save debug files if output_dir provided
            log("Could not find version number on page")
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                log("Saving debug files for troubleshooting...")
                
                # Save screenshot
                screenshot_path = os.path.join(output_dir, 'version_check_screenshot.png')
                page.screenshot(path=screenshot_path, full_page=True)
                log(f"Screenshot saved to: {screenshot_path}")
                
                # Save page HTML
                html_path = os.path.join(output_dir, 'version_check_page.html')
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(page.content())
                log(f"Page HTML saved to: {html_path}")
            
            return None
            
        except Exception as e:
            log(f"Error getting version: {str(e)}")
            
            # Save debug files on exception if output_dir provided
            if output_dir:
                try:
                    os.makedirs(output_dir, exist_ok=True)
                    log("Saving debug files after error...")
                    
                    screenshot_path = os.path.join(output_dir, 'version_check_error_screenshot.png')
                    page.screenshot(path=screenshot_path, full_page=True)
                    log(f"Error screenshot saved to: {screenshot_path}")
                    
                    html_path = os.path.join(output_dir, 'version_check_error_page.html')
                    with open(html_path, 'w', encoding='utf-8') as f:
                        f.write(page.content())
                    log(f"Error page HTML saved to: {html_path}")
                except Exception as debug_error:
                    log(f"Could not save debug files: {debug_error}")
            
            return None
        finally:
            browser.close()

def read_local_version(download_dir: str) -> Optional[str]:
    """
    Read the version of the most recently downloaded XAPK file.
    Returns version string or None if no files found.
    """
    try:
        import glob
        xapk_files = glob.glob(os.path.join(download_dir, "Roblox_*_apkcombo.com.xapk"))
        if not xapk_files:
            return None
        
        # Get the most recent file
        latest_file = max(xapk_files, key=os.path.getmtime)
        filename = os.path.basename(latest_file)
        
        # Extract version from filename
        version_match = re.search(r'Roblox[_-](\d+\.\d+\.\d+)', filename)
        if version_match:
            version = version_match.group(1)
            log(f"Local version found: {version}")
            return version
    except Exception as e:
        log(f"Error reading local version: {str(e)}")
    
    return None

def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.
    Returns: 1 if v1 > v2, -1 if v1 < v2, 0 if equal
    """
    def parse_version(v):
        return [int(x) for x in v.split('.')]
    
    v1_parts = parse_version(v1)
    v2_parts = parse_version(v2)
    
    if v1_parts > v2_parts:
        return 1
    elif v1_parts < v2_parts:
        return -1
    else:
        return 0

def download_with_playwright(url: str, download_dir: str) -> Optional[str]:
    """
    Use Playwright with stealth mode to download the APK file.
    
    Note: We must use the browser for both finding AND downloading the file
    because the download link is protected by Cloudflare which requires
    browser cookies/challenge solutions. Using requests library directly
    will just get the Cloudflare challenge page, not the actual file.
    
    Returns the path to the downloaded file or None if failed.
    """
    log(f"Navigating to: {url}")
    
    # Check if we should run headless (e.g., in Docker)
    headless = os.environ.get('HEADLESS', 'false').lower() == 'true'
    log(f"Running in {'HEADLESS' if headless else 'VISIBLE'} mode (HEADLESS env var: {os.environ.get('HEADLESS', 'not set')})")
    
    with sync_playwright() as p:
        # Launch browser (headless in Docker, visible otherwise)
        browser = p.chromium.launch(
            headless=headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
        
        # Create context with stealth settings
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            accept_downloads=True
        )
        
        # Additional stealth JavaScript
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            window.chrome = {
                runtime: {}
            };
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)
        
        page = context.new_page()
        
        try:
            # Navigate to the page
            log("Loading the page...")
            page_start = time.time()
            page.goto(url, wait_until='networkidle', timeout=60000)
            log(f"Page loaded in {time.time() - page_start:.2f}s")
            
            log("Waiting for download link to appear (max 60 seconds)...")
            
            # Wait for the download link to appear - check multiple possible selectors
            download_link = None
            max_wait_time = 60  # seconds (increased from 30)
            start_time = time.time()
            
            while time.time() - start_time < max_wait_time:
                elapsed = time.time() - start_time
                if elapsed > 0 and int(elapsed) % 10 == 0 and elapsed - int(elapsed) < 0.5:
                    log(f"Still waiting... ({elapsed:.1f}s elapsed)")
                
                # Try to find any link that starts with https://apkcombo.com/d?u=
                links = page.query_selector_all('a[href^="https://apkcombo.com/d?u="]')
                
                if links:
                    download_link = links[0].get_attribute('href')
                    log(f"Found download link after {elapsed:.2f}s: {download_link}")
                    break
                
                # Also try button elements with onclick handlers or download attributes
                buttons = page.query_selector_all('a[download], button[download], a.download-btn, button.download-btn')
                for button in buttons:
                    href = button.get_attribute('href')
                    if href and 'apkcombo.com/d?u=' in href:
                        download_link = href
                        log(f"Found download link in button: {download_link}")
                        break
                
                if download_link:
                    break
                    
                time.sleep(0.5)
            
            if not download_link:
                elapsed = time.time() - start_time
                log(f"Error: Download link not found after {elapsed:.2f}s")
                log("Taking screenshot for debugging...")
                screenshot_path = os.path.join(download_dir, 'debug_screenshot.png')
                page.screenshot(path=screenshot_path)
                log(f"Screenshot saved to: {screenshot_path}")
                
                # Also save page HTML for debugging
                html_path = os.path.join(download_dir, 'debug_page.html')
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(page.content())
                log(f"Page HTML saved to: {html_path}")
                return None
            
            log("Starting download with browser (required for Cloudflare)...")
            
            # Use Playwright to download - it handles Cloudflare automatically
            # First try clicking the link element (preferred method)
            with page.expect_download(timeout=120000) as download_info:
                try:
                    link_element = page.query_selector(f'a[href="{download_link}"]')
                    if link_element:
                        link_element.click()
                    else:
                        # If we can't find the element, try navigating without waiting for load
                        page.goto(download_link, wait_until='commit')
                except Exception as e:
                    # The page.goto might fail with "Download is starting" which is actually success
                    if 'Download is starting' not in str(e):
                        raise
                    # Otherwise continue - download has started
            
            download = download_info.value
            
            # Get the suggested filename
            suggested_filename = download.suggested_filename
            log(f"Downloading: {suggested_filename}")
            
            # Save the file
            download_path = os.path.join(download_dir, suggested_filename)
            download.save_as(download_path)
            
            log(f"Downloaded successfully to: {download_path}")
            
            return download_path
            
        except PlaywrightTimeoutError as e:
            log(f"Timeout error: {str(e)}")
            log("Taking screenshot for debugging...")
            page.screenshot(path=os.path.join(download_dir, 'timeout_screenshot.png'))
            return None
        except Exception as e:
            log(f"Error during download: {str(e)}")
            try:
                page.screenshot(path=os.path.join(download_dir, 'error_screenshot.png'))
            except:
                pass
            return None
        finally:
            browser.close()

def extract_xapk(xapk_file: str, extract_dir: str) -> bool:
    """Extract XAPK file to the specified directory."""
    log(f"Extracting XAPK file: {xapk_file}")
    
    try:
        with zipfile.ZipFile(xapk_file, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        log(f"Successfully extracted XAPK to: {extract_dir}")
        return True
    except zipfile.BadZipFile:
        log(f"Error: {xapk_file} is not a valid ZIP file")
        return False
    except Exception as e:
        log(f"Error extracting XAPK file: {str(e)}")
        return False

def process_apkcombo_contents(extract_dir: str, version: str) -> bool:
    """Process the extracted APKCombo XAPK contents."""
    log("Processing APKCombo XAPK contents")
    
    extracted_files = os.listdir(extract_dir)
    apk_files = [f for f in extracted_files if f.endswith(".apk")]
    
    if not apk_files:
        log("Error: No APK files found in the extracted XAPK")
        return False
    
    log(f"Found APK files: {apk_files}")
    
    # Process APK files according to APKCombo format
    required_apks = []
    base_apk = None
    
    for apk_file in apk_files:
        if apk_file == "com.roblox.client.apk":
            # This is the main APK - rename it to base.apk
            base_apk = apk_file
            old_path = os.path.join(extract_dir, apk_file)
            new_path = os.path.join(extract_dir, "base.apk")
            os.rename(old_path, new_path)
            log(f"Renamed {apk_file} to base.apk")
            required_apks.append("base.apk")
        elif apk_file.startswith("config.") and apk_file.endswith(".apk"):
            # Rename config.* files to split_config.*
            arch = apk_file.replace("config.", "").replace(".apk", "")
            new_name = f"split_config.{arch}.apk"
            old_path = os.path.join(extract_dir, apk_file)
            new_path = os.path.join(extract_dir, new_name)
            os.rename(old_path, new_path)
            log(f"Renamed {apk_file} to {new_name}")
            required_apks.append(new_name)
        elif apk_file.startswith("split_config.") and apk_file.endswith(".apk"):
            # Keep split_config files as-is
            required_apks.append(apk_file)
        else:
            # Keep other APK files as-is
            required_apks.append(apk_file)
    
    if not base_apk:
        log("Warning: No com.roblox.client.apk found")
    
    # Check if x86_64 architecture is present
    has_x86_64 = any("x86_64" in apk for apk in required_apks)
    
    if not has_x86_64:
        log("❌ ERROR: No x86_64 architecture files found in this APKCombo XAPK!")
        log("This version is not compatible with x86_64 systems.")
        return False
    
    log(f"✅ x86_64 architecture detected")
    log(f"Prepared APK files: {required_apks}")
    return True

def create_manifest(extract_dir: str, version: str) -> bool:
    """Create a manifest.json file for the extracted APKs."""
    log("Creating manifest.json file")
    
    extracted_files = os.listdir(extract_dir)
    apk_files = [f for f in extracted_files if f.endswith(".apk")]
    
    if not apk_files:
        log("Error: No APK files found in the extracted XAPK")
        return False
    
    # Create manifest data
    manifest_data = {
        "package_name": "com.roblox.client",
        "version_name": version,
        "app_name": "roblox"
    }
    
    # Add all APK files to the manifest
    for file in apk_files:
        manifest_data[file] = {
            "path": file,
            "size": os.path.getsize(os.path.join(extract_dir, file))
        }
    
    # Write manifest.json
    manifest_path = os.path.join(extract_dir, "manifest.json")
    try:
        with open(manifest_path, 'w') as f:
            json.dump(manifest_data, f, indent=2)
        log(f"Created manifest.json with {len(apk_files)} APK files")
        return True
    except Exception as e:
        log(f"Error creating manifest.json: {str(e)}")
        return False

def verify_apk_signatures(extract_dir: str) -> bool:
    """
    Verify APK signatures to ensure authenticity.
    
    Args:
        extract_dir: Directory containing extracted APK files
        
    Returns:
        True if verification was successful, False otherwise
    """
    try:
        from apksigtool import (
            extract_v2_sig,
            parse_apk_signing_block,
            show_x509_certificate,
            APK_SIGNATURE_SCHEME_V2_BLOCK_ID,
            APK_SIGNATURE_SCHEME_V3_BLOCK_ID
        )
    except ImportError:
        log("⚠️  apksigtool not installed - skipping signature verification")
        log("   Install with: pip install apksigtool")
        return True  # Don't fail if tool not available
    
    log("\n" + "="*70)
    log("🔐 Verifying APK Signatures")
    log("="*70)
    
    # Find all APK files
    apk_files = [f for f in os.listdir(extract_dir) if f.endswith('.apk')]
    
    if not apk_files:
        log("No APK files found for verification")
        return False
    
    log(f"Found {len(apk_files)} APK file(s) to verify")
    
    all_verified = True
    certificates_found = []
    
    for apk_file in apk_files:
        apk_path = os.path.join(extract_dir, apk_file)
        log(f"\n📦 Analyzing: {apk_file}")
        
        try:
            # Extract APK Signing Block
            result = extract_v2_sig(apk_path, expected=False)
            
            if result is None:
                log("  ⚠️  No V2/V3 signature found (may have V1 only)")
                continue
            
            sb_offset, sig_block = result
            signing_block = parse_apk_signing_block(sig_block)
            
            # Look for V2 and V3 signatures
            has_v2 = False
            has_v3 = False
            v2_block = None
            v3_block = None
            
            for pair in signing_block.pairs:
                if pair.id == APK_SIGNATURE_SCHEME_V2_BLOCK_ID:
                    has_v2 = True
                    v2_block = pair
                elif pair.id == APK_SIGNATURE_SCHEME_V3_BLOCK_ID:
                    has_v3 = True
                    v3_block = pair
            
            if not has_v2 and not has_v3:
                log("  ⚠️  No V2/V3 signature blocks found")
                continue
            
            # Display signature scheme info
            if has_v3:
                log(f"  ✅ APK Signature Scheme V3 (most secure)")
            if has_v2:
                log(f"  ✅ APK Signature Scheme V2")
            
            # Get certificate from V3 or V2 (prefer V3)
            sig_data = v3_block.value if has_v3 else v2_block.value
            
            if hasattr(sig_data, 'signers') and sig_data.signers:
                signer = sig_data.signers[0]
                
                # Get public key fingerprint
                if hasattr(signer, 'public_key') and signer.public_key:
                    pk_data = signer.public_key.data if hasattr(signer.public_key, 'data') else signer.public_key
                    pk_sha256 = hashlib.sha256(pk_data).hexdigest()
                    
                    log(f"  🔑 Public Key SHA-256: {pk_sha256}")
                    
                    # Get certificate details
                    if hasattr(signer, 'signed_data') and hasattr(signer.signed_data, 'certificates'):
                        certificates = signer.signed_data.certificates
                        if certificates:
                            cert = certificates[0]
                            cert_data = cert.data if hasattr(cert, 'data') else cert
                            
                            # Parse certificate to get organization
                            try:
                                # Import StringIO to capture output
                                from io import StringIO
                                import sys
                                
                                # Capture the output from show_x509_certificate
                                old_stdout = sys.stdout
                                sys.stdout = captured_output = StringIO()
                                
                                show_x509_certificate(cert_data, indent=0)
                                
                                sys.stdout = old_stdout
                                cert_info = captured_output.getvalue()
                                
                                # Check if cert_info contains the information
                                if cert_info:
                                    # Extract key information
                                    if "Roblox Corporation" in cert_info:
                                        log(f"  ✅ Signed by: Roblox Corporation")
                                        certificates_found.append({
                                            'file': apk_file,
                                            'organization': 'Roblox Corporation',
                                            'pk_sha256': pk_sha256
                                        })
                                        
                                        # Show Common Name if available
                                        for line in cert_info.split('\n'):
                                            if 'Common Name:' in line:
                                                log(f"  📝 {line.strip()}")
                                                break
                                    else:
                                        log(f"  ⚠️  Unknown signer (not Roblox Corporation)")
                                        # Extract organization name from cert_info
                                        for line in cert_info.split('\n'):
                                            if 'Organization:' in line:
                                                log(f"  {line.strip()}")
                                        all_verified = False
                                else:
                                    log(f"  ⚠️  Certificate info could not be retrieved")
                                    all_verified = False
                                        
                            except Exception as e:
                                log(f"  ⚠️  Could not parse certificate: {e}")
                                # Restore stdout if there was an error
                                if 'old_stdout' in locals():
                                    sys.stdout = old_stdout
                                all_verified = False
        
        except Exception as e:
            log(f"  ❌ Error verifying signature: {e}")
            all_verified = False
    
    # Summary
    log("\n" + "="*70)
    if certificates_found:
        roblox_count = sum(1 for c in certificates_found if c['organization'] == 'Roblox Corporation')
        log(f"📊 Verification Summary:")
        log(f"   Total APKs verified: {len(certificates_found)}")
        log(f"   Signed by Roblox Corporation: {roblox_count}")
        
        if roblox_count == len(certificates_found):
            log(f"   ✅ ALL APKs are authentically signed by Roblox Corporation")
        else:
            log(f"   ⚠️  WARNING: Some APKs are not signed by Roblox Corporation!")
            all_verified = False
    else:
        log("⚠️  No signatures could be verified")
        all_verified = False
    
    log("="*70)
    
    return all_verified

def main():
    parser = argparse.ArgumentParser(
        description="Download Roblox APK from APKCombo using Playwright",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Check version only (no download)
    python download_roblox.py --check-only
    
    # Download only if new version available
    python download_roblox.py
    
    # Download and extract
    python download_roblox.py --extract
    
    # Force download even if version is the same
    python download_roblox.py --force --extract
    
    # Custom output directory
    python download_roblox.py --output-dir ./downloads
        """
    )
    
    parser.add_argument(
        "--output-dir",
        default=os.path.expanduser("~/Downloads"),
        help="Directory to save the downloaded file (default: ~/Downloads)"
    )
    parser.add_argument(
        "--url",
        default="https://apkcombo.com/downloader/#package=com.roblox.client&arches=x86_64",
        help="APKCombo URL to download from"
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract and process the downloaded XAPK file"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force download even if the same version already exists locally"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check version without downloading"
    )
    
    args = parser.parse_args()
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Check current online version (with debug file saving)
    current_version = get_current_version(args.url, output_dir=args.output_dir)
    
    if not current_version:
        log("Warning: Could not determine current version")
        log(f"Check {args.output_dir} for debug files (screenshots, HTML)")
    
    # Check local version
    local_version = read_local_version(args.output_dir)
    
    # Compare versions
    if current_version and local_version:
        comparison = compare_versions(current_version, local_version)
        if comparison > 0:
            log(f"✨ New version available: {current_version} (you have: {local_version})")
        elif comparison < 0:
            log(f"ℹ️  Local version {local_version} is newer than online {current_version}")
            if not args.force:
                log("Skipping download. Use --force to download anyway.")
                return 0
        else:
            log(f"✅ You already have the latest version: {local_version}")
            if not args.force:
                log("Skipping download. Use --force to download anyway.")
                return 0
    elif local_version:
        log(f"Local version: {local_version}")
    
    # If check-only mode, exit here
    if args.check_only:
        if current_version:
            log(f"\nCurrent available version: {current_version}")
        return 0
    
    # Download the file
    log("\nProceeding with download...")
    downloaded_file = download_with_playwright(args.url, args.output_dir)
    
    if not downloaded_file:
        log("Failed to download file")
        return 1
    
    log(f"\n✅ Download completed: {downloaded_file}")
    
    # Extract and process if requested
    if args.extract:
        log("\nExtracting and processing XAPK file...")
        
        # Extract version from filename
        filename = os.path.basename(downloaded_file)
        version_match = re.search(r"(\d+\.\d+\.\d+)", filename)
        version = version_match.group(1) if version_match else "unknown"
        
        # Create extraction directory
        extract_dir = os.path.join(args.output_dir, f"roblox_{version}_extracted")
        os.makedirs(extract_dir, exist_ok=True)
        
        # Extract XAPK
        if not extract_xapk(downloaded_file, extract_dir):
            return 1
        
        # Process contents
        if not process_apkcombo_contents(extract_dir, version):
            return 1
        
        # Create manifest
        if not create_manifest(extract_dir, version):
            return 1
        
        # Verify APK signatures
        verify_apk_signatures(extract_dir)
        
        log(f"\n✅ Successfully extracted and processed to: {extract_dir}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

