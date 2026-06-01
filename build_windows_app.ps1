$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonPath = Join-Path $ProjectPath ".venv\Scripts\python.exe"
$VersionFilePath = Join-Path $ProjectPath "VERSION"
$IconPath = Join-Path $ProjectPath "assets\bot_icon.ico"
$DistPath = Join-Path $ProjectPath "dist"
$BuildPath = Join-Path $ProjectPath "build"
$SpecPath = Join-Path $ProjectPath "1SalemBOT.spec"
$EntryPointPath = Join-Path $ProjectPath "main.py"
$MainExePath = Join-Path $DistPath "1SalemBOT\1SalemBOT.exe"
$QtPluginSource = Join-Path $ProjectPath ".venv\Lib\site-packages\PySide6\plugins"

if (-not (Test-Path $PythonPath)) {
    throw "Python virtual environment not found at $PythonPath"
}

if (-not (Test-Path $VersionFilePath)) {
    throw "VERSION file not found at $VersionFilePath"
}

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

    & $PythonPath -m PyInstaller `
        --noconfirm `
        --windowed `
        --name "1SalemBOT" `
        --icon $IconPath `
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

    Write-Host "Desktop build created at $DistPath\1SalemBOT"
}
finally {
    Pop-Location
}
