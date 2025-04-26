from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import Response, JSONResponse
import httpx
import logging
from datetime import datetime
logger = logging.getLogger('my_logger')
# 定义 API 映射
api_mapping = {
    '/discord': 'https://discord.com/api',
    '/telegram': 'https://api.telegram.org',
    '/openai': 'https://api.openai.com',
    '/claude': 'https://api.anthropic.com',
    '/gemini': 'https://generativelanguage.googleapis.com',
    '/meta': 'https://www.meta.ai/api',
    '/groq': 'https://api.groq.com/openai',
    '/xai': 'https://api.x.ai',
    '/cohere': 'https://api.cohere.ai',
    '/huggingface': 'https://api-inference.huggingface.co',
    '/together': 'https://api.together.xyz',
    '/novita': 'https://api.novita.ai',
    '/portkey': 'https://api.portkey.ai',
    '/fireworks': 'https://api.fireworks.ai',
    '/openrouter': 'https://openrouter.ai/api'
}

proxy_router = APIRouter()

@proxy_router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"])
async def proxy_request(full_path: str, request: Request):
    """
    通用反向代理路由
    """
    # 查找匹配的 API 前缀
    matched_prefix = None
    rest_of_path = None
    for prefix, target_base_url in api_mapping.items():
        # 检查是否以前缀开头，需要考虑两种情况：
        # 1. 直接匹配前缀（如 /xai/v1...）
        # 2. 匹配不带开头斜杠的前缀（如 xai/v1...）
        if full_path.startswith(prefix) or full_path.startswith(prefix.lstrip('/')):
            matched_prefix = prefix
            # 如果是直接匹配前缀，需要去掉整个前缀
            if full_path.startswith(prefix):
                rest_of_path = full_path[len(prefix):]
            else:
                # 如果是匹配不带开头斜杠的前缀，需要去掉不带斜杠的前缀长度
                rest_of_path = full_path[len(prefix.lstrip('/')):]
            break

    if not matched_prefix:
        # 如果没有匹配的前缀，返回 404
        return JSONResponse(content={"detail": "Not Found"}, status_code=404)

    target_base_url = api_mapping[matched_prefix]
    # 确保目标基础 URL 以斜杠结尾，并且剩余路径以斜杠开头，以便正确拼接
    target_url = f"{target_base_url.rstrip('/')}/{rest_of_path.lstrip('/')}"
    datetimeStr = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{datetimeStr}] Proxying request to {target_url}")
    # 转发请求
    async with httpx.AsyncClient() as client:
        try:
            # 复制请求头部，排除一些不必要的头部
            headers = dict(request.headers)
            # 移除可能导致问题的头部，例如 host, referer, origin 等
            headers.pop('host', None)
            headers.pop('referer', None)
            headers.pop('origin', None)
            headers.pop('user-agent', None) # 可选：根据需要决定是否转发 user-agent

            response = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=await request.body(), # 转发请求体
                follow_redirects=True # 根据需要决定是否跟随重定向
            )

            # 返回目标 API 的响应
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response.headers,
                media_type=response.headers.get('content-type')
            )
        except httpx.RequestError as e:
            # 处理请求错误
            return JSONResponse(content={"detail": f"Proxy request failed: {e}"}, status_code=500)
        except Exception as e:
            # 处理其他未知错误
            return JSONResponse(content={"detail": f"An unexpected error occurred: {e}"}, status_code=500)