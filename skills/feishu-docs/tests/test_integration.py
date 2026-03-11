"""
飞书云文档 - 集成测试（需要真实飞书 API 权限）
"""
import unittest
import os
import sys

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from client import FeishuClient


class TestFeishuIntegration(unittest.TestCase):
    """集成测试 - 需要真实飞书 API 权限"""
    
    @classmethod
    def setUpClass(cls):
        """检查环境变量"""
        cls.app_id = os.getenv("FEISHU_APP_ID")
        cls.app_secret = os.getenv("FEISHU_APP_SECRET")
        
        if not cls.app_id or not cls.app_secret:
            raise unittest.SkipTest("需要配置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
    
    def test_get_token(self):
        """测试获取 token"""
        client = FeishuClient(self.app_id, self.app_secret)
        token = client.get_token()
        
        self.assertIsNotNone(token)
        self.assertTrue(len(token) > 0)
        print(f"✅ Token 获取成功: {token[:20]}...")
    
    def test_list_files(self):
        """测试获取文件列表"""
        client = FeishuClient(self.app_id, self.app_secret)
        files = client.list_files(page_size=10)
        
        self.assertIsInstance(files, list)
        print(f"✅ 获取到 {len(files)} 个文件")
        
        # 打印文件列表
        for f in files[:5]:
            print(f"  - {f.get('name')} ({f.get('type')})")
    
    def test_get_file_content(self):
        """测试获取文档内容"""
        # 先获取文件列表
        client = FeishuClient(self.app_id, self.app_secret)
        files = client.list_files(page_size=20)
        
        # 找第一个文档
        doc = None
        for f in files:
            if f.get('type') == 'docx':
                doc = f
                break
        
        if not doc:
            raise unittest.SkipTest("没有找到测试文档")
        
        content = client.get_file_content(doc.get('token'))
        
        self.assertIsNotNone(content)
        print(f"✅ 获取文档内容成功: {doc.get('name')}")
        print(f"   内容长度: {len(content)} 字符")


class TestFeishuEdgeCases(unittest.TestCase):
    """边界测试 - 不需要真实 API"""
    
    @classmethod
    def setUpClass(cls):
        # 使用测试配置
        cls.app_id = "test_app_id"
        cls.app_secret = "test_app_secret"
    
    def test_invalid_credentials(self):
        """测试无效凭证"""
        from client import FeishuClient
        
        # 这个测试只验证错误处理逻辑，不实际调用 API
        client = FeishuClient("invalid_id", "invalid_secret")
        
        # 验证 client 初始化成功
        self.assertEqual(client.app_id, "invalid_id")
        self.assertEqual(client.app_secret, "invalid_secret")
    
    def test_empty_file_token(self):
        """测试空 file_token"""
        from tools import read_doc
        
        result = read_doc("")
        self.assertIn("❌", result)
        self.assertIn("file_token", result)
    
    def test_empty_keyword(self):
        """测试空搜索关键词"""
        from tools import search_docs
        
        result = search_docs("")
        self.assertIn("❌", result)
        self.assertIn("关键词", result)


if __name__ == '__main__':
    unittest.main()
