@echo off
chcp 65001 >nul
rem 서버 실행 (Windows) — 처음 실행 시 방화벽 허용 창이 뜨면 "개인 네트워크" 허용
cd /d "%~dp0"
set PYTHONUTF8=1
python server.py %*
pause
