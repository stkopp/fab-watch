# Troubleshooting Fab Watch

## No popup appeared

1. Check the event's status. **History**, **Seller** and **Read** are intentionally
   silent. An unread item may be snoozed or waiting for its repeat deadline.
2. Open **Settings → Notifications**. Confirm the event has a channel other than None.
   Check interval and reminder interval have different meanings.
3. Choose the matching test in **Tools**. Tests follow the same policy as real events.
4. For Windows notifications, check Windows Settings, notification permissions and
   Do Not Disturb. Try Popout if you need a dedicated reminder window.
5. In Windows Task Scheduler, inspect `FabWatch-Check`, `FabWatch-Reviews`,
   `FabWatch-Engine`, `FabWatch-EngineReminders` and, after a test, `FabWatch-TestReviews`.
   They should point to your installed FabWatch.exe. They run in your signed-in session.

Do not delete databases to fix notifications. That destroys the evidence needed to
diagnose missed alerts and may reset a baseline. Closing an alert is not acknowledgement.

## Fab or Epic could not be checked

Open **Tools → Check details** for seller errors or read the Unreal Engine tab's status.
Confirm the source opens in your browser, then try again later. HTTP throttling,
temporary outages or changed response formats can prevent a complete scan.
Fab Watch retains the last successful checkpoint when this happens.

If the problem repeats, check **Tools → App updates…** and the repository's existing issues.
If the status says the source could not be reached, the next check will retry it.
For source format failures you can enable automatic public issues under
**Settings → GitHub issue reports**. Sign into GitHub CLI first, then choose
`gh.exe` in the dialog. See [what reports include](PRIVACY.md).
Report the app version, Windows version, event type, error text and a public source
URL if appropriate. Do not share tokens, cookies or complete local databases.

## My URL won't connect

Use a public seller URL, not a single listing URL. Try the Paste button or Ctrl+V.
The URL field is an input for connecting a profile; use the seller heading/catalog
to see the current connection. Do not reset the profile just because the input is empty.

## A new Engine version did not alert

Enable the appropriate engine type. Existing versions discovered on the first
successful scan are silent history. The detector requires recognizable versioned
announcement titles and increasing versions; an edit inside an old thread may not
count. Use **Check engine now** and inspect the displayed source error/last-check time.

## Updates fail

The GitHub API can be unavailable or rate-limited. Try again later, or download the
setup manually from [Releases](https://github.com/stkopp/fab-watch/releases).
Use **Updates… → Install local file…**. If checksum validation fails, do not execute
that file. A local package checksum detects damage but does not authenticate its author.

## Windows warns about the publisher

Releases are currently unsigned. Verify the repository, release and checksum;
do not turn off security protections. Report unexpected detections with their exact
name/version, without assuming every detection is a false positive.

## Recovery and removal

Reinstalling with **keep profile** preserves data and reconfigures tasks. Explicit
fresh setup archives the old profile before clearing it. Uninstall through Windows
Installed apps; user data is retained. See [privacy](PRIVACY.md) for its location.
