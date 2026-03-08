"""
OCR后处理器 - 优化识别结果
- 代码格式化
- 常见OCR错误修复
- 语言检测
"""

import re
from typing import Dict


class PostProcessor:
    """OCR结果后处理器"""
    
    # 常见代码OCR错误映射
    CODE_CORRECTIONS = {
        # 数字与字母混淆
        'O': '0',  # 大写O -> 数字0 (在代码语境中)
        'l': '1',  # 小写l -> 数字1
        'I': 'l',  # 大写I -> 小写l (在变量名中)
        'S': '5',  # S -> 5
        'B': '8',  # B -> 8
        # 符号混淆
        '‘': "'",  # 中文单引号 -> 英文单引号
        '’': "'",
        '"': '"',  # 中文双引号 -> 英文双引号
        '"': '"',
        '，': ',',  # 中文逗号 -> 英文逗号
        '。': '.',  # 中文句号 -> 英文句号
        '；': ';',  # 中文分号 -> 英文分号
        '：': ':',  # 中文冒号 -> 英文冒号
        '（': '(',  # 中文括号 -> 英文括号
        '）': ')',
        '【': '[',
        '】': ']',
        '｛': '{',
        '｝': '}',
    }
    
    # 代码特征关键词
    CODE_KEYWORDS = [
        'def ', 'class ', 'import ', 'from ', 'return ',
        'function', 'const ', 'let ', 'var ',
        'public ', 'private ', 'void ', 'static ',
        '#include', 'int ', 'char ', 'float ',
        'print(', 'console.', 'fmt.', 'System.',
    ]
    
    def is_code_content(self, text: str) -> bool:
        """检测内容是否为代码"""
        text_lower = text.lower()
        
        # 检查代码特征
        score = 0
        for keyword in self.CODE_KEYWORDS:
            if keyword in text_lower:
                score += 1
        
        # 检查代码符号密度
        code_symbols = ['{', '}', '(', ')', ';', '=', '+', '-', '*', '/', '%']
        symbol_count = sum(text.count(s) for s in code_symbols)
        
        # 检查缩进（Python风格）
        lines = text.split('\n')
        indented_lines = sum(1 for line in lines if line.startswith('    ') or line.startswith('\t'))
        
        # 综合判断
        if score >= 2:  # 有2个以上代码关键词
            return True
        if symbol_count > len(text) * 0.02:  # 符号密度 > 2%
            return True
        if indented_lines > len(lines) * 0.3:  # 30%以上行有缩进
            return True
            
        return False
    
    def format_code(self, text: str, language: str = None) -> str:
        """
        格式化代码
        - 修复OCR错误
        - 统一缩进
        - 检测语言
        """
        # 修复常见错误
        text = self._fix_common_errors(text)
        
        # 统一缩进（Tab转4空格）
        lines = text.split('\n')
        formatted_lines = []
        for line in lines:
            # Tab转空格
            line = line.replace('\t', '    ')
            # 去除行尾空格
            line = line.rstrip()
            formatted_lines.append(line)
        
        # 去除空行（保留代码结构）
        formatted_lines = self._remove_extra_blank_lines(formatted_lines)
        
        # 检测语言
        if not language:
            language = self._detect_language('\n'.join(formatted_lines))
        
        result = '\n'.join(formatted_lines)
        
        # 如果是Python，额外检查缩进
        if language == 'python':
            result = self._fix_python_indent(result)
        
        return result
    
    def _fix_common_errors(self, text: str) -> str:
        """修复常见OCR错误"""
        # 只在代码语境中修复（需要上下文判断）
        # 这里简单处理：全局替换常见的符号错误
        for wrong, correct in self.CODE_CORRECTIONS.items():
            text = text.replace(wrong, correct)
        
        return text
    
    def _remove_extra_blank_lines(self, lines: list) -> list:
        """去除多余的空行（保留最多1个连续空行）"""
        result = []
        prev_blank = False
        
        for line in lines:
            is_blank = not line.strip()
            if is_blank and prev_blank:
                continue  # 跳过连续空行
            result.append(line)
            prev_blank = is_blank
        
        return result
    
    def _detect_language(self, text: str) -> str:
        """检测代码语言"""
        text_lower = text.lower()
        
        # Python
        if any(kw in text_lower for kw in ['def ', 'import ', 'from ', 'print(', 'self.', '__init__']):
            return 'python'
        
        # JavaScript/TypeScript
        if any(kw in text_lower for kw in ['const ', 'let ', 'var ', 'function ', 'console.', '=>']):
            return 'javascript'
        
        # Java
        if any(kw in text_lower for kw in ['public class', 'private ', 'system.out', 'void ']):
            return 'java'
        
        # C/C++
        if any(kw in text_lower for kw in ['#include', 'int main', 'printf(', 'std::']):
            return 'cpp'
        
        # Go
        if any(kw in text_lower for kw in ['package ', 'func ', 'import (', 'fmt.']):
            return 'go'
        
        return 'text'
    
    def _fix_python_indent(self, text: str) -> str:
        """修复Python缩进问题"""
        lines = text.split('\n')
        fixed_lines = []
        expected_indent = 0
        
        for line in lines:
            stripped = line.lstrip()
            if not stripped:
                fixed_lines.append(line)
                continue
            
            # 检测缩进减少（如 return, break, pass 等）
            if stripped.startswith(('return', 'break', 'continue', 'pass', 'raise')):
                expected_indent = max(0, expected_indent - 4)
            
            # 检测缩进增加（如 def, class, if, for 等）
            if stripped.endswith(':') and not stripped.startswith('#'):
                current_indent = len(line) - len(stripped)
                fixed_line = ' ' * current_indent + stripped
                fixed_lines.append(fixed_line)
                expected_indent = current_indent + 4
            else:
                fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)


def format_ocr_result(result: Dict) -> str:
    """便捷函数：格式化OCR结果"""
    processor = PostProcessor()
    text = result.get('text', '')
    
    if processor.is_code_content(text):
        formatted = processor.format_code(text)
        lang = processor._detect_language(text)
        return f"```\n{formatted}\n```\n\n*检测到 {lang} 代码*"
    
    return text
