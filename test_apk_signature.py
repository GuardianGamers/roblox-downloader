#!/usr/bin/env python3
"""
APK Signature Analysis Test Script
===================================

Analyzes APK signatures using apksigtool for downloaded Roblox APKs.
Finds the latest version and prints signature information.

Usage:
    python3 test_apk_signature.py

Requirements:
    pip install apksigtool
"""

import os
import sys
import re
from pathlib import Path
from typing import List, Tuple, Optional
import zipfile
import binascii

try:
    import apksigtool
    from apksigtool import (
        extract_v2_sig,
        parse_apk_signing_block,
        parse_apk_signature_scheme_v2_block,
        parse_apk_signature_scheme_v3_block,
        show_x509_certificate,
        verify_apk_signature_scheme_v2,
        verify_apk_signature_scheme_v3,
    )
except ImportError:
    print("Error: apksigtool not installed")
    print("Install with: pip install apksigtool")
    sys.exit(1)


def parse_version(version_string: str) -> Tuple[int, ...]:
    """
    Parse version string like '2.692.843' into tuple of integers.
    
    Args:
        version_string: Version string to parse
        
    Returns:
        Tuple of version numbers
    """
    try:
        return tuple(map(int, version_string.split('.')))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def find_latest_roblox_version(downloads_dir: Path) -> Optional[Tuple[str, Path]]:
    """
    Find the latest Roblox version in the downloads directory.
    
    Args:
        downloads_dir: Path to downloads directory
        
    Returns:
        Tuple of (version_string, path_to_extracted_dir) or None
    """
    if not downloads_dir.exists():
        print(f"Error: Downloads directory not found: {downloads_dir}")
        return None
    
    # Pattern to match extracted directories: roblox_<version>_extracted
    pattern = re.compile(r'roblox_(\d+\.\d+\.\d+)_extracted')
    
    versions = []
    for item in downloads_dir.iterdir():
        if item.is_dir():
            match = pattern.match(item.name)
            if match:
                version = match.group(1)
                versions.append((version, item))
    
    if not versions:
        print("No extracted Roblox versions found")
        return None
    
    # Sort by version number and get latest
    versions.sort(key=lambda x: parse_version(x[0]), reverse=True)
    latest_version, latest_path = versions[0]
    
    print(f"Found {len(versions)} Roblox version(s)")
    print(f"Latest version: {latest_version}")
    print(f"Path: {latest_path}")
    
    return latest_version, latest_path


