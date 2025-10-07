#!/usr/bin/env python3
"""
AWS ECS Task for Roblox APK downloader.
This task runs the download_roblox.py script and uploads results to S3.
"""

import os
import sys
import json
import boto3
import subprocess
import tempfile
import glob
from pathlib import Path
from update_gameservers import update_gameservers

s3_client = boto3.client('s3')
ssm_client = boto3.client('ssm')

def get_ssm_parameter(name, default=None):
    """Get SSM parameter value."""
    try:
        response = ssm_client.get_parameter(Name=name)
        return response['Parameter']['Value']
    except:
        return default

def put_ssm_parameter(name, value):
    """Update SSM parameter value."""
    try:
        ssm_client.put_parameter(
            Name=name,
            Value=value,
            Type='String',
            Overwrite=True
        )
        return True
    except Exception as e:
        print(f"Error updating SSM parameter: {e}")
        return False

def upload_to_s3(local_path, bucket_name, s3_key):
    """Upload file to S3."""
    try:
        print(f"Uploading {local_path} to s3://{bucket_name}/{s3_key}")
        s3_client.upload_file(
            local_path,
            bucket_name,
            s3_key,
            ExtraArgs={
                'ServerSideEncryption': 'AES256',
                'StorageClass': 'STANDARD'
            }
        )
        print(f"Successfully uploaded to S3")
        return True
    except Exception as e:
        print(f"Error uploading to S3: {e}")
        return False

def upload_error_report_to_s3(bucket_name, error_type, error_details, debug_files=None):
    """
    Upload error report and debug files to S3 under errors/<timestamp>/.
    
    Args:
        bucket_name: S3 bucket name
        error_type: Type of error (e.g., 'version_detection', 'download_failed')
        error_details: Dict with error information
        debug_files: List of file paths to upload (screenshots, logs, etc.)
    
    Returns:
        S3 path where error was uploaded
    """
    from datetime import datetime
    import platform
    
    timestamp = datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S-UTC')
    error_prefix = f"errors/{timestamp}/"
    
    print(f"\n{'='*60}")
    print(f"UPLOADING ERROR REPORT TO S3")
    print(f"{'='*60}")
    print(f"Error type: {error_type}")
    print(f"S3 location: s3://{bucket_name}/{error_prefix}")
    
    try:
        # Create error report
        error_report = {
            'timestamp': timestamp,
            'error_type': error_type,
            'error_details': error_details,
            'environment': {
                'platform': platform.platform(),
                'python_version': platform.python_version(),
                'hostname': platform.node(),
            }
        }
        
        # Upload error report JSON
        report_key = f"{error_prefix}error_report.json"
        s3_client.put_object(
            Bucket=bucket_name,
            Key=report_key,
            Body=json.dumps(error_report, indent=2),
            ContentType='application/json',
            ServerSideEncryption='AES256'
        )
        print(f"✓ Uploaded error report: {report_key}")
        
        # Upload debug files if provided
        if debug_files:
            for file_path in debug_files:
                if os.path.exists(file_path):
                    filename = os.path.basename(file_path)
                    file_key = f"{error_prefix}{filename}"
                    
                    # Determine content type
                    content_type = 'application/octet-stream'
                    if filename.endswith('.png'):
                        content_type = 'image/png'
                    elif filename.endswith('.html'):
                        content_type = 'text/html'
                    elif filename.endswith('.txt') or filename.endswith('.log'):
                        content_type = 'text/plain'
                    
                    with open(file_path, 'rb') as f:
                        s3_client.put_object(
                            Bucket=bucket_name,
                            Key=file_key,
                            Body=f.read(),
                            ContentType=content_type,
                            ServerSideEncryption='AES256'
                        )
                    print(f"✓ Uploaded debug file: {file_key}")
                else:
                    print(f"⚠️  Debug file not found: {file_path}")
        
        print(f"{'='*60}")
        print(f"Error report uploaded successfully")
        print(f"View at: s3://{bucket_name}/{error_prefix}")
        print(f"{'='*60}\n")
        
        return f"s3://{bucket_name}/{error_prefix}"
        
    except Exception as e:
        print(f"❌ Error uploading error report: {e}")
        return None

def validate_roblox_version(version):
    """
    Validate that the version is in the correct Roblox format: 2.xxx.xxx
    Returns True if valid, False otherwise.
    """
    if not version:
        return False
    
    parts = version.split('.')
    if len(parts) != 3:
        return False
    
    # First part must be "2"
    if parts[0] != '2':
        return False
    
    # All parts should be numeric
    try:
        for part in parts:
            int(part)
        return True
    except ValueError:
        return False

