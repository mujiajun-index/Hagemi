FROM python:3.11-slim

WORKDIR /app

COPY ./app /app/app
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 环境变量 (在 Hugging Face Spaces 中设置)
# ENV GEMINI_API_KEYS=your_key_1,your_key_2,your_key_3
ENV VERSION=1.9.8

# 兼容huggingface本地保存(重新构建后依然消失)
RUN mkdir -p /app/app/images && chmod -R 777 /app/app/images

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]