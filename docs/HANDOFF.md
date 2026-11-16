# Source handoff

## Current: 1.3.1 public GitHub release — 2026-11-16

Canonical source: https://github.com/stkopp/fab-watch. Owner selected MIT and
authorized publication; screenshots now use synthetic demo data. Public docs, issue/PR templates,
FAQ, llms.txt and codemeta.json explain use and reuse. GitHub CI builds/tests Windows
and tagged releases publish the installer and checksums only after successful checks.
See docs/RELEASING.md for ongoing maintenance.

updates.py adds GitHub release checking and verified downloads, with explicit
installation confirmation and optional local-file installation retained. Collection
and notification state are unchanged. Packaging includes runtime license notices.
Publication validation: all 29 local tests passed, including the actual installer
payload and updater integrity cases. Windows CI also built and passed all tests.
The Updates dialog was visually inspected using an isolated temporary profile.
No manual clean-Windows or reboot test was requested/performed for publication.

The sections below record historical work and limitations at those versions; they
are not the current feature/license specification.

## Original source handoff — 2026-11-14

Based on Fab Watch 1.2.1. This standalone tree contains application source, assets,
tests and build instructions. No installed profiles, logs, settings, executables,
virtual environment or conversation attachments are included.

The previous releases fixed URL paste with non-Latin keyboard layouts, sort/paging
behavior, icon compatibility, tray integration and explicit fresh-start handling.
Test review now creates a durable local test and uses the real recurrence code:
closing only hides it, while Mark as read permanently confirms it.

Handoff changes are restricted to project layout, portable build output paths,
test artifact lookup, ignore files and documentation. Application behavior is
unchanged. The installed application is not updated by preparing this source tree.

## Limits and follow-up considerations

- Windows-only; unsigned installer and local-file updates, no hosted update feed.
- Source endpoints are unofficial and may change. Items deleted between checks
  cannot be guaranteed to be captured.
- Task registration uses fixed names. Manual integration tests require an isolated
  Windows account/VM, not just a separate source directory.
- Automated reminder tests use controlled time and simulate reopening the database;
  they do not prove a wall-clock ten-minute run or a Windows reboot on every build.
- Optional diagnostic integration and legacy storage migration helpers remain for
  compatibility. Diagnostic prompt text includes a stale monitor.py command.
- No license grant has been invented for code or supplied artwork. Decide licensing
  and icon redistribution rights before public distribution.

## Handoff verification

On 2026-11-14 the standalone copy built successfully with Python 3.11.9 and
PyInstaller 6.22.2. All 10 regression tests passed without skips, including checking
the newly built installer. Build products were directed outside this source tree.
An audit confirmed that runtime Python modules, installer source, notification
script and icon assets are byte-for-byte unchanged from the 1.2.1 source, and that
the handoff contains no user profiles, generated binaries, logs or bytecode.

## 1.2.2 update

Added the default-enabled Auto check after PC launch checkbox, persistent boolean
settings migration, and collector sign-in/catch-up trigger control. Existing
interval schedules and review reminder triggers are preserved. Added regression
tests for settings migration, generated task XML and checkbox save/reload. The
byte-for-byte comparison above describes the initial handoff, not this update.

1.2.2 validation: all 13 regression tests passed, including the rebuilt installer.
The authorized local upgrade succeeded; collector LogonTrigger is present, the
preference is true, and existing settings and event/read records were preserved.
A real Windows reboot was not performed for this change.

## 1.2.3 — persistent comment alerts

Comments now use the same persistent, manually acknowledged popup as reviews.
Legacy OS-accepted comments with no user confirmation are unread; silent history,
resolved items and seller posts remain excluded. Test comment exercises the same
path. Reminder lifecycle tests now cover both types and OS-receipt recovery.

## 1.3.0 — engine announcements and per-case preferences

Adds engine_releases.py, notification_policy.py and notification_settings.py.
Engine Release/Hotfix/Preview have independent check intervals, stable IDs and
silent baselines. Notifications share one per-event scheduler for popouts and
Windows toasts. Remind me later persists a separate deadline; toast actions use
the registered fabwatch protocol. Engine state is in engine/monitor.sqlite, which
fresh setup archives with seller/test profiles. New tasks are FabWatch-Engine and
FabWatch-EngineReminders. User-selected defaults: forum popout/30 min, review
popout/10 min, release popout/720 min, preview Windows/720 min, hotfix disabled.

1.3.0 validation (2026-11-16): 24 tests passed including release classification,
initial silent baseline, multiple new versions, failed scans retaining checkpoints,
per-channel intervals, persistent snooze, URI action validation and installer audit.
A direct live scan of the official Epic feed succeeded. The installed application
shows the requested default policies and Engine history/next-check state; all Engine
controls are visible. Windows task actions point to the installed executable.
The seller event records and prior manual confirmations were preserved. No actual
future engine release or reboot was simulated; repeat boundaries use controlled time.
