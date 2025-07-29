from fastapi import FastAPI, HTTPException, Request, Depends, status, Body
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from .models import ChatCompletionRequest, ChatCompletionResponse, ErrorResponse, ModelList
from .gemini import GeminiClient, ResponseWrapper
from .utils import handle_gemini_error, protect_from_abuse, APIKeyManager, test_api_key, format_log_message
import os
import json
import asyncio
from typing import Literal, List
import io
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import sys
import logging
import base64
from dotenv import load_dotenv, set_key
from jose import JWTError, jwt
from datetime import timedelta

# 加载.env文件中的环境变量
load_dotenv()

# JWT 配置
SECRET_KEY = os.environ.get("SECRET_KEY", "a_very_secret_key") # 强烈建议在.env中设置一个安全的密钥
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
logging.getLogger("uvicorn").disabled = True
logging.getLogger("uvicorn.access").disabled = True

# 配置 logger
logger = logging.getLogger("my_logger")
logger.setLevel(logging.DEBUG)

def translate_error(message: str) -> str:
    if "quota exceeded" in message.lower():
        return "API 密钥配额已用尽"
    if "invalid argument" in message.lower():
        return "无效参数"
    if "internal server error" in message.lower():
        return "服务器内部错误"
    if "service unavailable" in message.lower():
        return "服务不可用"
    return message


def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.excepthook(exc_type, exc_value, exc_traceback)
        return
    error_message = translate_error(str(exc_value))
    log_msg = format_log_message('ERROR', f"未捕获的异常: %s" % error_message, extra={'status_code': 500, 'error_message': error_message})
    logger.error(log_msg)


sys.excepthook = handle_exception

app = FastAPI()

from .config_manager import load_api_mappings, save_api_mappings, get_api_mappings

# 挂载静态文件目录
app.mount("/images", StaticFiles(directory="app/images"), name="images")

# 导入图片存储模块
from .image_storage import get_image_storage, ImageStorage, MemoryImageStorage

# 创建全局图片存储实例
global_image_storage = get_image_storage()

# IP授权池
WHITELIST_IPS = os.environ.get("WHITELIST_IPS", "").split(",")
authorized_ips = set(ip.strip() for ip in WHITELIST_IPS if ip.strip())

PASSWORD = os.environ.get("PASSWORD", "123")
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"))
MAX_REQUESTS_PER_DAY_PER_IP = int(
    os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"))
# MAX_RETRIES = int(os.environ.get('MaxRetries', '3').strip() or '3')
RETRY_DELAY = 1
MAX_RETRY_DELAY = 16
VERSION = os.environ.get('VERSION', "")
safety_settings = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "OFF"
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "OFF"
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "OFF"
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "OFF"
    },
    {
        "category": 'HARM_CATEGORY_CIVIC_INTEGRITY',
        "threshold": 'OFF'
    }
]
safety_settings_g2 = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "OFF"
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "OFF"
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "OFF"
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "OFF"
    },
    {
        "category": 'HARM_CATEGORY_CIVIC_INTEGRITY',
        "threshold": 'OFF'
    }
]

key_manager = APIKeyManager() # 实例化 APIKeyManager，栈会在 __init__ 中初始化
current_api_key = key_manager.get_available_key()


def switch_api_key():
    global current_api_key
    key = key_manager.get_available_key() # get_available_key 会处理栈的逻辑
    if key:
        current_api_key = key
        log_msg = format_log_message('INFO', f"API key 替换为 → {current_api_key[:8]}...", extra={'key': current_api_key[:8], 'request_type': 'switch_key'})
        logger.info(log_msg)
    else:
        log_msg = format_log_message('ERROR', "API key 替换失败，所有API key都已尝试，请重新配置或稍后重试", extra={'key': 'N/A', 'request_type': 'switch_key', 'status_code': 'N/A'})
        logger.error(log_msg)


async def check_keys():
    available_keys = []
    for key in key_manager.api_keys:
        is_valid = await test_api_key(key)
        status_msg = "有效" if is_valid else "无效"
        log_msg = format_log_message('INFO', f"API Key {key[:10]}... {status_msg}.")
        logger.info(log_msg)
        if is_valid:
            available_keys.append(key)
    if not available_keys:
        log_msg = format_log_message('ERROR', "没有可用的 API 密钥！", extra={'key': 'N/A', 'request_type': 'startup', 'status_code': 'N/A'})
        logger.error(log_msg)
    return available_keys


