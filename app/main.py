from fastapi import FastAPI, HTTPException, Request, Depends, status, Body, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from .models import AccessKey, AccessKeyCreate, ChatCompletionRequest, ChatCompletionResponse, ErrorResponse, ModelList
from .gemini import GeminiClient, ResponseWrapper
from .utils import handle_gemini_error, protect_from_abuse, APIKeyManager, test_api_key, format_log_message, generate_random_alphanumeric, get_client_ip,log_records,get_log_new,set_log_new,download_image_to_base64, GeminiServiceUnavailableError


import os
import json
import asyncio
import time
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许访问的源
    allow_credentials=True,  # 支持 cookie
    allow_methods=["*"],  # 允许所有方法
    allow_headers=["*"],  # 允许所有头部
)
templates = Jinja2Templates(directory="app/templates")

from .config_manager import (
    load_api_mappings, save_api_mappings, get_api_mappings,
    load_access_keys, save_access_keys, get_access_keys, access_keys_lock,
    load_gemini_api_keys, save_gemini_api_keys, get_gemini_api_keys,
    schedule_daily_reset
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/images", StaticFiles(directory="app/images"), name="images")

# 导入图片存储模块
from .image_storage import get_image_storage, ImageStorage, MemoryImageStorage, LocalImageStorage

# 创建全局图片存储实例
global_image_storage = get_image_storage()

# IP授权池
WHITELIST_IPS = os.environ.get("WHITELIST_IPS", "").split(",")
authorized_ips = set(ip.strip() for ip in WHITELIST_IPS if ip.strip())

# IP黑名单
BLACKLIST_IPS = os.environ.get("BLACKLIST_IPS", "").split(",")
blacklisted_ips = set(ip.strip() for ip in BLACKLIST_IPS if ip.strip())

PASSWORD = os.environ.get("PASSWORD", "123")
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"))
MAX_REQUESTS_PER_DAY_PER_IP = int(
    os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"))
# MAX_RETRIES = int(os.environ.get('MaxRetries', '3').strip() or '3')
RETRY_DELAY = 1
MAX_RETRY_DELAY = 16
VERSION = os.environ.get('VERSION', "")

#Gemini API返回空响应时的最大重试次数
GEMINI_EMPTY_RESPONSE_RETRIES = int(os.environ.get('GEMINI_EMPTY_RESPONSE_RETRIES', '3'))

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

key_manager = None
current_api_key = None


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
    for key in get_gemini_api_keys():
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
    load_access_keys()
    load_gemini_api_keys()
    global key_manager, current_api_key
    key_manager = APIKeyManager(get_gemini_api_keys()) # 实例化 APIKeyManager，栈会在 __init__ 中初始化
    current_api_key = key_manager.get_available_key()
    schedule_daily_reset()
    log_msg = format_log_message('INFO', "Starting Gemini API proxy...")
    logger.info(log_msg)
    await reload_keys()


def update_access_key_usage(token: str):
    if token.startswith("sk-"):
        access_keys = get_access_keys()
        key_data = access_keys.get(token)
        if key_data:
            key = AccessKey(**key_data)
            if key.is_active and key.usage_limit is not None and key.usage_limit > 0:
                with access_keys_lock:
                    # Re-fetch to ensure atomicity
                    key_data = access_keys.get(token)
                    if key_data:
                        key = AccessKey(**key_data)
                        key.usage_count += 1
                        access_keys[token] = key.dict()
                        save_access_keys()


# 专门用于Admin后台的JWT Token验证
async def verify_jwt_token(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials", headers={"WWW-Authenticate": "Bearer"})
        return True # Token有效
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

# 校验密码逻辑
async def verify_password(request: Request):
    auth_header = request.headers.get("Authorization")
    client_ip = get_client_ip(request)

    # IP黑名单检查
    if client_ip in blacklisted_ips:
        log_msg = format_log_message('WARNING', f"IP {client_ip} is in the blacklist, access denied.", extra={'ip': client_ip, 'reason': 'in_blacklist'})
        logger.warning(log_msg)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your IP address is blacklisted.")

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

        # 访问密钥验证
        if token.startswith("sk-"):
            access_keys = get_access_keys()
            key_data = access_keys.get(token)
            if key_data:
                key = AccessKey(**key_data)
                if key.is_active:
                    if key.expires_at and datetime.now().timestamp() > key.expires_at:
                        # 更新有效状态
                        with access_keys_lock:
                            key.is_active = False
                            access_keys[token] = key.dict()
                            save_access_keys()
                        log_msg = format_log_message('INFO', f"IP: {client_ip} Access key {token} expired")
                        logger.info(log_msg)
                        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access key expired")
                    if key.usage_limit is not None and key.usage_count >= key.usage_limit:
                        # 更新有效状态
                        with access_keys_lock:
                            key.is_active = False
                            access_keys[token] = key.dict()
                            save_access_keys()
                        log_msg = format_log_message('INFO', f"IP: {client_ip} Access key {token} usage limit exceeded")
                        logger.info(log_msg)
                        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access key usage limit exceeded")
                    return True
                else:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Access key is lose efficacy")

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
        messages = body['messages']
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


async def process_request(chat_request: ChatCompletionRequest, http_request: Request, request_type: Literal['stream', 'non-stream'],token:str = None):
    global current_api_key
    
    client_ip = get_client_ip(http_request)

    protect_from_abuse(
        http_request, MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP)
    # 解析是否是自定义思考模型,不在所有模型列表中,但使其也可以访问
    thinking_model, thinking_budget = GeminiClient._parse_model_name_and_budget(chat_request.model)
    if chat_request.model not in GeminiClient.AVAILABLE_MODELS and thinking_model not in GeminiClient.thinkingModels:
        error_msg = "无效的模型"
        extra_log = {'ip': client_ip, 'request_type': request_type, 'model': chat_request.model, 'status_code': 400, 'error_message': error_msg}
        log_msg = format_log_message('ERROR', error_msg, extra=extra_log)
        logger.error(log_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    key_manager.reset_tried_keys_for_request() # 在每次请求处理开始时重置 tried_keys 集合

    contents, system_instruction = GeminiClient.convert_messages(
        GeminiClient, chat_request.messages)

    retry_attempts = len(key_manager.api_keys) if key_manager.api_keys else 1 # 重试次数等于密钥数量，至少尝试 1 次
    for attempt in range(1, retry_attempts + 1):
        if attempt == 1:
            current_api_key = key_manager.get_available_key() # 每次循环开始都获取新的 key, 栈逻辑在 get_available_key 中处理
        
        if current_api_key is None: # 检查是否获取到 API 密钥
            log_msg_no_key = format_log_message('WARNING', "没有可用的 API 密钥，跳过本次尝试", extra={'ip': client_ip, 'request_type': request_type, 'model': chat_request.model, 'status_code': 'N/A'})
            logger.warning(log_msg_no_key)
            break  # 如果没有可用密钥，跳出循环
        extra_log = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': '200', 'error_message': ''}
        request_token_count = 0
        for message in chat_request.messages:
            if isinstance(message.content, str):
                request_token_count += len(message.content)
            elif isinstance(message.content, list):
                request_token_count += sum(len(json.dumps(p)) for p in message.content)
        log_message_text = f"第 [{attempt}/{retry_attempts}] 次尝试请求中, 输入token: {request_token_count}"
        if token and token.startswith("sk-"):
            log_message_text += f" 使用密钥: {token[:10]}..."
        log_msg = format_log_message('INFO', log_message_text, extra=extra_log)
        logger.info(log_msg)
        start_time = time.monotonic()

        gemini_client = GeminiClient(current_api_key, storage=global_image_storage)
        try:
            if chat_request.stream:
                async def stream_generator(client, request, contents, safety_settings, system_instruction):
                    try:
                        for emptyAttempt in range(1,GEMINI_EMPTY_RESPONSE_RETRIES+1):
                            response_text = ""
                            async for chunk in client.stream_chat(request, contents, safety_settings, system_instruction):
                                response_text += chunk
                                formatted_chunk = {"id": "chatcmpl-someid", "object": "chat.completion.chunk", "created": 1234567,
                                                "model": request.model, "choices": [{"delta": {"role": "assistant", "content": chunk}, "index": 0, "finish_reason": None}]}
                                yield f"data: {json.dumps(formatted_chunk)}\n\n"
                            response_text_len = len(response_text)
                            if response_text_len == 0 and emptyAttempt < GEMINI_EMPTY_RESPONSE_RETRIES+1:
                                switch_api_key()
                                client = GeminiClient(current_api_key, storage=global_image_storage)
                            else:
                                break
                        duration = time.monotonic() - start_time
                        extra_log_success_stream = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': request.model, 'status_code': 200, 'duration_ms': round(duration * 1000)}
                        log_message_text_stream = f"请求成功，耗时: {duration:.2f}s, 输出token: {response_text_len}"
                        if token and token.startswith("sk-"):
                            log_message_text_stream += f" 使用密钥: {token[:10]}..."
                        log_msg_success_stream = format_log_message('INFO', log_message_text_stream, extra=extra_log_success_stream)
                        logger.info(log_msg_success_stream)

                        yield "data: [DONE]\n\n"

                    except asyncio.CancelledError:
                        extra_log_cancel = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': request.model, 'error_message': '客户端已断开连接'}
                        log_msg = format_log_message('INFO', "客户端连接已中断", extra=extra_log_cancel)
                        logger.info(log_msg)
                    except Exception as e:
                        error_detail = handle_gemini_error(
                            e, current_api_key, key_manager, client_ip)
                        yield f"data: {json.dumps({'error': {'message': error_detail, 'type': 'gemini_error'}})}\n\n"
                return StreamingResponse(stream_generator(gemini_client, chat_request, contents, safety_settings_g2 if 'gemini-2.0-flash-exp' in chat_request.model else safety_settings, system_instruction), media_type="text/event-stream")
            else:
                async def run_gemini_completion():
                    try:
                        response_content = await asyncio.to_thread(gemini_client.complete_chat, chat_request, contents, safety_settings_g2 if 'gemini-2.0-flash-exp' in chat_request.model else safety_settings, system_instruction)
                        return response_content
                    except asyncio.CancelledError:
                        extra_log_gemini_cancel = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '客户端断开导致API调用取消'}
                        log_msg = format_log_message('INFO', "API调用因客户端断开而取消", extra=extra_log_gemini_cancel)
                        logger.info(log_msg)
                        raise

                async def check_client_disconnect():
                    while True:
                        if await http_request.is_disconnected():
                            extra_log_client_disconnect = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '检测到客户端断开连接'}
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
                            extra_log_gemini_task_cancel = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': 'API任务已终止'}
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
                        response_text_len = len(response_content.text)
                        extra_log = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 200}
                        if response_text_len == 0 and attempt < GEMINI_EMPTY_RESPONSE_RETRIES+1:
                            raise GeminiServiceUnavailableError("Gemini返回内容为空",504,extra_log)
                        response = ChatCompletionResponse(id="chatcmpl-someid", object="chat.completion", created=1234567890, model=chat_request.model,
                                                        choices=[{"index": 0, "message": {"role": "assistant", "content": response_content.text}, "finish_reason": "stop"}])
                        duration = time.monotonic() - start_time
                        extra_log['duration_ms'] = round(duration * 1000)
                        log_message_text_duration = f"请求成功，耗时: {duration:.2f}s, 输出token: {response_text_len}"
                        if token and token.startswith("sk-"):
                            log_message_text_duration += f" 使用密钥: {token[:10]}..."
                        log_msg_duration = format_log_message('INFO', log_message_text_duration, extra=extra_log)
                        logger.info(log_msg_duration)
                        
                        return response

                except asyncio.CancelledError:
                    extra_log_request_cancel = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message':"请求被取消" }
                    log_msg = format_log_message('INFO', "请求取消", extra=extra_log_request_cancel)
                    logger.info(log_msg)
                    raise
        except GeminiServiceUnavailableError as e:
            if e.status_code == 504:
                handle_gemini_error(e, current_api_key, key_manager, client_ip)
                if attempt < GEMINI_EMPTY_RESPONSE_RETRIES+1:
                    switch_api_key()
                    continue
                raise
        except HTTPException as e:
            if e.status_code == status.HTTP_408_REQUEST_TIMEOUT:
                extra_log = {'ip': client_ip, 'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model,
                            'status_code': 408, 'error_message': '客户端连接中断'}
                log_msg = format_log_message('ERROR', "客户端连接中断，终止后续重试", extra=extra_log)
                logger.error(log_msg)
                raise  
            else:
                raise  
        except Exception as e:
            handle_gemini_error(e, current_api_key, key_manager, client_ip)
            if attempt < retry_attempts:
                switch_api_key()
                continue

    msg = "所有API密钥均失败,请稍后重试"
    extra_log_all_fail = {'ip': client_ip, 'key': "ALL", 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': msg}
    log_msg = format_log_message('ERROR', msg, extra=extra_log_all_fail)
    logger.error(log_msg)
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

@app.get("/v1/models", response_model=ModelList)
def list_models(request: Request, _: None = Depends(verify_password)):
    client_ip = get_client_ip(request)
    log_msg = format_log_message('INFO', "Received request to list models", extra={'ip': client_ip, 'request_type': 'list_models', 'status_code': 200})
    logger.info(log_msg)
    return ModelList(data=[{"id": model, "object": "model", "created": 1678888888, "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS])

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest, http_request: Request, _: None = Depends(verify_password)):
    auth_header = http_request.headers.get("Authorization")
    token = None
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        update_access_key_usage(token)
    return await process_request(request, http_request, "stream" if request.stream else "non-stream",token)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_message = translate_error(str(exc))
    extra_log_unhandled_exception = {'status_code': 500, 'error_message': error_message}
    log_msg = format_log_message('ERROR', f"Unhandled exception: {error_message}", extra=extra_log_unhandled_exception)
    logger.error(log_msg)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=ErrorResponse(message=str(exc), type="internal_error").dict())


# 处理内存文件访问的路由
@app.get("/memory-media/{filename}")
async def get_memory_media(filename: str):
    # 使用全局图片存储实例
    storage = global_image_storage
    # 检查是否是内存存储实例
    if hasattr(storage, 'get_image'): # The method in storage is still called get_image
        # 从内存中获取文件数据
        base64_data, mime_type = storage.get_image(filename)
        # 检查文件数据是否存在
        if base64_data is None:
            raise HTTPException(status_code=404, detail="文件不存在")
        
        # 解码文件数据
        file_data = base64.b64decode(base64_data)
        if file_data:
            # 返回文件数据
            return StreamingResponse(io.BytesIO(file_data), media_type=mime_type)
    
    # 如果文件不存在或不是内存存储，返回404错误
    raise HTTPException(status_code=404, detail="文件不存在")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "len": len,
            "key_manager": key_manager,
            "GeminiClient": GeminiClient,
            "MAX_REQUESTS_PER_MINUTE": MAX_REQUESTS_PER_MINUTE,
            "MAX_REQUESTS_PER_DAY_PER_IP": MAX_REQUESTS_PER_DAY_PER_IP,
            "VERSION": VERSION,
        },
    )

@app.get("/admin", response_class=FileResponse)
async def admin_page():
    return FileResponse("app/templates/admin.html")

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    return templates.TemplateResponse("logs.html", {"request": request})

@app.get("/admin/env")
async def get_env_vars(_: None = Depends(verify_jwt_token)):
    env_vars_config = {
        "API与访问控制": {
            "GEMINI_API_KEYS": {"label": "Gemini API 密钥", "value": os.environ.get("GEMINI_API_KEYS", ""), "type": "password", "description": "您的Gemini API密钥，多个请用逗号隔开。"},
            "MAX_REQUESTS_PER_MINUTE": {"label": "每分钟最大请求数", "value": os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"), "description": "单个IP每分钟允许的最大请求次数。"},
            "MAX_REQUESTS_PER_DAY_PER_IP": {"label": "单IP每日最大请求数", "value": os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"), "description": "单个IP每天允许的最大请求次数。"},
            "EXTRA_MODELS": {"label": "自定义模型列表", "value": os.environ.get("EXTRA_MODELS", ""), "description": "自定义模型列表，多个请用逗号隔开。"},
            "WHITELIST_IPS": {"label": "IP白名单", "value": os.environ.get("WHITELIST_IPS", ""), "description": "允许直接访问的IP地址，多个请用逗号隔开。"},
            "BLACKLIST_IPS": {"label": "IP黑名单", "value": os.environ.get("BLACKLIST_IPS", ""), "description": "禁止访问的IP地址，多个请用逗号隔开。"},
            "GEMINI_EMPTY_RESPONSE_RETRIES": {"label": "Gemini空响应重试次数", "value": os.environ.get("GEMINI_EMPTY_RESPONSE_RETRIES", "3"), "description": "Gemini API返回空响应时的最大重试次数。"},
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
    client_ip = get_client_ip(request)
    if password != PASSWORD:
        log_msg = format_log_message('WARNING', "管理员登录失败: 密码错误", extra={'ip': client_ip, 'request_type': 'admin_login'})
        logger.warning(log_msg)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="密码错误!",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": "admin"}, expires_delta=access_token_expires
    )
    log_msg = format_log_message('INFO', "管理员登录成功", extra={'ip': client_ip, 'request_type': 'admin_login'})
    logger.info(log_msg)
    return {"access_token": access_token, "token_type": "bearer"}

async def reload_config():
    global MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP, WHITELIST_IPS, authorized_ips, BLACKLIST_IPS, blacklisted_ips, GEMINI_EMPTY_RESPONSE_RETRIES, global_image_storage, key_manager

    MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"))
    MAX_REQUESTS_PER_DAY_PER_IP = int(os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"))
    WHITELIST_IPS = os.environ.get("WHITELIST_IPS", "").split(",")
    authorized_ips = set(ip.strip() for ip in WHITELIST_IPS if ip.strip())
    BLACKLIST_IPS = os.environ.get("BLACKLIST_IPS", "").split(",")
    blacklisted_ips = set(ip.strip() for ip in BLACKLIST_IPS if ip.strip())
    GEMINI_EMPTY_RESPONSE_RETRIES = int(os.environ.get('GEMINI_EMPTY_RESPONSE_RETRIES', '3'))
    # 重新初始化代理URL
    GeminiClient.BASE_URL = os.environ.get("PROXY_URL") or "https://generativelanguage.googleapis.com"
    # 重新初始化自定义模型列表
    new_extra_models = os.environ.get("EXTRA_MODELS", "")
    if new_extra_models != ",".join(GeminiClient.EXTRA_MODELS):
        # 重新初始化自定义模型列表
        GeminiClient.EXTRA_MODELS = [model for model in new_extra_models.split(",") if model]
        # 重新初始化可用模型列表
        GeminiClient.AVAILABLE_MODELS = GeminiClient.merge_model()
    # 重新初始化 APIKeyManager
    new_api_keys = os.environ.get("GEMINI_API_KEYS", "")
    if new_api_keys != ",".join(key_manager.api_keys):
        import re
        keys = re.findall(r"AIzaSy[a-zA-Z0-9_-]{33}", new_api_keys)
        get_gemini_api_keys().clear()
        get_gemini_api_keys().extend(keys)
        save_gemini_api_keys()
        key_manager = APIKeyManager(get_gemini_api_keys())
        # 可以在这里添加重新检查 key 有效性的逻辑
        # 调用新的函数来处理密钥和模型的重载
        await reload_keys()
    # 重新初始化图片存储
    global_image_storage = get_image_storage()
    log_msg = format_log_message('INFO', "配置已重新加载。")
    logger.info(log_msg)


@app.post("/admin/update")
async def update_env_vars(request: Request, _: None = Depends(verify_jwt_token)):
    data = await request.json()
    password = data.pop("password", None)

    if password != PASSWORD:
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"message": "密码错误"})

    for key, value in data.items():
        os.environ[key] = value
    
    await reload_config()
    
    client_ip = get_client_ip(request)
    log_msg = format_log_message('INFO', "系统设置已更新", extra={'ip': client_ip, 'request_type': 'admin_update_env'})
    logger.info(log_msg)
    
    return JSONResponse(content={"message": "设置已更新并立即生效。"})
# API 映射管理接口
@app.get("/admin/api_mappings", dependencies=[Depends(verify_jwt_token)])
async def get_api_mappings_endpoint():
    return JSONResponse(content=get_api_mappings())

@app.post("/admin/api_mappings", dependencies=[Depends(verify_jwt_token)])
async def create_api_mapping(request: Request, payload: dict = Body(...)):
    mappings = get_api_mappings()
    prefix = payload.get("prefix")
    target_url = payload.get("target_url")
    if not prefix or not target_url:
        raise HTTPException(status_code=400, detail="前缀和目标URL不能为空")
    if prefix in mappings:
        raise HTTPException(status_code=400, detail="此前缀已存在")
    mappings[prefix] = target_url
    save_api_mappings()
    client_ip = get_client_ip(request)
    log_msg = format_log_message('INFO', f"API映射已创建: {prefix} -> {target_url}", extra={'ip': client_ip, 'request_type': 'admin_create_mapping'})
    logger.info(log_msg)
    return JSONResponse(content={"message": "API映射已创建"}, status_code=201)

@app.put("/admin/api_mappings", dependencies=[Depends(verify_jwt_token)])
async def update_api_mapping(request: Request, payload: dict = Body(...)):
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
    client_ip = get_client_ip(request)
    log_msg = format_log_message('INFO', f"API映射已更新: {old_prefix} -> {new_prefix}", extra={'ip': client_ip, 'request_type': 'admin_update_mapping'})
    logger.info(log_msg)
    return JSONResponse(content={"message": "API映射已成功更新"})

@app.delete("/admin/api_mappings/{prefix:path}", dependencies=[Depends(verify_jwt_token)])
async def delete_api_mapping(request: Request, prefix: str):
    mappings = get_api_mappings()
    original_prefix = "/" + prefix
    if original_prefix not in mappings:
        raise HTTPException(status_code=404, detail=f"未找到此前缀: {original_prefix}")
    del mappings[original_prefix]
    save_api_mappings()
    client_ip = get_client_ip(request)
    log_msg = format_log_message('INFO', f"API映射已删除: {original_prefix}", extra={'ip': client_ip, 'request_type': 'admin_delete_mapping'})
    logger.info(log_msg)
    return JSONResponse(content={"message": "API映射已删除"})

@app.post("/admin/check_gemini_key", dependencies=[Depends(verify_jwt_token)])
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

@app.get("/admin/media", dependencies=[Depends(verify_jwt_token)])
async def list_media(storage_type: str = 'local', page: int = 1, page_size: int = 10):
    try:
        if (storage_type == 'memory' and isinstance(global_image_storage, MemoryImageStorage)) or \
           (storage_type == 'local' and isinstance(global_image_storage, LocalImageStorage)):
            storage = global_image_storage
        else:
            storage = get_image_storage(storage_type)
        
        # The storage method `list_images` returns a dict with an 'images' key.
        # We need to adapt this to return 'media_files' for the frontend.
        result = storage.list_images(page=page, page_size=page_size)
        result['media_files'] = result.pop('images')
        return result

    except Exception as e:
        logger.error(f"获取媒体文件列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/admin/media", dependencies=[Depends(verify_jwt_token)])
async def delete_media(request: Request, storage_type: str, filenames: List[str] = Body(...)):
    try:
        if (storage_type == 'memory' and isinstance(global_image_storage, MemoryImageStorage)) or \
           (storage_type == 'local' and isinstance(global_image_storage, LocalImageStorage)):
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
        
        client_ip = get_client_ip(request)
        log_msg = format_log_message('INFO', f"删除了 {success_count} 个媒体文件", extra={'ip': client_ip, 'request_type': 'admin_delete_media'})
        logger.info(log_msg)

        if failed_files:
            return {"message": f"成功删除 {success_count} 个文件，{len(failed_files)} 个失败: {', '.join(failed_files)}", "success": False}
        
        return {"message": f"成功删除 {success_count} 个文件", "success": True}
    except Exception as e:
        logger.error(f"批量删除文件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/admin/storage_details", dependencies=[Depends(verify_jwt_token)])
async def get_storage_details(storage_type: str = 'local'):
    try:
        if (storage_type == 'memory' and isinstance(global_image_storage, MemoryImageStorage)) or \
           (storage_type == 'local' and isinstance(global_image_storage, LocalImageStorage)):
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


@app.get("/admin/keys", dependencies=[Depends(verify_jwt_token)])
async def get_keys():
    return get_access_keys()

@app.post("/admin/keys", dependencies=[Depends(verify_jwt_token)])
async def create_key(request: Request, key_create: AccessKeyCreate):
    access_keys = get_access_keys()
    new_key_str = "sk-" + generate_random_alphanumeric(64)
    
    while new_key_str in access_keys:
        new_key_str = "sk-" + generate_random_alphanumeric(64)

    if key_create.usage_limit is None:
        key_create.reset_daily = False

    new_key = AccessKey(
        key=new_key_str,
        **key_create.dict()
    )
    
    with access_keys_lock:
        access_keys[new_key.key] = new_key.dict()
        save_access_keys()
    
    client_ip = get_client_ip(request)
    log_msg = format_log_message('INFO', f"访问密钥已创建: {new_key.key[:8]}...", extra={'ip': client_ip, 'request_type': 'admin_create_key'})
    logger.info(log_msg)
    
    return JSONResponse(content={"message": "密钥创建成功"})

@app.put("/admin/keys/{key}", dependencies=[Depends(verify_jwt_token)])
async def update_key(request: Request, key: str, key_update: AccessKey):
    access_keys = get_access_keys()
    if key not in access_keys:
        raise HTTPException(status_code=404, detail="要更新的密钥不存在")

    # Key本身不应改变，但如果前端发送的key与AccessKey对象中的不一致，则以URL中的为准
    key_update.key = key

    if key_update.usage_limit is None:
        key_update.reset_daily = False
    
    # 更新字典
    with access_keys_lock:
        access_keys[key] = key_update.dict()
        save_access_keys()
        
    client_ip = get_client_ip(request)
    log_msg = format_log_message('INFO', f"访问密钥已更新: {key[:8]}...", extra={'ip': client_ip, 'request_type': 'admin_update_key'})
    logger.info(log_msg)
    
    return JSONResponse(content={"message": "密钥更新成功"})

@app.delete("/admin/keys/{key}", dependencies=[Depends(verify_jwt_token)])
async def delete_key(request: Request, key: str):
    access_keys = get_access_keys()
    if key not in access_keys:
        raise HTTPException(status_code=404, detail="密钥不存在")
    with access_keys_lock:
        del access_keys[key]
        save_access_keys()
        
    client_ip = get_client_ip(request)
    log_msg = format_log_message('INFO', f"访问密钥已删除: {key[:8]}...", extra={'ip': client_ip, 'request_type': 'admin_delete_key'})
    logger.info(log_msg)
    
    return JSONResponse(content={"message": "密钥删除成功"})

# --- 路由注册 ---
from .proxy import proxy_router
from .static_proxy import static_proxy_router

# 注册静态文件代理路由
app.include_router(static_proxy_router)

# 在所有特定路由定义完成后，最后包含反向代理路由器
app.include_router(proxy_router)

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket, token: str = None):
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    # 发送所有当前日志
    for log_entry in list(log_records):
        await websocket.send_text(log_entry)
        set_log_new(False)

    try:
        while True:
            # 检查是否有新的日志
            if get_log_new():
                # 发送最新日志
                    await websocket.send_text(log_records[-1])
                    set_log_new(False)
            await asyncio.sleep(0.1)  # 每0.1秒检查一次
    except WebSocketDisconnect:
        print("Client disconnected")
