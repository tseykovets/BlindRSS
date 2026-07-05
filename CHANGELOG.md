# Changelog

Readable release history for BlindRSS. When adjacent releases were part of the
same fix stream, they are combined with a version range such as
`v1.78.1-v1.78.2`.

## v1.80.0 - 2026-07-05

- Add German, Japanese, Spanish, Hindi, Chinese (Simplified/Traditional), Polish, French, Dutch (NL/BE), Italian, and Portuguese (BR/PT) translations.

## v1.79.1 - 2026-07-05

- Sync Claude memory index in agents.md.
- Merge pull request #50 from tseykovets/gettext.
- Merge pull request #49 from tseykovets/ru.
- Remove gettext functions around strings that don't need translation.
- Update Russian translation.

## v1.79.0 - 2026-07-04

- Add Russian translation.
- Merge pull request #47 from tseykovets/ru.

## v1.78.3 - 2026-07-03
- Fixed feeds whose URLs use internationalized domains and non-ASCII paths, including Cyrillic domains and paths.
- Made feed refresh errors report the real problem instead of replacing non-HTTP exceptions with a missing `response` attribute error.
- Added build-time gettext catalog compilation so translators only need to maintain `.po` files.
- Kept the focused feed in the channel tree when Mark All Items as Read is used under Unread Only.
- Added a repository changelog, linked it from the README, and added a View Changelog button to About.

## v1.78.1-v1.78.2 - 2026-07-03
- Fixed first volume adjustments jumping unexpectedly, including on slow streams.

## v1.78.0 - 2026-07-03
- Added the global All, Unread Only, and Read Only article filter with a matching filtered channel tree.
- Added the initial gettext-based interface internationalization support.

## v1.77.5 - 2026-07-03
- Stopped refresh from overwriting user-customized feed names.

## v1.77.4 - 2026-07-03
- Added initial support for non-ASCII feed URLs and optional tolerance for SSL certificate errors.
- Clarified Mark All as Read and Show Only Unread scoping.
- Removed the duplicate app name from tray status labels.

## v1.77.3 - 2026-07-03
- Stopped treating podcast enclosures as article webpage URLs.

## v1.77.1-v1.77.2 - 2026-07-03
- Improved screen reader announcements for article find misses.

## v1.77.0 - 2026-07-03
- Added the filter rules pipeline, configurable delete behavior, and related screen-reader find announcements.

## v1.76.0 - 2026-07-02
- Added permanent delete from Deleted Articles.
- Improved article find behavior so matches do not wrap unexpectedly.
- Included several bug-scan fixes.

## v1.75.0 - 2026-07-02
- Added Smart Folders and restorable deleted articles.
- Added find-in-article shortcuts and freed Space for list multi-select.

## v1.74.0-v1.74.1 - 2026-07-02
- Added multi-select article actions for bulk delete and copy.
- Blocked article deletion while refresh is active to avoid inconsistent state.

## v1.73.4-v1.73.5 - 2026-07-01/2026-07-02
- Improved NVDA responsiveness while navigating large article lists and the feed tree, including arrow, paging, Home, and End navigation.

## v1.73.3 - 2026-07-01
- Preserved missing full-text ledes when JSON-LD extraction had dropped them.

## v1.73.2 - 2026-07-01
- Avoided high-bitrate combined formats for YouTube live streams.
- Raised refresh concurrency and bounded per-feed retry time.

## v1.73.1 - 2026-07-01
- Handled URL-only feed item text more reliably.

## v1.73.0 - 2026-07-01
- Showed refresh status in the tray label.

## v1.72.0 - 2026-06-30
- Added recursive unread totals on category tree nodes.
- Showed feed refresh and download activity in the status bar.
- Made the Feed Description dialog close with Escape.

## v1.71.1 - 2026-06-30
- Exposed feed item descriptions in the UI.

## v1.71.0 - 2026-06-30
- Added a configurable article opening method with custom command support.
- Added a configurable default expanded/collapsed state for the category tree.
- Added a Feeds with Errors view for failed feed updates.

## v1.70.4-v1.70.6 - 2026-06-30
- Improved feed fetching against anti-bot WAFs, including browser impersonation and per-feed proxy support.
- Improved feed format compatibility.

