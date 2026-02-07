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
            full_config = json.loads(CONFIG_PATH.read_text())
            config = full_config.get("tools", {}).get("paddleocr", {})
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to read config: {e}", file=sys.stderr)

    token = os.environ.get("PADDLEOCR_TOKEN") or config.get("token")

    if not token:
        print("ERROR: PaddleOCR token not configured", file=sys.stderr)
        print("\nPlease configure token in one of two ways:")
        print("1. Environment variable: export PADDLEOCR_TOKEN='your-token'")
        print(
            '2. Config file: Add to ~/.nanobot/config.json: {"tools": {"paddleocr": {"token": "your-token"}}}'
        )
        sys.exit(1)

    return {"token": token, "apiUrl": config.get("apiUrl", DEFAULT_API_URL)}


def detect_file_type(file_path: str) -> int:
    """检测文件类型：PDF->0, 图片->1"""
    ext = Path(file_path).suffix.lower()
    return 0 if ext == ".pdf" else 1


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
    headers = {"Authorization": f"token {token}", "Content-Type": "application/json"}

    payload = {
        "file": file_data,
        "fileType": file_type,
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    try:
        response = requests.post(api_url, json=payload, headers=headers, timeout=180)

        if response.status_code != 200:
            print(f"ERROR: API request failed with status {response.status_code}", file=sys.stderr)
            print(f"Response: {response.text[:200]}", file=sys.stderr)
            sys.exit(1)

        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to call API: {e}", file=sys.stderr)
        sys.exit(1)


def save_results(result: dict, output_dir: Path, filename: str) -> None:
    """保存结果：Markdown + 图片下载"""
    output_dir.mkdir(parents=True, exist_ok=True)

    # API响应结构: { "result": {...}, "errorCode": ..., "errorMsg": ... }
    error_code = result.get("errorCode", "")
    error_msg = result.get("errorMsg", "")

    if error_code:
        print(f"WARNING: API returned error: {error_code} - {error_msg}", file=sys.stderr)

    actual_result = result.get("result", {})

    # 获取markdown文本
    layout_results = actual_result.get("layoutParsingResults", [])

    # 文本提取逻辑
    markdown_text = ""
    output_images = {}

    # 优先从 layoutParsingResults 中提取
    if layout_results and isinstance(layout_results[0], dict):
        first_result = layout_results[0]
        markdown_text = first_result.get("markdown", "").get("text", "")
        output_images = first_result.get("outputImages", {})

    # 如果第一层没有，尝试直接从 result 中提取
    if not markdown_text:
        markdown_text = actual_result.get("markdown", {}).get("text", "")

    # 调试信息
    if os.environ.get("DEBUG"):
        print(f"DEBUG: API response keys: {list(result.keys())}")
        print(f"DEBUG: actual_result keys: {list(actual_result.keys())}")
        print(f"DEBUG: layoutParsingResults count: {len(layout_results)}")
        print(f"DEBUG: markdown.text length: {len(markdown_text)}")
        if layout_results and isinstance(layout_results[0], dict):
            print(f"DEBUG: First layout result keys: {list(layout_results[0].keys())}")
        print(f"DEBUG: outputImages count: {len(output_images)}")
        print(f"DEBUG: errorCode: {error_code}, errorMsg: {error_msg}")

    # 直接保存markdown文本（从结果中提取）
    md_filename = output_dir / f"{filename}.md"
    try:
        md_filename.write_text(markdown_text, encoding="utf-8")
        print(f"✓ 保存: {md_filename}")
        if markdown_text:
            print(f"  └─ 文本长度: {len(markdown_text)} 字符")
        else:
            print(f"  └─ WARNING: 文本为空", file=sys.stderr)
    except IOError as e:
        print(f"ERROR: Failed to save {md_filename}: {e}", file=sys.stderr)

    # 处理关联图片（如果存在）
    for img_name, img_url in output_images.items():
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

    # 提取文件名（不含扩展名）
    filename = Path(file_path).stem

    # API响应结构: { "result": {...}, "errorCode": ..., "errorMsg": ... }
    actual_result = result.get("result", {})
    doc_count = len(actual_result.get("layoutParsingResults", []))
    save_results(result, output_dir, filename)

    print(f"  └─ 生成 {doc_count} 个文档")
    print()
    return doc_count


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="OCR image and PDF recognition using PaddleOCR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("files", nargs="+", help="一个或多个图片/PDF文件")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录（默认: {DEFAULT_OUTPUT_DIR})",
    )

    args = parser.parse_args()

    config = load_config()

    total_docs = 0
    for file_path in args.files:
        total_docs += process_file(str(file_path), args.output, config)

    print(f"✓ 完成: {total_docs} 个文档已保存到 {args.output}")


if __name__ == "__main__":
    main()
