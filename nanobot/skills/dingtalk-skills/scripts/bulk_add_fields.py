#!/usr/bin/env python3
"""
批量添加字段到钉钉 AI 表格数据表（新版 schema）

用法:
    python bulk_add_fields.py <baseId> <tableId> fields.json

fields.json 格式:
    [
        {"fieldName": "字段 1", "type": "text"},
        {"fieldName": "字段 2", "type": "number", "config": {"formatter": "INT"}},
        {"fieldName": "字段 3", "type": "singleSelect", "config": {"options": [{"name": "高"}]}}
    ]

兼容写法：
- name 会自动映射为 fieldName
- phone 会自动映射为 telephone
"""

import sys
import json
import subprocess
import os
import re
from pathlib import Path
from typing import Union, List, Dict, Any, Optional, Tuple

JsonData = Union[List[Any], Dict[str, Any]]

MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_FILE_EXTENSIONS = ['.json']
RESOURCE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{8,128}$')
ALLOWED_FIELD_TYPES = {
    'text', 'number', 'singleSelect', 'multipleSelect', 'date', 'currency',
    'user', 'department', 'group', 'progress', 'rating', 'checkbox',
    'attachment', 'url', 'richText', 'telephone', 'email', 'idCard',
    'barcode', 'geolocation', 'primaryDoc', 'formula', 'unidirectionalLink',
    'bidirectionalLink', 'creator', 'lastModifier', 'createdTime',
    'lastModifiedTime',
}
FIELD_TYPE_ALIASES = {
    'phone': 'telephone',
}


def resolve_safe_path(path: str, allowed_root: Optional[str] = None) -> Path:
    if allowed_root is None:
        allowed_root = os.environ.get('OPENCLAW_WORKSPACE', os.getcwd())

    allowed_root = Path(allowed_root).resolve()
    target_path = (
        Path(path).resolve()
        if Path(path).is_absolute()
        else (Path.cwd() / path).resolve()
    )

    try:
        target_path.relative_to(allowed_root)
        return target_path
    except ValueError:
        raise ValueError(
            f"路径超出允许范围：{path}\n"
            f"目标路径：{target_path}\n"
            f"允许根目录：{allowed_root}\n"
            f"提示：设置 OPENCLAW_WORKSPACE 环境变量或确保文件在工作目录内"
        )


def validate_resource_id(resource_id: str) -> bool:
    return bool(resource_id and RESOURCE_ID_PATTERN.match(resource_id.strip()))


def validate_file_extension(filename: str, allowed_extensions: list) -> bool:
    return any(filename.lower().endswith(ext) for ext in allowed_extensions)


def safe_json_load(file_path: Path, max_size: int = MAX_FILE_SIZE) -> JsonData:
    file_size = file_path.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"文件过大：{file_size:,} 字节 (限制：{max_size:,} 字节)"
        )
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def normalize_field_config(field: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(field)
    if 'fieldName' not in normalized and 'name' in normalized:
        normalized['fieldName'] = normalized.pop('name')
    normalized['type'] = FIELD_TYPE_ALIASES.get(
        normalized.get('type', 'text'), normalized.get('type', 'text')
    )
    return normalized


def validate_field_config(field: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(field, dict):
        return False, '字段配置必须是对象'

    field = normalize_field_config(field)

    if 'fieldName' not in field:
        return False, '缺少必需字段：fieldName'
    if not isinstance(field['fieldName'], str) or not field['fieldName'].strip():
        return False, 'fieldName 必须是非空字符串'

    field_type = field.get('type', 'text')
    if field_type not in ALLOWED_FIELD_TYPES:
        return False, f"不支持的字段类型：{field_type}"

    config = field.get('config')
    if config is not None and not isinstance(config, dict):
        return False, 'config 必须是对象'

    if field_type in {'singleSelect', 'multipleSelect'}:
        options = (config or {}).get('options')
        if not options or not isinstance(options, list):
            return False, (
                'singleSelect / multipleSelect 必须提供 config.options 数组'
            )

    if field_type in {'unidirectionalLink', 'bidirectionalLink'}:
        linked_sheet_id = (config or {}).get('linkedSheetId')
        if not linked_sheet_id or not validate_resource_id(linked_sheet_id):
            return False, '关联字段必须提供合法的 config.linkedSheetId'

    return True, ''


def build_fields_json(fields: List[Dict[str, Any]]) -> str:
    """构建 --fields 参数的 JSON 字符串。"""
    payload_fields = []
    for field in fields:
        normalized = normalize_field_config(field)
        item: Dict[str, Any] = {
            'fieldName': normalized['fieldName'].strip(),
            'type': normalized.get('type', 'text'),
        }
        if 'config' in normalized and normalized['config'] is not None:
            item['config'] = normalized['config']
        payload_fields.append(item)
    return json.dumps(payload_fields, ensure_ascii=False)


def run_dws(args: List[str]) -> Optional[Dict[str, Any]]:
    if not args:
        print('错误：空命令')
        return None

    cmd = ['dws'] + args
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"错误：{result.stderr.strip()}")
            return None
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"无法解析响应：{result.stdout[:200]}...")
            print(f"JSON 解析错误：{e}")
            return None
    except subprocess.TimeoutExpired:
        print('错误：命令执行超时（60 秒）')
        return None
    except FileNotFoundError:
        print('错误：未找到 dws 命令，请确认已安装')
        return None


def bulk_add_fields(
    base_id: str, table_id: str, fields_file: str
) -> bool:
    try:
        safe_path = resolve_safe_path(fields_file)
    except ValueError as e:
        print(f"路径验证失败：{e}")
        return False

    if not validate_file_extension(fields_file, ALLOWED_FILE_EXTENSIONS):
        print(f"错误：只允许 {', '.join(ALLOWED_FILE_EXTENSIONS)} 文件")
        return False
    if not safe_path.exists():
        print(f"错误：文件不存在：{safe_path}")
        return False

    try:
        fields = safe_json_load(safe_path)
    except ValueError as e:
        print(f"错误：{e}")
        return False
    except json.JSONDecodeError as e:
        print(f"错误：JSON 格式无效：{e}")
        return False

    if not isinstance(fields, list) or not fields:
        print('错误：fields.json 必须是非空 JSON 数组')
        return False
    if len(fields) > 15:
        print('错误：单次最多创建 15 个字段，请拆分后重试')
        return False

    for i, field in enumerate(fields):
        valid, error = validate_field_config(field)
        if not valid:
            print(f"错误：字段 #{i+1} 配置无效：{error}")
            return False

    fields_json = build_fields_json(fields)
    result = run_dws([
        'aitable', 'field', 'create',
        '--base-id', base_id,
        '--table-id', table_id,
        '--fields', fields_json,
        '--format', 'json',
    ])

    if not result:
        return False

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return True


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        print('用法示例:')
        print('  python bulk_add_fields.py basexxx tablexxx fields.json')
        sys.exit(1)

    base_id = sys.argv[1]
    table_id = sys.argv[2]
    fields_file = sys.argv[3]

    if not validate_resource_id(base_id):
        print('错误：无效的 baseId 格式')
        sys.exit(1)
    if not validate_resource_id(table_id):
        print('错误：无效的 tableId 格式')
        sys.exit(1)

    success = bulk_add_fields(base_id, table_id, fields_file)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
