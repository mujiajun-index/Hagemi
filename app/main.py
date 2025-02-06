from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse, StreamingResponse
from .models import ChatCompletionRequest, ChatCompletionResponse, ErrorResponse, ModelList
from .gemini import GeminiClient
from .utils import handle_gemini_error, protect_from_abuse, test_api_key
import os
import json
import logging
import sys
import asyncio
from typing import Literal
import random


# --- 日志配置 ---
logger = logging.getLogger("gemini_app")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
logger.setLevel(logging.DEBUG if DEBUG else logging.INFO)

formatter = logging.Formatter('[%(key)s]-%(request_type)s-[%(model)s]-%(status_code)s: %(message)s' if not DEBUG
                            else '%(asctime)s - %(levelname)s - [%(key)s]-%(request_type)s-[%(model)s]-%(status_code)s-%(message)s - %(error_message)s')

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

for logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
    logging.getLogger(logger_name).setLevel(logging.WARNING)

def translate_error(message: str) -> str:
    if "quota exceeded" in message.lower(): return "API 密钥配额已用尽"
    if "invalid argument" in message.lower(): return "无效参数"
    if "internal server error" in message.lower(): return "服务器内部错误"
    if "service unavailable" in message.lower(): return "服务不可用"
    if "blocked" in message.lower(): return "请求被阻止"
    return message

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    error_message = translate_error(str(exc_value))
    log_extra = {'key': 'N/A', 'request_type': 'N/A', 'model': 'N/A', 'status_code': 'N/A', 'error_message': '' if not DEBUG else error_message }
    logger.error("未捕获的异常: %s" % error_message, exc_info=None if not DEBUG else (exc_type, exc_value, exc_traceback), extra=log_extra)
sys.excepthook = handle_exception

app = FastAPI()

# --- 环境变量 ---
API_KEYS = os.environ.get("GEMINI_API_KEYS", "111,AIzaSyCnmiWgVV5El2JAcWbny7HeSaWJg8PrsRk").split(",")
if not API_KEYS:
    raise ValueError("请设置 GEMINI_API_KEYS 环境变量")
PASSWORD = os.environ.get("PASSWORD", "123")
MAX_REQUESTS_PER_MINUTE = int(os.environ.get("MAX_REQUESTS_PER_MINUTE", "30"))
MAX_REQUESTS_PER_DAY_PER_IP = int(os.environ.get("MAX_REQUESTS_PER_DAY_PER_IP", "600"))

# 全局 API 密钥栈
api_key_stack_global = []

def get_api_key_stack():
    """获取 API 密钥"""
    return api_key_stack_global

async def check_keys():
    available_keys = []
    for key in API_KEYS:
        is_valid = await test_api_key(key)
        status_msg = "有效" if is_valid else "无效"
        logger.info(f"API Key {key[:10]}... {status_msg}.", extra={'key': key[:10], 'request_type': 'startup', 'model': 'N/A', 'status_code': 'N/A', 'error_message': ''})
        if is_valid:
            available_keys.append(key)
    return available_keys  # 只返回有效密钥列表, 不在这里报错

@app.on_event("startup")
async def startup_event():
    global API_KEYS
    global api_key_stack_global
    logger.info("Starting Gemini API proxy...", extra={'key': 'N/A', 'request_type': 'startup', 'model': 'N/A', 'status_code': 'N/A', 'error_message': ''})

    # 先检查密钥有效性
    available_keys = await check_keys()
    if not available_keys:
        logger.error("没有可用的 API 密钥！", extra={'key': 'N/A', 'request_type': 'startup', 'model': 'N/A', 'status_code': 'N/A', 'error_message': ''})
        raise ValueError("没有可用的 API 密钥！") # 没有可用密钥，直接抛出异常

    # 使用第一个有效的 API 密钥拉取模型列表
    first_valid_key = available_keys[0]
    all_models = GeminiClient.list_available_models(first_valid_key)
    GeminiClient.AVAILABLE_MODELS = [model[7:] for model in all_models]
    logger.info(f"Available models loaded using key: {first_valid_key[:10]}...", extra={'key': first_valid_key[:10], 'request_type': 'startup', 'model': 'N/A', 'status_code': 'N/A', 'error_message': ''})

    # 更新 API_KEYS 和 api_key_stack_global
    API_KEYS = available_keys  # 只保留有效的 API 密钥
    api_key_stack_global = API_KEYS.copy()
    random.shuffle(api_key_stack_global)
    logger.info(f"可用 API 密钥数量：{len(API_KEYS)}", extra={'key': 'N/A', 'request_type': 'startup', 'model': 'N/A', 'status_code': 'N/A', 'error_message': ''})

