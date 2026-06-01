# Changelog

## v1.5 - Final Public Release

### Added

- Twitch Bot Account and Channel Account login flows with separate token storage.
- Automatic Alerts listener that runs independently from Start Bot.
- Real EventSub alert storage and display pipeline.
- Alert icon mapping by real Twitch event type.
- Full Alerts page and Dashboard Alerts card.
- Sidebar account connection status indicators.
- Built-in English and Arabic localization resources.
- RTL support for Arabic UI.
- Media controls that keep sliders/progress direction LTR in Arabic mode.
- AI chat replies with single leading chatter mention and no extra `@user` placeholders.
- Live Log batching, line caps, and time-based retention.
- Protected backend owner/security policy layer for bot replies.
- Twitch-style account panels and official Twitch logo asset.
- Viewer directory, relationship lists, dashboard analytics, and live chat rendering.
- Music request queue, VLC playback, mute/volume controls, and skip/stop flow.
- Windows installer and portable release build scripts.
- Shared `VERSION` file used by the app, portable build, and installer build.
- Dormant Update Manager backend for future GitHub release JSON parsing, version comparison, release notes parsing, and installer/portable asset detection.
- Settings page Updates section with current version, placeholder Check for Updates button, and disabled Auto Update placeholder.

### Changed

- EventSub keepalive logging is collapsed and rate-limited to keep the UI lightweight.
- Live Log now keeps recent activity only and avoids long-session growth.
- Trigger chips were redesigned into compact one-pill controls with hover remove action.
- Alert rows now use real stored data only and avoid duplicate follower rows.
- Start Bot now controls chat/AI/music behavior only; Alerts run through their own listener.
- Update infrastructure is prepared but intentionally performs no network requests or downloads in v1.5.

### Fixed

- Packaged startup crash caused by missing Live Log initialization.
- Sidebar navigation order for Alerts and Twitch.
- Sidebar account status dot visibility and styling.
- Arabic volume slider mirroring and Arabic-only volume button ordering.
- Alert EventSub subscription status reporting and missing-permission messaging.
- Twitch alert storage fields for event type, username, timestamp, and details.

### Release Outputs

- `1SalemBOT.exe`
- `1SalemBOT_Setup_v1.5.exe`
- `1SalemBOT_Portable_v1.5.zip`
