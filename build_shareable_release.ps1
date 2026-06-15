param(
    [ValidateSet("Auto", "Beta", "Stable")]
    [string]$Channel = "Auto"
)

$ErrorActionPreference = "Stop"

$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildScriptPath = Join-Path $ProjectPath "build_windows_app.ps1"
$VersionFilePath = Join-Path $ProjectPath "VERSION"
$VersionChannelFilePath = Join-Path $ProjectPath "VERSION_CHANNEL"
if (-not (Test-Path $VersionFilePath)) {
    throw "VERSION file not found at $VersionFilePath"
}
$AppVersion = (Get-Content -LiteralPath $VersionFilePath -Raw).Trim()
if (-not $AppVersion) {
    throw "VERSION file is empty"
}

function Resolve-VersionChannel {
    param([string]$RequestedChannel, [string]$ChannelFilePath)
    $rawChannel = $RequestedChannel
    if ($rawChannel -eq "Auto") {
        if (Test-Path -LiteralPath $ChannelFilePath) {
            $rawChannel = (Get-Content -LiteralPath $ChannelFilePath -Raw).Trim()
        } else {
            $rawChannel = "Stable"
        }
    }
    switch -Regex ($rawChannel.ToLowerInvariant()) {
        "^(beta|development|dev|local|testing)$" { return "Beta" }
        "^(stable|release|public|production)$" { return "Stable" }
        default { throw "Unsupported VERSION_CHANNEL value: $rawChannel" }
    }
}

$ResolvedChannel = Resolve-VersionChannel -RequestedChannel $Channel -ChannelFilePath $VersionChannelFilePath
$IsBeta = $ResolvedChannel -eq "Beta"
$AppVersionLabel = if ($IsBeta) { "$AppVersion Beta" } else { $AppVersion }
$AppVersionTag = if ($IsBeta) { "$($AppVersion)_Beta" } else { $AppVersion }
$AppSourceVersionTag = if ($IsBeta) { "$AppVersion-Beta" } else { $AppVersion }
$VersionJsonVersion = $AppVersionLabel
$VersionJsonChannel = $ResolvedChannel.ToLowerInvariant()
$VersionCore = ($AppVersion -split "[-+]")[0]
$VersionParts = @($VersionCore -split "\." | ForEach-Object { [int]$_ })
while ($VersionParts.Count -lt 4) {
    $VersionParts += 0
}
$AppVersionInfo = ($VersionParts[0..3] -join ".")
$ReleaseRoot = Join-Path $ProjectPath "shareable"
$PortableName = if ($IsBeta) { "1SalemBOT-Portable-v$AppSourceVersionTag" } else { "1SalemBOT-Portable-v$AppVersionTag" }
$PortablePath = Join-Path $ReleaseRoot $PortableName
$PortableZipPath = Join-Path $ReleaseRoot "1SalemBOT_Portable_v$AppVersionTag.zip"
$VersionJsonPath = Join-Path $ReleaseRoot "version.json"
$InstallerScriptPath = Join-Path $ProjectPath "installer.iss"
$InstallerOutputPath = Join-Path $ReleaseRoot "1SalemBOT_Setup_v$AppVersionTag.exe"
$GitHubOwner = "salemq8"
$GitHubRepo = "1SalemBOT"
$GitHubLatestDownloadBase = "https://github.com/$GitHubOwner/$GitHubRepo/releases/latest/download"
$InstallerAssetName = "1SalemBOT_Setup_v$AppVersionTag.exe"
$PortableAssetName = "1SalemBOT_Portable_v$AppVersionTag.zip"
$BuiltAppPath = Join-Path $ProjectPath "dist\1SalemBOT"
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

& powershell -ExecutionPolicy Bypass -File $BuildScriptPath -Channel $ResolvedChannel
if ($LASTEXITCODE -ne 0) {
    throw "Desktop build failed"
}

if (-not (Test-Path $BuiltAppPath)) {
    throw "Built app folder not found at $BuiltAppPath"
}