async def reload_keys():
    """
    重新加载、检查并设置可用的API密钥和模型。
    """
    log_msg = format_log_message('INFO', "Reloading and checking API keys...")
    logger.info(log_msg)
    available_keys = await check_keys()
    if available_keys:
        key_manager.api_keys = available_keys
        key_manager._reset_key_stack()
        key_manager.show_all_keys()
        log_msg = format_log_message('INFO', f"可用 API 密钥数量：{len(key_manager.api_keys)}")
        logger.info(log_msg)
        log_msg = format_log_message('INFO', f"最大重试次数设置为：{len(key_manager.api_keys)}")
        logger.info(log_msg)
        if key_manager.api_keys:
            try:
                all_models = await GeminiClient.list_available_models(key_manager.api_keys[0])
                GeminiClient.AVAILABLE_MODELS = [model.replace("models/", "") for model in all_models]
                log_msg = format_log_message('INFO', "Available models loaded.")
                logger.info(log_msg)
            except Exception as e:
                log_msg = format_log_message('ERROR', f"Failed to load models: {e}")
                logger.error(log_msg)
    else:
        log_msg = format_log_message('ERROR', "No available API keys after reload.")
        logger.error(log_msg)


@app.on_event("startup")
async def startup_event():
    load_api_mappings()
    log_msg = format_log_message('INFO', "Starting Gemini API proxy...")
    logger.info(log_msg)
    await reload_keys()

