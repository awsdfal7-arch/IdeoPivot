@echo off
setlocal

cd /d "%~dp0"

set "APP_VERSION=%~1"
set "ISCC_PATH="

if exist "C:\Install\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Install\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC_PATH if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC_PATH=C:\Program Files\Inno Setup 6\ISCC.exe"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python was not found in PATH.
    exit /b 1
)

if not exist "%~dp0build_windows_onedir.ps1" (
    echo [ERROR] Missing build_windows_onedir.ps1
    exit /b 1
)

if not exist "%~dp0build_windows_installer.ps1" (
    echo [ERROR] Missing build_windows_installer.ps1
    exit /b 1
)

echo [1/2] Building onedir package...
powershell -ExecutionPolicy Bypass -File "%~dp0build_windows_onedir.ps1" -Clean
if errorlevel 1 (
    echo [ERROR] Failed to build onedir package.
    exit /b 1
)

echo [2/2] Building installer package...
if defined APP_VERSION (
    if defined ISCC_PATH (
        powershell -ExecutionPolicy Bypass -File "%~dp0build_windows_installer.ps1" -Clean -AppVersion "%APP_VERSION%" -IsccPath "%ISCC_PATH%"
    ) else (
        powershell -ExecutionPolicy Bypass -File "%~dp0build_windows_installer.ps1" -Clean -AppVersion "%APP_VERSION%"
    )
) else (
    if defined ISCC_PATH (
        powershell -ExecutionPolicy Bypass -File "%~dp0build_windows_installer.ps1" -Clean -IsccPath "%ISCC_PATH%"
    ) else (
        powershell -ExecutionPolicy Bypass -File "%~dp0build_windows_installer.ps1" -Clean
    )
)
if errorlevel 1 (
    echo [ERROR] Failed to build installer package.
    exit /b 1
)

echo [DONE] Installer output:
dir /b "%~dp0installer_output\*.exe"

endlocal
exit /b 0