Copy-Item -LiteralPath $BuiltAppPath -Destination $PortablePath -Recurse

foreach ($requiredVlcPath in @(
    (Join-Path $VlcTargetPath "libvlc.dll"),
    (Join-Path $VlcTargetPath "libvlccore.dll"),
    (Join-Path $VlcTargetPath "plugins")
)) {
    if (-not (Test-Path -LiteralPath $requiredVlcPath)) {
        throw "Bundled VLC runtime is missing from portable package: $requiredVlcPath"
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
1SalemBOT Portable v$AppVersionLabel
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
        @("settings.json", "users.json", "dashboard_state.json", "music_command.json", "chat_log.txt", "twitch_bot_auth.json", "twitch_channel_auth.json", "telemetry.json") -contains $_.Name
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

$innoArguments = @(
    "/DMyAppVersion=$AppVersion",
    "/DMyAppDisplayVersion=$AppVersionLabel",
    "/DMyAppVersionTag=$AppVersionTag",
    "/DMyAppVersionInfo=$AppVersionInfo",
    "/DMyAppSource=$PortablePath",
    "/DMyInstallerOutput=$ReleaseRoot",
    $InstallerScriptPath
)
& $InnoCompilerPath @innoArguments
if ($LASTEXITCODE -ne 0) {
    throw "Installer build failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $InstallerOutputPath)) {
    throw "Installer build failed"
}

$releaseNotes = @()
$changelogPath = Join-Path $ProjectPath "CHANGELOG.md"
if (Test-Path $changelogPath) {
    $changelogLines = Get-Content -LiteralPath $changelogPath -Encoding UTF8
    $insideCurrentVersion = $false
    foreach ($line in $changelogLines) {
        if ($line -match "^##\s+v$([regex]::Escape($AppVersion))\b") {
            $insideCurrentVersion = $true
            continue
        }
        if ($insideCurrentVersion -and $line -match "^##\s+") {
            break
        }
        if ($insideCurrentVersion) {
            $clean = $line.Trim()
            if ($clean -and -not $clean.StartsWith("###")) {
                $releaseNotes += $clean
            }
        }
    }
}
if (-not $releaseNotes) {
    $releaseNotes = @("1SalemBOT v$AppVersionLabel release.")
}

$versionPayload = [ordered]@{
    version = $VersionJsonVersion
    version_core = $AppVersion
    installer_url = "$GitHubLatestDownloadBase/$InstallerAssetName"
    portable_url = "$GitHubLatestDownloadBase/$PortableAssetName"
    release_notes = $releaseNotes
    channel = $VersionJsonChannel
    installer = [ordered]@{
        name = $InstallerAssetName
        url = "$GitHubLatestDownloadBase/$InstallerAssetName"
        sha256 = (Get-FileHash -LiteralPath $InstallerOutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
        silent_args = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
        supports_silent = $true
    }
    portable = [ordered]@{
        name = $PortableAssetName
        url = "$GitHubLatestDownloadBase/$PortableAssetName"
        sha256 = (Get-FileHash -LiteralPath $PortableZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        supports_silent = $false
    }
}

$versionJson = $versionPayload | ConvertTo-Json -Depth 8
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($VersionJsonPath, $versionJson, $utf8NoBom)
Copy-Item -LiteralPath $VersionJsonPath -Destination (Join-Path $PortablePath "version.json") -Force

$requiredReleaseFiles = @($InstallerOutputPath, $PortableZipPath, $VersionJsonPath)
foreach ($requiredReleaseFile in $requiredReleaseFiles) {
    if (-not (Test-Path -LiteralPath $requiredReleaseFile)) {
        throw "Release artifact missing: $requiredReleaseFile"
    }
}

Write-Host "Portable build created at $PortablePath"
Write-Host "Portable zip created at $PortableZipPath"
Write-Host "Installer created at $InstallerOutputPath"
Write-Host "Update metadata created at $VersionJsonPath"