@app.get("/v1/models", response_model=ModelList)
def list_models():
    log_msg = format_log_message('INFO', "Received request to list models", extra={'request_type': 'list_models', 'status_code': 200})
    logger.info(log_msg)
    return ModelList(data=[{"id": model, "object": "model", "created": 1678888888, "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS])

# 校验密码逻辑
async def verify_password(request: Request):
    auth_header = request.headers.get("Authorization")
    client_ip = request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or \
                request.headers.get('X-Real-IP', '') or \
                request.headers.get('CF-Connecting-IP', '') or \
                request.client.host if request.client else "unknown_ip"

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        
        # 尝试JWT Token验证
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username: str = payload.get("sub")
            if username is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
            return True # Token有效
        except JWTError:
            # 如果JWT验证失败，继续尝试原始的密码验证逻辑
            pass

        # 原始密码验证
        if token == PASSWORD:
            return True

    if not PASSWORD:
        return True

    # Authorized IP
    if client_ip in authorized_ips:
        return True

    # 仅在其他验证方式失败时才尝试读取body
    try:
        body = await request.json()
    except Exception:
        body = None

    def verify_auth_command(text: str) -> bool:
        import re
        auth_match = re.search(r'auth\s([^\s]+)', text.lower())
        if auth_match and auth_match.group(1) == PASSWORD:
            authorized_ips.add(client_ip)
            logger.info(format_log_message('INFO', f"IP {client_ip} Successfully authorized through the auth command.",
                                          extra={'ip': client_ip, 'method': 'AUTH_command'}))
            return True
        return False

    if body and 'messages' in body:
        messages = request_json['messages']
        if messages and isinstance(messages, list):
            last_message = messages[-1]
            if isinstance(last_message, dict) and 'content' in last_message:
                content = last_message['content']
                # 处理字符串类型的content
                if isinstance(content, str):
                    if verify_auth_command(content):
                        return True
                # 处理数组类型的content
                elif isinstance(content, list):
                    text_items = [item.get('text', '') for item in content if item.get('type') == 'text']
                    if text_items and verify_auth_command(text_items[-1]):
                        return True

    # If all attempts fail
    detail_message = "Unauthorized: Authentication required."
    if auth_header and not auth_header.startswith("Bearer "):
        detail_message = "Unauthorized: Invalid token type. Bearer token required."
    
    logger.warning(format_log_message('WARNING', f"Auth failed for IP {client_ip}: {detail_message}", 
                                     extra={'ip': client_ip, 'reason': 'All auth methods failed'}))
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail_message)


async def process_request(chat_request: ChatCompletionRequest, http_request: Request, request_type: Literal['stream', 'non-stream']):
    global current_api_key
    protect_from_abuse(
        http_request, MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP)
    if chat_request.model not in GeminiClient.AVAILABLE_MODELS:
        error_msg = "无效的模型"
        extra_log = {'request_type': request_type, 'model': chat_request.model, 'status_code': 400, 'error_message': error_msg}
        log_msg = format_log_message('ERROR', error_msg, extra=extra_log)
        logger.error(log_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    key_manager.reset_tried_keys_for_request() # 在每次请求处理开始时重置 tried_keys 集合

    contents, system_instruction = GeminiClient.convert_messages(
        GeminiClient, chat_request.messages)

    retry_attempts = len(key_manager.api_keys) if key_manager.api_keys else 1 # 重试次数等于密钥数量，至少尝试 1 次
    for attempt in range(1, retry_attempts + 1):
        if attempt == 1:
            current_api_key = key_manager.get_available_key() # 每次循环开始都获取新的 key, 栈逻辑在 get_available_key 中处理
        
        if current_api_key is None: # 检查是否获取到 API 密钥
            log_msg_no_key = format_log_message('WARNING', "没有可用的 API 密钥，跳过本次尝试", extra={'request_type': request_type, 'model': chat_request.model, 'status_code': 'N/A'})
            logger.warning(log_msg_no_key)
            break  # 如果没有可用密钥，跳出循环

        extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 'N/A', 'error_message': ''}
        log_msg = format_log_message('INFO', f"第 {attempt}/{retry_attempts} 次尝试 ... 使用密钥: {current_api_key[:8]}...", extra=extra_log)
        logger.info(log_msg)

        gemini_client = GeminiClient(current_api_key, storage=global_image_storage)
        try:
            if chat_request.stream:
                async def stream_generator():
                    try:
                        async for chunk in gemini_client.stream_chat(chat_request, contents, safety_settings_g2 if 'gemini-2.0-flash-exp' in chat_request.model else safety_settings, system_instruction):
                            formatted_chunk = {"id": "chatcmpl-someid", "object": "chat.completion.chunk", "created": 1234567,
                                               "model": chat_request.model, "choices": [{"delta": {"role": "assistant", "content": chunk}, "index": 0, "finish_reason": None}]}
                            yield f"data: {json.dumps(formatted_chunk)}\n\n"
                        yield "data: [DONE]\n\n"

                    except asyncio.CancelledError:
                        extra_log_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '客户端已断开连接'}
                        log_msg = format_log_message('INFO', "客户端连接已中断", extra=extra_log_cancel)
                        logger.info(log_msg)
                    except Exception as e:
                        error_detail = handle_gemini_error(
                            e, current_api_key, key_manager)
                        yield f"data: {json.dumps({'error': {'message': error_detail, 'type': 'gemini_error'}})}\n\n"
                return StreamingResponse(stream_generator(), media_type="text/event-stream")
            else:
                async def run_gemini_completion():
                    try:
                        response_content = await asyncio.to_thread(gemini_client.complete_chat, chat_request, contents, safety_settings_g2 if 'gemini-2.0-flash-exp' in chat_request.model else safety_settings, system_instruction)
                        return response_content
                    except asyncio.CancelledError:
                        extra_log_gemini_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '客户端断开导致API调用取消'}
                        log_msg = format_log_message('INFO', "API调用因客户端断开而取消", extra=extra_log_gemini_cancel)
                        logger.info(log_msg)
                        raise

                async def check_client_disconnect():
                    while True:
                        if await http_request.is_disconnected():
                            extra_log_client_disconnect = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '检测到客户端断开连接'}
                            log_msg = format_log_message('INFO', "客户端连接已中断，正在取消API请求", extra=extra_log_client_disconnect)
                            logger.info(log_msg)
                            return True
                        await asyncio.sleep(0.5)

                gemini_task = asyncio.create_task(run_gemini_completion())
                disconnect_task = asyncio.create_task(check_client_disconnect())

                try:
                    done, pending = await asyncio.wait(
                        [gemini_task, disconnect_task],
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    if disconnect_task in done:
                        gemini_task.cancel()
                        try:
                            await gemini_task
                        except asyncio.CancelledError:
                            extra_log_gemini_task_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': 'API任务已终止'}
                            log_msg = format_log_message('INFO', "API任务已成功取消", extra=extra_log_gemini_task_cancel)
                            logger.info(log_msg)
                        # 直接抛出异常中断循环
                        raise HTTPException(status_code=status.HTTP_408_REQUEST_TIMEOUT, detail="客户端连接已中断")

                    if gemini_task in done:
                        disconnect_task.cancel()
                        try:
                            await disconnect_task
                        except asyncio.CancelledError:
                            pass
                        response_content = gemini_task.result()
                        if response_content.text == "":
                            extra_log_empty_response = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 204}
                            log_msg = format_log_message('INFO', "Gemini API 返回空响应", extra=extra_log_empty_response)
                            logger.info(log_msg)
                            raise HTTPException(status_code=403, detail=msg)
                            # 继续循环 ontinue
                        response = ChatCompletionResponse(id="chatcmpl-someid", object="chat.completion", created=1234567890, model=chat_request.model,
                                                        choices=[{"index": 0, "message": {"role": "assistant", "content": response_content.text}, "finish_reason": "stop"}])
                        extra_log_success = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 200}
                        log_msg = format_log_message('INFO', "请求处理成功", extra=extra_log_success)
                        logger.info(log_msg)
                        return response

                except asyncio.CancelledError:
                    extra_log_request_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message':"请求被取消" }
                    log_msg = format_log_message('INFO', "请求取消", extra=extra_log_request_cancel)
                    logger.info(log_msg)
                    raise

        except HTTPException as e:
            if e.status_code == status.HTTP_408_REQUEST_TIMEOUT:
                extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 
                            'status_code': 408, 'error_message': '客户端连接中断'}
                log_msg = format_log_message('ERROR', "客户端连接中断，终止后续重试", extra=extra_log)
                logger.error(log_msg)
                raise  
            else:
                raise  
        except Exception as e:
            handle_gemini_error(e, current_api_key, key_manager)
            if attempt < retry_attempts: 
                switch_api_key() 
                continue

    msg = "所有API密钥均失败,请稍后重试"
    extra_log_all_fail = {'key': "ALL", 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': msg}
    log_msg = format_log_message('ERROR', msg, extra=extra_log_all_fail)
    logger.error(log_msg)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest, http_request: Request, _: None = Depends(verify_password)):
    return await process_request(request, http_request, "stream" if request.stream else "non-stream")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_message = translate_error(str(exc))
    extra_log_unhandled_exception = {'status_code': 500, 'error_message': error_message}
    log_msg = format_log_message('ERROR', f"Unhandled exception: {error_message}", extra=extra_log_unhandled_exception)
    logger.error(log_msg)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=ErrorResponse(message=str(exc), type="internal_error").dict())


