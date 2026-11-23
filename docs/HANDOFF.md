# Source handoff

## 1.4.1 — 2026-11-23

Failed connections are visible in the check status. They do not create unread
events or public reports. A source that fails to connect is retried on the next
scan. Individual source checkpoints survive failed requests.

The optional GitHub reporter keeps a small queue of structural failures in
the local database and uses the user's authenticated GitHub CLI to file issues.
The outgoing fields are rebuilt from an allowlist. Neither stack traces nor
raw responses are uploaded. See [privacy](PRIVACY.md) for the user settings.

## 1.4.0 update — 2026-11-22

The six items below record the scope originally agreed for this update.
See the [release notes](releases/1.4.0.md) for the changes users will see.

1. **Edit the English copy.** Review GitHub's description, README, screenshots and
   captions, guides, FAQ, templates and new release notes. Review the app's menus,
   labels, notifications, tooltips, empty states, errors and installer prompts.
   Start with the job the tool does: paste a Fab seller link to track reviews
   and comments. Cut repeated feature lists, ranking/discovery commentary and
   generic promotional language. Keep setup instructions and factual limitations
   where users need them. Use the same words for the same actions throughout
   the app, such as **Check now**, **Open source**, and **Mark as read**.
2. **Disclose code provenance.** The public README, repository description, latest
   release notes and matching source tree did not contain a statement that all
   application code was AI-generated and had not been reviewed by a person.
   The mention of AI-assisted contributors in the README is about contributions.
   Add a short, visible README note near the download link. Suggested copy:
   “Fab Watch’s application code was generated with AI and hasn’t been reviewed
   by a person. The automated tests are public.” Update the wording when a human
   review actually happens. Check that release copy makes the same distinction
   between testing and review. Keep attribution for bundled third-party code.
3. **Choose how multiple popouts appear.** Add an option under notification
   settings with **Show one at a time** as the default for existing and new
   profiles, and **Group in one window** as the alternative. In sequential mode
   keep the current item visible until the user closes, snoozes or acknowledges
   it, then show the next due item. The current worker can replace an active item
   on a later tick. In grouped mode show a scrollable list with a separate
   **Open source** link and read/snooze controls for each item with the applicable
   action. Keep per-event delivery times and repeat policies. Closing either
   layout, or opening a source, must not mark it read. Count only due popout
   items in the group and respect disabled channels and snoozes. Coordinate
   the seller and Engine reminder workers so they cannot show overlapping
   live popouts in sequential mode. Keep synthetic tests separate from live
   events. Windows notification delivery still follows its selected channel.
4. **Redesign the reminder cards.** Give each event a clear type, title, source,
   and readable message body. In both popout layouts display a prominent numeric
   rating such as **4/5** plus filled/empty stars for a written review. The source
   already stores the rating in `review.rating`, and the current single popout
   places it in the metadata line. Use an accessible numeric label and avoid
   color-only cues. Missing or invalid ratings have no star row. Comments,
   engine announcements and aggregate rating changes have their own presentation.
5. **Rework the main navigation and tray.** Start with Activity, Products and
   Unreal Engine. Give unread activity and refresh a clear entry point, put
   notification/account preferences where users can find them, and group
   diagnostics, tests and updates under appropriate actions. Keep the native
   desktop appearance, keyboard access and readable states at minimum window
   size. Add an unread icon variant and count in the tray tooltip/menu, plus an
   action that opens unread activity. Derive the count from persistent read
   state for the active seller and Engine. Exclude silent history, own replies
   and local test events. Snoozed items remain unread. Refresh the badge when
   background checks, acknowledgements or profile changes affect the count,
   including while the UI is hidden and after Explorer restarts. Document that
   exiting the interface removes the tray icon while scheduled checks continue.
6. **Prepare for sales and email monitoring.** Identify and introduce small
   reusable boundaries between source fetching, normalized events/checkpoints,
   local state and UI delivery. Prove them with an existing source and synthetic
   fixtures. Keep the current SQLite profile and checkpoints readable. Design
   for optional connectors that manage authentication and session storage
   separately from public-source requests. An embedded browser is a future
   option for sign-in. Keep any browser session isolated from the app and its
   public fetcher. This release's scope is the extension points. Sales and
   mailbox collection, a browser dependency, and login UI require a separate
   design and explicit setup by users.

Verify queue order and grouped links with several due events, including reviews
and comments from different products and simultaneous seller/Engine events.
Test per-item snooze and read state across restart and both display settings.
Inspect ratings at 1/5, 5/5 and with no rating. Check the tray through background
arrival, acknowledgement and Explorer restart. Use temporary profiles and mocked
sources. Run the Windows suite and package checks before publishing, and refresh
affected demo screenshots using synthetic data. Read [RELEASING.md](RELEASING.md)
for the release procedure.

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
