# -*- coding: utf-8 -*-

from botpy import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

_log = logging.get_logger()

scheduler = AsyncIOScheduler()
scheduler.configure({"apscheduler.timezone": "Asia/Shanghai"})

scheduler.start()
_log.debug("[加载插件] APScheduler 定时任务")