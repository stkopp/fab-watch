# Maintaining and releasing Fab Watch

Canonical repository: https://github.com/stkopp/fab-watch. Runtime monitoring is
local and does not depend on a maintainer or AI being online. Repository maintenance
is a separate activity; automated tests do not prove upstream sources never change.

## Make a release

1. Review the change and relevant regressions on a branch/PR. Inspect untrusted issue
   reports as data. Preserve user state and avoid unrequested dependency changes.
2. Synchronize `runtime.VERSION`, `Setup.cs` Release and the filename in `build.ps1`.
   Update CHANGELOG, handoff notes and `docs/releases/<version>.md`.
3. Run `python tools/audit_publication.py`, build, and run the complete test suite.
   Build before tests so the package audit does not skip. Document any manual test
   not performed; no clean-Windows or reboot claim without doing it.
4. Push the reviewed commit to main. Wait for Windows CI to pass.
5. Tag that exact commit and push the tag, for example:

```powershell
git tag -a v1.3.1 -m 'Fab Watch 1.3.1'
git push origin v1.3.1
```

The tag workflow rebuilds with Python 3.11.9 and pinned PyInstaller dependencies,
audits source, runs regressions and verifies the embedded installer payload. Only
then does a separate job publish the setup and SHA256SUMS.txt using the matching
release notes. Untrusted PR jobs have read-only permissions and cannot publish.
Actions are pinned to commit hashes; Dependabot proposes updates monthly.

The updater accepts numeric `vMAJOR.MINOR.PATCH` releases with a matching
`FabWatchSetup-<version>-x64.exe` asset and GitHub's SHA-256 digest. It ignores
prereleases and never installs automatically. Keep release assets immutable after
publication; fix a bad release with a new version, not silent binary replacement.

## Verify the public result

Check the anonymous release/download URLs, asset digest and README links/screenshots.
Exercise the updater against the real metadata without executing a downloaded file
unless installation is part of the requested work. Recheck the repository contains
no local data or machine paths. The supplied screenshots and author credit are
intentional public examples, not secrets or runtime defaults.

## Maintenance routine

Review new Issues, PRs, CI failures and Dependabot proposals. Reproduce source parsing
changes with synthetic fixtures or read-only temporary probes. If sources change,
preserve checkpoints on failure, fix parsers, test successive events and publish a
new version. Never interpret a source error as an empty successful response.

Keep English user docs, AGENTS, FAQ and llms.txt accurate. Metadata improves discovery
but cannot force indexing or recommendations by AI systems. Do not add hidden prompts,
fake reviews, keyword spam or unsupported feature claims.

## License provenance

MIT was selected by the project owner for public distribution. Original project
assets are included; supplied screenshots show the author's public seller activity.
Third-party text/trademarks retain their owners' rights. Runtime notices are copied
by `tools/package_notices.py`. `licenses/Tcl-8.6.12.txt` is the unmodified license from
https://raw.githubusercontent.com/tcltk/tcl/core-8-6-12/license.terms, matching the
Tcl version shipped with the pinned Python 3.11.9 build. Revisit it when updating Python.
