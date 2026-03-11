"""
飞书云文档客户端 - 单元测试
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from client import FeishuClient


class TestFeishuClient(unittest.TestCase):
    """测试 FeishuClient 核心功能"""
    
    @patch('client.requests.post')
    def test_get_tenant_access_token_success(self, mock_post):
        """测试获取 token 成功"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": 0,
            "msg": "success",
            "tenant_access_token": "test_token_12345",
            "expire": 7200
        }
        mock_post.return_value = mock_response
        
        client = FeishuClient(app_id="test_id", app_secret="test_secret")
        token = client._get_tenant_access_token()
        
        self.assertEqual(token, "test_token_12345")
        mock_post.assert_called_once()
    
    @patch('client.requests.post')
    def test_get_tenant_access_token_fail(self, mock_post):
        """测试获取 token 失败"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": 999,
            "msg": "app not found"
        }
        mock_post.return_value = mock_response
        
        client = FeishuClient(app_id="invalid_id", app_secret="invalid_secret")
        
        with self.assertRaises(Exception) as context:
            client._get_tenant_access_token()
        
        self.assertIn("获取 token 失败", str(context.exception))
    
    @patch('client.requests.post')
    @patch('client.requests.get')
    def test_list_files_success(self, mock_get, mock_post):
        """测试获取文件列表成功"""
        # Mock token 获取
        mock_post_response = Mock()
        mock_post_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "test_token"
        }
        mock_post.return_value = mock_post_response
        
        # Mock 文件列表获取
        mock_get_response = Mock()
        mock_get_response.json.return_value = {
            "code": 0,
            "data": {
                "files": [
                    {"name": "测试文档", "token": "abc123", "type": "docx"},
                    {"name": "测试文件夹", "token": "def456", "type": "folder"}
                ]
            }
        }
        mock_get.return_value = mock_get_response
        
        client = FeishuClient(app_id="test_id", app_secret="test_secret")
        files = client.list_files()
        
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]["name"], "测试文档")
    
    @patch('client.requests.post')
    @patch('client.requests.get')
    def test_get_file_content(self, mock_get, mock_post):
        """测试获取文档内容"""
        # Mock token 获取
        mock_post_response = Mock()
        mock_post_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "test_token"
        }
        mock_post.return_value = mock_post_response
        
        # Mock 文档 blocks 获取
        mock_get_response = Mock()
        mock_get_response.json.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "block_type": 3,  # heading1
                        "heading1": {
                            "elements": [
                                {"text_run": {"content": "测试文档标题"}}
                            ]
                        }
                    },
                    {
                        "block_type": 2,  # paragraph
                        "paragraph": {
                            "elements": [
                                {"text_run": {"content": "这是测试内容"}}
                            ]
                        }
                    }
                ],
                "page_token": None  # 没有更多页
            }
        }
        mock_get.return_value = mock_get_response
        
        client = FeishuClient(app_id="test_id", app_secret="test_secret")
        content = client.get_file_content("test_doc_id")
        
        self.assertIn("测试文档标题", content)
        self.assertIn("测试内容", content)


class TestClientCaching(unittest.TestCase):
    """测试 token 缓存机制"""
    
    @patch('client.requests.post')
    def test_token_is_cached(self, mock_post):
        """测试 token 会被缓存，不会重复请求"""
        mock_response = Mock()
        mock_response.json.return_value = {
            "code": 0,
            "tenant_access_token": "cached_token"
        }
        mock_post.return_value = mock_response
        
        client = FeishuClient(app_id="test_id", app_secret="test_secret")
        
        # 第一次获取
        token1 = client.get_token()
        # 第二次获取
        token2 = client.get_token()
        
        self.assertEqual(token1, token2)
        # 只应该调用一次
        self.assertEqual(mock_post.call_count, 1)


if __name__ == '__main__':
    unittest.main()
