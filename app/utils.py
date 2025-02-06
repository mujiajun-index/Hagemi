import random
from fastapi import HTTPException, Request
import time
import re
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import os
import logging
import requests
import httpx
from threading import Lock

logger = logging.getLogger("gemini_app")

class APIKeyManager:
    def __init__(self):
        self.api_keys = re.findall(
            r"AIzaSy[a-zA-Z0-9_-]{33}", os.environ.get('GEMINI_API_KEYS', ""))
        self.current_index = random.randint(0, len(self.api_keys) - 1) if self.api_keys else 0 # 避免空列表时报错
        self.api_key_blacklist = set()
        self.api_key_blacklist_duration = 60
        self.scheduler = BackgroundScheduler()
        self.scheduler.start()

    def get_available_key(self):
        num_keys = len(self.api_keys)
        if num_keys == 0:  # 处理没有 API 密钥的情况
            logger.error("没有配置任何 API 密钥！")
            return None

        for _ in range(num_keys):
            if self.current_index >= num_keys:
                self.current_index = 0
            current_key = self.api_keys[self.current_index]
            self.current_index += 1

            if current_key not in self.api_key_blacklist:
                return current_key

        logger.error("所有API key都已耗尽或被暂时禁用，请重新配置或稍后重试")
        return None
    
    def show_all_keys(self):
        logger.info(f"当前可用API key个数: {len(self.api_keys)} ", extra={'key': 'N/A', 'request_type': 'startup', 'model': 'N/A', 'status_code': 'N/A', 'error_message': ''})
        for i, api_key in enumerate(self.api_keys):
            logger.info(f"API Key{i}: {api_key[:8]}...{api_key[-3:]}", extra={'key': api_key[:8], 'request_type': 'startup', 'model': 'N/A', 'status_code': 'N/A', 'error_message': ''})


    def blacklist_key(self, key):
        logger.warning(f"{key[:8]} → 暂时禁用 {self.api_key_blacklist_duration} 秒")
        self.api_key_blacklist.add(key)
        self.scheduler.add_job(lambda: self.api_key_blacklist.discard(key), 'date',
                               run_date=datetime.now() + timedelta(seconds=self.api_key_blacklist_duration))

def handle_gemini_error(error, current_api_key, key_manager, switch_api_key_func) -> str:
    if isinstance(error, requests.exceptions.HTTPError):
        status_code = error.response.status_code
        if status_code == 400:
            try:
                error_data = error.response.json()
                if 'error' in error_data:
                    if error_data['error'].get('code') == "invalid_argument":
                        logger.error(
                            f"{current_api_key[:8]} ... {current_api_key[-3:]} → 无效，可能已过期或被删除")
                        key_manager.blacklist_key(current_api_key)
                        switch_api_key_func()
                        return "无效的 API 密钥"
                    error_message = error_data['error'].get(
                        'message', 'Bad Request')
                    logger.warning(f"400 错误请求: {error_message}")
                    return f"400 错误请求: {error_message}"
            except ValueError:
                logger.warning("400 错误请求：响应不是有效的JSON格式")
                return "400 错误请求：响应不是有效的JSON格式"

        elif status_code == 429:
            logger.warning(
                f"{current_api_key[:8]} ... {current_api_key[-3:]} → 429 官方资源耗尽"
            )
            key_manager.blacklist_key(current_api_key)
            switch_api_key_func()
            return "API 密钥配额已用尽"

        elif status_code == 403:
            logger.error(
                f"{current_api_key[:8]} ... {current_api_key[-3:]} → 403 权限被拒绝"
            )
            key_manager.blacklist_key(current_api_key)
            switch_api_key_func()
            return "权限被拒绝"
        elif status_code == 500:
            logger.warning(
                f"{current_api_key[:8]} ... {current_api_key[-3:]} → 500 服务器内部错误"
            )
            switch_api_key_func()
            return "Gemini API 内部错误"

        elif status_code == 503:
            logger.warning(
                f"{current_api_key[:8]} ... {current_api_key[-3:]} → 503 服务不可用"
            )
            switch_api_key_func()
            return "Gemini API 服务不可用"
        else:
            logger.warning(
                f"{current_api_key[:8]} ... {current_api_key[-3:]} → {status_code} 未知错误"
            )
            switch_api_key_func()
            return f"未知错误/模型不可用: {status_code}"

    elif isinstance(error, requests.exceptions.ConnectionError):
        logger.warning(f"连接错误")
        return "连接错误"

    elif isinstance(error, requests.exceptions.Timeout):
        logger.warning(f"请求超时")
        return "请求超时"
    else:
        logger.error(f"发生未知错误: {error}")
        return f"发生未知错误: {error}"

async def test_api_key(api_key: str) -> bool:
    """
    测试 API 密钥是否有效。
    """
    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models?key={}".format(api_key)
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            return True
    except Exception:
        return False

rate_limit_data = {}
rate_limit_lock = Lock()

def protect_from_abuse(request: Request, max_requests_per_minute: int = 30, max_requests_per_day_per_ip: int = 600):
    now = int(time.time())
    minute = now // 60
    day = now // (60 * 60 * 24)

    minute_key = f"{request.url.path}:{minute}"
    day_key = f"{request.client.host}:{day}"

    with rate_limit_lock:
        minute_count, minute_timestamp = rate_limit_data.get(
            minute_key, (0, now))
        if now - minute_timestamp >= 60:
            minute_count = 0
            minute_timestamp = now
        minute_count += 1
        rate_limit_data[minute_key] = (minute_count, minute_timestamp)

        day_count, day_timestamp = rate_limit_data.get(day_key, (0, now))
        if now - day_timestamp >= 86400:
            day_count = 0
            day_timestamp = now
        day_count += 1
        rate_limit_data[day_key] = (day_count, day_timestamp)

    if minute_count > max_requests_per_minute:
        raise HTTPException(status_code=429, detail={
            "message": "Too many requests per minute", "limit": max_requests_per_minute})
    if day_count > max_requests_per_day_per_ip:
        raise HTTPException(status_code=429, detail={"message": "Too many requests per day from this IP", "limit": max_requests_per_day_per_ip})