## v1.70.2-v1.70.3 - 2026-06-28/2026-06-29
- Broadened RSS and Atom feed compatibility.

## v1.70.1 - 2026-06-28
- Preserved nested category hierarchy during OPML export/import.
- Refreshed the README and community links.

## v1.70.0 - 2026-06-25
- Added Windows installed-app support with Program Files installation and mutable data stored outside the install directory.

## v1.69.1 - 2026-06-25
- Retried update backup moves when a runtime DLL is transiently locked.

## v1.69.0 - 2026-06-25
- Added the Windows per-user installer, roaming AppData storage behavior, and Chromecast handoff support.

## v1.68.0 - 2026-06-25
- Added podcast and media chapters across providers, the player, and the accessible reader.
- Improved VoiceOver accessible names across the main window, dialogs, and player.
- Added native menu behavior, start-at-login support, and macOS Option+Arrow media keys.

## v1.67.5 - 2026-06-22
- Allowed same-named subcategories under different parent categories.

## v1.67.4 - 2026-06-10
- Fixed full text loading in the macOS accessible browser and improved macOS parity.

## v1.65.0-v1.67.3 - 2026-06-01/2026-06-07
- Improved YouTube and offline playback reliability with yt-dlp/VLC fallback exhaustion, cookie import, local-download playback, playback cache management, offline podcast playback, and MKV retry for conversion failures.
- Added a Download button to the accessible browser.

## v1.64.0 - 2026-05-31
- Broadened media-tool detection and improved YouTube playback stability.

## v1.63.53-v1.63.54 - 2026-05-31
- Improved article copy actions so Copy Text can include already-extracted full text with title and author headers.
- Cleaned up YouTube/media context menu behavior for copy and download actions.

## v1.63.52 - 2026-05-29
- Added cross-platform updater work, search subscriptions, accessibility fixes, and refresh fixes.

## v1.63.50-v1.63.51 - 2026-05-29
- Added Linux build support to the cross-platform release pipeline.
- Added a Copy Audio Link context-menu option for media items.

## v1.63.47-v1.63.49 - 2026-05-21/2026-05-25
- Fixed eager video search metadata lookups.
- Fixed Supercast/subscriber feed episode titles being replaced by footer links.
- Fixed updater window and article shortcut behavior.

## v1.63.43-v1.63.46 - 2026-05-21
- Made Windows updates more robust around locked files, updater handoff, security, and playback cleanup.
- Raised the Miniflux session pool size above targeted-refresh worker limits.

## v1.63.41-v1.63.42 - 2026-05-21
- Improved Miniflux refresh behavior, including startup refresh fanout, keep-alive sessions, shorter connect timeouts, and pre-release robustness fixes.

## v1.63.38-v1.63.40 - 2026-05-19/2026-05-21
- Fixed article delete shortcut/menu behavior and clipboard preservation on shutdown.
- Required Python 3.14 for builds.

## v1.63.37 - 2026-05-19
- Forced startup refresh and gated debug file logging.

## v1.63.36 - 2026-05-09
- Improved feed refresh reliability.

## v1.63.34-v1.63.35 - 2026-05-08
- Improved release publication checks so updater-visible releases are published and marked Latest.
- Fixed Miniflux refresh status reporting.

## v1.63.33 - 2026-05-08
- Bugfixes.

## Historical Changelog

Older entries below were reconstructed from the Forgejo mirror's tag history and
the historical notes kept in the repository.

## v1.63.31-v1.63.32 - 2026-04-29
- Fixed updater GitHub owner detection and signature verification fallback.

## v1.63.28-v1.63.30 - 2026-04-15
- Added accessible browser category expansion and Enter-to-open behavior.
- Moved user data into a safer config location and restored the accessible browser after settings.
- Improved macOS release flow, bundled dependency detection, and cross-platform release docs.

## v1.63.27 - 2026-04-06
- Fixed local OPML imports, homepage feed repair, feed selection, dead-feed retries, chapter download timing, conditional refresh, and refresh CPU usage.

## v1.63.23-v1.63.26 - 2026-03-08/2026-03-15
- Added nested subcategory support in the tree.
- Improved YouTube feed search ranking and playlist priority.
- Reduced local refresh CPU load and refreshed imported OPML feeds.

