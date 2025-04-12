import requests
import json
import os
import asyncio
from app.models import ChatCompletionRequest, Message  # 相对导入
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import httpx
import logging
import datetime

logger = logging.getLogger('my_logger')
from dotenv import load_dotenv
# 加载.env文件中的环境变量
load_dotenv()

@dataclass
class GeneratedText:
    text: str
    finish_reason: Optional[str] = None


class ResponseWrapper:
    def __init__(self, data: Dict[Any, Any]):  # 正确的初始化方法名
        self._data = data
        self._text = self._extract_text()
        self._finish_reason = self._extract_finish_reason()
        self._prompt_token_count = self._extract_prompt_token_count()
        self._candidates_token_count = self._extract_candidates_token_count()
        self._total_token_count = self._extract_total_token_count()
        self._thoughts = self._extract_thoughts()
        self._json_dumps = json.dumps(self._data, indent=4, ensure_ascii=False)

    def _extract_thoughts(self) -> Optional[str]:
        try:
            for part in self._data['candidates'][0]['content']['parts']:
                if 'thought' in part:
                    return part['text']
            return ""
        except (KeyError, IndexError):
            return ""

    def _extract_text(self) -> str:
        try:
            for part in self._data['candidates'][0]['content']['parts']:
                if 'thought' not in part:
                    return part['text']
            return ""
        except (KeyError, IndexError):
            return ""

    def _extract_finish_reason(self) -> Optional[str]:
        try:
            return self._data['candidates'][0].get('finishReason')
        except (KeyError, IndexError):
            return None

    def _extract_prompt_token_count(self) -> Optional[int]:
        try:
            return self._data['usageMetadata'].get('promptTokenCount')
        except (KeyError):
            return None

    def _extract_candidates_token_count(self) -> Optional[int]:
        try:
            return self._data['usageMetadata'].get('candidatesTokenCount')
        except (KeyError):
            return None

    def _extract_total_token_count(self) -> Optional[int]:
        try:
            return self._data['usageMetadata'].get('totalTokenCount')
        except (KeyError):
            return None

    @property
    def text(self) -> str:
        return self._text

    @property
    def finish_reason(self) -> Optional[str]:
        return self._finish_reason

    @property
    def prompt_token_count(self) -> Optional[int]:
        return self._prompt_token_count

    @property
    def candidates_token_count(self) -> Optional[int]:
        return self._candidates_token_count

    @property
    def total_token_count(self) -> Optional[int]:
        return self._total_token_count

    @property
    def thoughts(self) -> Optional[str]:
        return self._thoughts

    @property
    def json_dumps(self) -> str:
        return self._json_dumps


