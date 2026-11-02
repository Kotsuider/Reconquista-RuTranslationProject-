@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

pushd "%~dp0"

if not exist "st" (
    echo [ERROR] Pristine folder 'st' not found.
    echo Please place original files in 'st' and run disassemble_st.bat first.
    popd
    pause
    exit /b 1
)

if not exist "majiro_arc.py" (
    echo [ERROR] majiro_arc.py not found next to this script.
    popd
    pause
    exit /b 1
)

set "TL_SOURCE="
if exist "Owari" (
    set "TL_SOURCE=Owari"
) else if exist "Owari.xlsx" (
    set "TL_SOURCE=Owari.xlsx"
) else if exist "..\Owari.xlsx" (
    set "TL_SOURCE=..\Owari.xlsx"
)

if "%TL_SOURCE%"=="" (
    echo [ERROR] Translation source 'Owari' folder or 'Owari.xlsx' not found.
    popd
    pause
    exit /b 1
)

echo ============================================================
echo   Building translation for Owari no Sekai to Birthday
echo   Source: %TL_SOURCE%
echo ============================================================
echo.

echo [1/9] Preparing clean scenario directory from st...
if not exist "scenario" mkdir "scenario"
copy /Y "st\*.mjil" "scenario\" >nul
copy /Y "st\*.mjres" "scenario\" >nul
echo Clean disassemblies copied from st to scenario.
python patch_furigana.py "scenario"
if errorlevel 1 (
    echo [ERROR] Furigana patching failed!
    popd
    pause
    exit /b 1
)
python patch_web_font.py "scenario" --font "M+ 1m regular"
if errorlevel 1 (
    echo [ERROR] Web font patching failed!
    popd
    pause
    exit /b 1
)
echo.
echo [2/9] Inserting choice menu translations from choices.md...
if exist "choices.md" (
    python "%~dp0choices_tool.py" apply "choices.md" "scenario"
    if errorlevel 1 (
        echo [ERROR] choices_tool.py apply failed!
        popd
        pause
        exit /b 1
    )
) else (
    echo   WARNING: choices.md not found - choice menus will stay in Japanese.
)

echo.
echo [3/9] Inserting SNS chat translations from sns.md...
if exist "sns.md" (
    python "%~dp0sns_tool.py" apply "sns.md" "scenario"
    if errorlevel 1 (
        echo [ERROR] sns_tool.py apply failed!
        popd
        pause
        exit /b 1
    )
) else (
    echo   WARNING: sns.md not found - SNS chat will stay in Japanese.
)
python patch_sns_popups.py "scenario"
if errorlevel 1 (
    echo [ERROR] patch_sns_popups.py failed!
    popd
    pause
    exit /b 1
)

echo.
echo [4/9] Inserting translations into .mjres...
python mjres_tool.py insert "%TL_SOURCE%" -o "scenario"
if errorlevel 1 (
    echo [ERROR] Translation insertion failed!
    popd
    pause
    exit /b 1
)

echo.
echo [5/9] Applying line wrapping...
python wrap_mjres.py "scenario"
if errorlevel 1 (
    echo [ERROR] Line wrapping failed!
    popd
    pause
    exit /b 1
)

echo.
echo [6/9] Sanitizing Unicode characters for CP932...
python sanitize_mjres.py "scenario"
if errorlevel 1 (
    echo [ERROR] Sanitization failed!
    popd
    pause
    exit /b 1
)

echo.
echo [7/9] Assembling scripts via maji.exe...
set /a count_assembled=0
for %%F in (scenario\*.mjil) do (
    maji.exe assemble "%%F"
    if errorlevel 1 (
        echo [ERROR] Assembly failed for %%~nxF!
        popd
        pause
        exit /b 1
    )
    set /a count_assembled+=1
)
echo Successfully assembled: !count_assembled! scripts.

echo.
echo [8/9] Packaging to scenario_tl...
if not exist "scenario_tl" mkdir "scenario_tl"

copy /Y "scenario\*.mjo" "scenario_tl\" >nul

if exist "Owari\Other_tr\*.mail" copy /Y "Owari\Other_tr\*.mail" "scenario_tl\" >nul
if exist "Owari\Other_tr\*.blog" copy /Y "Owari\Other_tr\*.blog" "scenario_tl\" >nul
if exist "Owari\Other_tr\*.profile" copy /Y "Owari\Other_tr\*.profile" "scenario_tl\" >nul

if exist "st\*.cfg" copy /Y "st\*.cfg" "scenario_tl\" >nul
if exist "st\*.winmerge" copy /Y "st\*.winmerge" "scenario_tl\" >nul

echo.
echo [9/9] Packing scenario_tl into an archive...
if not exist "scenario_tl\*.mjo" (
    echo [ERROR] scenario_tl contains no .mjo files - nothing to pack.
    popd
    pause
    exit /b 1
)

rem The game archive is MajiroArcV1.000, so pack version 1
python "%~dp0majiro_arc.py" pack "scenario_tl" "scenario_tl.arc" --version 1
if errorlevel 1 (
    echo [ERROR] Packing failed!
    popd
    pause
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
    echo [WARN] Entry count changed !OLD_COUNT! -^> !NEW_COUNT!
    echo        check scenario_tl for stale or missing files.
)

python "%~dp0majiro_arc.py" verify "scenario_tl.arc"
if errorlevel 1 (
    echo [ERROR] Archive verification failed - nothing was deployed.
    popd
    pause
    exit /b 1
)

rem One-time backup of the archive that was in the game root before the first build
if not exist "..\scenario.arc.bak" (
    if exist "..\scenario.arc" (
        copy /Y "..\scenario.arc" "..\scenario.arc.bak" >nul
        echo   Backed up the previous archive to ..\scenario.arc.bak
    )
)

move /Y "scenario_tl.arc" "..\scenario.arc" >nul
if errorlevel 1 (
    echo [ERROR] Failed to move the archive to ..\scenario.arc
    popd
    pause
    exit /b 1
)
echo   Deployed ..\scenario.arc

echo.
echo ============================================================
echo   BUILD COMPLETED SUCCESSFULLY!
echo   Output folder: scenario_tl
echo   Archive deployed to: ..\scenario.arc
echo ============================================================
echo.

popd
exit /b 0
