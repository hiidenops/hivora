# Security policy

## Reporting a vulnerability

Please report security issues **privately**, through GitHub:
[Report a vulnerability](https://github.com/hiidenops/hivora/security/advisories/new)
(Security tab → *Report a vulnerability*). Do not open a public issue.

Include what you found, how to reproduce it, and the version (Settings → Updates, or
`docker inspect hivora`). You will get an answer in the advisory itself.

## Supported versions

Fixes go into the latest release. Before 1.0, update to the latest version to get them
(see [docs/updating.md](docs/updating.md)).

## What to know when running Hivora

- Hivora controls Docker on its machine, which amounts to root access: protect the panel
  like an administrator account (two-factor authentication, the admin VPN rather than the
  Internet mode).
- Docker bypasses UFW: a port published by Docker is not filtered by the host firewall.
