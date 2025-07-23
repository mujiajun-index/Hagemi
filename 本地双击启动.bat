@echo off
chcp 65001
echo 正在安装依赖...
pip install -r requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo 依赖安装失败，请检查错误信息。
    pause
    exit /b %ERRORLEVEL%
)

echo 依赖安装成功，正在启动服务...
echo 服务将在 http://localhost:7860 上运行
echo.
echo 按 Ctrl+C 可以停止服务
echo.

set PYTHONIOENCODING=utf-8
uvicorn app.main:app --reload --host 0.0.0.0 --port 7860