## v1.63.17-v1.63.22 - 2026-02-27/2026-02-28
- Improved YouTube playback in packaged builds with proxy fallback, stream-proxy fallback, and the `android_vr` client.
- Improved search dialog keyboard/status behavior and preserved article text selection shortcuts.
- Clarified Grok/Groq naming in translation settings.

## v1.63.12-v1.63.16 - 2026-02-27
- Added Qwen, OpenRouter, and Groq translation support with provider-scoped settings.
- Improved translation fallback reliability, model coverage, Gemini auth compatibility, and media search playback.
- Fixed Windows notification prerequisites.

## v1.63.8-v1.63.11 - 2026-02-25/2026-02-27
- Improved Ning activity feed titles, formatting, and full-text replacement behavior.
- Added feed-search source filtering and preserved text selection shortcuts.

## v1.63.4-v1.63.7 - 2026-02-25
- Added YouTube channel, YouTube playlist, Mastodon, Bluesky, PieFed, and video-search sources.
- Added a feed tree delete shortcut and Miniflux fixes.

## v1.63.0-v1.63.3 - 2026-02-19/2026-02-24
- Restored podcast chapter support and added previous/next chapter keyboard shortcuts.
- Added requested issue fixes, translation and UX improvements, and contact/community info.
- Fixed Ctrl+Up/Down volume shortcuts, YouTube playback stalls, and OPML feed title preservation.

## v1.62.0-v1.62.2 - 2026-02-17
- Added Windows notification activation so articles can open/play from notifications.
- Improved notification persistence in Action Center.

## v1.61.0-v1.61.1 - 2026-02-17
- Expanded Windows UX with sorting, startup, and notification improvements.
- Fixed desktop shortcut creation.

## v1.60.37-v1.60.39 - 2026-02-10/2026-02-17
- Added built-in player soundcard selection.
- Improved feed refreshing and Inoreader support.
- Fixed stale feed refresh across providers and yt-dlp playback for YouTube Shorts and similar URLs.

## v1.60.27-v1.60.36 - 2026-02-04/2026-02-10
- Added article search filtering, persistent search visibility/configuration, and search scope controls.
- Fixed search clearing, tab traversal, title+text search, RangeCacheProxy probe stalls, and yt-dlp playback.

## v1.60.14-v1.60.26 - 2026-01-31/2026-02-02
- Fixed VLC, proxy, and range-cache playback issues including URL normalization, undefined playback variables, new-feed episode visibility, slow startup, open-ended range handling, GUI-blocking probes, duplicate redirect resolution, and yt-dlp extractor preloading.
- Tightened PyInstaller package collection.

## v1.60.10-v1.60.13 - 2026-01-30
- Bugfixes.
- Made skip-silence defaults more conservative so quiet speech and natural pauses are less likely to be skipped.
- Fixed Remember last selected feed/folder, including feeds nested in categories.
- Fixed Mark All as Read plus refresh behavior so old read articles were not deleted during tree rebuild and recreated as unread later.

## v1.60.0-v1.60.9 - 2026-01-26/2026-01-29
- Added first-load article caching and Mark All as Read.
- Improved playback startup responsiveness, duplicate article ID handling, provider/feed-scoped cache IDs, tree unread counts, Delete key feed removal, Show Only Unread, immediate shutdown, and updater logging/rollback behavior.
- Fixed NPR conditional refresh behavior.

## v1.58.0-v1.59.0 - 2026-01-24
- Added and improved BazQux Reader support, including read/unread handling, strict filters, and Hide Read Articles setting.

## v1.57.0-v1.57.5 - 2026-01-22/2026-01-23
- Added podcast/player fixes.
- Optimized large-feed refresh with batched database writes.
- Improved Windows media-tool installation reliability.
- Fixed dependency-check crashes, Alt+Space system menu behavior, and first-letter navigation.

## v1.56.17-v1.56.27 - 2026-01-19/2026-01-21
- Improved playback resume, seek repeat handling, silence-skip behavior, and startup maximize behavior.
- Fixed Inoreader support and improved Windows dependency checks, dependency installs, and updater behavior.

## v1.56.8-v1.56.16 - 2026-01-12/2026-01-17
- Hardened yt-dlp headers and fixed menu IDs, cached column ordering, skip-silence backward seeks, BBC article detection, resume persistence, play/pause keyboard behavior, Bluesky RSS parsing, media fallback/open-in-browser behavior, article column order, and bundled Deno support.

