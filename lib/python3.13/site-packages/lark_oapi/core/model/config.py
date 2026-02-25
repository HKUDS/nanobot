from typing import Optional

from lark_oapi.core import AppType, LogLevel
from lark_oapi.core.cache import ICache
from lark_oapi.core.const import FEISHU_DOMAIN


class Config(object):
    def __init__(self) -> None:
        self.app_id: Optional[str] = None
        self.app_secret: Optional[str] = None
        self.domain: str = FEISHU_DOMAIN  # 域名, 默认为 https://open.feishu.cn
        self.timeout: Optional[float] = None  # 客户端超时时间, 单位秒, 默认永不超时
        self.app_type: AppType = AppType.SELF  # 应用类型, 默认为自建应用; 若设为 ISV 需在 request_option 中配置 tenant_key
        self.enable_set_token: bool = False  # 是否允许手动设置 token, 默认不开启; 开启后需在 request_option 中配置 token
        self.cache: Optional[ICache] = None  # 自定义缓存, 默认使用预置的本地缓存
        self.log_level: LogLevel = LogLevel.WARNING  # 日志级别, 默认为 WARNING
