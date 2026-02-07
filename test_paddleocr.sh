#!/bin/bash
# PaddleOCR 脚本单元测试

echo "🧪 PaddleOCR 脚本测试"
echo "=================="

# 检查Python脚本是否存在
if [ ! -f "nanobot/skills/paddleocr/scripts/ocr.py" ]; then
    echo "❌ 失败: ocr.py 不存在"
    exit 1
fi

echo "✓ ocr.py 存在"

# 测试1: 验证导入
echo ""
echo "📋 测试1: 验证导入"
python3 -c "
import sys
sys.path.insert(0, 'nanobot/skills/paddleocr/scripts')
try:
    import ocr
    print('✓ 导入成功')
except Exception as e:
    print(f'❌ 导入失败: {e}')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo "❌ 导入测试失败"
    exit 1
fi

echo "✓ 导入测试通过"

# 测试2: 验证函数存在
echo ""
echo "📋 测试2: 验证函数"
python3 -c "
import sys
sys.path.insert(0, 'nanobot/skills/paddleocr/scripts')
import ocr

functions = ['load_config', 'detect_file_type', 'encode_file', 'call_paddleocr', 'save_results', 'process_file', 'main']
missing = [f for f in functions if not hasattr(ocr, f)]

if missing:
    print(f'❌ 缺失函数: {missing}')
    sys.exit(1)

print(f'✓ 所有函数存在: {len(functions)}个')
"

if [ $? -ne 0 ]; then
    echo "❌ 函数验证失败"
    exit 1
fi

echo "✓ 函数验证通过"

# 测试3: 验证常量定义
echo ""
echo "📋 测试3: 验证常量"
python3 -c "
import sys
sys.path.insert(0, 'nanobot/skills/paddleocr/scripts')
import ocr

constants = ['DEFAULT_API_URL', 'CONFIG_PATH', 'DEFAULT_OUTPUT_DIR', 'IMAGE_EXTENSIONS']

for const in constants:
    if not hasattr(ocr, const):
        print(f'❌ 缺失常量: {const}')
        sys.exit(1)

print(f'✓ 所有常量存在: {len(constants)}个')
"

if [ $? -ne 0 ]; then
    echo "❌ 常量验证失败"
    exit 1
fi

echo "✓ 常量验证通过"

echo ""
echo "=================="
echo "✅ 所有单元测试通过！"
echo "   - 导入模块: ✓"
echo "   - 函数定义: ✓"
echo "   - 常量定义: ✓"
echo ""
echo "💡 提示: 脚本已准备就绪，可以测试API调用（需要配置PADDLEOCR_TOKEN）"
