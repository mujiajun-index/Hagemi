from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from .models import ChatCompletionRequest, ChatCompletionResponse, ErrorResponse, ModelList
from .gemini import GeminiClient, ResponseWrapper
from .utils import handle_gemini_error, protect_from_abuse, APIKeyManager, test_api_key
import os
import json
import asyncio
from typing import Literal
import random
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
import sys


DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
LOG_FORMAT_DEBUG = '%(asctime)s - %(levelname)s - [%(key)s]-%(request_type)s-[%(model)s]-%(status_code)s: %(message)s - %(error_message)s'
LOG_FORMAT_NORMAL = '[%(key)s]-%(request_type)s-[%(model)s]-%(status_code)s: %(message)s'


def format_log_message(level, message, extra=None):
    """格式化日志消息，模拟之前的 logging 格式"""
    log_values = {
        'asctime': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # 模拟 asctime
        'levelname': level, # 日志级别
        'key': extra.get('key', 'N/A') if extra else 'N/A',
        'request_type': extra.get('request_type', 'N/A') if extra else 'N/A',
        'model': extra.get('model', 'N/A') if extra else 'N/A',
        'status_code': extra.get('status_code', 'N/A') if extra else 'N/A',
        'error_message': extra.get('error_message', '') if extra else '' ,
        'message': message
    }
    log_format = LOG_FORMAT_DEBUG if DEBUG else LOG_FORMAT_NORMAL
    return log_format % log_values


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
    print(log_msg)


sys.excepthook = handle_exception

app = FastAPI()

