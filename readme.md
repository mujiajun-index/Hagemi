# 🚀 Gemini API Proxy

这是一个基于 FastAPI 构建的 Gemini API 代理，旨在提供一个简单、安全且可配置的方式来访问 Google 的 Gemini 模型。它特别适用于在 Hugging Face Spaces 上部署，并与 SillyTavern 和沉浸式翻译等工具集成。

## ✨ 主要功能：

### 🔑 API 密钥轮询和管理：

*   通过 `GEMINI_API_KEYS` 环境变量配置多个 API 密钥。
*   启动时自动检查密钥的有效性。
*   按随机顺序进行轮询,并确保不会连续随机到同一个密钥。

### 📑 模型列表接口：

*   提供 `/v1/models` 接口，返回 Gemini 支持的模型列表，与 OpenAI API 格式兼容。

### 💬 聊天补全接口：

*   提供 `/v1/chat/completions` 接口，支持流式（streaming）和非流式响应，与 OpenAI API 格式兼容。
*   自动将 OpenAI 格式的请求转换为 Gemini 格式。

### 🔒 密码保护（可选）：

*   通过 `PASSWORD` 环境变量设置密码。
*   启用密码保护后，所有请求需要在 `Authorization` 请求头中提供 `Bearer <password>` 令牌。
*   提供默认密码 `"123"`，**强烈建议在生产环境中修改**。

### 🚦 速率限制和防滥用：

*   基于 IP 地址和请求路径进行速率限制。
*   通过环境变量自定义限制：
    *   `MAX_REQUESTS_PER_MINUTE`：每分钟最大请求数（默认 30）。
    *   `MAX_REQUESTS_PER_DAY_PER_IP`：每天每个 IP 最大请求数（默认 600）。
*   超过速率限制时返回 429 错误，并提供详细的错误信息。

### ⚙️ 错误处理和日志：

*   捕获并处理 Gemini API 的常见错误（配额耗尽、服务不可用、无效参数等），返回中文错误信息。
*   全局异常处理，记录所有未处理的异常。
*   通过 `DEBUG` 环境变量控制日志详细程度（默认 `false`，生产环境建议设置为 `false`）。

### 🧩 服务兼容

*   提供的接口与 OpenAI API 格式兼容,便于接入各种服务

## 🛠️ 使用方式：

### 🚀 部署到 Hugging Face Spaces：

1.  创建一个新的 Space。
2.  将本项目代码上传到 Space。
3.  在 Space 的 `Settings` -> `Variables` 中设置以下环境变量：
    *   `GEMINI_API_KEYS`：你的 Gemini API 密钥，用逗号分隔（例如：`key1,key2,key3`）。
    *   `PASSWORD`：（可选）设置访问密码，留空则使用默认密码 `"123"`。
    *   `MAX_REQUESTS_PER_MINUTE`：（可选）每分钟最大请求数。
    *   `MAX_REQUESTS_PER_DAY_PER_IP`：（可选）每天每个 IP 最大请求数。
    *   `DEBUG`：（可选）设置为 `"true"` 启用详细日志，生产环境建议设置为 `"false"`。
4.  确保 `requirements.txt` 文件已包含必要的依赖（`fastapi`, `uvicorn`, `google-generativeai`, `pydantic`）。
5.  Space 将会自动构建并运行。

### 💻 本地运行（可选,未测试）：

1.  安装依赖：`pip install -r requirements.txt`
2.  设置环境变量（如上所述）。
3.  运行：`uvicorn app.main:app --reload --host 0.0.0.0 --port 7860`

### 🌐 API 请求示例（假设 Space 的 URL 为 `https://your-space-url.hf.space`）：

*   **获取模型列表：**

    ```bash
    curl https://your-space-url.hf.space/v1/models
    ```

*   **非流式聊天补全：**

    ```bash
    curl https://your-space-url.hf.space/v1/chat/completions \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer 123" \
      -d '{
        "model": "gemini-pro",
        "messages": [
          {"role": "user", "content": "你好！"}
        ]
      }'
    ```

*   **流式聊天补全：**

    ```bash
    curl https://your-space-url.hf.space/v1/chat/completions \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer 123" \
      -d '{
        "model": "gemini-pro",
        "messages": [
          {"role": "user", "content": "你好！"}
        ],
        "stream": true
      }'
    ```
### 🔌 接入sillytavern

1.  在连接中选择OpenAI
2.  在API Base URL中填入`https://your-space-url.hf.space/v1`
3.  在API Key中填入`PASSWORD`环境变量的值,如未设置则填入`123`

## ⚠️ 注意事项：

*   **强烈建议在生产环境中设置 `PASSWORD` 环境变量，并使用强密码。**
*   根据你的使用情况调整速率限制相关的环境变量。
*   生产环境中建议将 `DEBUG` 设置为 `"false"`，以减少日志量。
*   确保你的 Gemini API 密钥具有足够的配额。