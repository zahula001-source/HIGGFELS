@echo off
chcp 65001 >nul
title IP Changer Tool
cd /d "%~dp0"

REM ---------- Kiem tra Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [LOI] May chua cai Python.
    echo  1. Tai tai https://www.python.org/downloads/
    echo  2. Khi cai, nho TICK o "Add Python to PATH"
    echo  3. Cai xong mo lai file .bat nay
    echo.
    pause
    exit /b 1
)

REM ---------- Cai pywinauto neu thieu ----------
python -c "import pywinauto" >nul 2>nul
if errorlevel 1 (
    echo Dang cai pywinauto, cho chut...
    python -m pip install --quiet pywinauto
)

REM ---------- Che do tich hop: .bat kem tham so thi chay lenh roi thoat ----------
REM Vi du tool khac goi:  HMA_IP_Changer.bat switch    hoac    country "USA"
if not "%~1"=="" (
    python hma_app_switcher.py %*
    exit /b %errorlevel%
)

:MENU
cls
echo ================================================
echo    HMA IP CHANGER - doi IP khong can dong tay
echo    yeu cau: app HMA VPN dang mo
echo ================================================
echo.
echo    1. Xem trang thai + IP hien tai
echo    2. Ket noi VPN
echo    3. DOI IP NGAY - giu nguyen quoc gia
echo    4. Debug - in cac nut bam trong app HMA
echo    5. DOI SANG NUOC KHAC - nhap ten nuoc
echo    6. DOI SANG MOT NUOC NGAU NHIEN
echo    0. Thoat
echo.
set /p CHOICE=Chon [0-6]:

if "%CHOICE%"=="0" exit /b 0
if "%CHOICE%"=="1" python hma_app_switcher.py status
if "%CHOICE%"=="2" python hma_app_switcher.py connect
if "%CHOICE%"=="3" python hma_app_switcher.py switch
if "%CHOICE%"=="4" python hma_app_switcher.py debug
if "%CHOICE%"=="5" goto COUNTRY
if "%CHOICE%"=="6" python hma_app_switcher.py randomcountry
goto END

:COUNTRY
echo.
set /p CN=Nhap ten nuoc, vi du USA - Germany - Japan - UK :
python hma_app_switcher.py country "%CN%"

:END
echo.
pause
goto MENU