PASSWORD = os.environ.get("PASSWORD", "123")
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"))
MAX_REQUESTS_PER_DAY_PER_IP = int(
    os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"))
MAX_RETRIES = int(os.environ.get('MaxRetries', '3').strip() or '3')
RETRY_DELAY = 1
MAX_RETRY_DELAY = 16
safety_settings = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "BLOCK_NONE"
    },
    {
        "category": 'HARM_CATEGORY_CIVIC_INTEGRITY',
        "threshold": 'BLOCK_NONE'
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
        print(log_msg)
    else:
        log_msg = format_log_message('ERROR', "API key 替换失败，所有API key都已耗尽或被暂时禁用，请重新配置或稍后重试", extra={'key': 'N/A', 'request_type': 'switch_key', 'status_code': 'N/A'})
        print(log_msg)


async def check_keys():
    available_keys = []
    for key in key_manager.api_keys:
        is_valid = await test_api_key(key)
        status_msg = "有效" if is_valid else "无效"
        log_msg = format_log_message('INFO', f"API Key {key[:10]}... {status_msg}.")
        print(log_msg)
        if is_valid:
            available_keys.append(key)
    if not available_keys:
        log_msg = format_log_message('ERROR', "没有可用的 API 密钥！", extra={'key': 'N/A', 'request_type': 'startup', 'status_code': 'N/A'})
        print(log_msg)
    return available_keys


@app.on_event("startup")
async def startup_event():
    log_msg = format_log_message('INFO', "Starting Gemini API proxy...")
    print(log_msg)
    available_keys = await check_keys()
    if available_keys:
        key_manager.api_keys = available_keys
        key_manager._reset_key_stack() # 启动时也确保创建随机栈
        key_manager.show_all_keys()
        log_msg = format_log_message('INFO', f"可用 API 密钥数量：{len(key_manager.api_keys)}")
        print(log_msg)
        if key_manager.api_keys:
            all_models = await GeminiClient.list_available_models(key_manager.api_keys[0])
            GeminiClient.AVAILABLE_MODELS = [model.replace(
                "models/", "") for model in all_models]
            log_msg = format_log_message('INFO', "Available models loaded.")
            print(log_msg)


@app.get("/v1/models", response_model=ModelList)
def list_models():
    log_msg = format_log_message('INFO', "Received request to list models", extra={'request_type': 'list_models', 'status_code': 200})
    print(log_msg)
    return ModelList(data=[{"id": model, "object": "model", "created": 1678888888, "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS])


async def verify_password(request: Request):
    if PASSWORD:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401, detail="Unauthorized: Missing or invalid token")
        token = auth_header.split(" ")[1]
        if token != PASSWORD:
            raise HTTPException(
                status_code=401, detail="Unauthorized: Invalid token")


async def process_request(chat_request: ChatCompletionRequest, http_request: Request, request_type: Literal['stream', 'non-stream']):
    global current_api_key
    protect_from_abuse(
        http_request, MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP)
    if chat_request.model not in GeminiClient.AVAILABLE_MODELS:
        error_msg = "无效的模型"
        extra_log = {'request_type': request_type, 'model': chat_request.model, 'status_code': 400, 'error_message': error_msg}
        log_msg = format_log_message('ERROR', error_msg, extra=extra_log)
        print(log_msg)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)

    key_manager.reset_tried_keys_for_request() # 在每次请求处理开始时重置 tried_keys 集合

    contents, system_instruction = GeminiClient.convert_messages(
        GeminiClient, chat_request.messages)
    for attempt in range(1, len(key_manager.api_keys) + 1 if key_manager.api_keys else MAX_RETRIES + 1): # 尝试次数改为 API 密钥数量, 最多 MAX_RETRIES 次
        extra_log = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model}
        log_msg = format_log_message('INFO', f"第 {attempt}/{len(key_manager.api_keys) if key_manager.api_keys else MAX_RETRIES} 次尝试 ...", extra=extra_log)
        print(log_msg)
        current_api_key = key_manager.get_available_key() # 每次循环都获取新的 key, 栈逻辑在 get_available_key 中处理
        if not current_api_key: # 如果 get_available_key 返回 None, 说明没有可用 key 了，直接跳出循环
            break

        gemini_client = GeminiClient(current_api_key)
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
                        log_msg = format_log_message('INFO', "Client disconnected", extra=extra_log_cancel)
                        print(log_msg)
                    except Exception as e:
                        error_detail = handle_gemini_error(
                            e, current_api_key, key_manager, switch_api_key)
                        log_message = f"API Key failed: {error_detail}"
                        extra_log_error = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': error_detail}
                        log_msg = format_log_message('ERROR', log_message, extra=extra_log_error)
                        print(log_msg)
                        yield f"data: {json.dumps({'error': {'message': error_detail, 'type': 'gemini_error'}})}\n\n"
                        if attempt < (len(key_manager.api_keys) if key_manager.api_keys else MAX_RETRIES): # 流式也根据apikey 数量判断是否切换key
                            switch_api_key() # 这里虽然叫 switch_api_key_func, 但实际上 get_available_key 会处理栈和重新生成
                return StreamingResponse(stream_generator(), media_type="text/event-stream")
            else:
                async def run_gemini_completion():
                    try:
                        response_content = await asyncio.to_thread(gemini_client.complete_chat, chat_request, contents, safety_settings_g2 if 'gemini-2.0-flash-exp' in chat_request.model else safety_settings, system_instruction)
                        return response_content
                    except asyncio.CancelledError:
                        extra_log_gemini_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': 'Gemini API 调用因客户端断开连接而被取消'}
                        log_msg = format_log_message('INFO', "Gemini API call cancelled due to client disconnect", extra=extra_log_gemini_cancel)
                        print(log_msg)
                        raise

                async def check_client_disconnect():
                    while True:
                        if await http_request.is_disconnected():
                            extra_log_client_disconnect = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '在非流式请求期间检测到客户端断开连接。正在取消 Gemini API 调用。'}
                            log_msg = format_log_message('INFO', "Client disconnected during non-streaming request.  Cancelling Gemini API call.", extra=extra_log_client_disconnect)
                            print(log_msg)
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
                            extra_log_gemini_task_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message': '客户端断开连接后，Gemini API 任务已成功取消。'}
                            log_msg = format_log_message('INFO', "Gemini API task successfully cancelled after client disconnect.", extra=extra_log_gemini_task_cancel)
                            print(log_msg)
                            pass
                        raise HTTPException(status_code=status.HTTP_408_REQUEST_TIMEOUT, detail="Client disconnected")

                    if gemini_task in done:
                        disconnect_task.cancel()
                        try:
                            await disconnect_task
                        except asyncio.CancelledError:
                            pass
                        response_content = gemini_task.result()
                        response = ChatCompletionResponse(id="chatcmpl-someid", object="chat.completion", created=1234567890, model=chat_request.model,
                                                        choices=[{"index": 0, "message": {"role": "assistant", "content": response_content.text}, "finish_reason": "stop"}])
                        extra_log_success = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 200}
                        log_msg = format_log_message('INFO', "Request successful", extra=extra_log_success)
                        print(log_msg)
                        return response

                except asyncio.CancelledError:
                    extra_log_request_cancel = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'error_message':"请求被取消" }
                    log_msg = format_log_message('INFO', "Request cancelled", extra=extra_log_request_cancel)
                    print(log_msg)
                    raise


        except requests.exceptions.RequestException as e:
            error_detail = handle_gemini_error(
                e, current_api_key, key_manager, switch_api_key)
            extra_log_request_exception = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': error_detail}
            log_msg = format_log_message('ERROR', f"{error_detail}", extra=extra_log_request_exception)
            print(log_msg)
            if attempt < (len(key_manager.api_keys) if key_manager.api_keys else MAX_RETRIES): # 根据apikey 数量判断是否切换key
                switch_api_key() # 这里虽然叫 switch_api_key_func, 但实际上 get_available_key 会处理栈和重新生成
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{len(key_manager.api_keys) if key_manager.api_keys else MAX_RETRIES} 次尝试后仍然失败，请修改预设或输入") # 错误信息里的重试次数也动态修改
        except Exception as e:
            error_detail = handle_gemini_error(
                e, current_api_key, key_manager, switch_api_key)
            extra_log_exception = {'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': error_detail}
            log_msg = format_log_message('ERROR', f"{error_detail}", extra=extra_log_exception)
            print(log_msg)
            if attempt < (len(key_manager.api_keys)  if key_manager.api_keys else MAX_RETRIES): # 根据apikey 数量判断是否切换key
                switch_api_key() # 这里虽然叫 switch_api_key_func, 但实际上 get_available_key 会处理栈和重新生成
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{len(key_manager.api_keys) if key_manager.api_keys else MAX_RETRIES} 次尝试后仍然失败，请修改预设或输入") # 错误信息里的重试次数也动态修改

    msg = "所有API密钥或重试次数均失败"
    extra_log_all_fail = {'key': "ALL", 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': msg}
    log_msg = format_log_message('ERROR', msg, extra=extra_log_all_fail)
    print(log_msg)
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
    print(log_msg)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=ErrorResponse(message=str(exc), type="internal_error").dict())