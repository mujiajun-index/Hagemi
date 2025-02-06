import google.generativeai as genai
from .models import ChatCompletionRequest, Message
import os
import asyncio
from google.api_core.exceptions import GoogleAPIError, ResourceExhausted, InternalServerError, ServiceUnavailable, InvalidArgument


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

    async def _send_message(self, model_name: str, messages: list, stream: bool):
        model = self.get_model(model_name)
        chat = model.start_chat(history=self.convert_messages(messages))
        last_message_content = messages[-1].content if messages else ""
        if stream:
            response = await chat.send_message_async(last_message_content, stream=True)
            return response
        else:
            response = chat.send_message(last_message_content, stream=False)
            return response

    async def stream_chat(self, request: ChatCompletionRequest):
        try:
            response = await self._send_message(request.model, request.messages, stream=True)
            async for chunk in response:
                yield chunk.text
        except (GoogleAPIError, ResourceExhausted, InternalServerError, ServiceUnavailable, InvalidArgument) as e:
            raise

    def complete_chat(self, request: ChatCompletionRequest):
        try:
            response = self._send_message(request.model, request.messages, stream=False)
            return response.text
        except (GoogleAPIError, ResourceExhausted, InternalServerError, ServiceUnavailable, InvalidArgument) as e:
            raise

    def convert_messages(self, messages) -> list:
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
        try:
            genai.configure(api_key=api_key)
            models = genai.list_models()
            return [model.name for model in models]
        except Exception as e:
            print(f"Error listing models: {e}")
            return []