# Changelog

## v1.7 - Support, Updates, and Queue Controls

### Added

- Technical Support section with support email, logs folder shortcut, diagnostic copy, and Discord placeholder.
- Redacted local crash reports with next-start crash support dialog.
- Support and crash report mail drafts open through the default mail app with no SMTP or stored email credentials.
- Update progress states for checking, update found, downloading, verification, installer preparation, installation, and close-to-apply.
- Music queue controls for clear queue, move selected track up/down, queue count, and duplicate prevention.
- Auto Restart Bot on Startup setting, enabled by default.

### Changed

- Windows EXE and installer metadata now identify CompanyName, ProductName, FileDescription, Copyright, and v1.7 version metadata.
- Music policy messages remain generic in public UI and release notes.

### Fixed

- Viewer message counts now update from every incoming Twitch chat message before command filtering, while bot self-messages and duplicate message IDs are ignored.
- Crash report support now opens an Outlook draft with a redacted crash log attached when Outlook desktop is available, with mailto and manual-attachment fallback otherwise.
- Dashboard, sidebar, settings, music, viewers, and update panels now share centralized theme background layers for a more consistent dark UI.
- Restored themed button fills, hover states, card elevation, list borders, and update progress styling after the background palette cleanup.
- Fixed action buttons with a dedicated styled button widget so queue, Bot Settings, Twitch setup, and update controls cannot render as plain text.
- Fixed QComboBox dropdowns, QMenu popups, and input fields so menus use themed panel/accent colors and inputs keep visible themed borders, backgrounds, padding, and focus highlights.
- Restored the Bot Settings form hierarchy with styled Theme/Language/Log Retention combo boxes, read-only Bot/Channel login fields, editable Trigger Input, and a bordered trigger chip container.
- Restored visible checkbox states, dark bordered queue panels, title-based queue rows for YouTube URLs/playlists, role-priority viewer sorting, and stronger selected viewer row highlighting.
- Finalized queue list contrast to match Chat/Live Log surfaces and changed the default viewer directory order to message-count first with role priority only as a tie-breaker, including Lead Moderator detection above Moderator.

## v1.6 - Music Queue Stability

### Fixed

- Skip now stops only the current track, keeps the remaining queue intact, and advances to the next queued track cleanly.
- Skip handoff now starts the next queued track as soon as VLC stop completes, with a 5-second maximum delay cap.
- Empty queue/player state now resets to `No track loaded` without leaving the player stuck as loading or playing.
- YouTube playlist URLs now import up to 50 videos into the music queue without blocking the UI.
- Playlist imports start the first item immediately when idle and keep the remaining videos queued in order.
- Music requests now use generic music policy handling before queueing unavailable tracks.
- Playlist imports skip unavailable tracks and add playable tracks only.
- App startup now waits 3 seconds, then runs one automatic bot restart through the same Restart Bot sequence.
- Restart Bot now prevents overlapping restart requests so bot chat/EventSub connections do not duplicate while Alerts remain independently guarded.
- Twitch chat music requests now require explicit commands such as `!sr`, `!songrequest`, `!play`, or a configured music command.
- Arabic bot-addressed requests such as `بوت شغل قصله`, `يا بوت شغل قصله`, and `@1SalemGPT شغل قصله` now enter the music queue.
- Normal chat messages, including bare `play song name` text, are ignored by the music queue.

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
- GitHub Releases updater using remote `version.json`, semantic version comparison, installer download progress, cancellation, and installer launch after app exit.
- Settings page Updates section with current version, Check for Updates, Auto Update, status messages, progress bar, and Cancel Download.
- Automatic `version.json` generation during Windows release builds.
- GitHub latest-release validation script for `version.json`, setup installer, and portable ZIP assets.
- `RELEASE.md` with the production publishing workflow for GitHub Releases.

### Changed

- EventSub keepalive logging is collapsed and rate-limited to keep the UI lightweight.
- Live Log now keeps recent activity only and avoids long-session growth.
- Trigger chips were redesigned into compact one-pill controls with hover remove action.
- Alert rows now use real stored data only and avoid duplicate follower rows.
- Start Bot now controls chat/AI/music behavior only; Alerts run through their own listener.
- Auto Update is optional and checks on startup only when enabled.

### Fixed

- Packaged startup crash caused by missing Live Log initialization.
- Sidebar navigation order for Alerts and Twitch.
- Sidebar account status dot visibility and styling.
- Arabic volume slider mirroring and Arabic-only volume button ordering.
- Alert EventSub subscription status reporting and missing-permission messaging.
- Twitch alert storage fields for event type, username, timestamp, and details.

### Release Outputs

- `1SalemBOT.exe`
- `1SalemBOT_Setup_v1.7.exe`
- `1SalemBOT_Portable_v1.7.zip`
