# -*- coding: utf-8 -*-
import yaml

from typing import Dict, Any


def read(yaml_path) -> Dict[str, Any]:
    """
    读取指定目录的yaml文件

    :param yaml_path: 相对当前的yaml文件绝对路径
    :return:
    """
    # 加上 ,encoding='utf-8'，处理配置文件中含中文出现乱码的情况。
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)