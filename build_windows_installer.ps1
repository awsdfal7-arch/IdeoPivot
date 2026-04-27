param(
    [string]$AppVersion = "",
    [string]$IsccPath = "",
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$DistParent = Join-Path $ProjectRoot "dist"
$InstallerScript = Join-Path $ProjectRoot "installer_inno.iss"
$OutputDir = Join-Path $ProjectRoot "installer_output"
$OutputBaseName = "sj-generator-setup-cn-dev"

function Resolve-IsccPath {
    param([string]$Candidate)

    if ($Candidate -and (Test-Path $Candidate)) {
        return $Candidate
    }

    $common = @(
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    )
    foreach ($path in $common) {
        if (Test-Path $path) {
            return $path
        }
    }

    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return ""
}

Push-Location $ProjectRoot
try {
    $distExe = Get-ChildItem -Path $DistParent -Filter *.exe -Recurse -File -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $distExe) {
        throw "Missing dist output. Build the PyInstaller onedir package first."
    }

    if ($Clean) {
        Remove-Item -Recurse -Force $OutputDir -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

    $resolvedIscc = Resolve-IsccPath -Candidate $IsccPath
    if (-not $resolvedIscc) {
        throw "ISCC.exe was not found. Install Inno Setup 6 first, or pass -IsccPath."
    }

    if ($AppVersion) {
        $env:SJ_GENERATOR_APP_VERSION = $AppVersion
        $OutputBaseName = "sj-generator-setup-cn-$AppVersion"
    }

    & $resolvedIscc ("/O" + $OutputDir) ("/F" + $OutputBaseName) $InstallerScript
}
finally {
    Pop-Location
}
