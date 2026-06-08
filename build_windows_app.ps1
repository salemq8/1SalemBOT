$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$VersionFilePath = Join-Path $ProjectPath "VERSION"
$IconPath = Join-Path $ProjectPath "assets\bot_icon.ico"
$DistPath = Join-Path $ProjectPath "dist"
$BuildPath = Join-Path $ProjectPath "build"
$SpecPath = Join-Path $ProjectPath "1SalemBOT.spec"
$VersionInfoPath = Join-Path $ProjectPath "1SalemBOT_version_info.txt"
$EntryPointPath = Join-Path $ProjectPath "main.py"
$MainExePath = Join-Path $DistPath "1SalemBOT\1SalemBOT.exe"
$QtPluginSource = Join-Path $ProjectPath ".venv\Lib\site-packages\PySide6\plugins"

if (-not (Test-Path $PythonPath)) {
    throw "Python virtual environment not found at $PythonPath"
}

if (-not (Test-Path $VersionFilePath)) {
    throw "VERSION file not found at $VersionFilePath"
}
$AppVersion = (Get-Content -LiteralPath $VersionFilePath -Raw).Trim()
if (-not $AppVersion) {
    throw "VERSION file is empty"
}
$VersionCore = ($AppVersion -split "[-+]")[0]
$VersionParts = @($VersionCore -split "\." | ForEach-Object { [int]$_ })
while ($VersionParts.Count -lt 4) {
    $VersionParts += 0
}
$AppVersionInfo = ($VersionParts[0..3] -join ".")

& $PythonPath -m pip show pyinstaller | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $PythonPath -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install pyinstaller"
    }
}

Push-Location $ProjectPath
try {
    Get-Process | Where-Object {
        $_.ProcessName -eq "1SalemBOT" -and
        $_.Path -and
        $_.Path.StartsWith((Join-Path $ProjectPath "dist-"), [System.StringComparison]::OrdinalIgnoreCase)
    } | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }

    $mainRunning = Get-Process | Where-Object {
        $_.ProcessName -eq "1SalemBOT" -and
        $_.Path -and
        [System.IO.Path]::GetFullPath($_.Path) -eq [System.IO.Path]::GetFullPath($MainExePath)
    } | Select-Object -First 1
    if ($mainRunning) {
        throw "Close the running app from $MainExePath before building again."
    }

    Get-ChildItem -Directory | Where-Object { $_.Name -like "build*" -or $_.Name -like "dist-*" } | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
    }
    Get-ChildItem -Filter "*.spec" -File | ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
    }

    if (Test-Path $BuildPath) {
        Remove-Item -LiteralPath $BuildPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $DistPath) {
        Remove-Item -LiteralPath $DistPath -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $VersionInfoPath) {
        Remove-Item -LiteralPath $VersionInfoPath -Force -ErrorAction SilentlyContinue
    }

@"
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($($VersionParts[0]), $($VersionParts[1]), $($VersionParts[2]), $($VersionParts[3])),
    prodvers=($($VersionParts[0]), $($VersionParts[1]), $($VersionParts[2]), $($VersionParts[3])),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [
          StringStruct('CompanyName', '1SalemQ8'),
          StringStruct('FileDescription', '1SalemBOT'),
          StringStruct('FileVersion', '$AppVersionInfo'),
          StringStruct('InternalName', '1SalemBOT'),
          StringStruct('LegalCopyright', '1SalemQ8'),
          StringStruct('OriginalFilename', '1SalemBOT.exe'),
          StringStruct('ProductName', '1SalemBOT'),
          StringStruct('ProductVersion', '$AppVersionInfo')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -LiteralPath $VersionInfoPath -Encoding UTF8

    & $PythonPath -m PyInstaller `
        --noconfirm `
        --windowed `
        --name "1SalemBOT" `
        --icon $IconPath `
        --version-file $VersionInfoPath `
        --collect-data certifi `
        --collect-data PySide6 `
        --collect-binaries PySide6 `
        --add-data "assets;assets" `
        --add-data "VERSION;." `
        --add-data "$QtPluginSource;PySide6\plugins" `
        $EntryPointPath

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed"
    }

    if (Test-Path $SpecPath) {
        Remove-Item -LiteralPath $SpecPath -Force
    }
    if (Test-Path $VersionInfoPath) {
        Remove-Item -LiteralPath $VersionInfoPath -Force
    }

    Write-Host "Desktop build created at $DistPath\1SalemBOT"
}
finally {
    Pop-Location
}
