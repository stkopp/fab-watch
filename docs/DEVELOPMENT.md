# Development on Windows

Use Windows x64 and Python 3.11.9 x64 with Tcl/Tk installed. Runtime modules use only
the standard library. The .NET Framework 4 compiler is expected at
`%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe`.

Run PowerShell from this repository:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\build.ps1 -Python (Resolve-Path .\.venv\Scripts\python.exe).Path
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Before building, the package test explicitly skips if the installer is absent.
After building, all tests including the package check must pass without skips.
The suite is Windows-specific and needs an interactive desktop for Tk/native tray
tests. It uses synthetic temporary state and mocks network/task mutation calls.
It does not install the application or modify a real seller's database.

Build products go to `.build/` and `dist/FabWatchSetup-1.3.1-x64.exe`. Both directories
are ignored by Git. You can keep the source directory completely free of products:

```powershell
.\build.ps1 -Python (Resolve-Path .\.venv\Scripts\python.exe).Path -BuildDir C:\Temp\FabWatch-build -OutputDir C:\Temp\FabWatch-dist
$env:FABWATCH_TEST_PACKAGE = 'C:\Temp\FabWatch-dist\FabWatchSetup-1.3.1-x64.exe'
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
Remove-Item Env:\FABWATCH_TEST_PACKAGE
```

Build directories should be dedicated scratch directories: PyInstaller replaces
its previous generated app there. Do not point them at source or user data.

## Manual verification in a disposable Windows account or VM

Running `python app.py` uses the normal local profile and real task names. Use an
isolated account for interactive testing; changing an environment variable alone
is insufficient to isolate Windows tasks and registry registration.

1. Install the built setup in the test account. Check blank Seller URL/no connected
   seller, icons in title/taskbar/tray, Start and desktop shortcuts.
2. Check Ctrl+V, Shift+Insert, Paste and right-click menu in English and another
   keyboard layout. Connect a public test seller; confirm the catalog/history.
3. Refresh, change the interval, sort columns both ways and navigate pages. Verify
   Next update and error details. Do not manufacture reviews on the public site.
4. Press Test review. Close its window and exit the main interface. After ten real
   minutes verify that it returns. Press Mark as read yourself, restart and verify
   that it does not return. Also test a pending reminder across sign-in.
5. Press Test comment and inspect its configured notification and icon. Source failures
   must not erase history or be reported as an empty successful check.
6. Install an update with keep-data selected. Compare history/confirmations. Test
   explicit fresh start and its archive, then uninstall in this test account.

## Troubleshooting

Read logs and Check details first. A pending review is not considered read merely
because Windows accepted a notification. Confirm the relevant scheduled task and
inspect last_review_notice on a disposable database copy when debugging recurrence.
For endpoint changes, reproduce with synthetic fixtures or a separate copied
profile; preserve source completeness checks and stable IDs.

Do not run optional diagnostic CLI calls during normal tests. repairs.py is legacy
compatibility code; its generated prompt still refers to an older monitor.py
command. That instruction is stale and should not be used to reproduce this app.

## Publication checks

Run `python tools/audit_publication.py` before committing a public release. It checks
local state/credentials/machine paths, synthetic code fixtures, local Markdown links
and version consistency. It is a guardrail, not proof that no sensitive data can
exist. The package regression checks the actual installer archive separately.

Windows CI builds before testing so the package regression is not skipped. The
tests briefly create Tk windows/tray icons and do not install the app. Hosted CI
coverage is not a manual clean-Windows installation test. Build/runtime license
notices are collected by tools/package_notices.py. See [releasing](RELEASING.md).
