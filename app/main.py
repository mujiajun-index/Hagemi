# main.py
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from .models import ChatCompletionRequest, ChatCompletionResponse, ErrorResponse, ModelList  
from .gemini import GeminiClient, ResponseWrapper  
from .utils import handle_gemini_error, protect_from_abuse, APIKeyManager, test_api_key  
import os
import json
import logging
import sys
import asyncio
from typing import Literal
import random
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler


class CustomLoggerAdapter(logging.LoggerAdapter):
    """
    自定义日志适配器，自动添加默认字段。
    """

    def __init__(self, logger, extra=None):
        super().__init__(logger, extra or {})
        self.default_extra = {
            'key': 'N/A',
            'request_type': 'N/A',
            'model': 'N/A',
            'status_code': 'N/A',
            'error_message': ''
        }

    def process(self, msg, kwargs):
        extra = kwargs.get('extra', {})
        full_extra = self.default_extra.copy()
        full_extra.update(extra)
        kwargs['extra'] = full_extra
        return msg, kwargs


# 设置日志记录
logger = logging.getLogger("gemini_app")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

# 日志格式
formatter = logging.Formatter('%(asctime)s - %(levelname)s - [%(key)s]-%(request_type)s-[%(model)s]-%(status_code)s: %(message)s - %(error_message)s' if DEBUG
else '[%(key)s]-%(request_type)s-[%(model)s]-%(status_code)s: %(message)s')


stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)
logger = CustomLoggerAdapter(logger)  # 使用自定义适配器


for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)


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
    logger.error("未捕获的异常: %s" % error_message, exc_info=None if not DEBUG else (
        exc_type, exc_value, exc_traceback))


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

key_manager = APIKeyManager()
current_api_key = key_manager.get_available_key()


def switch_api_key():
    global current_api_key
    key = key_manager.get_available_key()
    if key:
        current_api_key = key
        logger.info(f"API key 替换为 → {current_api_key[:8]}...", extra={
            'key': current_api_key[:8], 'request_type': 'switch_key'})
    else:
        logger.error("API key 替换失败，所有API key都已耗尽或被暂时禁用，请重新配置或稍后重试")


async def check_keys():
    available_keys = []
    for key in key_manager.api_keys:
        is_valid = await test_api_key(key)
        status_msg = "有效" if is_valid else "无效"
        logger.info(f"API Key {key[:10]}... {status_msg}.")  # 更简洁的日志
        if is_valid:
            available_keys.append(key)
    if not available_keys:
        logger.error("没有可用的 API 密钥！")
    return available_keys


@app.on_event("startup")
async def startup_event():
    logger.info("Starting Gemini API proxy...")
    available_keys = await check_keys()
    if available_keys:
        key_manager.api_keys = available_keys
        key_manager.show_all_keys()  # 在检查完密钥后显示
        logger.info(f"可用 API 密钥数量：{len(key_manager.api_keys)}")
        if key_manager.api_keys:
            all_models = await GeminiClient.list_available_models(key_manager.api_keys[0])
            GeminiClient.AVAILABLE_MODELS = [model.replace(
                "models/", "") for model in all_models]
            logger.info(f"Available models loaded.")


@app.get("/v1/models", response_model=ModelList)
def list_models():
    logger.info("Received request to list models",
                extra={'request_type': 'list_models', 'status_code': 200})
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
        logger.error(error_msg, extra={'request_type': request_type,
                     'model': chat_request.model, 'status_code': 400, 'error_message': error_msg})
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    contents, system_instruction = GeminiClient.convert_messages(
        GeminiClient, chat_request.messages)
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info(f"第 {attempt}/{MAX_RETRIES} 次尝试 ...", extra={
            'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model})
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
                        logger.info("Client disconnected", extra={'key': current_api_key[:8], 'request_type': request_type,
                                    'model': chat_request.model, 'error_message': '客户端已断开连接'})
                    except Exception as e:
                        error_detail = handle_gemini_error(
                            e, current_api_key, key_manager, switch_api_key)
                        log_message = f"API Key failed: {error_detail}"
                        logger.error(log_message, exc_info=None if not DEBUG else True, extra={'key': current_api_key[:8], 'request_type': request_type,
                                     'model': chat_request.model, 'status_code': 500, 'error_message': error_detail})
                        yield f"data: {json.dumps({'error': {'message': error_detail, 'type': 'gemini_error'}})}\n\n"
                        if attempt < MAX_RETRIES:
                            switch_api_key()
                return StreamingResponse(stream_generator(), media_type="text/event-stream")
            else:
                response_content = gemini_client.complete_chat(
                    chat_request, contents, safety_settings_g2 if 'gemini-2.0-flash-exp' in chat_request.model else safety_settings, system_instruction)
                response = ChatCompletionResponse(id="chatcmpl-someid", object="chat.completion", created=1234567890, model=chat_request.model,
                                                  choices=[{"index": 0, "message": {"role": "assistant", "content": response_content.text}, "finish_reason": "stop"}])
                logger.info("Request successful", extra={'key': current_api_key[:8], 'request_type': request_type,
                            'model': chat_request.model, 'status_code': 200})
                return response
        except requests.exceptions.RequestException as e:
            error_detail = handle_gemini_error(
                e, current_api_key, key_manager, switch_api_key)
            logger.error(f"{error_detail}", exc_info=None if not DEBUG else True, extra={
                         'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': error_detail})
            if attempt < MAX_RETRIES:
                switch_api_key()
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{MAX_RETRIES} 次尝试后仍然失败，请修改预设或输入")
        except Exception as e:
            error_detail = handle_gemini_error(
                e, current_api_key, key_manager, switch_api_key)
            logger.error(f"{error_detail}", exc_info=None if not DEBUG else True, extra={
                         'key': current_api_key[:8], 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': error_detail})
            if attempt < MAX_RETRIES:
                switch_api_key()
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"{MAX_RETRIES} 次尝试后仍然失败，请修改预设或输入")

    msg = "所有API密钥或重试次数均失败"
    logger.error(msg, extra={'key': "ALL", 'request_type': request_type,
                 'model': chat_request.model, 'status_code': 500, 'error_message': msg})
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)


@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest, http_request: Request, _: None = Depends(verify_password)):
    return await process_request(request, http_request, "stream" if request.stream else "non-stream")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_message = translate_error(str(exc))
    logger.error(f"Unhandled exception", exc_info=None if not DEBUG else True,
                 extra={'status_code': 500, 'error_message': error_message})
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=ErrorResponse(message=str(exc), type="internal_error").dict())