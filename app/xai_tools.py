import json
import os
import time
from typing import Tuple, Dict, Any
import logging
import requests
from fastapi.responses import Response, JSONResponse, StreamingResponse

logger = logging.getLogger('my_logger')
HOST_IMAGE_URL = os.environ.get('HOST_URL', 'https://imgen.x.ai')
XAI_RESPONSE_FORMAT = os.environ.get('XAI_RESPONSE_FORMAT', 'url')
# 导入图片存储模块
from app.image_storage import get_image_storage
# 初始化图片存储服务
storage = get_image_storage()

def xai_image_request_converter(method, headers, request_json: Dict[str, Any]):
    """
    将grok-2-image模型的聊天请求转换为xai图像生成API请求
    
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
        
        # 构建图像生成请求
        image_request = {
            "prompt": prompt,
            "model": model,  # 使用grok-2-image模型
            "n": n,  # 使用提取的数字或默认值作为生成图像数量
            "response_format": XAI_RESPONSE_FORMAT  # url:返回URL格式,b64_json:返回base64格式
        }
        
        # 如果有user字段，添加到请求中
        if 'user' in request_json:
            image_request['user'] = request_json['user']
            
        # 转换为JSON字符串并编码为bytes
        new_request_body = json.dumps(image_request).encode('utf-8')
       
        # 发送请求到xAI图像生成API
        response = requests.request(
            method=method,
            url="https://api.x.ai/v1/images/generations",
            headers=headers,
            data=new_request_body,
            stream=enable_stream
        )
        
        # 解析返回的JSON数据
        if response.status_code == 200:
            response_data = response.json()
            # 提取图片URL和修改后的提示词
            if 'data' in response_data and len(response_data['data']) > 0:
                images = []
                for i, item in enumerate(response_data['data']):
                    url = item.get('url', '')
                    b64_json = item.get('b64_json', '')
                    revised_prompt = item.get('revised_prompt', '')
                    
                    # 将URL转换为Markdown格式
                    if url:
                        # 替换xAI图片服务器域名为本地代理地址
                        if url.startswith('https://imgen.x.ai'):
                            url = url.replace('https://imgen.x.ai', HOST_IMAGE_URL)
                        images.append({"url": url, "revised_prompt": revised_prompt, "index": i})
                    elif b64_json:
                        url = storage.save_image("image/png", b64_json)
                        images.append({"url": url, "revised_prompt": revised_prompt, "index": i})

                # 构建符合OpenAI格式的响应结构
                content = ""
                for img in images:
                    if img['index']==0 and img['revised_prompt']:
                        content += f"{img['revised_prompt']}\n\n"
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
                logger.error("xAI图像生成API返回的数据中没有图片URL")
        
        # 如果处理失败，返回原始响应
        return Response(
            content=response.content,
            status_code=response.status_code,
            media_type=response.headers.get('content-type')
        )
        
    except Exception as e:
        logger.error(f"转换xai图片请求时出错: {str(e)}")
        # 出错时返回错误响应
        error_response = {
            "error": {
                "message": f"转换xai图片请求时出错: {str(e)}",
                "type": "internal_error",
                "code": 500
            }
        }
        return JSONResponse(content=error_response, status_code=500)