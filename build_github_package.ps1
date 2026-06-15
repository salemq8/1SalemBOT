param(
    [ValidateSet("Auto", "Beta", "Stable")]
    [string]$Channel = "Auto"
)

$ErrorActionPreference = "Stop"

$ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$VersionFilePath = Join-Path $ProjectPath "VERSION"
$VersionChannelFilePath = Join-Path $ProjectPath "VERSION_CHANNEL"
if (-not (Test-Path -LiteralPath $VersionFilePath)) {
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
$SourceVersionTag = if ($IsBeta) { "$AppVersion-Beta" } else { $AppVersion }
$SourceFolderName = "1SalemBOT-v$SourceVersionTag-source"
$SourceZipName = "$SourceFolderName.zip"
$ChannelFileValue = $ResolvedChannel.ToLowerInvariant()

$ReleaseRoot = Join-Path $ProjectPath "release_github"
$SourceRoot = Join-Path $ReleaseRoot $SourceFolderName
$ArtifactsRoot = Join-Path $ReleaseRoot "artifacts"
$SourceZip = Join-Path $ReleaseRoot $SourceZipName
$ShareableRoot = Join-Path $ProjectPath "shareable"
$InstallerPath = Join-Path $ShareableRoot "1SalemBOT_Setup_v$AppVersionTag.exe"
$PortableZipPath = Join-Path $ShareableRoot "1SalemBOT_Portable_v$AppVersionTag.zip"
$VersionJsonPath = Join-Path $ShareableRoot "version.json"

foreach ($requiredArtifact in @($InstallerPath, $PortableZipPath, $VersionJsonPath)) {
    if (-not (Test-Path -LiteralPath $requiredArtifact)) {
        throw "Required artifact missing. Build channel $ResolvedChannel first: $requiredArtifact"
    }
}

$resolvedProject = [System.IO.Path]::GetFullPath($ProjectPath)
$resolvedRelease = [System.IO.Path]::GetFullPath($ReleaseRoot)
if (-not $resolvedRelease.StartsWith($resolvedProject, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove release folder outside project: $resolvedRelease"
}

if (Test-Path -LiteralPath $ReleaseRoot) {
    Remove-Item -LiteralPath $ReleaseRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $SourceRoot | Out-Null
New-Item -ItemType Directory -Path $ArtifactsRoot | Out-Null

$files = @(
    ".gitignore",
    "VERSION",
    "VERSION_CHANNEL",
    "README.md",
    "CHANGELOG.md",
    "RELEASE.md",
    "requirements.txt",
    "main.py",
    "build_windows_app.ps1",
    "build_shareable_release.ps1",
    "build_github_package.ps1",
    "validate_github_release.ps1",
    "installer.iss",
    "create_shortcut.ps1",
    "make_icon.py"
)
foreach ($file in $files) {
    $source = Join-Path $ProjectPath $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $SourceRoot $file) -Force
    }
}
foreach ($dir in @("core", "assets", "tests", "docs")) {
    $source = Join-Path $ProjectPath $dir
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $SourceRoot $dir) -Recurse -Force
    }
}

Set-Content -LiteralPath (Join-Path $SourceRoot "VERSION") -Value $AppVersion -Encoding ASCII
Set-Content -LiteralPath (Join-Path $SourceRoot "VERSION_CHANNEL") -Value $ChannelFileValue -Encoding ASCII

$readmePath = Join-Path $SourceRoot "README.md"
if (Test-Path -LiteralPath $readmePath) {
    $readme = Get-Content -LiteralPath $readmePath -Raw -Encoding UTF8
    $readme = $readme -replace "^# 1SalemBOT v[^\r\n]+", "# 1SalemBOT v$AppVersionLabel"
    [System.IO.File]::WriteAllText($readmePath, $readme, [System.Text.UTF8Encoding]::new($false))
}

Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force -Directory |
    Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "logs", "data", "user-data", "cache", "build", "dist", "shareable", "release_github", ".venv") } |
    Sort-Object FullName -Descending |
    Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force -File |
    Where-Object {
        $_.Name -like "*.pyc" -or
        $_.Name -like "*.pyo" -or
        $_.Name -like "*.log" -or
        $_.Name -like "*.tmp" -or
        $_.Name -like ".env*" -or
        $_.Name -in @(
            "settings.json",
            "users.json",
            "dashboard_state.json",
            "music_command.json",
            "chat_log.txt",
            "alerts.json",
            "alert_status.json",
            "bot_runtime.json",
            "alert_runtime.json",
            "viewer_relationships.json",
            "twitch_auth.json",
            "twitch_bot_auth.json",
            "twitch_channel_auth.json",
            "telemetry.json",
            "telemetry.log"
        )
    } |
    Remove-Item -Force

Copy-Item -LiteralPath $InstallerPath -Destination $ArtifactsRoot -Force
Copy-Item -LiteralPath $PortableZipPath -Destination $ArtifactsRoot -Force
Copy-Item -LiteralPath $VersionJsonPath -Destination $ArtifactsRoot -Force

if (Test-Path -LiteralPath $SourceZip) {
    Remove-Item -LiteralPath $SourceZip -Force
}
Compress-Archive -Path (Join-Path $SourceRoot "*") -DestinationPath $SourceZip -Force

$checklistPath = Join-Path $ReleaseRoot "RELEASE_CHECKLIST.md"
$generated = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
@"
# 1SalemBOT v$AppVersionLabel Release Checklist

Generated: $generated

## Channel
- $ResolvedChannel

## Included
- Clean source folder and source zip for 1SalemBOT v$AppVersionLabel.
- Source code, assets, tests, docs, requirements, README, CHANGELOG, RELEASE guide, installer/build scripts.
- Bilingual legal documents: docs/TERMS.md and docs/PRIVACY.md.
- Supabase telemetry setup SQL: docs/supabase_installations.sql.
- Windows setup installer.
- Windows portable zip.
- GitHub update metadata version.json.
- Bundled VLC runtime inside the app package artifacts.

## Excluded
- Twitch tokens and auth files.
- API keys, .env files, credentials, cookies, and secrets.
- Personal settings and runtime state.
- Telemetry install id runtime file (telemetry.json).
- Telemetry diagnostics log (telemetry.log).
- Chat history, logs, caches, __pycache__, build folders, dist folders, temp files.
- Local virtual environment and user-specific data.

## Naming
- App: 1SalemBOT v$AppVersionLabel
- Installer: 1SalemBOT_Setup_v$AppVersionTag.exe
- Portable: 1SalemBOT_Portable_v$AppVersionTag.zip
- Source: $SourceZipName
- Channel: $ResolvedChannel

## Upload Files
- artifacts/1SalemBOT_Setup_v$AppVersionTag.exe
- artifacts/1SalemBOT_Portable_v$AppVersionTag.zip
- artifacts/version.json
- $SourceZipName
"@ | Set-Content -LiteralPath $checklistPath -Encoding UTF8

Write-Host "GitHub package created at $ReleaseRoot"
Write-Host "Source zip created at $SourceZip"
