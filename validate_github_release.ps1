param(
    [string]$Owner = "salemq8",
    [string]$Repo = "1SalemBOT",
    [ValidateSet("Auto", "Beta", "Stable")]
    [string]$Channel = "Auto",
    [switch]$SkipRemote
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
$AppVersionTag = if ($IsBeta) { "$AppVersion-Beta" } else { $AppVersion }
$VersionJsonChannel = $ResolvedChannel.ToLowerInvariant()
$ReleaseRoot = Join-Path $ProjectPath "shareable"
$InstallerAssetName = "1SalemBOT_Setup_v$AppVersionTag.exe"
$PortableAssetName = "1SalemBOT_Portable_v$AppVersionTag.zip"
$VersionJsonAssetName = "version.json"
$Sha256SumsAssetName = "SHA256SUMS.txt"
$InstallerPath = Join-Path $ReleaseRoot $InstallerAssetName
$PortableZipPath = Join-Path $ReleaseRoot $PortableAssetName
$VersionJsonPath = Join-Path $ReleaseRoot $VersionJsonAssetName
$Sha256SumsPath = Join-Path $ReleaseRoot $Sha256SumsAssetName
$UpdateUrl = "https://github.com/$Owner/$Repo/releases/latest/download/version.json"
$DownloadBase = if ($IsBeta) { "https://github.com/$Owner/$Repo/releases/latest/download" } else { "https://github.com/$Owner/$Repo/releases/download/v$AppVersion" }

$localRequiredFiles = @($InstallerPath, $PortableZipPath, $VersionJsonPath, $Sha256SumsPath)
foreach ($path in $localRequiredFiles) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Local release artifact missing: $path"
    }
}

$versionJson = Get-Content -LiteralPath $VersionJsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($field in @("version", "installer_url", "portable_url", "release_notes")) {
    if (-not $versionJson.PSObject.Properties.Name.Contains($field)) {
        throw "version.json missing required field: $field"
    }
}
if ($versionJson.version -ne $AppVersionLabel) {
    throw "version.json version '$($versionJson.version)' does not match expected label '$AppVersionLabel'"
}
if ($versionJson.PSObject.Properties.Name.Contains("channel") -and $versionJson.channel -ne $VersionJsonChannel) {
    throw "version.json channel '$($versionJson.channel)' does not match expected channel '$VersionJsonChannel'"
}
if ($versionJson.installer_url -ne "$DownloadBase/$InstallerAssetName") {
    throw "version.json installer_url is not the expected GitHub release URL"
}
if ($versionJson.portable_url -ne "$DownloadBase/$PortableAssetName") {
    throw "version.json portable_url is not the expected GitHub release URL"
}
if (-not $versionJson.release_notes -or $versionJson.release_notes.Count -lt 1) {
    throw "version.json release_notes is empty"
}

$shaContent = Get-Content -LiteralPath $Sha256SumsPath -Raw -Encoding UTF8
foreach ($assetName in @($InstallerAssetName, $PortableAssetName, $VersionJsonAssetName)) {
    if ($shaContent -notmatch [regex]::Escape($assetName)) {
        throw "SHA256SUMS.txt missing asset: $assetName"
    }
}

Write-Host "Local release artifact validation passed."

if ($SkipRemote) {
    Write-Host "Remote GitHub release validation skipped."
    exit 0
}

if ($ResolvedChannel -ne "Stable") {
    throw "Remote GitHub release validation is only allowed for Stable channel builds. Use -SkipRemote for Beta validation."
}

$headers = @{
    "User-Agent" = "1SalemBOT-release-validator"
    "Accept" = "application/vnd.github+json"
}
$latestReleaseUrl = "https://api.github.com/repos/$Owner/$Repo/releases/latest"
try {
    $latestRelease = Invoke-RestMethod -Uri $latestReleaseUrl -Headers $headers -Method Get
} catch {
    throw "Could not read latest GitHub release from $latestReleaseUrl. $($_.Exception.Message)"
}

$assetNames = @($latestRelease.assets | ForEach-Object { $_.name })
foreach ($assetName in @($VersionJsonAssetName, $InstallerAssetName, $PortableAssetName, $Sha256SumsAssetName)) {
    if ($assetNames -notcontains $assetName) {
        throw "Latest GitHub release is missing required asset: $assetName"
    }
}

try {
    $remoteVersionJson = Invoke-RestMethod -Uri $UpdateUrl -Headers @{ "User-Agent" = "1SalemBOT-release-validator" } -Method Get
} catch {
    throw "Could not download remote version.json from $UpdateUrl. $($_.Exception.Message)"
}
foreach ($field in @("version", "installer_url", "portable_url", "release_notes")) {
    if (-not $remoteVersionJson.PSObject.Properties.Name.Contains($field)) {
        throw "Remote version.json missing required field: $field"
    }
}
if ($remoteVersionJson.version -ne $AppVersionLabel) {
    throw "Remote version.json version '$($remoteVersionJson.version)' does not match expected label '$AppVersionLabel'"
}

Write-Host "Remote GitHub latest release validation passed."
