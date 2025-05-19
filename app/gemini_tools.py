import json
import os
import time
from typing import Dict, Any
import logging
import requests
from fastapi.responses import Response, JSONResponse, StreamingResponse

logger = logging.getLogger('my_logger')
HOST_IMAGE_URL = os.environ.get('HOST_URL', 'https://generativelanguage.googleapis.com')
# 导入全局图片存储实例
from app.main import global_image_storage as storage

def gemini_image_request_converter(method, headers, request_json: Dict[str, Any]):
    """
    将imagen-3.0-generate模型的聊天请求转换为Gemini图像生成API请求
    
    Args:
        method: 请求方法
        headers: 请求头
        request_json: 请求体JSON数据
        
    Returns:
        Response: 返回响应对象，可能是普通Response或StreamingResponse
    """
    try:
        model = request_json.get('model', '') # 模型名称
        enable_stream = request_json.get('stream', False) # 是否启用流式响应
        # 获取最后一条消息的内容作为图像生成的提示词
        messages = request_json.get('messages', [])
        if not messages:
            logger.error("请求中没有消息内容")
            error_response = {
                "error": {
                    "message": "请求中没有消息内容",
                    "type": "invalid_request_error",
                    "code": 400
                }
            }
            return JSONResponse(content=error_response, status_code=400)
            
        last_message = messages[-1]
        content = last_message.get('content', '')
        # 如果content是列表，获取最后一个包含text字段的项目
        if isinstance(content, list):
            text_items = [item.get('text', '') for item in content if item.get('type') == 'text']
            prompt = text_items[-1] if text_items else ''
        else:
            prompt = content
        
        # 从prompt前10个字符中提取数字作为生成图片数量
        import re
        n = request_json.get('n', 1)  # 默认值为1
        # 获取前10个字符（如果字符串长度小于10，则获取整个字符串）
        first_10_chars = prompt[:10]
        # 使用正则表达式匹配数字
        match = re.search(r'\d+', first_10_chars)
        if match:
            n = int(match.group())
            # 限制n的范围在1-10之间，超出范围则设置为1
            if n < 1 or n > 10:
                n = 1
        
        # 使用正则表达式匹配图片生成比例
        aspect_ratio_pattern = r'(1:1|9:16|16:9|3:4|4:3)'
        aspect_ratio_match = re.search(aspect_ratio_pattern, prompt)
        r = aspect_ratio_match.group(1) if aspect_ratio_match else '1:1'

        # 构建Gemini图像生成请求
        image_request = {
            "instances": [
                {
                    "prompt": prompt
                }
            ],
            "parameters": {
                "sampleCount": n,  # 使用提取的数字或默认值作为生成图像数量
                "aspectRatio": r, #模型支持“1:1”“9:16”“16:9”“3:4”或“4:3”。
                # "personGeneration":"allow_all", #允许生成任何年龄的人。
                # "addWatermark":False, #是否在生成的图像上添加水印。
            }
        }
        # 转换为JSON字符串并编码为bytes
        new_request_body = json.dumps(image_request).encode('utf-8')
        # 发送请求到Gemini图像生成API
        # 注意：Gemini API需要从Authorization头部获取API密钥，格式为Bearer <API_KEY>
        auth_header = headers.get('authorization', '')
        api_key = 'none'
        if auth_header.startswith('Bearer '):
            api_key = auth_header[7:]  # 去掉'Bearer '前缀
        # 构建Gemini API URL
        gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predict?key={api_key}"
        # 发送请求到Gemini API
        response = requests.request(
            method='POST',  # 固定使用POST方法
            url=gemini_url,
            headers={'Content-Type': 'application/json'},
            data=new_request_body,
            stream=False
        )
        # 解析返回的JSON数据
        if response.status_code == 200:
            response_data = response.json()
            # 提取图片URL
            images = []
            if 'predictions' in response_data:
                for i, prediction in enumerate(response_data['predictions']):
                    mime_type = prediction.get('mimeType', '')
                    base64_data = prediction.get('bytesBase64Encoded', '')
                    enhanced_prompt = prediction.get('prompt', '')
                    if mime_type and base64_data:
                        # 使用全局图片存储实例保存图片并获取URL
                        url = storage.save_image(mime_type, base64_data)
                        logger.info(f"图片的访问地址: {url}")
                        images.append({"url": url, "index": i, "enhanced_prompt": enhanced_prompt})
            if images:
                # 构建符合OpenAI格式的响应结构
                content = ""
                for img in images:
                    if img['index'] == 0 and img['enhanced_prompt']:
                        content += f"{img['enhanced_prompt']}\n\n"
                    content += f"![image{img['index']}]({img['url']})\n\n"
                
                # 创建OpenAI格式的响应
                openai_response = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": content.strip(),
                                "role": "assistant"
                            },
                            "finish_reason": "stop"
                        }
                    ],
                    "system_fingerprint": "fp_" + hex(int(time.time()))[2:]
                }
                # 根据stream参数决定返回方式
                if enable_stream:
                    # 返回OpenAI格式的流式响应
                    async def generate_response():
                        # 发送响应数据
                        yield f"data: {json.dumps(openai_response)}\n\n"
                        # 发送完成标记
                        yield "data: [DONE]\n\n"
                    
                    return StreamingResponse(
                        content=generate_response(),
                        media_type="text/event-stream"
                    )
                else:
                    # 返回普通响应
                    return Response(
                        content=json.dumps(openai_response).encode('utf-8'),
                        status_code=200,
                        media_type="application/json"
                    )
            else:
                logger.error("Gemini图像生成失败,或被拒绝生成")
                return JSONResponse(content={"error": "Gemini图像生成失败,或被拒绝生成"}, status_code=403)
        
        # 如果处理失败，返回原始响应
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get('content-type')
        )
        
    except Exception as e:
        logger.error(f"转换Gemini图片请求时出错: {str(e)}")
        # 出错时返回错误响应
        error_response = {
            "error": {
                "message": f"转换Gemini图片请求时出错: {str(e)}",
                "type": "internal_error",
                "code": 500
            }
        }
        return JSONResponse(content=error_response, status_code=500)