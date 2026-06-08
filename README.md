# 1SalemBOT v1.7

1SalemBOT is a Windows desktop Twitch management app for running a channel bot, live alerts, AI chat replies, music requests, viewer tools, dashboard analytics, and bilingual English/Arabic UI.

## Features

- Twitch Bot Account login for chat replies, commands, and moderation-related actions.
- Twitch Channel Account login for broadcaster-level dashboard features and live alerts.
- EventSub-powered Alerts listener that starts automatically when the Channel Account is connected.
- Optional one-shot startup bot restart with overlap protection, while keeping the manual Restart Bot button available.
- Real alert feed for follows, subs, gifted subs, raids, bits, rewards, polls, predictions, hype train, shoutouts, and supported channel events.
- AI chat replies with clean Twitch-style mention formatting.
- Built-in English and Arabic localization with instant language switching.
- RTL layout support for Arabic, with media sliders kept in normal LTR direction.
- Theme system with dark blue default styling and additional themes.
- Music request system with YouTube lookup, playlist import, generic music policy handling, duplicate prevention, queue controls, mute, volume, and skip/stop.
- Technical Support tools for support email drafts, logs folder access, copied diagnostics, and redacted crash reports.
- Viewer directory with follower/subscriber/unfollower views and local activity analytics.
- Dashboard stats, live chat preview, alerts card, and lightweight Live Log retention.
- Protected backend policy layer for owner/security behavior.
- Windows installer and portable package build scripts.

## Requirements

- Windows 10/11.
- Python 3.11 or newer for source runs/builds.
- Twitch developer application with the configured redirect URI used by the app.
- OpenAI API key for AI chat replies.
- VLC installed in `C:\Program Files\VideoLAN\VLC` when building the full portable release.
- Inno Setup 6 when building the installer.

## Version Management

The release version is stored in the root `VERSION` file. The desktop app, portable package names, and installer build all read from that same value.

To prepare a future release, update `VERSION` first, then run the release build script.

## Install From Release

Use one of the release artifacts:

- `1SalemBOT_Setup_v1.7.exe` for normal Windows installation.
- `1SalemBOT_Portable_v1.7.zip` for portable use.
- `dist/1SalemBOT/1SalemBOT.exe` for the local one-folder desktop build.

The app stores runtime settings, Twitch tokens, logs, and user data in the Windows app data folder by default. Portable mode stores runtime data in `user-data` beside the launcher.

## Run From Source

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

## Build

Build the desktop app:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_windows_app.ps1
```

Build the final portable zip and installer:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_shareable_release.ps1
```

Outputs:

- `dist/1SalemBOT/`
- `shareable/1SalemBOT-Portable-v1.7/`
- `shareable/1SalemBOT_Portable_v1.7.zip`
- `shareable/1SalemBOT_Setup_v1.7.exe`
- `shareable/version.json`

## Updates

The app supports Windows updates through GitHub Releases:

- The local version is read from the root `VERSION` file.
- The updater fetches `https://github.com/salemq8/1SalemBOT/releases/latest/download/version.json`.
- Semantic versions are compared before offering an update.
- The Windows installer is downloaded to a temporary folder with progress shown in Settings.
- The installer is launched only after the current app closes.
- Auto Update can be enabled or disabled from Settings.

The release build generates `shareable/version.json` automatically. It must be uploaded to GitHub Releases with the installer and portable ZIP.

Generated `version.json` shape:

```json
{
  "version": "1.7",
  "installer_url": "https://github.com/salemq8/1SalemBOT/releases/latest/download/1SalemBOT_Setup_v1.7.exe",
  "portable_url": "https://github.com/salemq8/1SalemBOT/releases/latest/download/1SalemBOT_Portable_v1.7.zip",
  "release_notes": ["Change one", "Change two"],
  "channel": "stable",
  "installer": {
    "name": "1SalemBOT_Setup_v1.7.exe",
    "url": "https://github.com/salemq8/1SalemBOT/releases/latest/download/1SalemBOT_Setup_v1.7.exe",
    "sha256": "optional-sha256",
    "silent_args": ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
  }
}
```

## Publishing A New GitHub Release

1. Update `VERSION`.
2. Update `CHANGELOG.md`.
3. Build the release:

```powershell
powershell -ExecutionPolicy Bypass -File .\build_shareable_release.ps1
```

4. Upload these files to the GitHub Release for `salemq8/1SalemBOT`:
   - `shareable/1SalemBOT_Setup_v<VERSION>.exe`
   - `shareable/1SalemBOT_Portable_v<VERSION>.zip`
   - `shareable/version.json`
5. Validate local assets before upload:

```powershell
powershell -ExecutionPolicy Bypass -File .\validate_github_release.ps1 -SkipRemote
```

6. Validate the live GitHub latest release after upload:

```powershell
powershell -ExecutionPolicy Bypass -File .\validate_github_release.ps1
```

## Runtime Data And Secrets

Do not commit or upload:

- Twitch token files.
- OpenAI API keys.
- `settings.json`.
- Chat logs.
- Alert history.
- Viewer/user runtime state.
- Build folders such as `build`, `dist`, `shareable`, or `release_github`.

The provided `.gitignore` excludes these files and folders.

## License

No open-source license file is included in this release package. All rights are reserved unless the owner adds a license separately.
