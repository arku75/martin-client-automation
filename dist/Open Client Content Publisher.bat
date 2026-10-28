@echo off
title Client Content Publisher
cd /d "%~dp0"

rem Busca Python. En Windows suele estar como "py"; si no, como "python".
where py >nul 2>&1 && (py -3 client_content_publisher.pyz & goto :eof)
where python >nul 2>&1 && (python client_content_publisher.pyz & goto :eof)

echo.
echo   Python is missing. It is the only thing this program needs.
echo.
echo   1. The download page will open.
echo   2. Download Python and run the installer.
echo   3. IMPORTANT: tick the box "Add python.exe to PATH".
echo   4. When it finishes, open this file again.
echo.
pause
start https://www.python.org/downloads/
