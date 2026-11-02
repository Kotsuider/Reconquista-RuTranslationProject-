@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

pushd "%~dp0"

echo ============================================================
echo   Патчер системного меню окна (.exe)
echo ============================================================
echo.

if exist "patch_menu.exe" (
    patch_menu.exe
) else if exist "patch_exe_menu.py" (
    python patch_exe_menu.py menu_translation.json
) else (
    echo [ERROR] patch_menu.exe или patch_exe_menu.py не найдены!
)

echo.
pause
popd
exit /b 0
