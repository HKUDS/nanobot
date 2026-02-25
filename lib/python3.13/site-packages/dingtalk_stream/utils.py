# -*- coding:utf-8 -*-

import os

import http.client
import json

DINGTALK_OPENAPI_ENDPOINT = os.getenv(
    "DINGTALK_OPENAPI_ENDPOINT", "https://api.dingtalk.com"
)

async def http_post_json(url, data):
    """异步发送 HTTP POST 请求，携带 JSON 数据"""
    # 解析 URL
    is_https = True
    if url.startswith("http://"):
        is_https = False
        url = url[7:]  # 去掉 "http://"
    if url.startswith("https://"): url = url[8:]  # 去掉 "https://"
    host, _, path = url.partition('/')
    path = '/' + path  # 确保路径以 '/' 开头

    # 将数据转换为 JSON 字符串
    json_data = json.dumps(data)
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(json_data))
    }
    # 创建 HTTP 连接
    conn = http.client.HTTPSConnection(host) if is_https else http.client.HTTPConnection(host)
    # 发送 POST 请求
    conn.request("POST", path, body=json_data, headers=headers)
    # 获取响应
    response = conn.getresponse()
    response_data = response.read().decode('utf-8')
    # 关闭连接
    conn.close()
    return response.status, response_data