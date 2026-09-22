@echo off
chcp 65001 >nul
title Cai dat Antidetect Tool - Lan dau chay file nay

echo.
echo ============================================
echo   CAI DAT ANTIDETECT TOOL - LAN DAU TIEN
echo ============================================
echo.

:: Kiem tra Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Chua co Python! Dang tai tu winget...
    winget install Python.Python.3.11 -e --silent
    echo Cai xong, chay lai file setup.bat nhe!
    pause
    exit
)

echo [OK] Python da co san
echo.

:: Cai pip packages
echo [1/3] Dang cai thu vien Python...
pip install fastapi uvicorn[standard] playwright pydantic aiofiles python-multipart requests cloakbrowser --quiet
if errorlevel 1 (
    echo [LOI] Cai thu vien that bai! Kiem tra ket noi mang.
    pause
    exit
)
echo [OK] Thu vien da cai xong
echo.

:: Cai Playwright browsers (chi Chrome)
echo [2/3] Dang cai trinh duyet Chrome cho Playwright...
playwright install chromium
if errorlevel 1 (
    echo [LOI] Cai Chrome that bai!
    pause
    exit
)
echo [OK] Chrome da cai xong
echo.

:: Tao thu muc data neu chua co
echo [3/3] Tao cau truc thu muc...
if not exist "data" mkdir data
if not exist "data\logs" mkdir data\logs
if not exist "data\extensions" mkdir data\extensions
if not exist "static" mkdir static
echo [OK] Thu muc san sang
echo.

echo ============================================
echo   CAI DAT HOAN TAT!
echo   Gio hay chay file: start.bat
echo ============================================
echo.
pause
