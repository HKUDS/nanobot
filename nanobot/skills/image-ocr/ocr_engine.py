"""
OCR引擎封装 - 支持多种OCR后端
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Union


class OCREngine:
    """OCR引擎管理器"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config = self._load_config(config_path)
        self._paddle_engine = None
        self._baidu_token = None
        
    def _load_config(self, config_path: Optional[Path]) -> Dict:
        """加载配置文件"""
        default_config = {
            'ocr_engine': 'paddle',
            'language': 'ch_sim',
            'save_temp': False,
            'baidu_api_key': '',
            'baidu_secret_key': '',
        }
        
        if config_path and config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                user_config = json.load(f)
                default_config.update(user_config)
        
        return default_config
    
    def recognize(self, image_path: Union[str, Path], 
                  engine_type: Optional[str] = None) -> Dict:
        """
        识别图片中的文字
        
        Returns:
            {
                'text': '完整文字',
                'blocks': [{'text': '块1', 'confidence': 0.98, 'position': [...]}, ...],
                'engine': 'paddle',
                'confidence': 0.95,
            }
        """
        engine = engine_type or self.config['ocr_engine']
        
        if engine == 'paddle':
            return self._recognize_paddle(image_path)
        elif engine == 'baidu':
            return self._recognize_baidu(image_path)
        elif engine == 'tencent':
            return self._recognize_tencent(image_path)
        else:
            raise ValueError(f"不支持的OCR引擎: {engine}")
    
    def _recognize_paddle(self, image_path: Union[str, Path]) -> Dict:
        """使用PaddleOCR识别"""
        try:
            from paddleocr import PaddleOCR
        except ImportError:
            raise RuntimeError(
                "PaddleOCR未安装，请运行: pip3 install paddleocr"
            )
        
        # 延迟初始化（第一次使用时加载模型）
        if self._paddle_engine is None:
            self._paddle_engine = PaddleOCR(
                use_angle_cls=True,
                lang=self.config['language'],
                show_log=False,
            )
        
        # 执行识别
        result = self._paddle_engine.ocr(str(image_path), cls=True)
        
        # 解析结果
        blocks = []
        all_text = []
        confidences = []
        
        if result and result[0]:
            for line in result[0]:
                if line:
                    position, (text, confidence) = line
                    blocks.append({
                        'text': text,
                        'confidence': round(confidence, 4),
                        'position': position,
                    })
                    all_text.append(text)
                    confidences.append(confidence)
        
        return {
            'text': '\n'.join(all_text),
            'blocks': blocks,
            'engine': 'paddle',
            'confidence': round(sum(confidences) / len(confidences), 4) if confidences else 0,
        }
    
    def _recognize_baidu(self, image_path: Union[str, Path]) -> Dict:
        """使用百度OCR API识别"""
        import requests
        import base64
        
        api_key = self.config.get('baidu_api_key')
        secret_key = self.config.get('baidu_secret_key')
        
        if not api_key or not secret_key:
            raise RuntimeError("百度OCR需要配置 api_key 和 secret_key")
        
        # 获取access_token
        if not self._baidu_token:
            token_url = f"https://aip.baidubce.com/oauth/2.0/token"
            response = requests.post(token_url, data={
                'grant_type': 'client_credentials',
                'client_id': api_key,
                'client_secret': secret_key,
            })
            self._baidu_token = response.json()['access_token']
        
        # 读取图片
        with open(image_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode()
        
        # 调用API
        ocr_url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/accurate_basic"
        response = requests.post(
            ocr_url,
            params={'access_token': self._baidu_token},
            data={'image': image_data},
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        
        result = response.json()
        
        if 'error_code' in result:
            raise RuntimeError(f"百度OCR错误: {result['error_msg']}")
        
        words_result = result.get('words_result', [])
        blocks = [
            {
                'text': item['words'],
                'confidence': item.get('probability', {}).get('average', 0.99),
                'position': None,
            }
            for item in words_result
        ]
        
        all_text = '\n'.join([b['text'] for b in blocks])
        avg_confidence = sum([b['confidence'] for b in blocks]) / len(blocks) if blocks else 0
        
        return {
            'text': all_text,
            'blocks': blocks,
            'engine': 'baidu',
            'confidence': round(avg_confidence, 4),
        }
    
    def _recognize_tencent(self, image_path: Union[str, Path]) -> Dict:
        """使用腾讯OCR API（待实现）"""
        raise NotImplementedError("腾讯OCR暂未实现，请使用 paddle 或 baidu")


# 便捷函数
def quick_ocr(image_path: str) -> str:
    """快速识别，只返回文字"""
    engine = OCREngine()
    result = engine.recognize(image_path)
    return result['text']
