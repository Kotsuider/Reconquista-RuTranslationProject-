@echo off
setlocal enabledelayedexpansion

rem ------------------------------------------------------------
rem disassemble_st.bat
rem Disassembles all .mjo scripts from the 'st' folder using maji.exe
rem ------------------------------------------------------------

pushd "%~dp0"

if not exist "st" (
    echo ERROR: Folder 'st' not found.
    popd
    pause
    exit /b 1
)

echo === Disassembling scripts from st folder ===
set /a count=0

for %%F in (st\*.mjo) do (
    echo [%%~nxF] Disassembling...
    maji disassemble "%%F"
    if errorlevel 1 (
        echo [ERROR] Failed to disassemble %%~nxF
    ) else (
        set /a count+=1
    )
)

echo.
echo ===================================================
echo Disassembly completed!
echo Processed files: !count!
echo Results (.mjil, .mjres) are saved in the 'st' folder.
echo ===================================================

popd
pause
exit /b 0
