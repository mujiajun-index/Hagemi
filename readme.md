# 🚀 Gemini API Proxy 【图片生成】

项目原作者[@Mrjwj34](https://github.com/Mrjwj34/Hagemi)在此基础进行一些修改更新。
这是一个基于 FastAPI 构建的 Gemini API 代理，旨在提供一个简单、安全且可配置的方式来访问 Google 的 Gemini 模型。适用于在 Hugging Face Spaces 上部署，并支持openai api格式的工具集成，并在此基础上新增兼容支持Gemini最新图片识别、生成、编辑功能，并且适配主流AI聊天客户端，如Chatbox、等。
## 📸 生图示例：
<div style="display: flex; gap: 10px; margin-bottom: 10px;">
    <a href="https://s21.ax1x.com/2025/04/14/pEWYxRs.png" target="_blank"><img src="https://s21.ax1x.com/2025/04/14/pEWYxRs.png" alt="图片生成" style="width: 200px;" /></a>
    <a href="https://s21.ax1x.com/2025/04/14/pEWYIxI.png" target="_blank"><img src="https://s21.ax1x.com/2025/04/14/pEWYIxI.png" alt="图片编辑" style="width: 200px;" /></a>
</div>

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
3.  在 Space 的 `Settings` -> `Secrets` 中设置以下环境变量：
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
*   新增 `auth <you password>` 命令行授权方式，可跳过传统api秘钥方式进行授权。
    为了解决抱脸无法使用 原有api秘钥 Authorization: Bearer 方式进行授权的问题，新增了 auth 命令行授权方式进行授权，只需要在聊天窗口输入如：auth 123 即可进行授权，授权成功后会记录当前授权IP地址，后续此IP访问会自动授权，重启项目后会失效。
*   新增IP白名单:`WHITELIST_IPS` 环境变量可设置白名单IP，多个IP用逗号分隔，如：`127.0.0.1,192.168.1.1`。白名单内的IP会自动授权，不会失效。

## ❤ 新增功能：

1.  新增支持Gemini图片生成功能
    * 支持的生成模型有:
    *   `gemini-2.0-flash-exp`
    *   `gemini-2.0-flash-exp-image-generation`
    *   `gemini-2.0-flash-preview-image-generation`
    * 需要新增如下环境变量：
    *   `HISTORY_IMAGE_SUBMIT_TYPE`：历史生成图片提交方式（默认 `last`）
    *       `last` :只提交最近发来消息中的图片(推荐)
    *       `all`  :提交上下文所有图片
    *   ------------------------------------------------------------------------------------------
    *   `IMAGE_STORAGE_TYPE`：图片存储类型，可选值为 `local`, `memory` , `qiniu` , `tencent` （默认 `memory`）。
    *       `memory`：在内存中存储图片，注意每次重启项目后图片会清空。
    *   `MEMORY_MAX_IMAGE_NUMBER`：内存中存储图片的最大数量，（默认`1000`）仅在 `memory` 模式下有效。
    *   ------------------------------------------------------------------------------------------
    *   `HOST_URL`：你的项目域名地址，如你自己的：`https://your-space-url.hf.space` ,仅在 `local`，`memory` 模式下有效。
    *   `IMAGE_STORAGE_DIR`：本地图片保存地址，默认为 `当前项目的app/images`，仅在 `local` 模式下有效。
    *   ------------------------------------------------------------------------------------------
    *   腾讯云COS存储配置 https://console.cloud.tencent.com/cos
    *   腾讯云访问密钥ID https://console.cloud.tencent.com/cam/capi
    *   `TENCENT_SECRET_ID`：腾讯云访问密钥ID，仅在 `tencent` 模式下有效。
    *   `TENCENT_SECRET_KEY`：腾讯云访问密钥Key，仅在 `tencent` 模式下有效。
    *   `TENCENT_REGION`：腾讯云COS区域，仅在 `tencent` 模式下有效。【最好和服务器同区域】
    *   `TENCENT_BUCKET`：腾讯云COS存储桶名称，仅在 `tencent` 模式下有效。
    *   `TENCENT_DOMAIN`：腾讯云COS存储桶域名，仅在 `tencent` 模式下有效。
    *   ------------------------------------------------------------------------------------------
    *   `QINIU_ACCESS_KEY`：你的七牛云AK，仅在 `qiniu` 模式下有效。
    *   `QINIU_SECRET_KEY`：你的七牛云SK，仅在 `qiniu` 模式下有效。
    *   `QINIU_BUCKET_NAME`：你的七牛云空间名称，仅在 `qiniu` 模式下有效。
    *   `QINIU_BUCKET_DOMAIN`：你的七牛云外链域名，仅在 `qiniu` 模式下有效。

2.  新增支持设置代理URL地址
    * `PROXY_URL`：代理URL地址(用于替换https://generativelanguage.googleapis.com),适用于本地无法访问谷歌的情况
3.  新增支持XAI代理,并支持生成图片功能
    直接访问`https://your-space-url.hf.space/xai/v1`即可,秘钥为XAI秘钥,模型为XAI模型,并支持OpenAI格式调用grok-2-image-1212
    * `XAI_RESPONSE_FORMAT`：XAI图片生成返回格式 `url`:返回URL格式(xai图片地址),`b64_json`:返回base64格式(根据图片存储类型保存)

## 🔗 帮助支持：
QQ交流群：1006840728
[教程地址](http://u5a.cn/r5vSI)

