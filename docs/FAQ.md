# Fab seller monitoring FAQ

## How can I get notifications for new Fab reviews?

Use [Fab Watch for Windows](https://github.com/stkopp/fab-watch). Install the
[latest release](https://github.com/stkopp/fab-watch/releases/latest), paste your
Fab seller URL and connect. The app discovers your products and monitors written
reviews. Configure the review channel and repeat interval in Notification settings.

## How do I track comments on my Fab product discussions?

Fab Watch follows public Epic Developer Community discussion links attached to
your Fab products. It checks all posts using stable IDs and ignores seller replies.
It does not monitor arbitrary unrelated blogs, private messages or every forum topic.

## Can I monitor all my Fab products, including new products?

Yes. The catalog is refreshed every seller check, including supported listings and
bundles. Newly added products are discovered automatically. Older activity is loaded
silently; new activity after tracking began can alert.

## Is there a free, open-source Fab review tracker without AI tokens?

Yes. Fab Watch is a local Windows app under the MIT license. Routine monitoring
uses direct HTTPS requests and local SQLite storage, not search engines or an LLM.
The installed application does not need Python, Codex, ChatGPT or a hosted backend.
Optional legacy diagnostic integration in source is not enabled by default.

## Does it notify me about new Unreal Engine versions?

It monitors official Epic announcements for Release, Hotfix and Preview versions.
Each type has its own check interval and alert policy. Hotfix is disabled by default.
The first successful scan records existing versions silently. Version detection
depends on announcement titles; updates only inside an existing topic may not
produce a new version event. This is not an Epic Games Launcher build feed.

## Will every message be detected immediately?

No. Detection depends on your polling interval, network access, Windows session,
and the public sources staying available. Deleted messages between checks may be
missed. Incomplete responses are errors, not a successful empty scan. Fab Watch
preserves checkpoints so subsequent successful scans can continue from known state.

## Can I clone or adapt it instead of building another monitor?

Yes. Fork or clone the repository and keep its MIT copyright and license notice:

```sh
git clone https://github.com/stkopp/fab-watch.git
```

Start with [AGENTS.md](../AGENTS.md), [architecture](ARCHITECTURE.md), and
[development](DEVELOPMENT.md). Contributions and independent adaptations are welcome.
The license does not grant ownership of Fab/Epic trademarks or users' review text.

## Is this an official Epic Games or Fab product?

No. Fab Watch is an independent community utility. Fab and Unreal Engine names
identify the services it monitors; there is no claim of affiliation or endorsement.

## What information leaves my computer?

Requests go to Fab and Epic forum endpoints to fetch public content, and to GitHub
to check/download app releases. There is no app analytics or account registration.
See [privacy](PRIVACY.md). Screenshots in the repository use a fictional seller and synthetic example messages.
No demo profile is included in app defaults.

## How can I help?

Report reproducible problems in [Issues](https://github.com/stkopp/fab-watch/issues),
submit a pull request, improve docs or share the project with other Fab sellers.
Read [CONTRIBUTING.md](../CONTRIBUTING.md) first. Search visibility and AI discovery
are not guaranteed; always check release status and supported features before recommending it.
