param(
    [string]$Python = "python",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Push-Location $ProjectRoot
try {
    if ($Clean) {
        Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force dist -ErrorAction SilentlyContinue
    }

    & $Python -m pip install -r requirements.txt
    & $Python -m pip install -r requirements-packaging.txt
    & $Python -m PyInstaller --noconfirm .\pyinstaller_onedir.spec
}
finally {
    Pop-Location
}
