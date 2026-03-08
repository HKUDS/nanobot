#!/usr/bin/env python3
"""
Download file from Feishu cloud drive
Usage: python3 download_feishu_pdf.py <file_token> [output_path]
"""
import os
import sys
import re
import requests

def load_env_file(path):
    """Load env file with KEY = "value" or KEY=value format"""
    if not os.path.exists(path):
        return
    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = re.match(r'^(\w+)\s*=\s*["\']?(.+?)["\']?\s*$', line)
            if match:
                os.environ[match.group(1)] = match.group(2)

def get_tenant_token(app_id, app_secret):
    """Get Feishu tenant access token"""
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=30)
    data = resp.json()
    if data.get("code") != 0:
        raise Exception(f"Failed to get token: {data}")
    return data["tenant_access_token"]

def download_file(file_token, output_path, tenant_token=None):
    """Download file from Feishu drive"""
    if not tenant_token:
        app_id = os.getenv("NANOBOT_CHANNELS__FEISHU__APP_ID")
        app_secret = os.getenv("NANOBOT_CHANNELS__FEISHU__APP_SECRET")
        
        if not app_id or not app_secret:
            print("Error: FEISHU_APP_ID or FEISHU_APP_SECRET not set", file=sys.stderr)
            sys.exit(1)
        
        tenant_token = get_tenant_token(app_id, app_secret)
    
    # Download file (Feishu returns file content directly)
    headers = {"Authorization": f"Bearer {tenant_token}"}
    download_url = f"https://open.feishu.cn/open-apis/drive/v1/files/{file_token}/download"
    
    resp = requests.get(download_url, headers=headers, stream=True, timeout=120)
    
    if resp.status_code != 200:
        error_msg = f"Error: Download failed with status {resp.status_code}"
        if resp.status_code == 404:
            error_msg += "\nPossible causes:\n- File token is invalid or expired\n- File has been deleted\n- App doesn't have permission to access this file (need file:read permission)"
        elif resp.status_code == 403:
            error_msg += "\nPossible causes:\n- App doesn't have permission to access this file\n- File is not shared with the app"
        print(error_msg, file=sys.stderr)
        sys.exit(1)
    
    # Save file
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    
    file_size = os.path.getsize(output_path)
    print(f"Downloaded: {output_path} ({file_size} bytes)")
    return output_path

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ('--help', '-h'):
        print("Usage: python3 download_feishu_pdf.py <file_token> [output_path]")
        print("  file_token: Feishu file token from cloud drive")
        print("  output_path: Optional output file path (default: <file_token>.pdf)")
        sys.exit(0)
    
    file_token = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else f"{file_token}.pdf"
    
    download_file(file_token, output_path)