def analyze_apk_signature(apk_path: Path) -> None:
    """
    Analyze and print APK signature information.
    
    Args:
        apk_path: Path to APK file
    """
    print(f"\n{'='*70}")
    print(f"Analyzing: {apk_path.name}")
    print(f"{'='*70}")
    
    try:
        # Extract APK Signing Block
        print("\n[Extracting APK Signing Block...]")
        try:
            result = extract_v2_sig(str(apk_path), expected=False)
            if result is None:
                print("  No APK Signing Block found (v1 signature only or unsigned)")
                # Try to get v1 signature info from META-INF
                analyze_v1_signature(apk_path)
                return
            
            sb_offset, sig_block = result
            print(f"  Signing Block Offset: {sb_offset}")
            print(f"  Signing Block Size: {len(sig_block)} bytes")
            
        except Exception as e:
            print(f"  Error extracting signing block: {e}")
            analyze_v1_signature(apk_path)
            return
        
        # Parse APK Signing Block
        print("\n[Parsing APK Signing Block...]")
        signing_block = parse_apk_signing_block(sig_block)
        
        # Check for v2 and v3 signatures
        has_v2 = False
        has_v3 = False
        v2_block = None
        v3_block = None
        
        for pair in signing_block.pairs:
            pair_id = pair.id if hasattr(pair, 'id') else None
            
            if pair_id == apksigtool.APK_SIGNATURE_SCHEME_V2_BLOCK_ID:
                has_v2 = True
                v2_block = pair
                print(f"  ✓ Found APK Signature Scheme V2 Block")
            elif pair_id == apksigtool.APK_SIGNATURE_SCHEME_V3_BLOCK_ID:
                has_v3 = True
                v3_block = pair
                print(f"  ✓ Found APK Signature Scheme V3 Block")
        
        # Display v3 signature info with certificate details (preferred)
        if has_v3:
            print("\n[APK Signature Scheme V3]")
            print(f"  ✓ Found V3 Signature Block")
            print(f"  Block ID: 0x{v3_block.id:08x} ({v3_block.id})")
            print(f"  Block Size: {v3_block.length} bytes")
            print(f"  V3 signatures are the most secure and support key rotation")
            
            # Display signer/certificate info
            try:
                # v3_block.value is already a parsed APKSignatureSchemeBlock
                v3_data = v3_block.value
                if hasattr(v3_data, 'signers') and v3_data.signers:
                    print(f"\n  Signers: {len(v3_data.signers)}")
                    for i, signer in enumerate(v3_data.signers, 1):
                        print(f"\n  Signer #{i}:")
                        
                        # Show public key fingerprint
                        if hasattr(signer, 'public_key') and signer.public_key:
                            import hashlib
                            # public_key.data contains the actual bytes
                            pk_data = signer.public_key.data if hasattr(signer.public_key, 'data') else signer.public_key
                            pk_sha256 = hashlib.sha256(pk_data).hexdigest()
                            pk_sha1 = hashlib.sha1(pk_data).hexdigest()
                            print(f"    Public Key SHA-256: {pk_sha256}")
                            print(f"    Public Key SHA-1:   {pk_sha1}")
                        
                        # Show certificate details - they're in signed_data
                        if hasattr(signer, 'signed_data') and hasattr(signer.signed_data, 'certificates'):
                            certificates = signer.signed_data.certificates
                            if certificates:
                                print(f"\n    Certificates: {len(certificates)}")
                                for j, cert in enumerate(certificates, 1):
                                    print(f"\n    Certificate #{j}:")
                                    # cert.data contains the actual certificate bytes
                                    cert_data = cert.data if hasattr(cert, 'data') else cert
                                    cert_info = show_x509_certificate(cert_data, indent=3)
                                    print(cert_info)
            except Exception as e:
                print(f"  (Could not parse signer details: {e})")
                import traceback
                traceback.print_exc()
        
        # Display v2 signature info with certificate details
        if has_v2:
            print("\n[APK Signature Scheme V2]")
            print(f"  ✓ Found V2 Signature Block")
            print(f"  Block ID: 0x{v2_block.id:08x} ({v2_block.id})")
            print(f"  Block Size: {v2_block.length} bytes")
            print(f"  V2 signatures protect the entire APK file")
            
            # Display signer/certificate info
            try:
                # v2_block.value is already a parsed APKSignatureSchemeBlock
                v2_data = v2_block.value
                if hasattr(v2_data, 'signers') and v2_data.signers:
                    print(f"\n  Signers: {len(v2_data.signers)}")
                    for i, signer in enumerate(v2_data.signers, 1):
                        print(f"\n  Signer #{i}:")
                        
                        # Show public key fingerprint
                        if hasattr(signer, 'public_key') and signer.public_key:
                            import hashlib
                            # public_key.data contains the actual bytes
                            pk_data = signer.public_key.data if hasattr(signer.public_key, 'data') else signer.public_key
                            pk_sha256 = hashlib.sha256(pk_data).hexdigest()
                            pk_sha1 = hashlib.sha1(pk_data).hexdigest()
                            print(f"    Public Key SHA-256: {pk_sha256}")
                            print(f"    Public Key SHA-1:   {pk_sha1}")
                        
                        # Show certificate details - they're in signed_data
                        if hasattr(signer, 'signed_data') and hasattr(signer.signed_data, 'certificates'):
                            certificates = signer.signed_data.certificates
                            if certificates:
                                print(f"\n    Certificates: {len(certificates)}")
                                for j, cert in enumerate(certificates, 1):
                                    print(f"\n    Certificate #{j}:")
                                    # cert.data contains the actual certificate bytes
                                    cert_data = cert.data if hasattr(cert, 'data') else cert
                                    cert_info = show_x509_certificate(cert_data, indent=3)
                                    print(cert_info)
            except Exception as e:
                print(f"  (Could not parse signer details: {e})")
                import traceback
                traceback.print_exc()
        
        if not has_v2 and not has_v3:
            print("  No v2/v3 signatures found in signing block")
        
        # Print summary of all blocks found
        print(f"\n[All Signing Blocks Found]")
        for pair in signing_block.pairs:
            print(f"  Block ID: 0x{pair.id:08x} ({pair.id}), Length: {pair.length} bytes")
            
    except Exception as e:
        print(f"Error analyzing APK: {e}")
        import traceback
        traceback.print_exc()


def analyze_v1_signature(apk_path: Path) -> None:
    """
    Analyze v1 (JAR) signature from META-INF.
    
    Args:
        apk_path: Path to APK file
    """
    print("\n[Checking for V1 (JAR) Signature...]")
    try:
        with zipfile.ZipFile(str(apk_path), 'r') as zf:
            # Look for signature files in META-INF
            sig_files = [name for name in zf.namelist() 
                        if name.startswith('META-INF/') and 
                        (name.endswith('.RSA') or name.endswith('.DSA') or name.endswith('.EC'))]
            
            if sig_files:
                print(f"  ✓ Found V1 signature files: {', '.join(sig_files)}")
            else:
                print("  No V1 signature files found")
                print("  APK appears to be unsigned")
    except Exception as e:
        print(f"  Error checking v1 signature: {e}")


def main():
    """Main function."""
    print("APK Signature Analysis Tool")
    print("=" * 70)
    
    # Get downloads directory
    downloads_dir = Path(__file__).parent / "downloads"
    
    # Find latest version
    result = find_latest_roblox_version(downloads_dir)
    if not result:
        sys.exit(1)
    
    version, extracted_dir = result
    
    # Find all APK files in the extracted directory
    apk_files = list(extracted_dir.glob("*.apk"))
    
    if not apk_files:
        print(f"\nNo APK files found in {extracted_dir}")
        sys.exit(1)
    
    print(f"\nFound {len(apk_files)} APK file(s):")
    for apk in apk_files:
        print(f"  - {apk.name}")
    
    # Analyze each APK
    for apk_path in apk_files:
        analyze_apk_signature(apk_path)
    
    print(f"\n{'='*70}")
    print("Analysis complete!")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
