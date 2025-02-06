# 🚀 Gemini API Proxy

本项目基于某论坛上一位大佬@Moonfanzp的代码修改而来,但鉴于本人能力水平有限,所以项目可能出现~~大量~~一些bug,请谨慎使用,下面是介绍:
这是一个基于 FastAPI 构建的 Gemini API 代理，旨在提供一个简单、安全且可配置的方式来访问 Google 的 Gemini 模型。适用于在 Hugging Face Spaces 上部署，并支持openai api格式的工具集成。

## ✨ 主要功能：

### 🔑 API 密钥轮询和管理

### 📑 模型列表接口

### 💬 聊天补全接口：

*   提供 `/v1/chat/completions` 接口，支持流式（streaming）和非流式响应，与 OpenAI API 格式兼容。
*   自动将 OpenAI 格式的请求转换为 Gemini 格式。

### 🔒 密码保护（可选）：

*   通过 `PASSWORD` 环境变量设置密码。
*   提供默认密码 `"123"`。

### 🚦 速率限制和防滥用：

*   通过环境变量自定义限制：
    *   `MAX_REQUESTS_PER_MINUTE`：每分钟最大请求数（默认 30）。
    *   `MAX_REQUESTS_PER_DAY_PER_IP`：每天每个 IP 最大请求数（默认 600）。
*   超过速率限制时返回 429 错误。

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
    ...(还有一些变量,但是没啥大用,可以到代码里找)
4.  确保 `requirements.txt` 文件已包含必要的依赖。
5.  Space 将会自动构建并运行。
6.  URL格式为`https://your-space-url.hf.space`。

### 💻 本地运行（可选,未测试但是应该能行）：

1.  安装依赖：`pip install -r requirements.txt`
2.  设置环境变量（如上所述）。
3.  运行：`uvicorn app.main:app --reload --host 0.0.0.0 --port 7860`

### 🔌 接入其他服务

1.  在连接中选择OpenAI
2.  在API Base URL中填入`https://your-space-url.hf.space/v1`
3.  在API Key中填入`PASSWORD`环境变量的值,如未设置则填入`123`

## ⚠️ 注意事项：

*   **强烈建议在生产环境中设置 `PASSWORD` 环境变量，并使用强密码。**
*   根据你的使用情况调整速率限制相关的环境变量。
*   确保你的 Gemini API 密钥具有足够的配额。
