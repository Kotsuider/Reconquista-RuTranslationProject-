@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ------------------------------------------------------------
rem build_translation.bat
rem 1. Copies pristine disassemblies (.mjil, .mjres) from st into scenario
rem 2. Inserts translations from Reqonquista.xlsx into scenario/*.mjres
rem 3. Sanitises incompatible Unicode characters
rem 4. Assembles scenario/*.mjil using maji.exe
rem 5. Copies compiled .mjo files, config.mjo, and CSV data into scenario_tl
rem ------------------------------------------------------------

pushd "%~dp0"

if not exist "..\Reqonquista.xlsx" (
    echo ERROR: Reqonquista.xlsx not found in parent directory.
    popd
    exit /b 1
)

if not exist "st" (
    echo ERROR: Pristine folder 'st' not found. Run disassemble_st.bat first.
    popd
    exit /b 1
)

echo === Step 1: Preparing clean scenario directory from st ===
if not exist "scenario" mkdir "scenario"

rem Copy clean original .mjil and .mjres from st to scenario
copy /Y "st\*.mjil" "scenario\" >nul
copy /Y "st\*.mjres" "scenario\" >nul
echo Clean disassemblies copied from st to scenario.

echo === Step 2: Inserting translations from Excel ===
python mjres_tool.py insert "..\Reqonquista.xlsx" -o "scenario"
if errorlevel 1 (
    echo ERROR: mjres_tool.py failed.
    popd
    exit /b 1
)

echo === Step 3: Wrapping long lines to prevent mid-word breaks ===
python wrap_mjres.py "scenario"
if errorlevel 1 (
    echo ERROR: wrap_mjres.py failed.
    popd
    exit /b 1
)

echo === Step 4: Sanitising Unicode characters ===
python sanitize_mjres.py
if errorlevel 1 (
    echo ERROR: Sanitisation failed.
    popd
    exit /b 1
)

echo === Step 5: Assembling scripts ===
for %%F in (scenario\*.mjil) do (
    echo   Assembling %%~nxF ...
    maji assemble "%%F"
    if errorlevel 1 (
        echo ERROR: Assembly failed for %%~nxF
        popd
        exit /b 1
    )
)

echo === Step 5: Copying to scenario_tl ===
if not exist "scenario_tl" mkdir "scenario_tl"
for %%F in (scenario\*.mjo) do (
    copy /Y "%%F" "scenario_tl\%%~nxF" >nul
    echo   Copied %%~nxF
)
if exist "config.mjo" (
    copy /Y "config.mjo" "scenario_tl\config.mjo" >nul
    echo   Copied config.mjo
)
rem Copy CSV data files from original scenario folder
if exist "..\scenario\*.csv" (
    copy /Y "..\scenario\*.csv" "scenario_tl\" >nul
    echo   Copied CSV data files
)

echo.
echo ============================================
echo Build completed! Output in scenario_tl
echo ============================================
popd
exit /b 0