#!/bin/sh
# 서버 실행 (macOS·Linux·라즈베리파이·안드로이드 Termux)
cd "$(dirname "$0")" && exec python3 server.py "$@"
