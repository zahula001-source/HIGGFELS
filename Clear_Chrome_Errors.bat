@echo off
chcp 65001 >nul
echo ==================================================
echo      DOLA AI - DON DEP CHROME CHAY NGAM & LOI
echo ==================================================
echo.
echo [1] Dang tat toan bo tien trinh chrome.exe bi treo...
taskkill /F /IM chrome.exe /T 2>nul
echo.

echo [2] Dang xoa cac tep khoa (SingletonLock, lock...) trong cac Profile...
del /S /Q "data\browsers\SingletonLock" 2>nul
del /S /Q "data\browsers\SingletonCookie" 2>nul
del /S /Q "data\browsers\SingletonSocket" 2>nul
del /S /Q "data\browsers\lock" 2>nul
del /S /Q "data\browsers\.parentlock" 2>nul
del /S /Q "data\browsers\DevToolsActivePort" 2>nul

echo.
echo ==================================================
echo Da don dep hoan tat! Ban co the mo lai Tool.
echo Bam phim bat ky de thoat...
pause >nul
