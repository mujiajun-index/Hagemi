FROM python:3.11-slim

WORKDIR /app

COPY ./app /app/app
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# 环境变量 (在 Hugging Face Spaces 中设置)
# ENV GEMINI_API_KEYS=your_key_1,your_key_2,your_key_3
ENV VERSION=1.9.9

# 兼容huggingface本地保存限制为50GB（非持久性）磁盘空间(免费用户重新构建应用重启后数据会丢失)
RUN mkdir -p /app/app/images && chmod -R 777 /app/app/images

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]