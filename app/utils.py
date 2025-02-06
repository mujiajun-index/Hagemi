import google.generativeai as genai
from google.api_core.exceptions import GoogleAPIError
from fastapi import HTTPException, Request
import time
from threading import Lock
from google.api_core.exceptions import ResourceExhausted, InternalServerError, ServiceUnavailable,  InvalidArgument


def handle_gemini_error(e: Exception) -> str:
    if isinstance(e, ResourceExhausted):
        return "API 密钥配额已用尽"
    elif isinstance(e, (InternalServerError, ServiceUnavailable)):
        return "Gemini API 内部错误或服务不可用"
    elif isinstance(e, InvalidArgument):
        return f"无效参数错误: {e.message}"
    elif isinstance(e, GoogleAPIError):
        if "429" in str(e) and "Quota exceeded" in str(e):
            return "API 密钥配额已用尽"
        if "400" in str(e) and "invalid" in str(e).lower():
            return "无效参数"
        return f"Gemini API 错误: {e.message}"
    else:
        return str(e)


async def test_api_key(api_key: str) -> bool:
    """
    测试 API 密钥是否有效。
    """
    try:
        genai.configure(api_key=api_key)
        models = genai.list_models()
        # 检查返回的模型列表是否为空
        if not models:
            return False
        # 进一步检查 (可选, 根据 Gemini API 的实际响应调整)
        for model in models:
            if "error" in model.name.lower():  # 假设错误模型名称中包含 "error"
                return False
        return True  # 如果列表不为空，且没有发现错误，则认为密钥有效
    except GoogleAPIError as e:
        print(f"GoogleAPIError: {e}")
        return False
    except Exception as e:
        print(f"Other Exception: {e}")
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
        minute_count, minute_timestamp = rate_limit_data.get(minute_key, (0, now))
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
         raise HTTPException(status_code=429, detail={"message": "Too many requests per minute", "limit": max_requests_per_minute})
    if day_count > max_requests_per_day_per_ip:
         raise HTTPException(status_code=429, detail={"message": "Too many requests per day from this IP", "limit": max_requests_per_day_per_ip})