@echo off
chcp 65001 >nul
cd /d %~dp0backend
if not exist .venv (
    echo [首次运行] 正在创建虚拟环境并安装依赖，需要联网，请稍候...
    python -m venv .venv
    .venv\Scripts\pip install -q -r requirements.txt
)
echo.
echo   Dart GCS:  http://127.0.0.1:8787
echo   浏览器打开上述地址；关闭本窗口即停止上位机
echo.
.venv\Scripts\python -m app.main
