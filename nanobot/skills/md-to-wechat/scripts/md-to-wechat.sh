#!/bin/bash
# Markdown to WeChat HTML Converter
# 将Markdown文件转换为微信公众号兼容的HTML

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 检查参数
if [ $# -lt 1 ]; then
    echo "用法: $0 <input.md> [选项]"
    echo ""
    echo "选项:"
    echo "  -o, --output     输出HTML文件路径"
    echo "  -t, --title      文章标题"
    echo "  -s, --subtitle   副标题"
    echo "  -a, --author     作者名称 (默认: 非凡产研)"
    echo "  --tags           标签列表，逗号分隔"
    echo ""
    echo "示例:"
    echo "  $0 article.md"
    echo "  $0 article.md -o output.html -t \"标题\" -s \"副标题\""
    exit 1
fi

INPUT_FILE="$1"
shift

# 检查输入文件是否存在
if [ ! -f "$INPUT_FILE" ]; then
    echo "❌ 文件不存在: $INPUT_FILE"
    exit 1
fi

# 执行Python脚本
python3 "${SKILL_DIR}/md_to_wechat.py" "$INPUT_FILE" "$@"
