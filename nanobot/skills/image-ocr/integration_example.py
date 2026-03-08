"""
OpenClaw 集成示例 - 让 Qwen-Coder 能"看懂"图片

在你的 Agent 消息处理逻辑中添加以下内容
"""

import os
import sys
from pathlib import Path

# 假设你的 Agent 代码结构
class MyAgent:
    def __init__(self):
        # 加载 OCR Skill
        sys.path.insert(0, str(Path(__file__).parent / 'skills' / 'image-ocr'))
        from ocr_engine import OCREngine
        from post_processor import PostProcessor
        
        self.ocr = OCREngine()
        self.processor = PostProcessor()
    
    def handle_message(self, message):
        """处理收到的消息"""
        
        # 判断消息类型
        if message.type == 'text':
            # 普通文字消息，直接处理
            return self.process_text(message.content)
        
        elif message.type == 'image':
            # 图片消息！调用OCR
            return self.handle_image_message(message)
        
        elif message.type == 'file':
            # 检查是否为图片文件
            if message.file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
                return self.handle_image_message(message)
            return self.process_file(message)
    
    def handle_image_message(self, message):
        """处理图片消息 - 关键逻辑"""
        
        # 1. 下载图片（假设 message 有 download 方法）
        image_path = message.download_image()
        
        # 2. 调用OCR识别
        try:
            ocr_result = self.ocr.recognize(image_path)
            extracted_text = ocr_result['text']
            
            # 3. 检查是否为代码并格式化
            if self.processor.is_code_content(extracted_text):
                formatted_text = self.processor.format_code(extracted_text)
                context = f"用户发送了一张代码截图，内容如下:\n\n```\n{formatted_text}\n```"
            else:
                context = f"用户发送了一张图片，其中的文字内容是:\n\n{extracted_text}"
            
            # 4. 把OCR结果 + 用户原问题 一起喂给 Qwen-Coder
            # 假设用户的问题是 "帮我看看这段代码有什么问题"
            user_question = message.caption or "请分析这张图片"
            
            full_prompt = f"""{context}

用户的问题是: {user_question}

请根据图片内容和用户问题给出回答。"""
            
            # 5. 调用 Qwen-Coder（或其他纯文本模型）
            response = self.query_model('qwen-coder', full_prompt)
            
            return response
            
        except Exception as e:
            return f"图片识别失败: {e}"
    
    def query_model(self, model_name, prompt):
        """调用模型（根据你的实际实现）"""
        # 这里替换为你的模型调用逻辑
        pass


# ========== 更简单的使用方式 ==========

def simple_ocr_workflow(image_path: str, user_question: str = "") -> str:
    """
    最简单的OCR+问答流程
    
    使用示例:
    ```python
    result = simple_ocr_workflow("/path/to/code.png", "这段代码有什么问题？")
    print(result)
    ```
    """
    sys.path.insert(0, 'skills/image-ocr')
    from ocr_engine import OCREngine
    from post_processor import PostProcessor
    
    # 识别
    engine = OCREngine()
    result = engine.recognize(image_path)
    text = result['text']
    
    # 格式化
    processor = PostProcessor()
    if processor.is_code_content(text):
        text = processor.format_code(text)
    
    # 组装提示词（给模型的输入）
    if user_question:
        prompt = f"用户发了一张图片，并问：{user_question}\n\n图片中的内容是：\n\n{text}"
    else:
        prompt = f"用户发了一张图片，内容是：\n\n{text}\n\n请根据以上内容回答。"
    
    return prompt


# ========== 高级用法：批量处理 ==========

def batch_ocr(image_paths: list) -> list:
    """批量识别多张图片"""
    sys.path.insert(0, 'skills/image-ocr')
    from ocr_engine import OCREngine
    
    engine = OCREngine()
    results = []
    
    for path in image_paths:
        try:
            result = engine.recognize(path)
            results.append({
                'path': path,
                'success': True,
                'text': result['text'],
                'confidence': result['confidence'],
            })
        except Exception as e:
            results.append({
                'path': path,
                'success': False,
                'error': str(e),
            })
    
    return results
