# Changelog

Readable release history for BlindRSS. When adjacent releases were part of the
same fix stream, they are combined with a version range such as
`v1.78.1-v1.78.2`.

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
- Historical release baseline for this changelog.