def get_current_version_from_apkcombo(bucket_name=None):
    """
    Get the current Roblox version from APKCombo.
    Validates format and retries if invalid.
    
    Args:
        bucket_name: Optional S3 bucket name for error reporting
    
    Returns:
        Version string or None if failed
    """
    max_attempts = 3
    retry_delay = 180  # 3 minutes
    all_stdout = []
    all_stderr = []
    
    for attempt in range(max_attempts):
        try:
            if attempt > 0:
                print(f"Waiting {retry_delay} seconds before retry {attempt + 1}/{max_attempts}...")
                import time
                time.sleep(retry_delay)
            
            print(f"Checking current Roblox version on APKCombo (attempt {attempt + 1}/{max_attempts})...")
            
            # Run with screenshot on error
            result = subprocess.run(
                ['python', '/app/download_roblox.py', '--check-only', '--output-dir', '/tmp/version_check'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            all_stdout.append(f"=== Attempt {attempt + 1} stdout ===\n{result.stdout}")
            all_stderr.append(f"=== Attempt {attempt + 1} stderr ===\n{result.stderr}")
            
            # Parse version from output
            for line in result.stdout.split('\n'):
                if 'Found version from page:' in line:
                    version = line.split('Found version from page:')[1].strip()
                    print(f"Detected version: {version}")
                    
                    # Validate version format
                    if validate_roblox_version(version):
                        print(f"✓ Version format is valid (2.xxx.xxx): {version}")
                        return version
                    else:
                        print(f"✗ Invalid version format: {version} (expected 2.xxx.xxx)")
                        if attempt < max_attempts - 1:
                            print(f"Will retry after {retry_delay} seconds...")
                            continue
                        else:
                            print(f"Failed to get valid version after {max_attempts} attempts")
                            # Upload error report on final failure
                            if bucket_name:
                                upload_error_report_to_s3(
                                    bucket_name=bucket_name,
                                    error_type='invalid_version_format',
                                    error_details={
                                        'detected_version': version,
                                        'expected_format': '2.xxx.xxx',
                                        'attempts': max_attempts,
                                        'stdout': '\n\n'.join(all_stdout),
                                        'stderr': '\n\n'.join(all_stderr),
                                        'return_code': result.returncode
                                    },
                                    debug_files=_find_debug_files('/tmp/version_check')
                                )
                            return None
            
            print(f"Could not parse version from APKCombo output")
            
        except subprocess.TimeoutExpired as e:
            print(f"Timeout checking version (attempt {attempt + 1}): {e}")
            all_stdout.append(f"=== Attempt {attempt + 1} timeout ===\n{e.stdout if e.stdout else 'No stdout'}")
            all_stderr.append(f"=== Attempt {attempt + 1} timeout ===\n{e.stderr if e.stderr else 'No stderr'}")
        except Exception as e:
            print(f"Error checking version (attempt {attempt + 1}): {e}")
            all_stderr.append(f"=== Attempt {attempt + 1} exception ===\n{str(e)}")
    
    # All attempts failed - upload error report
    if bucket_name:
        upload_error_report_to_s3(
            bucket_name=bucket_name,
            error_type='version_detection_failed',
            error_details={
                'error': 'Could not detect version after all attempts',
                'attempts': max_attempts,
                'stdout': '\n\n'.join(all_stdout),
                'stderr': '\n\n'.join(all_stderr)
            },
            debug_files=_find_debug_files('/tmp/version_check')
        )
    
    return None

def _find_debug_files(directory):
    """Find all debug files (screenshots, HTML, logs) in a directory."""
    debug_files = []
    if os.path.exists(directory):
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(('.png', '.html', '.log', '.txt')):
                    debug_files.append(os.path.join(root, file))
    return debug_files

def version_exists_in_s3(bucket_name, s3_prefix, version):
    """Check if a specific version already exists in S3."""
    try:
        # Check if the version directory exists and has files
        version_prefix = f"{s3_prefix}{version}/"
        print(f"Checking if version {version} exists in S3: s3://{bucket_name}/{version_prefix}")
        
        response = s3_client.list_objects_v2(
            Bucket=bucket_name,
            Prefix=version_prefix,
            MaxKeys=1
        )
        
        exists = response.get('KeyCount', 0) > 0
        if exists:
            print(f"✓ Version {version} already exists in S3")
        else:
            print(f"✗ Version {version} not found in S3")
        
        return exists
    except Exception as e:
        print(f"Error checking S3: {e}")
        return False

def main():
    """
    ECS Task for Roblox downloader.
    Reads configuration from environment variables.
    """
    # Get action from environment variable (default: download)
    action = os.environ.get('ACTION', 'download')
    extract = os.environ.get('EXTRACT', 'true').lower() == 'true'
    force = os.environ.get('FORCE', 'false').lower() == 'true'
    update_games = os.environ.get('UPDATE_GAMESERVERS', 'true').lower() == 'true'    
    print(f"Starting Roblox downloader task...")
    print(f"Action: {action}, Extract: {extract}, Force: {force}")
    
    # Get configuration from environment
    stage = os.environ.get('STAGE', 'dev')
    bucket_name = os.environ.get('BUCKET_NAME')
    s3_prefix = os.environ.get('S3_PREFIX', 'apk/')
    
    # Define SSM parameter path for version tracking
    version_param = f"/guardiangamer/{stage}/roblox/current-version"
    
    if not bucket_name:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'BUCKET_NAME not configured'})
        }
    
    # Create temporary directory for downloads
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Using temporary directory: {temp_dir}")
        
        # Build command
        cmd = [
            'python',
            '/app/download_roblox.py',
            '--output-dir', temp_dir
        ]
        
        if action == 'check':
            cmd.append('--check-only')
        else:
            if extract:
                cmd.append('--extract')
            if force:
                cmd.append('--force')
        
        # Get current version from APKCombo (with error reporting)
        current_apkcombo_version = get_current_version_from_apkcombo(bucket_name=bucket_name)
        
        if not current_apkcombo_version:
            print("⚠️  Could not determine valid version from APKCombo")
            print("⚠️  Skipping APK download but will proceed with gameservers update")
            
            result = {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'APK version detection failed, skipped download',
                    'apk_skipped': True
                })
            }
            
            # Still update gameservers even though APK failed
            if update_games and action in ['all', 'gameservers']:
                print("\n" + "=" * 60)
                print("UPDATING GAMESERVERS (APK detection failed)")
                print("=" * 60)
                
                gameservers_result = update_gameservers(
                    bucket_name=bucket_name,
                    s3_prefix=""  # Store in root of bucket under gameservers/
                )
                
                # Merge results
                result_body = json.loads(result['body'])
                gameservers_body = json.loads(gameservers_result['body'])
                result_body['gameservers'] = gameservers_body
                result['body'] = json.dumps(result_body)
            
            return result
        
        # Check if this version already exists in S3
        if version_exists_in_s3(bucket_name, s3_prefix, current_apkcombo_version) and not force:
            print(f"Version {current_apkcombo_version} already exists in S3. Skipping download.")
            
            # Update SSM parameter with current version
            put_ssm_parameter(version_param, current_apkcombo_version)
            
            result = {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'Version already exists in S3',
                    'version': current_apkcombo_version,
                    'skipped': True
                })
            }
            
            # Update gameservers even if APK was skipped
            if update_games and action in ['all', 'gameservers']:
                print("\n" + "=" * 60)
                print("UPDATING GAMESERVERS (APK skipped but updating games)")
                print("=" * 60)
                
                gameservers_result = update_gameservers(
                    bucket_name=bucket_name,
                    s3_prefix=""  # Store in root of bucket under gameservers/
                )
                
                # Merge results
                result_body = json.loads(result['body'])
                gameservers_body = json.loads(gameservers_result['body'])
                result_body['gameservers'] = gameservers_body
                result['body'] = json.dumps(result_body)
            
            return result
        
        print(f"Proceeding with download of version {current_apkcombo_version}")
        
        # Run the downloader
        try:
            print(f"Running command: {' '.join(cmd)}")
            print("=" * 60)
            # Capture output for error reporting
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=850  # Lambda timeout is 900s
            )
            print(result.stdout)
            print("=" * 60)
            
            if result.returncode != 0:
                print(f"❌ Download failed with return code {result.returncode}")
                
                # Upload error report with debug files
                error_report_path = upload_error_report_to_s3(
                    bucket_name=bucket_name,
                    error_type='download_failed',
                    error_details={
                        'version': current_apkcombo_version,
                        'return_code': result.returncode,
                        'command': ' '.join(cmd),
                        'stdout': result.stdout,
                        'stderr': result.stderr
                    },
                    debug_files=_find_debug_files(output_dir)
                )
                
                return {
                    'statusCode': 500,
                    'body': json.dumps({
                        'error': 'Download failed',
                        'returncode': result.returncode,
                        'error_report': error_report_path
                    })
                }
            
        except subprocess.TimeoutExpired as e:
            print(f"❌ Download timed out after {e.timeout} seconds")
            
            # Upload error report for timeout
            upload_error_report_to_s3(
                bucket_name=bucket_name,
                error_type='download_timeout',
                error_details={
                    'version': current_apkcombo_version,
                    'timeout_seconds': e.timeout,
                    'command': ' '.join(cmd),
                    'stdout': e.stdout if e.stdout else 'No stdout',
                    'stderr': e.stderr if e.stderr else 'No stderr'
                },
                debug_files=_find_debug_files(output_dir)
            )
            
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Download timed out'})
            }
        except Exception as e:
            print(f"❌ Unexpected error during download: {e}")
            
            # Upload error report for unexpected errors
            upload_error_report_to_s3(
                bucket_name=bucket_name,
                error_type='download_exception',
                error_details={
                    'version': current_apkcombo_version,
                    'exception': str(e),
                    'exception_type': type(e).__name__,
                    'command': ' '.join(cmd)
                },
                debug_files=_find_debug_files(output_dir)
            )
            
            return {
                'statusCode': 500,
                'body': json.dumps({'error': str(e)})
            }
        
        # If check-only mode, we're done
        if action == 'check':
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'action': 'check',
                    'current_version': current_version,
                    'output': result.stdout
                })
            }
        
        # Find downloaded XAPK file
        xapk_files = glob.glob(os.path.join(temp_dir, "Roblox_*_apkcombo.com.xapk"))
        
        if not xapk_files:
            print("No XAPK file found - assuming no new version available")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'message': 'No new version available',
                    'current_version': current_version
                })
            }
        
        # Get the most recent file
        xapk_file = max(xapk_files, key=os.path.getmtime)
        filename = os.path.basename(xapk_file)
        print(f"Found XAPK file: {filename}")
        
        # Extract version from filename
        import re
        version_match = re.search(r'Roblox[_-](\d+\.\d+\.\d+)', filename)
        new_version = version_match.group(1) if version_match else "unknown"
        print(f"Detected version: {new_version}")
        
        # Upload XAPK file to S3 organized by version: /apk/{version}/filename.xapk
        s3_key = f"{s3_prefix}{new_version}/{filename}"
        if not upload_to_s3(xapk_file, bucket_name, s3_key):
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to upload XAPK to S3'})
            }
        
        uploaded_files = [s3_key]
        
        # If extracted, upload the extracted files to /apk/{version}/extracted/
        if extract:
            extracted_dir = os.path.join(temp_dir, f"roblox_{new_version}_extracted")
            if os.path.exists(extracted_dir):
                print(f"Uploading extracted files from {extracted_dir}")
                
                for root, dirs, files in os.walk(extracted_dir):
                    for file in files:
                        local_file = os.path.join(root, file)
                        relative_path = os.path.relpath(local_file, extracted_dir)
                        # Upload to /apk/{version}/extracted/...
                        s3_extracted_key = f"{s3_prefix}{new_version}/extracted/{relative_path}"
                        
                        if upload_to_s3(local_file, bucket_name, s3_extracted_key):
                            uploaded_files.append(s3_extracted_key)
        
        # Update SSM parameter with new version
        if new_version != "unknown":
            put_ssm_parameter(version_param, new_version)
        
        result = {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Download successful',
                'version': new_version,
                'previous_version': current_version,
                'bucket': bucket_name,
                'uploaded_files': uploaded_files,
                's3_url': f"s3://{bucket_name}/{s3_key}"
            })
        }
        
        # Update gameservers if requested
        if update_games and action in ['all', 'gameservers']:
            print("\n" + "=" * 60)
            print("UPDATING GAMESERVERS")
            print("=" * 60)
            
            gameservers_result = update_gameservers(
                bucket_name=bucket_name,
                s3_prefix=""  # Store in root of bucket under gameservers/
            )
            
            # Merge results
            result_body = json.loads(result['body'])
            gameservers_body = json.loads(gameservers_result['body'])
            result_body['gameservers'] = gameservers_body
            result['body'] = json.dumps(result_body)
        
        return result

if __name__ == "__main__":
    try:
        result = main()
        print(json.dumps(result, indent=2))
        sys.exit(0 if result.get('statusCode') == 200 else 1)
    except Exception as e:
        print(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
