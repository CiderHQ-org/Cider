# Quadra website and report hosting

The website runs on korona behind Caddy. Public website files live in this
repository under `website/dist/`. Private report-service code and configuration
are deployed separately; `/services/` is ignored by Git. Previously tracked
mirror files remain tracked.

## Deployment

A signed GitHub push webhook at
`https://vps.korona.lat/quadra/site-hook` queues a deployment for
`CiderHQ-org/Cider`, branch `main`. The receiver verifies the SHA-256 HMAC and
the repository and branch before accepting it. The secret is stored only in
`/etc/quadra-reports.env` and the GitHub hook configuration.

`quadra-site-sync.path` starts `quadra-site-sync.service` after a valid push.
`quadra-site-sync.timer` also checks every minute so missed deliveries recover.
The sync service fetches the trusted main branch, prepares static files in a
new release directory, and atomically switches `/var/www/quadrahq/current`.
It copies the root `install.sh` over the site's installer copy. It never runs
repository build scripts or changes private report data. An invalid deployment
leaves the preceding site in place; the five newest static releases are kept.

The deployed commit is visible at `/deployment.json`. To inspect or retry:

```sh
systemctl status quadra-site-sync.path quadra-site-sync.timer
journalctl -u quadra-site-sync.service -n 30 --no-pager
systemctl start quadra-site-sync.service
```

Vercel Git deployments are disabled in `vercel.json`. The old deployment can
continue serving until DNS is changed; new commits deploy to the VPS.

## DNS and HTTPS

For the korona host used by this deployment:

| Record | Name | Value |
| --- | --- | --- |
| A | `@` | `23.164.52.24` |
| CNAME | `www` | `quadrahq.org` |

Replace the root's Vercel A records and the `www` Vercel CNAME. Do not retain
an AAAA record pointing to the old host. Caddy manages HTTPS on demand for
these exact hostnames and redirects `www` to the root domain. Before cutover,
the same static files and API routes can be checked locally on the VPS at
`http://127.0.0.1:9481/`. The API's configured browser origin remains
`https://quadrahq.org`.

Caddy imports `/etc/caddy/quadra-site.caddy` at top level and
`/etc/caddy/quadra-site-hook.caddy` inside its existing HTTPS catchall. Reload
the running Caddy through its admin endpoint after validating a candidate
configuration; korona's main Caddy process is managed by PM2.

## Reports and Discord

The `/report/` page explains the full collection sequence and posts directly
to the VPS. The service checks the actual gzip/tar contents and requires both
`diagnostic_signals: true` and `allow_debugger: true` in `settings.json`.
It also requires a launch log for reports other than setup/download failures.
These checks inspect saved settings; users must still enable the switches
before the failing launch and collect the matching run.

The archive limit is 8 MiB compressed and 64 MiB expanded. Links, traversal,
duplicate filenames and oversized members are rejected. Validation alone does
not store a report. Submission requires the description, reproduction steps,
issue type, a verified archive and the sharing acknowledgement. Repeating the
same submission key returns the existing report rather than creating a second.

Reports are stored privately under `/var/lib/quadra-reports/`:

| Path | Contents |
| --- | --- |
| `reports.sqlite3` | Report index, delivery state and retry information |
| `reports/REPORT_ID/diagnostics.tar.gz` | Original validated archive |
| `reports/REPORT_ID/launch.log` | Recent launch log, setup error or summary |
| `reports/REPORT_ID/report.json` | Complete description, steps and contact details |

There is no public report-listing or file-download endpoint. The bot sends
the archive, log and description to the configured Discord channel and pings
only the configured maintainer. The Discord sender uses the bot REST API;
it needs View Channel, Send Messages and Attach Files permissions, without
privileged message-content intents. Delivery failures stay queued on disk;
rate limits honor Discord's retry delay. Archive storage is capped at 5 GiB
without automatically deleting existing reports.

Set `DISCORD_BOT_TOKEN` in the root-owned, mode-0600 file
`/etc/quadra-reports.env`. Channel and mention IDs are configured there too.
`quadra-reports-config.path` restarts the service when this file changes.
Tokens do not belong in Git or chat. To inspect reports over SSH:

```sh
python3 /opt/quadra-reports/server.py list
python3 /opt/quadra-reports/server.py show REPORT_ID
journalctl -u quadra-reports.service -n 30 --no-pager
```

The private source, deployment units and tests are installed in
`/opt/quadra-reports/`. Run the service tests without sending real messages:

```sh
python3 -m unittest discover -s /opt/quadra-reports/tests -p 'test_*.py'
```
