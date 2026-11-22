# Track Fab reviews and seller discussion comments on Windows

Fab Watch is a free, MIT-licensed desktop app for Fab marketplace sellers. It
checks your public product catalog, written reviews and linked Epic Developer
Community discussions. It also watches Unreal Engine release announcements.

## Install

1. Open [the latest release](https://github.com/stkopp/fab-watch/releases/latest).
2. Download `FabWatchSetup-<version>-x64.exe` from Assets. You do not need the
   source ZIP or Python to use the app.
3. Run setup in your normal Windows account. It installs to
   `%LOCALAPPDATA%\FabWatch` and adds Start menu/desktop shortcuts and startup tasks.
4. Open Fab Watch. A new profile has no seller configured.

Windows x64 is required. The installer is currently unsigned; Windows may display
a publisher/reputation warning. Verify that your download came from this repository.
Do not disable antivirus or Windows security. Release assets include SHA-256 checksums:

```powershell
Get-FileHash .\FabWatchSetup-1.4.0-x64.exe -Algorithm SHA256
```

Compare the result with `SHA256SUMS.txt` from the same release. A checksum detects
corruption; it is not a code-signing certificate or a guarantee of safety.

## Connect a seller

1. Copy your public seller link, such as `https://www.fab.com/sellers/Your%20Name`.
2. Paste it into **Seller URL**, then press **Connect**.
3. Wait for the first catalog and activity scan. Existing messages become silent
   **History** so you are not flooded by old reviews.
4. Use **Settings → Seller and schedule** to change the 60-minute check interval.
   **Check now** scans the seller's catalog and activity, including new products.
5. Use **Activity**, **Products**, and **Unreal Engine** to inspect results.

Your seller replies are excluded using source identity information. The app needs
no Fab password, API token, ChatGPT subscription or always-running AI agent.

## Try notifications

In **Tools**, choose **Test review**, **Test comment**, or **Test engine alert**. These create
local test events; they do not post anything to Fab or Epic. Test events use your
notification policy, so an event configured with notification type **None** is silent.

Press **Remind me later** to postpone. Press **Mark as read** to stop reminders.
Closing a popup does not mark its event read. Read confirmations and snooze
deadlines survive app and Windows restarts. Tests use their own persistent database.

## Keep monitoring

Closing the main window puts it in the tray. Select **Unread activity** from the
tray menu to see new items. A dot on the tray icon means there are unread items. Scheduled checks continue even if
you exit the main UI. Windows must be running and your account signed in; an off
or sleeping PC cannot deliver notifications. **Auto check after PC launch** is
enabled by default and means a sign-in/catch-up check, not a pre-login service.

See [notification settings](NOTIFICATIONS.md), [FAQ](FAQ.md),
[troubleshooting](TROUBLESHOOTING.md), and [updates](UPDATES.md).
