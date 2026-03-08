#!/usr/bin/env python3
"""
Image OCR Skill - CLI入口
提取图片中的文字，支持多种OCR引擎
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 添加技能目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from ocr_engine import OCREngine
from post_processor import PostProcessor


def main():
    parser = argparse.ArgumentParser(description='图片OCR识别工具')
    parser.add_argument('image_path', help='图片路径')
    parser.add_argument('--format', choices=['text', 'markdown', 'json'], 
                       default='text', help='输出格式')
    parser.add_argument('--save', action='store_true', 
                       help='保存结果到文件')
    parser.add_argument('--engine', choices=['paddle', 'baidu', 'tencent'],
                       default=None, help='指定OCR引擎')
    
    args = parser.parse_args()
    
    # 检查图片是否存在
    if not os.path.exists(args.image_path):
        print(f"❌ 图片不存在: {args.image_path}", file=sys.stderr)
        sys.exit(1)
    
    # 初始化OCR引擎
    config_path = Path(__file__).parent.parent / 'config.json'
    engine = OCREngine(config_path=config_path if config_path.exists() else None)
    
    # 执行OCR
    try:
        result = engine.recognize(args.image_path, engine_type=args.engine)
        
        # 后处理
        processor = PostProcessor()
        
        # 检测是否为代码截图并格式化
        if processor.is_code_content(result['text']):
            result['text'] = processor.format_code(result['text'])
            result['is_code'] = True
        
        # 格式化输出
        if args.format == 'json':
            output = json.dumps(result, ensure_ascii=False, indent=2)
        elif args.format == 'markdown':
            output = format_markdown(result)
        else:
            output = format_text(result)
        
        print(output)
        
        # 保存到文件
        if args.save:
            output_path = Path(args.image_path).with_suffix('.ocr.txt')
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"\n💾 已保存到: {output_path}", file=sys.stderr)
            
    except Exception as e:
        print(f"❌ OCR识别失败: {e}", file=sys.stderr)
        sys.exit(1)


def format_text(result):
    """纯文本格式输出"""
    lines = [
        "📝 图片OCR识别结果",
        "=" * 40,
        "",
        result['text'],
        "",
        f"置信度: {result.get('confidence', 'N/A')}",
        f"引擎: {result.get('engine', 'unknown')}",
    ]
    return '\n'.join(lines)


def format_markdown(result):
    """Markdown格式输出"""
    lines = [
        "## 📝 图片OCR识别结果",
        "",
    ]
    
    if result.get('is_code'):
        lines.extend([
            "### 代码内容",
            "",
            "```",
            result['text'],
            "```",
        ])
    else:
        lines.extend([
            "### 文字内容",
            "",
            result['text'],
        ])
    
    lines.extend([
        "",
        "---",
        f"- **识别引擎**: {result.get('engine', 'unknown')}",
        f"- **平均置信度**: {result.get('confidence', 'N/A')}",
        f"- **文字块数**: {len(result.get('blocks', []))}",
    ])
    
    return '\n'.join(lines)


if __name__ == '__main__':
    main()
