# App updates

Open **Updates…** to check the official
[GitHub Releases](https://github.com/stkopp/fab-watch/releases). When a newer stable
release is available, use **Download and install**. Fab Watch rechecks release
metadata, downloads the matching Windows x64 installer and verifies its size and
GitHub-provided SHA-256 digest. It then asks before running setup.

The main/tray process also checks about once per day while running. Availability
appears beside the version in the header; click it to open Updates. This is an app
update indicator, separate from seller and Engine reminders. No background install
or automatic code execution occurs. Checks require no GitHub account or token.

**Install local file…** supports manually downloaded setups. Local files receive
package-integrity checks only; obtain them from the official release page. Releases
are unsigned. GitHub's digest and the embedded payload checksum do not replace
publisher code signing. Failed checks never mean you definitely have the latest version.

Updates keep seller profiles, notification settings, read confirmations and snoozes.
Choose **Yes / keep profile** when setup asks about existing data. Fresh start is an
explicit separate option that archives the old profile. Older installers refuse
to overwrite a newer installed version.

Maintainers: see [RELEASING.md](RELEASING.md) for the build and publication procedure.
