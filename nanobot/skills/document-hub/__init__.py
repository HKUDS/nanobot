"""
Document Hub - 统一文档处理中心

专注于Word、Excel、PDF、Markdown等文档的读取、生成和转换。

与Media Hub的关系：
- Document Hub 处理文档文件（Word/Excel/PDF/MD）
- Media Hub 处理媒体文件（图片/音频/视频）
- 两者通过协作接口共同完成多媒体内容处理

详见: skills/HUB_COLLABORATION.md
"""

from .document_hub import (
    DocumentHub,
    DocumentInfo,
    DocumentType,
    DocumentError,
    DocumentReadError,
    DocumentWriteError,
    DocumentConvertError,
    read,
    write,
    convert,
    get_info,
    get_hub,
    sanitize_path,
    to_feishu,
    from_feishu,
)

# MediaHub 已迁移到 skills/media-hub/
# 如需媒体处理功能，请使用: from skills.media_hub import get_hub

__version__ = "1.0.0"
__all__ = [
    "DocumentHub",
    "DocumentInfo",
    "DocumentType",
    "DocumentError",
    "DocumentReadError",
    "DocumentWriteError",
    "DocumentConvertError",
    "read",
    "write",
    "convert",
    "get_info",
    "get_hub",
    "sanitize_path",
    "to_feishu",
    "from_feishu",
]
