from fastapi import APIRouter, Request
from fastapi.responses import Response, JSONResponse, StreamingResponse
import requests
import logging
from datetime import datetime

logger = logging.getLogger('my_logger')

# 定义静态资源代理映射
static_mapping = {
    '/xai-imgen': 'https://imgen.x.ai'
}

static_proxy_router = APIRouter()

@static_proxy_router.api_route("/{full_path:path}", methods=["GET"])
async def static_proxy_request(full_path: str, request: Request):
    """
    静态资源反向代理路由
    """
    # 查找匹配的静态资源前缀
    matched_prefix = None
    rest_of_path = None
    for prefix, target_base_url in static_mapping.items():
        # 检查是否以前缀开头
        if full_path.startswith(prefix) or full_path.startswith(prefix.lstrip('/')):
            matched_prefix = prefix
            rest_of_path = full_path # 静态资源前缀不需要去掉
            # # 如果是直接匹配前缀，需要去掉整个前缀
            # if full_path.startswith(prefix):
            #     rest_of_path = full_path[len(prefix):]
            # else:
            #     # 如果是匹配不带开头斜杠的前缀，需要去掉不带斜杠的前缀长度
            #     rest_of_path = full_path[len(prefix.lstrip('/')):]          
            break

    if not matched_prefix:
        # 如果没有匹配的前缀，返回 404
        return JSONResponse(content={"detail": f"Invalid URL ({request.method} /{full_path})"}, status_code=404)

    target_base_url = static_mapping[matched_prefix]
    # 确保目标基础 URL 以斜杠结尾，并且剩余路径以斜杠开头，以便正确拼接
    target_url = f"{target_base_url.rstrip('/')}/{rest_of_path.lstrip('/')}"
    # datetimeStr = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # logger.info(f"[{datetimeStr}] Proxying static request to {target_url}")

    try:
        # 复制请求头部，排除一些不必要的头部
        headers = dict(request.headers)
        # 移除可能导致问题的头部
        headers.pop('host', None)
        headers.pop('referer', None)
        headers.pop('origin', None)
        headers.pop('user-agent', None)

        # 发送请求到目标服务器
        response = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            stream=True  # 使用流式传输以支持大文件
        )

        # 定义异步生成器函数来处理流式响应
        async def stream_response():
            try:
                # 设置较小的块大小以实现更平滑的流式传输
                chunk_size = 8192  # 8KB 的块大小
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if await request.is_disconnected():
                        # 如果客户端断开连接，关闭响应并退出
                        response.close()
                        break
                    if chunk:  # 过滤掉保持活动的新行
                        yield chunk
            except Exception as e:
                # 发生异常时确保关闭响应
                response.close()
                raise e

        # 返回流式响应
        return StreamingResponse(
            content=stream_response(),
            status_code=response.status_code,
            media_type=response.headers.get('content-type')
        )

    except requests.RequestException as e:
        # 处理请求错误
        return JSONResponse(content={"detail": f"Static proxy request failed: {e}"}, status_code=500)
    except Exception as e:
        # 处理其他未知错误
        return JSONResponse(content={"detail": f"An unexpected error occurred: {e}"}, status_code=500)