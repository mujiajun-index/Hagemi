import google.generativeai as genai
# from .models import ChatCompletionRequest, Message # 移除了此行
from .models import ChatCompletionRequest, Message  #直接从models导入, 确保models.py在同一目录下, 或正确设置了PYTHONPATH
import os
import asyncio  # 导入 asyncio


class GeminiClient:
    AVAILABLE_MODELS = ["gemini-pro", "gemini-pro-vision"]

    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)
        self.model_cache = {}
        self.api_key = api_key

    def get_model(self, model_name: str):
        if model_name not in self.model_cache:
            self.model_cache[model_name] = genai.GenerativeModel(model_name)
        return self.model_cache[model_name]

    async def stream_chat(self, request: ChatCompletionRequest):  # 改为 async
        """
        与 Gemini API 进行流式对话。
        """
        model = self.get_model(request.model)
        chat = model.start_chat(history=self.convert_messages(request.messages))
        last_message_content = request.messages[-1].content if request.messages else ""

        response = await chat.send_message_async(last_message_content, stream=True)  # 使用 send_message_async
        async for chunk in response:  # 使用 async for
            yield chunk.text

    def complete_chat(self, request: ChatCompletionRequest):
        """
        与 Gemini API 进行非流式对话。
        """
        model = self.get_model(request.model)
        chat = model.start_chat(history=self.convert_messages(request.messages))
        last_message_content = request.messages[-1].content if request.messages else ""
        response = chat.send_message(last_message_content, stream=False)
        return response.text

    def convert_messages(self, messages):
        """
        将 OpenAI 格式的 messages 转换为 Gemini 格式。
        """
        gemini_messages = []
        for msg in messages:
            if msg.role == "system":
                gemini_messages.insert(0, {"role": "user", "parts": [msg.content]})
            elif msg.role == "user":
                gemini_messages.append({"role": "user", "parts": [msg.content]})
            elif msg.role == "assistant":
                gemini_messages.append({"role": "model", "parts": [msg.content]})
        return gemini_messages

    @staticmethod
    def list_available_models(api_key) -> list:
        """获取可用模型列表"""
        try:
            genai.configure(api_key=api_key)
            models = genai.list_models()
            return [model.name for model in models]
        except Exception as e:
            print(f"Error listing models: {e}")
            return []