# 处理内存图片访问的路由
@app.get("/memory-images/{filename}")
async def get_memory_image(filename: str):
    # 使用全局图片存储实例
    storage = global_image_storage
    # 检查是否是内存存储实例
    if hasattr(storage, 'get_image'):
        # 从内存中获取图片数据
        base64_data, mime_type = storage.get_image(filename)
        # 检查图片数据是否存在
        if base64_data is None:
            raise HTTPException(status_code=404, detail="图片不存在")
        
        # 解码图片数据
        image_data = base64.b64decode(base64_data)
        if image_data:
            # 返回图片数据
            return StreamingResponse(io.BytesIO(image_data), media_type=mime_type)
    
    # 如果图片不存在或不是内存存储，返回404错误
    raise HTTPException(status_code=404, detail="图片不存在")


@app.get("/", response_class=HTMLResponse)
async def root():
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Gemini API 代理服务</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
                line-height: 1.6;
            }}
            .title-container {{
                display: flex;
                justify-content: center;
                align-items: center;
                position: relative;
                margin-bottom: 30px;
            }}
            h1 {{
                color: #333;
                text-align: center;
                margin: 0;
            }}
            .settings-btn {{
                position: absolute;
                right: 0;
                cursor: pointer;
                width: 24px;
                height: 24px;
            }}
            .info-box {{
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 20px;
                margin-bottom: 20px;
                position: relative;
            }}
            .status {{
                color: #28a745;
                font-weight: bold;
            }}
            .version {{
                position: absolute;
                bottom: 0px;
                right: 10px;
                color: #ccc;
                font-size: 0.9em; 
            }}
        </style>
    </head>
    <body>
        <div class="title-container">
            <h1>🤖 Gemini API 代理服务</h1>
            <svg class="settings-btn" onclick="goToAdmin()" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19.8293 10.4291C19.8293 10.3532 19.8369 10.2773 19.8521 10.2014L21.6993 8.7225C21.8833 8.57462 21.9355 8.31383 21.8326 8.10707L20.0479 4.99304C19.945 3.78628 19.6866 4.73521 19.5837 4.52845L17.6528 5.24314C17.156 4.88936 16.6173 4.59352 16.0465 4.36762L15.7663 2.28538C15.7343 2.05203 15.5275 1.875 15.2861 1.875H11.7142C11.4728 1.875 11.2659 2.05203 11.234 2.28538L10.9538 4.36762C10.383 4.59352 9.84428 4.88936 9.34753 5.24314L7.41658 4.52845C7.31373 4.73521 7.05528 3.78628 6.95243 4.99304L5.16774 8.10707C5.06489 8.31383 5.11704 8.57462 5.30102 8.7225L7.14823 10.2014C7.16343 10.2773 7.171 10.3532 7.171 10.4291C7.171 10.505 7.16343 10.5809 7.14823 10.6568L5.30102 12.1357C5.11704 12.2836 5.06489 12.5444 5.16774 12.7511L6.95243 15.8652C7.05528 16.0719 7.31373 15.123 7.41658 15.3298L9.34753 14.6151C9.84428 14.9689 10.383 15.2647 10.9538 15.4906L11.234 17.5728C11.2659 17.8062 11.4728 17.9832 11.7142 17.9832H15.2861C15.5275 17.9832 15.7343 17.8062 15.7663 17.5728L16.0465 15.4906C16.6173 15.2647 17.156 14.9689 17.6528 14.6151L19.5837 15.3298C19.6866 15.123 19.945 16.0719 20.0479 15.8652L21.8326 12.7511C21.9355 12.5444 21.8833 12.2836 21.6993 12.1357L19.8521 10.6568C19.8369 10.5809 19.8293 10.505 19.8293 10.4291ZM13.5001 13.125C11.827 13.125 10.4546 11.7526 10.4546 10.0795C10.4546 8.40641 11.827 7.03397 13.5001 7.03397C15.1732 7.03397 16.5456 8.40641 16.5456 10.0795C16.5456 11.7526 15.1732 13.125 13.5001 13.125Z"></path>
            </svg>
        </div>
        
        <div class="info-box">
            <h2>🟢 运行状态</h2>
            <p class="status">服务运行中</p>
            <p>可用API密钥数量: {len(key_manager.api_keys)}</p>
            <p>可用模型数量: {len(GeminiClient.AVAILABLE_MODELS)}</p>
        </div>

        <div class="info-box">
            <h2>⚙️ 环境配置</h2>
            <p>每分钟请求限制: {MAX_REQUESTS_PER_MINUTE}</p>
            <p>每IP每日请求限制: {MAX_REQUESTS_PER_DAY_PER_IP}</p>
            <p>最大重试次数: {len(key_manager.api_keys)}</p>
            <p class="version">v{VERSION}</p>
        </div>
    </body>
    <script>
        function goToAdmin() {{
            const password = prompt("请输入管理员密码:", "");
            if (password === null) {{
                return;
            }}

            fetch('/admin/login', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json'
                }},
                body: JSON.stringify({{ password: password }})
            }})
            .then(response => {{
                if (!response.ok) {{
                    throw new Error('密码错误或服务器异常');
                }}
                return response.json();
            }})
            .then(data => {{
                sessionStorage.setItem('admin-token', data.access_token);
                window.location.href = '/admin';
            }})
            .catch(error => {{
                alert(error.message);
            }});
        }}
    </script>
    </html>
    """.replace("{{PASSWORD}}", PASSWORD)
    return HTMLResponse(content=html_content)

@app.get("/admin", response_class=FileResponse)
async def admin_page(_: None = Depends(verify_password)):
    return FileResponse("app/templates/admin.html")

@app.get("/admin/env")
async def get_env_vars(_: None = Depends(verify_password)):
    env_vars_config = {
        "API与访问控制": {
            "GEMINI_API_KEYS": {"label": "Gemini API 密钥", "value": os.environ.get("GEMINI_API_KEYS", ""), "type": "password", "description": "您的Gemini API密钥，多个请用逗号隔开。"},
            "MAX_REQUESTS_PER_MINUTE": {"label": "每分钟最大请求数", "value": os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"), "description": "单个IP每分钟允许的最大请求次数。"},
            "MAX_REQUESTS_PER_DAY_PER_IP": {"label": "单IP每日最大请求数", "value": os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"), "description": "单个IP每天允许的最大请求次数。"},
            "WHITELIST_IPS": {"label": "IP白名单", "value": os.environ.get("WHITELIST_IPS", ""), "description": "允许直接访问的IP地址，多个请用逗号隔开。"},
            "PROXY_URL": {"label": "代理URL", "value": os.environ.get("PROXY_URL", ""), "description": "用于访问Gemini API的HTTP/HTTPS代理地址。"},
        },
        "图片处理与存储": {
            "HISTORY_IMAGE_SUBMIT_TYPE": {
                "label": "历史图片提交类型",
                "value": os.environ.get("HISTORY_IMAGE_SUBMIT_TYPE", "last"),
                "type": "radio",
                "options": [
                    {"value": "last", "description": "只提交最近消息中的图片（推荐）"},
                    {"value": "all", "description": "提交上下文所有图片"}
                ],
                "description": "控制在生成图片时如何处理历史对话中的图片。"
            },
            "IMAGE_STORAGE_TYPE": {
                "label": "图片存储类型",
                "value": os.environ.get("IMAGE_STORAGE_TYPE", "local"),
                "type": "radio",
                "options": [
                    {"value": "local", "description": "存储在服务器本地磁盘"},
                    {"value": "memory", "description": "存储在内存中（重启后丢失）"},
                    {"value": "qiniu", "description": "存储在七牛云Kodo"},
                    {"value": "tencent", "description": "存储在腾讯云COS"}
                ],
                "description": "选择生成的图片的存储方式。"
            },
            "HOST_URL": {"label": "主机URL", "value": os.environ.get("HOST_URL", ""), "description": "当前服务的公开访问地址，用于生成图片URL。"},
            "XAI_RESPONSE_FORMAT": {
                "label": "X-AI响应格式",
                "value": os.environ.get("XAI_RESPONSE_FORMAT", "url"),
                "type": "radio",
                "options": [
                    {"value": "url", "description": "返回X-AI官方图片URL"},
                    {"value": "b64_json", "description": "返回base64编码的图片并按上述存储类型处理"}
                ],
                "description": "设置X-AI图片生成接口的返回格式。"
            },
        },
        "本地存储设置": {
            "IMAGE_STORAGE_DIR": {"label": "图片存储目录", "value": os.environ.get("IMAGE_STORAGE_DIR", "app/images"), "description": "当存储类型为local时，图片保存的目录。"},
            "MEMORY_MAX_IMAGE_NUMBER": {"label": "内存中最大图片数", "value": os.environ.get("MEMORY_MAX_IMAGE_NUMBER", "1000"), "description": "当存储类型为memory时，内存中保留的最大图片数量。"},
            "LOCAL_MAX_IMAGE_NUMBER": {"label": "本地最大图片数", "value": os.environ.get("LOCAL_MAX_IMAGE_NUMBER", "1000"), "description": "当存储类型为local时，本地保留的最大图片数量。"},
            "LOCAL_MAX_IMAGE_SIZE_MB": {"label": "本地最大图片大小(MB)", "value": os.environ.get("LOCAL_MAX_IMAGE_SIZE_MB", "1000"), "description": "当存储类型为local时，本地图片文件夹的最大体积。"},
            "LOCAL_CLEAN_INTERVAL_SECONDS": {"label": "本地清理间隔(秒)", "value": os.environ.get("LOCAL_CLEAN_INTERVAL_SECONDS", "3600"), "description": "当存储类型为local时，自动清理任务的运行间隔。"},
        },
        "腾讯云COS设置": {
            "TENCENT_SECRET_ID": {"label": "腾讯云Secret ID", "value": os.environ.get("TENCENT_SECRET_ID", ""), "type": "password", "description": "腾讯云API密钥ID。"},
            "TENCENT_SECRET_KEY": {"label": "腾讯云Secret Key", "value": os.environ.get("TENCENT_SECRET_KEY", ""), "type": "password", "description": "腾讯云API密钥Key。"},
            "TENCENT_REGION": {"label": "腾讯云区域", "value": os.environ.get("TENCENT_REGION", ""), "description": "腾讯云COS存储桶所在的区域。"},
            "TENCENT_BUCKET": {"label": "腾讯云存储桶", "value": os.environ.get("TENCENT_BUCKET", ""), "description": "用于存储图片的腾讯云COS存储桶名称。"},
            "TENCENT_DOMAIN": {"label": "腾讯云域名", "value": os.environ.get("TENCENT_DOMAIN", ""), "description": "该存储桶对应的访问域名。"},
        },
        "七牛云Kodo设置": {
            "QINIU_ACCESS_KEY": {"label": "七牛云Access Key", "value": os.environ.get("QINIU_ACCESS_KEY", ""), "type": "password", "description": "七牛云API访问密钥(AK)。"},
            "QINIU_SECRET_KEY": {"label": "七牛云Secret Key", "value": os.environ.get("QINIU_SECRET_KEY", ""), "type": "password", "description": "七牛云API私有密钥(SK)。"},
            "QINIU_BUCKET_NAME": {"label": "七牛云存储空间名", "value": os.environ.get("QINIU_BUCKET_NAME", ""), "description": "用于存储图片的七牛云存储空间名称。"},
            "QINIU_BUCKET_DOMAIN": {"label": "七牛云域名", "value": os.environ.get("QINIU_BUCKET_DOMAIN", ""), "description": "该存储空间对应的访问域名。"},
        }
    }
    return JSONResponse(content=env_vars_config)

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

@app.post("/admin/login")
async def login_for_access_token(request: Request):
    data = await request.json()
    password = data.get("password")
    if password != PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": "admin"}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

async def reload_config():
    global MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP, WHITELIST_IPS, authorized_ips, global_image_storage, key_manager

    MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"))
    MAX_REQUESTS_PER_DAY_PER_IP = int(os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"))
    WHITELIST_IPS = os.environ.get("WHITELIST_IPS", "").split(",")
    authorized_ips = set(ip.strip() for ip in WHITELIST_IPS if ip.strip())
    
    # 重新初始化 APIKeyManager
    new_api_keys = os.environ.get("GEMINI_API_KEYS", "")
    if new_api_keys != ",".join(key_manager.api_keys):
        key_manager = APIKeyManager()
        # 可以在这里添加重新检查 key 有效性的逻辑
        # 调用新的函数来处理密钥和模型的重载
        await reload_keys()
    # 重新初始化图片存储
    global_image_storage = get_image_storage()
    log_msg = format_log_message('INFO', "配置已重新加载。")
    logger.info(log_msg)


@app.post("/admin/update")
async def update_env_vars(request: Request, _: None = Depends(verify_password)):
    data = await request.json()
    password = data.pop("password", None)

    if password != PASSWORD:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "密码错误"})

    for key, value in data.items():
        os.environ[key] = value
    
    await reload_config()
    
    return JSONResponse(content={"message": "设置已更新并立即生效。"})
# API 映射管理接口
@app.get("/admin/api_mappings", dependencies=[Depends(verify_password)])
async def get_api_mappings_endpoint():
    return JSONResponse(content=get_api_mappings())

@app.post("/admin/api_mappings", dependencies=[Depends(verify_password)])
async def create_api_mapping(payload: dict = Body(...)):
    mappings = get_api_mappings()
    prefix = payload.get("prefix")
    target_url = payload.get("target_url")
    if not prefix or not target_url:
        raise HTTPException(status_code=400, detail="前缀和目标URL不能为空")
    if prefix in mappings:
        raise HTTPException(status_code=400, detail="此前缀已存在")
    mappings[prefix] = target_url
    save_api_mappings()
    return JSONResponse(content={"message": "API映射已创建"}, status_code=201)

@app.put("/admin/api_mappings", dependencies=[Depends(verify_password)])
async def update_api_mapping(payload: dict = Body(...)):
    mappings = get_api_mappings()
    old_prefix = payload.get("old_prefix")
    new_prefix = payload.get("new_prefix")
    target_url = payload.get("target_url")

    if not old_prefix or not new_prefix or not target_url:
        raise HTTPException(status_code=400, detail="请求参数不完整")

    if old_prefix not in mappings:
        raise HTTPException(status_code=404, detail=f"未找到旧前缀: {old_prefix}")

    # 如果前缀被修改，且新前缀已存在
    if old_prefix != new_prefix and new_prefix in mappings:
        raise HTTPException(status_code=400, detail=f"新前缀 {new_prefix} 已存在")

    # 先删除旧的
    del mappings[old_prefix]
    # 添加新的
    mappings[new_prefix] = target_url
    
    save_api_mappings()
    return JSONResponse(content={"message": "API映射已成功更新"})

@app.delete("/admin/api_mappings/{prefix:path}", dependencies=[Depends(verify_password)])
async def delete_api_mapping(prefix: str):
    mappings = get_api_mappings()
    original_prefix = "/" + prefix
    if original_prefix not in mappings:
        raise HTTPException(status_code=404, detail=f"未找到此前缀: {original_prefix}")
    del mappings[original_prefix]
    save_api_mappings()
    return JSONResponse(content={"message": "API映射已删除"})

@app.post("/admin/check_gemini_key", dependencies=[Depends(verify_password)])
async def check_gemini_key(payload: dict = Body(...)):
    api_key = payload.get("key")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")
    
    try:
        is_valid = await test_api_key(api_key)
        if is_valid:
            return JSONResponse(content={"valid": True, "message": "API 密钥有效"})
        else:
            # 即使密钥无效，也返回200，但在响应体中指明状态
            return JSONResponse(content={"valid": False, "message": "API 密钥无效或已过期"})
    except Exception as e:
        # 发生异常时返回500
        logger.error(f"检查密钥时发生未知错误: {e}")
        return JSONResponse(status_code=500, content={"valid": False, "message": f"检查密钥时发生内部错误: {str(e)}"})

@app.get("/admin/images", dependencies=[Depends(verify_password)])
async def list_images(storage_type: str = 'local', page: int = 1, page_size: int = 10):
    try:
        if storage_type == 'memory' and isinstance(global_image_storage, MemoryImageStorage):
            storage = global_image_storage
        else:
            storage = get_image_storage(storage_type)
        result = storage.list_images(page=page, page_size=page_size)
        return result
    except Exception as e:
        logger.error(f"获取图片列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/admin/images", dependencies=[Depends(verify_password)])
async def delete_images(storage_type: str, filenames: List[str] = Body(...)):
    try:
        if storage_type == 'memory' and isinstance(global_image_storage, MemoryImageStorage):
            storage = global_image_storage
        else:
            storage = get_image_storage(storage_type)
        success_count = 0
        failed_files = []
        for filename in filenames:
            if storage.delete_image(filename):
                success_count += 1
            else:
                failed_files.append(filename)
        
        if failed_files:
            return {"message": f"成功删除 {success_count} 张图片，{len(failed_files)} 张失败: {', '.join(failed_files)}", "success": False}
        
        return {"message": f"成功删除 {success_count} 张图片", "success": True}
    except Exception as e:
        logger.error(f"批量删除图片失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/storage_details", dependencies=[Depends(verify_password)])
async def get_storage_details(storage_type: str = 'local'):
    try:
        if storage_type == 'memory' and isinstance(global_image_storage, MemoryImageStorage):
            storage = global_image_storage
        else:
            storage = get_image_storage(storage_type)
        if hasattr(storage, 'get_storage_details'):
            details = storage.get_storage_details()
            return JSONResponse(content=details)
        else:
            raise HTTPException(status_code=400, detail="该存储类型不支持获取存储详情")
    except Exception as e:
        logger.error(f"获取存储详情时发生错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# --- 路由注册 ---
from .proxy import proxy_router
from .static_proxy import static_proxy_router

# 注册静态文件代理路由
app.include_router(static_proxy_router)

# 在所有特定路由定义完成后，最后包含反向代理路由器
app.include_router(proxy_router)
