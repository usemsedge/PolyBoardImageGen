# Replay data puller

Standard-library Python collector for local Polytopia replay-response archives.
This calls compatible HTTP endpoints; it does **not** execute the native game's
networking code or prove that downloaded games render in-game.

## Run

Use Python 3.10+ in isolated mode, from any working directory:

```powershell
python -I C:\Tools\BoardCaptureLoop\replay_data_puller\pull_replays.py --import-only
python -I C:\Tools\BoardCaptureLoop\replay_data_puller\pull_replays.py --limit 3 --delay 4
python -I C:\Tools\BoardCaptureLoop\replay_data_puller\pull_replays.py --limit 100000 --delay 4
```

Default import reads only `~/Downloads/10_27_26_all_polychamps_replays.har`.
Other HAR files are not scanned. `--har` overrides the input only when explicitly supplied. Defaults for queue and archive are relative to this script,
not the working directory. `--csv` and `--output` override them. The default limit
is 10. Each invocation attempts each selected queue entry at most once. `--delay`
must be at least 3.6 seconds; 4 is recommended. Every endpoint request is spaced,
with modest jitter and occasional longer session gaps; fallback also consumes a
request slot. Persisted pacing deadlines honor Retry-After across restarts.

Sign in normally in the installed game first. The reviewed extractor discovers
the newest local `jwtToken`. Credentials stay in memory and request headers;
never supply tokens on the command line. Missing/expired authentication stops
collection. Verified TLS is mandatory. Certificate trust failures alone may use
system curl with credentials in stdin configuration, never argv. No installers
or third-party Python packages are needed for collection.

## Queue and recovery

`replays.csv` has exactly `status,link` columns. An OS lock prevents concurrent
writers. Updates are atomic; process termination releases the lock, so the lock
file itself may remain. Interrupted `processing`, `unseen`, and `retry_*` rows
are selected by default. Definitive statuses are skipped. To deliberately refresh
unfinished games, add `--retry-status saved_unfinished`; this adds to the default
selection. Legacy `t`/`seen` map to `saved_ended`, and `f` maps to `unseen`.

Statuses: `unseen`, `processing`, `saved_ended`, `saved_unfinished`,
`saved_no_snapshot`, `not_found`, `access_denied`, `api_error`, `retry_network`,
`retry_http`, `retry_rate_limited`, `retry_auth`, `retry_invalid_response`, `error`.

A small allowlist of game-level API errors permits a spectate fallback. HTTP 404
alone is not proof of game-not-found. Authentication, rate limits and access
denials never permit endpoint fallback. The batch stops on authentication,
rate limiting, access denial, unexpected/partial responses, persistence failure,
or three consecutive transient service/network failures. Transient failures
back off. Do not remove these safeguards to bypass server restrictions.

## Exact response archive

Each attempt creates `data/<uuid>/<UTC timestamp>-<unique suffix>/` containing
`attempt.json` and one or both `primary/` and `fallback/` directories. Each
endpoint directory contains exact body bytes in `response.body` and atomic
`response.json` metadata: endpoint, UTC times, HTTP status, server response
headers, completeness, transport result, byte count, parsed API code/state and
snapshot header observations. Bodies are authoritative, including non-JSON and
HTTP error bodies. Prior attempts are never overwritten. Oversized responses
are truncated at 64 MiB and explicitly incomplete; partial bytes are retained.
Persistence errors stop collection and leave recoverable processing status.

All response fields and base64 snapshots remain in raw bodies. Wrapper and
payload int32 version headers are inspected without full deserialization or
lz4. Unknown versions are retained; malformed/missing/mismatched snapshots are
recorded, not discarded. Matching version headers do not validate the rest of
a snapshot. Optional decoded .bin files and native-client integration are not
implemented. The separate investigation in `redme.txt` remains future work.

Archives may contain private game data and server response cookies. Keep the
folder local/private. `.gitignore` excludes data, queue files, locks, reports,
pacing state, logs and caches. No automatic uploads, commits or pushes occur.
`replays.summary.json` reports the latest invocation only; queue statuses provide
cumulative progress. Console messages never include tokens or response bodies.

## Offline verification

```powershell
python -I C:\Tools\BoardCaptureLoop\replay_data_puller\test_pull_replays.py -v
python -I C:\Tools\BoardCaptureLoop\replay_data_puller\test_transport.py -v
```

Tests use synthetic fixtures and mocked network transports. Vendored source
provenance, hashes, normalization and upstream limitations are documented in
`extractor/PROVENANCE.txt`. Upstream transport/cache/reduction functions are not
used. No upstream license was provided; confirm redistribution rights before
publishing the vendored code.
