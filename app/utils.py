import random
from fastapi import HTTPException, Request
import time
from google.api_core.exceptions import ResourceExhausted, InternalServerError, ServiceUnavailable, GoogleAPIError, InvalidArgument
import google.generativeai as genai
from threading import Lock


def rotate_api_keys(api_keys: list):
    """
    随机打乱 API 密钥列表，实现轮询。
    """
    random.shuffle(api_keys)
    return api_keys

def handle_gemini_error(e: Exception) -> str:
    """
    处理 Gemini API 错误，提取有用的错误信息，并翻译成中文。
    更强的绕过google检查的错误处理
    """
    if isinstance(e, ResourceExhausted):
        return "API 密钥配额已用尽"
    elif isinstance(e, (InternalServerError, ServiceUnavailable)):
        return "Gemini API 内部错误或服务不可用"
    elif isinstance(e, InvalidArgument):
        return f"无效参数错误: {e.message}"  # 仍然保留原始的 e.message
    elif isinstance(e, GoogleAPIError):
        # 尝试更详细地解析 GoogleAPIError
        if "429" in str(e) and "Quota exceeded" in str(e): return "API 密钥配额已用尽"
        if "400" in str(e) and "invalid" in str(e).lower(): return "无效参数"
        return f"Gemini API 错误: {e.message}" # 仍然保留原始的 e.message
    else:
        return str(e)  # 仍然保留原始的错误信息

async def test_api_key(api_key: str) -> bool:
    """
    测试 API 密钥是否有效。
    """
    try:
        genai.configure(api_key=api_key)
        genai.list_models()
        return True
    except Exception:
        return False


# 全局变量和锁
rate_limit_data = {}
rate_limit_lock = Lock()

def protect_from_abuse(request: Request, max_requests_per_minute: int = 30, max_requests_per_day_per_ip: int = 600):
    now = int(time.time())
    minute = now // 60
    day = now // (60 * 60 * 24)

    # 注意：这里建议对 day_key 不要区分 URL 路径，否则每个路径都会单独计数
    minute_key = f"{request.url.path}:{minute}"
    day_key = f"{request.client.host}:{day}"

    with rate_limit_lock:
        # 分钟计数
        minute_count, minute_timestamp = rate_limit_data.get(minute_key, (0, now))
        if now - minute_timestamp >= 60:
            # 超过一分钟则重置
            minute_count = 0
            minute_timestamp = now
        minute_count += 1
        rate_limit_data[minute_key] = (minute_count, minute_timestamp)

        # 日计数
        day_count, day_timestamp = rate_limit_data.get(day_key, (0, now))
        if now - day_timestamp >= 86400:
            day_count = 0
            day_timestamp = now
        day_count += 1
        rate_limit_data[day_key] = (day_count, day_timestamp)

    if minute_count > max_requests_per_minute:
         raise HTTPException(status_code=429, detail={"message": "Too many requests per minute", "limit": max_requests_per_minute})
    if day_count > max_requests_per_day_per_ip:
         raise HTTPException(status_code=429, detail={"message": "Too many requests per day from this IP", "limit": max_requests_per_day_per_ip})
