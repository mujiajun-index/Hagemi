from math import log
import requests
import json
import os
import re
from app.models import ChatCompletionRequest, Message  # 相对导入
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import httpx
import logging
import datetime
import base64

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
            text = ""
            for part in self._data['candidates'][0]['content']['parts']:
                if 'thought' not in part:
                    if 'text' in part:
                        text += part['text']
                    elif 'inlineData' in part:
                        # 这里不处理图片，由GeminiClient处理
                        pass
            return text
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

    # Gemini 模型列表
    GEMINI_MODELS = []

    # 扩展模型列表，支持设置思考token的模型
    EXTENDED_MODELS = [
        "---------- EXTENDED_MODELS ----------",
        "gemini-2.5-pro-nothinking",
        "gemini-2.5-flash-nothinking",
        "gemini-2.5-flash-lite-nothinking",
        "gemini-2.5-pro-thinking-32768",
        "gemini-2.5-flash-thinking-24576",
        "gemini-2.5-flash-lite-thinking-24576"
    ]

    # 自定义模型列表，支持设置思考token的模型
    EXTRA_MODELS = [model for model in os.environ.get("EXTRA_MODELS", "").split(",") if model]
    # 历史图片提交方式: all:提交上下文所有图片 last:只提交最后一张图片(推荐)
    HISTORY_IMAGE_SUBMIT_TYPE = os.environ.get("HISTORY_IMAGE_SUBMIT_TYPE", "last")
    # API基础URL，默认为Google官方API地址
    BASE_URL = os.environ.get("PROXY_URL") or "https://generativelanguage.googleapis.com"
    def __init__(self, api_key: str, storage=None):
        self.api_key = api_key
        # 使用传入的存储实例或创建新实例
        if storage is None:
            from app.image_storage import get_image_storage
            self.storage = get_image_storage()
        else:
            self.storage = storage

   # 支持设置思考token的模型列表
    thinkingModels = [
        "gemini-2.5-pro",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite"
    ]
    
    @staticmethod
    def _parse_model_name_and_budget(model_name: str):
        # 验证model_name是否以thinkingModels中的模型开头
        if not any(model_name.startswith(m) for m in GeminiClient.thinkingModels):
            return None, None

        """
        Parses the model name to extract the base model and thinking budget.
        - gemini-2.5-pro-thinking-128 -> model: gemini-2.5-pro, budget: 128
        - gemini-2.5-flash-nothinking -> model: gemini-2.5-flash, budget: 0
        - gemini-2.5-pro -> model: gemini-2.5-pro, budget: -1
        """
        # Default values
        base_model = model_name
        thinking_budget = -1

        # Regex to find thinking config
        match = re.match(r"^(.*?)-(thinking|nothinking)(?:-(\d+))?$", model_name)

        if match:
            base_model = match.group(1)
            thinking_mode = match.group(2)
            budget_value = match.group(3)

            if thinking_mode == "thinking":
                if budget_value:
                    thinking_budget = int(budget_value)
                else:
                    thinking_budget = -1  # Default to dynamic if no value is specified
            elif thinking_mode == "nothinking":
                if base_model == "gemini-2.5-pro":
                    thinking_budget = 128; #gemini-2.5-pro 最少设置 128 Token
                else:
                    thinking_budget = 0  # Thinking off

        return base_model, thinking_budget

    # 过滤Markdown格式的图片
    def filter_markdown_images(self, content):
        import re
        if isinstance(content, list):
            first_image_item_processed = False
            for item in reversed(content):
                if isinstance(item, dict) and 'parts' in item:
                    # 只处理AI模型parts中text的Markdown图片
                    if 'model' in item['role']:
                        for part in reversed(item['parts']):
                            if 'text' in part and '![' in part['text']:
                                # 提取Markdown所有图片URL
                                matches = re.finditer(r'!\[.*?\]\((.*?)\)', part['text'])
                                for match in matches:
                                    image_url = match.group(1)
                                    # 根据配置决定是否下载图片
                                    is_really = True if self.HISTORY_IMAGE_SUBMIT_TYPE == 'all' \
                                        or (self.HISTORY_IMAGE_SUBMIT_TYPE == 'last' and not first_image_item_processed) else False
                                    # 调用方法获取base64数据并添加到parts , is_really 是否真的下载图片
                                    inline_data = self.get_inline_data_base64_images(image_url, is_really)
                                    item['parts'].append(inline_data)
                                if matches:
                                    # 替换Markdown图片标记
                                    part['text'] = re.sub(r'!\[.*?\]\(.*?\)', '[image]', part['text'])
                                    first_image_item_processed = True

            return content
        return content

    #根据 Markdown格式的图片 返回 base64 格式的图片  is_really 是否真的下载图片
    def get_inline_data_base64_images(self, markdown_image, is_really=True):
        # logger.info(f"下载请求中的图片: {markdown_image} is_really: {is_really}")
        # 检查是否为内存存储，并尝试从内存中获取图片
        if is_really and hasattr(self.storage, 'get_image'):
            try:
                # 从URL中提取文件名
                image_name = markdown_image.split('/')[-1]
                # logger.info(f"尝试从内存中获取图片: {image_name}")
                base64_data,mime_type = self.storage.get_image(image_name)
                # logger.info(f"内存中图片的MIME类型: {mime_type} 图片的大小: {len(base64_data)}")
                if base64_data:
                    return {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64_data
                        }
                    }
            except Exception:
                pass

        # 如果不是内存存储或从内存获取失败，则尝试下载
        if is_really:
            from app.utils import download_image_to_base64
            mime_type, base64_data = download_image_to_base64(markdown_image)
            if mime_type and base64_data:
                return {
                    "inline_data": {
                        "mime_type": mime_type,
                        "data": base64_data
                    }
                }
        # 如果下载失败，或不需要下载，返回默认无效图片
        return {
            "inline_data": {
                "mime_type": "image/png",
                "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAAXNSR0IArs4c6QAAAA1JREFUGFdj+P///38ACfsD/QVDRcoAAAAASUVORK5CYII="
            }
        }


    # 支持图片生成的模型列表 
    imageModels = [
        "gemini-2.0-flash-exp",
        "gemini-2.0-flash-exp-image-generation",
        "gemini-2.0-flash-preview-image-generation"
    ]

    def _save_image(self, mime_type: str, base64_data: str) -> str:
        # 直接使用初始化时创建的存储服务实例
        # 保存图片并返回URL
        return self.storage.save_image(mime_type, base64_data)

    async def stream_chat(self, request: ChatCompletionRequest, contents, safety_settings, system_instruction):
        # 需要过滤contents 消息中的Markdown格式的图片、
        contents = self.filter_markdown_images(contents);
        # 此处根据 request.model 来判断是否是图片生成模型
        isImageModel = request.model in self.imageModels

        # 默认基础模型
        base_model = request.model

        # 判断是否是思考模型并解析思维预算的模型名称和设置
        thinking_model, thinking_budget = self._parse_model_name_and_budget(request.model)

        if thinking_model is not None:
            base_model = thinking_model

        url = f"{self.BASE_URL}/v1beta/models/{base_model}:streamGenerateContent?key={self.api_key}&alt=sse"
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
        # 思考模型需要设置思维预算
        if thinking_budget is not None:
            data["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": thinking_budget
            }
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
                                                    logger.info(f"生成的图片数据: {mime_type}--{len(base64_data)}")
                                                    # 保存图片并获取HTTP URL
                                                    image_url = self._save_image(mime_type, base64_data)
                                                    # 计算上传耗时
                                                    upload_end_time = datetime.datetime.now()
                                                    upload_duration = (upload_end_time - upload_start_time).total_seconds()
                                                    logger.info(f"图片上传耗时: {upload_duration:.2f}秒")
                                                    logger.info(f"图片的访问地址: {image_url}")
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
                            elif 'error' in data and data['error']:
                                raise ValueError(f"模型的响应被截断: {data['error']}")
                        except json.JSONDecodeError:
                            # logger.debug(f"JSON解析错误, 当前缓冲区内容: {buffer}")
                            continue
                        except Exception as e:
                            # logger.error(f"流式处理期间发生错误: {e}")
                            raise e
                except Exception as e:
                    # logger.error(f"流式处理错误: {e}")
                    raise e
                # finally:
                    # yield "![](https://lf-flow-web-cdn.doubao.com/obj/flow-doubao/samantha/logo-icon-white-bg.png)"
                    # logger.info("请求结束")


    def complete_chat(self, request: ChatCompletionRequest, contents, safety_settings, system_instruction):
        # 需要过滤contents 消息中的Markdown格式的图片、
        contents = self.filter_markdown_images(contents);
        # 此处根据 request.model 来判断是否是图片生成模型
        isImageModel = request.model in self.imageModels
        
      # 默认基础模型
        base_model = request.model

        # 判断是否是思考模型并解析思维预算的模型名称和设置
        thinking_model, thinking_budget = self._parse_model_name_and_budget(request.model)
        if thinking_model is not None:
            base_model = thinking_model

        url = f"{self.BASE_URL}/v1beta/models/{base_model}:generateContent?key={self.api_key}"
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
        if thinking_budget is not None:
            data["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": thinking_budget
            }

        # logger.info(f"请求数据: {json.dumps(data, ensure_ascii=False)}")
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        response_data = response.json()
        # logger.info(f"响应数据: {json.dumps(response_data, ensure_ascii=False)}")
                # 检查响应中的错误
        if 'error' in response_data and response_data['error']:
            raise ValueError(f"模型的响应异常: {response_data['error']}")

        # 处理图片生成
        if isImageModel and 'candidates' in response_data and response_data['candidates']:
            candidate = response_data['candidates'][0]
            if 'content' in candidate and 'parts' in candidate['content']:
                parts = candidate['content']['parts']
                for part in parts:
                    if 'inlineData' in part:
                        inline_data = part['inlineData']
                        if 'mimeType' in inline_data and 'data' in inline_data:
                            mime_type = inline_data['mimeType']
                            base64_data = inline_data['data']
                            # 记录上传开始时间
                            upload_start_time = datetime.datetime.now()
                            logger.info(f"生成的图片数据: {mime_type}--{len(base64_data)}")
                            # 保存图片并获取HTTP URL
                            image_url = self._save_image(mime_type, base64_data)
                            # 计算上传耗时
                            upload_end_time = datetime.datetime.now()
                            upload_duration = (upload_end_time - upload_start_time).total_seconds()
                            logger.info(f"图片上传耗时: {upload_duration:.2f}秒")
                            logger.info(f"图片的访问地址: {image_url}")
                            
                            # 在文本中添加图片链接
                            for text_part in parts:
                                if 'text' in text_part:
                                    text_part['text'] += f"\n![]({image_url})"
                                    break
                            else:
                                # 如果没有找到文本部分，添加一个新的文本部分
                                parts.append({"text": f"![]({image_url})"})
        
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


    def merge_model():
        # 合并所有模型
        models = []
        models.extend(GeminiClient.GEMINI_MODELS)
        models.extend(GeminiClient.EXTENDED_MODELS)
        models.extend(GeminiClient.EXTRA_MODELS)
        return models
    
    @staticmethod
    async def list_available_models(api_key) -> list:
        url = "{}/v1beta/models?key={}".format(GeminiClient.BASE_URL,api_key)
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            models = [model["name"] for model in data.get("models", [])]
            # 初始化Gemini模型列表
            GeminiClient.GEMINI_MODELS = list(models)
            # 合并扩展模型
            models.extend(GeminiClient.EXTENDED_MODELS)
            # 自定义模型列表
            models.extend(GeminiClient.EXTRA_MODELS)
            return models
