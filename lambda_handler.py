#!/usr/bin/env python3
"""
AWS Lambda handler for Roblox APK downloader.
This handler runs the download_roblox.py script and uploads results to S3.
"""

import os
import json
import boto3
import subprocess
import tempfile
import glob
from pathlib import Path

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

def handler(event, context):
    """
    Lambda handler for Roblox downloader.
    
    Event format:
    {
        "action": "download",  # or "check"
        "extract": true,
        "force": false
    }
    """
    print(f"Event: {json.dumps(event)}")
    
    # Get configuration from environment
    stage = os.environ.get('STAGE', 'dev')
    bucket_name = os.environ.get('BUCKET_NAME')
    s3_prefix = os.environ.get('S3_PREFIX', 'apk/')
    
    if not bucket_name:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'BUCKET_NAME not configured'})
        }
    
    # Parse event
    action = event.get('action', 'download')
    extract = event.get('extract', True)
    force = event.get('force', False)
    
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
        
        # Get current version from SSM
        version_param = f"/guardiangamer/{stage}/roblox/current-version"
        current_version = get_ssm_parameter(version_param, "0.0.0")
        print(f"Current version in SSM: {current_version}")
        
        # Run the downloader
        try:
            print(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=850  # Lambda timeout is 900s
            )
            
            print(f"STDOUT:\n{result.stdout}")
            if result.stderr:
                print(f"STDERR:\n{result.stderr}")
            
            if result.returncode != 0:
                return {
                    'statusCode': 500,
                    'body': json.dumps({
                        'error': 'Download failed',
                        'returncode': result.returncode,
                        'stderr': result.stderr
                    })
                }
            
        except subprocess.TimeoutExpired:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Download timed out'})
            }
        except Exception as e:
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
        
        # Upload XAPK file to S3
        s3_key = f"{s3_prefix}{filename}"
        if not upload_to_s3(xapk_file, bucket_name, s3_key):
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to upload XAPK to S3'})
            }
        
        uploaded_files = [s3_key]
        
        # If extracted, upload the extracted files as well
        if extract:
            extracted_dir = os.path.join(temp_dir, f"roblox_{new_version}_extracted")
            if os.path.exists(extracted_dir):
                print(f"Uploading extracted files from {extracted_dir}")
                
                for root, dirs, files in os.walk(extracted_dir):
                    for file in files:
                        local_file = os.path.join(root, file)
                        relative_path = os.path.relpath(local_file, extracted_dir)
                        s3_extracted_key = f"{s3_prefix}extracted/{new_version}/{relative_path}"
                        
                        if upload_to_s3(local_file, bucket_name, s3_extracted_key):
                            uploaded_files.append(s3_extracted_key)
        
        # Update SSM parameter with new version
        if new_version != "unknown":
            put_ssm_parameter(version_param, new_version)
        
        return {
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

# For local testing
if __name__ == "__main__":
    # Test event
    test_event = {
        "action": "download",
        "extract": True,
        "force": False
    }
    
    # Mock context
    class Context:
        function_name = "roblox-downloader-dev"
        memory_limit_in_mb = 2048
        invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:roblox-downloader-dev"
        aws_request_id = "test-request-id"
    
    result = handler(test_event, Context())
    print(json.dumps(result, indent=2))
