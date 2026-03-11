"""
飞书云文档工具函数 - 单元测试
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# 添加 src 目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestListDocs(unittest.TestCase):
    """测试 list_docs 函数"""
    
    @patch('tools.get_client')
    def test_list_docs_empty(self, mock_get_client):
        """测试空列表"""
        mock_client = Mock()
        mock_client.list_files.return_value = []
        mock_get_client.return_value = mock_client
        
        from tools import list_docs
        result = list_docs()
        
        self.assertEqual(result, "没有找到文档")
    
    @patch('tools.get_client')
    def test_list_docs_with_files(self, mock_get_client):
        """测试文件列表"""
        mock_client = Mock()
        mock_client.list_files.return_value = [
            {"name": "项目计划", "token": "abc123", "type": "docx"},
            {"name": "数据表格", "token": "def456", "type": "sheet"}
        ]
        mock_get_client.return_value = mock_client
        
        from tools import list_docs
        result = list_docs()
        
        self.assertIn("项目计划", result)
        self.assertIn("数据表格", result)
        self.assertIn("📄 文档", result)
        self.assertIn("📊 表格", result)


class TestReadDoc(unittest.TestCase):
    """测试 read_doc 函数"""
    
    @patch('tools.get_client')
    def test_read_doc_empty_token(self, mock_get_client):
        """测试空 token"""
        from tools import read_doc
        result = read_doc("")
        
        self.assertIn("❌ 请提供文档的 file_token", result)
    
    @patch('tools.get_client')
    def test_read_doc_success(self, mock_get_client):
        """测试读取成功"""
        mock_client = Mock()
        mock_client.get_file_content.return_value = '{"title": "测试"}'
        mock_get_client.return_value = mock_client
        
        from tools import read_doc
        result = read_doc("test_token")
        
        self.assertIn("测试", result)
    
    @patch('tools.get_client')
    def test_read_doc_error(self, mock_get_client):
        """测试读取失败"""
        mock_client = Mock()
        mock_client.get_file_content.side_effect = Exception("文档不存在")
        mock_get_client.return_value = mock_client
        
        from tools import read_doc
        result = read_doc("invalid_token")
        
        self.assertIn("❌ 读取失败", result)


class TestSearchDocs(unittest.TestCase):
    """测试 search_docs 函数"""
    
    def test_search_empty_keyword(self):
        """测试空关键词"""
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
        
        # 直接测试函数逻辑
        from tools import search_docs
        result = search_docs("")
        
        self.assertIn("❌ 请提供搜索关键词", result)
    
    @unittest.skip("需要集成测试环境")
    def test_search_no_results(self):
        """测试无搜索结果 - 需要集成测试"""
        pass
    
    @unittest.skip("需要集成测试环境")
    def test_search_with_results(self):
        """测试有搜索结果 - 需要集成测试"""
        pass


if __name__ == '__main__':
    unittest.main()
