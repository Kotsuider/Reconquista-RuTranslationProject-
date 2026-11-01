@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ------------------------------------------------------------
rem build_translation.bat
rem 1. Copies pristine disassemblies (.mjil, .mjres) from st into scenario
rem 2. Inserts choice menu translations from choices.md into scenario/*.mjil
rem 3. Inserts translations from Reqonquista.xlsx into scenario/*.mjres
rem 4. Wraps long lines to prevent mid-word breaks
rem 5. Sanitises incompatible Unicode characters
rem 6. Assembles scenario/*.mjil using maji.exe
rem 7. Copies compiled .mjo files, config.mjo and CSV data into scenario_tl
rem 8. Packs scenario_tl into scenario_tl.arc using majiro_arc.py
rem 9. Deploys the archive to the game root as ..\scenario.arc
rem ------------------------------------------------------------

pushd "%~dp0"

if not exist "Reqonquista.xlsx" (
    echo ERROR: Reqonquista.xlsx not found in parent directory.
    popd
    exit /b 1
)

if not exist "st" (
    echo ERROR: Pristine folder 'st' not found. Run disassemble_st.bat first.
    popd
    exit /b 1
)

if not exist "majiro_arc.py" (
    echo ERROR: majiro_arc.py not found next to this script.
    popd
    exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python not found in PATH.
    popd
    exit /b 1
)

echo === Step 1: Preparing clean scenario directory from st ===
if not exist "scenario" mkdir "scenario"

rem Copy clean original .mjil and .mjres from st to scenario
copy /Y "st\*.mjil" "scenario\" >nul
copy /Y "st\*.mjres" "scenario\" >nul
echo Clean disassemblies copied from st to scenario.

echo === Step 1b: Patching furigana and rubies ===
python "%~dp0patch_reko_furigana.py" "scenario"
if errorlevel 1 (
    echo ERROR: patch_reko_furigana.py failed.
    popd
    exit /b 1
)

echo === Step 1c: Patching fonts and UI dialogs ===
python "%~dp0patch_reko_fonts_and_ui.py" "scenario"
if errorlevel 1 (
    echo ERROR: patch_reko_fonts_and_ui.py failed.
    popd
    exit /b 1
)

echo === Step 2: Inserting choice translations into scenario/*.mjil ===
if exist "choices.md" (
    python "%~dp0choices_tool.py" apply "choices.md" "scenario"
    if errorlevel 1 (
        echo ERROR: choices_tool.py apply failed.
        popd
        exit /b 1
    )
) else (
    echo   WARNING: choices.md not found - choice menus will stay in Japanese.
)

echo === Step 3: Inserting translations from Excel ===
python mjres_tool.py insert "Reqonquista.xlsx" -o "scenario"
if errorlevel 1 (
    echo ERROR: mjres_tool.py failed.
    popd
    exit /b 1
)

echo === Step 4: Wrapping long lines to prevent mid-word breaks ===
python wrap_mjres.py "scenario"
if errorlevel 1 (
    echo ERROR: wrap_mjres.py failed.
    popd
    exit /b 1
)

echo === Step 5: Sanitising Unicode characters ===
python sanitize_mjres.py
if errorlevel 1 (
    echo ERROR: Sanitisation failed.
    popd
    exit /b 1
)

echo === Step 6: Assembling scripts ===
for %%F in (scenario\*.mjil) do (
    echo   Assembling %%~nxF ...
    maji assemble "%%F"
    if errorlevel 1 (
        echo ERROR: Assembly failed for %%~nxF
        popd
        exit /b 1
    )
)

echo === Step 7: Copying to scenario_tl ===
if not exist "scenario_tl" mkdir "scenario_tl"
for %%F in (scenario\*.mjo) do (
    copy /Y "%%F" "scenario_tl\%%~nxF" >nul
    echo   Copied %%~nxF
)
rem config.mjo is compiled dynamically from scenario\config.mjil with font unlocks
rem if exist "config.mjo" copy /Y "config.mjo" "scenario_tl\config.mjo" >nul
rem Copy CSV data files from original scenario folder
if exist "..\scenario\*.csv" (
    copy /Y "..\scenario\*.csv" "scenario_tl\" >nul
    echo   Copied CSV data files
)

echo === Step 8: Packing scenario_tl into an archive ===
if not exist "scenario_tl\*.mjo" (
    echo ERROR: scenario_tl contains no .mjo files - nothing to pack.
    popd
    exit /b 1
)

rem The game archive is MajiroArcV1.000, so pack version 1
python "%~dp0majiro_arc.py" pack "scenario_tl" "scenario_tl.arc" --version 1
if errorlevel 1 (
    echo ERROR: Packing failed.
    popd
    exit /b 1
)

rem Sanity check: the new archive should hold as many files as the one it replaces
set "OLD_COUNT=n/a"
if exist "..\scenario.arc" (
    for /f %%C in ('python "%~dp0majiro_arc.py" count "..\scenario.arc"') do set "OLD_COUNT=%%C"
)
set "NEW_COUNT=?"
for /f %%C in ('python "%~dp0majiro_arc.py" count "scenario_tl.arc"') do set "NEW_COUNT=%%C"
echo   Entries in new archive: !NEW_COUNT!  ^(current ..\scenario.arc: !OLD_COUNT!^)
if not "!OLD_COUNT!"=="n/a" if not "!OLD_COUNT!"=="!NEW_COUNT!" (
    echo WARNING: entry count changed !OLD_COUNT! -^> !NEW_COUNT!
    echo          check scenario_tl for stale or missing files
)

python "%~dp0majiro_arc.py" verify "scenario_tl.arc"
if errorlevel 1 (
    echo ERROR: Archive verification failed - nothing was deployed.
    popd
    exit /b 1
)

echo === Step 9: Deploying archive to the game root ===
rem Keep a one-time copy of the archive that was there before the first build
if not exist "..\scenario.arc.bak" (
    if exist "..\scenario.arc" (
        copy /Y "..\scenario.arc" "..\scenario.arc.bak" >nul
        echo   Backed up the previous archive to ..\scenario.arc.bak
    )
)
move /Y "scenario_tl.arc" "..\scenario.arc" >nul
if errorlevel 1 (
    echo ERROR: Failed to move the archive to ..\scenario.arc
    popd
    exit /b 1
)
echo   Deployed ..\scenario.arc

echo.
echo ============================================
echo Build completed! Output in scenario_tl
echo Archive deployed to ..\scenario.arc
echo ============================================
popd
exit /b 0
