#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ææ¡£åå»ºå¨+æéç®¡çå¨ - åå¹¶å­æè½
å¨é£ä¹¦åå»ºææ¡£å¹¶èªå¨å®ææéç®¡ç
è¾åºï¼doc_with_permission.json
"""

import sys
import json
import urllib.parse
import time
from pathlib import Path
from datetime import datetime
import requests

# æ·»å  feishu_auth è·¯å¾
AUTH_SCRIPT_DIR = Path(__file__).parent.parent.parent.parent / "feishu-doc-creator" / "scripts"
if str(AUTH_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(AUTH_SCRIPT_DIR))


def load_config():
    """ä»ç¯å¢åéå è½½é£ä¹¦éç½®"""
    import os
    config = {
        'FEISHU_APP_ID': os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_ID', ''),
        'FEISHU_APP_SECRET': os.environ.get('NANOBOT_CHANNELS__FEISHU__APP_SECRET', ''),
        'FEISHU_API_DOMAIN': os.environ.get('FEISHU_API_DOMAIN', 'https://open.feishu.cn'),
        'FEISHU_WIKI_SPACE_ID': os.environ.get('FEISHU_WIKI_SPACE_ID', '7313882962775556100'),
        'FEISHU_WIKI_PARENT_NODE': os.environ.get('FEISHU_WIKI_PARENT_NODE', 'Uqsqwoug5iYca3koiAQcUaEqnOf'),
        'FEISHU_AUTO_COLLABORATOR_ID': os.environ.get('FEISHU_AUTO_COLLABORATOR_ID', ''),
        'FEISHU_AUTO_COLLABORATOR_TYPE': os.environ.get('FEISHU_AUTO_COLLABORATOR_TYPE', 'openid'),
        'FEISHU_AUTO_COLLABORATOR_PERM': os.environ.get('FEISHU_AUTO_COLLABORATOR_PERM', 'full_access'),
    }
    if not config['FEISHU_APP_ID'] or not config['FEISHU_APP_SECRET']:
        raise Exception("ç¼ºå°é£ä¹¦å­æ®ï¼è¯·è®¾ç½®ç¯å¢åé NANOBOT_CHANNELS__FEISHU__APP_ID / NANOBOT_CHANNELS__FEISHU__APP_SECRET")
    return config


def get_access_token(config, use_user_token=False):
    """è·åè®¿é®ä»¤ç"""
    if use_user_token:
        # ä»æä»¶è¯»å user_access_token
        token_path = Path(__file__).parent.parent.parent.parent / "feishu-token.json"
        if token_path.exists():
            with open(token_path, 'r', encoding='utf-8') as f:
                token_data = json.load(f)
                # æ¯æ access_token å user_access_token ä¸¤ç§æ ¼å¼
                return token_data.get("user_access_token") or token_data.get("access_token")
        return None
    else:
        # è·å tenant_access_token
        url = f"{config['FEISHU_API_DOMAIN']}/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json"}
        payload = {
            "app_id": config['FEISHU_APP_ID'],
            "app_secret": config['FEISHU_APP_SECRET']
        }
        response = requests.post(url, json=payload, headers=headers)
        result = response.json()
        if result.get("code") == 0:
            return result["tenant_access_token"]
        else:
            raise Exception(f"è·å tenant_access_token å¤±è´¥: {result}")


def create_document(token, config, title):
    """åå»ºé£ä¹¦ç¥è¯åºææ¡£ - ä½¿ç¨ wiki API å¨ç¥è¯åºä¸­åå»º"""
    # è·åç¥è¯åºéç½®ï¼é»è®¤ç©ºé´IDåç¶èç¹tokenï¼
    space_id = config.get('FEISHU_WIKI_SPACE_ID', '7313882962775556100')
    parent_node_token = config.get('FEISHU_WIKI_PARENT_NODE', 'Uqsqwoug5iYca3koiAQcUaEqnOf')
    
    # ä½¿ç¨ wiki API å¨ç¥è¯åºåå»ºææ¡£
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/wiki/v2/spaces/{space_id}/nodes"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "title": title,
        "parent_node_token": parent_node_token,
        "obj_type": "docx",
        "node_type": "origin"
    }

    response = requests.post(url, json=payload, headers=headers)
    
    # è°è¯ï¼æå°åå§ååº
    print(f"     ååºç¶æ: {response.status_code}")
    
    try:
        result = response.json()
    except json.JSONDecodeError as e:
        raise Exception(f"JSONè§£æå¤±è´¥: {e}, åå§ååº: {response.text[:500]}")

    if result.get("code") == 0:
        doc_id = result["data"]["node"]["obj_token"]
        node_token = result["data"]["node"]["node_token"]
        print(f"     ææ¡£ID: {doc_id}")
        print(f"     èç¹Token: {node_token}")
        return doc_id, node_token
    else:
        raise Exception(f"åå»ºç¥è¯åºææ¡£å¤±è´¥: {result}")


def add_permission_member(token, config, document_id, user_id, user_type, perm):
    """æ·»å åä½èæé - å¿é¡»ä½¿ç¨ tenant_access_token"""
    params = urllib.parse.urlencode({"type": "docx"})
    url = f"{config['FEISHU_API_DOMAIN']}/open-apis/drive/v1/permissions/{document_id}/members?{params}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "member_id": user_id,
        "member_type": user_type,
        "perm": perm
    }

    response = requests.post(url, json=payload, headers=headers)
    result = response.json()

    if result.get("code") == 0:
        return result
    else:
        raise Exception(f"æ·»å æéæåå¤±è´¥: {result}")


def main():
    """ä¸»å½æ° - å½ä»¤è¡å¥å£"""
    # è§£æåæ°
    title = "æªå½åææ¡£"
    output_dir = Path("output")

    if len(sys.argv) >= 2:
        title = sys.argv[1]

    if len(sys.argv) >= 3:
        output_dir = Path(sys.argv[2])

    output_dir.mkdir(parents=True, exist_ok=True)

    # å è½½éç½®
    config = load_config()
    if not config:
        print("[feishu-doc-creator-with-permission] Error: Unable to load config")
        sys.exit(1)

    print("=" * 70)
    print("ç¥è¯åºææ¡£åå»º + æéç®¡çï¼åå­æä½ï¼")
    print("=" * 70)
    print(f"ææ¡£æ é¢: {title}")
    print(f"åå»ºä½ç½®: ç¥è¯åº")
    print()

    # æééç½®
    collaborator_id = config.get('FEISHU_AUTO_COLLABORATOR_ID')
    collaborator_type = config.get('FEISHU_AUTO_COLLABORATOR_TYPE', 'openid')
    collaborator_perm = config.get('FEISHU_AUTO_COLLABORATOR_PERM', 'full_access')

    # ç»ææ°æ®
    result = {
        "title": title,
        "created_at": datetime.now().isoformat(),
        "permission": {
            "collaborator_added": False,
            "user_has_full_control": False,
            "collaborator_id": collaborator_id
        },
        "errors": []
    }

    # ========== ç¬¬ä¸æ­¥ï¼åå»ºææ¡£ ==========
    print("[æ­¥éª¤ 1/2] åå»ºææ¡£ (tenant_access_token)...")
    try:
        token = get_access_token(config, use_user_token=False)
        doc_id, node_token = create_document(token, config, title)
        result["document_id"] = doc_id
        result["node_token"] = node_token
        result["document_url"] = f"{config.get('FEISHU_WEB_DOMAIN', 'https://feishu.cn')}/docx/{doc_id}"
        print(f"[OK] ç¥è¯åºææ¡£åå»ºæå")
        print(f"     ææ¡£ID: {doc_id}")
    except Exception as e:
        error_msg = str(e)
        result["errors"].append(f"åå»ºææ¡£å¤±è´¥: {error_msg}")
        print(f"[FAIL] åå»ºææ¡£å¤±è´¥: {error_msg}")
        # ä¿å­å¤±è´¥ç»æå¹¶éåº
        result_file = output_dir / "doc_with_permission.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        sys.exit(1)

    # ========== ç¬¬äºæ­¥ï¼æ·»å åä½èæé ==========
    # æ³¨ï¼ç±äºäºç/ç¥è¯åºè·¯å¾éç½®ï¼åå»ºèèªå¨æ¥æç®¡çæéï¼æ éæææè½¬ç§»
    print("\n[æ­¥éª¤ 2/2] æ·»å åä½èæé (tenant_access_token)...")
    if collaborator_id:
        try:
            add_permission_member(token, config, doc_id, collaborator_id, collaborator_type, collaborator_perm)
            result["permission"]["collaborator_added"] = True
            result["permission"]["user_has_full_control"] = True
            print(f"[OK] åä½èæéæ·»å æå")
            print(f"     åä½èID: {collaborator_id}")
            print(f"[INFO] ç¨æ·å·²è·å¾å®å¨æ§å¶æï¼å¯ç¼è¾+å¯å é¤ï¼")
        except Exception as e:
            error_msg = str(e)
            result["errors"].append(f"æ·»å åä½èå¤±è´¥: {error_msg}")
            print(f"[FAIL] æ·»å åä½èå¤±è´¥: {error_msg}")
            print("[WARN] ç¨æ·å¯è½æ æ³ç¼è¾ææ¡£")
    else:
        print("[SKIP] æªéç½®åä½è IDï¼è·³è¿")
        result["errors"].append("æªéç½®åä½è IDï¼è·³è¿æéæ·»å ")

    # ä¿å­ç»æ
    result_file = output_dir / "doc_with_permission.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # æå°æè¦
    print()
    print("=" * 70)
    print("æä½å®æ")
    print("=" * 70)
    print(f"ææ¡£URL: {result['document_url']}")
    print(f"åä½èæ·»å : {result['permission']['collaborator_added']}")
    print(f"ç¨æ·å®å¨æ§å¶: {result['permission']['user_has_full_control']}")
    print(f"ç¨æ·å®å¨æ§å¶: {result['permission']['user_has_full_control']}")
    print(f"\nè¾åºæä»¶: {result_file}")
    print(f"\n[OUTPUT] {result_file}")


if __name__ == "__main__":
    main()
