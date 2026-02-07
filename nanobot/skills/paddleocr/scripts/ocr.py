#!/usr/bin/env python3
"""
PaddleOCR OCR Script
识别图片和PDF文档中的文字，支持批量处理多个文件。
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
import requests

# 默认API URL
DEFAULT_API_URL = "https://k7b3acgclfxeacxe.aistudio-app.com/layout-parsing"
CONFIG_PATH = Path("~/.nanobot/config.json").expanduser()
DEFAULT_OUTPUT_DIR = Path("~/.nanobot/workspace/output").expanduser()

# 图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff"}


def load_config():
    """加载配置：环境变量 > config.json > 默认值"""
    config = {}
    if CONFIG_PATH.exists():
        try:
            config = json.loads(CONFIG_PATH.read_text()).get("paddleocr", {})
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to read config: {e}", file=sys.stderr)
    
    token = os.environ.get("PADDLEOCR_TOKEN") or config.get("token")
    
    if not token:
        print("ERROR: PaddleOCR token not configured", file=sys.stderr)
        print("\nPlease configure token in one of two ways:")
        print("1. Environment variable: export PADDLEOCR_TOKEN='your-token'")
        print('2. Config file: Add to ~/.nanobot/config.json: {"paddleocr": {"token": "your-token"}}')
        sys.exit(1)
    
    return {
        "token": token,
        "apiUrl": config.get("apiUrl", DEFAULT_API_URL)
    }


def detect_file_type(file_path: str) -> int:
    """检测文件类型：PDF->0, 图片->1"""
    ext = Path(file_path).suffix.lower()
    return 0 if ext == '.pdf' else 1


def encode_file(file_path: str) -> str:
    """Base64编码文件"""
    try:
        with open(file_path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except (IOError, OSError) as e:
        print(f"ERROR: Failed to read file {file_path}: {e}", file=sys.stderr)
        sys.exit(1)


def call_paddleocr(file_data: str, file_type: int, api_url: str, token: str) -> dict:
    """调用PaddleOCR API"""
    headers = {
        "Authorization": f"token {token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "file": file_data,
        "fileType": file_type,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    
    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=60)
        
        if response.status_code != 200:
            print(f"ERROR: API request failed with status {response.status_code}", file=sys.stderr)
            print(f"Response: {response.text[:200]}", file=sys.stderr)
            sys.exit(1)
        
        return response.json()
    
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to call API: {e}", file=sys.stderr)
        sys.exit(1)


def save_results(result: dict, output_dir: Path, doc_index: int) -> None:
    """保存结果：Markdown + 图片下载"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    layout_results = result.get("layoutParsingResults", [])
    for i, res in enumerate(layout_results):
        md_filename = output_dir / f"doc_{doc_index}_{i}.md"
        try:
            md_text = res.get("markdown", {}).get("text", "")
            md_filename.write_text(md_text, encoding="utf-8")
            print(f"✓ 保存: {md_filename}")
        except IOError as e:
            print(f"ERROR: Failed to save {md_filename}: {e}", file=sys.stderr)
        
        markdown_images = res.get("markdown", {}).get("images", {})
        for img_name, img_url in markdown_images.items():
            img_path = output_dir / img_name
            try:
                img_response = requests.get(img_url, timeout=30)
                if img_response.status_code == 200:
                    img_path.write_bytes(img_response.content)
                    print(f"  └─ 图片: {img_path}")
            except (requests.exceptions.RequestException, IOError) as e:
                print(f"  └─ WARNING: Failed to download {img_name}: {e}", file=sys.stderr)


def process_file(file_path: str, output_dir: Path, config: dict) -> int:
    """处理单个文件"""
    if not Path(file_path).exists():
        print(f"ERROR: 文件不存在: {file_path}", file=sys.stderr)
        return 0
    
    print(f"处理: {file_path}")
    
    file_type = detect_file_type(file_path)
    file_data = encode_file(file_path)
    
    result = call_paddleocr(file_data, file_type, config["apiUrl"], config["token"])
    
    doc_count = len(result.get("layoutParsingResults", []))
    save_results(result, output_dir, doc_count)
    
    print(f"  └─ 生成 {doc_count} 个文档")
    print()
    return doc_count


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="OCR image and PDF recognition using PaddleOCR",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "files",
        nargs='+',
        help="一个或多个图片/PDF文件"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录（默认: {DEFAULT_OUTPUT_DIR})"
    )
    
    args = parser.parse_args()
    
    config = load_config()
    
    total_docs = 0
    for file_path in args.files:
        total_docs += process_file(str(file_path), args.output, config)
    
    print(f"✓ 完成: {total_docs} 个文档已保存到 {args.output}")


if __name__ == "__main__":
    main()
