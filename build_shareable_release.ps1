$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildScriptPath = Join-Path $ProjectPath "build_windows_app.ps1"
$VersionFilePath = Join-Path $ProjectPath "VERSION"
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
$ReleaseRoot = Join-Path $ProjectPath "shareable"
$PortableName = "1SalemBOT-Portable-v$AppVersion"
$PortablePath = Join-Path $ReleaseRoot $PortableName
$PortableZipPath = Join-Path $ReleaseRoot "1SalemBOT_Portable_v$AppVersion.zip"
$InstallerScriptPath = Join-Path $ProjectPath "installer.iss"
$InstallerOutputPath = Join-Path $ReleaseRoot "1SalemBOT_Setup_v$AppVersion.exe"
$BuiltAppPath = Join-Path $ProjectPath "dist\1SalemBOT"
$VlcSourcePath = Join-Path ${env:ProgramFiles} "VideoLAN\VLC"
$VlcTargetPath = Join-Path $PortablePath "vlc"
$LauncherPath = Join-Path $PortablePath "Launch 1SalemBOT Portable.bat"
$ReadmePath = Join-Path $PortablePath "README.txt"
$InnoCompilerPath = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "C:\Users\Asrok\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not (Test-Path $BuildScriptPath)) {
    throw "build_windows_app.ps1 not found at $BuildScriptPath"
}

if (-not (Test-Path $InstallerScriptPath)) {
    throw "installer.iss not found at $InstallerScriptPath"
}

if (-not $InnoCompilerPath) {
    throw "Inno Setup compiler was not found. Install Inno Setup 6 first."
}

if (Test-Path $ReleaseRoot) {
    Remove-Item -LiteralPath $ReleaseRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseRoot | Out-Null

& powershell -ExecutionPolicy Bypass -File $BuildScriptPath
if ($LASTEXITCODE -ne 0) {
    throw "Desktop build failed"
}

if (-not (Test-Path $BuiltAppPath)) {
    throw "Built app folder not found at $BuiltAppPath"
}

Copy-Item -LiteralPath $BuiltAppPath -Destination $PortablePath -Recurse

if (-not (Test-Path $VlcSourcePath)) {
    throw "VLC runtime folder not found at $VlcSourcePath"
}

New-Item -ItemType Directory -Path $VlcTargetPath | Out-Null

$vlcFolders = @("plugins", "locale", "lua", "hrtfs")
foreach ($folderName in $vlcFolders) {
    $sourceFolder = Join-Path $VlcSourcePath $folderName
    if (Test-Path $sourceFolder) {
        Copy-Item -LiteralPath $sourceFolder -Destination (Join-Path $VlcTargetPath $folderName) -Recurse
    }
}

$vlcFiles = @("libvlc.dll", "libvlccore.dll", "vlc-cache-gen.exe")
foreach ($fileName in $vlcFiles) {
    $sourceFile = Join-Path $VlcSourcePath $fileName
    if (Test-Path $sourceFile) {
        Copy-Item -LiteralPath $sourceFile -Destination (Join-Path $VlcTargetPath $fileName)
    }
}

@"
@echo off
setlocal
set "SALEMBOT_DATA_DIR=%~dp0user-data"
if not exist "%SALEMBOT_DATA_DIR%" mkdir "%SALEMBOT_DATA_DIR%"
start "" "%~dp01SalemBOT.exe"
"@ | Set-Content -LiteralPath $LauncherPath -Encoding ASCII

@"
1SalemBOT Portable v$AppVersion
==================

This portable build is ready to run on another Windows PC.

What it includes:
- Main desktop app
- Bundled Qt/runtime dependencies
- Bundled VLC runtime for music playback

What it does NOT include:
- Twitch tokens
- API keys
- chat history
- local settings from the developer machine

How to use:
1. Extract the whole folder anywhere.
2. Launch "Launch 1SalemBOT Portable.bat".
3. Complete Twitch setup with your own accounts.

Notes:
- The portable launcher stores app data in the local "user-data" folder next to the app.
- The installed version uses the normal Windows AppData profile instead.
"@ | Set-Content -LiteralPath $ReadmePath -Encoding UTF8

$unexpectedSensitiveFiles = Get-ChildItem -LiteralPath $PortablePath -Recurse -File |
    Where-Object {
        $_.FullName -notlike "*\user-data\*" -and
        @("settings.json", "users.json", "dashboard_state.json", "music_command.json", "chat_log.txt", "twitch_bot_auth.json", "twitch_channel_auth.json") -contains $_.Name
    }

if ($unexpectedSensitiveFiles) {
    $unexpectedSensitiveFiles | Select-Object FullName | Format-Table -AutoSize | Out-String | Write-Host
    throw "Sensitive runtime files were found in the portable package"
}

if (Test-Path $PortableZipPath) {
    Remove-Item -LiteralPath $PortableZipPath -Force
}
Compress-Archive -Path (Join-Path $PortablePath "*") -DestinationPath $PortableZipPath -Force

if (Test-Path $InstallerOutputPath) {
    Remove-Item -LiteralPath $InstallerOutputPath -Force
}

$installerProcess = Start-Process -FilePath $InnoCompilerPath `
    -ArgumentList @(
        "/DMyAppVersion=$AppVersion",
        "/DMyAppVersionInfo=$AppVersionInfo",
        "/DMyAppSource=$PortablePath",
        "/DMyInstallerOutput=$ReleaseRoot",
        $InstallerScriptPath
    ) `
    -PassThru

if (-not $installerProcess.WaitForExit(300000)) {
    if (Test-Path $InstallerOutputPath) {
        Stop-Process -Id $installerProcess.Id -Force -ErrorAction SilentlyContinue
    } else {
        Stop-Process -Id $installerProcess.Id -Force -ErrorAction SilentlyContinue
        throw "Installer build timed out before producing the setup file"
    }
}

if (-not (Test-Path $InstallerOutputPath)) {
    throw "Installer build failed"
}

Write-Host "Portable build created at $PortablePath"
Write-Host "Portable zip created at $PortableZipPath"
Write-Host "Installer created at $InstallerOutputPath"
