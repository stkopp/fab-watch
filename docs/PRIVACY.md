# Privacy and local data

Fab Watch does not require an account, Fab credentials, telemetry consent, an AI
subscription or a hosted database. It fetches public seller/catalog/review data
from `www.fab.com` and public discussion/announcement JSON from
`forums.unrealengine.com`. GitHub receives normal HTTPS requests for app release
metadata and installer downloads. These services see normal connection information
such as your IP address; Fab Watch does not control their logging.

Local data is in `%LOCALAPPDATA%\FabWatch`:

- `settings.json`: connected seller and preferences.
- `profiles/<hash>/monitor.sqlite`: catalog, source checkpoints, reviews/comments,
  read confirmations and snoozes for each connected seller.
- `engine/monitor.sqlite`: engine announcement history and checkpoints.
- `test-reviews/monitor.sqlite`: local synthetic notification tests.
- `update-state.json` and `updates/`: app version-check cache and downloaded installers.
- Logs, incident reports and backups: troubleshooting and explicit fresh-start archives.

No profile/database/log is included in release packages. Documentation screenshots use
synthetic examples, not factory settings. Updating preserves your local data.
Uninstalling leaves it available for reinstallation. Setup's explicit fresh-start
option first archives existing profiles. Remove local data/backups yourself only
if you intend to discard all history and confirmations.

Source includes optional legacy diagnostic CLI integration in `repairs.py`.
It is not configured or enabled by the standard installation. Enabling it manually
can send diagnostic content to the configured external CLI; review that code and
the CLI's settings before doing so. Normal monitoring does not invoke it.

Before attaching diagnostic logs to an issue, inspect them for paths, message text
and other content you do not want to publish. Never attach credentials or your full
profile database. Synthetic reproductions are preferred.
