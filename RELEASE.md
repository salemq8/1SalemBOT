# Release Guide

This project publishes Windows updates through GitHub Releases for `salemq8/1SalemBOT`.

## 1. Set VERSION And Channel

For the official v1.8 GitHub release:

```text
VERSION: 1.8
VERSION_CHANNEL: stable
```

Public GitHub releases are built with the Stable channel and are labeled `1SalemBOT v<VERSION>`.

## 2. Update Changelog

Add a new top entry in `CHANGELOG.md`:

```markdown
## v1.8 - Release Name

### Added

- ...
```

The build script extracts this section into `version.json` as `release_notes`.

## 3. Build Release

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_shareable_release.ps1 -Channel Stable
powershell -ExecutionPolicy Bypass -File .\build_github_package.ps1 -Channel Stable
```

Generated files:

- `shareable/1SalemBOT_Setup_v<VERSION>.exe`
- `shareable/1SalemBOT_Portable_v<VERSION>.zip`
- `shareable/version.json`
- `release_github/1SalemBOT-v<VERSION>-source.zip`

## 4. Validate Local Release Assets

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\validate_github_release.ps1 -Channel Stable -SkipRemote
```

This fails if any local release asset is missing or if `version.json` does not contain:

- `version`
- `installer_url`
- `portable_url`
- `release_notes`

## 5. Create GitHub Release

Create a GitHub Release in:

```text
https://github.com/salemq8/1SalemBOT/releases
```

Recommended tag:

```text
v<VERSION>
```

Upload all required assets:

- `1SalemBOT_Setup_v<VERSION>.exe`
- `1SalemBOT_Portable_v<VERSION>.zip`
- `version.json`

## 6. Verify Update Endpoint

After publishing, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\validate_github_release.ps1 -Channel Stable
```

The updater reads:

```text
https://github.com/salemq8/1SalemBOT/releases/latest/download/version.json
```

Validation fails if the latest release is missing `version.json`, the setup installer, or the portable ZIP.

## 7. Auto Update Flow

When Auto Update is enabled in Settings:

- The app checks GitHub on startup.
- It downloads `version.json`.
- It compares semantic versions against local `VERSION`.
- If newer, it shows an Update Available dialog.
- It downloads the installer to a temp folder with progress.
- It launches the installer only after the current app exits.
- Silent installation uses `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART` when supported.

The app never replaces its own files while running.
