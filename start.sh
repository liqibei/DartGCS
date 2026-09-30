#!/usr/bin/env bash
# Dart GCS 一键启动（Ubuntu / RK3588 等 Linux）
cd "$(dirname "$0")/backend"
if [ ! -d .venv ]; then
    echo "[首次运行] 正在创建虚拟环境并安装依赖，需要联网，请稍候..."
    python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt
fi
echo
echo "  Dart GCS:  http://127.0.0.1:8787"
echo
exec .venv/bin/python -m app.main