## v1.56.0-v1.56.7 - 2026-01-07/2026-01-12
- Added an option to disable startup refresh.
- Improved Load more articles behavior, focus retention, scroll/selection preservation, refresh sounds, and startup behavior.

## v1.55.0 - 2026-01-07
- Added Open in Browser to the article context menu.

## v1.54.0-v1.54.2 - 2026-01-07
- Fixed dialog closing, focus reset, undefined variables, feed refresh, NPR refresh, Android Authority boilerplate, list focus on refresh, All Articles naming, and Feed Properties button handling.
- Added core and GUI unit tests.

## v1.53.0-v1.53.7 - 2026-01-06
- Improved article status management and full-text extraction triggers.
- Fixed NPR audio/feed handling, sounds, accessibility, window maximize, bundled sound paths, update preservation of sounds, custom sound priority, feed parsing resilience, and dialog tab order.

## v1.52.0-v1.52.5 - 2026-01-05/2026-01-06
- Added single-feed refresh and Tyee boilerplate cleanup.
- Fixed media content handling without enclosures, BBC yt-dlp support, Miniflux refresh argument handling, and Mutagen import issues.

## v1.51.0 - 2026-01-05
- Added Help menu, About dialog, interactive media-tool check, feed refresh fixes, and single-instance enforcement.

## v1.50.0-v1.50.5 - 2026-01-05
- Added feed editing and media polish.
- Improved Wired/full-text extraction, podcast detection, pagination detection, All Feeds feed-source display, updater cleanup, podcast resume consistency, and range-cache Content-Range handling.

## v1.49.0-v1.49.5 - 2026-01-03/2026-01-05
- Prevented yt-dlp autoplay on publisher articles and avoided treating VoxMedia articles as yt-dlp-supported.
- Improved build dry-run Python detection, PyInstaller webrtcvad packaging, locked SQLite playback-state handling, large local database responsiveness, full-text lead extraction, and feed deletion safety.

## v1.48.11-v1.48.17 - 2026-01-03
- Added Favorites view across providers.
- Added lazy chapters and stable playback resume/seek persistence.
- Fixed webrtcvad packaging, OneDrive updater behavior, media resolution for BBC/playlist-like sites, and reduced Miniflux refresh log noise.

## v1.48.0-v1.48.10 - 2025-12-30/2025-12-31
- Added Fediverse search and improved search/menu placement.
- Reduced startup/update CPU, improved search focus/text, made updater launches invisible, supported cross-drive installs, fixed feed preview during refresh, and improved Odysee/Rumble URL handling and ffmpeg header behavior.

## v1.43.0-v1.47.0 - 2025-12-30
- Improved media support for Rumble/Odysee.
- Added feed finder, gPodder keyword search, unified feed search, and Reddit search.
- Fixed updater install-dir lock handling, config/database preservation on update, and OneDrive update retries.

## v1.42.0-v1.42.10 - 2025-12-28
- Added updater and release automation, debug mode, and update manifest support.
- Improved signing, thumbprint, and hash handling for update manifests and release builds.

## v1.34-v1.41 - 2025-12-20/2025-12-22
- Refactored HTTP handling and added yt-dlp cookie support.
- Added Read and Unread sections and date parsing fixes.
- Improved the build process and Miniflux behavior.

## v1.31-v1.33 - 2025-12-19
- Improved dependency checks, media-tool detection, PyInstaller package collection, and Python version documentation.
- Improved silence-skip and seek handling for remote streams.

## v1.3 - 2025-12-18
- Improved thread safety, UI responsiveness, and error handling.

## v1.21 - 2025-12-16
- Added silence skipping and detection with WebRTC VAD.

## v1.1-v1.2 - 2025-12-04/2025-12-16
- Added the download manager, VLC backend, playback speed, retention options, tray options, unified casting, range-cache proxy, article extraction, and casting improvements.
- Improved config and database portability, date handling, database handling, Miniflux sync, Windows dependency setup, and project documentation.

## v1.01 - 2025-11-30
- Fixed importing.

## v1.0 - 2025-11-30
- Created the initial BlindRSS source, documentation, license, and repository history.
