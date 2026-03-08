#!/usr/bin/env python3
"""
高德地图导航技能 - 测试版本
用于验证高德地图API连接
"""

import requests
import json
import os

def test_amap_api():
    """测试高德地图API是否可用"""
    
    # 尝试从环境变量或配置文件获取Key
    api_key = os.environ.get('AMAP_KEY')
    
    if not api_key:
        return {
            "status": "need_config",
            "message": "高德地图API Key未配置。请运行：python3 skills/secure-key-manager/key_manager.py get -n amap-api-key"
        }
    
    # 测试地理编码API
    test_address = "杭州市西湖区"
    url = f"https://restapi.amap.com/v3/geocode/geo?address={test_address}&key={api_key}"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('status') == '1':
            return {
                "status": "success",
                "message": f"高德地图API连接正常！测试地址'{test_address}'查询成功",
                "location": data.get('geocodes', [{}])[0].get('location')
            }
        else:
            return {
                "status": "error",
                "message": f"API返回错误: {data.get('info', '未知错误')}"
            }
    except Exception as e:
        return {
            "status": "error", 
            "message": f"连接失败: {str(e)}"
        }

if __name__ == "__main__":
    result = test_amap_api()
    print(json.dumps(result, indent=2, ensure_ascii=False))
