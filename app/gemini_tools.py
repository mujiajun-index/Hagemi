import json
from math import log
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
            # 限制n的范围在1-4之间，超出范围则设置为1
            if n < 1 or n > 4:
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

# Gemini视频模型请求转换器
def gemini_veo_request_converter(method, headers, request_json: Dict[str, Any]):
    """
    将gemini-veo模型的聊天请求转换为Gemini视频生成API请求
    该函数遵循VEO模型的两步异步流程：
    1. 发送一个长时运行的预测请求到`:predictLongRunning`端点。
    2. 轮询操作状态，直到视频生成完成或出现错误。
    """
    try:
        model = request_json.get('model', '')
        enable_stream = request_json.get('stream', False)
        messages = request_json.get('messages', [])
        if not messages:
            logger.error("请求中没有消息内容")
            return JSONResponse(content={"error": {"message": "请求中没有消息内容", "type": "invalid_request_error", "code": 400}}, status_code=400)

        last_message = messages[-1]
        content = last_message.get('content', '')
        if isinstance(content, list):
            text_items = [item.get('text', '') for item in content if item.get('type') == 'text']
            prompt = text_items[-1] if text_items else ''
        else:
            prompt = content

        # 从prompt前10个字符中提取数字作为生成视频数量
        import re
        n = request_json.get('n', 1)  # 默认值为1
        # 获取前10个字符（如果字符串长度小于10，则获取整个字符串）
        first_10_chars = prompt[:10]
        # 使用正则表达式匹配数字
        match = re.search(r'\d+', first_10_chars)
        if match:
            n = int(match.group())
            # 限制n的范围在1-2之间，超出范围则设置为1
            if n < 1 or n > 2:
                n = 1
        aspect_ratio_pattern = r'(9:16|16:9)'
        aspect_ratio_match = re.search(aspect_ratio_pattern, prompt)
        aspect_ratio = aspect_ratio_match.group(1) if aspect_ratio_match else '16:9'
        video_request = {
            "instances": [{"prompt": prompt}],
            "parameters": {
                "aspectRatio": aspect_ratio,
                "personGeneration": "allow_adult",
                # "numberOfVideos": n,
                "durationSeconds": 8,
            },
        }
        new_request_body = json.dumps(video_request).encode('utf-8')

        auth_header = headers.get('authorization', '')
        api_key = 'none'
        if auth_header.startswith('Bearer '):
            api_key = auth_header[7:]

        # Step 1: Start the long-running prediction job
        long_running_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning?key={api_key}"
        initial_response = requests.post(long_running_url, headers={'Content-Type': 'application/json'}, data=new_request_body)

        if initial_response.status_code != 200:
            logger.error(f"启动VEO任务失败: {initial_response.text}")
            return Response(content=initial_response.content, status_code=initial_response.status_code, media_type=initial_response.headers.get('content-type'))

        op_data = initial_response.json()
        logger.info(f"VEO任务已启动,正在生成中...")
        op_name = op_data.get('name')
        if not op_name:
            logger.error(f"未能从响应中获取操作名称: {op_data}")
            return JSONResponse(content={"error": "未能从响应中获取操作名称"}, status_code=500)
        # 记录任务开始时间
        start_time = time.time()
        # Step 2: Poll for the result
        status_url = f"https://generativelanguage.googleapis.com/v1beta/{op_name}?key={api_key}"
        while True:
            status_response = requests.get(status_url)
            if status_response.status_code != 200:
                logger.error(f"检查操作状态失败: {status_response.text}")
                return Response(content=status_response.content, status_code=status_response.status_code, media_type=status_response.headers.get('content-type'))

            status_data = status_response.json()
            # logger.info(f"VEO任务状态检查结果: {status_data}")
            if status_data.get('done'):
                # 计算总耗时
                totalLatency = round(time.time() - start_time, 2)
                logger.info(f"VEO任务已完成,总耗时{totalLatency}秒")
                if 'response' in status_data:
                    # Success case
                    response_data = status_data['response']
                    videos = []
                    if 'generateVideoResponse' in response_data:
                        generate_video_response = response_data['generateVideoResponse']
                        if 'generatedSamples' in generate_video_response and generate_video_response['generatedSamples']:
                            for i, sample in enumerate(generate_video_response['generatedSamples']):
                                video_info = sample.get('video', {})
                                url = video_info.get('uri')
                                if url:
                                    # 视频URL可能需要API Key才能下载
                                    download_url = f"{url}&key={api_key}"
                                    # 使用全局图片存储实例保存视频并获取URL
                                    from app.utils import download_video_to_base64
                                    mime_type, base64_data = download_video_to_base64(download_url)
                                    url = storage.save_image(mime_type, base64_data)
                                    logger.info(f"视频的访问地址: {url}")
                                    videos.append({"url": url, "index": i})
                        
                        if videos:
                            content = "视频已生成:\n\n" + "\n\n".join([f"[点击下载]({vid['url']})" for vid in videos])
                            openai_response = {
                                "id": f"chatcmpl-{int(time.time())}",
                                "object": "chat.completion",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{"index": 0, "message": {"role": "assistant", "content": content.strip()}, "finish_reason": "stop"}],
                                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                            }
                            if enable_stream:
                                chunk_response = openai_response.copy()
                                chunk_response["object"] = "chat.completion.chunk"
                                chunk_response["choices"] = [{"index": 0, "delta": {"role": "assistant", "content": content.strip()}, "finish_reason": "stop"}]
                                async def generate_response():
                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                                    yield "data: [DONE]\n\n"
                                return StreamingResponse(content=generate_response(), media_type="text/event-stream")
                            else:
                                return JSONResponse(content=openai_response)
                        else:
                            # 如果没有生成视频，检查是否有raiMediaFilteredReasons
                            if 'raiMediaFilteredReasons' in generate_video_response and generate_video_response['raiMediaFilteredReasons']:
                                error_message = "VEO任务完成但视频被过滤: " + generate_video_response['raiMediaFilteredReasons'][0]
                                logger.error(error_message)
                                return JSONResponse(content={"error": error_message}, status_code=403)
                            else:
                                logger.error("VEO任务完成但未找到视频数据")
                                return JSONResponse(content={"error": "VEO任务完成但未找到视频数据"}, status_code=403)
                elif 'error' in status_data:
                    # Error case
                    error_details = status_data.get('error', {})
                    logger.error(f"VEO任务失败: {error_details}")
                    return JSONResponse(content={"error": f"VEO任务失败: {error_details.get('message', '未知错误')}"}, status_code=500)
                break # Exit loop
            
            # logger.info(f"视频 {op_name} 尚未准备好。5秒后重试...")
            time.sleep(5)

    except Exception as e:
        logger.error(f"转换Gemini视频请求时出错: {str(e)}")
        return JSONResponse(content={"error": {"message": f"转换Gemini视频请求时出错: {str(e)}", "type": "internal_error", "code": 500}}, status_code=500)