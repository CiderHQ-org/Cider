# Quadra Roblox deployment mirror

The launcher tries Roblox first. An HTTP **403** on the public MacPlayer
version endpoint retries the identical channel on `clientsettings.roblox.com`.
A denied macOS client ZIP retries the identical upload on
`setup-aws.rbxcdn.com`, then `setup-ak.rbxcdn.com`. If those official origins
are also blocked or unreachable, the launcher uses:

`https://vps.korona.lat/quadra/roblox`

Other errors keep their normal behavior. Account, sign-in, game and cookie
requests never use this service. Restricted-channel errors still allow the
launcher's existing recovery from the client's required-update log.

The Python service accepts only these paths (no query parameters):

- `/healthz`
- `/v2/client-version/MacPlayer`, optionally `/channel/CHANNEL`
- `/mac/version-UPLOAD-RobloxPlayer.zip`

Upstream hosts are fixed Roblox HTTPS origins. Cold archive fetches also try
the official AWS/Akamai origins after a primary CDN 403, so the mirror does
not inherit the primary origin's regional denial. Metadata is validated and
cached for 60 seconds. ZIPs are downloaded completely into a temporary file,
checked for length and ZIP structure, then renamed into an immutable cache.
The launcher checks the ZIP, embedded version when supplied, and extraction
before replacing its current client. Interrupted transfers leave the
installed client in place.

The service listens only on `127.0.0.1:9473`. It allows 16 active requests,
two archive fetches, 512 MiB per archive and a 2 GiB completed archive cache.
It has no third-party Python dependencies. The supplied systemd unit uses a
dynamic user and a private cache at `/var/cache/quadra-roblox`.

## Deployment on korona

Install `server.py` as `/opt/quadra-downloads/server.py`, the unit as
`/etc/systemd/system/quadra-roblox-mirror.service`, and `route.caddy` as
`/etc/caddy/quadra-downloads.caddy`. Import the route inside the existing
`https://` block, ahead of its catchall handler:

```caddy
import /etc/caddy/quadra-downloads.caddy
```

Back up `/etc/caddy/Caddyfile`, validate a candidate configuration with
`caddy validate --adapter caddyfile --config CANDIDATE`, then enable/start
the service and reload Caddy. Check the public `/healthz` and version paths.
The deployed configuration preserves the other hosted applications.

For an update, replace the service script and restart only
`quadra-roblox-mirror.service`. Do not publish an incomplete `.part` file or
turn this route into a general URL proxy. No launcher authentication is
required because all supplied data is public Roblox deployment data.

## Validation

`tests/roblox_downloads_test.py` checks primary-first behavior, 403-only retry,
official-origin and mirror recovery, path restrictions, deployment validation
and interrupted download cleanup.
`tests/roblox_mirror_test.py` checks upstream validation, immutable cache reuse,
truncated/invalid ZIP rejection and the HTTP path contract with fake upstreams.
Run both with disposable XDG directories, as in `tests/run.sh`.