class GeminiClient:

    AVAILABLE_MODELS = []
    EXTRA_MODELS = os.environ.get("EXTRA_MODELS", "").split(",")
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        # 初始化时获取存储服务实例
        from app.image_storage import get_image_storage
        self.storage = get_image_storage()

    # 支持图片生成的模型列表 
    imageModels = [
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash-exp-image-generation",
    ]

    def _save_image(self, mime_type: str, base64_data: str) -> str:
        # 直接使用初始化时创建的存储服务实例
        # 保存图片并返回URL
        return self.storage.save_image(mime_type, base64_data)

    async def stream_chat(self, request: ChatCompletionRequest, contents, safety_settings, system_instruction):
        logger.info("流式开始 →")
        # 此处根据 request.model 来判断是否是图片生成模型
        isImageModel = request.model in self.imageModels

        api_version = "v1alpha" if "think" in request.model else "v1beta"
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:streamGenerateContent?key={self.api_key}&alt=sse"
        headers = {
            "Content-Type": "application/json",
        }
        data = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                "responseModalities": ["Text"] if not isImageModel else ["Text", "Image"]
            },
            "safetySettings": safety_settings
        }
        if system_instruction and not isImageModel:
            data["system_instruction"] = system_instruction
        
        # logger.info(f"请求数据: {json.dumps(data, ensure_ascii=False)}")
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, headers=headers, json=data, timeout=600) as response:
                buffer = b""
                try:
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        if line.startswith("data: "):
                            line = line[len("data: "):] 
                        buffer += line.encode('utf-8')
                        try:
                            data = json.loads(buffer.decode('utf-8'))
                            # logger.debug(f"收到数据: {json.dumps(data, ensure_ascii=False)}")
                            buffer = b""
                            if 'candidates' in data and data['candidates']:
                                candidate = data['candidates'][0]
                                if 'content' in candidate:
                                    content = candidate['content']
                                    if 'parts' in content and content['parts']:
                                        parts = content['parts']
                                        text = ""
                                        for part in parts:
                                            if 'text' in part:
                                                text += part['text']
                                            if 'inlineData' in part:
                                                inline_data = part['inlineData']
                                                if 'mimeType' in inline_data and 'data' in inline_data:
                                                    mime_type = inline_data['mimeType']
                                                    base64_data = inline_data['data']
                                                    # 记录上传开始时间
                                                    upload_start_time = datetime.datetime.now()
                                                    logger.debug(f"生成的图片数据: {mime_type}--{len(base64_data)}")
                                                    # 保存图片并获取HTTP URL
                                                    image_url = self._save_image(mime_type, base64_data)
                                                    # 计算上传耗时
                                                    upload_end_time = datetime.datetime.now()
                                                    upload_duration = (upload_end_time - upload_start_time).total_seconds()
                                                    logger.info(f"图片上传耗时: {upload_duration:.2f}秒")
                                                    logger.debug(f"图片的访问地址: {image_url}")
                                                    text += f"![]({image_url})"
                                        if text:
                                            yield text
                                        
                                if candidate.get("finishReason") and candidate.get("finishReason") != "STOP":
                                    # logger.warning(f"模型的响应因违反内容政策而被标记: {candidate.get('finishReason')}")
                                    raise ValueError(f"模型的响应被截断: {candidate.get('finishReason')}")
                                
                                if 'safetyRatings' in candidate:
                                    for rating in candidate['safetyRatings']:
                                        if rating['probability'] == 'HIGH':
                                            # logger.warning(f"模型的响应因高概率被标记为 {rating['category']}")
                                            raise ValueError(f"模型的响应被截断: {rating['category']}")
                        except json.JSONDecodeError:
                            # logger.debug(f"JSON解析错误, 当前缓冲区内容: {buffer}")
                            continue
                        except Exception as e:
                            # logger.error(f"流式处理期间发生错误: {e}")
                            raise e
                except Exception as e:
                    # logger.error(f"流式处理错误: {e}")
                    raise e
                finally:
                    # yield "![](https://lf-flow-web-cdn.doubao.com/obj/flow-doubao/samantha/logo-icon-white-bg.png)"
                    logger.info("流式结束 ←")


    def complete_chat(self, request: ChatCompletionRequest, contents, safety_settings, system_instruction):
        isImageModel = request.model in self.imageModels
        logger.info(f"是否是图片模型: {isImageModel}")
        api_version = "v1alpha" if "think" in request.model else "v1beta"
        url = f"https://generativelanguage.googleapis.com/{api_version}/models/{request.model}:generateContent?key={self.api_key}"
        headers = {
            "Content-Type": "application/json",
        }
        data = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
                "responseModalities": ["Text"] if not isImageModel else ["Text", "Image"]
            },
            "safetySettings": safety_settings
        }
        if system_instruction and not isImageModel:
            data["system_instruction"] = system_instruction

        logger.info(f"请求数据: {json.dumps(data, ensure_ascii=False)}")
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        response_data = response.json()
        logger.info(f"响应数据: {json.dumps(response_data, ensure_ascii=False)}")
        return ResponseWrapper(response_data)

    def convert_messages(self, messages, use_system_prompt=False):
        gemini_history = []
        errors = []
        system_instruction_text = ""
        is_system_phase = use_system_prompt
        for i, message in enumerate(messages):
            role = message.role
            content = message.content

            if isinstance(content, str):
                if is_system_phase and role == 'system':
                    if system_instruction_text:
                        system_instruction_text += "\n" + content
                    else:
                        system_instruction_text = content
                else:
                    is_system_phase = False

                    if role in ['user', 'system']:
                        role_to_use = 'user'
                    elif role == 'assistant':
                        role_to_use = 'model'
                    else:
                        errors.append(f"Invalid role: {role}")
                        continue

                    if gemini_history and gemini_history[-1]['role'] == role_to_use:
                        gemini_history[-1]['parts'].append({"text": content})
                    else:
                        gemini_history.append(
                            {"role": role_to_use, "parts": [{"text": content}]})
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if item.get('type') == 'text':
                        parts.append({"text": item.get('text')})
                    elif item.get('type') == 'image_url':
                        image_data = item.get('image_url', {}).get('url', '')
                        if image_data.startswith('data:image/'):
                            try:
                                mime_type, base64_data = image_data.split(';')[0].split(':')[1], image_data.split(',')[1]
                                parts.append({
                                    "inline_data": {
                                        "mime_type": mime_type,
                                        "data": base64_data
                                    }
                                })
                            except (IndexError, ValueError):
                                errors.append(
                                    f"Invalid data URI for image: {image_data}")
                        else:
                            errors.append(
                                f"Invalid image URL format for item: {item}")

                if parts:
                    if role in ['user', 'system']:
                        role_to_use = 'user'
                    elif role == 'assistant':
                        role_to_use = 'model'
                    else:
                        errors.append(f"Invalid role: {role}")
                        continue
                    if gemini_history and gemini_history[-1]['role'] == role_to_use:
                        gemini_history[-1]['parts'].extend(parts)
                    else:
                        gemini_history.append(
                            {"role": role_to_use, "parts": parts})
        if errors:
            return errors
        else:
            return gemini_history, {"parts": [{"text": system_instruction_text}]}

    @staticmethod
    async def list_available_models(api_key) -> list:
        url = "https://generativelanguage.googleapis.com/v1beta/models?key={}".format(
            api_key)
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            models = [model["name"] for model in data.get("models", [])]
            models.extend(GeminiClient.EXTRA_MODELS)
            return models