@app.get("/v1/models", response_model=ModelList)
def list_models():
    logger.info("Received request to list models", extra={'key': 'N/A', 'request_type': 'list_models', 'model': 'N/A', 'status_code': 200, 'error_message': ''})
    return ModelList(data=[{"id": model, "object": "model", "created": 1678888888, "owned_by": "organization-owner"} for model in GeminiClient.AVAILABLE_MODELS])

async def verify_password(request: Request):
    if PASSWORD:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized: Missing or invalid token")
        token = auth_header.split(" ")[1]
        if token != PASSWORD:
            raise HTTPException(status_code=401, detail="Unauthorized: Invalid token")

async def process_request(chat_request: ChatCompletionRequest, http_request:Request, request_type: Literal['stream', 'non-stream'], api_key_stack: list, used_keys: set):
    protect_from_abuse(http_request, MAX_REQUESTS_PER_MINUTE, MAX_REQUESTS_PER_DAY_PER_IP)
    if chat_request.model not in GeminiClient.AVAILABLE_MODELS:
        error_msg = "无效的模型"
        logger.error(error_msg, extra={'key': 'N/A', 'request_type': request_type, 'model': chat_request.model, 'status_code': 400, 'error_message': error_msg if DEBUG else ''})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    while api_key_stack:
        api_key = api_key_stack.pop()
        if api_key in used_keys:
            continue
        used_keys.add(api_key)
        gemini_client = GeminiClient(api_key)

        async def stream_generator():
            try:
                async for chunk in gemini_client.stream_chat(chat_request):
                    formatted_chunk = {"id": "chatcmpl-someid", "object": "chat.completion.chunk", "created": 1234567,
                                        "model": chat_request.model, "choices": [{"delta": {"role": "assistant", "content": chunk}, "index": 0, "finish_reason": None}]}
                    yield f"data: {json.dumps(formatted_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            except asyncio.CancelledError:
                logger.info("Client disconnected", extra={'key': api_key[:10], 'request_type': request_type, 'model': chat_request.model, 'status_code': 'N/A', 'error_message': '客户端已断开连接' if DEBUG else ''})
            except Exception as e:
                error_detail = handle_gemini_error(e)
                log_message = f"API Key failed: {error_detail}"
                logger.error(log_message, exc_info=None if not DEBUG else True, extra={'key': api_key[:10], 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message': error_detail if DEBUG else ''})
                yield f"data: {json.dumps({'error': {'message': error_detail, 'type': 'gemini_error'}})}\n\n"

        if chat_request.stream:
            return StreamingResponse(stream_generator(), media_type="text/event-stream")
        else:
            try:
                response_content = gemini_client.complete_chat(chat_request)
                response = ChatCompletionResponse(id="chatcmpl-someid", object="chat.completion", created=1234567890, model=chat_request.model,
                            choices=[{"index": 0, "message": {"role": "assistant", "content": response_content}, "finish_reason": "stop"}])
                logger.info("Request successful", extra={'key': api_key[:10], 'request_type': request_type, 'model': chat_request.model, 'status_code': 200, 'error_message': ''})
                return response
            except Exception as e:
                error_detail = handle_gemini_error(e)
                log_message = f"API Key failed: {error_detail}"
                logger.error(log_message, exc_info=None if not DEBUG else True, extra={'key': api_key[:10], 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message':error_detail if DEBUG else ''})

    msg = "所有API密钥或重试次数均失败"
    logger.error(msg, extra={'key': "ALL", 'request_type': request_type, 'model': chat_request.model, 'status_code': 500, 'error_message':msg if DEBUG else ''})
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)

@app.post("/v1/chat/completions", response_model=ChatCompletionResponse)
async def chat_completions(request: ChatCompletionRequest, http_request: Request, _: None = Depends(verify_password)):
    api_key_stack = get_api_key_stack()
    used_keys = set()
    return await process_request(request, http_request, "stream" if request.stream else "non-stream", api_key_stack, used_keys)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_message = translate_error(str(exc))
    log_extra = {'key': 'N/A', 'request_type': 'N/A', 'model': 'N/A', 'status_code': 500, 'error_message': error_message}
    logger.error(f"Unhandled exception ({exc.__class__.__name__}): {error_message}", exc_info=None if not DEBUG else True, extra=log_extra)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=ErrorResponse(message=str(exc), type="internal_error").dict())