# Architecture

## Modules

| File | Responsibility |
| --- | --- |
| app.py | English UI, seller connection, background job queue, feed sorting/paging, test actions, CLI modes |
| runtime.py | Settings, per-seller paths, task registration, collection orchestration, persistent test reviews |
| sources.py | Seller resolution, catalog/review pagination, Discourse post retrieval and complete snapshots |
| transport.py | Restricted HTTPS requests, retries, rate-limit cooldowns and structural error reports |
| collector.py | Source-by-source collection and transactional event/checkpoint updates |
| storage.py | SQLite schema, durable events, confirmations, backups and legacy import helpers |
| authors.py | Seller identity comparison and own-message suppression |
| notifications.py / toast.ps1 | Batched Windows notifications, delivery records and error-alert throttling |
| review_reminder.py | Persistent event windows/Windows alerts, configurable recurrence and explicit acknowledgement |
| windows_shell.py | Native tray window, reopen signaling, menu and Explorer restart recovery |
| appearance.py / fab-watch.* | Theme and bundled PNG/ICO resources |
| repairs.py | Incident grouping, local diagnostic files, optional Codex diagnostic subprocess |
| Setup.cs / build.ps1 | Per-user installation, archive-backed fresh start, rollback, shortcuts and packaging |

## Processes and state

The UI is a single instance guarded by window.lock. Network work runs in a worker
thread; Tk updates stay on the UI thread. The native tray queues actions into Tk.
Closing the UI hides it; exiting the interface does not stop scheduled checks.

Task Scheduler runs `--scheduled` for collection, `--reminder` for real reviews,
and `--test-reminder` for local test reviews. Task names are `FabWatch-Check`,
`FabWatch-Reviews` and `FabWatch-TestReviews`. Tasks use the signed-in user's session
so notifications can be displayed. A Run registry entry starts `--tray` at sign-in.
The default collector interval is 60 minutes; review/test tasks repeat every 10.

Production data lives under `%LOCALAPPDATA%\FabWatch`:

- settings.json: connected seller, interval, schedule anchor, optional diagnostic CLI.
- profiles/<seller-id-hash>/monitor.sqlite: independent seller catalogs and checkpoints.
- test-reviews/monitor.sqlite: only local synthetic review tests.
- backups/: profiles archived by explicit fresh setup.
- app/, FabWatchSetup.exe: installed binaries and retained uninstaller.
- logs and incidents: local diagnostic output; never part of a release payload.

SQLite schema version is currently 1. Tables: meta, products, sources, events,
deliveries, incidents. Toast-pending means accepted IS NULL, silent=0, resolved IS NULL.
Reminder-pending additionally includes comments with no confirmed_by_user_at,
even when accepted has a legacy OS receipt; silent/resolved/own events are excluded.
Review confirmation writes accepted and confirmed_by_user_at. Silent history and
seller-authored records never open reminder windows. last_review_notice stores the
event ID and Unix display time; X hides the window without changing acknowledgement.

## Collection contract

Resolve a pasted seller URL, fetch its whole catalog, then fetch listing details,
all written reviews and available linked discussion posts. Stable IDs identify
events; seen IDs and known review records accumulate. Partial failures retain the
last successful source state. New products are picked up on subsequent checks.
Historical timestamps are compared to tracking_started_at for silent backfill.

Events follow per-kind notification policies. OS delivery is recorded separately
from explicit human acknowledgement. Local tests exercise the same reminder path
through a separate database/task, without a Fab request.

## Installer contract

build.ps1 compiles an onedir app, then appends a compressed payload, length, SHA-256
and FABWZIP1 marker to the C# installer. Integrity checks detect corruption; they do
not authenticate a publisher. Releases are unsigned. Updates are downloaded from GitHub with digest verification
or selected from local setup files. Setup validates extraction paths, stages files, switches the app
directory and restores the previous directory on failure. It explicitly assigns
icons to Start/desktop shortcuts and notification registration.

An ordinary update preserves data. Interactive setup detects existing settings and
offers keep/fresh/cancel. `/silent` preserves unless `/fresh` is also supplied.
Fresh mode archives settings, profiles and test-reviews; uninstall retains data.

## Startup preference (1.2.2)

`auto_check_after_launch` is a validated boolean defaulting to true for new and
legacy settings. The UI checkbox saves it and re-registers the collector task
without resetting the existing schedule anchor. Only FabWatch-Check loses its
LogonTrigger and StartWhenAvailable catch-up when disabled. Review/test reminders
and the tray sign-in entry remain independent. Existing recent-run deduplication
still applies to the collector. A connected seller is required for collection.

In 1.2.3 both Test buttons enqueue persistent synthetic events into test-reviews.
The compatibility names confirm_review, awaiting_review and FabWatch-Reviews now
cover comments too. Existing OS receipt timestamps are preserved for audit.

## Engine and notification scheduler (1.3.0)

Engine polling uses a 5-minute Windows task to honor each enabled type's check
interval, so checks can be delayed by up to a worker tick while signed in. It
follows category pages ordered by creation until the checkpoint overlap is
covered (initial baseline: one year). Numeric high-water versions prevent old
bumped topics from alerting. New Preview builds require a versioned announcement
title; changes only inside an existing topic are not new announcements.

The reminder process reloads preferences every tick and routes all enabled pending
events to popout/Windows/none. Delivery times are persisted by event and channel;
OS acceptance does not acknowledge events. Snooze deadlines override repeat timing.
Rating/error events now use this scheduler too. Legacy delivery records remain
for audit. Popup timers use a controlled clock in tests, not wall-clock waiting.

## Public app updates (1.3.1)

updates.py checks the fixed public GitHub repository independently of collection.
The main/tray UI checks daily while running; errors remain errors, not up-to-date
claims. Downloading rechecks metadata, restricts HTTPS redirect hosts, enforces
size bounds and verifies the GitHub SHA-256 digest. Only an explicit user action
executes setup. update-state.json caches availability; it contains no seller data.
