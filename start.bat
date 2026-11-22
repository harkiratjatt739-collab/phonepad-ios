@echo off
cd /d "%~dp0"
echo Installing requirements (first run only)...
py -m pip install -q aiohttp vgamepad cryptography qrcode
echo.
py server.py
pause
