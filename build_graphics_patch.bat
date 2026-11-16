@echo off
setlocal
pushd "%~dp0" || exit /b 1

if not exist "graphics_patch\*" (
    mkdir "graphics_patch" || goto fail
    echo Put replacement files in graphics_patch and run this batch file again.
    popd
    exit /b 0
)

dir /b /s /a-d "graphics_patch\*" >nul 2>&1
if errorlevel 1 (
    echo Put replacement files in graphics_patch and run this batch file again.
    popd
    exit /b 0
)

set "build=update.arc.%RANDOM%.%RANDOM%.tmp"
set "maskdir=%build%.masks"
set "ready=%build%"
python "ToMajiTools\majiro_arc.py" pack "graphics_patch" "%build%" --version 2 --strict
if errorlevel 1 goto fail
if exist "graphics_patch\skip_.png" (
    mkdir "%maskdir%" || goto fail
    python -c "import PIL" >nul 2>&1
    if errorlevel 1 (
        py -3.10 "ToMajiTools\encode_rc8_mask.py" "graphics_patch\skip_.png" "%maskdir%\skip_.rc8"
    ) else (
        python "ToMajiTools\encode_rc8_mask.py" "graphics_patch\skip_.png" "%maskdir%\skip_.rc8"
    )
    if errorlevel 1 goto fail
    python "ToMajiTools\majiro_arc.py" repack "%build%" "%maskdir%" "%build%.rc8" --strict
    if errorlevel 1 goto fail
    set "ready=%build%.rc8"
)
python "ToMajiTools\majiro_arc.py" verify "%ready%"
if errorlevel 1 goto fail
move /y "%ready%" "update.arc" >nul
if errorlevel 1 goto fail
call :cleanup
echo Created update.arc.
popd
exit /b 0

:fail
call :cleanup
echo Failed to build update.arc.
popd
exit /b 1


:cleanup
if exist "%build%" del "%build%"
if exist "%build%.rc8" del "%build%.rc8"
if exist "%maskdir%\skip_.rc8" del "%maskdir%\skip_.rc8"
if exist "%maskdir%" rmdir "%maskdir%"
exit /b 0
